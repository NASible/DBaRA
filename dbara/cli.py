from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from dbara import __version__
from dbara.config import Config
from dbara.docker_ops import DockerClient
from dbara.engine import BackupEngine, RestoreEngine
from dbara.log import Logger
from dbara.runner import CommandRunner


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dbara",
        description="Docker Backup and Restore Application",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Backup one app:
    dbara -m backup -a jellyfin -d /srv/apps -b /srv/backups -p prod -v

  Backup all apps, keep last 7 archives each:
    dbara -m backup -d /srv/apps -b /srv/backups -A --keep-last 7

  Restore latest backup for one app:
    dbara -m restore -a jellyfin -d /srv/apps -b /srv/backups -r /srv/apps -o 1000:1000

Hooks:
  Place executable scripts at: HOOKS_DIR/<app>/{pre-backup,post-backup,pre-restore,post-restore}
""",
    )

    # Required
    req = p.add_argument_group("required")
    req.add_argument(
        "-m", "--mode", required=True, choices=["backup", "restore"], help="Operation mode"
    )
    req.add_argument(
        "-d", "--app-folder-dir", required=True, type=Path,
        help="Parent directory containing per-app folders",
    )
    req.add_argument(
        "-b", "--backup-dest-dir", required=True, type=Path,
        help="Backup destination (directory for backup; file or directory for restore)",
    )

    # Common
    com = p.add_argument_group("common options")
    com.add_argument("-a", "--app-name", default="", help="Single app name")
    com.add_argument(
        "--apps", nargs="+", metavar="APP", default=None,
        help="Restore a specific list of apps (restore mode only)",
    )
    com.add_argument(
        "-A", "--all-apps", action="store_true",
        help="Backup/restore all apps (backup: scans --app-folder-dir; restore: scans --backup-dest-dir)",  # noqa: E501
    )
    com.add_argument("-r", "--restore-dest-dir", type=Path, default=None)
    com.add_argument(
        "-o", "--owner-group", default="",
        help="Set ownership after restore as user:group (overrides --ownership-map)",
    )
    com.add_argument("-p", "--optional-prefix", default="", help="Prefix in backup filename")
    com.add_argument(
        "-x", "--remove-after-backup", action="store_true",
        help="Remove app directory after successful backup (archive integrity verified first)",
    )
    com.add_argument(
        "-s", "--no-start-container", action="store_true",
        help="Do NOT start the container after the operation completes",
    )
    com.add_argument(
        "-f", "--force", action="store_true",
        help="Force backup even when no changes are detected",
    )
    com.add_argument("--strict", action="store_true", help="Treat warnings as fatal errors")
    com.add_argument(
        "--skip-checksum", action="store_true", help="Skip checksum generation/verification"
    )
    com.add_argument(
        "-v", "--verbose", action="count", default=0,
        help="-v enables debug output; -vv additionally writes a logfile",
    )

    # Performance / behaviour
    perf = p.add_argument_group("performance / behaviour")
    perf.add_argument("--compress", choices=["zstd", "gzip"], default="zstd")
    perf.add_argument(
        "--zstd-opts", default="-T0 -3", help='Options forwarded to zstd (default: "-T0 -3")'
    )
    perf.add_argument(
        "--fast-hash", action=argparse.BooleanOptionalAction, default=True,
        help="Use xxh128sum when available (default: enabled)",
    )
    perf.add_argument(
        "--io-nice", action=argparse.BooleanOptionalAction, default=True,
        help="Wrap heavy operations with ionice+nice (default: enabled)",
    )
    perf.add_argument(
        "--keep-last", type=int, default=0, metavar="N",
        help="Keep last N backups per app and prune older ones (0 = disabled)",
    )
    perf.add_argument(
        "--state-dir", type=Path, default=Path("/var/lib/app-backup/state"),
        help="Directory for change-detection state files",
    )
    perf.add_argument(
        "--hooks-dir", type=Path, default=Path("/etc/app-backup/hooks"),
        help="Root directory for per-app hook scripts",
    )
    perf.add_argument(
        "--lock-dir", type=Path, default=Path("/var/lock"),
        help="Directory for per-app lock files (default: /var/lock)",
    )
    perf.add_argument("--ownership-map", type=Path, default=None, dest="ownership_map_file")
    perf.add_argument("--stop-timeout", type=int, default=30, metavar="SEC")
    perf.add_argument("--retry-max", type=int, default=5, metavar="N")
    perf.add_argument("--retry-base-sleep", type=int, default=2, metavar="SEC")
    perf.add_argument(
        "--logfile", type=Path, default=Path("/var/log/app-backup-restore.log"),
        help="Log file path (written when -vv is used)",
    )

    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _build_config(args: argparse.Namespace) -> Config:
    return Config(
        mode=args.mode,
        app_name=args.app_name,
        app_names=args.apps or [],
        app_folder_dir=args.app_folder_dir,
        backup_dest_dir=args.backup_dest_dir,
        restore_dest_dir=args.restore_dest_dir,
        remove_after_backup=args.remove_after_backup,
        start_container=not args.no_start_container,
        all_apps=args.all_apps,
        force=args.force,
        strict=args.strict,
        skip_checksum=args.skip_checksum,
        compressor=args.compress,
        zstd_opts=args.zstd_opts,
        fast_hash=args.fast_hash,
        io_nice=args.io_nice,
        keep_last=args.keep_last,
        state_dir=args.state_dir,
        hooks_dir=args.hooks_dir,
        lock_dir=args.lock_dir,
        ownership_map_file=args.ownership_map_file,
        owner_group=args.owner_group,
        optional_prefix=args.optional_prefix,
        stop_timeout=args.stop_timeout,
        retry_max=args.retry_max,
        retry_base_sleep=args.retry_base_sleep,
        verbosity=args.verbose,
        logfile=args.logfile,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        config = _build_config(args)
        config.validate()
    except ValueError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    # Initialise logger
    logfile: Path | None = config.logfile if config.verbosity >= 2 else None
    if logfile is not None:
        logfile.parent.mkdir(parents=True, exist_ok=True)
    logger = Logger(verbosity=config.verbosity, strict=config.strict, logfile=logfile)

    # Prerequisites
    if not shutil.which("docker"):
        logger.fatal("Docker is not installed or not in PATH.")
    if config.compressor == "zstd" and not shutil.which("zstd"):
        logger.warn("zstd not found; please install it for best performance.")
    if not shutil.which("xxh128sum"):
        logger.warn("xxh128sum not found; falling back to sha256sum for checksums.")

    # Shared dependencies
    try:
        config.state_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        logger.fatal(
            f"Cannot create state directory {config.state_dir}: permission denied. "
            f"Run with sudo or use --state-dir to specify a writable location."
        )
    runner = CommandRunner(config=config, logger=logger)
    docker = DockerClient(
        runner=runner,
        logger=logger,
        stop_timeout=config.stop_timeout,
        start_container=config.start_container,
    )

    # Dispatch
    if config.mode == "backup":
        engine = BackupEngine(config=config, runner=runner, docker=docker, logger=logger)
        if config.all_apps:
            engine.backup_all_apps()
        else:
            # Match backup_all_apps: only restart containers that were running
            # before the backup, so a deliberately stopped container stays stopped.
            was_running = docker.container_exists(config.app_name) and docker.container_running(
                config.app_name
            )
            docker.stop(config.app_name)
            engine.backup_single_app(config.app_name)
            if was_running:
                docker.start(config.app_name)
    else:
        engine_r = RestoreEngine(config=config, runner=runner, docker=docker, logger=logger)
        if config.all_apps:
            engine_r.restore_all_apps()
        elif config.app_names:
            engine_r.restore_apps(config.app_names)
        else:
            engine_r.restore_app()

    logger.info("✅ Script completed successfully!")
    logger.print_summary()
    return 0


if __name__ == "__main__":
    sys.exit(main())
