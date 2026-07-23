# Backtest Validation And Evidence

## Scope

KQUANT validates deterministic, long-only research signals. The validation
runtime has no broker, account, position, order, or automatic-execution path.
Historical policy replay and prospective AI-action observation remain separate
evidence sources.

## Portfolio Replay

`kquant.portfolio_backtest` replays completed long trades with a cash-only
portfolio model:

- initial cash, maximum positions, maximum position value, per-trade risk, and
  total open risk are explicit configuration;
- simultaneous entries are ordered by deterministic rank/score then symbol;
- insufficient cash or risk capacity produces a recorded rejection;
- exits release cash before later entries; and
- no margin or short position is permitted.

The report includes total and annualized return, maximum drawdown, Sharpe,
Sortino, Calmar, Profit Factor, win rate, R statistics, consecutive losses,
event-time exposure, turnover, and trade count. Event-time NAV is not an
intraday mark-to-market series, so these statistics are research indicators,
not live-performance projections.

## Benchmarks And Audit

Validation reports include SPY/QQQ buy-and-hold, SPY EMA20/EMA50 trend, and a
deterministic-policy-only reference. Every run writes JSON and Markdown audit
files with a data snapshot hash, strategy configuration hashes, validation
configuration, runtime details, and a reproducibility fingerprint. Timestamps
and output paths are excluded from the fingerprint.

## Overfit Controls

The robustness layer provides:

- chronological rolling walk-forward windows with an embargo;
- neighbouring EMA, volume, ATR-stop, and R:R variants replayed from scratch;
- risk-on/off, volatility, and trend slices;
- symbol, sector, and stock-layer concentration, including removal of the best
  five symbols;
- bootstrap mean-R and Wilson win-rate intervals;
- an approximate deflated-Sharpe check plus a trial-count record; and
- a 0-100 Evidence Score for deciding whether forward observation is allowed.

The Evidence Score is never a buy signal. A strategy can be frozen for forward
observation only when an explicit validation audit fingerprint exists and the
score reaches 70. The current canonical strategy is
`swing_long_v1.1.0`; no evidence is relabelled retroactively.

## Remaining Limits

Historical universe membership is still survivorship-limited, and Longbridge
entitlements require an owner-supplied credentialed audit. Results with small
sample counts must remain labelled insufficient or limited evidence.
