# KQUANT v2 Week 2 Report: Explicit Schema Migrations

Date: 2026-08-16
Branch: `codex/kquant-v2-gap-analysis`
Starting baseline: `988ad6c docs(v2): add master plan and architecture gap analysis`

## 1. Objective and completion

Week 2 replaced the legacy schema-on-connect implementation with an explicit,
versioned SQLite migration registry while preserving the existing runtime API
and research data.

Completion status: complete.

## 2. Runtime and schema changes

- Added `kquant.db` with migration registry, ordered versions, checksums,
  forward-only execution, migration audit rows, schema fingerprints, and schema
  quarantine records.
- Kept the existing `kquant.database_migrations` functions as a compatibility
  facade for existing CLI and application callers.
- Moved the legacy schema bootstrap out of `stock_store.connect()`. The function
  now reaches the explicit migration runner before returning a compatibility
  connection.
- Added migration v2, `explicit_schema_migration_framework`.
- Added a non-mutating `database-status` inspection path and explicit
  `migrate-database` CLI command.
- Added migration state and schema fingerprint to `/api/health`.
- Registered six historical non-runtime tables as quarantined. They remain in
  SQLite unchanged and are not exposed through active routes.

## 3. Real database migration and preservation check

Pre-migration backup:

`work/backups/kquant-us-pre-v2-schema-20260816T115651Z.sqlite3`

Restore drill: passed, `PRAGMA integrity_check = ok`, active database was not
overwritten.

The active `work/kquant_us.sqlite3` is now schema version 2 with a verified
schema fingerprint. The migration added metadata only. The following core row
counts matched exactly before and after migration:

| Table group | Before | After |
| --- | ---: | ---: |
| Universe | 296 | 296 |
| Canonical candles | 69,362 | 69,362 |
| Candle observations | 69,615 | 69,615 |
| Legacy candles | 93,471 | 93,471 |
| Labels | 80,248 | 80,248 |
| Signals and features | 1,453 / 1,453 | 1,453 / 1,453 |
| Provider events | 327,079 | 327,079 |
| Validation datasets/runs/trades | 0 / 0 / 0 | 0 / 0 / 0 |
| Instructions and alerts | 0 / 0 | 0 / 0 |
| Option observation tables | 0 / 0 / 0 | 0 / 0 / 0 |

## 4. Tests and browser/runtime verification

- Python: `161 passed`.
- Frontend: `2 passed`.
- Production build: passed; Vite retains the existing 527.55 kB JavaScript
  bundle warning.
- Read-only boundary: passed, 80 routes, no account/trade/order submission path.
- `/api/health`: returns `database_schema_version = 2`, migration status
  `up_to_date`, `checksum_verified = true`, and a schema fingerprint.
- `git diff --check`: passed.

## 5. Leakage and operational review

- No historical research data was backfilled or rewritten during this migration.
- New model, Theme, and Options logic remains out of scope.
- Legacy schema bootstrap is transactional for a fresh database. It is retained
  only as migration v1; later schema changes must be new, explicit migrations.
- Existing Longbridge coverage, survivorship risk, provider-event retention, and
  feature/label lineage remain Week 3-4 work.
- The local server did not receive Longbridge environment variables in this
  shell, so its health view correctly reports provider standby. This is an
  environment/runtime configuration state, not a schema migration failure.

## 6. Gate decision

Decision: `GO_WEEK_3_DATA_SNAPSHOTS`.

Week 2 gates passed: fresh database initialization, legacy database upgrade,
repeat migration, checksum mismatch fail-closed behavior, backup/restore, and
historical row-count preservation all verified.

## 7. Commit and rollback

Planned commit: `feat(db): add explicit schema migration framework`.

Rollback for the active database is restoration of the verified pre-migration
backup above. Application-code rollback is a normal Git revert; no destructive
database downgrade is provided.

## 8. Next week

Week 3 adds immutable Data Snapshot contracts with source, `as_of`,
`available_at`, `fetched_at`, item hashes, source eligibility, and point-in-time
universe semantics. It will not begin Theme, model, or Options implementation.
