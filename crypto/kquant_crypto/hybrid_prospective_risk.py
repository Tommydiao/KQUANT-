"""Research-only paired pending-plan risk with the original protection engine."""
from collections import Counter
from copy import deepcopy
from .hybrid_mc_portfolio import ExistingExposurePortfolio
from .strategy_dual_mode_v1 import Bar


def closed_hours(as_of, prefix, batches, symbols):
    """Seed an incomplete hour only with bars already available at decision time."""
    hour_start=as_of//3600*3600
    expected=list(range(hour_start,as_of,300))
    if as_of%300 or [r['start'] for r in prefix]!=expected:
        raise ValueError('Incomplete or future first-hour prefix')
    rows={s:[] for s in symbols}
    for item in prefix:
        if set(item['bars'])!=set(symbols):raise ValueError('Cross-symbol prefix gap')
        for s,b in item['bars'].items():
            if b['start']!=item['start'] or not b['start']+300<=b['available_at']<=as_of:
                raise ValueError('Prefix not closed/available at decision')
            rows[s].append(Bar(b['start'],b['open'],b['high'],b['low'],b['close'],0))
    for i,batch in enumerate(batches):
        start=as_of+i*300;now=start+300
        if set(batch)!=set(symbols) or any(b.start!=start for b in batch.values()):
            raise ValueError('Path gap or cross-symbol misalignment')
        for s,b in batch.items():rows[s].append(b)
        hourly={}
        if now%3600==0:
            for s,seq in rows.items():
                if len(seq)!=12 or [b.start for b in seq]!=list(range(now-3600,now,300)):
                    raise ValueError('Generated hour is incomplete')
                hourly[s]=Bar(now-3600,seq[0].open,max(b.high for b in seq),
                    min(b.low for b in seq),seq[-1].close,0)
            rows={s:[] for s in symbols}
        yield batch,hourly,now


def paired_states(state,symbol,signal_time):
    pending=state['pending'].get(symbol)
    if pending is None or pending['signal_time']!=signal_time or symbol in state['positions']:
        raise ValueError('Originally admitted unfilled proposal required')
    if pending['quantity']<=0:raise ValueError('Positive reserved quantity required')
    with_plan=deepcopy(state);without=deepcopy(state)
    # Pending reservations have not debited cash; never refund a fictional fill.
    del without['pending'][symbol]
    return with_plan,without


def simulate_pair(state,context,path,policy,rules,candidate,symbol):
    with_plan,without=paired_states(state,symbol,context['as_of'])
    ports={};initial={};peaks={};maxdd={};risk={};exits={};fills={}
    for name,snap in (('WITH_PLAN',with_plan),('WITHOUT_PLAN',without)):
        port=ExistingExposurePortfolio(policy,rules,exit_candidate=candidate);port.restore(snap)
        ports[name]=port;initial[name]=peaks[name]=port.value();maxdd[name]=0.
        risk[name]=False;exits[name]=Counter();fills[name]=0
    if initial['WITH_PLAN']!=initial['WITHOUT_PLAN']:raise ValueError('Cancellation changed initial NAV')
    for batch,hourly,now in closed_hours(context['as_of'],context['first_hour_prefix'],path['batches'],policy['symbols']):
        for name,port in ports.items():
            port.on_path_batch(batch,hourly,now);drained=port.drain()
            exits[name].update(t['exit_reason'] for t in drained['trades'])
            fills[name]+=sum(e['kind']=='VIRTUAL_ENTRY' and e['symbol']==symbol for e in drained['events'])
            nav=port.value()
            if nav<=0:raise ValueError('Nonpositive NAV')
            peaks[name]=max(peaks[name],nav);maxdd[name]=max(maxdd[name],1-nav/peaks[name])
            booked=sum(v.get('estimated_risk_amount',v['risk_amount']) for v in [*port.positions.values(),*port.pending.values()])
            risk[name]|=booked>nav*policy['max_open_risk']+1e-8
    results={name:dict(net_change=p.value()-initial[name],max_incremental_nav_drawdown=maxdd[name],
        booked_risk_ratio_exceeded=risk[name],open_at_horizon=len(p.positions),pending_at_horizon=len(p.pending),
        exit_reasons=dict(exits[name]),target_plan_fills=fills[name],terminal_mark_only=True) for name,p in ports.items()}
    if fills['WITHOUT_PLAN']!=0 or fills['WITH_PLAN']>1:
        raise ValueError('New or duplicated target-plan entry')
    return dict(results=results,paired_net_change=results['WITH_PLAN']['net_change']-results['WITHOUT_PLAN']['net_change'],
        runtime_enabled=False,calibrated_risk=False)
