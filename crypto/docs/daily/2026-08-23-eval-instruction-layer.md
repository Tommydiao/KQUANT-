# EVAL Instruction Layer Progress

## Scope

This increment implements the missing boundary between the deterministic EVAL
Agent and downstream alerts/Paper/Shadow. It does not loosen any weekly Gate.

## Changes

- Schema v9 adds `crypto_trade_instructions` and
  `crypto_instruction_events`.
- Schema v10 adds metadata-only `crypto_model_artifacts`; EVAL binds model
  version, dataset hash, feature-order hash, test-partition hash and
  calibration status without storing executable model bytes.
- Schema v11 adds additive `evidence_partition` and `oos_fold` fields to
  validation trades. Existing rows remain `legacy`; new runs persist train,
  validation, test and locked OOS fold evidence separately.
- Schema v12 adds point-in-time `factor_values_json` to validation trades.
  Existing rows remain empty by design; new outcomes persist the factor inputs
  available at the signal bar for leakage-safe model benchmarking.
- `TradeInstruction` is an auditable projection of one EVAL result, not an
  exchange order. Its state is derived deterministically from the EVAL decision.
- `RealtimeSupervisor` accepts EVAL results, persists the projection, tracks
  duplicate `material_state_hash` suppression and exposes runtime counters.
- `POST /api/crypto/trade-plans` now returns the plan, EVAL result and the
  EVAL-derived instruction projection together.
- Added current/history/detail instruction endpoints and supervisor status
  endpoints, including compatibility aliases without the `/crypto` prefix.
- `Alert Agent` now rejects `REJECTED`, `WATCH_ONLY` and `INVALIDATED` results
  even if a caller attempts to set `allowed_alert=true`.
- Alerts are read from notification records only when they carry an EVAL
  evaluation binding.
- EVAL-authorized alerts now fan out through the existing SSE hub and the
  configured Web Push/Telegram transports; both transports remain disabled by
  default and never receive secrets in API responses.
- Added `scripts/rebuild_crypto_coverage_index.py` for datasets written by a
  collector version that predates incremental coverage indexing.
- Added read-only model artifact inspection endpoints. A registered artifact
  must be frozen and calibrated before its probability evidence can pass the
  model gate.
- Added Holder snapshot persistence from security-provider payloads and the
  read-only `GET /api/crypto/assets/{asset_id}/holders/latest` endpoint.
  Holder refreshes are stored separately from token-safety decision hashes so
  ownership changes do not manufacture duplicate security events. The
  endpoint is explicitly `data_only`; a Holder snapshot can never authorize
  EVAL or Paper by itself.
- Added `GET /api/crypto/security/coverage`, which reports provider enablement,
  checked-token coverage and latest `passed/blocked/unknown` counts without
  exposing provider credentials. The current local DEX store contains 127
  token identities and 2,900 market snapshots. One explicit BSC single-token
  smoke check is recorded as `unknown` because the provider did not return
  complete safety fields; this is still effectively `1/127` coverage and EVAL
  remains fail closed for the unknown token.
- Today now surfaces security coverage and model-calibration status next to the
  runtime evidence. This is presentation-only: the UI cannot promote a model
  or change the EVAL decision.
- DEX discovery persistence now runs synchronous SQLite pair and security
  upserts in worker threads, with one transaction per discovery response.
  SQLite WAL initialization is confined to migrations and health status is
  read-only. Market Parquet flushes also run behind an async lock in a worker
  thread. Together these changes prevent public DEX/CEX collection from
  blocking the FastAPI event loop or making `/api/health` intermittently
  unreachable; DEX collection and the dashboard remain separate read-only
  concerns.
- MEME factor history now joins security and Holder snapshots point-in-time:
  an `as_of` request cannot use a later safety result or later ownership data.
  Paper observations additionally verify plan identity and entry snapshot
  bindings against the approved EVAL result.
- EVAL now distinguishes provider availability from explicit token safety;
  `live` or `available` provider status cannot satisfy the security gate.
- MEME factors now have a separate registered namespace,
  `crypto_meme_factor_v1.0.0`. EVAL recognizes these IDs alongside the CEX
  namespace without combining their scores or opening any execution gate.
- Added a closed-candle warm start from the immutable compacted 1m Parquet
  snapshot. Historical rows are marked `historical` and never count as fresh
  provider data; live events continue to be the only source for current trust.
- Added `MarketRegimeRuntime`, which computes 24-hour core returns, alt breadth
  and available derivatives evidence from closed 1H candles, persists a
  `crypto_market_regime_snapshots` row with a `crypto_market_regime_inputs`
  DataSnapshot, and binds that snapshot into CEX trade-plan drafts. The
  market-regime route and health output now expose `DATA_CAUTION` until the
  closed-history and live-freshness requirements are met.
- Data Coverage now reports a persisted-Parquet span Gate separately from a
  continuous collector-session Gate, preventing concatenated history from
  being presented as uninterrupted collection.
- Validation now supports three ordered, date-based expanding OOS folds with
  disjoint locked test windows. The original 60/20/20 report remains for
  compatibility; the new `oos_folds` and `oos_summary` evidence is separate.
- Added `kquant_crypto/dex_paper.py`, a read-only DEX fill-cost layer. It
  estimates constant-product price impact from the captured pool liquidity
  and includes fee, tax and Gas in the paper cash flow. Unknown safety/tax,
  missing snapshot identity, shallow liquidity and excessive impact fail
  closed; no order or wallet API is involved.
- Hardened the long-run CEX collector to rebuild its Parquet coverage index
  after the provider task stops, so a completed run produces a self-contained
  coverage Gate report even when it started with an older writer.
- Added notification policy enforcement for the downstream Alert Agent:
  ordinary alerts have a five-per-local-day cap, quiet hours are audited as
  suppressed records, `RISK/CRITICAL` bypass those two limits, and Web Push
  or Telegram transient delivery failures retry up to three times. This
  policy never changes the deterministic EVAL decision.
- Added canonical CEX identity registration for first-seen venues, assets and
  instruments, plus registry-backed asset coverage in
  `GET /api/crypto/data/coverage`. Repeated ticks do not create duplicate
  identity rows.
- Added the closed-candle `CEXSignalRuntime` bridge. It consumes only closed
  1m events after the runtime has produced a complete 5m candle, computes the
  registered factor set, persists a factor snapshot, creates a deterministic
  research plan, and sends it through EVAL and the instruction projection.
  Forming candles and insufficient history are ignored; this bridge has no
  direct notification or execution capability.
- Corrected `trend_ema_slope` and `volume_acceleration` to return the
  normalized values described by their registered formulas, and added a
  public `closed_history` accessor so signal code cannot read forming candles.
- Alert delivery now requires the exact `evaluation_status=passed` state;
  `passed_with_warnings` is not an authorization state.
- Added a closed-K-line Parquet Dataset Builder and
  `POST /api/crypto/validation/runs/from-parquet`. It reads only Binance spot
  closed bars, records a content hash and exclusion reasons, and returns
  `NO_GO` when the raw event file count needs maintenance compaction.
- Added `scripts/compact_crypto_klines.py`, which atomically publishes a
  deduplicated closed-1m snapshot while leaving raw append-only events intact.
  The current local store was compacted to 124,235 closed spot bars across the
  configured CEX Universe; raw append-only events remain intact.
- The corrected slope and volume formulas are now registered as
  `crypto_factor_v1.0.1`; prior snapshots remain historical evidence.
- The coverage API now reads the incremental Parquet coverage index instead of
  recursively enumerating every raw event file on each dashboard request.
  Full filesystem reconciliation remains an explicit maintenance operation.
- Added the public Binance historical kline backfill task. It is a separate,
  resumable maintenance path with cursor state, retry handling, closed-bar
  filtering, `provider_status=historical`, `available_at` provenance and no
  account or order capability. It does not claim a validation result by
  itself; compaction and the locked OOS pipeline remain required.
- Historical replay now precomputes the registered factor series and ATR
  prefixes once per input series. On the first 20-day core-symbol snapshot,
  dataset loading took about 3.9 seconds and the three-fold OOS replay about
  26.1 seconds. The run produced 3 OOS folds but 0 completed trades, so its
  evidence status remains `insufficient` and no performance claim is made.
- Historical replay now declares its feature scope in the dataset hash and
  report. The Parquet endpoint defaults to the explicit
  `crypto_historical_ohlcv_v1.0.0` / `ohlcv_only_limited` policy, excluding
  `cvd_bias`, `oi_price_alignment`, `funding_extreme` and
  `liquidity_spread`; the live signal runtime still uses its full factor set.
- The initial runs `validation_809c93d6ff014a9e8026e0f42f2115d1` and
  `validation_ad518c5b74bf4b3e906705918cc67a81` used the generic 24-bar
  default on 1m data. That is a 24-minute holding window, not the intended
  24-hour contract. They remain immutable audit records but are superseded
  for strategy evidence and must not be compared directly with the corrected
  interval-aware runs.
- The interval-aware core run is persisted as
  `validation_0425b15d0169401e8fb3dcb9e9c1f68a` using 15m bars, a 96-bar
  24-hour holding window, and the OHLCV+Funding/OI limited scope. Its 39-trade
  locked test set has 58.97% win rate, average `+0.704R`, PF `2.677`, maximum
  drawdown `3.24R`, and bootstrap expected-R interval
  `[+0.267R, +1.149R]`. The 50-trade OOS chain averages `+0.320R`, PF `1.538`,
  and interval `[-0.127R, +0.760R]`. Evidence is limited and below the 100
  test-trade / positive lower-bound Gate, so it remains research-only.
- The earlier derivative run `validation_af7d4babfeb2428183bbe2c69f460005`
  used the same pre-fix 24-minute window and is also superseded; its database
  record remains available only for audit comparison.
- The Parquet loader now aggregates closed 1m bars into requested 5m/15m/1h
  intervals before validation. Holding windows are derived from wall-clock
  hours, preventing a bar-count/unit mismatch from contaminating future runs.
- Added a validation-only parameter experimenter and CLI. It ranks candidates
  using the validation partition only and explicitly omits test/OOS results
  from the returned selection report. On the current core 15m derivative
  dataset, `setup_threshold=50` was the least negative validation candidate
  (`-0.210R`, PF `0.737`, 21 samples), while thresholds 60 and 70 were worse.
  All three candidates are insufficient evidence; this is diagnostic output,
  not a parameter promotion or a performance claim.
- Added a non-authoritative model benchmark layer with a train-rate baseline,
  uncalibrated rules score, deterministic NumPy Logistic baseline, optional
  LightGBM status and a deferred Quantile slot. It fits only the train
  partition, reports validation and locked test metrics separately, and never
  selects a model or changes EVAL permissions. The current core 15m
  derivatives run has 41 complete train rows, 13 validation rows and 39 test
  rows. The Logistic baseline scores test AUC `0.440` and Brier `0.399`, while
  validation AUC is `0.000` and Brier `0.333`; calibration remains closed and
  the evidence is insufficient. LightGBM is not installed locally and the
  Quantile baseline is explicitly deferred.
- The dashboard now exposes signal-runtime and validation evidence counters so
  `monitoring`, `insufficient`, and `NO_GO` are visible as separate states;
  zero test trades are never presented as a strategy win rate.
- Added a versioned CEX universe catalog with `CORE`, `MAJOR_ALT`,
  `CEX_HIGH_BETA` and `MEME` tiers. Startup now creates or reuses a full
  point-in-time Universe Snapshot, and Signal Runtime binds its real snapshot
  ID into every EVAL plan instead of using a placeholder binding.
- The current local runtime materializes `crypto_universe_v1.1.0` with 29
  canonical CEX symbols across the four tiers. The latest health smoke reports
  Schema `12/12`, `read_only=true`, and the same Universe content hash after
  restart, confirming deterministic snapshot reuse rather than duplicate
  startup snapshots.
- Added the public Binance derivatives history adapter for Funding Rate and
  Open Interest. It uses only the public USD-M market-data endpoints, stores
  `historical_rest_replay` provenance, keeps `available_at` as an explicit
  source-time proxy, and exposes an isolated checkpoint path for repair jobs.
  No API key, account, wallet, or order capability is accepted.
- A real core-symbol replay for BTCUSDT, ETHUSDT and SOLUSDT completed 64
  Funding rows and 500 hourly OI rows per symbol for the August 1-22 window.
  Binance returned an end-capped OI page for that interval; the backfill now
  detects the missing prefix and repairs it with a narrowed end time. A
  separate repair checkpoint added the five hourly boundary rows per symbol.
  This is provider coverage evidence, not yet a point-in-time validation
  result; the historical availability proxy must be reviewed before these
  features can enter a formal model dataset.
- `ParquetMarketStore.query()` now narrows the filesystem traversal before
  DuckDB reads and uses `union_by_name=true`, so mixed optional `sequence`
  schemas from long-running provider streams remain auditable instead of
  failing the query path.
- Added `derivative_snapshots.parquet` compaction and a read-only derivative
  dataset loader. It deduplicates by instrument, event type and source time,
  aligns Funding/OI only after both source and availability timestamps, and
  keeps the derivative feature scope separate from the OHLCV baseline.
- Added `scripts/run_crypto_validation.py` for reproducible locked Parquet
  validation runs. The first core-symbol OHLCV+Funding/OI replay is persisted
  as `validation_af7d4babfeb2428183bbe2c69f460005` with dataset hash
  `a5304550ad780476121081e84f0b7f020c6838005ec560a2d679a9bd6d61261f`.
  Its 356-trade locked test set has 31.74% win rate, average `-0.472R`, PF
  `0.470`, maximum drawdown `170.71R`, and bootstrap expected-R interval
  `[-0.602R, -0.346R]`. The 683-trade OOS chain averages `-0.802R` with PF
  `0.255`. It fails the performance Gate and remains research-only.

## Gate status

- Foundation EVAL still returns only `REJECTED` or `WATCH_ONLY` for the current
  evidence boundary.
- `allowed_alert=false`, `allowed_paper=false` and `allowed_shadow=false` are
  preserved.
- No account, wallet, private-key, order, swap or automatic execution route was
  added.
- The automatic CEX signal bridge is active for collected public candles, but
  its current output remains EVAL-blocked until security, market, model and
  Paper evidence gates are independently opened.
- The single 24-hour public CEX collector remains active; its continuity Gate
  is not yet complete.
- The validation/OOS and Holder changes are implemented and tested, but no
  performance Gate is passed: the OHLCV-only baseline has enough completed
  test outcomes to measure, but its negative expectancy and Profit Factor
  fail the required thresholds. Derivatives and live execution factors still
  require separate historical evidence.
- The coverage index now reports 29/29 configured CEX symbols with at least
  23 hours of persisted public data. This is a backfill/data-coverage result;
  the independent 24-hour continuous collector Gate remains pending until
  its own run report completes.
- Derivative coverage is currently limited to the three core perpetuals and
  is intentionally not mixed into the 29-symbol OHLCV validation run. The
  derivative-aligned replay now exists for the three core symbols, but its
  explicit source-time availability proxy is still limited evidence and does
  not pass the performance Gate.
- The raw store currently contains more than 100,000 small event files; the
  compacted snapshot is a read optimization, not additional historical data.
  The 24-hour collection Gate remains `NO_GO` until the collector continuity
  report proves the required window.

## Verification

- Python: `128 passed`; the Parquet coverage regression includes assertions
  that the indexed hot path does not scan raw files.
- Frontend: Vitest `1 passed`; Vite production build passed. The read-only
  route scan also passed.
- Local API smoke: coverage responds in about 0.02 seconds from the index;
  signal runtime is running with public events observed across the expanded
  Universe but no EVAL authorizations; the latest validation is explicitly
  `ohlcv_only_limited` and remains `NO_GO` on performance evidence.
- New tests cover instruction creation, material-state deduplication, rejected
  EVAL invalidation, API projection and Alert Agent downstream enforcement.
- Backfill regression tests cover REST pagination, retry on rate limit,
  historical provenance, closed-bar filtering and cursor resume.
- The active collector was not interrupted to run the rebuild; its final
  continuity report remains the source of truth for the 24-hour Gate.
