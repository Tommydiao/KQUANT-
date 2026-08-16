# KQUANT v2 Week 3 Report: Data Snapshot and Point-in-Time Contract

Date: 2026-08-16
Branch: `codex/kquant-v2-gap-analysis`
Starting baseline: `8053044 feat(db): add explicit schema migration framework`

## 1. Objective and completion

Week 3 introduced an immutable market-data snapshot contract so later Theme and
model work can identify exactly which closed, source-qualified observations were
available at a decision time.

Completion status: complete.

## 2. Changes

- Added schema migration v3, `data_snapshot_contract`.
- Added immutable `data_snapshots` and `data_snapshot_items` tables.
- Added source policy `market_source_eligibility_v1`.
- Every stored snapshot item carries source, market `as_of_time`, conservative
  `available_at`, `fetched_at`, eligibility status, exclusion reason, payload,
  and content hash.
- Added deterministic snapshot IDs derived from the snapshot content hash.
- Added `GET /api/data/snapshots/{snapshot_id}`.
- Added `resolve_universe_membership()`, which resolves only exact or prior
  observed snapshots. It never substitutes future membership and always labels
  the current runtime snapshot history `survivorship_limited`.
- Updated API contract version to `kquant-api-2026-08-16-data-snapshot-v1`.

## 3. Source and leakage behavior

- Only closed, `longbridge_candles`, `available` observations can be eligible
  for model input.
- Yahoo and fixture sources remain stored as reference evidence but are marked
  `reference_only` and cannot satisfy model eligibility.
- Forming candles are counted as exclusions and do not enter snapshot items.
- Candles fetched after the requested cutoff do not enter a historical snapshot,
  even when their market timestamp is earlier.
- Current universe snapshots remain usable provenance but are not a complete
  historical constituent dataset; all such resolutions are model-ineligible
  until historical membership evidence is added.

## 4. Real database migration and preservation

Pre-migration backup:

`work/backups/kquant-us-pre-data-snapshot-20260816T121824Z.sqlite3`

Restore drill: passed, `PRAGMA integrity_check = ok`, with no active database
overwrite.

The active database is now schema version 3. Migration v3 added empty contract
tables only. Core universe, canonical/legacy candles, labels, signals, features,
provider events, validation, instruction, alert, and options-observation counts
matched exactly before and after migration.

## 5. Tests and runtime verification

- Python: `165 passed`.
- Frontend: `2 passed`.
- Production build: passed; existing 527.55 kB Vite chunk warning remains.
- Read-only boundary: passed; 81 routes, no account/trade/order submission path.
- Local server: `http://127.0.0.1:8001/`.
- `/api/health`: confirms API contract `kquant-api-2026-08-16-data-snapshot-v1`,
  schema version 3, verified migration checksum, and 81 safe routes.
- New regression cases prove deterministic re-creation, future-candle isolation,
  forming-candle exclusion, Yahoo reference isolation, and no future-universe
  membership backfill.

## 6. Gate decision

Decision: `GO_WEEK_4_DATA_COVERAGE`.

Week 3 snapshot integrity gates pass. The programme remains `NO_GO` for
predictive modeling because Longbridge daily/1H coverage and historical universe
membership are still below their required thresholds.

## 7. Commit and rollback

Planned commit: `feat(data): add immutable point-in-time snapshots`.

Rollback for the active database is restoration of the verified pre-v3 backup.
No destructive schema downgrade is attempted.

## 8. Next week

Week 4 unifies the code and database universe into a versioned registry, adds a
coverage/gap/adjustment/company-action workbench, and builds a controlled
Longbridge backfill queue. It does not start Theme, model, or Options logic.
