# KQUANT Spot Event Research Report

Date: 2026-09-13  
Run: `outputs/spot_event_research/dev_run_20260913_02`  
Scope: BTCUSDT, ETHUSDT, SOLUSDT Spot long/cash  
Evidence: `DEV_ONLY_EXPOSED_RESEARCH`  
Admission and execution: disabled

## Executive conclusion

The two preregistered event definitions were implemented and evaluated on the
authorized Binance development history. Neither passed the preliminary gate.

- Sell-pressure repair produced 23 mature events. Its 6-hour win rate was
  52.17%, but average net return was -0.316%, descriptive payoff was 0.507 and
  descriptive profit factor was 0.553. Loss magnitude was almost twice win
  magnitude.
- Buy-pressure start produced only 2 mature events. Its 6-hour average net
  return was -1.737%, descriptive payoff and profit factor were both 0.095.
- No event definition was eligible for Student-t fitting or portfolio replay.
  This is the registered stopping rule, not an incomplete run.

The result rejects these exact event definitions on this exposed development
period. It does not establish that every sell-exhaustion or demand-start event
has no economic value.

## Frozen contract

The immutable contract is `config/spot_event_research_v1.json`.

- Events use aligned, closed 5-minute bars to form one 15-minute observation.
- A signal exists only after two additional closed 5-minute confirmation bars.
- Historical entry is the next 5-minute open after confirmation.
- The primary fixed-horizon label is 6 hours; 1-hour and 24-hour labels are
  diagnostics only.
- Each symbol and sample type has a 24-hour cooldown.
- Base cost is 10 bps fee plus 5 bps slippage per side. Double cost is reported.
- Thresholds are estimated separately per symbol and fold from training data.
- Three expanding chronological development folds retain 72-hour purge and
  embargo boundaries.

Contract hash:
`d9e83825a86665af049c96c2f7936eac3c7fa4c86c04f1f9b37162f601154fbe`

## Data validation

| Check | Result |
| --- | ---: |
| Native 5m rows per symbol | 76,440 |
| Total joined native 5m rows | 229,320 |
| Missing timestamps | 0 |
| Conflicting timestamps | 0 |
| Invalid quote volume, trade count or taker-buy values | 0 |
| Event dataset hash stable across two immutable runs | Yes |
| Event panel hash stable across two immutable runs | Yes |

Event dataset hash:
`5df44ef607adf9fd36816c752a2ce97b8a0b8dfb262e85e391e56fc06132aba2`

Event panel hash:
`0978ce8fed5428a8069a5f380fa54268b3b484cdf25f8fa61e3064fd112e2fd9`

Binance native fields used are quote volume, trade count and taker-buy quote
volume. They measure trade-side participation. They do not identify liquidation,
wallet ownership, whale flow or causal capital movement.

## Event results

The following PF and payoff values describe fixed 6-hour event outcomes. They
are not portfolio-strategy performance or execution evidence.

| Event | Mature | Win rate | Mean net return | Payoff | PF | Double-cost mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Sell-pressure repair | 23 | 52.17% | -0.316% | 0.507 | 0.553 | -0.615% |
| Buy-pressure start | 2 | 50.00% | -1.737% | 0.095 | 0.095 | -2.031% |

Sell-pressure repair contained 11 BTC, 7 ETH and 5 SOL events. Its fold means
were +0.423%, -1.392% and +0.256%. The apparent positive result in two folds did
not survive aggregation, costs or uncertainty.

Buy-pressure start contained one BTC and one ETH event, both in the first fold.
The definition is too sparse and its observed mean is negative.

## Price-only controls and uncertainty

| Event | Event 6H mean | Price-only control 6H mean | Observed increment | 95% block interval | Holm-adjusted nonpositive mass |
| --- | ---: | ---: | ---: | ---: | ---: |
| Sell-pressure repair | -0.316% | -0.333% | +0.0165% | -0.683% to +0.725% | 0.86 |
| Buy-pressure start | -1.737% | -0.430% | -1.307% | -1.459% to +0.955% | 0.86 |

The synchronized 7-day block bootstrap preserves shared calendar dependence.
Its nonpositive mass is a development confidence diagnostic, not a calibrated
p-value. Both intervals cross zero and neither event has reliable incremental
evidence over its price-only control.

Diagnostic horizon means:

| Event | 1H | 6H | 24H |
| --- | ---: | ---: | ---: |
| Sell-pressure repair | -0.028% | -0.316% | -0.793% |
| Buy-pressure start | -0.602% | -1.737% | +0.359% |

The positive 24-hour value for buy-pressure start is based on two observations
and has no decision authority.

## Gate result

Sell-pressure repair failed mature sample count, positive base mean, positive
double-cost mean and the adjusted control-increment uncertainty check. It passed
only the mechanical two-positive-fold condition and had a trivially positive
point increment over control.

Buy-pressure start failed every preliminary check. Because no event passed all
checks:

- Student-t fitting was not run.
- Monte Carlo was not used to create or rescue a signal.
- Capital-constrained portfolio replay was not run.
- No forward observer, EVAL promotion, Testnet, Live or exchange path was enabled.

Final status:

| Dimension | Status |
| --- | --- |
| Engineering | `BUILD_PASS` |
| Data | `ELIGIBLE_FOR_EXPOSED_DEV_EVENT_STUDY` |
| Model | `SKIPPED_NO_PRELIMINARY_EVENT_GATE` |
| Performance | `PERFORMANCE_UNPROVEN / EVENT_DEFINITIONS_REJECTED` |

## Reproduction

From `C:\Users\Administrator\Desktop\KQUANT-\crypto`:

```powershell
python scripts\run_spot_event_research.py all `
  --output outputs/spot_event_research/dev_run_20260913_02
```

The output directory is immutable. Use a new run ID to reproduce again.

Regression evidence:

```text
python -m pytest -q
1278 passed, 10 skipped, 27 subtests passed in 107.22s
```

The implementation did not modify the legacy A/B policies, risk budgets,
protection rules, strategy admission or execution switches.
