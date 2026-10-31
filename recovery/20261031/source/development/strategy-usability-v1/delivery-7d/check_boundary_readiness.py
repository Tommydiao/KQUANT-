"""Isolated boundary diagnostic; no SDK, production data, or approval changes."""
from datetime import timedelta
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'tools'))
from bootstrap import activate
activate()
from kquant import options_one_minute as common
from kquant import options_minute_decisions as decisions
from kquant.options_opening_trend_recovery import TrendRecoveryLane
from kquant.options_opening_momentum import load_policy
from test_method_binding import synthetic_inputs

args = synthetic_inputs()
end = args['checkpoint']
requested = end + timedelta(milliseconds=20)
received = end + timedelta(milliseconds=40)
rows = []
for original in args['bars'][2:]:
    row = dict(original, request_started_at=requested.isoformat(), received_at=received.isoformat())
    row['sdk_evidence'] = dict(provider_symbol='TEST_ONLY.US', interface='QuoteContext.candlesticks',
        adjustment='NoAdjust', request_started_at=requested.isoformat(),
        clock_evidence=dict(state='VERIFIED_BOUND', uncertainty_ms=50,
            checked_at=(end-timedelta(seconds=1)).isoformat(), source_hash='TEST_ONLY'))
    rows.append(row)

with TemporaryDirectory(prefix='TEST_ONLY-boundary-', dir=HERE) as directory:
    root = Path(directory)
    lane = TrendRecoveryLane(root / 'minute.sqlite3', lambda *args: None,
        queue_path=root / 'research.sqlite3', clock=lambda: received)
    try:
        bars = {common.timestamp(row['open_at']): row for row in rows}
        last = rows[-1]
        task = lane.task('TEST_ONLY', end-timedelta(minutes=1), bars, load_policy(), 'TEST_ONLY_SCOPE')
        output = dict(test_only=True, no_sdk_calls=True, production_writes=0,
            request_after_close_ms=20, measured_uncertainty_ms=50,
            recovery_reports_ready=lane.bar_ready('TEST_ONLY', end-timedelta(minutes=1), last),
            canonical_method_accepts=decisions._local_candidate(last, {'method':decisions.LOCAL_METHOD}),
            recovery_task_created=task is not None,
            classification='READINESS_BOUNDARY_COMPARISON_NOT_REAL_MARKET_EVIDENCE')
    finally:
        lane.close()
with (HERE/'boundary-readiness-9dc4.json').open('x', encoding='utf-8') as stream:
    json.dump(output, stream, indent=2)
print(json.dumps(output))
