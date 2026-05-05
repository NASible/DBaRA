from __future__ import annotations

from pathlib import Path

from dbara.hooks import run_hook
from tests.conftest import FakeRunner, Logger


def test_hook_called_when_executable(tmp_path: Path) -> None:
    runner = FakeRunner()
    hook = tmp_path / "myapp" / "pre-backup"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\necho hi")
    hook.chmod(0o755)
    run_hook("myapp", "pre-backup", tmp_path, runner, Logger())
    assert runner.called_with_prefix(str(hook))


def test_hook_skipped_when_absent(tmp_path: Path) -> None:
    runner = FakeRunner()
    run_hook("myapp", "pre-backup", tmp_path, runner, Logger())
    assert runner.calls == []


def test_hook_skipped_when_not_executable(tmp_path: Path) -> None:
    runner = FakeRunner()
    hook = tmp_path / "myapp" / "pre-backup"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\necho hi")
    hook.chmod(0o644)
    run_hook("myapp", "pre-backup", tmp_path, runner, Logger())
    assert runner.calls == []


def test_hook_call_passes_path_exactly(tmp_path: Path) -> None:
    runner = FakeRunner()
    hook = tmp_path / "myapp" / "post-backup"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\nexit 0")
    hook.chmod(0o755)
    run_hook("myapp", "post-backup", tmp_path, runner, Logger())
    assert runner.calls == [[str(hook)]]
