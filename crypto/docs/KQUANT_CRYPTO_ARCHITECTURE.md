# KQUANT CRYPTO Architecture and EVAL Boundary

## Agent responsibility

Market Data, Discovery, Security, Factor, Signal and Trade Plan components
produce versioned evidence and a draft. The deterministic EVAL Agent is the
only component allowed to decide whether a draft may become an alert, Paper
observation or Shadow candidate. Alert delivery is downstream of EVAL.

The LLM is an advisory side channel. It can explain registered evidence and
raise questions, but its response is never merged into the decision fields.
An unavailable or invalid LLM response therefore cannot make a plan more
permissive.

## Week 1 EVAL contract

`crypto_eval_v1.0.2` checks identity, security, data freshness, liquidity,
market regime, registered factors, model evidence, plan completeness and
expiry/duplication in a fixed order. Security blocks have the highest
precedence. Unknown security is `REJECTED`; other missing evidence is at most
`WATCH_ONLY`.

The foundation gate keeps `allowed_alert`, `allowed_paper` and
`allowed_shadow` false for every result. This is deliberate until provider,
data-trust and out-of-sample gates are implemented in later weeks.

## Data flow

1. Public provider events are normalized into canonical assets and instruments.
2. Snapshots receive source time, received time, availability and content
   hashes.
3. The versioned Factor Registry accepts only the twelve initial low-
   redundancy factor IDs. Signal proposals expose stage, score and factor
   contributions but cannot notify.
4. Trade Plan Agent translates a proposal into an immutable draft with entry,
   stop, target, expiry and invalidation conditions.
5. Trade plan drafts are saved before evaluation.
6. EVAL runs, blockers, evidence and final decisions are immutable audit rows.
7. Alert Agent reads only EVAL-approved records; the foundation cannot approve
   any.

The Parquet layer has one writer boundary: a cross-process lock plus atomic
file replacement. A dashboard process may read the store, but a long-running
collector is the preferred owner of public-event persistence.

High-frequency persistence is bounded by `crypto_raw_storage_v1.0.0`: every
incoming trade remains available to the in-memory ring buffer and CVD logic,
then is written as one time-bucketed `trade_summary` with counts, buy/sell
volume, notional, CVD and large-trade statistics. BBO and ticker events are
time-sampled; closed K-lines and derivative snapshots keep their source
events. The policy is configurable through
`KQUANT_CRYPTO_TRADE_BUCKET_SECONDS`,
`KQUANT_CRYPTO_QUOTE_SAMPLE_SECONDS` and
`KQUANT_CRYPTO_TICKER_SAMPLE_SECONDS`.

High-frequency WebSocket subscriptions are separately limited by
`KQUANT_CRYPTO_HIGH_FREQUENCY_SYMBOLS` (default `BTCUSDT,ETHUSDT,SOLUSDT`).
The full configured CEX universe still receives ticker and 1m K-lines, while
trade/BBO/mark-price streams are reserved for the core liquidity set.
Production collectors use a 5,000-event write batch by default
(`KQUANT_CRYPTO_STORAGE_FLUSH_EVERY`); tests and bounded maintenance runs can
override this without changing the evidence contract.

## Current version matrix

| Layer | Version | Status |
| --- | --- | --- |
| Application | `0.3.3` | EVAL instruction, roll research, Shadow ledger, indexed market storage and public market-structure evidence |
| API | `kquant-crypto-api-2026-08-24-evidence-v5` | read-only research endpoints including public Binance market structure, DefiLlama context and optional CoinGlass ETF, derivatives, on-chain and whale evidence collection |
| Schema | `17` | EVAL, instructions, model evidence, validation partitions, PIT factor values, roll research, external evidence, Shadow ledger and confirmed OCR journal previews |
| Market contract | `crypto_market_v1.0.0` | public CEX adapters |
| Raw storage policy | `crypto_raw_storage_v1.0.0` | bounded trade summaries and sampled quote evidence |
| Factor registry | `crypto_factor_v1.0.1` | normalized slope/volume formulas; no production score gate |
| EVAL policy | `crypto_eval_v1.0.2` | deterministic, explicit downstream release flags closed by default |
| Model | `crypto_model_benchmark_v1.0.0` / `crypto_bayesian_v1.0.0` | rules/naive/NumPy Logistic plus validation-only Platt/Isotonic scaffolding; Bayesian posterior carries PIT training-window and feature-order hashes; calibration and EVAL integration closed |
| Evidence | `crypto_public_evidence_v1.2.0` / `crypto_market_structure_public_v1.0.0` / `crypto_coinglass_evidence_v1.2.0` | secret-free Binance/OKX public derivatives and Binance ticker breadth/relative-strength evidence plus optional, key-gated CoinGlass derivatives/ETF/on-chain/whale evidence; documented BTC/ETH stablecoin series is source-timed and all missing fields remain `N/A` |
| Staging | `crypto_staging_contract_v1.1.0` | fail-closed PostgreSQL compatibility plan; SQLite remains the active local runtime |

## Security boundary

This repository has no account, wallet, private-key, position, order,
trade-execution or swap path. Exchange integrations in later weeks are public
market-data adapters only. The boundary scan checks exact route segments so
the required `trade-plans` resource path is not confused with a trade
submission route.

## 999 plan implementation boundary

The code now includes the deterministic `crypto_roll_v1.0.0` engine, point-in-
time Bayesian and fixed-seed Monte Carlo research, source-timed external
evidence, Roll Desk/Journal confirmation, SQLite backup/restore helpers and a
Stocks/Crypto navigation gateway. OCR input is now a short-lived preview and
cannot write the Roll Journal without an explicit confirmation record. These
are executable research contracts, not evidence that ETF/on-chain coverage,
100 qualifying OOS trades, or 15 real trading-day Shadow Observation has
already been collected. Until those real gates pass, EVAL keeps alert, Paper
and Shadow release closed where required.

Listed crypto proxies have an additional fail-closed contract: ETHU, MSTU and
MSTR require an exact listed instrument ID and an `instrument_data_status` of
`actual`. A missing listed history or an underlying-times-two substitution
becomes a blocked roll or an unavailable Monte Carlo result; no synthetic
listed-instrument performance is persisted as evidence.

Bayesian snapshots also record optional `training_window_start`,
`training_window_end`, `training_dataset_hash`, `random_seed` and a
`feature_order_hash`. The response exposes the registered likelihood evidence
used for each feature and lists unsupported features explicitly; an unsupported
feature keeps the posterior in `data_caution`. A training window that extends
beyond the signal time is rejected before persistence.

Monte Carlo results persist the normalized input hash and target regime in
addition to the fixed-seed configuration and result hash. This makes a
probability run replayable without storing raw high-frequency events in the
SQLite control database.

## Final readiness contract

`GET /api/operations/go-no-go` and
`python scripts/check_crypto_readiness.py` aggregate the locked validation,
continuous collection, raw-index repair, external evidence, PostgreSQL
Staging, backup/restore and real Shadow-day gates. Missing or stale inputs are
failures, not inferred passes. The report is secret-free and always returns
`research_only=true` and `order_submission=false`; it is an audit report, not
an execution unlock.

The public health response also exposes a compact `collector_session` status
when the separate long-run market-data process is active. It is deliberately
reported separately from the dashboard provider supervisor, so the gateway
never merges two runtimes or claims that a collector has account access.

## Large-archive coverage repair runbook

The raw event archive is append-only and may contain hundreds of thousands of
small Parquet files. `scripts/rebuild_crypto_coverage_index.py` therefore
supports a resumable scope workflow:

1. `--write-scope-manifest work/coverage_scope_manifest.json` lists only
   `venue/market_type/symbol` partition directories and does not open raw
   files.
2. `--run-scope-manifest work/coverage_scope_manifest.json` scans one scope at
   a time and atomically writes a fragment under
   `data/market/_coverage_fragments/`.
3. `--merge-fragments --scope-manifest ... --publish` replaces the main index
   only when every expected scope is present and complete. Missing, partial,
   unexpected or invalid fragments leave the existing index untouched.

Date-scoped runs can further narrow maintenance with repeated `--date`
arguments. A fragment is evidence for its declared scope only; it is never
used as a full-dataset coverage pass. This keeps the dashboard fail-closed
while the collector continues writing new raw events.
