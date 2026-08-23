# Week 7 Progress Report: Deterministic Validation Foundation

## 1. Goal and completion

The validation foundation is implemented in parallel with the still-open
long-duration provider Gate. It is deliberately not presented as a completed
OOS result: the current Parquet collection is only a short public-data run.

## 2. Implementation

- `backtest.py` replays the deterministic early-start setup policy.
- Signals use bars through an explicit point-in-time index.
- Entries use the next bar open with configurable fee and slippage.
- Gap exits use the actual open; stop and target on the same bar resolve as
  stop-first; overlapping positions are prevented by the maximum holding
  window.
- Reports include sample count, evidence grade, win rate, average R, average
  win/loss R, Profit Factor, drawdown and target/stop-first rates.
- `date_split` partitions by calendar date and records an embargo window.
- Schema v6 stores validation runs and individual trade outcomes.
- `GET /api/crypto/validation/latest` returns `not_collected` until a formal
  dataset builder saves a run.

## 3. Tests and evidence boundary

- Future bars cannot change a factor computed at a fixed `as_of_index`.
- Backtest entries are after the signal bar and cost fields are included.
- Samples below 30 are marked `insufficient`; no performance claim is made.
- Python: `48 passed`.
- Read-only route scan: passed.

## 4. Gate

**NO-GO.** No test-set trade count, calibrated probability, Profit Factor or
maximum-drawdown claim exists yet. The next validation step requires a clean
historical CEX dataset, PIT membership and at least three OOS folds.
