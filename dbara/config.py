from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    mode: str
    app_name: str
    app_folder_dir: Path
    backup_dest_dir: Path
    restore_dest_dir: Path | None
    remove_after_backup: bool
    start_container: bool
    all_apps: bool
    force: bool
    strict: bool
    skip_checksum: bool
    compressor: str
    zstd_opts: str
    fast_hash: bool
    io_nice: bool
    keep_last: int
    state_dir: Path
    hooks_dir: Path
    lock_dir: Path
    ownership_map_file: Path | None
    owner_group: str
    optional_prefix: str
    stop_timeout: int
    retry_max: int
    retry_base_sleep: int
    verbosity: int
    logfile: Path
    app_names: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.mode not in ("backup", "restore"):
            raise ValueError(f"Invalid mode {self.mode!r}. Must be 'backup' or 'restore'.")
        if self.compressor not in ("zstd", "gzip"):
            raise ValueError(f"Invalid compressor {self.compressor!r}. Must be 'zstd' or 'gzip'.")
        if self.keep_last < 0:
            raise ValueError(f"--keep-last must be >= 0, got {self.keep_last}.")
        if self.stop_timeout <= 0:
            raise ValueError(f"--stop-timeout must be > 0, got {self.stop_timeout}.")
        if self.retry_max < 1:
            raise ValueError(f"--retry-max must be >= 1, got {self.retry_max}.")
        if self.retry_base_sleep < 1:
            raise ValueError(f"--retry-base-sleep must be >= 1, got {self.retry_base_sleep}.")
        if self.mode == "restore":
            has_app = bool(self.app_name or self.app_names or self.all_apps)
            if not has_app:
                raise ValueError(
                    "Restore mode requires --app-name (-a), --apps, or --all-apps (-A)."
                )
            if self.restore_dest_dir is None:
                raise ValueError("Restore mode requires --restore-dest-dir (-r).")
        if self.mode == "backup" and not self.all_apps and not self.app_name:
            raise ValueError("Backup mode requires --app-name (-a) unless --all-apps is set.")


def parse_ownership_map(map_file: Path, app: str) -> str | None:
    """Return 'user:group' for app from an ownership map file, or None if not found."""
    for line in map_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        if key.strip() == app and val.strip():
            return val.strip()
    return None
