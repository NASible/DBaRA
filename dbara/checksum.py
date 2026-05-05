from __future__ import annotations

import hashlib
import os
from pathlib import Path

from dbara.log import Logger
from dbara.runner import CommandRunner


def hash_program(fast_hash: bool, runner: CommandRunner) -> str:
    """Return 'xxh128sum' if fast_hash is enabled and the tool is available, else 'sha256sum'."""
    if fast_hash and runner.tool_available("xxh128sum"):
        return "xxh128sum"
    return "sha256sum"


def checksum_suffix(program: str) -> str:
    return "xxh128" if program == "xxh128sum" else "sha256sum"


def create_checksum_file(
    app: str,
    backup_path: Path,
    base_dir: Path,
    runner: CommandRunner,
    logger: Logger,
    fast_hash: bool,
) -> Path:
    """Generate a checksum file for all files under base_dir/app.

    The file is named {backup_path}.sha256sum or {backup_path}.xxh128 and uses
    the same format as sha256sum/xxh128sum so it can be verified externally.
    """
    import shlex

    hasher = hash_program(fast_hash, runner)
    suffix = checksum_suffix(hasher)
    out_path = Path(str(backup_path) + f".{suffix}")
    logger.info(f"Generating {hasher} checksums -> {out_path.name}")
    # Pipe find → xargs → hasher, with output redirect — requires a shell for the pipeline.
    # All dynamic values are shlex-quoted; none come from user input at this point.
    shell_cmd = (
        f"find {shlex.quote(app)} -type f -print0 "
        f"| xargs -0 {shlex.quote(hasher)} "
        f"> {shlex.quote(str(out_path))}"
    )
    runner.run_io_niced(["bash", "-c", shell_cmd], cwd=base_dir)
    return out_path


def verify_checksum_file(
    restore_path: Path,
    checksum_file: Path,
    runner: CommandRunner,
    logger: Logger,
    fast_hash: bool,
) -> bool:
    """Verify restore_path contents against checksum_file.

    Returns True if all checksums pass (or file missing — non-fatal).
    Returns False and logs warnings on any mismatch.
    """
    if not checksum_file.is_file():
        logger.warn(f"Checksum file {checksum_file} missing, skipping verification.")
        return True

    hasher = hash_program(fast_hash, runner)
    logger.info(f"Verifying checksums with {hasher}...")
    result = runner.run(
        [hasher, "-c", str(checksum_file)],
        cwd=restore_path,
        capture_output=True,
        check=False,
    )
    failed = False
    for line in (result.stdout + result.stderr).splitlines():
        if "FAILED" in line or "No such file" in line:
            logger.warn(f"Checksum issue: {line}")
            failed = True
    return not failed


def signature_of_dir(directory: Path) -> str:
    """Pure-Python change-detection signature.

    Walks directory, collects (relative_path, size, mtime_ns) for every file
    sorted by path, then returns a hex SHA-256 digest. Fully unit-testable
    without subprocess.

    NOTE: Incompatible with the bash version's .sig files (which used
    find -printf | xxh128sum). On first Python run, every app will appear
    changed and receive one unconditional backup — safe by design.
    """
    h = hashlib.sha256()
    entries: list[tuple[str, int, int]] = []
    for dirpath, _dirs, filenames in os.walk(directory):
        for fname in filenames:
            full = Path(dirpath) / fname
            try:
                st = full.stat()
            except OSError:
                continue
            rel = str(full.relative_to(directory))
            entries.append((rel, st.st_size, st.st_mtime_ns))
    for rel, size, mtime_ns in sorted(entries):
        h.update(f"{rel}\x00{size}\x00{mtime_ns}\n".encode())
    return h.hexdigest()
