# 999.txt implementation checkpoint

## Implemented in this checkpoint

- Frozen `crypto_roll_v1.0.0` remains separate from `crypto_early_v1.0.0`.
- Roll actions, actual ETHU/MSTU instrument mappings, realized-profit-only
  capital, floating-loss add block and point-in-time metadata are persisted.
- Bayesian `BULL / ACCUMULATION / DISTRIBUTION / BEAR_STRESS` posterior and
  fixed-seed Monte Carlo research outputs remain fail-closed when history or
  source timing is insufficient. Monte Carlo now supports optional
  regime-conditioned input and keeps risk-of-ruin within a path probability.
- External ETF, derivatives, on-chain and whale evidence has a registered
  source contract, optional configured JSON feed adapter, published/source /
  available timestamps, missing-field tracking and content hashes. Missing
  values remain `N/A`; no synthetic values are created.
- Validation now reports outcomes by action and asset group (`btc_eth`,
  `ethu`, `mstr`, `mstu`, `crypto_alt`) in addition to the locked date split.
- Added a NumPy Quantile Regression challenger baseline. LightGBM remains
  deferred and cannot influence EVAL.
- Added 20 Crypto and 20 Stock frozen golden contract cases. These are
  regression fixtures, not market-performance evidence.
- Added Schema 16 Shadow Observation Ledger with user review, immutable
  outcome records, audit events and a real-calendar 15-day gate.
- Added secret-free operations observability, staging readiness status,
  explicit SQLite backup/restore helpers and a local read-only gateway at
  `http://127.0.0.1:8020/`.
- PWA Service Worker no longer caches API responses or the unversioned root
  HTML; only versioned assets, manifest and favicon are cacheable.

## Verified

- Python: `186 passed`.
- Frontend: Vitest passed; `npm.cmd run build` passed.
- `scripts/verify_read_only_boundary.py`: passed.
- Local Crypto health: Schema `16/16`, migration `ready`, `read_only=true`,
  roll execution `false`, Shadow status `NO_GO`.
- Gateway health: stock and crypto backends available when both local servers
  are running; `data_mixing=false`, order submission `false`.
- Gateway smoke helper: `scripts/check_gateway.py` passed with direct local
  HTTP and a cold-backend-safe timeout; manifest and Service Worker both
  returned `200`.
- Backup/restore: SQLite backup and restore completed with matching SHA-256,
  `pragma quick_check=ok`, and 16 migration records in the restored copy.
- Added a secret-free public Binance derivatives collector and an explicit
  configured ETF/on-chain collector CLI. Each source is independently
  fail-closed, source-timed, hashed and persisted with missing fields as
  `N/A`.
- `/api/health` now exposes build SHA, start time and the application/API/
  frontend/schema version matrix. Backup status reads the latest real manifest
  instead of returning a hard-coded empty state. The gateway exposes a
  read-only `/api/gateway/config` mode contract.
- Roll Desk supports deterministic EVAL review, OCR-text preview and a
  user-confirmed Roll Journal write; no step creates an order or wallet action.
- A fresh local SQLite backup was created at
  `work/backups/20260823T155833Z`; its database SHA-256 is stored in the
  manifest. The restored copy has since been verified with matching SHA-256,
  SQLite `quick_check=ok`, and 47 user tables; the verification metadata is
  recorded in the manifest.

## Still not complete / evidence not claimed

- No real ETF/on-chain/whale feed is configured in this environment, so
  coverage is not established.
- No qualifying real roll dataset has passed the 100-trade/OOS/cost/drawdown
  gate. The validation result remains research-only and `NO_GO`.
- No 15 real trading-day Shadow Observation has been collected. Simulated days
  cannot replace calendar observations.
- Staging Postgres is not configured or restore-verified; local SQLite is the
  active runtime.
- The gateway is a navigation/health boundary, not a shared reverse proxy or
  unified session. Each backend still owns its login and database.
- There is no account, wallet, private-key, order, swap or automatic execution
  path.

## Next gate order

1. Configure one approved ETF/on-chain feed and collect source-timed snapshots.
2. Accumulate closed-candle roll history and run the locked validation report.
3. Start the 15-calendar-trading-day Shadow run without changing parameters.
4. Only after local backup/restore verification, configure protected Staging
   Postgres and run schema/query compatibility tests.
5. Re-evaluate Go/No-Go. Until then the runtime remains
   `RESEARCH_ONLY -> PAPER_ONLY -> SHADOW_ONLY`.
