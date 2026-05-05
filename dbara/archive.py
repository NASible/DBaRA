from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from dbara.log import Logger

_GLOB_PATTERNS = (
    "*_{app}_*.bkup.tar.zst",
    "*_{app}_*.bkup.tar.tgz",
    "*_{app}_*.bkup.tar.gz",
)

_ARCHIVE_DATE_RE = re.compile(r"^(.+)_(\d{8}_\d{6})\.bkup\.tar\.(zst|tgz|gz)$")


def backup_ext(compressor: str) -> str:
    return "zst" if compressor == "zstd" else "tgz"


def build_archive_name(
    app: str,
    compressor: str,
    optional_prefix: str = "",
    hostname: str = "",
    timestamp: datetime | None = None,
) -> str:
    """Return the backup archive filename (no directory component)."""
    if timestamp is None:
        timestamp = datetime.now()
    date_str = timestamp.strftime("%Y%m%d_%H%M%S")
    prefix_part = f"{optional_prefix}_" if optional_prefix else ""
    ext = backup_ext(compressor)
    return f"{hostname}_{prefix_part}{app}_{date_str}.bkup.tar.{ext}"


def select_newest_archive(directory: Path, app: str) -> Path | None:
    """Return the most-recently-modified backup archive for app in directory, or None."""
    candidates: list[tuple[float, Path]] = []
    for pattern_tmpl in _GLOB_PATTERNS:
        for p in directory.glob(pattern_tmpl.format(app=app)):
            if p.is_file():
                candidates.append((p.stat().st_mtime, p))
    if not candidates:
        return None
    return max(candidates, key=lambda t: t[0])[1]


def prune_old_backups(
    backup_dir: Path,
    app: str,
    keep_last: int,
    logger: Logger,
) -> None:
    """Delete the oldest archives for app, keeping only the last keep_last.

    Also removes associated .sha256sum and .xxh128 checksum sidecar files.
    No-op when keep_last <= 0.
    """
    if keep_last <= 0:
        return
    logger.info(f"Pruning old backups for {app!r} (keeping last {keep_last})...")
    archives: list[tuple[float, Path]] = []
    for pattern_tmpl in _GLOB_PATTERNS:
        for p in backup_dir.glob(pattern_tmpl.format(app=app)):
            if p.is_file():
                archives.append((p.stat().st_mtime, p))
    archives.sort(key=lambda t: t[0])  # oldest first
    count = len(archives)
    if count <= keep_last:
        logger.debug(f"Only {count} archive(s) for {app!r}; nothing to prune.")
        return
    for _, old in archives[: count - keep_last]:
        logger.info(f"Pruning old backup: {old}")
        old.unlink(missing_ok=True)
        Path(str(old) + ".sha256sum").unlink(missing_ok=True)
        Path(str(old) + ".xxh128").unlink(missing_ok=True)


def list_apps_in_backup_dir(backup_dir: Path) -> list[str]:
    """Return sorted unique app names inferred from archive filenames in backup_dir.

    Parses the archive naming convention: {hostname}[_{prefix}]{app}_{YYYYMMDD_HHMMSS}.bkup.tar.EXT
    The app name is the last underscore-delimited segment before the timestamp.
    App names containing underscores are not supported by this auto-discovery.
    """
    if not backup_dir.is_dir():
        return []
    apps: set[str] = set()
    for f in backup_dir.iterdir():
        if not f.is_file():
            continue
        m = _ARCHIVE_DATE_RE.match(f.name)
        if not m:
            continue
        stem = m.group(1)  # e.g. "hostname_prefix_appname"
        app = stem.rsplit("_", 1)[-1]
        if app:
            apps.add(app)
    return sorted(apps)
