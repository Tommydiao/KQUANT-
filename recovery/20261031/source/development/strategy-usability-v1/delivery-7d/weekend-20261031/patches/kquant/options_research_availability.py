"""Post-commit observation and original durable admission, never inferred latency."""
from contextlib import closing
import json
from . import options_one_minute as common
from .options_data_paths import connect_store

KIND = 'S0_S1_POST_COMMIT_AVAILABILITY_V1'
TIMELINESS_POLICY = 'ORIGINAL_DURABLE_ENQUEUE_30S_V1'


def timeliness(row, observed_at):
    origin = row.get('original_enqueued_at')
    try:
        elapsed = (common.timestamp(observed_at) - common.timestamp(origin)).total_seconds()
        state = 'TIMELY' if 0 <= elapsed <= 30 else ('LATE' if elapsed > 30 else 'UNKNOWN')
    except (AttributeError, TypeError, ValueError):
        elapsed, state = None, 'UNKNOWN'
    return dict(policy=TIMELINESS_POLICY, original_enqueued_at=origin,
        observed_after_commit_at=observed_at, enqueue_to_observed_commit_seconds=elapsed,
        state=state, current_opportunity_allowed=state == 'TIMELY')


def record_many(path, rows, *, observed_at):
    stamp = common.timestamp(observed_at).isoformat()
    entries = []
    for row in rows:
        if not row.get('strategy_comparison'):
            continue
        s1 = row['strategy_comparison']['s1']
        payload = dict(kind=KIND, evaluation_id=row['evaluation_id'], observed_at=stamp,
            semantics='FIRST_OBSERVED_AFTER_RESULT_COMMIT_NOT_BROWSER_DELIVERY',
            s1_evaluation_id=s1['evaluation_id'],
            input_fingerprint=row.get('runtime_inputs', {}).get('input_fingerprint'))
        if row.get('timeliness_policy') == TIMELINESS_POLICY:
            payload['timeliness'] = timeliness(row, stamp)
        entries.append((common.digest([KIND, row['evaluation_id']]), row['session'], row['symbol'],
            'RESEARCH_AVAILABILITY', stamp, s1.get('deadline_at') or stamp,
            'COMPLETED', common.canonical(payload)))
    if len(entries) > 222:
        raise ValueError('AVAILABILITY_BATCH_BOUND_EXCEEDED')
    if not entries:
        return
    with closing(connect_store(path, timeout=.05)) as db, db:
        # A crash here leaves UNKNOWN, never an invented earlier availability.
        db.executemany('''INSERT OR IGNORE INTO two_hour_jobs
            VALUES (?,?,?,?,?,?,?,NULL,NULL,0,NULL,NULL,?)''', entries)


def attach(db, rows):
    if not rows:
        return
    for row in rows:
        if row.get('timeliness_policy') == TIMELINESS_POLICY:
            row['research_timeliness'] = dict(policy=TIMELINESS_POLICY, state='UNKNOWN',
                original_enqueued_at=row.get('original_enqueued_at'), current_opportunity_allowed=False)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='two_hour_jobs'").fetchone():
        return
    ids = [common.digest([KIND, row.get('parent_evaluation_id') or row['evaluation_id']]) for row in rows]
    raw = db.execute('SELECT payload_json FROM two_hour_jobs WHERE job_id IN (' + ','.join('?' * len(ids)) + ')', ids)
    observations = {value['evaluation_id']: value for (data,) in raw for value in [json.loads(data)]}
    for row in rows:
        observation = observations.get(row.get('parent_evaluation_id') or row['evaluation_id'])
        if not observation:
            continue
        row['research_ready_at'] = observation['observed_at']
        if observation.get('timeliness'):
            row['research_timeliness'] = observation['timeliness']
        if row.get('strategy_comparison'):
            row['strategy_comparison']['availability'] = observation
            if observation.get('timeliness'):
                row['strategy_comparison']['s1']['research_timeliness'] = observation['timeliness']


def current_allowed(row):
    return (row.get('timeliness_policy') != TIMELINESS_POLICY or
        row.get('research_timeliness', {}).get('current_opportunity_allowed') is True)
