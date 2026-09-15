"""Conditional path summaries, explicitly not market-calibrated probabilities."""
import math


def verify_numeric_summary(rows, reported):
    """Recompute linear quantiles without using the runner's NumPy reducer."""
    if not rows:
        raise ValueError('Empty path population')
    fields=('net_change','max_historical_nav_drawdown','max_incremental_nav_drawdown')
    if any(not math.isfinite(r[k]) for r in rows for k in fields):
        raise ValueError('Nonfinite path value')
    values=sorted(r['net_change'] for r in rows)
    quantiles=[]
    for probability in (.1,.5,.9):
        index=(len(values)-1)*probability
        low=math.floor(index);high=math.ceil(index)
        quantiles.append(values[low]+(values[high]-values[low])*(index-low))
    computed=dict(net_change_quantiles=quantiles,
        max_historical_nav_drawdown=max(r['max_historical_nav_drawdown'] for r in rows),
        max_incremental_nav_drawdown=max(r['max_incremental_nav_drawdown'] for r in rows),
        open_at_horizon_paths=sum(r['open_at_horizon']>0 for r in rows))
    if len(reported['net_change_quantiles'])!=3:
        raise ValueError('Quantile count mismatch')
    pairs=list(zip(quantiles,reported['net_change_quantiles']))
    pairs.extend((computed[k],reported[k]) for k in fields[1:])
    if any(not math.isfinite(b) or not math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-10) for a,b in pairs):
        raise ValueError('Numeric summary mismatch')
    if computed['open_at_horizon_paths']!=reported['open_at_horizon_paths']:
        raise ValueError('Horizon count mismatch')
    return computed


def summarize_path_events(rows, expected_count):
    if len(rows)!=expected_count or expected_count<=0:
        raise ValueError('Complete preregistered path population required')
    counts={'budget_exceeded':0,'protective_stop':0,'open_at_horizon':0}
    for r in rows:
        counts['budget_exceeded']+=int(r['budget_exceeded'])
        counts['protective_stop']+=int(any(r['exit_reasons'].get(k,0)>0
            for k in ('stop','gap_stop','entry_gap_stop')))
        counts['open_at_horizon']+=int(r['open_at_horizon']>0)
    # P(no events | p,n)=(1-p)^n; this is conditional on this generator only.
    zero_upper=-math.expm1(math.log(.05)/expected_count)
    return dict(paths=expected_count,events={k:dict(count=n,fraction=n/expected_count,
        zero_event_upper95_if_iid=zero_upper if n==0 else None) for k,n in counts.items()},
        calibrated_market_probability=False,
        limitation='One-sided zero-count bound assumes conditionally iid simulation paths; excludes generator error, market dependence and posterior uncertainty. Open positions remain horizon-limited valuations, not successful exits.')
