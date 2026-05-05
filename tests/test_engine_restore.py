from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from dbara.engine import RestoreEngine
from dbara.log import Logger
from tests.conftest import FakeDockerClient, FakeRunner, make_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_archive(directory: Path, name: str) -> Path:
    p = directory / name
    p.write_text("")
    time.sleep(0.02)
    return p


def _setup(
    tmp_path: Path,
    app: str = "myapp",
    existing: set[str] | None = None,
    running: set[str] | None = None,
    **config_overrides: Any,
) -> tuple[Path, RestoreEngine, FakeRunner, FakeDockerClient]:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    archive = _make_archive(backup_dir, f"host_{app}_20240101_000000.bkup.tar.zst")

    restore_dir = tmp_path / "restore"
    # Pre-populate restore path so _verify_restore finds it non-empty
    restore_path = restore_dir / app
    restore_path.mkdir(parents=True)
    (restore_path / "dummy.txt").write_text("x")

    config = make_config(
        mode="restore",
        app_name=app,
        app_folder_dir=tmp_path / "apps",
        backup_dest_dir=backup_dir,
        restore_dest_dir=restore_dir,
        hooks_dir=tmp_path / "hooks",
        skip_checksum=True,
        **config_overrides,
    )
    runner = FakeRunner()
    # Preset tar -tf to return an empty listing (no entries to verify)
    runner.preset_response(["tar", "-I", "zstd", "-tf"], stdout="")
    docker = FakeDockerClient(existing=existing or set(), running=running or set())
    engine = RestoreEngine(config=config, runner=runner, docker=docker, logger=Logger())
    return archive, engine, runner, docker


# ---------------------------------------------------------------------------
# archive selection
# ---------------------------------------------------------------------------

def test_restore_uses_newest_archive_from_directory(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    _make_archive(backup_dir, "host_myapp_20240101_000000.bkup.tar.zst")
    newest = _make_archive(backup_dir, "host_myapp_20240201_000000.bkup.tar.zst")

    restore_dir = tmp_path / "restore"
    restore_path = restore_dir / "myapp"
    restore_path.mkdir(parents=True)
    (restore_path / "dummy.txt").write_text("x")

    config = make_config(
        mode="restore",
        app_name="myapp",
        app_folder_dir=tmp_path / "apps",
        backup_dest_dir=backup_dir,
        restore_dest_dir=restore_dir,
        hooks_dir=tmp_path / "hooks",
        skip_checksum=True,
    )
    runner = FakeRunner()
    runner.preset_response(["tar", "-I", "zstd", "-tf"], stdout="")
    engine = RestoreEngine(
        config=config, runner=runner, docker=FakeDockerClient(), logger=Logger()
    )
    engine.restore_app()

    tar_call = runner.first_call_with_prefix("tar", "-I", "zstd", "-xf")
    assert tar_call is not None
    assert newest.name in tar_call[tar_call.index("-xf") + 1]


def test_restore_accepts_direct_archive_file(tmp_path: Path) -> None:
    backup_file = tmp_path / "host_myapp_20240101_000000.bkup.tar.zst"
    backup_file.write_text("")

    restore_dir = tmp_path / "restore"
    restore_path = restore_dir / "myapp"
    restore_path.mkdir(parents=True)
    (restore_path / "dummy.txt").write_text("x")

    config = make_config(
        mode="restore",
        app_name="myapp",
        app_folder_dir=tmp_path / "apps",
        backup_dest_dir=backup_file,
        restore_dest_dir=restore_dir,
        hooks_dir=tmp_path / "hooks",
        skip_checksum=True,
    )
    runner = FakeRunner()
    runner.preset_response(["tar", "-I", "zstd", "-tf"], stdout="")
    engine = RestoreEngine(
        config=config, runner=runner, docker=FakeDockerClient(), logger=Logger()
    )
    engine.restore_app()  # should not raise


def test_restore_sanity_check_rejects_mismatched_filename(tmp_path: Path) -> None:
    wrong_file = tmp_path / "host_sonarr_20240101_000000.bkup.tar.zst"
    wrong_file.write_text("")

    config = make_config(
        mode="restore",
        app_name="myapp",
        backup_dest_dir=wrong_file,
        restore_dest_dir=tmp_path / "restore",
        hooks_dir=tmp_path / "hooks",
        skip_checksum=True,
    )
    runner = FakeRunner()
    engine = RestoreEngine(
        config=config, runner=runner, docker=FakeDockerClient(), logger=Logger()
    )
    with pytest.raises(SystemExit):
        engine.restore_app()


# ---------------------------------------------------------------------------
# Container stop / start sequencing
# ---------------------------------------------------------------------------

def test_restore_stops_running_container(tmp_path: Path) -> None:
    _, engine, _, docker = _setup(tmp_path, existing={"myapp"}, running={"myapp"})
    engine.restore_app()
    assert "myapp" in docker.stopped


def test_restore_starts_container_after_restore(tmp_path: Path) -> None:
    _, engine, _, docker = _setup(tmp_path, existing={"myapp"}, running={"myapp"})
    engine.restore_app()
    assert "myapp" in docker.started


def test_restore_skips_start_when_disabled(tmp_path: Path) -> None:
    _, engine, _, docker = _setup(
        tmp_path, existing={"myapp"}, running={"myapp"}, start_container=False
    )
    engine.restore_app()
    assert docker.started == []


def test_restore_no_stop_when_container_not_running(tmp_path: Path) -> None:
    _, engine, _, docker = _setup(tmp_path, existing={"myapp"}, running=set())
    engine.restore_app()
    assert docker.stopped == []


# ---------------------------------------------------------------------------
# tar extract command
# ---------------------------------------------------------------------------

def test_restore_tar_extract_command_structure(tmp_path: Path) -> None:
    _, engine, runner, _ = _setup(tmp_path)
    engine.restore_app()
    assert runner.called_with_prefix("tar", "-I", "zstd", "-xf")


def test_restore_tar_uses_strip_components(tmp_path: Path) -> None:
    _, engine, runner, _ = _setup(tmp_path)
    engine.restore_app()
    tar_call = runner.first_call_with_prefix("tar", "-I", "zstd", "-xf")
    assert tar_call is not None
    assert "--strip-components=1" in tar_call


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------

def test_restore_calls_chown_when_owner_group_set(tmp_path: Path) -> None:
    _, engine, runner, _ = _setup(tmp_path, owner_group="1000:1000")
    engine.restore_app()
    assert runner.called_with_prefix("chown", "-R", "1000:1000")


def test_restore_skips_chown_when_no_owner_group(tmp_path: Path) -> None:
    _, engine, runner, _ = _setup(tmp_path, owner_group="")
    engine.restore_app()
    assert not runner.called_with_prefix("chown")


# ---------------------------------------------------------------------------
# Multi-app restore (restore_apps / restore_all_apps)
# ---------------------------------------------------------------------------

def _setup_multi(
    tmp_path: Path,
    apps: list[str],
    **config_overrides: Any,
) -> tuple[Path, RestoreEngine, FakeRunner, FakeDockerClient]:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for app in apps:
        (backup_dir / f"host_{app}_20240101_000000.bkup.tar.zst").write_text("")

    restore_dir = tmp_path / "restore"
    for app in apps:
        restore_path = restore_dir / app
        restore_path.mkdir(parents=True)
        (restore_path / "dummy.txt").write_text("x")

    config = make_config(
        mode="restore",
        app_name="",
        app_folder_dir=tmp_path / "apps",
        backup_dest_dir=backup_dir,
        restore_dest_dir=restore_dir,
        hooks_dir=tmp_path / "hooks",
        skip_checksum=True,
        **config_overrides,
    )
    runner = FakeRunner()
    runner.preset_response(["tar", "-I", "zstd", "-tf"], stdout="")
    docker = FakeDockerClient()
    engine = RestoreEngine(config=config, runner=runner, docker=docker, logger=Logger())
    return restore_dir, engine, runner, docker


def test_restore_apps_restores_each_in_list(tmp_path: Path) -> None:
    _, engine, runner, _ = _setup_multi(tmp_path, ["authelia", "jellyfin"])
    engine.restore_apps(["authelia", "jellyfin"])
    tar_calls = [c for c in runner.calls if c and c[0] == "tar" and "-xf" in c]
    assert len(tar_calls) == 2


def test_restore_apps_extracts_correct_archives(tmp_path: Path) -> None:
    _, engine, runner, _ = _setup_multi(tmp_path, ["authelia", "jellyfin"])
    engine.restore_apps(["authelia", "jellyfin"])
    tar_calls = [c for c in runner.calls if c and c[0] == "tar" and "-xf" in c]
    extracted = {c[c.index("-xf") + 1] for c in tar_calls}
    assert any("authelia" in p for p in extracted)
    assert any("jellyfin" in p for p in extracted)


def test_restore_all_apps_discovers_and_restores(tmp_path: Path) -> None:
    _, engine, runner, _ = _setup_multi(tmp_path, ["authelia", "jellyfin"])
    engine.restore_all_apps()
    tar_calls = [c for c in runner.calls if c and c[0] == "tar" and "-xf" in c]
    assert len(tar_calls) == 2


def test_restore_all_apps_empty_backup_dir_warns(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    restore_dir = tmp_path / "restore"

    config = make_config(
        mode="restore",
        app_name="",
        app_folder_dir=tmp_path / "apps",
        backup_dest_dir=backup_dir,
        restore_dest_dir=restore_dir,
        hooks_dir=tmp_path / "hooks",
        skip_checksum=True,
    )
    from dbara.log import Logger as RealLogger
    logger = RealLogger(verbosity=0, strict=False, logfile=None)
    engine = RestoreEngine(
        config=config, runner=FakeRunner(), docker=FakeDockerClient(), logger=logger
    )
    engine.restore_all_apps()
    assert any("No backup archives" in w for w in logger.warnings)
