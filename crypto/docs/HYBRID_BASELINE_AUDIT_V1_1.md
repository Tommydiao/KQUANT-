# Hybrid V1.1 M0 Evidence Log

Date: 2026-09-05. Final M0 findings below supersede initial evidence notes.

## Scope and Ownership

This pass is owned by the current integration task. No new parallel writer has
been assigned. Existing uncommitted candidate files and the two user-provided
Hybrid plans are protected inputs, not disposable generated files. Shared source
changes require a separate compatibility review. The authoritative plan is
`KQUANT_Crypto_Hybrid_PLAN_V1.1.md`; V1 is context, not a competing authority.

## Reverified State

- `git rev-parse HEAD`: `baac8d1fe3156be39f7b725d0ed9a20e68c2431f`.
- `git status --short`: four tracked modifications (Crypto dashboard, gateway,
  strategy manifest, unified App) plus untracked candidate implementation,
  configuration, tests, UI panel and documentation. None was reverted or staged.
- Process inspection confirms original collector PIDs 40088 and 36116, created
  2026-09-05 00:14:46 local; candidate PID 31772, created 14:44:33 local.
  Presence is not proof of healthy ingestion or writer-lease ownership.
- No process was stopped, restarted or signaled in this Hybrid audit pass.
- Repository `rg --files -g AGENTS.md` returned no rules file. Parent-directory
  rules still require explicit verification.

## Actual Regression Execution

Working directory: `C:\Users\Administrator\Desktop\KQUANT-\crypto`.

```powershell
python -m pytest -q tests/test_strategy_dual_mode_v1.py tests/test_candidate_portfolio.py tests/test_candidate_forward.py tests/test_candidate_store_metrics.py tests/test_candidate_dataset.py tests/test_candidate_api.py
```

Actual output: `196 passed in 16.98s`. Exit code: 0.
This is the existing candidate-related suite, not a Hybrid suite, full Crypto
regression, golden historical replay or evidence of profitability. Prior claims
of 491 passing tests have not been re-established by this narrower run.

## Baseline References Inspected

- `config/dual_regime_candidate_v1.json`: original three symbols, 10,000 cash,
  0.25% trade risk, 0.50% open risk, two positions, 25% symbol notional,
  1% daily loss, three-loss/two-hour pause, fees 10bps, historical execution
  proxy 5bps and quote-only extra slippage 2bps. No parameter changed.
- `outputs/dual_regime_v1/candidate_selection.json`: A references
  `dev_A_base_v4`, B references `dev_B_base_v4`; both failed, A retained only
  as the engineering default. `holdout_opened=false`.
- A recorded payoff 0.6186031223, PF 0.5744171850, mean R -0.1586444862.
  These are inspected saved results, not freshly reproduced performance.
- `DUAL_REGIME_DATA_AUDIT.md` records exposed history and current-rule proxies.
  Its prior file-hash and database claims still need fresh verification.
- Source inspection finds no `portfolio_version` contract in the candidate
  portfolio. Existing `_reserve`, `_enter`, `on_quote`, `on_closed_batch` are
  not proof of the new three-identity or final commit version requirements.

## Source Findings

The original dual-regime V2 document specifies trend 72 five-minute bars / six
hours and range 36 bars / three hours. It defines payoff using net money, maximum
drawdown on five-minute liquidation-aware equity, historical BASE 10/5bps and
stress 20/10bps. Forward uses actual bid/ask plus 2bps extra execution loss.

Its line 237 references the original 10R drawdown criterion but does not define
the denominator or aggregation. The saved run reports a cumulative trade-R
drawdown PASS. Equivalence to the original criterion is NOT established; this
audit does not rewrite the saved run and does not adopt that PASS for Hybrid.

## Initial Next Evidence Required (Historical Work Log)

Complete all docs, parent rules, module/source hashes, live lease inspection,
exact baseline source/run consistency, immutable golden trace, and the original
10R source search. Then deliver M1 contracts and isolated synthetic tests.
Mathematical filtering, model training and live admission remain disabled.

## Completed Read-Only Reverification

All pre-existing Markdown documents under crypto/docs, including daily reports,
were read; their hashes are listed in the M0 inventory. Historical weekly reports
are context, not evidence of today's schema, runtime or Gate. In particular the
old architecture's no-execution-route description predates the gated execution
code. All explicit parent AGENTS paths were absent. Current integration task is
the sole owner of new hybrid_* files; old untracked/shared files are protected.

Read-only candidate DB metadata verifies A/B v4 completed; forward_A_frozen_v1 is
running with unexpired lease at inspection. No original writer token was acquired.
Final process check again observed collector40088/36116, forward31772 and web
3060/29592 with unchanged creation times. Existence is not an ingestion-quality
or 24-hour-continuity certificate.

New development-only replay in m0_golden_20260905_04 returned exit0/PASS. A:220,213
events,27 trades,73,441 equity rows; B:220,977 events,185 trades,73,441 equity rows.
Every record matches the original persisted trace after reproducing only save()'s
run_id envelope and equity timestamp float conversion. Prices, quantities, fees,
decision reasons, net R and cash are compared exactly without rounding tolerance.
All saved module source hashes still match. Old A/B metadata lacks CLI hash;
that provenance gap remains, despite current core trace reproduction.

Verifier attempts01 (missing rules location),02/03 (unapplied serialization
envelope) were failures and retained. Attempt04 corrected only the audit tool.
No original strategy or result was repaired, overwritten or selected again.

Six frozen file byte hashes and canonical manifest42b913ec...651a were verified.
DuckDB filters authorized development dates before fetching market rows. Only
warmup and development data through1776038400 (2026-04-13 UTC) were materialized
by the new verifier. Full-file integrity hashing does cover sealed file bytes.

The old loader first materializes the full frozen dataset, then replay restricts
decision dates. Thus holdout_opened=false is not proof that later rows were never
loaded. Existing data audit already marks history exposed. No unseen OOS claimed.

## Original 10R Source and Incompatibility

`backtest.py:211`: risk = cost-adjusted next-open entry_price - stop_price.
Its summarize_outcomes accumulates realized R in caller order, then peak/trough.
`validation.py:304,369` builds outcomes in sorted asset order; it is not a
chronological three-symbol portfolio trace. Its default maximum_drawdown_r is10.

The dual candidate instead fixes signal-time BASE expected net loss per unit,
uses filled quantity for actual R, and sorts completed trades by exit_time/trade_id
in candidate_metrics._basic. Five-minute liquidation-equity drawdown is separate.
Therefore the original implementation is located, but metric transfer is not
equivalent. Do not change either denominator/order or claim full Hybrid PASS.
B-10R requires an explicit metric-contract clarification before full admission.

## Reuse Findings

Existing bayesian_model uses versioned fixed likelihoods (source lines151,193),
not fitted hierarchical net-R inference. Existing MonteCarloConfig uses5/20/60
days and single-series blocks, not six-hour synchronized three-asset current-risk
paths. Reuse PIT/hash/math utilities after tests, not old forecast output as Hybrid
evidence. Existing model_registry/model_baselines/quantile_model offer artifact
and NumPy baseline primitives, not validated Hybrid models. llm_advisor's save
path invokes the original migration/store; it must not be reused for Hybrid writes.

## Environment Resolution Finding

The final inventory's script-context find_spec resolves an older editable install
at Desktop/KQUANT-CRYPTO/kquant_crypto. An actual `python -c` import from crypto
cwd resolves this repository's __init__, hybrid_transaction_contract and
candidate_simulation; pytest configuration explicitly sets pythonpath=["."].
Both candidate CLI and golden verifier prepend their resolved repository ROOT.
Thus the executed regression/replay path is verified, but a generic new script or
installed console entry may select the wrong checkout. This is B-ENV, not a reason
to mutate the live environment. Final delivery inventory records both origins.
