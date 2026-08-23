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
database migration for this contract is schema v12; v9 adds the EVAL-derived
research instruction projection and its state events, v10 adds immutable
model-evidence metadata, v11 records validation partition/OOS-fold evidence,
and v12 records signal-time factor values for leakage-safe model benchmarks
without rewriting legacy rows. Model files themselves are never
stored by the app.

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

CEX and DEX/MEME factors use separate registered namespaces. The current
versions are `crypto_factor_v1.0.1` and `crypto_meme_factor_v1.0.0`; EVAL may
recognize both namespaces, but it does not merge their scores or loosen the
security, model, Paper or Shadow gates.
