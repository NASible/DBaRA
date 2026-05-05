from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import NoReturn

_RESET = "\033[0m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"


class Logger:
    def __init__(
        self,
        verbosity: int = 0,
        strict: bool = False,
        logfile: Path | None = None,
    ) -> None:
        self.verbosity = verbosity
        self.strict = strict
        self.logfile = logfile
        self.warnings: list[str] = []

    def _ts(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _write_log(self, level: str, msg: str) -> None:
        if self.logfile is not None and self.verbosity >= 2:
            try:
                with self.logfile.open("a") as fh:
                    fh.write(f"[{level}] {self._ts()} - {msg}\n")
            except OSError:
                pass

    def info(self, msg: str) -> None:
        print(f"[INFO] {self._ts()} - {msg}")
        self._write_log("INFO", msg)

    def warn(self, msg: str) -> None:
        print(f"{_YELLOW}[WARN] {self._ts()} - {msg}{_RESET}")
        self._write_log("WARN", msg)
        self.warnings.append(msg)
        if self.strict:
            self.fatal("Strict mode enabled: treating warning as fatal error.")

    def error(self, msg: str) -> None:
        print(f"{_RED}[ERROR] {self._ts()} - {msg}{_RESET}", file=sys.stderr)
        self._write_log("ERROR", msg)

    def debug(self, msg: str) -> None:
        if self.verbosity >= 1:
            print(f"{_CYAN}[DEBUG] {self._ts()} - {msg}{_RESET}")
            self._write_log("DEBUG", msg)

    def fatal(self, msg: str) -> NoReturn:
        self.error(msg)
        raise SystemExit(1)

    def print_summary(self) -> None:
        print()
        if self.warnings:
            print(f"{_YELLOW}============================================")
            print("Summary of Warnings Encountered:")
            for w in self.warnings:
                print(f"- {w}")
            print(f"============================================{_RESET}")
        else:
            print(f"{_GREEN}✅ No warnings encountered.{_RESET}")
