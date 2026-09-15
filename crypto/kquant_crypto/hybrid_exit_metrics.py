"""Descriptive paired exit metrics; no independent trade or portfolio claims."""


def summarize(rows):
    valid=[r for r in rows if r['net_r'] is not None]
    gains=[r['net_r'] for r in valid if r['net_r']>0]
    losses=[-r['net_r'] for r in valid if r['net_r']<0]
    stress=[r['fixed_path_stress_net_r'] for r in valid]
    overlap=sum(max(a['entry_time'],b['entry_time']) < min(a['exit_time'],b['exit_time'])
                for i,a in enumerate(valid) for b in valid[i+1:])
    return {'observations':len(rows),'resolved':len(valid),'unavailable':len(rows)-len(valid),
        'mean_net_r':sum(r['net_r'] for r in valid)/len(valid) if valid else None,
        'profit_factor':sum(gains)/sum(losses) if losses else None,
        'payoff':(sum(gains)/len(gains))/(sum(losses)/len(losses)) if gains and losses else None,
        'same_path_stress_mean_r':sum(stress)/len(stress) if stress else None,
        'same_path_stress_pf':sum(max(0,r) for r in stress)/sum(max(0,-r) for r in stress)
            if any(r<0 for r in stress) else None,
        'max_holding_hours':max((r['exit_time']-r['entry_time'])/3600 for r in valid) if valid else None,
        'overlapping_pairs':overlap,
        'portfolio_risk_validated':False,'independent_oos':False,
        'performance':'PERFORMANCE_UNPROVEN'}
