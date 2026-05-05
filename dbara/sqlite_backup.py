from __future__ import annotations

import sqlite3
from pathlib import Path

from dbara.log import Logger

_DB_SUFFIXES = (".sqlite", ".sqlite3", ".db")
_SQLITE_MAGIC = b"SQLite format 3\x00"


def _is_sqlite(path: Path) -> bool:
    """Return True only if the file starts with the SQLite3 magic header."""
    try:
        with path.open("rb") as fh:
            return fh.read(16) == _SQLITE_MAGIC
    except OSError:
        return False


def sqlite_safe_backup(app_path: Path, logger: Logger) -> list[Path]:
    """Create consistent .bak sidecars for every SQLite database under app_path.

    Uses Python's stdlib sqlite3 module (conn.backup()) — no CLI dependency.
    Returns the list of created sidecar paths so the caller can clean them up
    after the tar archive is written.
    """
    dbs: list[Path] = []
    for suffix in _DB_SUFFIXES:
        dbs.extend(app_path.rglob(f"*{suffix}"))

    if not dbs:
        return []

    sidecars: list[Path] = []
    for db in sorted(dbs):
        if not _is_sqlite(db):
            logger.debug(f"Skipping non-SQLite file: {db}")
            continue
        sidecar = db.parent / (db.name + ".bak")
        logger.info(f"Creating SQLite safe backup for: {db}")
        try:
            src = sqlite3.connect(str(db))
            dst = sqlite3.connect(str(sidecar))
            src.backup(dst)
            dst.close()
            src.close()
            sidecars.append(sidecar)
        except Exception as exc:
            logger.warn(f"SQLite safe backup failed for {db}: {exc}")
    return sidecars


def cleanup_sqlite_sidecars(app_path: Path, logger: Logger) -> None:
    """Delete *.sqlite.bak, *.sqlite3.bak, *.db.bak files created by sqlite_safe_backup."""
    for suffix in _DB_SUFFIXES:
        for sidecar in app_path.rglob(f"*{suffix}.bak"):
            logger.debug(f"Removing SQLite sidecar: {sidecar}")
            sidecar.unlink(missing_ok=True)
