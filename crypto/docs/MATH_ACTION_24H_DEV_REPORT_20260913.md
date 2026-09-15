# KQUANT 24H Mathematical Action Study - DEV Report

Date: 2026-09-13

## Decision

The first mathematical-action implementation is runnable and reproducible, but it is not profitable evidence and is not admissible for Paper, Testnet, or Live trading.

- Engineering: `BUILD_PASS` for the isolated research path.
- Spot data: `ELIGIBLE_FOR_EXPOSED_DEV_RESEARCH`.
- Perpetual data: `DATA_BLOCKED`.
- Bayesian model: `DIAGNOSTICS_FAILED`.
- Performance: `PERFORMANCE_UNPROVEN`.
- Admission: `ABSTAIN`.
- Effective action: `WAIT`.

## What Changed

This study does not wait for a technical signal and then ask a model to approve it. At every completed hour it creates the same action set:

1. Long BTC Spot.
2. Long ETH Spot.
3. Long SOL Spot.
4. Short BTC Perpetual.
5. Short ETH Perpetual.
6. Short SOL Perpetual.
7. Wait.

The current frozen data only supports the three Spot-long actions. Perpetual-short actions stay blocked because no frozen USD-M Futures OHLCV, mark-price, and actual-funding dataset is registered.

The first model inputs are deliberately small and mathematical: 1H/6H/24H log returns, 24H realized and downside volatility, 24H turnover-proxy change, and 6H relative return against the equal-weight three-coin market. No EMA, RSI, MACD, chart pattern, LLM feature, TCN, or LightGBM is used.

## Frozen Contract

- Version: `math_action_24h_dev_v1.0.0`.
- Contract hash: `3c60e7379937cd66fa47501606b54b28ea1b94adb0e8cfaf509ec2615d30519f`.
- Dataset hash: `1ddfa28adfa797b068c1f24af768668973ebc3db94aa4bff0a1cc477fb5ad7f6`.
- Panel hash: `695a2c6a85d6cfb3524f922f239bfd5f99374ef9a38d5995839cb786ed6d4f51`.
- Source scope: `DEV_ONLY / EXPOSED_RESEARCH`.
- Signal clock: every completed hour.
- Horizon: next 24 hours.
- Entry: next exact 5-minute bar open.
- Stop/target: 1x/2x 24-hour volatility from the frozen signal reference.
- Same-bar stop/target collision: stop first.
- Entry outside the frozen plan: not filled; never backfilled.
- Spot cost: 10 bps fee and 5 bps slippage per side.
- Risk: 0.25% per trade, 0.50% total open risk, two positions maximum.
- Execution/admission: disabled.

## Data Evidence

- Signal range: 2025-07-28 15:00 UTC through 2026-04-12 00:00 UTC.
- Last label end: 2026-04-13 00:00 UTC.
- Hourly cross-sections: 6,178.
- Potential actions: 18,534, exactly 6,178 per symbol.
- Mature filled labels: 18,534.
- Purged boundary rows: 288.
- Train rows: 11,091.
- Validation rows: 3,576.
- Diagnostic rows: 3,579.

All historical availability is assumed at candle close. It is not receipt-time or exchange-fill evidence. The turnover input is close times base volume, not exchange-native quote turnover. Hourly 24-hour labels overlap and are dependent observations.

## Ridge Baseline

The Ridge model was trained only on a fixed 24-hour stride inside the development-train partition. It selects the highest predicted Spot-long net R at each hour when that estimate is positive; otherwise it waits.

Action-level descriptive results:

| Partition | Selected | Mean net R | PF | Win rate | Payoff |
| --- | ---: | ---: | ---: | ---: | ---: |
| Train | 805 | -0.066 | 0.819 | 47.83% | 0.894 |
| Validation | 233 | -0.207 | 0.499 | 37.77% | 0.822 |
| Diagnostic | 226 | -0.032 | 0.929 | 42.92% | 1.236 |

Frozen risk-budget portfolio replay:

| Partition | Trades | Mean net R | PF | Win rate | Net PnL |
| --- | ---: | ---: | ---: | ---: | ---: |
| Train | 152 | -0.184 | 0.592 | 40.79% | -681.73 USDT |
| Validation | 49 | -0.241 | 0.477 | 32.65% | -272.33 USDT |
| Diagnostic | 49 | -0.051 | 0.878 | 42.86% | -58.70 USDT |

Initial research capital was 10,000 USDT. Final cash was 8,987.25 USDT, a loss of 1,012.75 USDT. Ridge is rejected as a trading candidate.

## Bayesian Student-t Model

- Likelihood: Student-t over costed 24-hour net R.
- Hierarchy: partially pooled symbol intercepts.
- Training rows: 462 non-overlapping daily-stride rows across 154 time slices.
- Chains/draws: 4 chains, 1,000 tune plus 1,000 draws per chain.
- Sampler: NumPyro NUTS.
- R-hat max: 1.0040.
- Bulk ESS min: 1,103.
- Tail ESS min: 834.
- BFMI minimum: 0.8967.
- Divergences: 7.

The divergence limit is zero, so the artifact fails diagnostics. Before applying that fail-closed rule, 39 of 18,534 action rows had a 5th percentile conditional-mean posterior above zero. These rows cannot be promoted because the sampler failed. The effective policy therefore generated zero trades and selected `WAIT`.

The positive result observed inside those 39 rows is not reported as model performance: the data is exposed, the posterior is not calibrated, diagnostics failed, and selecting the rows after fitting is not an independent test.

## Monte Carlo Risk Evidence

The raw 39 Bayesian q05 candidates were passed to a point-in-time, volatility-regime-conditioned block bootstrap. Each eligible candidate used 5,000 historical 24-hour paths assembled only from 5-minute returns available before its signal time.

- Candidates submitted: 39.
- Completed: 23.
- Abstained for insufficient same-regime blocks: 16.
- Mean expected net R across completed candidates: -0.936R.
- Candidates with positive simulated expected net R: 0.
- Mean stop-first frequency: 97.81%.
- Mean target-first frequency: 2.19%.
- Same-regime historical blocks per completed case: 30 to 56.

These are uncalibrated bootstrap frequencies, not market probabilities. They nevertheless provide a strong risk veto against the current 1-sigma stop, 2-sigma target, 24-hour holding geometry. Monte Carlo cannot upgrade the failed Bayesian artifact, so the effective action remains `WAIT`.

## Old Strategy Comparison

The old technical reference and new mathematical study share the same market dataset hash, but use different opportunity populations and execution policies. They are not a paired contest.

- Old `ORIGINAL_1`: 27 trades, mean -0.159R, PF 0.574, net PnL -106.99 USDT.
- New Ridge mathematical replay: 250 trades, net PnL -1,012.75 USDT.
- New Bayesian mathematical decision: 0 trades because diagnostics force `WAIT`.

The first mathematical formulation has not solved the profitability problem. Its immediate value is architectural: action choice now comes from an explicit net-R distribution and can fail closed, rather than from a traditional indicator score.

## Reproduction

Working directory:

```powershell
cd C:\Users\Administrator\Desktop\KQUANT-\crypto
```

Freeze and build the action panel:

```powershell
.\work\hybrid_runtime_restore_env_20260906\Scripts\python.exe scripts\run_math_action_24h_dev.py freeze --output outputs/math_action_24h/<new-run-id>
.\work\hybrid_runtime_restore_env_20260906\Scripts\python.exe scripts\run_math_action_24h_dev.py build-labels --output outputs/math_action_24h/<new-run-id>
.\work\hybrid_runtime_restore_env_20260906\Scripts\python.exe scripts\run_math_action_24h_dev.py baseline --output outputs/math_action_24h/<new-run-id>
```

Fit and predict in the isolated Bayesian environment:

```powershell
.\work\hybrid_dev_fit_fast_env\Scripts\python.exe scripts\run_math_action_24h_dev.py fit --output outputs/math_action_24h/<new-run-id> --sampler numpyro
.\work\hybrid_dev_fit_fast_env\Scripts\python.exe scripts\run_math_action_24h_dev.py predict --output outputs/math_action_24h/<new-run-id>
```

Replay and compare:

```powershell
.\work\hybrid_runtime_restore_env_20260906\Scripts\python.exe scripts\run_math_action_24h_dev.py replay --output outputs/math_action_24h/<new-run-id>
.\work\hybrid_runtime_restore_env_20260906\Scripts\python.exe scripts\run_math_action_24h_dev.py compare --output outputs/math_action_24h/<new-run-id>
.\work\hybrid_runtime_restore_env_20260906\Scripts\python.exe scripts\run_math_action_24h_dev.py report --output outputs/math_action_24h/<new-run-id>
```

Every command refuses to overwrite an existing artifact.

## Next Research Gate

1. Diagnose the seven divergences without inspecting or optimizing performance outcomes. Any model revision must receive a new version and preregistration.
2. Add a frozen USD-M Futures dataset with actual Funding and mark-price history before implementing the independent short model.
3. Add the preregistered 5,000-path Monte Carlo risk veto after the Bayesian fit passes sampler diagnostics.
4. Run untouched forward observations and an independent chronological holdout before claiming calibration or profitability.
5. Keep EVAL, Paper, Testnet, Live, and all order paths disabled until those gates pass.
