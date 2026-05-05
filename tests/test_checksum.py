from __future__ import annotations

import time
from pathlib import Path

import pytest

from dbara.checksum import (
    checksum_suffix,
    hash_program,
    signature_of_dir,
    verify_checksum_file,
)
from tests.conftest import FakeRunner, Logger, make_config


# ---------------------------------------------------------------------------
# hash_program / checksum_suffix
# ---------------------------------------------------------------------------

def test_hash_program_prefers_xxh128sum_when_available() -> None:
    runner = FakeRunner()
    runner.set_available_tools("xxh128sum", "sha256sum")
    assert hash_program(fast_hash=True, runner=runner) == "xxh128sum"


def test_hash_program_falls_back_when_xxh128sum_unavailable() -> None:
    runner = FakeRunner()
    runner.set_available_tools("sha256sum")
    assert hash_program(fast_hash=True, runner=runner) == "sha256sum"


def test_hash_program_respects_fast_hash_false() -> None:
    runner = FakeRunner()
    runner.set_available_tools("xxh128sum", "sha256sum")
    assert hash_program(fast_hash=False, runner=runner) == "sha256sum"


def test_checksum_suffix_xxh() -> None:
    assert checksum_suffix("xxh128sum") == "xxh128"


def test_checksum_suffix_sha256() -> None:
    assert checksum_suffix("sha256sum") == "sha256sum"


# ---------------------------------------------------------------------------
# signature_of_dir — pure Python, fully unit-testable with tmp_path
# ---------------------------------------------------------------------------

def test_signature_stable_for_same_content(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "b.txt").write_text("world")
    sig1 = signature_of_dir(tmp_path)
    sig2 = signature_of_dir(tmp_path)
    assert sig1 == sig2


def test_signature_changes_after_file_modification(tmp_path: Path) -> None:
    f = tmp_path / "data.txt"
    f.write_text("original")
    sig_before = signature_of_dir(tmp_path)
    # Ensure mtime changes by writing new content (touches mtime)
    time.sleep(0.01)
    f.write_text("modified")
    sig_after = signature_of_dir(tmp_path)
    assert sig_before != sig_after


def test_signature_changes_after_file_addition(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a")
    sig_before = signature_of_dir(tmp_path)
    (tmp_path / "b.txt").write_text("b")
    sig_after = signature_of_dir(tmp_path)
    assert sig_before != sig_after


def test_signature_changes_after_file_deletion(tmp_path: Path) -> None:
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("a")
    f2.write_text("b")
    sig_before = signature_of_dir(tmp_path)
    f2.unlink()
    sig_after = signature_of_dir(tmp_path)
    assert sig_before != sig_after


def test_signature_empty_directory(tmp_path: Path) -> None:
    sig = signature_of_dir(tmp_path)
    assert isinstance(sig, str)
    assert len(sig) == 64  # SHA-256 hex digest


def test_signature_recurses_into_subdirectories(tmp_path: Path) -> None:
    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "nested.txt").write_text("nested")
    sig1 = signature_of_dir(tmp_path)
    (sub / "nested.txt").write_text("changed")
    sig2 = signature_of_dir(tmp_path)
    assert sig1 != sig2


# ---------------------------------------------------------------------------
# verify_checksum_file
# ---------------------------------------------------------------------------

def test_verify_checksum_warns_when_file_missing(tmp_path: Path) -> None:
    runner = FakeRunner()
    logger = Logger()
    result = verify_checksum_file(
        tmp_path, tmp_path / "nonexistent.sha256sum", runner, logger, fast_hash=False
    )
    assert result is True  # missing checksum is non-fatal
    assert any("missing" in w for w in logger.warnings)


def test_verify_checksum_returns_false_on_failed_line(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.preset_response(
        ["sha256sum"], returncode=1,
        stdout="file.txt: FAILED\n", stderr="",
    )
    checksum_file = tmp_path / "out.sha256sum"
    checksum_file.write_text("deadbeef  file.txt\n")
    logger = Logger()
    result = verify_checksum_file(tmp_path, checksum_file, runner, logger, fast_hash=False)
    assert result is False
    assert any("FAILED" in w for w in logger.warnings)


def test_verify_checksum_returns_true_on_clean_output(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.preset_response(["sha256sum"], stdout="file.txt: OK\n")
    checksum_file = tmp_path / "out.sha256sum"
    checksum_file.write_text("deadbeef  file.txt\n")
    logger = Logger()
    result = verify_checksum_file(tmp_path, checksum_file, runner, logger, fast_hash=False)
    assert result is True
    assert logger.warnings == []
