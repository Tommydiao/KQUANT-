# KQUANT CRYPTO Roll Research Progress

## Scope

This checkpoint implements the first research layers from the unfinished-work
plan without changing the US equity runtime and without adding any account,
wallet, private-key or order path.

## Completed

- Frozen `crypto_roll_v1.0.0` policy with explicit actions, actual asset
  mappings, point-in-time cutoffs and deterministic IDs.
- Realized-profit-only roll capital; floating losses cannot become an add.
- Separate roll ledger for realized profit, rolled capital and remaining risk.
- Point-in-time Bayesian posterior with source freshness and missing-field
  fail-closed behavior.
- Deterministic regime-conditioned Monte Carlo research layer with 5D, 20D and
  60D horizons, fixed seed, path-count limits and leveraged-ETF friction.
- External evidence records for ETF, derivatives, on-chain, whale and market
  structure inputs. Missing AAVE, ENA, ZEC or PUMP fields remain `N/A`.
- Locked roll validation with next-bar entry, costs, gap handling, stop-first
  resolution, 60/20/20 date partitions and disjoint expanding OOS folds.
- Schema migrations 13-16 and authenticated research-only API endpoints.
- Structured Roll Feature Packet with explicit Bayesian, Monte Carlo, external
  evidence and validation sections; no hidden probability or authority field.
- Registered evidence-source capability reporting without exposing keys.
- Roll Journal OCR text preview that is always non-writable until a separate
  user-confirmed ledger action.
- Crypto dashboard Roll Desk summary, with a read-only Stocks/Crypto gateway
  that keeps the two backends, databases and sessions separate.
- Immutable Shadow Observation Ledger with user review, outcome and audit
  records; the 15-calendar-trading-day gate remains closed.
- Secret-free operations summary plus explicit SQLite backup and restore
  scripts. Staging Postgres is represented as a fail-closed readiness check,
  not as a configured deployment.

## Evidence and gate status

- No production external ETF/on-chain/whale adapter was added in this
  checkpoint, so the evidence layer is schema/API ready but not a coverage
  claim.
- No real historical roll dataset, 15-day Shadow Observation or Paper result
  exists yet.
- The validation gate remains `NO_GO` until sample, OOS, cost and drawdown
  thresholds are met.
- Bayesian and Monte Carlo outputs are advisory research records; Roll API
  responses keep alert, Paper and Shadow permissions closed and still require
  EVAL downstream.

## Verification

- Python tests and frontend build are run after this checkpoint.
- Read-only boundary scanning remains mandatory.
- The current branch is `codex/crypto-v1-foundation`; this checkpoint is an
  uncommitted rollback point until the user requests a commit or publication.

## Next work

1. Connect source-specific ETF, derivatives, on-chain and whale collectors
   behind the external evidence contract; current adapters remain optional
   and return N/A when not configured.
2. Build real closed-candle roll datasets and run the locked validation API.
3. Run the 15-calendar-trading-day Shadow Observation and record outcomes;
   simulated days cannot substitute for this evidence.
4. Configure and verify protected Staging Postgres only after local restore
   tests pass.
