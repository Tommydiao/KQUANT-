# Risk Controls

kquant keeps the Agent Harness inside a research-first US options boundary. The
MVP can create local tasks, public/fixture market-data reads, reports,
approvals, audit events, and simulated paper records for legacy flows. The only
new broker adapter is Alpaca Paper options, and it is manually triggered outside
the Agent Harness auto-execution path. Live order execution is not implemented.

The US options scanner reads public market data and writes research reports
only; it does not read broker credentials, broker account state, or broker order
endpoints. BTC/ETH remains a legacy sandbox and should not drive new risk
surface area.

## Default Live Boundary

Live trading is blocked by default in three places:

- Existing dashboard readiness keeps Live locked unless the local config, Testnet self-check, Testnet sync, market freshness, kill switch, and budget gates all pass.
- Agent Harness `RiskManager` rejects `live_order` and `paper_to_live_promotion` actions by default.
- The MVP does not register a broker/live order tool for the Agent Harness. Approval can acknowledge a high-risk request, but it does not place an order.
- Alpaca Paper options endpoints require a manual HTTP action, a ready order intent, and a second manual confirmation; LLM/Agent/automation requesters are blocked.

The Harness environment defaults are intentionally conservative:

```bash
LIVE_TRADING_ENABLED=false
REQUIRE_APPROVAL_FOR_LIVE=true
AUDIT_LOG_ENABLED=true
PAPER_TRADING_ENABLED=true
```

## Risk Rules

`RiskManager` persists each evaluation in `risk_checks` and writes audit events. MVP rules include:

- `RULE-001`: Harness live trading remains disabled by default.
- `RULE-002`: Live actions require `LIVE_TRADING_ENABLED=true`, but live execution is still not implemented in this MVP.
- `RULE-003`: High-risk actions require human approval.
- `RULE-004`: Order notional must be below `MAX_ORDER_NOTIONAL`.
- `RULE-005`: Asset exposure must be below `MAX_ASSET_EXPOSURE`.
- `RULE-006`: Daily loss must be below `MAX_DAILY_LOSS`.
- `RULE-007`: Live promotion requires a backtest record.
- `RULE-008`: Live promotion requires a paper record.
- `RULE-009`: Risk checks must be persisted.
- `RULE-010`: High-risk actions require an audit trail.

## Approvals

Approvals can be `pending`, `approved`, `rejected`, or `expired`.

Pending approvals pause a task in `waiting_approval`. Rejection or expiry blocks continuation. Approval only records human acknowledgement and allows the task to leave the waiting state; it does not enable live execution in the MVP.

## Paper Orders And Options

`PaperTradingTool` writes to the local `paper_orders` table and records `order.paper.created`. The payload includes `exchange_call=false` to make the safety contract auditable. It never creates a Binance client and never calls exchange order APIs.

The active `us_options_scan` task does not create a paper order by default and
does not auto-create paper orders. Agent Eval fails if the default Options scan
creates a paper order side effect.

Alpaca Paper options uses separate tables, `options_order_intents` and
`options_paper_orders`, so it does not inherit crypto futures leverage or margin
semantics. V1 allows only single-leg long options:

- `buy_to_open` and `sell_to_close`
- limit order only
- `time_in_force=day`
- max 1 contract/order
- max daily premium `$500`
- max open premium `$1000`

Blocked in v1: short options, spreads, market live orders, live orders, and
LLM/Agent/automation-triggered order intents.

## Extending Tools Safely

New tools must subclass `ToolBase` and declare:

- `permission_level`
- `requires_approval`
- `input_schema()`
- `execute()`

Any tool that can modify external state must be treated as high risk until reviewed. A future live order tool must use `permission_level=write_high_risk`, `requires_approval=true`, and route through `RiskManager` and `ApprovalManager` before any exchange adapter can be called.
