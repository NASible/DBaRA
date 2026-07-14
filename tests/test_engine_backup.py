from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dbara.checksum import signature_of_dir
from dbara.engine import BackupEngine
from dbara.log import Logger
from tests.conftest import FakeDockerClient, FakeRunner, make_config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup(
    tmp_path: Path,
    app: str = "myapp",
    **config_overrides: Any,
) -> tuple[Path, BackupEngine, FakeRunner]:
    apps_dir = tmp_path / "apps"
    app_path = apps_dir / app
    app_path.mkdir(parents=True)
    (app_path / "data.txt").write_text("some data")

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()

    config = make_config(
        app_folder_dir=apps_dir,
        backup_dest_dir=tmp_path / "backups",
        state_dir=state_dir,
        lock_dir=lock_dir,
        hooks_dir=tmp_path / "hooks",
        skip_checksum=True,
        **config_overrides,
    )
    runner = FakeRunner()
    docker = FakeDockerClient()
    engine = BackupEngine(config=config, runner=runner, docker=docker, logger=Logger())
    return app_path, engine, runner


# ---------------------------------------------------------------------------
# tar command structure
# ---------------------------------------------------------------------------

def test_backup_calls_tar_with_one_file_system(tmp_path: Path) -> None:
    _, engine, runner = _setup(tmp_path)
    engine.backup_single_app("myapp")
    assert runner.called_with_prefix("tar", "--one-file-system")


def test_backup_tar_includes_app_name(tmp_path: Path) -> None:
    _, engine, runner = _setup(tmp_path)
    engine.backup_single_app("myapp")
    tar_call = runner.first_call_with_prefix("tar", "--one-file-system")
    assert tar_call is not None
    assert "myapp" in tar_call


def test_backup_tar_uses_zstd_compression(tmp_path: Path) -> None:
    _, engine, runner = _setup(tmp_path)
    engine.backup_single_app("myapp")
    tar_call = runner.first_call_with_prefix("tar", "--one-file-system")
    assert tar_call is not None
    assert "-I" in tar_call
    zstd_idx = tar_call.index("-I")
    assert "zstd" in tar_call[zstd_idx + 1]


def test_backup_tar_uses_gzip_when_configured(tmp_path: Path) -> None:
    _, engine, runner = _setup(tmp_path, compressor="gzip")
    runner.set_available_tools("sha256sum")  # no pigz
    engine.backup_single_app("myapp")
    tar_call = runner.first_call_with_prefix("tar", "--one-file-system")
    assert tar_call is not None
    assert "-z" in tar_call


# ---------------------------------------------------------------------------
# Change detection
# ---------------------------------------------------------------------------

def test_backup_skips_when_content_unchanged(tmp_path: Path) -> None:
    _, engine, runner = _setup(tmp_path)
    engine.backup_single_app("myapp")
    tar_after_first = sum(1 for c in runner.calls if c and c[0] == "tar")
    engine.backup_single_app("myapp")
    tar_after_second = sum(1 for c in runner.calls if c and c[0] == "tar")
    assert tar_after_second == tar_after_first


def test_backup_runs_when_content_changed(tmp_path: Path) -> None:
    app_path, engine, runner = _setup(tmp_path)
    engine.backup_single_app("myapp")
    tar_after_first = sum(1 for c in runner.calls if c and c[0] == "tar")
    (app_path / "data.txt").write_text("changed content")
    engine.backup_single_app("myapp")
    tar_after_second = sum(1 for c in runner.calls if c and c[0] == "tar")
    assert tar_after_second > tar_after_first


def test_backup_force_overrides_skip(tmp_path: Path) -> None:
    apps_dir = tmp_path / "apps"
    app_path = apps_dir / "myapp"
    app_path.mkdir(parents=True)
    (app_path / "data.txt").write_text("data")

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()

    # Pre-write sig so content appears "unchanged"
    sig = signature_of_dir(app_path)
    (state_dir / "myapp.sig").write_text(sig)

    config = make_config(
        app_folder_dir=apps_dir,
        backup_dest_dir=tmp_path / "backups",
        state_dir=state_dir,
        lock_dir=lock_dir,
        hooks_dir=tmp_path / "hooks",
        skip_checksum=True,
        force=True,
    )
    runner = FakeRunner()
    engine = BackupEngine(
        config=config, runner=runner, docker=FakeDockerClient(), logger=Logger()
    )
    engine.backup_single_app("myapp")
    assert runner.called_with_prefix("tar", "--one-file-system")


# ---------------------------------------------------------------------------
# remove_after_backup
# ---------------------------------------------------------------------------

def test_remove_after_backup_deletes_app_dir(tmp_path: Path) -> None:
    app_path, engine, _ = _setup(tmp_path, remove_after_backup=True)
    engine.backup_single_app("myapp")
    assert not app_path.exists()


def test_remove_after_backup_verifies_integrity_first(tmp_path: Path) -> None:
    _, engine, runner = _setup(tmp_path, remove_after_backup=True)
    engine.backup_single_app("myapp")
    # Verify command: tar -I zstd -tf <backup_path>
    assert runner.called_with_prefix("tar", "-I", "zstd", "-tf")


def test_no_rm_if_integrity_check_fails(tmp_path: Path) -> None:
    app_path, engine, runner = _setup(tmp_path, remove_after_backup=True)
    # Make the integrity-check tar command raise
    runner.raise_on(["tar", "-I", "zstd", "-tf"])
    with pytest.raises(SystemExit):
        engine.backup_single_app("myapp")
    assert app_path.exists()


# ---------------------------------------------------------------------------
# backup_all_apps — container stop / start sequencing
# ---------------------------------------------------------------------------

def test_all_apps_stops_and_starts_running_container(tmp_path: Path) -> None:
    apps_dir = tmp_path / "apps"
    (apps_dir / "app1").mkdir(parents=True)
    (apps_dir / "app1" / "data.txt").write_text("data")

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()

    config = make_config(
        app_folder_dir=apps_dir,
        backup_dest_dir=tmp_path / "backups",
        state_dir=state_dir,
        lock_dir=lock_dir,
        hooks_dir=tmp_path / "hooks",
        skip_checksum=True,
    )
    runner = FakeRunner()
    docker = FakeDockerClient(existing={"app1"}, running={"app1"})
    engine = BackupEngine(config=config, runner=runner, docker=docker, logger=Logger())

    engine.backup_all_apps()

    assert "app1" in docker.stopped
    assert "app1" in docker.started


def test_all_apps_does_not_start_container_that_was_stopped(tmp_path: Path) -> None:
    apps_dir = tmp_path / "apps"
    (apps_dir / "app1").mkdir(parents=True)
    (apps_dir / "app1" / "data.txt").write_text("data")

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()

    config = make_config(
        app_folder_dir=apps_dir,
        backup_dest_dir=tmp_path / "backups",
        state_dir=state_dir,
        lock_dir=lock_dir,
        hooks_dir=tmp_path / "hooks",
        skip_checksum=True,
    )
    runner = FakeRunner()
    # Container exists but is NOT running
    docker = FakeDockerClient(existing={"app1"}, running=set())
    engine = BackupEngine(config=config, runner=runner, docker=docker, logger=Logger())

    engine.backup_all_apps()

    assert docker.stopped == []
    assert docker.started == []


def test_all_apps_does_not_stop_container_when_content_unchanged(tmp_path: Path) -> None:
    apps_dir = tmp_path / "apps"
    app_path = apps_dir / "app1"
    app_path.mkdir(parents=True)
    (app_path / "data.txt").write_text("data")

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()

    # Pre-write sig so the app appears unchanged
    from dbara.checksum import signature_of_dir
    (state_dir / "app1.sig").write_text(signature_of_dir(app_path))

    config = make_config(
        app_folder_dir=apps_dir,
        backup_dest_dir=tmp_path / "backups",
        state_dir=state_dir,
        lock_dir=lock_dir,
        hooks_dir=tmp_path / "hooks",
        skip_checksum=True,
    )
    runner = FakeRunner()
    docker = FakeDockerClient(existing={"app1"}, running={"app1"})
    engine = BackupEngine(config=config, runner=runner, docker=docker, logger=Logger())

    engine.backup_all_apps()

    assert docker.stopped == []  # no downtime — nothing changed
