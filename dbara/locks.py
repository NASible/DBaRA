from __future__ import annotations

import fcntl
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path


class LockError(RuntimeError):
    pass


@contextmanager
def app_lock(app: str, lock_dir: Path) -> Generator[None, None, None]:
    """Non-blocking exclusive flock for an app. Raises LockError if already held."""
    lock_path = lock_dir / f"app-backup-{app}.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY)
    acquired = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as exc:
            raise LockError(f"Another backup is already running for {app!r}") from exc
        yield
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
