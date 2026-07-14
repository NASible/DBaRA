from __future__ import annotations

from pathlib import Path

import pytest

from dbara.config import parse_ownership_map
from tests.conftest import make_config

# ---------------------------------------------------------------------------
# Config.validate()
# ---------------------------------------------------------------------------

def test_valid_backup_single_app() -> None:
    make_config(mode="backup", app_name="myapp").validate()


def test_valid_backup_all_apps() -> None:
    make_config(mode="backup", app_name="", all_apps=True).validate()


def test_valid_restore() -> None:
    make_config(
        mode="restore",
        app_name="myapp",
        restore_dest_dir=Path("/restore"),
    ).validate()


def test_invalid_mode() -> None:
    with pytest.raises(ValueError, match="Invalid mode"):
        make_config(mode="copy").validate()


def test_invalid_compressor() -> None:
    with pytest.raises(ValueError, match="Invalid compressor"):
        make_config(compressor="bzip2").validate()


def test_negative_keep_last() -> None:
    with pytest.raises(ValueError, match="keep-last"):
        make_config(keep_last=-1).validate()


def test_zero_keep_last_is_valid() -> None:
    make_config(keep_last=0).validate()


def test_invalid_stop_timeout() -> None:
    with pytest.raises(ValueError, match="stop-timeout"):
        make_config(stop_timeout=0).validate()


def test_invalid_retry_max() -> None:
    with pytest.raises(ValueError, match="retry-max"):
        make_config(retry_max=0).validate()


def test_restore_requires_app_name() -> None:
    with pytest.raises(ValueError, match="--app-name"):
        make_config(mode="restore", app_name="", restore_dest_dir=Path("/r")).validate()


def test_restore_requires_restore_dest_dir() -> None:
    with pytest.raises(ValueError, match="--restore-dest-dir"):
        make_config(mode="restore", app_name="app", restore_dest_dir=None).validate()


def test_backup_single_requires_app_name_without_all_apps() -> None:
    with pytest.raises(ValueError, match="--app-name"):
        make_config(mode="backup", app_name="", all_apps=False).validate()


# ---------------------------------------------------------------------------
# parse_ownership_map()
# ---------------------------------------------------------------------------

def test_ownership_map_found(tmp_path: Path) -> None:
    map_file = tmp_path / "owners.txt"
    map_file.write_text("jellyfin=1000:1000\nradarr=1001:1001\n")
    assert parse_ownership_map(map_file, "jellyfin") == "1000:1000"
    assert parse_ownership_map(map_file, "radarr") == "1001:1001"


def test_ownership_map_not_found(tmp_path: Path) -> None:
    map_file = tmp_path / "owners.txt"
    map_file.write_text("jellyfin=1000:1000\n")
    assert parse_ownership_map(map_file, "sonarr") is None


def test_ownership_map_ignores_comments(tmp_path: Path) -> None:
    map_file = tmp_path / "owners.txt"
    map_file.write_text("# comment\n\njellyfin=1000:1000\n")
    assert parse_ownership_map(map_file, "jellyfin") == "1000:1000"


def test_ownership_map_ignores_lines_without_equals(tmp_path: Path) -> None:
    map_file = tmp_path / "owners.txt"
    map_file.write_text("notavalidline\njellyfin=2000:2000\n")
    assert parse_ownership_map(map_file, "jellyfin") == "2000:2000"
