from __future__ import annotations

import pytest

from dbara.docker_ops import DockerClient
from tests.conftest import FakeRunner, Logger


def _client(
    runner: FakeRunner,
    stop_timeout: int = 30,
    start_container: bool = True,
) -> DockerClient:
    return DockerClient(
        runner=runner,
        logger=Logger(),
        stop_timeout=stop_timeout,
        start_container=start_container,
    )


# ---------------------------------------------------------------------------
# container_exists / container_running
# ---------------------------------------------------------------------------

def test_container_exists_true_when_output_nonempty() -> None:
    runner = FakeRunner()
    runner.preset_response(["docker", "ps", "-a"], stdout="abc123\n")
    assert _client(runner).container_exists("myapp") is True


def test_container_exists_false_when_output_empty() -> None:
    runner = FakeRunner()
    runner.preset_response(["docker", "ps", "-a"], stdout="")
    assert _client(runner).container_exists("myapp") is False


def test_container_running_true_when_output_nonempty() -> None:
    runner = FakeRunner()
    runner.preset_response(["docker", "ps", "-q"], stdout="abc123\n")
    assert _client(runner).container_running("myapp") is True


def test_container_running_false_when_output_empty() -> None:
    runner = FakeRunner()
    runner.preset_response(["docker", "ps", "-q"], stdout="")
    assert _client(runner).container_running("myapp") is False


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------

def test_stop_calls_docker_stop_when_running() -> None:
    runner = FakeRunner()
    # container_exists returns True, container_running returns True
    runner.preset_response(["docker", "ps", "-a"], stdout="id1\n")
    runner.preset_response(["docker", "ps", "-q"], stdout="id1\n")
    _client(runner, stop_timeout=15).stop("myapp")
    assert runner.called_with_prefix("docker", "stop", "-t", "15", "myapp")


def test_stop_skips_when_container_not_running() -> None:
    runner = FakeRunner()
    runner.preset_response(["docker", "ps", "-a"], stdout="id1\n")  # exists
    runner.preset_response(["docker", "ps", "-q"], stdout="")        # not running
    _client(runner).stop("myapp")
    assert not runner.called_with_prefix("docker", "stop")


def test_stop_skips_when_container_does_not_exist() -> None:
    runner = FakeRunner()
    runner.preset_response(["docker", "ps", "-a"], stdout="")  # doesn't exist
    _client(runner).stop("myapp")
    assert not runner.called_with_prefix("docker", "stop")


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------

def test_start_calls_docker_start() -> None:
    runner = FakeRunner()
    runner.preset_response(["docker", "ps", "-a"], stdout="id1\n")  # exists
    runner.preset_response(["docker", "ps", "-q"], stdout="")        # not running
    _client(runner).start("myapp")
    assert runner.called_with_prefix("docker", "start", "myapp")


def test_start_skips_when_disabled() -> None:
    runner = FakeRunner()
    _client(runner, start_container=False).start("myapp")
    assert not runner.called_with_prefix("docker", "start")


def test_start_skips_when_already_running() -> None:
    runner = FakeRunner()
    runner.preset_response(["docker", "ps", "-a"], stdout="id1\n")  # exists
    runner.preset_response(["docker", "ps", "-q"], stdout="id1\n")  # already running
    _client(runner).start("myapp")
    assert not runner.called_with_prefix("docker", "start")


def test_start_skips_when_container_absent() -> None:
    runner = FakeRunner()
    runner.preset_response(["docker", "ps", "-a"], stdout="")  # doesn't exist
    _client(runner).start("myapp")
    assert not runner.called_with_prefix("docker", "start")
