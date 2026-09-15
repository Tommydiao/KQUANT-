"""Descriptive opportunity outcomes, deliberately separate from simulated fills."""
from bisect import bisect_left


def opportunity_label(rows, starts, signal_time, reference, horizon_hours, cutoff):
    if horizon_hours not in (6, 24) or reference <= 0:
        raise ValueError('Registered horizon and positive reference required')
    end = signal_time + horizon_hours * 3600
    common = {'signal_time': signal_time, 'horizon_hours': horizon_hours,
              'evaluation_end': end, 'label_version': 'opportunity_close_reference_v1',
              'fill_status': 'NOT_APPLICABLE', 'counterfactual_trade': False,
              'gross_return': None, 'mfe': None, 'mae': None,
              'label_available_at': None,
              'execution_quality': 'DESCRIPTIVE_BAR_OUTCOME_NOT_TRADE',
              'selection': 'ALL_PROVEN_HOURLY_FEATURE_ROWS'}
    if end > cutoff:
        return dict(common, label_status='CENSORED', reason='AUTHORIZED_HISTORY_END')
    i = bisect_left(starts, signal_time)
    future = rows[i:i+horizon_hours]
    if len(future) != horizon_hours or any(b.start != signal_time+j*3600 for j,b in enumerate(future)):
        return dict(common, label_status='UNAVAILABLE', reason='HISTORY_GAP')
    return dict(common, label_status='MATURE', reason=None, label_available_at=end,
                gross_return=future[-1].close/reference-1,
                mfe=max(0.0,max(b.high for b in future)/reference-1),
                mae=min(0.0,min(b.low for b in future)/reference-1))
