# Early Trend 3-15D v1.0.0

`early_trend_3_15d_v1.0.0` is a read-only, long-only research strategy for ordinary US stocks and non-leveraged ETFs.

## State contract

- `EARLY_WATCH`: daily setup score is at least 60.
- `ARMED`: daily setup score is at least 72 and setup data/event gates are clear.
- `BUY_REVIEW`: an armed setup also has a closed 1H trigger score of at least 70, a closed 5m confirmation, fresh Longbridge BBO, and a regular-session clock. Until validation gates pass, this remains paper-only.
- `LATE_WAIT_PULLBACK`: five-day return is above 15% or EMA20 extension is above 10%.
- `INVALIDATED`: price structure and relative strength have both reversed.

The daily setup uses only completed daily candles. The intraday trigger uses only completed 1H and 5m candles. Ordinary quote ticks can update display prices but cannot change the strategy state.

## Factor groups

The 100-point setup contains fast EMA turn or constrained ignition (25), relative strength and acceleration versus SPY/QQQ (20), volume accumulation (20), base/breakout structure (20), and liquidity/risk (15). Every factor carries its own timestamp and contribution.

The constrained ignition path requires a strong daily close, a break above the prior five closes, proximity to EMA8, and positive five-day relative strength versus SPY. It is designed to detect the first confirmed expansion from a base without treating an arbitrary downtrend bounce as a buy signal.

## Evidence boundary

Historical daily setup evidence and intraday trigger evidence are reported separately. `BUY_REVIEW` cannot leave paper-only mode until the sealed test set has at least 100 completed trades, the 95% bootstrap lower bound of average R is positive, Profit Factor is at least 1.25, maximum drawdown is at most 8%, and 20 trading days with 30 prospective triggers have completed.

This strategy cannot access accounts, positions, brokers, or order submission.
