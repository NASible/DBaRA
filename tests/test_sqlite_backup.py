from __future__ import annotations

import sqlite3
from pathlib import Path

from dbara.sqlite_backup import cleanup_sqlite_sidecars, sqlite_safe_backup
from tests.conftest import Logger


def _db(path: Path) -> Path:
    """Create a minimal valid SQLite database at path."""
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE t (id INTEGER)")
    con.commit()
    con.close()
    return path


# ---------------------------------------------------------------------------
# sqlite_safe_backup
# ---------------------------------------------------------------------------

def test_backup_creates_sidecar_for_sqlite(tmp_path: Path) -> None:
    _db(tmp_path / "data.sqlite")
    sidecars = sqlite_safe_backup(tmp_path, Logger())
    assert len(sidecars) == 1
    assert sidecars[0] == tmp_path / "data.sqlite.bak"
    assert sidecars[0].exists()


def test_backup_handles_sqlite3_extension(tmp_path: Path) -> None:
    _db(tmp_path / "data.sqlite3")
    sidecars = sqlite_safe_backup(tmp_path, Logger())
    assert any(s.name.endswith(".sqlite3.bak") for s in sidecars)


def test_backup_handles_db_extension(tmp_path: Path) -> None:
    _db(tmp_path / "data.db")
    sidecars = sqlite_safe_backup(tmp_path, Logger())
    assert any(s.name.endswith(".db.bak") for s in sidecars)


def test_backup_skips_non_sqlite_db_files(tmp_path: Path) -> None:
    # BoltDB, LevelDB, etc. share .db extension but are not SQLite
    boltdb = tmp_path / "portainer.db"
    boltdb.write_bytes(b"\x00\x01\x00\x00" + b"\x00" * 12)  # not SQLite magic
    logger = Logger()
    sidecars = sqlite_safe_backup(tmp_path, logger)
    assert sidecars == []
    assert logger.warnings == []  # silently skipped, no warning


def test_backup_noop_when_no_databases(tmp_path: Path) -> None:
    assert sqlite_safe_backup(tmp_path, Logger()) == []


def test_backup_discovers_nested_databases(tmp_path: Path) -> None:
    sub = tmp_path / "subdir"
    sub.mkdir()
    _db(sub / "nested.db")
    sidecars = sqlite_safe_backup(tmp_path, Logger())
    assert len(sidecars) == 1


def test_backup_sidecar_is_valid_sqlite(tmp_path: Path) -> None:
    _db(tmp_path / "src.sqlite")
    sidecars = sqlite_safe_backup(tmp_path, Logger())
    # The sidecar should be openable as a database
    con = sqlite3.connect(str(sidecars[0]))
    tables = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    con.close()
    assert ("t",) in tables


# ---------------------------------------------------------------------------
# cleanup_sqlite_sidecars
# ---------------------------------------------------------------------------

def test_cleanup_removes_bak_sidecars(tmp_path: Path) -> None:
    bak = tmp_path / "data.sqlite.bak"
    bak.write_text("placeholder")
    cleanup_sqlite_sidecars(tmp_path, Logger())
    assert not bak.exists()


def test_cleanup_preserves_original_databases(tmp_path: Path) -> None:
    db = tmp_path / "data.sqlite"
    db.write_text("placeholder")
    cleanup_sqlite_sidecars(tmp_path, Logger())
    assert db.exists()


def test_cleanup_removes_db_bak_extension(tmp_path: Path) -> None:
    bak = tmp_path / "data.db.bak"
    bak.write_text("placeholder")
    cleanup_sqlite_sidecars(tmp_path, Logger())
    assert not bak.exists()
