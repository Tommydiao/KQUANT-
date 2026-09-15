"""Outcome-blind calendar/state start selection for exposed MC research."""
from datetime import datetime, timezone
import math


def select_starts(rows):
    selected, rejected, used = [], [], set()
    last = None
    for row in rows:
        t = row['as_of']
        if last is not None and t <= last:
            raise ValueError('Strict chronological unique snapshots required')
        last = t
        if t % 3600:
            raise ValueError('Closed UTC hour required')
        if row['regime'] not in ('UP_TREND', 'RANGE', 'TRANSITION'):
            raise ValueError('Unknown regime')
        if any(not math.isfinite(row[k]) or row[k] <= 0 for k in ('nav', 'historical_peak')):
            raise ValueError('Positive finite NAV and historical peak required')
        if row['historical_peak'] < row['nav']:
            raise ValueError('Historical peak must include current NAV')
        if row['history_end'] > t:
            raise ValueError('Future history forbidden')
        if not row['original_positions'] and not row['original_pending']:
            continue
        key = (datetime.fromtimestamp(t, timezone.utc).strftime('%Y-%m'), row['regime'])
        if key in used:
            continue
        if row['history_bars'] != 2017 or row['history_end'] != t or not row['history_contiguous']:
            rejected.append({'as_of': t, 'reason': 'INCOMPLETE_PAST_HISTORY'})
            continue
        # Freeze selection before testing path distribution sufficiency or outcomes.
        used.add(key)
        selected.append(dict(row, selection_key=list(key)))
    return {'selected': selected, 'rejected': rejected, 'selection_uses_outcomes': False}
