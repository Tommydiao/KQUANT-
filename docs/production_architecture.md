# Production Architecture

## Current Operating Boundary

KQUANT is a local, single-user US-stock research workstation. It provides
market-data research, deterministic signal review, AI research context, manual
plans, and an auditable Journal. It does not connect to accounts, positions,
orders, options, crypto, or execution.

## Target Architecture

| Component | Current local implementation | Production target | Gate |
| --- | --- | --- | --- |
| Frontend | React static build served by FastAPI | Vercel static frontend | Hosted API authentication and CORS review |
| API | Local FastAPI | Container/VM FastAPI | Staging health, latency, and no-trade route scan |
| Database | SQLite with versioned local schema | PostgreSQL | Adapter/query parity and restore drill |
| Cache/task lock | SQLite task idempotency rows | Redis | Concurrent task/load test |
| Schedule | Explicit local CLI scheduler runner | Cron or managed scheduler | Idempotency/retry validation |
| Reports/backups | Local outputs and verified SQLite copy | Object storage | Restore drill |
| Alerts | Web queue; optional email/Telegram env delivery | Personal notification channel | Secret handling and delivery smoke |

## Database Migration Contract

`kquant.database_migrations` versions the local SQLite schema and records each
applied migration. It recognizes a PostgreSQL URL only as a production target;
the active query runtime remains SQLite-only and deliberately blocks PostgreSQL
traffic until a tested adapter, query-parity suite, staging import, and restore
drill exist. This is a safety gate, not a hidden fallback.

Rollback is backup restoration, not destructive schema downgrade. Before every
production migration: make a verified backup, run a restore drill, run the
read-only route scan, then use a staging database first.

## Secrets And Network Boundaries

Longbridge, OpenAI, SMTP, and Telegram credentials are environment variables
only. They must not appear in Git, SQLite payloads, API responses, frontend
bundles, reports, or operational-event messages. Optional external alerts are
off unless `KQUANT_ENABLE_NOTIFICATIONS=true` and their channel configuration
is complete.
