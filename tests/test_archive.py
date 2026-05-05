from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from dbara.archive import (
    build_archive_name,
    list_apps_in_backup_dir,
    prune_old_backups,
    select_newest_archive,
)
from tests.conftest import Logger

# ---------------------------------------------------------------------------
# build_archive_name
# ---------------------------------------------------------------------------

def test_archive_name_format_with_prefix() -> None:
    ts = datetime(2024, 6, 15, 10, 30, 0)
    name = build_archive_name("jellyfin", "zstd", "prod", "myhost", ts)
    assert name == "myhost_prod_jellyfin_20240615_103000.bkup.tar.zst"


def test_archive_name_format_without_prefix() -> None:
    ts = datetime(2024, 6, 15, 10, 30, 0)
    name = build_archive_name("jellyfin", "zstd", "", "myhost", ts)
    assert name == "myhost_jellyfin_20240615_103000.bkup.tar.zst"


def test_archive_name_gzip_extension() -> None:
    ts = datetime(2024, 1, 1, 0, 0, 0)
    name = build_archive_name("app", "gzip", "", "host", ts)
    assert name.endswith(".bkup.tar.tgz")


def test_archive_name_contains_app() -> None:
    ts = datetime(2024, 1, 1, 0, 0, 0)
    name = build_archive_name("sonarr", "zstd", "", "h", ts)
    assert "sonarr" in name


# ---------------------------------------------------------------------------
# select_newest_archive
# ---------------------------------------------------------------------------

def test_select_newest_returns_latest(tmp_path: Path) -> None:
    old = tmp_path / "host_myapp_20240101_000000.bkup.tar.zst"
    new = tmp_path / "host_myapp_20240201_000000.bkup.tar.zst"
    old.write_text("")
    time.sleep(0.01)
    new.write_text("")
    # make sure mtime differs
    assert select_newest_archive(tmp_path, "myapp") == new


def test_select_newest_returns_none_when_empty(tmp_path: Path) -> None:
    assert select_newest_archive(tmp_path, "myapp") is None


def test_select_newest_ignores_other_apps(tmp_path: Path) -> None:
    other = tmp_path / "host_otherapp_20240101_000000.bkup.tar.zst"
    other.write_text("")
    assert select_newest_archive(tmp_path, "myapp") is None


def test_select_newest_matches_tgz_extension(tmp_path: Path) -> None:
    archive = tmp_path / "host_myapp_20240101_000000.bkup.tar.tgz"
    archive.write_text("")
    assert select_newest_archive(tmp_path, "myapp") == archive


# ---------------------------------------------------------------------------
# prune_old_backups
# ---------------------------------------------------------------------------

def _make_archive(directory: Path, name: str) -> Path:
    p = directory / name
    p.write_text("")
    time.sleep(0.02)  # ensure distinct mtimes
    return p


def test_prune_keeps_last_n(tmp_path: Path) -> None:
    logger = Logger()
    a1 = _make_archive(tmp_path, "host_app_20240101_000000.bkup.tar.zst")
    a2 = _make_archive(tmp_path, "host_app_20240102_000000.bkup.tar.zst")
    a3 = _make_archive(tmp_path, "host_app_20240103_000000.bkup.tar.zst")
    prune_old_backups(tmp_path, "app", keep_last=2, logger=logger)
    assert not a1.exists()
    assert a2.exists()
    assert a3.exists()


def test_prune_noop_when_keep_last_zero(tmp_path: Path) -> None:
    logger = Logger()
    a = _make_archive(tmp_path, "host_app_20240101_000000.bkup.tar.zst")
    prune_old_backups(tmp_path, "app", keep_last=0, logger=logger)
    assert a.exists()


def test_prune_noop_when_count_lte_keep_last(tmp_path: Path) -> None:
    logger = Logger()
    a = _make_archive(tmp_path, "host_app_20240101_000000.bkup.tar.zst")
    prune_old_backups(tmp_path, "app", keep_last=5, logger=logger)
    assert a.exists()


def test_prune_also_removes_checksum_sidecars(tmp_path: Path) -> None:
    logger = Logger()
    a1 = _make_archive(tmp_path, "host_app_20240101_000000.bkup.tar.zst")
    sha = Path(str(a1) + ".sha256sum")
    xxh = Path(str(a1) + ".xxh128")
    sha.write_text("checksums")
    xxh.write_text("checksums")
    _make_archive(tmp_path, "host_app_20240102_000000.bkup.tar.zst")
    prune_old_backups(tmp_path, "app", keep_last=1, logger=logger)
    assert not a1.exists()
    assert not sha.exists()
    assert not xxh.exists()


def test_prune_does_not_touch_other_apps(tmp_path: Path) -> None:
    logger = Logger()
    other = _make_archive(tmp_path, "host_otherapp_20240101_000000.bkup.tar.zst")
    a1 = _make_archive(tmp_path, "host_app_20240101_000000.bkup.tar.zst")
    _make_archive(tmp_path, "host_app_20240102_000000.bkup.tar.zst")
    prune_old_backups(tmp_path, "app", keep_last=1, logger=logger)
    assert not a1.exists()
    assert other.exists()


# ---------------------------------------------------------------------------
# list_apps_in_backup_dir
# ---------------------------------------------------------------------------

def test_list_apps_single_app(tmp_path: Path) -> None:
    (tmp_path / "host_myapp_20240101_000000.bkup.tar.zst").write_text("")
    (tmp_path / "host_myapp_20240102_000000.bkup.tar.zst").write_text("")
    assert list_apps_in_backup_dir(tmp_path) == ["myapp"]


def test_list_apps_multiple_apps_sorted(tmp_path: Path) -> None:
    (tmp_path / "host_jellyfin_20240101_000000.bkup.tar.zst").write_text("")
    (tmp_path / "host_authelia_20240101_000000.bkup.tar.zst").write_text("")
    assert list_apps_in_backup_dir(tmp_path) == ["authelia", "jellyfin"]


def test_list_apps_empty_dir(tmp_path: Path) -> None:
    assert list_apps_in_backup_dir(tmp_path) == []


def test_list_apps_ignores_non_archive_files(tmp_path: Path) -> None:
    (tmp_path / "readme.txt").write_text("")
    (tmp_path / "host_myapp_20240101_000000.bkup.tar.zst.sha256sum").write_text("")
    assert list_apps_in_backup_dir(tmp_path) == []


def test_list_apps_with_prefix_in_filename(tmp_path: Path) -> None:
    (tmp_path / "host_prod_jellyfin_20240101_000000.bkup.tar.zst").write_text("")
    assert list_apps_in_backup_dir(tmp_path) == ["jellyfin"]


def test_list_apps_tgz_extension(tmp_path: Path) -> None:
    (tmp_path / "host_sonarr_20240101_000000.bkup.tar.tgz").write_text("")
    assert list_apps_in_backup_dir(tmp_path) == ["sonarr"]
