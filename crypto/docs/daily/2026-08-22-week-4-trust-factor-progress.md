# Week 4 Progress Report: Trust, Regime and Transparent Factors

## 1. Goal and completion

The implementation foundation for the data-trust, canonical-universe,
market-regime and transparent-factor layers is complete. This is a code
milestone, not a production evidence milestone: the live collection still
needs to finish its full 24-hour run before the CEX provider Gate can be
reviewed.

## 2. Code, Schema and API

- Migration v3 adds `crypto_data_snapshots`, the point-in-time universe
  registry/membership tables and `crypto_market_regime_snapshots`.
- Migration v4 adds `crypto_factor_definitions` and
  `crypto_factor_snapshots`.
- `data_trust.py` rejects stale, forming, unavailable and cross-source
  conflicting inputs from EVAL-eligible status.
- `universe.py` uses CEX identity or `chain_id + contract_address` rather than
  a ticker-only key.
- `market_regime.py` provides a deterministic fail-closed regime classifier.
- `factor_registry.py` registers twelve versioned, low-redundancy factor IDs
  and persists auditable factor snapshots.
- `signal_agent.py` produces only a stage proposal and factor contribution
  list; `trade_plan_agent.py` produces only a draft.
- `alert_agent.py` refuses any result that is not explicitly authorized by
  EVAL.
- New authenticated read/research routes include factor registry/current
  snapshot and a draft-to-EVAL endpoint. No account, wallet or order route was
  added.

## 3. EVAL behavior

`EvaluationAgent` now passes the registered factor IDs into the fixed EVAL
policy. Unknown factor IDs remain blockers. Each evaluation persists blockers,
source snapshot bindings, supporting/opposing factor evidence and a decision
hash. The foundation policy still returns at most `WATCH_ONLY`; `allowed_alert`,
`allowed_paper` and `allowed_shadow` remain false.

## 4. Verification

- Python: `37 passed`.
- Frontend: Vitest `1 passed`.
- Frontend production build: passed.
- Read-only boundary scan: passed.
- `git diff --check`: passed.
- Public collection is still running for BTCUSDT, ETHUSDT and SOLUSDT through
  Binance Spot and OKX Spot/Perpetual. The latest short inspection showed
  148,463 normalized events and nine partitions; this is not a 24-hour result.

## 5. Risks and Gate

- No historical CEX coverage matrix, OOS result or calibrated model exists.
- No DEX/MEME security provider is enabled.
- The machine/provider clock offset is calibrated and recorded, but long-run
  reconnect and storage-growth behavior remain unverified.
- Forming bars, stale data, unknown security and unknown factors fail closed.

**Gate: NO-GO.** Continue public collection and test work. Do not produce
active Paper/Shadow decisions or performance claims from this short runtime.
