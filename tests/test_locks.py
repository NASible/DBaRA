from __future__ import annotations

import fcntl
import os
from pathlib import Path

import pytest

from dbara.locks import LockError, app_lock


def test_lock_acquires_without_error(tmp_path: Path) -> None:
    with app_lock("myapp", tmp_path):
        pass


def test_lock_file_is_created(tmp_path: Path) -> None:
    with app_lock("myapp", tmp_path):
        pass
    assert (tmp_path / "app-backup-myapp.lock").exists()


def test_lock_raises_when_already_held(tmp_path: Path) -> None:
    lock_path = tmp_path / "app-backup-myapp.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(LockError, match="myapp"):
            with app_lock("myapp", tmp_path):
                pass
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_lock_released_after_context_exit(tmp_path: Path) -> None:
    with app_lock("myapp", tmp_path):
        pass
    with app_lock("myapp", tmp_path):
        pass  # acquirable again — lock was released
