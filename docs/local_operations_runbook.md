# Local Operations Runbook

## Daily Checks

```powershell
.\.venv\Scripts\python.exe -m kquant database-status
.\.venv\Scripts\python.exe -m kquant operations-health
.\.venv\Scripts\python.exe -m kquant run-local-task --name preflight --key 2026-07-23
```

Candidate refresh is deliberately explicit because it invokes market-data
providers:

```powershell
.\.venv\Scripts\python.exe -m kquant run-local-task --name candidate_refresh --key 2026-07-23-regular --enable-market-scan
```

The task runner records an idempotency key, execution attempt, result, and
failure event. Repeating a completed key does not repeat the work.

## Alerts

Web alerts are stored locally and can cover new buy setups, watch entry zones,
hard vetoes, data anomalies, and manual-plan invalidations. Optional `email`
and `telegram` delivery require an explicit opt-in and read their credentials
only from the local environment. No credential is persisted.

## Backup And Restore Drill

```powershell
.\.venv\Scripts\python.exe -m kquant backup-local --backup-dir work\backups
.\.venv\Scripts\python.exe -m kquant restore-drill --backup-path work\backups\kquant-us-YYYYMMDDTHHMMSSZ.sqlite3
```

`restore-drill` copies the backup to a temporary location, checks SQLite
integrity, and never replaces the active database. A real recovery requires a
separate, operator-confirmed replacement of a stopped local runtime; keep the
broken database as evidence until the restored copy is verified.
