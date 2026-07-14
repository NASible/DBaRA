"""Shared fixtures and test doubles for the DBaRA test suite."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from dbara.config import Config
from dbara.log import Logger

# ---------------------------------------------------------------------------
# Default config values — override selectively in each test
# ---------------------------------------------------------------------------
_DEFAULTS: dict[str, Any] = {
    "mode": "backup",
    "app_name": "testapp",
    "app_names": [],
    "app_folder_dir": Path("/apps"),
    "backup_dest_dir": Path("/backups"),
    "restore_dest_dir": None,
    "remove_after_backup": False,
    "start_container": True,
    "all_apps": False,
    "force": False,
    "strict": False,
    "skip_checksum": False,
    "compressor": "zstd",
    "zstd_opts": "-T0 -3",
    "fast_hash": True,
    "io_nice": False,  # disabled in tests so FakeRunner sees plain commands
    "keep_last": 0,
    "state_dir": Path("/var/lib/app-backup/state"),
    "hooks_dir": Path("/etc/app-backup/hooks"),
    "lock_dir": Path("/var/lock"),
    "ownership_map_file": None,
    "owner_group": "",
    "optional_prefix": "",
    "stop_timeout": 30,
    "retry_max": 3,
    "retry_base_sleep": 1,
    "verbosity": 0,
    "logfile": Path("/var/log/app-backup-restore.log"),
}


def make_config(**overrides: Any) -> Config:
    return Config(**{**_DEFAULTS, **overrides})


# ---------------------------------------------------------------------------
# FakeRunner — records every call; no subprocess is ever spawned
# ---------------------------------------------------------------------------
class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.call_cwds: list[Path | None] = []  # parallel to self.calls
        self._responses: list[tuple[list[str], subprocess.CompletedProcess[str]]] = []
        self._raise_on: list[list[str]] = []
        self._available: set[str] = {"zstd", "sha256sum", "xxh128sum", "sqlite3", "pigz"}

    # -- configuration helpers --

    def set_available_tools(self, *tools: str) -> None:
        self._available = set(tools)

    def preset_response(
        self,
        cmd_prefix: list[str],
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self._responses.append(
            (cmd_prefix, subprocess.CompletedProcess(cmd_prefix, returncode, stdout, stderr))
        )

    def raise_on(self, cmd_prefix: list[str]) -> None:
        self._raise_on.append(cmd_prefix)

    # -- CommandRunner interface --

    def run(
        self,
        cmd: list[str],
        *,
        check: bool = True,
        capture_output: bool = False,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        self.call_cwds.append(cwd)
        for prefix in self._raise_on:
            if cmd[: len(prefix)] == prefix:
                raise subprocess.CalledProcessError(1, cmd, "", "error")
        for prefix, resp in self._responses:
            if cmd[: len(prefix)] == prefix:
                if check and resp.returncode != 0:
                    raise subprocess.CalledProcessError(
                        resp.returncode, cmd, resp.stdout, resp.stderr
                    )
                return resp
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def run_with_retry(
        self, cmd: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        return self.run(cmd, **kwargs)

    def run_io_niced(
        self, cmd: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        return self.run(cmd, **kwargs)

    def tool_available(self, name: str) -> bool:
        return name in self._available

    # -- helpers for assertions --

    def called_with_prefix(self, *prefix: str) -> bool:
        return any(call[: len(prefix)] == list(prefix) for call in self.calls)

    def first_call_with_prefix(self, *prefix: str) -> list[str] | None:
        for call in self.calls:
            if call[: len(prefix)] == list(prefix):
                return call
        return None

    def cwd_of_first_call_with_prefix(self, *prefix: str) -> Path | None:
        for call, cwd in zip(self.calls, self.call_cwds, strict=True):
            if call[: len(prefix)] == list(prefix):
                return cwd
        return None


# ---------------------------------------------------------------------------
# FakeDockerClient — pre-configured set of existing/running containers
# ---------------------------------------------------------------------------
class FakeDockerClient:
    def __init__(
        self,
        existing: set[str] | None = None,
        running: set[str] | None = None,
    ) -> None:
        self.existing: set[str] = set(existing or ())
        self.running: set[str] = set(running or ())
        self.stopped: list[str] = []
        self.started: list[str] = []

    def container_exists(self, name: str) -> bool:
        return name in self.existing

    def container_running(self, name: str) -> bool:
        return name in self.running

    def stop(self, name: str) -> None:
        if name in self.running:
            self.stopped.append(name)
            self.running.discard(name)

    def start(self, name: str) -> None:
        self.started.append(name)
        self.running.add(name)


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
def fake_docker() -> FakeDockerClient:
    return FakeDockerClient()


@pytest.fixture
def logger() -> Logger:
    return Logger(verbosity=0, strict=False, logfile=None)
