# P1 Data And Validation Contract

## Scope and identity

Every stock or crypto research result must include these fields:

`market`, `symbol`, `instrument_id`, `product`, `direction`,
`strategy_version`, `dataset_hash`, `snapshot_id`, `build_sha`, `run_id`,
`evaluated_at`, `source_status`, `coverage_scope`, `gate_status`, and
`failed_checks`.

The workspace may present these fields together, but it must not join stock
and crypto datasets or use one market's provider health to satisfy another
market's gate.

## Coverage definitions

| Coverage type | Meaning | May qualify a strategy gate? |
| --- | --- | --- |
| Display freshness | latest quote/candle is recent enough for the UI | no |
| Historical validation coverage | closed bars cover the frozen test interval | yes, with PIT checks |
| Signal-time eligibility | enough closed history existed at the signal timestamp | yes |
| Continuous collection | one collector ran with acceptable SLOs | only for runtime evidence |

Forming candles are display-only. They cannot create features, labels, signals,
plans, EVAL approvals, validation trades, or execution intents.

## Crypto strategy contract

The active execution candidate is a Spot-long unit using a closed `1H` setup
and a closed `5m` trigger. A dataset containing only `1H` data can support a
partial research result but cannot be called a complete validation of this
two-timeframe strategy.

Signal-time logic is frozen as follows:

1. Features may use only bars and external evidence with `available_at` at or
   before the signal timestamp.
2. A signal is generated after a closed bar. The earliest simulated entry is
   the next valid tradable bar.
3. Stop and target touched in the same bar resolve to stop first. Gaps use the
   first executable price, not an idealized stop price.
4. Data are split by time, with purge and holding-period embargo. The locked
   test partition is not used for parameter selection, calibration, or model
   choice.
5. Binance Spot validation uses 10 bps per side fee and 5 bps per side
   slippage. The stress report doubles both assumptions.

## Required independent evidence

For a `strategy_version x symbol x product x direction` execution unit:

| Check | Requirement |
| --- | --- |
| OOS folds | at least 3 locked folds |
| Aggregate completed test trades | at least 200 |
| Per-unit completed test trades | at least 30 |
| Bootstrap 95% lower bound of Expected R | greater than 0 |
| Profit Factor | at least 1.25 |
| Stress-cost Profit Factor | at least 1.05 |
| Average win / absolute average loss | at least 1.5 |
| Maximum drawdown | at most 10R |
| Best-asset removal | remaining Expected R greater than 0 |

Any absent, stale, mismatched, or failed value is a fail-closed result. The
current `crypto_spot_momentum_v2.1.0` report remains a negative baseline and
does not qualify BTC, ETH, SOL, ARB, ZEC, PUMP, or HYPE for Testnet automation.

## Models and EVAL

Bayesian, Monte Carlo, Logistic, and Quantile outputs are evidence objects,
not replacements for validation. Each must declare the training cutoff,
feature order, dataset/snapshot hashes, random seed when applicable, and
calibration status. Simulation paths do not increase the number of historical
trades.

EVAL consumes only registered factors and complete plan evidence. Unknown
factors, stale data, missing BBO, incomplete plans, invalid model metadata, or
failed strategy gates cannot be upgraded by LLM output. LLM output is advisory
and must not change EVAL, entry, stop, target, risk limits, or execution
authorization.

## Data collection SLOs

The first implementation pass uses these provisional SLOs until a provider
contract supersedes them:

| Scope | Target | Failure handling |
| --- | --- | --- |
| BTC/ETH/SOL 5m and 1H validation span | 99% closed-bar coverage | block validation unit |
| Research-universe 5m and 1H validation span | 90% closed-bar coverage | exclude failing unit, retain audit record |
| Public collector heartbeat | no gap greater than 5 minutes during a declared run | mark continuous-run evidence partial |
| Provider or cross-source conflict | detected and persisted | no promotion beyond watch-only |

Historical backfill, continuous collection, and live quote freshness must be
reported separately. Missing provider data is `N/A` or `data_caution`; it must
never be coerced into a passing numeric feature.
