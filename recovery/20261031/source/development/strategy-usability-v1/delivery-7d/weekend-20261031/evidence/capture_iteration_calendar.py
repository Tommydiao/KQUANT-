"""Use project calendar only; no registration, source requests, or approvals."""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parents[1]
DELIVERY = HERE.parent
BASE = DELIVERY.parents[1] / 'workspace'
sys.path[:0] = [str(BASE), str(DELIVERY/'opening-first-hour'), str(HERE/'calendar')]
from window_calendar import window


def main():
    denominator = json.loads((DELIVERY/'denominator.json').read_text(encoding='utf-8-sig'))
    days = [window(date(2026, 11, 2)+timedelta(days=n), denominator) for n in range(12)]
    scheduled = [row for row in days if row['checkpoint_count']]
    if len(scheduled) != 10 or any(row['checkpoint_count'] != 11 or row['positions_per_variant'] != 2200 for row in scheduled):
        raise ValueError('ITERATION_CALENDAR_OR_DENOMINATOR_MISMATCH')
    import kquant.market_clock as clock
    import first_hour
    result = dict(schema='NOVEMBER_ITERATION_CALENDAR_V1',
        observed_at=datetime.now(timezone.utc).isoformat(), days=days,
        source_hashes={str(p): sha256(p.read_bytes()).hexdigest() for p in (
            Path(clock.__file__), Path(first_hour.__file__), HERE/'calendar/window_calendar.py',
            DELIVERY/'denominator.json')},
        actual_windows_observed=0, actual_schedule_registered=False,
        production_writes=0, final_evidence_due='2026-11-14T01:00:00+08:00')
    target = HERE/'evidence/iteration-calendar-20261101.json'
    target.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(path=str(target), trading_days=len(scheduled),
        first=scheduled[0]['checkpoints'][0]['at'], last=scheduled[-1]['checkpoints'][-1]['at'],
        prewarm=scheduled[0]['prewarm'], cutoff=scheduled[0]['cutoff'])))


if __name__ == '__main__':
    main()
