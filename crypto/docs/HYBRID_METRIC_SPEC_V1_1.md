# Hybrid Metric Specification V1.1

Status: partially frozen, original 10R transfer equivalence unresolved. Owner: integration.
Source: original dual-regime V2 sections on costs and acceptance, Hybrid V1.1
sections 6.2 and 10.3. Definitions here do not rewrite immutable baseline reports.

Sample: completed actually executed virtual trade intents, grouped across fills;
counterfactual labels never increase this sample. Report each run, experiment arm,
UTC calendar, symbol and mode separately. Breakeven counts in overall mean/count
but not conditional winner/loser means. Termination liquidations are separately
identified; open marked positions are not completed trades.

| Metric | Definition and unit | Original threshold |
| --- | --- | --- |
| PF_pnl | sum positive net money / abs(sum negative net money), ratio | combination >=1.30; each mode >=1.25 |
| Payoff_pnl | mean positive net money / abs(mean negative net money), ratio | combination >=1.8; each mode >=1.5 |
| Mean_net_R | mean(net money / filled quantity / frozen BASE Lnet), R | >0 |
| PF_R | ratio of summed positive/negative net R | descriptive, not replacement for PF_pnl |
| Payoff_R | conditional mean positive/negative R ratio | descriptive, not replacement for money payoff |
| Portfolio_MDD | maximum 1-V/current-or-prior equity high, five-minute liquidation-aware equity, percentage | <=5% |
| Cumulative_trade_R | sum completed trade net R | not a return percentage |
| Original 10R | old backtest cost-adjusted entry-minus-stop denominator and caller-order cumulative R; not equivalent to dual candidate | BLOCKER; no full performance PASS |

Zero winner or loser denominator produces null and explicit counts/status, not
infinity/999 or automatic PASS. Valuation gaps remain unknown, not interpolated
equity or complete drawdown evidence. HWM includes initial 10,000 baseline cash.
Trade-R peak/trough may be reported under its explicit name; it is not yet proven
identical to the original 10R criterion.

Historical BASE: fee10bps/side and combined adverse execution proxy5bps/side.
Stress: fee20bps, proxy10bps. Forward: actual ask/bid with extra2bps, stress4bps;
observed spread is not doubled. Current exchange rules are historical proxies.
Freeze raw reference prices, fills, quantities and signal BASE Lnet per trade.

Three distinct reports: BASE full portfolio; fixed BASE trades/quantities recosted
at double fee/proxy; complete stress replay including changed cash/sizing/rejections.
Fixed-trade stress PF>=1.05, full stress mean net R>0. Both retain BASE R denominator.
Runtime/LLM/research costs are a separate accounting report, not fabricated fees.

Independence remains unproven on exposed history. Original minimums: 200 independent
completed virtual trades, 50 per mode, 30 for each claimed symbol-mode. Bootstrap
uses synchronized UTC seven-day blocks, 2,000 draws, seed20260905; insufficient
calendar/sample evidence cannot be cured by more resampling. Remove best symbol
and largest winner as separately reported sensitivity checks.

No Hybrid statistical results have been generated in M1. Mathematical simulated
paths, source-code tests and counterfactual labels are not new market trades.
