"""Posthoc virtual capital/time attribution; not executable risk estimates."""
import math


def exposure_audit(trades, equity, start, end, symbols):
    if end<=start:raise ValueError('Positive audit window required')
    selected=[r for r in equity if start<=r['time']<=end]
    if any(b['time']<=a['time'] for a,b in zip(selected,selected[1:])):
        raise ValueError('Duplicate or unordered equity records require explicit audit')
    if not selected or selected[0]['time']!=start or selected[-1]['time']!=end:
        raise ValueError('Complete audit boundary marks required')
    seconds=0;weighted=0.;gaps=[]
    for a,b in zip(selected,selected[1:]):
        dt=b['time']-a['time']
        if dt!=300 or a.get('equity') is None or a.get('valuation_status','available')!='available':
            gaps.append([a['time'],b['time']]);continue
        nav,cash=a['equity'],a['cash']
        if not all(math.isfinite(v) for v in (nav,cash)) or nav<=0 or cash<0 or cash>nav+1e-7:
            raise ValueError('Invalid cash/NAV mark')
        seconds+=dt;weighted+=max(0,nav-cash)/nav*dt
    by_symbol={s:dict(trades=0,net_pnl=0.,gross_positive_net_pnl=0.,holding_seconds=0) for s in symbols}
    intervals=[];dates=set();ids=set()
    for t in trades:
        if t['trade_id'] in ids:raise ValueError('Duplicate virtual trade')
        ids.add(t['trade_id'])
        if not start<=t['entry_time']<=t['exit_time']<=end:raise ValueError('Trade outside window')
        if not math.isfinite(t['net_pnl']):raise ValueError('Unknown PnL')
        stats=by_symbol[t['symbol']];stats['trades']+=1;stats['net_pnl']+=t['net_pnl']
        stats['gross_positive_net_pnl']+=max(t['net_pnl'],0)
        stats['holding_seconds']+=t['exit_time']-t['entry_time']
        intervals.append((t['entry_time'],t['exit_time']))
        if t['exit_time']>t['entry_time']:
            dates.update(range(t['entry_time']//86400,(t['exit_time']-1)//86400+1))
    merged=[]
    for begin,finish in sorted(intervals):
        if not merged or begin>merged[-1][1]:merged.append([begin,finish])
        else:merged[-1][1]=max(merged[-1][1],finish)
    net=sum(t['net_pnl'] for t in trades)
    gross_positive=sum(max(t['net_pnl'],0) for t in trades)
    active=[s for s in symbols if by_symbol[s]['trades']]
    best=max(active,key=lambda s:by_symbol[s]['net_pnl']) if active else None
    return dict(trades=len(trades),calendar_days=(end-start)/86400,
        active_holding_days=len(dates),any_position_seconds=sum(b-a for a,b in merged),
        summed_position_seconds=sum(b-a for a,b in intervals),
        any_position_time_fraction=sum(b-a for a,b in merged)/(end-start),
        time_weighted_costed_position_value_fraction=weighted/seconds if seconds else None,
        valuation_covered_seconds=seconds,valuation_gaps=gaps,by_symbol=by_symbol,
        net_pnl=net,net_pnl_excluding_best_net_asset=net-by_symbol[best]['net_pnl'] if best else None,
        best_net_asset=best,max_single_trade_gross_profit_share=max((max(t['net_pnl'],0) for t in trades),default=0)/gross_positive if gross_positive else None,
        missing_traded_symbols=[s for s in symbols if s not in active],
        gross_profit_shares_by_symbol={s:v['gross_positive_net_pnl']/gross_positive if gross_positive else None for s,v in by_symbol.items()},
        limitation='Trade times and marked exposure are OHLC proxies. Marked value excludes pending reservations and is not order-book liquidity or gross notional. Positive-profit shares are not shares of negative total net PnL.')
