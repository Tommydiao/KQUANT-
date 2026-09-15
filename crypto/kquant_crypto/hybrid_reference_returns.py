"""Fixed-horizon price contrast, separate from stop/target policy labels."""


def six_hour_return(start, bars, cutoff):
    end=start+21600
    if end>cutoff:return dict(status='CENSORED',reason='HORIZON_BEYOND_AUTHORIZED_DATA',gross_return=None,net_return=None)
    selected=[b for b in bars if start<=b.start<end]
    if [b.start for b in selected]!=list(range(start,end,300)):
        return dict(status='UNAVAILABLE',reason='HORIZON_GAP',gross_return=None,net_return=None)
    opening,closing=selected[0].open,selected[-1].close
    if opening<=0 or closing<=0:raise ValueError('Positive reference prices required')
    return dict(status='MATURE',reason=None,entry_time=start,label_available_at=end,
        entry_reference=opening,exit_reference=closing,gross_return=closing/opening-1,
        net_return=(closing*.9995*.999)/(opening*1.0005*1.001)-1,
        execution_policy='FIXED_6H_LEGACY_PROXY_10_5',stops_applied=False,
        trading_outcome=False,training_enabled=False)
