# Strategy Specification: swing_long_v1.1.0

Status: frozen deterministic specification for implementation and validation

## Scope

`swing_long_v1.1.0` is the sole canonical strategy for the 84-day plan. It is
a long-only US stock/ETF tactical swing strategy with a target holding horizon
of 3-7 trading days. It uses a closed daily bar for trend and a closed 1-hour
bar for entry confirmation.

This is a deterministic policy. AI may summarize the evidence and propose a
manual plan, but it cannot calculate a different score, bypass a veto, promote
`PASS` to `BUY SETUP`, modify a stored candle, or submit an order.

## Universe and eligibility

- The input is the active point-in-time Core universe membership as of the
  signal date. Until historical membership is built, every historical report
  must label the survivorship limitation.
- Only US stocks and ETFs in that universe are eligible.
- Direction is `LONG` only. There is no short, options, crypto, leverage, or
  broker-execution behavior.
- Required bars: at least 60 completed daily bars and 20 completed 1-hour bars.
- A forming daily or 1-hour bar may be rendered but is excluded from all
  feature, signal, and validation calculations.

## Data inputs

| Input | Definition |
| --- | --- |
| Daily close and volume | Most recent closed 1D candle; trends and volume are measured here. |
| Hourly close | Most recent closed 1H candle; entry confirmation is measured here. |
| EMA | Standard recursive EMA on the ordered close series, using the first available close as the initial value. |
| ATR percent | Average true range over the latest 20 daily candles, expressed as a percent of each bar close. |
| Volume ratio | Latest daily volume divided by the mean of the preceding up-to-20 daily volumes. |
| 1H momentum | Percentage change from the 1H close seven bars earlier to the latest closed 1H close. |
| Extension | Percentage difference between the latest closed daily close and daily EMA20. |

All input timestamps and calculations use only data available at the signal
close. Any missing, stale, fallback, or malformed required input blocks a
buy-class result.

## Parameters

| Parameter | Value |
| --- | ---: |
| Daily EMAs | 8, 9, 20, 50, 200 |
| 1H EMAs | 8, 9, 20, 50 |
| Trend return window | 5 trading days |
| 1H momentum window | 7 completed 1H bars |
| ATR lookback | 20 daily bars |
| Volume baseline | preceding 20 daily bars, excluding latest bar |
| Strict score threshold | 88 |
| Watch score threshold | 65 |
| Minimum 1H momentum for strict setup | 0.6% |
| Minimum volume ratio for strict setup | 1.20 |
| Maximum ATR for strict setup | 5.0% |
| Extension window for strict setup | -2.5% to +5.5% versus daily EMA20 |
| Historical focus horizon | 5 daily bars |
| Minimum strict evidence | 10 samples, 55% focus win rate, average focus return above 0.4% |
| Nominal maximum holding period | 7 trading days |

## Score calculation

Let `r5` be 5-day daily-close return in percent, `m1h` be 1H momentum in
percent, `v` be volume ratio, `a` be ATR percent, and `e` be extension percent.
`clamp(x, low, high)` limits `x` to the stated interval.

```text
trend = clamp(
  14 * I(close > EMA20)
  + 14 * I(EMA20 > EMA50)
  + 14 * I(EMA50 > EMA200)
  + clamp(2.2 * r5, -8, 18),
  0, 52
)

trigger = clamp(
  12 * I(close_1h > EMA20_1h)
  + 7 * I(EMA20_1h > EMA50_1h)
  + clamp(3.0 * m1h, -8, 11),
  0, 30
)

volume = clamp(18 * (v - 0.75), 0, 18)

risk = clamp(
  18
  - min(8, 1.4 * max(0, a - 5))
  - min(7, max(0, e - 7))
  - min(5, 0.8 * abs(min(e, -2))),
  0, 18
)

score = round(clamp(trend + trigger + volume + risk, 0, 100), 1)
```

Every component and final score must be persisted with the strategy version.

## Classification and hard gates

The level is assigned in this order:

1. `BUY SETUP` only when `score >= 88` and every strict gate is true:
   - daily structure: `close > EMA20 > EMA50 > EMA200`;
   - 1H structure: `close_1h > EMA20_1h > EMA50_1h` and `m1h >= 0.6%`;
   - `volume_ratio >= 1.20`;
   - ATR and extension are inside the parameter window;
   - daily and 1H data are `available`, are from Longbridge when Longbridge is
     the selected primary provider, and are not forming bars; and
   - historical focus evidence meets the minimum sample, win-rate, and return
     criteria.
2. `WATCH` when `score >= 65`, daily close is above EMA50, 1H momentum is above
   -1.5%, and the required data is available for research. `WATCH` is never a
   trading authorization.
3. `PASS` in all other cases.

Separately, `DATA_CAUTION` or `RISK_OFF`, stale/provider-failed data, a missing
or stale regular-session quote, an incomplete bar, an invalid stop, R:R below
2.0, insufficient evidence, or a failed route/data safety check blocks a fresh
manual long review. These conditions may downgrade an AI action but cannot be
overridden by it.

## Market regime filter

The regime is computed from closed daily SPY, QQQ, IWM, and VIX inputs.

- `RISK_ON`: clean data; SPY and QQQ above EMA50 and EMA200 with EMA20 above
  EMA50; IWM above EMA50 and EMA200; VIX below 22.
- `RISK_OFF`: failed benchmark data, VIX at or above 28, SPY or QQQ below
  EMA200, SPY 20-day return at or below -8%, or QQQ 20-day return at or below
  -10%.
- `DATA_CAUTION`: one or more required benchmark datasets are unavailable or
  stale.
- `MIXED`: all other valid states.

`DATA_CAUTION` and `RISK_OFF` block buy-class actions. `MIXED` permits only
careful manual review after all stock-level gates pass.

## Entry, stop, target, and invalidation

For a valid tactical setup, use the current closed daily price `C`, daily EMA20
`E20`, EMA50 `E50`, and ATR decimal `A = max(ATR% / 100, 0.01)`:

```text
entry_low  = min(C, 0.99 * E20)
entry_high = max(1.005 * C, 1.015 * E20)
stop       = min(0.985 * E50, C * (1 - clamp(A, 0.035, 0.07)))
target_1   = entry_high + 2.0 * (entry_high - stop)
target_2   = entry_high + 2.6 * (entry_high - stop)
R:R        = ((target_1 + target_2) / 2 - (entry_low + entry_high) / 2)
            / ((entry_low + entry_high) / 2 - stop)
```

The plan is invalidated when the daily close loses the planned stop, the 1H
close loses the EMA20/EMA50 area, ATR or exit risk expands materially, data
becomes stale/failed, or the market regime becomes `RISK_OFF`. No chase is
permitted above the entry zone. A manual real-money review additionally needs
R:R at least 2.0, a saved journal, and every later-stage Go/No-Go gate.

## Versioning rule

This document defines `swing_long_v1.1.0`. Any change to a parameter, score
weight, classification threshold, stop/target formula, universe rule, market
filter, or confirmation rule creates a new strategy version. Past signals,
journal entries, and validation results remain bound to their original version
and must never be recomputed in place.

## Current implementation alignment

The current workflow exposes only `swing_long_v1`; legacy profiles are marked
comparison-only. Signals, journals, and validation records bind the immutable
strategy version and configuration hash. The strict gate consumes the
machine-readable candle data-quality decision, so fixture, Yahoo fallback,
stale, malformed, or otherwise non-clean data cannot promote a signal to
`BUY SETUP`.
