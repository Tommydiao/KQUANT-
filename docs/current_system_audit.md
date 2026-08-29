# KQUANT Current System Audit

Audit date: 2026-07-23 (Asia/Shanghai)

## Audit scope

This is the Day 1 baseline audit for the 84-day KQUANT plan. It describes the
checked local working branch and does not change strategy parameters, market
data behavior, or user-facing trade conclusions.

## Baseline identified

- Local repository: `C:\Users\Administrator\Desktop\KQUANT-`
- Active branch: `codex/runtime-validation-v3`
- Local HEAD: `680e184 Add strategy validation v3 and CI`
- Local branch relationship: three commits ahead of the locally configured
  `origin/main` reference (`8bcd01b`)
- Local worktree status at audit: clean
- Public GitHub default branch observed during this audit: older stock terminal
  code; it does not yet reflect the three local runtime-validation commits.

The remote/local divergence is a release-management risk. Do not discard the
local branch or claim that `main` contains its work until the branch is pushed,
reviewed, and merged through an explicit release step.

## Current product boundary

KQUANT is currently a local, single-user US-stock research terminal.

- Long-only research workflow; no broker trade context is created.
- FastAPI is served from `kquant.dashboard` and exposes stock research,
  journal, AI-review, data-health, and strategy-validation APIs.
- `scripts/verify_read_only_boundary.py` and the dashboard route audit reject
  account, broker, order, position, options, Binance, BTC, and ETH routes.
- The UI accepts only `source=live`; fixture data is retained for tests rather
  than exposed to the user-facing terminal.
- AI can rank, explain, and propose a manual review plan. It must not change
  raw market data, bypass hard vetoes, or submit a trade.

This aligns with the 84-day plan's pre-real-money boundary. Automated orders,
broker account reads, options, crypto trading, and unrelated UI expansion
remain out of scope.

## Implemented architecture

| Area | Current implementation | Audit finding |
| --- | --- | --- |
| Runtime | `kquant.dashboard` FastAPI plus static Vite/React bundle | Stock-only runtime is present. |
| Market data | Persistent read-only Longbridge `QuoteContext`; Yahoo fallback/reference path | Correct direction, but live readiness depends on local credentials and permission checks. |
| Realtime | BBO/depth support, 1m forming candle, derived 5m bar, UTC timestamps, XNYS calendar fallback | Implemented and tested with mocks; needs credentialed smoke evidence. |
| Persistence | SQLite/WAL in `work/kquant_us.sqlite3`; candles, signals, labels, journal, provider events, validation tables | Existing schema lacks a first-class strategy-version registry and a formal candle dataset contract. |
| Signal layer | `kquant.stock_signals` contains profiles, rule features, hard vetoes, AI packets, journal, and reporting | Functional but concentrated in a large module; strategy specification needs to be frozen before changing it. |
| Validation | Deterministic historical policy replay plus prospective AI-action outcomes are stored separately | Strong v3 foundation; evidence has not yet been shown from a complete Longbridge historical dataset. |
| Safety | Route safety report, read-only boundary scan, credential masking/self-check | No execution routes in the active dashboard. Continue scanning after every release. |
| CI | Windows GitHub Actions workflow exists locally | Its current remote status cannot validate the stale default branch. |

## Data and time contract observed

- Backend market timestamps are UTC ISO values.
- The exchange timezone is `America/New_York`; the UI supports China and New
  York presentation.
- Forming candles may render, but must not confirm rules, AI actions, or
  backtests.
- Yahoo is permissible only as clearly marked display/reference fallback. A
  Yahoo fallback, stale quote, or non-regular session is a hard veto for a
  buy-class action.

The implementation needs a dedicated written data contract that specifies
source precedence, OHLCV adjustment, unique candle identity, fetch metadata,
and how data-quality failures propagate to strategy eligibility.

## Strategy state

The code currently exposes `swing_long_v1` as the dashboard default and also
contains `tactical_1w_v1` and `high_beta_growth_v1` for validation. These names,
their rule inputs, and their validation policy version are not yet governed by
a single version registry.

Before changing scores, thresholds, stops, targets, regime filters, universe
rules, or entry confirmation, KQUANT needs:

1. a written `swing_long_v1` specification;
2. a versioned strategy record and immutable configuration hash; and
3. a clear binding from signal, journal, validation run, and report to that
   version.

## Verification baseline

- The prior local branch history reports a green suite, but it was not treated
  as current evidence in this audit.
- On 2026-07-23, `.venv-win\Scripts\python.exe` failed because it references
  the old computer's Python installation.
- A new `.venv` was created from the bundled Python, but installation of
  `.[dev]` timed out while downloading dependencies. The bundled runtime does
  not include `pytest`.
- Therefore **no fresh Python test result is claimed by this audit**. Restore
  the environment before accepting new functional changes.

## Priority gaps

1. Restore a reproducible local Python/Node verification environment.
2. Publish or otherwise reconcile the local runtime-validation branch with the
   intended GitHub release branch.
3. Add the MVP boundary, strategy specification, and market-data contract.
4. Add a strategy version registry before modifying any strategy logic.
5. Establish a unified candle-store contract and daily data-quality reporting
   before treating historical validation as execution evidence.

## Next approved implementation boundary

The next planned work creates only governance and documentation artifacts:
`docs/personal_live_mvp.md`, `docs/strategy_specification.md`, and
`docs/market_data_contract.md`. It will not widen product scope or add a broker,
order, account, options, or crypto path.
