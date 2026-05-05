# Contributing to DBaRA

Thanks for your interest in contributing. This document covers how to set up a development
environment, the rules for submitting changes, and what to expect during code review.

---

## Ground Rules

- **Linux only (currently)** DBaRA uses `fcntl` for locking and is intentionally Linux-specific for the time being.

- **No runtime dependencies.** The package uses stdlib. Do not add third-party runtime dependencies. Dev/test dependencies are fine.

- **Tests are required.** Every non-trivial code change needs a corresponding test. The test suite uses `FakeRunner` and `FakeDockerClient` — no subprocess calls, no real Docker, no root.

- **Type annotations required.** All new code must pass `mypy --strict`. Do not use `Any` without a comment explaining why it cannot be avoided.

- **Keep it focused.** Fix one thing per PR. Separate refactors from feature additions.

---

## Development Setup

```bash
# Clone the repo
git clone https://github.com/NASible/DBaRA.git
cd DBaRA

# Create a virtualenv and install dev dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt -e .

# Verify everything works
pytest
```

---

## Running the Checks

All three checks must pass before opening a PR.

```bash
# Tests
pytest --tb=short -q

# Type checking
mypy dbara

# Linting
ruff check dbara
```

---

## Pull Request Process

1. **Fork** the repository and create a branch from `main`.

2. **Write tests** for your change. Aim to keep or improve coverage.

3. **Run all checks** locally (`pytest`, `mypy`, `ruff`) — CI will block on failures.

4. **Keep commits focused.** One logical change per commit with a clear message.

5. **Open the PR** against `main` and fill in the PR template.

6. A maintainer will review within a few days. Be responsive to review feedback.

---

## Reporting Bugs

Use the [Bug Report](.github/ISSUE_TEMPLATE/bug_report.yml) issue template and include:

- The exact `dbara` command you ran
- The full output (use `-v` or `-vv` to get more detail)
- Your:
  - OS 
  - Python version
  - Docker version
  - and DBaRA version (`dbara --version`)

---

## Code Style

- **Line length:** 100 characters (enforced by ruff).

- **Imports:** sorted by ruff (`I` ruleset) — run `ruff check --fix` to auto-fix.

- **Comments:** only when the *why* is non-obvious; never narrate what the code does.

- **No new global state** — all dependencies are injected (Config, Logger, Runner, DockerClient).
