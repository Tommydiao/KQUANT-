# KQUANT CRYPTO

KQUANT CRYPTO is an independent, read-only crypto market research terminal.
It is intentionally separate from the US equity KQUANT repository and starts
on port `8010`.

The first release establishes the final review boundary:

```text
market data -> data trust -> factors -> signal proposal
-> trade plan draft -> deterministic EVAL Agent -> alert/Paper/Shadow
                                           ^
                                      LLM advisory only
```

The foundation release does not connect exchange accounts, wallets, private
keys or order APIs. Providers are disabled by default. The EVAL policy returns
only `REJECTED` or `WATCH_ONLY` until later weekly gates are explicitly
implemented and passed.

The default CEX watchlist is versioned in `config/crypto_universe.yml` and is
split into `CORE`, `MAJOR_ALT`, `CEX_HIGH_BETA` and `MEME` tiers. The runtime
creates or reuses a point-in-time Universe Snapshot at startup. Set
`KQUANT_CRYPTO_CORE_SYMBOLS` to override the public observation list; this
does not authorize orders or promote a symbol past the EVAL gates.

Every EVAL input must bind the same evidence set: `market`, `regime`, `factor`,
`security`, `liquidity`, `derivative`, `signal`, `plan`, `model`, `universe`
and `eval_policy`. Missing or mismatched bindings are recorded as blockers and
cannot authorize an alert, Paper observation or Shadow observation. The
database migration for this contract is schema v17; v9 adds the EVAL-derived
research instruction projection and its state events, v10 adds immutable
model-evidence metadata, v11 records validation partition/OOS-fold evidence,
and v12 records signal-time factor values for leakage-safe model benchmarks.
v13 adds the crypto roll ledger and Bayesian/Monte Carlo research records,
v14 adds point-in-time ETF, derivatives, on-chain and whale evidence, v15
adds the locked crypto roll validation report, v16 adds the immutable Shadow
Observation Ledger, and v17 adds the OCR Roll Journal preview/confirmation
record. Existing rows remain additive; model files
themselves are never stored by the app.

## Local setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m kquant_crypto db migrate
.\.venv\Scripts\python.exe -m pytest -q
```

For local login, generate values without placing secrets in source control:

```powershell
.\.venv\Scripts\python.exe -m kquant_crypto auth hash-password
.\.venv\Scripts\python.exe -m kquant_crypto auth generate-session-secret
```

Put the returned values in `.env` as `KQUANT_CRYPTO_LOGIN_PASSWORD_HASH`
and `KQUANT_CRYPTO_SESSION_SECRET`, together with the local email.

For optional iPhone Web Push, generate VAPID values locally and copy the
three printed lines into `.env`. Keep notifications disabled until the keys
and HTTPS origin have been checked:

```powershell
python scripts/generate_vapid_keys.py
```

Then set `KQUANT_CRYPTO_ENABLE_NOTIFICATIONS=true`, restart the server, open
the HTTPS site on iPhone, add it to the Home Screen, and use the dashboard
device panel to grant permission and send a test. Web Push is advisory only;
it can deliver EVAL-approved research alerts but cannot submit trades.

## Current research endpoints

- `GET /api/health`
- `GET /api/version` (public build/schema/API contract summary)
- `GET /api/auth/session`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/crypto/trade-plans/current`
- `GET /api/crypto/instructions/current`
- `GET /api/crypto/instructions/history`
- `GET /api/crypto/instructions/{instruction_id}`
- `GET /api/crypto/runtime/supervisor-status`
- `GET /api/crypto/runtime/signal-status`
- `GET /api/crypto/providers/status`
- `POST /api/crypto/evidence/fetch-coinglass` (optional read-only CoinGlass evidence; requires explicit key and provider flag)
- `GET /api/crypto/universe/current`
- `GET /api/crypto/data/coverage`
- The coverage response includes a `coverage_gate` for persisted Binance spot
  spans. Its `evidence_scope` is `persisted_parquet_span`; it is not a claim
  that one collector process ran continuously for that entire period.
- `GET /api/crypto/models`
- `GET /api/crypto/models/{model_id}`
- `GET /api/crypto/evaluations/latest`
- `GET /api/crypto/evaluations/{evaluation_id}/advisories`
- `POST /api/crypto/evaluations/{evaluation_id}/advisory` (non-authoritative LLM review)
- `GET /api/crypto/factors/registry`
- `GET /api/crypto/assets/{asset_id}/factors/current`
- `GET /api/crypto/dex/pairs/latest`
- `GET /api/crypto/assets/{asset_id}/security/latest`
- `GET /api/crypto/assets/{asset_id}/holders/latest`
- `GET /api/crypto/assets/{asset_id}/meme-factors`
- `GET /api/crypto/security/latest`
- `GET /api/crypto/security/coverage`
- `POST /api/crypto/validation/runs` (local deterministic replay; test data only; supports locked rolling OOS folds)
- `POST /api/crypto/validation/runs/from-parquet` (closed Binance spot Parquet only; insufficient data returns `NO_GO`)
- `GET /api/crypto/validation/latest`
- `GET /api/crypto/validation/gate` (locked test/OOS evidence gate; research-only)
- `GET /api/crypto/validation/model-benchmarks/latest`
- `GET /api/crypto/roll/current`
- `GET /api/crypto/roll/history`
- `GET /api/crypto/roll/ledger`
- `GET /api/crypto/roll-journal` (read-only alias for the Roll Journal)
- `POST /api/crypto/roll/evaluate` (deterministic research decision; no Paper or Shadow permission)
- `POST /api/crypto/roll/feature-packet` (point-in-time evidence packet; advisory only)
- Listed proxies `ETHU`/`MSTU`/`MSTR` require an exact instrument ID and actual
  listed-instrument data; underlying-times-two substitutions are rejected.
- `POST /api/crypto/roll/ledger` (realized-profit audit entry; explicit confirmation required)
- `POST /api/crypto/roll-journal/confirm` (confirmed Roll Journal write)
- `POST /api/crypto/roll-journal/ocr-preview` (preview only; confirmation required before writing)
- `GET /api/crypto/roll/{roll_id}`
- `POST /api/crypto/research/bayesian`
- `GET /api/crypto/research/bayesian/{asset_id}`
- `GET /api/crypto/research/bayesian/snapshots/{snapshot_id}`
- `POST /api/crypto/research/monte-carlo`
- `GET /api/crypto/research/monte-carlo/{asset_id}`
- `GET /api/crypto/research/monte-carlo/runs/{run_id}`
- `POST /api/crypto/validation/roll-runs`

Optional CoinGlass collection is explicit and fail-closed. It supports
derivatives snapshots for any configured symbol, BTC/ETH ETF flow, and
source-specific on-chain/whale snapshots. The documented market-wide stablecoin
market-cap series is attached only to BTC/ETH market snapshots. Fields absent
from the provider remain `N/A` and the evidence cannot promote a roll decision
by itself:

```powershell
python scripts/collect_coinglass_evidence.py --category exchange_derivatives --symbol BTC --symbol ETH
python scripts/collect_coinglass_evidence.py --category etf_flow --symbol BTC --symbol ETH
python scripts/collect_coinglass_evidence.py --category onchain --symbol BTC --symbol ETH
python scripts/collect_coinglass_evidence.py --category whale --symbol BTC --symbol ETH --symbol SOL
```

Set `KQUANT_CRYPTO_ENABLE_COINGLASS=true` and `COINGLASS_API_KEY` only in the
local `.env` before collection. The key is never returned by capabilities,
responses, logs, or saved evidence.

DefiLlama public context is also available without an API key. It maps only
the documented global stablecoin series to BTC/ETH market context and the
current protocol TVL endpoint to AAVE/ENA; all other on-chain, holder and
whale fields remain `N/A`. Enable it explicitly with
`KQUANT_CRYPTO_ENABLE_DEFILLAMA=true` and collect it with:

```powershell
python scripts/collect_defillama_evidence.py --category onchain --symbol BTC --symbol ETH
python scripts/collect_defillama_evidence.py --category protocol_metric --symbol AAVE --symbol ENA
```

These snapshots are research evidence only, carry source timing and content
hashes, and cannot by themselves pass the EVAL or readiness gates.

Binance public market structure is collected separately from the CEX ticker
endpoint. It records configured-universe breadth plus ETH/BTC and SOL/BTC;
BTC dominance and market regime remain `N/A` until an explicit source snapshot
exists. The result is therefore still `data_caution` and cannot authorize a
roll action:

```powershell
python scripts/collect_market_structure_evidence.py --symbol BTC

# Collect the registered public evidence set for the 999 plan.  This is
# source-timed research data only; failed providers remain N/A/data_caution.
python scripts/collect_999_public_evidence.py --symbol BTC --symbol ETH --symbol SOL --symbol AAVE --symbol ENA --symbol ZEC --symbol PUMP
```
- `POST /api/crypto/validation/roll-runs/from-parquet` (closed-bar roll replay)
- `GET /api/crypto/validation/roll-latest`
- `GET /api/crypto/validation/roll-runs/{run_id}`
- `GET /api/crypto/shadow/summary`
- `GET /api/crypto/shadow/observations`
- `POST /api/crypto/shadow/observations` (observation only; no execution permission)
- `GET /api/crypto/shadow/{observation_id}`
- `GET /api/crypto/shadow/{observation_id}/audit`
- `POST /api/crypto/shadow/{observation_id}/review`
- `POST /api/crypto/shadow/{observation_id}/outcome` (immutable outcome record)
- `POST /api/crypto/evidence`
- `GET /api/crypto/assets/{asset_id}/evidence`
- `GET /api/crypto/assets/{asset_id}/evidence/history`
- `GET /api/crypto/evidence/capabilities` (configured status only; no secret values)
- `GET /api/crypto/evidence/coverage` (observed versus verified coverage by category)
- `POST /api/crypto/evidence/fetch-public` (Binance/OKX public derivatives, Binance market structure, or explicitly enabled DefiLlama context; no credentials)
- `POST /api/crypto/evidence/fetch-configured` (explicit ETF/on-chain JSON feed; missing fields stay `N/A`)
- `GET /api/crypto/paper-observations`
- `POST /api/crypto/paper-observations` (requires `allowed_paper=true` from EVAL)
- `POST /api/crypto/paper-observations/{observation_id}/close`
- `GET /api/notifications/status`
- `POST /api/notifications/web-push/subscribe`
- `POST /api/notifications/web-push/test`
- `POST /api/crypto/trade-plans` (draft only, immediately reviewed by EVAL)
- `GET /api/crypto/alerts`
- `GET /api/crypto/alerts/stream`
- `GET /api/runtime/boundary`
- `GET /api/operations/observability`
- `GET /api/operations/staging`
- `GET /api/operations/backup/status`

All research endpoints require the HttpOnly local session cookie. Provider
credentials, notification secrets and login material are environment-only.
For long-running collections, build the read-optimized closed-candle snapshot
before running validation: `python scripts/compact_crypto_klines.py`. Snapshots
for `1m`, `15m`, `1h` and other requested intervals are stored side by side;
building a higher-timeframe snapshot never replaces the live `1m` snapshot.
Raw event files remain append-only; validation returns `compaction_required`
rather than blocking the realtime server when the raw-file count is too large
for a synchronous scan.

To extend the historical evidence set, use the public Binance REST backfill
maintenance task. It is resumable, rate-limited by the provider client,
persists only closed candles, and never uses account credentials:

```powershell
python scripts/backfill_binance_klines.py --symbol BTCUSDT --symbol ETHUSDT `
  --interval 1m --start 2026-01-01T00:00:00Z --max-pages 10
python scripts/compact_crypto_klines.py
```

The backfill cursor is stored under the ignored data directory. Each event is
marked `provider_status=historical` with `source=binance_public_rest_klines`
and an `available_at` timestamp. A backfill report is evidence collection,
not a validation result; after enough data has accumulated, run the Parquet
validation endpoint and keep its OOS Gate separate from live observations.

After a long collection window, the coverage index can be repaired without
publishing one giant raw index in a single operation. This helper waits for
the independent collector to exit, runs resumable scope fragments, and
publishes only after the complete manifest merge gate passes:

```powershell
.\scripts\finish_crypto_collection_maintenance.ps1
```

For a controlled 24-hour public-data window, use the watchdog. It waits for
coverage maintenance, writes session-specific logs, and never enables account
credentials or order endpoints. `-MaxSessions 1` is the recommended first
acceptance run; use `-BinanceOnly` for the lower-load Binance-only profile:

```powershell
.\scripts\run_crypto_collection_watchdog.ps1 -SessionHours 24 -MaxSessions 1 -BinanceOnly
```

The watchdog is a collection reliability tool, not a permission switch. A
stale session, provider failure, incomplete coverage merge, missing source
evidence, or failed validation keeps readiness at `NO_GO`.

The frozen roll policy can be replayed from the closed 1H snapshot with:

```powershell
python scripts/run_crypto_roll_validation.py --interval 1h --min-bars 220 `
  --max-hold-bars 24 --include-derivatives
```

The command persists a `crypto_roll_v1.0.0` report and exits non-zero when the
research gate is not met. A non-zero result is expected while the sample,
cost, bootstrap and Shadow gates remain incomplete; it never enables Paper,
Shadow or any execution capability.
Holder snapshots are `data_only` evidence; they never authorize an EVAL
decision by themselves. Token safety must still pass its own security
snapshot and the complete EVAL policy.

DEX/MEME Paper cost estimation is implemented as a pure, read-only quote
layer in `kquant_crypto/dex_paper.py`. It uses the contemporaneous pool
liquidity, price impact, DEX fee, token tax, Gas and source snapshot ID. It
does not create a wallet transaction or a broker order, and it cannot bypass
the `allowed_paper` flag stored by EVAL.

Notification delivery is also policy-gated: ordinary alerts are capped at
five per local day, quiet hours suppress ordinary alerts, and `RISK`/`CRITICAL`
alerts are exempt from quiet hours and the daily cap. Suppressed deliveries
are retained as audit records; Web Push and Telegram retry transient failures
up to three times.

The instruction supervisor is downstream of EVAL only. It records
`MONITORING`, `READY`, `TRIGGERED`, `INVALIDATED`, `EXPIRED` and `EXIT_REVIEW`
states, but the current foundation policy keeps `allowed_alert`, `allowed_paper`
and `allowed_shadow` closed. A state projection is not an order and cannot
access an exchange account or wallet.

The CEX signal runtime only evaluates completed 5m candles after enough
history exists. It creates auditable factor snapshots and plan drafts, then
hands them to EVAL; it cannot send alerts directly. A forming candle, stale
provider, unknown security state or closed model gate remains blocked.

## Stocks/Crypto gateway

The optional local gateway now serves the first unified React shell plus a
platform health contract. Build `../platform/web`, then start it with
`python -m kquant_crypto gateway` on port `8020`. The shell links to the
independent stock backend on `8001` and crypto backend on `8010`, while keeping
database, session and API contracts separate. A gateway health result with
`data_mixing=false` is required before using it as the shared entry point.

The current shell is a local composition layer, not a production single-origin
reverse proxy. A hosted deployment still needs stable backend URLs, shared
authentication design, monitoring, backup and rollback verification.

Staging Postgres is represented by a fail-closed readiness contract and is not
claimed as configured until `KQUANT_CRYPTO_STAGING_DATABASE_URL` is supplied
and a separate migration/restore test passes. Local SQLite remains the active
development database.

The local staging contract can be inspected without exposing the DSN:

```powershell
python -m kquant_crypto staging status
python -m kquant_crypto staging verify
python -m kquant_crypto staging migrate  # only after a staging DSN is configured
```

Public evidence collection is explicit and source-timed. Binance or OKX
derivatives can be collected without an account key; ETF and on-chain evidence
requires a configured JSON endpoint and is never filled with synthetic values:

```powershell
python scripts/collect_public_evidence.py --symbol BTC --symbol ETH
python scripts/collect_public_evidence.py --source okx --symbol BTC --symbol ETH
python scripts/collect_configured_evidence.py --source official_etf_feed --category etf_flow --symbol BTC --symbol ETH
python scripts/collect_configured_evidence.py --source onchain_metrics_feed --category onchain --symbol BTC --symbol ETH
```

The Stocks/Crypto gateway at `http://127.0.0.1:8020/` serves the unified shell.
`/api/platform/health` and `/api/platform/summary` expose the two independent
modes; the gateway does not merge sessions, proxy market data, or create a
shared trading path.

The Shadow Observation Ledger records real calendar observations, user review
status and immutable outcomes. Simulated days cannot satisfy its 15-trading-day
gate. Current status is expected to remain `NO_GO` until real observations and
the locked validation gate both pass.

When the validation gate eventually authorizes Shadow, capture the current
EVAL-approved set with the explicit local command below. It skips plans without
point-in-time cutoff/coverage, is idempotent, and reports `synthetic_days_created: 0`:

```powershell
python scripts/capture_crypto_shadow.py
```

CEX and DEX/MEME factors use separate registered namespaces. The current
versions are `crypto_factor_v1.0.1` and `crypto_meme_factor_v1.0.0`; EVAL may
recognize both namespaces, but it does not merge their scores or loosen the
security, model, Paper or Shadow gates.

## Roll research boundary

`crypto_early_v1.0.0` remains the comparison baseline. The new
`crypto_roll_v1.0.0` policy is deterministic and point-in-time: it can only
use realized profit as roll capital, never adds while a position is floating
at a loss, and requires actual instrument mappings for ETHU and MSTU. Bayesian
posteriors and Monte Carlo paths are evidence records, not execution
authorization. The roll API deliberately stops before EVAL/Alert/Paper/Shadow;
its response keeps `eval_required=true` and all downstream permissions false
until the independent OOS gates are passed.

The validation report includes a locked 60/20/20 date split and disjoint
expanding OOS folds. It reports evidence status, expected R, average win/loss
ratio, Profit Factor, maximum drawdown and bootstrap intervals. Missing
history returns `simulation_unavailable` or `NO_GO`; no probability or trading
claim is synthesized from absent data.
