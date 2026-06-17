# KQUANT Roadmap: US Stock First, Options Second

## Product Direction

KQUANT is now a US stock signal terminal first. The near-term goal is to help a
human trader review long-only stock opportunities with clean data, readable
charts, and explainable rule-based signals.

Options return later as a secondary expression tool: only a stock with a strong
`BUY SETUP` should trigger an ATM option review.

## Phase 0: Architecture Reset

Target: 1-2 days.

- Move the product wording to `KQUANT US Stock Signal Terminal`.
- Use `work/kquant_us.sqlite3` as the new primary database.
- Keep old runtime data as backup only.
- Keep the new Python namespace under `kquant`.
- Keep live execution and broker wiring out of the main product.

Acceptance:

- Home UI, README, config, and reports describe the US stock terminal.
- New database initializes automatically.
- Main workflow does not depend on options.

## Phase 1: US Stock Data Foundation

Target: 3-5 days.

- Maintain a selected 100-stock universe.
- Store daily and 1h candles.
- Use public Yahoo chart data for prototype live data.
- Track provider health, missing candles, rate limits, and freshness.
- Keep deterministic fixture data for offline demo and tests.

Tables:

- `stock_universe`
- `stock_candles`
- `provider_events`
- `audit_events`

API:

- `GET /api/stocks/universe`
- `GET /api/stocks/candles`
- `GET /api/stocks/provider-health`

## Phase 2: Stock Signal Engine v1

Target: 5-7 days.

Profile: `swing_long_v1`.

Rules:

- long-only;
- `BUY SETUP >= 82`;
- `WATCH >= 65`;
- otherwise `PASS`.

Factors:

- daily trend structure;
- 1h momentum confirmation;
- EMA20 / EMA50 / EMA200 alignment;
- volume expansion;
- ATR risk;
- extension and gap risk.

Outputs:

- `symbol`
- `score`
- `level`
- `trend_summary`
- `trigger_summary`
- `risk_warnings`
- `manual_checklist`
- `data_status`

## Phase 3: Formal React Frontend

Target: 5-7 days.

Primary screens:

- Today's Stock Setups
- Selected Stock Review
- Daily K-Line
- 1H K-Line
- Signal Reasons
- Manual Journal

Keep:

- English / Chinese;
- Light / Dark;
- TradingView-style charts;
- mobile layout;
- fixture mode.

## Phase 4: Backtest and Training Labels

Target: 1-2 weeks.

Do not train an LLM first. Build the dataset first.

Labels:

- `forward_return_3d`
- `forward_return_5d`
- `forward_return_10d`
- `max_drawdown_5d`
- `hit_target_before_stop`
- `close_above_entry_after_5d`

Tables:

- `stock_features`
- `stock_labels`
- `stock_backtest_runs`

Later model candidates:

- Logistic Regression
- Random Forest
- XGBoost / LightGBM

## Phase 5: 10-Trading-Day Live Pilot

Target: 2 weeks.

Every trading day:

- run one 100-stock scan;
- review `BUY SETUP` and selected `WATCH` names;
- record journal status: `reviewed`, `skipped`, or `paper-observed`;
- note provider errors and missing candles;
- record post-market outcome.

No real-money trade and no automated order.

## Phase 6: Options Return

Target: 1-2 weeks after stock signal stability.

Options are only generated from stock `BUY SETUP` names.

First option scope:

- ATM call;
- DTE 7-30;
- spread filter;
- volume/OI filter;
- IV risk warning;
- 3D Buy Lens as final review.

Levels:

- `OPTION CANDIDATE`
- `OPTION WATCH`
- `OPTION PASS`

## Phase 7: AI Review Assistant

Optional after live pilot.

AI may:

- explain signal context;
- ask risk questions;
- summarize journal notes;
- generate review reports.

AI may not:

- set scores;
- decide BUY/WATCH/PASS;
- trigger scans;
- access broker/account/order paths.
