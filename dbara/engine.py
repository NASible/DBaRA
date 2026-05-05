from __future__ import annotations

import shutil
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dbara.archive import (
    build_archive_name,
    list_apps_in_backup_dir,
    prune_old_backups,
    select_newest_archive,
)
from dbara.checksum import create_checksum_file, signature_of_dir, verify_checksum_file
from dbara.config import Config, parse_ownership_map
from dbara.docker_ops import DockerClient
from dbara.hooks import run_hook
from dbara.locks import LockError, app_lock
from dbara.log import Logger
from dbara.runner import CommandRunner
from dbara.sqlite_backup import cleanup_sqlite_sidecars, sqlite_safe_backup


def _compress_args(config: Config, runner: CommandRunner) -> list[str]:
    """Return the tar compression flag list for the configured compressor."""
    if config.compressor == "zstd":
        return ["-I", f"zstd {config.zstd_opts}"]
    # gzip: prefer pigz for multi-threading
    if runner.tool_available("pigz"):
        return ["--use-compress-program", "pigz -11 -p 0"]
    return ["-z"]


def _decompress_args(backup_file: Path, runner: CommandRunner) -> list[str]:
    """Return the tar decompression flag list inferred from the archive extension."""
    name = backup_file.name
    if name.endswith(".zst"):
        return ["-I", "zstd"]
    if name.endswith((".tgz", ".gz")):
        if runner.tool_available("pigz"):
            return ["--use-compress-program", "pigz -p 0"]
        return ["-z"]
    return []


class BackupEngine:
    def __init__(
        self,
        config: Config,
        runner: CommandRunner,
        docker: DockerClient,
        logger: Logger,
    ) -> None:
        self._config = config
        self._runner = runner
        self._docker = docker
        self._logger = logger

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def backup_single_app(self, app: str) -> None:
        config = self._config
        app_path = config.app_folder_dir / app

        try:
            with app_lock(app, config.lock_dir):
                self._do_backup(app, app_path)
        except LockError as exc:
            self._logger.fatal(str(exc))

    def backup_all_apps(self) -> None:
        config = self._config
        self._logger.info(f"Backing up all apps found in {config.app_folder_dir}...")
        try:
            entries = sorted(config.app_folder_dir.iterdir())
        except OSError as exc:
            self._logger.fatal(f"Cannot read app folder {config.app_folder_dir}: {exc}")

        for entry in entries:
            if entry.is_symlink() and not entry.exists():
                self._logger.warn(f"Broken symlink found: {entry.name}, skipping.")
                continue
            if not entry.is_dir():
                self._logger.warn(f"Unexpected non-directory: {entry.name}, skipping.")
                continue

            app = entry.name
            app_path = config.app_folder_dir / app

            # Check for changes BEFORE stopping the container so we don't cause
            # unnecessary downtime when nothing has changed.
            if self._is_unchanged(app, app_path):
                self._logger.info(
                    f"No changes detected for {app!r} since last backup. Skipping."
                )
                continue

            container_exists = self._docker.container_exists(app)
            was_running = container_exists and self._docker.container_running(app)

            if container_exists:
                if was_running:
                    self._docker.stop(app)
                else:
                    self._logger.info(
                        f"Container {app!r} exists but was not running; proceeding."
                    )
            else:
                self._logger.info(
                    f"No container named {app!r}; proceeding with filesystem backup only."
                )

            self.backup_single_app(app)

            if container_exists and was_running:
                self._docker.start(app)
            else:
                self._logger.info(
                    f"Not starting {app!r} "
                    "(container didn't exist or wasn't running before)."
                )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_unchanged(self, app: str, app_path: Path) -> bool:
        """Read-only change check — does NOT update the sig file."""
        if self._config.force or not app_path.is_dir():
            return False
        state_file = self._config.state_dir / f"{app}.sig"
        if not state_file.is_file():
            return False
        return state_file.read_text().strip() == signature_of_dir(app_path)

    def _should_skip(self, app: str, app_path: Path) -> bool:
        """Read-only check used inside _do_backup. Never writes the sig file."""
        if self._config.force:
            self._logger.info(f"Force backup: ignoring change detection for {app!r}.")
            return False
        state_file = self._config.state_dir / f"{app}.sig"
        current_sig = signature_of_dir(app_path)
        if state_file.is_file() and state_file.read_text().strip() == current_sig:
            self._logger.info(
                f"No changes detected for {app!r} since last backup. Skipping."
            )
            return True
        return False

    def _record_sig(self, app: str, app_path: Path) -> None:
        """Write the change-detection sig. Called only after a successful backup."""
        state_file = self._config.state_dir / f"{app}.sig"
        state_file.write_text(signature_of_dir(app_path))

    def _do_backup(self, app: str, app_path: Path) -> None:
        config = self._config

        if not app_path.is_dir():
            self._logger.warn(
                f"App folder {app_path} does not exist or is not a directory, skipping."
            )
            return

        if self._should_skip(app, app_path):
            return

        hostname = socket.gethostname().split(".")[0]
        archive_name = build_archive_name(
            app,
            config.compressor,
            config.optional_prefix,
            hostname,
            datetime.now(),
        )
        backup_path = config.backup_dest_dir / archive_name
        try:
            config.backup_dest_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            self._logger.fatal(
                f"Cannot create backup destination {config.backup_dest_dir}: {exc}. "
                f"Check directory permissions or use a different --backup-dest-dir."
            )

        run_hook(app, "pre-backup", config.hooks_dir, self._runner, self._logger)
        sqlite_safe_backup(app_path, self._logger)

        tar_cmd = [
            "tar",
            "--one-file-system",
            "--numeric-owner",
            "-cf", str(backup_path),
            "-C", str(config.app_folder_dir),
            app,
        ] + _compress_args(config, self._runner)

        self._logger.info(f"Backing up {app!r} -> {backup_path}")
        try:
            self._runner.run_io_niced(tar_cmd)
        except subprocess.CalledProcessError as exc:
            self._logger.fatal(
                f"Backup failed for {app!r}: tar exited with code {exc.returncode}. "
                f"Verify that {config.backup_dest_dir} is writable and has sufficient space."
            )

        # Archive written successfully — record the sig now so a failed backup
        # never causes the next run to skip when no archive actually exists.
        self._record_sig(app, app_path)

        cleanup_sqlite_sidecars(app_path, self._logger)

        if not config.skip_checksum:
            create_checksum_file(
                app, backup_path, config.app_folder_dir,
                self._runner, self._logger, config.fast_hash,
            )
        else:
            self._logger.info("Checksum generation skipped.")

        self._logger.info(f"Backup complete for {app!r} at {backup_path}")
        run_hook(app, "post-backup", config.hooks_dir, self._runner, self._logger)

        if config.remove_after_backup:
            self._verify_archive_integrity(backup_path, app_path)
            self._logger.warn(
                f"Removing app directory {app_path} after backup (archive verified)."
            )
            shutil.rmtree(app_path)

        prune_old_backups(config.backup_dest_dir, app, config.keep_last, self._logger)

    def _verify_archive_integrity(self, backup_path: Path, app_path: Path) -> None:
        self._logger.info("Verifying archive integrity before removal...")
        verify_cmd = ["tar"] + _decompress_args(backup_path, self._runner)
        verify_cmd += ["-tf", str(backup_path)]
        try:
            self._runner.run_io_niced(verify_cmd)
        except Exception as exc:
            self._logger.fatal(
                f"Archive integrity check failed — NOT removing {app_path}. ({exc})"
            )


class RestoreEngine:
    def __init__(
        self,
        config: Config,
        runner: CommandRunner,
        docker: DockerClient,
        logger: Logger,
    ) -> None:
        self._config = config
        self._runner = runner
        self._docker = docker
        self._logger = logger

    def restore_app(self) -> None:
        self._restore_one(self._config.app_name)

    def restore_apps(self, apps: list[str]) -> None:
        """Restore each app in the provided list sequentially."""
        self._logger.info(f"Restoring {len(apps)} app(s): {', '.join(apps)}")
        for app in apps:
            self._logger.info(f"--- Restoring {app!r} ---")
            self._restore_one(app)

    def restore_all_apps(self) -> None:
        """Auto-discover app names from backup_dest_dir and restore each."""
        apps = list_apps_in_backup_dir(self._config.backup_dest_dir)
        if not apps:
            self._logger.warn(
                f"No backup archives found in {self._config.backup_dest_dir}."
            )
            return
        self.restore_apps(apps)

    def _restore_one(self, app: str) -> None:
        config = self._config

        # Resolve ownership: CLI flag > ownership map file
        owner_group = config.owner_group
        if not owner_group and config.ownership_map_file:
            if not config.ownership_map_file.is_file():
                self._logger.fatal(
                    f"Ownership map file not found: {config.ownership_map_file}"
                )
            mapped = parse_ownership_map(config.ownership_map_file, app)
            if mapped:
                owner_group = mapped
                self._logger.info(f"Ownership map: {app!r} -> {owner_group}")

        # --- 1) Locate backup file before any downtime ---
        backup_file = self._resolve_backup_file(app, config.backup_dest_dir)
        self._logger.info(f"Selected backup file: {backup_file}")

        # --- 2) Detect container state (no side effects yet) ---
        container_exists = self._docker.container_exists(app)
        was_running = container_exists and self._docker.container_running(app)

        # --- 3) Stop if needed ---
        if container_exists and was_running:
            self._docker.stop(app)
        elif not container_exists:
            self._logger.info(
                f"No container named {app!r}; proceeding with filesystem restore only."
            )
        else:
            self._logger.info(
                f"Container {app!r} exists but is not running; proceeding without stop."
            )

        # --- 4) Prepare destination and pre-restore hook ---
        assert config.restore_dest_dir is not None
        restore_path = config.restore_dest_dir / app
        restore_path.mkdir(parents=True, exist_ok=True)
        run_hook(app, "pre-restore", config.hooks_dir, self._runner, self._logger)

        # --- 5) Extract ---
        tar_cmd = (
            ["tar"]
            + _decompress_args(backup_file, self._runner)
            + [
                "-xf", str(backup_file),
                "-C", str(restore_path),
                "--strip-components=1",
                "--overwrite",
            ]
        )
        self._runner.run_io_niced(tar_cmd)

        # --- 6) Ownership ---
        if owner_group:
            self._logger.info(f"Setting ownership to {owner_group!r}...")
            self._runner.run(["chown", "-R", owner_group, str(restore_path)])

        # --- 7) Verify ---
        self._verify_restore(backup_file, restore_path)

        # --- 8) Post-restore hook and conditional restart ---
        run_hook(app, "post-restore", config.hooks_dir, self._runner, self._logger)

        if config.start_container and container_exists and was_running:
            self._docker.start(app)
        else:
            self._logger.info(
                f"Not starting {app!r} "
                "(container didn't exist, wasn't running before, or start disabled)."
            )

    def _resolve_backup_file(self, app: str, backup_dest: Path) -> Path:
        if backup_dest.is_file():
            if app not in backup_dest.name:
                self._logger.fatal(
                    f"Sanity check failed: file {backup_dest.name!r} "
                    f"does not match app {app!r}."
                )
            return backup_dest
        if backup_dest.is_dir():
            found = select_newest_archive(backup_dest, app)
            if found is None:
                self._logger.fatal(
                    f"No valid archive found for {app!r} in {backup_dest}."
                )
            return found
        self._logger.fatal(
            f"Backup destination {backup_dest!r} is not a valid file or directory."
        )

    def _verify_restore(self, backup_file: Path, restore_path: Path) -> None:
        self._logger.info("Verifying restored data...")
        if not restore_path.is_dir():
            self._logger.fatal(f"Restored directory {restore_path} missing!")
        if not any(restore_path.rglob("*")):
            self._logger.fatal(f"Restored directory {restore_path} is empty!")

        # List archive contents and check each path exists
        list_cmd = (
            ["tar"] + _decompress_args(backup_file, self._runner) + ["-tf", str(backup_file)]
        )
        try:
            result = self._runner.run(list_cmd, capture_output=True)
        except Exception as exc:
            self._logger.warn(f"Could not list archive contents for verification: {exc}")
            return

        entries = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        total = len(entries)
        checked = 0
        for entry in entries:
            # Strip top-level component (mirrors --strip-components=1)
            parts = entry.split("/", 1)
            relative = parts[1] if len(parts) > 1 else ""
            if not relative or relative.endswith("/"):
                checked += 1
                _progress(checked, total)
                continue
            if not (restore_path / relative).exists():
                self._logger.warn(f"Missing file after restore: {relative}")
            checked += 1
            _progress(checked, total)

        print()  # newline after progress bar

        if not self._config.skip_checksum:
            xxh_path = Path(str(backup_file) + ".xxh128")
            sha_path = Path(str(backup_file) + ".sha256sum")
            checksum_file = xxh_path if xxh_path.is_file() else sha_path
            verify_checksum_file(
                restore_path, checksum_file,
                self._runner, self._logger, self._config.fast_hash,
            )
        else:
            self._logger.info("Checksum verification skipped.")

        self._logger.info("Restore verification complete.")


def _progress(current: int, total: int, width: int = 50) -> None:
    if total == 0:
        return
    filled = current * width // total
    bar = "#" * filled + "-" * (width - filled)
    pct = current * 100 // total
    sys.stdout.write(f"\r[{bar}] {pct:3d}%")
    sys.stdout.flush()
