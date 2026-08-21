# KQUANT v2 Week 12 Gate Repair: Market Availability Contract

Date: 2026-08-22
Branch: `codex/kquant-v2-gap-analysis`
Scope: read-only point-in-time data semantics. No broker, account, position,
order, execution, or market-data permission change was added.

## 1. Why this repair is required

The prior snapshot and replay implementation used a candle's local
`fetched_at` time as the availability cutoff. That is safe against one form of
look-ahead bias, but it also rejects valid provider history whenever the data
was backfilled after the market session. It would prevent a correct historical
replay from using a bar that had objectively closed at the signal time.

KQUANT now separates three facts:

- `as_of_time`: the decision cut-off requested by a strategy or replay.
- `available_at`: the earliest conservative market-time at which the completed
  bar can affect a decision.
- `fetched_at`: when this KQUANT installation retrieved or persisted the row.

The data still retains `fetched_at` for audit, provider revision analysis, and
prospective-observation accounting. It is not substituted for market
availability in a historical policy replay.

## 2. Contract

Contract identifier: `market_bar_close_bound_v1`.

`kquant.market_availability.candle_available_at()` derives availability from
the candle open time and its declared interval:

- 1m, 5m, 15m, and 1H bars become eligible only after their full interval.
- Daily, weekly, and monthly bars use deliberately conservative calendar
  close bounds of one day, seven days, and thirty-one days respectively.
- A source row may supply an explicit `market_available_at`; otherwise the
  deterministic interval bound applies.
- Forming candles remain excluded before this calculation.

For the Longbridge daily records used by this project, the canonical closed
bar timestamp is the start of the trading date in the exchange time basis, so
the one-day bound occurs before the following session's open. Entry still uses
the next daily bar's open and never the signal bar's close as a fill.

## 3. Implemented version changes

- `data_snapshot_v1.1.0`: snapshot items store close-bound `available_at`,
  retain `fetched_at`, include historical-backfill counts, and declare
  provider-history revision risk.
- `stock_quant_model_0_v1.1.0`, feature, label, and dataset contracts:
  features use only bars closed by `as_of_time`; a signal forms at daily close;
  the next bar is the simulated entry; label completion occurs at the exit
  bar's close bound.
- `stock_quant_validation_v1.3.0`: cache dataset construction and market
  regime use the same availability helper; historical source policy advances
  to `longbridge_pit_stock_quant_v2`.
- `stock_quant_readiness_v1.1.0`: SQL coverage checks apply the same daily
  and 1H close bounds.
- Freeze, forward-observation, shadow-readiness, and production-readiness
  paths reject a prior validation run whose dataset, feature, label, or
  validation contract is no longer current.
- Application/API contract: `kquant-api-2026-08-22-v2-oos-shadow-v4`.

Existing v1 snapshots and validation reports stay immutable for audit, but
they are not current-contract compatible and cannot unlock Shadow Observation.

## 4. Leakage controls and residual risks

- Future rows cannot enter a feature or benchmark calculation because their
  close-bound availability is after the requested `as_of_time`.
- A signal is generated only after the daily bar close; simulated execution is
  at the following daily open. Same-bar stop/target conflict remains
  stop-first.
- Historical provider responses can be revised. Such rows are marked through
  `historical_backfill_item_count` and `provider_history_revision_risk`; this
  is historical evidence, not prospective performance.
- Corporate-action adjustment mode, symbol membership history, and earnings
  event timestamps remain separate data-quality requirements. This patch does
  not claim to solve survivorship bias or vendor revision risk.

## 5. Verification

- New unit coverage verifies daily close-bound inclusion/exclusion and
  deterministic timestamp normalization.
- Snapshot, Capital Rotation, Stock Quant feature/label, validation,
  readiness, production-readiness, freeze, forward-pilot, and shadow tests
  verify the shared contract and fail-closed version compatibility.
- The complete regression, frontend build, read-only boundary scan, and
  browser restart are required before this repair is accepted.

## 6. Gate status

This repair makes a controlled Longbridge historical backfill meaningful; it
does not create test trades, prospective observations, or a live trading
approval. The current release decision remains `NO_GO`.
