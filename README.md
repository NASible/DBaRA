# DBaRA — Docker Backup and Restore Application

[![CI](https://github.com/NASible/DBaRA/actions/workflows/ci.yml/badge.svg)](https://github.com/NASible/DBaRA/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/dbara.svg)](https://pypi.org/project/dbara/)
[![Python](https://img.shields.io/pypi/pyversions/dbara.svg)](https://pypi.org/project/dbara/)

A production-ready Python CLI for backing up and restoring Docker application data directories.
Stops the container, archives the data, verifies integrity, and restarts.

## Features

- **change detection**
- **checksums**
- **retry logic**
- **hooks**
- **per-app locking**

## Requirements

- **Linux Desktop/Server OS**
- **Python 3.11+**
- **Docker** in `PATH`
- **zstd** or **gzip** (zstd recommended)
- **xxh128sum** (optional — falls back to sha256sum when absent)

## Installation

### From PyPI (recommended)

```bash
pipx install dbara
```

Or into an isolated virtualenv:

```bash
python3 -m venv /opt/dbara
/opt/dbara/bin/pip install dbara
ln -s /opt/dbara/bin/dbara /usr/local/bin/dbara
```

### From source

```bash
git clone https://github.com/NASible/DBaRA.git
cd DBaRA
pipx install .
```

Verify the install:

```bash
dbara --version
```

---

## Examples

### Backup — single app

Stop the container, archive the data directory, verify the checksum, then restart:

```bash
dbara -m backup \
  -a jellyfin \
  -d /srv/apps \
  -b /srv/backups \
  --keep-last 7 \
  -v
```

`--keep-last 7` automatically prunes archives older than the 7 most recent.  
`-v` enables debug output. Use `-vv` to also write a logfile.

### Backup — all apps

Iterate every subdirectory under `--app-folder-dir`, skipping apps whose contents have not
changed since the last backup:

```bash
dbara -m backup \
  -A \
  -d /srv/apps \
  -b /srv/backups \
  -p prod \
  --keep-last 7
```

`-p prod` inserts `prod` into every archive filename:
`myhost_prod_jellyfin_20240615_020000.bkup.tar.zst`

### Backup — force even when unchanged

```bash
dbara -m backup -a sonarr -d /srv/apps -b /srv/backups -f
```

`-f / --force` bypasses change detection and always creates a new archive.

---

### Restore — single app (latest archive)

Auto-selects the most recent archive for the app by modification time:

```bash
dbara -m restore \
  -a jellyfin \
  -d /srv/apps \
  -b /srv/backups \
  -r /srv/apps \
  -o 1000:1000
```

`-o 1000:1000` runs `chown -R 1000:1000` on the restored directory.

### Restore — single app (specific archive)

Pass the archive path directly to `--backup-dest-dir` to restore a particular snapshot:

```bash
dbara -m restore \
  -a jellyfin \
  -d /srv/apps \
  -b /srv/backups/myhost_jellyfin_20240615_020000.bkup.tar.zst \
  -r /srv/apps
```

### Restore — several specific apps

`--apps` takes a space-separated list and restores each one sequentially:

```bash
dbara -m restore \
  --apps authelia authentik vaultwarden \
  -d /srv/apps \
  -b /srv/backups \
  -r /srv/apps \
  --ownership-map /etc/dbara/owners.txt
```

Using `--ownership-map` instead of `-o` applies the right ownership per app automatically.

### Restore — all apps

Auto-discovers every app present in the backup directory and restores each one.
Useful after a full server rebuild:

```bash
dbara -m restore \
  -A \
  -d /srv/apps \
  -b /srv/backups \
  -r /srv/apps \
  --ownership-map /etc/dbara/owners.txt \
  -v
```

> **Note:** `-A` for restore infers app names from archive filenames. App names that contain
> underscores (e.g. `my_app`) will not be auto-discovered — use `--apps` explicitly for those.

### Restore — without restarting the container

```bash
dbara -m restore \
  -a sonarr \
  -d /srv/apps \
  -b /srv/backups \
  -r /srv/apps \
  -s
```

`-s / --no-start-container` extracts the data but leaves the container stopped.

---

## Archive Filename Format

```text
{hostname}_{prefix_}{app}_{YYYYMMDD_HHMMSS}.bkup.tar.{ext}
```

Examples:

| Scenario | Filename |
| -------- | -------- |
| No prefix, zstd | `myhost_jellyfin_20240615_020000.bkup.tar.zst` |
| With prefix "prod" | `myhost_prod_jellyfin_20240615_020000.bkup.tar.zst` |
| gzip compressor | `myhost_jellyfin_20240615_020000.bkup.tar.tgz` |

Checksum sidecar files sit next to the archive:

- `...bkup.tar.zst.xxh128` (when xxh128sum is available)
- `...bkup.tar.zst.sha256sum` (fallback)

---

## CLI Reference

### Required flags

| Flag | Description |
| ---- | ----------- |
| `-m, --mode` | Operation: `backup` or `restore` |
| `-d, --app-folder-dir` | Parent directory containing per-app folders |
| `-b, --backup-dest-dir` | Backup destination directory (or specific archive file for restore) |

### Common options

| Flag | Default | Description |
| ---- | ------- | ----------- |
| `-a, --app-name` | — | Single app to back up or restore |
| `--apps APP [APP ...]` | — | Restore a specific list of apps (restore mode only) |
| `-A, --all-apps` | — | Backup: every subdirectory under `--app-folder-dir`; Restore: every app found in `--backup-dest-dir` |
| `-r, --restore-dest-dir` | — | Where to extract restored files |
| `-o, --owner-group` | — | Set `user:group` ownership after restore (e.g. `1000:1000`) |
| `-p, --optional-prefix` | — | Prefix inserted in the archive filename |
| `-x, --remove-after-backup` | off | Delete app directory after backup (**archive integrity verified first**) |
| `-s, --no-start-container` | off | Do not restart the container after the operation |
| `-f, --force` | off | Force backup even when no changes are detected |
| `--strict` | off | Treat any warning as a fatal error |
| `--skip-checksum` | off | Skip checksum generation/verification |
| `-v, --verbose` | — | `-v` enables debug output; `-vv` also writes a logfile |

### Performance / behaviour

| Flag | Default | Description |
| ---- | ------- | ----------- |
| `--compress` | `zstd` | Compressor: `zstd` or `gzip` |
| `--zstd-opts` | `-T0 -3` | Options forwarded to `zstd` |
| `--fast-hash / --no-fast-hash` | enabled | Prefer `xxh128sum` over `sha256sum` when available |
| `--io-nice / --no-io-nice` | enabled | Wrap heavy I/O with `ionice -c2 -n7 nice -n 19` |
| `--keep-last N` | `0` (disabled) | Prune all but the last N archives per app |
| `--state-dir` | `/var/lib/app-backup/state` | Directory for change-detection `.sig` state files |
| `--hooks-dir` | `/etc/app-backup/hooks` | Root directory for per-app hook scripts |
| `--lock-dir` | `/var/lock` | Directory for per-app lock files |
| `--ownership-map` | — | File mapping app names to `user:group` ownership |
| `--stop-timeout` | `30` | Seconds passed to `docker stop -t` |
| `--retry-max` | `5` | Maximum retry attempts for shell commands |
| `--retry-base-sleep` | `2` | Base sleep for exponential backoff: `base ** attempt` seconds |
| `--logfile` | `/var/log/app-backup-restore.log` | Log file path (written when `-vv` is active) |

---

## Hooks

Place executable scripts at `HOOKS_DIR/<app>/<hook-name>`:

```text
/etc/app-backup/hooks/
├── jellyfin/
│   ├── pre-backup
│   ├── post-backup
│   ├── pre-restore
│   └── post-restore
└── sonarr/
    └── pre-backup
```

Hook scripts receive no arguments. The backup or restore is **aborted** if a hook exits non-zero
(subject to `--retry-max` retries with exponential backoff).

Example pre-backup hook that flushes a database:

```bash
#!/bin/bash
sqlite3 /srv/apps/myapp/data.db "PRAGMA wal_checkpoint(FULL);"
```

---

## Ownership Map

Use `--ownership-map` to map app names to `user:group` ownership without specifying `-o` on every
restore command:

```ini
# /etc/app-backup/owners.txt
jellyfin=1000:1000
sonarr=1001:1001
radarr=1001:1001
# Lines starting with # are ignored
```

```bash
dbara -m restore -a jellyfin -d /srv/apps -b /srv/backups -r /srv/apps \
  --ownership-map /etc/app-backup/owners.txt
```

If `--owner-group` is also specified it takes precedence over the map file.

---

## Change Detection

DBaRA computes a SHA-256 digest over the sorted list of `(relative_path, file_size, mtime_ns)`
tuples for every file under the app directory. The digest is stored as a `.sig` file in
`--state-dir`. If the digest is unchanged since the last run, the backup is skipped.

- Use `-f / --force` to override and backup anyway.
- State files are per-app: `{state-dir}/{app}.sig`.

---

## SQLite Safe Backup

Before archiving, DBaRA automatically creates consistent hot-backup copies of every SQLite
database it finds (`.sqlite`, `.sqlite3`, `.db`) using Python's built-in `sqlite3.backup()`.
The copies are stored as `<file>.bak` alongside the originals, included in the archive, and then
deleted after the tar operation completes.

This ensures the archive contains a consistent point-in-time snapshot even if the application
was writing to the database at the time of backup.

---

## Running as a Scheduled Job

### systemd timer (recommended)

```ini
# /etc/systemd/system/dbara-backup.timer
[Unit]
Description=Nightly DBaRA backup

[Timer]
OnCalendar=*-*-* 02:00:00
RandomizedDelaySec=300
Persistent=true

[Install]
WantedBy=timers.target
```

```ini
# /etc/systemd/system/dbara-backup.service
[Unit]
Description=DBaRA backup

[Service]
Type=oneshot
ExecStart=/usr/local/bin/dbara -m backup -A \
  -d /srv/apps -b /srv/backups \
  --keep-last 7 -vv
```

```bash
systemctl enable --now dbara-backup.timer
```

### cron

```cron
0 2 * * * root /usr/local/bin/dbara -m backup -A -d /srv/apps -b /srv/backups --keep-last 7
```

---

## Deployment with Ansible

An Ansible role is available in a separate repository:
[**NASible/ansible-role-dbara**](https://github.com/NASible/ansible-role-dbara)

```bash
ansible-galaxy install nasible.dbara
```

The role installs DBaRA into a virtualenv, creates required directories,
and configures a systemd timer for scheduled backups.

---

## Development

```bash
# Install dev dependencies
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt -e .

# Run tests
.venv/bin/pytest

# Type-check
.venv/bin/mypy dbara

# Lint
.venv/bin/ruff check dbara tests
```

All tests are pure unit tests — no Docker, no real filesystem writes (except where `tmp_path`
is used), no subprocess calls. The `FakeRunner` and `FakeDockerClient` test doubles in
`tests/conftest.py` cover every code path without touching the system.
