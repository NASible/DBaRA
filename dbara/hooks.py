from __future__ import annotations

import os
from pathlib import Path

from dbara.log import Logger
from dbara.runner import CommandRunner


def run_hook(
    app: str,
    hook_name: str,
    hooks_dir: Path,
    runner: CommandRunner,
    logger: Logger,
) -> None:
    """Execute the named hook script for app if it exists and is executable."""
    hook_path = hooks_dir / app / hook_name
    if hook_path.is_file() and os.access(hook_path, os.X_OK):
        logger.info(f"Running hook: {hook_path}")
        runner.run_with_retry([str(hook_path)])
    else:
        logger.debug(f"No hook found for {app}/{hook_name}")
