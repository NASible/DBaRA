from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from dbara.runner import CommandRunner
from tests.conftest import make_config, Logger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _runner(retry_max: int = 3, retry_base_sleep: int = 2, io_nice: bool = False) -> CommandRunner:
    config = make_config(retry_max=retry_max, retry_base_sleep=retry_base_sleep, io_nice=io_nice)
    return CommandRunner(config=config, logger=Logger())


# ---------------------------------------------------------------------------
# run_with_retry — retry count and backoff
# ---------------------------------------------------------------------------

def test_retry_succeeds_on_first_attempt() -> None:
    runner = _runner()
    completed = subprocess.CompletedProcess(["echo"], 0, "ok", "")
    with patch("subprocess.run", return_value=completed) as mock_run:
        result = runner.run_with_retry(["echo", "hi"])
    assert result.returncode == 0
    assert mock_run.call_count == 1


def test_retry_succeeds_on_second_attempt() -> None:
    runner = _runner(retry_max=3, retry_base_sleep=1)
    fail = subprocess.CalledProcessError(1, ["cmd"])
    success = subprocess.CompletedProcess(["cmd"], 0, "", "")
    with (
        patch("subprocess.run", side_effect=[fail, success]),
        patch("time.sleep") as mock_sleep,
    ):
        result = runner.run_with_retry(["cmd"])
    assert result.returncode == 0
    mock_sleep.assert_called_once_with(1.0)  # 1 ** 1 = 1


def test_retry_exhausts_and_raises() -> None:
    runner = _runner(retry_max=3, retry_base_sleep=2)
    fail = subprocess.CalledProcessError(1, ["cmd"])
    with (
        patch("subprocess.run", side_effect=fail),
        patch("time.sleep"),
    ):
        with pytest.raises(subprocess.CalledProcessError):
            runner.run_with_retry(["cmd"])


def test_retry_sleep_uses_exponential_backoff() -> None:
    runner = _runner(retry_max=4, retry_base_sleep=2)
    fail = subprocess.CalledProcessError(1, ["cmd"])
    success = subprocess.CompletedProcess(["cmd"], 0, "", "")
    with (
        patch("subprocess.run", side_effect=[fail, fail, fail, success]),
        patch("time.sleep") as mock_sleep,
    ):
        runner.run_with_retry(["cmd"])
    # attempt 1 → sleep 2^1=2, attempt 2 → sleep 2^2=4, attempt 3 → sleep 2^3=8
    mock_sleep.assert_has_calls([call(2.0), call(4.0), call(8.0)])


# ---------------------------------------------------------------------------
# run_io_niced — ionice/nice prepend
# ---------------------------------------------------------------------------

def test_io_nice_prepends_ionice_when_enabled() -> None:
    runner = _runner(io_nice=True)
    captured: list[list[str]] = []

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        captured.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with patch.object(runner, "run", side_effect=fake_run):
        runner.run_io_niced(["tar", "-cf", "out.tar", "app"])

    assert captured[0][:6] == ["ionice", "-c2", "-n7", "nice", "-n", "19"]
    assert captured[0][6:] == ["tar", "-cf", "out.tar", "app"]


def test_io_nice_skips_prepend_when_disabled() -> None:
    runner = _runner(io_nice=False)
    captured: list[list[str]] = []

    def fake_run(cmd: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        captured.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with patch.object(runner, "run", side_effect=fake_run):
        runner.run_io_niced(["tar", "-cf", "out.tar", "app"])

    assert captured[0] == ["tar", "-cf", "out.tar", "app"]


# ---------------------------------------------------------------------------
# tool_available
# ---------------------------------------------------------------------------

def test_tool_available_true() -> None:
    runner = _runner()
    with patch("shutil.which", return_value="/usr/bin/zstd"):
        assert runner.tool_available("zstd") is True


def test_tool_available_false() -> None:
    runner = _runner()
    with patch("shutil.which", return_value=None):
        assert runner.tool_available("xxh128sum") is False
