"""Calendar-backed observation slots, not scheduled execution or future results."""
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]/'workspace'
sys.path.insert(0, str(BASE))
from kquant.market_clock import is_trading_day, session_bounds_utc


def build(constraint):
    denominator_raw = (HERE/'denominator.json').read_bytes()
    denominator = json.loads(denominator_raw)
    registered = len(denominator['items'])
    applicable = sum(row['identity_status'] == 'verified' for row in denominator['items'])
    start = datetime.fromisoformat(constraint['t0_utc'].replace('Z', '+00:00'))
    end = datetime.fromisoformat(constraint['deadline_utc'].replace('Z', '+00:00'))
    day, windows = start.date(), []
    while day <= end.date():
        if is_trading_day(day):
            opening, closing = session_bounds_utc(day)
            if start < opening < end:
                points = []
                for minutes in (5, 10, 15, 20, 25):
                    checkpoint = opening+timedelta(minutes=minutes)
                    earliest_label = checkpoint+timedelta(seconds=60, minutes=60)
                    points.append(dict(checkpoint=checkpoint.isoformat(),
                        original_deadline=min(checkpoint+timedelta(seconds=300), opening+timedelta(minutes=30)).isoformat(),
                        earliest_primary_label_maturity=earliest_label.isoformat(),
                        primary_label_could_mature_before_delivery=earliest_label <= end,
                        actual_post_commit_at=None, actual_primary_label_maturity=None,
                        complete_s0=None, complete_s1=None, technical_events=None,
                        specific_reference_contracts=None, browser_deliveries=None))
                windows.append(dict(session=day.isoformat(), opening=opening.isoformat(), closing=closing.isoformat(),
                    prewarm=(opening-timedelta(minutes=60)).isoformat(),
                    preopen_verdict=(opening-timedelta(minutes=5)).isoformat(),
                    entry_cutoff=(opening+timedelta(minutes=30)).isoformat(),
                    registered_objects=registered, predetermined_applicable_objects=applicable,
                    registered_direction_positions=registered*10, applicable_direction_positions_per_variant=applicable*10,
                    checkpoints=points, actual_runtime_window=None, status='FUTURE_NOT_RUN',
                    all_primary_labels_could_mature_before_delivery=all(
                        p['primary_label_could_mature_before_delivery'] for p in points)))
        day += timedelta(days=1)
    return dict(schema='KQUANT_FIXED_DEADLINE_WINDOW_LEDGER_V1',
        t0_utc=constraint['t0_utc'], deadline_utc=constraint['deadline_utc'], deadline_reset=False,
        calendar='EXISTING_PROJECT_MARKET_CLOCK', synthetic_market_results=False,
        denominator_source=dict(path=str(HERE/'denominator.json'), sha256=sha256(denominator_raw).hexdigest(),
            scope_hash=denominator['scope_hash']),
        actual_future_counts=None, new_background_scheduler_installed=False,
        primary_reaction_seconds=60, primary_path_minutes=60,
        maturity_semantics='LOWER_BOUND_FROM_NOMINAL_CHECKPOINT; ACTUAL_POST_COMMIT_TIME_CAN_ONLY_BE_LATER',
        preferred_complete_observation_sessions=[w['session'] for w in windows
            if w['all_primary_labels_could_mature_before_delivery']][:3], windows=windows)


if __name__ == '__main__':
    constraint = json.loads((HERE/'constraint.json').read_text(encoding='utf-8'))
    output = HERE/'next-complete-windows-fixed-deadline-v2.json'
    result = build(constraint)
    result['constraint_sha256'] = sha256((HERE/'constraint.json').read_bytes()).hexdigest()
    result['calendar_source_sha256'] = sha256((BASE/'kquant/market_clock.py').read_bytes()).hexdigest()
    result['recorder_sha256'] = sha256(Path(__file__).read_bytes()).hexdigest()
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=True, indent=2)
    print(json.dumps(dict(path=str(output), preferred=result['preferred_complete_observation_sessions'],
        incomplete_by_delivery=[w['session'] for w in result['windows']
            if not w['all_primary_labels_could_mature_before_delivery']], actual_results=None)))
