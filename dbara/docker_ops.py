from __future__ import annotations

from dbara.log import Logger
from dbara.runner import CommandRunner


class DockerClient:
    def __init__(
        self,
        runner: CommandRunner,
        logger: Logger,
        stop_timeout: int,
        start_container: bool,
    ) -> None:
        self._runner = runner
        self._logger = logger
        self._stop_timeout = stop_timeout
        self._start_container = start_container

    def container_exists(self, name: str) -> bool:
        result = self._runner.run(
            ["docker", "ps", "-a", "-q", "--filter", f"name=^/{name}$"],
            capture_output=True,
        )
        return bool(result.stdout.strip())

    def container_running(self, name: str) -> bool:
        result = self._runner.run(
            ["docker", "ps", "-q", "--filter", f"name=^/{name}$"],
            capture_output=True,
        )
        return bool(result.stdout.strip())

    def stop(self, name: str) -> None:
        if not self.container_exists(name):
            self._logger.info(f"No container named {name!r} exists; skipping stop.")
            return
        if not self.container_running(name):
            self._logger.info(f"Container {name!r} exists but is not running; nothing to stop.")
            return
        self._logger.info(f"Stopping container {name!r} (timeout {self._stop_timeout}s)...")
        self._runner.run_with_retry(["docker", "stop", "-t", str(self._stop_timeout), name])

    def start(self, name: str) -> None:
        if not self._start_container:
            self._logger.info("Start container disabled by user.")
            return
        if not self.container_exists(name):
            self._logger.info(f"No container named {name!r} exists; skipping start.")
            return
        if self.container_running(name):
            self._logger.info(f"Container {name!r} already running; no start needed.")
            return
        self._logger.info(f"Starting container {name!r}...")
        self._runner.run_with_retry(["docker", "start", name])
