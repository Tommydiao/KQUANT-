# KQUANT Funds-Behavior and Trend-Persistence Research Report

Date: 2026-09-13  
Scope: BTCUSDT, ETHUSDT, SOLUSDT spot long/cash  
Status: `DEV_ONLY_EXPOSED_RESEARCH`  
Admission: disabled

## Executive conclusion

The measurement defects identified before this experiment were reproduced and
fixed without changing the legacy A/B policies, risk budgets, protection rules,
or execution admission. The correction materially changes the interpretation of
the old Monte Carlo output, but it does not rescue the old strategy.

Four preregistered candidates were then evaluated on real Binance history:

- H1: persistence after an increase in aggressive buying and trading activity.
- H2: persistence of return strength after removing the common three-asset move.
- Each hypothesis was evaluated at fixed 24-hour and 72-hour horizons.

All four candidates failed the Ridge falsification baseline. The hierarchical
Student-t action gate also produced either no trades or negative performance, and
only 5 of 12 sampler runs passed the registered diagnostics. No candidate is
selected. Forward performance observation, EVAL promotion, Testnet, Live, and
exchange execution remain disabled.

## 1. Measurement corrections

### Monte Carlo no-touch paths

The previous close-path implementation represented both "no stop" and "no
target" with the terminal array index, then classified `first_stop <=
first_target` as a stop. A path touching neither boundary was therefore recorded
as `-1R` rather than a time exit at the terminal close.

`math_action_regime_block_bootstrap_dev_v1.0.1` now distinguishes no-touch paths,
records terminal-close time exits, and explicitly labels close-only barrier
frequencies as diagnostic. An OHLC, synchronized multi-asset block-bootstrap path
is available for risk analysis with open-gap priority and same-bar stop-first
semantics. It cannot create an entry signal.

For the same 23 completed old research cases, the aggregate diagnostic changed:

| Metric | Old defective run | Corrected run |
| --- | ---: | ---: |
| Mean stop frequency | 97.81% | 27.95% |
| Mean target frequency | 2.19% | 2.19% |
| Mean time-exit frequency | 0.00% | 69.86% |
| Mean expected R | -0.936R | -0.219R |

This invalidates the old extreme-stop-rate claim. The corrected diagnostic
expected R remains negative and is not a calibrated forecast.

### Candidate selection and label availability

Candidate selection now occurs before inspecting future `label_status`. A
higher-ranked candidate without an available outcome remains unavailable; it is
not silently replaced by a lower-ranked mature winner. A regression test fixes
this contract.

The dataset builder now preserves a stop or target observed before a later data
gap. An unresolved path ending at a gap is `CENSORED`, not `NOT_FILLED` or a
fabricated loss.

### Portfolio accounting

Entry and exit fees are cash-booked, mark-to-market equity is reconstructed from
contemporaneous bars, and the daily loss boundary is UTC. The new experiment uses
5-minute portfolio replay. Historical fills remain an explicitly labelled
next-5-minute-open proxy, not exchange fills or quote-aware evidence.

## 2. Frozen experiment

The immutable contract is `config/trend_evidence_research_v1.json`.

- Universe: BTCUSDT, ETHUSDT, SOLUSDT spot.
- Candidates: exactly H1/H2 x 24H/72H.
- Entry: next 5-minute open after the hourly signal.
- Protection: fixed 1-sigma stop, 2-sigma target, stop-first on an ambiguous bar.
- Base cost: 10 bps fee plus 5 bps slippage per side.
- Stress cost: fixed sequence and full replay at twice the base cost.
- Evaluation: three chronological walk-forward development folds with a 72-hour
  purge and embargo.
- Ridge: fixed L2 penalty of 10 with train-only transformations.
- Main research model: hierarchical Student-t; entry requires posterior mean net
  R 5% quantile above zero and passing sampler diagnostics.

Contract hash:
`8b9fc1f545568951351fd958160b47aa03a58ca15ecbec972cf3437b0ff74852`

All history is already exposed development material. These results are not
independent OOS evidence.

## 3. Data evidence

Native Binance spot records were joined back to the audited research capsule.
The source fields are quote volume, trade count, and taker-buy quote volume.
Aggressor imbalance is a trade-side participation proxy; it is not labelled as
whale flow.

| Item | Result |
| --- | ---: |
| Raw hourly rows | 19,110 |
| Rows per symbol | 6,370 |
| Join conflicts or missing native flow rows | 0 |
| Candidate panel rows | 72,876 |
| 24H rows per hypothesis | 18,291 |
| 72H rows per hypothesis | 18,147 |
| Fold count | 3 |

Enriched dataset hash:
`2fe3ac2d1af8566a027ea16df55b68424a394b21f2f4532a4f68600498d6d054`

Warm-up history is used only for feature initialization and is not counted as an
additional trading period. H2 rolling market sensitivity is estimated from prior
data only.

## 4. Ridge falsification results

| Candidate | Trades | Win rate | Payoff | PF | Mean net R | Max DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| H1_FLOW_24H | 140 | 36.43% | 0.994 | 0.569 | -0.190R | 4.60% |
| H1_FLOW_72H | 121 | 33.06% | 1.274 | 0.629 | -0.227R | 4.84% |
| H2_RESIDUAL_24H | 148 | 38.51% | 0.970 | 0.607 | -0.164R | 4.60% |
| H2_RESIDUAL_72H | 142 | 28.87% | 1.368 | 0.555 | -0.285R | 6.93% |

The simple baseline rejects every hypothesis/horizon pair. Performance also
worsens under the registered double-cost test.

## 5. Hierarchical Student-t results

Twelve candidate-fold fits were completed in the isolated research environment.
Five passed the registered sampler diagnostics; seven failed because of one or
more divergences or insufficient tail ESS. A failed fold abstains.

| Candidate | Gated trades | PF | Mean net R | Decision |
| --- | ---: | ---: | ---: | --- |
| H1_FLOW_24H | 0 | N/A | N/A | Rejected / abstained |
| H1_FLOW_72H | 42 | 0.634 | -0.229R | Rejected |
| H2_RESIDUAL_24H | 0 | N/A | N/A | Rejected / abstained |
| H2_RESIDUAL_72H | 14 | 0.192 | -0.616R | Rejected |

The posterior lower-bound rule did not reveal a viable candidate. Zero trades is
not recorded as successful performance.

## 6. Negative controls, ablation, and dependence audit

The immutable supplementary audit is
`outputs/trend_evidence_controls/controls_20260913_02/controls_audit.json`.
Its random control is matched to realized portfolio trade counts by candidate
and fold, while preserving the source portfolio constraints. The preliminary
`controls_20260913_01` run is retained only to document the earlier hourly
opportunity-count definition.

| Candidate | Model mean R / PF | Price momentum mean R / PF | Flow ablation mean R / PF | Matched random median mean R / PF |
| --- | ---: | ---: | ---: | ---: |
| H1_FLOW_24H | -0.190 / 0.569 | -0.189 / 0.581 | -0.149 / 0.650 | -0.151 / 0.632 |
| H1_FLOW_72H | -0.227 / 0.629 | -0.248 / 0.620 | -0.169 / 0.723 | -0.208 / 0.666 |
| H2_RESIDUAL_24H | -0.164 / 0.607 | -0.189 / 0.581 | -0.123 / 0.703 | -0.172 / 0.589 |
| H2_RESIDUAL_72H | -0.285 / 0.555 | -0.248 / 0.620 | -0.283 / 0.555 | -0.228 / 0.637 |

The random median trade counts are 137, 122, 147, and 143 against model counts
of 140, 121, 148, and 142. H1 flow variables reduce performance relative to the
price-only ablation. H2 24H is slightly less negative than price momentum and
matched random, but remains negative and materially below every gate. H2 72H
does not improve on its ablation or controls.

The equal-weight BTC/ETH/SOL buy-and-hold control has a mean fold return of
-11.25%, a worst fold of -33.37%, and maximum drawdown of 47.05%. This confirms
that the exposed interval is difficult, but it does not excuse a negative
absolute trading result.

Seven-day synchronized UTC block bootstrap, 2,000 fixed-seed paths:

| Candidate | Mean R 5% | Median | Mean R 95% | P(mean R > 0) |
| --- | ---: | ---: | ---: | ---: |
| H1_FLOW_24H | -0.286 | -0.171 | -0.056 | 0.70% |
| H1_FLOW_72H | -0.384 | -0.233 | -0.068 | 1.10% |
| H2_RESIDUAL_24H | -0.254 | -0.154 | -0.047 | 0.95% |
| H2_RESIDUAL_72H | -0.434 | -0.265 | -0.086 | 0.85% |

All upper bounds remain below zero. These are dependence-aware development
intervals, not independent OOS confidence claims.

The lead-time diagnostic also fails to establish a useful early-start advantage:
24H candidates have zero-hour median lead versus a positive trailing 6H return;
72H candidates show two hours, but 49-50 entries were already price-positive at
entry. Future lead data is used only for this post-trade diagnostic and never for
selection.

## 7. Gate decision

| Dimension | Result | Reason |
| --- | --- | --- |
| Engineering | `BUILD_PASS` | Pure research path, replay, artifacts, hashes, and full Crypto regression pass |
| Data | `ELIGIBLE_DEV_ONLY` | Native flow fields joined cleanly; history is exposed and fills are bar proxies |
| Model | `REJECTED` | All candidates fail; only 5/12 Student-t fits pass diagnostics |
| Performance | `PERFORMANCE_UNPROVEN` / descriptive `TARGET_NOT_MET` | No independent OOS, fewer than 200 candidate trades, negative mean R and PF below gates |

The unresolved legacy 10R contract independently prevents a performance PASS.
No result can be used to enable candidate screening, EVAL promotion, Testnet, or
Live execution.

## 8. Reproduction

From `C:\Users\Administrator\Desktop\KQUANT-\crypto`:

```powershell
work\hybrid_dev_fit_fast_env\Scripts\python.exe scripts\run_trend_evidence_research.py freeze --run-id dev_run_20260913_01
work\hybrid_dev_fit_fast_env\Scripts\python.exe scripts\run_trend_evidence_research.py build --run-id dev_run_20260913_01
work\hybrid_dev_fit_fast_env\Scripts\python.exe scripts\run_trend_evidence_research.py ridge --run-id dev_run_20260913_01
work\hybrid_dev_fit_fast_env\Scripts\python.exe scripts\run_trend_evidence_research.py bayes --run-id dev_run_20260913_01
work\hybrid_dev_fit_fast_env\Scripts\python.exe scripts\run_trend_evidence_research.py report --run-id dev_run_20260913_01
```

Primary machine-readable report:
`outputs/trend_evidence_research/dev_run_20260913_01/report_final.json`

Corrected old-research comparison:
`outputs/math_action_24h/dev_run_20260913_corrected_01/report_final.json`

Negative-control and uncertainty audit:

```powershell
work\hybrid_dev_fit_fast_env\Scripts\python.exe scripts\run_trend_evidence_controls.py --source-run-id dev_run_20260913_01 --audit-id controls_20260913_02
```

Output:
`outputs/trend_evidence_controls/controls_20260913_02/controls_audit.json`

Verification completed with the restored Crypto runtime environment:

```text
1271 passed, 10 skipped, 27 subtests passed in 121.82s
Gated execution boundary passed; no arbitrary order, wallet, or withdrawal routes.
```

An initial full-suite collection attempt used the deliberately minimal math-fit
environment and failed on absent application dependencies. No tests ran in that
attempt. The suite was rerun in the correct restored runtime environment and
passed as shown above.

## 9. Next research decision

Do not tune these four candidates against the exposed folds. Archive them as
falsified development hypotheses. The next research proposal must introduce a
new economic hypothesis and a new preregistered experiment, or wait for a frozen
unexposed/forward interval. It must not reopen the restricted interval, change
dates, add assets, or loosen the current gates to manufacture a winner.
