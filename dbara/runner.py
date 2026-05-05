from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from dbara.config import Config
from dbara.log import Logger


class CommandRunner:
    """Single choke-point for all external subprocess calls.

    Inject a FakeRunner in tests to record calls without executing anything.
    """

    def __init__(self, config: Config, logger: Logger) -> None:
        self._config = config
        self._logger = logger

    def run(
        self,
        cmd: list[str],
        *,
        check: bool = True,
        capture_output: bool = False,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self._logger.debug(f"$ {' '.join(cmd)}")
        return subprocess.run(
            cmd,
            check=check,
            capture_output=capture_output,
            text=True,
            cwd=str(cwd) if cwd else None,
        )

    def run_with_retry(
        self,
        cmd: list[str],
        **kwargs: bool | Path | None,
    ) -> subprocess.CompletedProcess[str]:
        """Run cmd with exponential backoff retry on failure."""
        attempt = 1
        while True:
            try:
                return self.run(cmd, **kwargs)  # type: ignore[arg-type]
            except subprocess.CalledProcessError as exc:
                if attempt >= self._config.retry_max:
                    self._logger.error(
                        f"Command failed after {attempt} attempt(s): {' '.join(cmd)}"
                    )
                    raise
                sleep_for = self._config.retry_base_sleep**attempt
                self._logger.warn(
                    f"Attempt {attempt} failed (rc={exc.returncode}), "
                    f"retrying in {sleep_for}s: {' '.join(cmd)}"
                )
                time.sleep(float(sleep_for))
                attempt += 1

    def run_io_niced(
        self,
        cmd: list[str],
        **kwargs: bool | Path | None,
    ) -> subprocess.CompletedProcess[str]:
        """Wrap cmd with ionice+nice when io_nice is enabled."""
        if self._config.io_nice:
            cmd = ["ionice", "-c2", "-n7", "nice", "-n", "19"] + cmd
        return self.run(cmd, **kwargs)  # type: ignore[arg-type]

    def tool_available(self, name: str) -> bool:
        return shutil.which(name) is not None
