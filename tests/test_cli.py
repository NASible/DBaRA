from __future__ import annotations

from pathlib import Path

import pytest

from dbara.cli import _build_config, build_parser, main
from tests.conftest import FakeDockerClient

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

_BASE = ["-m", "backup", "-d", "/apps", "-b", "/backups"]


def test_parse_mode_and_required_flags() -> None:
    args = build_parser().parse_args(_BASE + ["-a", "myapp"])
    assert args.mode == "backup"
    assert args.app_folder_dir == Path("/apps")
    assert args.backup_dest_dir == Path("/backups")
    assert args.app_name == "myapp"


def test_parse_all_apps_flag() -> None:
    args = build_parser().parse_args(_BASE + ["-A"])
    assert args.all_apps is True


def test_no_start_container_inverts_start_container() -> None:
    args = build_parser().parse_args(_BASE + ["-a", "app", "-s"])
    config = _build_config(args)
    assert config.start_container is False


def test_start_container_is_true_by_default() -> None:
    args = build_parser().parse_args(_BASE + ["-a", "app"])
    config = _build_config(args)
    assert config.start_container is True


def test_verbose_single_sets_verbosity_1() -> None:
    args = build_parser().parse_args(_BASE + ["-a", "app", "-v"])
    assert args.verbose == 1


def test_verbose_double_sets_verbosity_2() -> None:
    args = build_parser().parse_args(_BASE + ["-a", "app", "-vv"])
    assert args.verbose == 2


def test_no_fast_hash_disables_fast_hash() -> None:
    args = build_parser().parse_args(_BASE + ["-a", "app", "--no-fast-hash"])
    assert args.fast_hash is False


def test_fast_hash_enabled_by_default() -> None:
    args = build_parser().parse_args(_BASE + ["-a", "app"])
    assert args.fast_hash is True


def test_compress_gzip() -> None:
    args = build_parser().parse_args(_BASE + ["-a", "app", "--compress", "gzip"])
    config = _build_config(args)
    assert config.compressor == "gzip"


def test_keep_last_parsed() -> None:
    args = build_parser().parse_args(_BASE + ["-a", "app", "--keep-last", "7"])
    config = _build_config(args)
    assert config.keep_last == 7


def test_stop_timeout_parsed() -> None:
    args = build_parser().parse_args(_BASE + ["-a", "app", "--stop-timeout", "60"])
    config = _build_config(args)
    assert config.stop_timeout == 60


def test_retry_max_parsed() -> None:
    args = build_parser().parse_args(_BASE + ["-a", "app", "--retry-max", "10"])
    config = _build_config(args)
    assert config.retry_max == 10


def test_optional_prefix_parsed() -> None:
    args = build_parser().parse_args(_BASE + ["-a", "app", "-p", "prod"])
    config = _build_config(args)
    assert config.optional_prefix == "prod"


def test_restore_dest_dir_parsed() -> None:
    args = build_parser().parse_args(
        ["-m", "restore", "-d", "/apps", "-b", "/backups", "-a", "app", "-r", "/restore"]
    )
    config = _build_config(args)
    assert config.restore_dest_dir == Path("/restore")


def test_lock_dir_parsed() -> None:
    args = build_parser().parse_args(_BASE + ["-a", "app", "--lock-dir", "/tmp/locks"])
    config = _build_config(args)
    assert config.lock_dir == Path("/tmp/locks")


def test_force_flag() -> None:
    args = build_parser().parse_args(_BASE + ["-a", "app", "-f"])
    config = _build_config(args)
    assert config.force is True


def test_strict_flag() -> None:
    args = build_parser().parse_args(_BASE + ["-a", "app", "--strict"])
    config = _build_config(args)
    assert config.strict is True


def test_skip_checksum_flag() -> None:
    args = build_parser().parse_args(_BASE + ["-a", "app", "--skip-checksum"])
    config = _build_config(args)
    assert config.skip_checksum is True


def test_missing_required_mode_exits() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["-d", "/apps", "-b", "/backups"])


def test_missing_required_app_folder_dir_exits() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["-m", "backup", "-b", "/backups"])


# ---------------------------------------------------------------------------
# main() — validate() failure returns 1 without touching docker
# ---------------------------------------------------------------------------

def test_main_returns_1_when_no_app_or_all_apps(tmp_path: Path) -> None:
    result = main(["-m", "backup", "-d", str(tmp_path), "-b", str(tmp_path)])
    assert result == 1


def test_main_returns_1_for_restore_without_app_name(tmp_path: Path) -> None:
    result = main([
        "-m", "restore", "-d", str(tmp_path), "-b", str(tmp_path),
        "-r", str(tmp_path),
    ])
    assert result == 1


def test_apps_flag_parsed_as_list() -> None:
    args = build_parser().parse_args(
        ["-m", "restore", "-d", "/apps", "-b", "/backups",
         "-r", "/restore", "--apps", "authelia", "jellyfin"]
    )
    config = _build_config(args)
    assert config.app_names == ["authelia", "jellyfin"]


def test_main_returns_1_for_restore_without_restore_dest_dir(tmp_path: Path) -> None:
    result = main(["-m", "restore", "-d", str(tmp_path), "-b", str(tmp_path), "-a", "app"])
    assert result == 1


# ---------------------------------------------------------------------------
# main() — single-app backup preserves prior container state
# ---------------------------------------------------------------------------

def _run_single_app_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    running: bool,
) -> FakeDockerClient:
    docker = FakeDockerClient(existing={"myapp"}, running={"myapp"} if running else set())

    class StubEngine:
        def __init__(self, **kwargs: object) -> None:
            pass

        def backup_single_app(self, app: str) -> None:
            pass

    monkeypatch.setattr("dbara.cli.shutil.which", lambda name: "/usr/bin/stub")
    monkeypatch.setattr("dbara.cli.DockerClient", lambda **kwargs: docker)
    monkeypatch.setattr("dbara.cli.BackupEngine", StubEngine)

    result = main([
        "-m", "backup", "-a", "myapp",
        "-d", str(tmp_path), "-b", str(tmp_path),
        "--state-dir", str(tmp_path / "state"),
    ])
    assert result == 0
    return docker


def test_single_app_backup_restarts_previously_running_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker = _run_single_app_backup(tmp_path, monkeypatch, running=True)
    assert docker.started == ["myapp"]


def test_single_app_backup_leaves_stopped_container_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docker = _run_single_app_backup(tmp_path, monkeypatch, running=False)
    assert docker.started == []
