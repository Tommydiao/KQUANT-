# Technical Feature Contract

`kquant.technical_features` is the single deterministic feature interface for
the canonical strategy. Its version is `technical_features_v1`.

It defines EMA, ATR percent, RSI-14, volume expansion, trend slope,
distance/extension, and gap risk with a minimum input length and null policy
for every feature. Callers must pass completed, time-ordered candles; forming
bars are excluded by the contract.

`build_signal` now consumes this contract for its existing EMA, ATR, volume,
and 1H momentum inputs, and persists the added RSI, trend-slope, and gap-risk
observations for audit. These new observations do not change the frozen scoring
weights or thresholds in `swing_long_v1.1.0`.
