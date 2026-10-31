"""First observed post-commit availability, never inferred from calculation time."""
from contextlib import closing
import json
from . import options_one_minute as common
from .options_data_paths import connect_store

KIND = 'S0_S1_POST_COMMIT_AVAILABILITY_V1'


def record_many(path, rows, *, observed_at):
    stamp = common.timestamp(observed_at).isoformat()
    entries = []
    for row in rows:
        if not row.get('strategy_comparison'):
            continue
        if row['state'] != 'NUMERIC_PASS' and row['strategy_comparison']['s1']['state'] != 'NUMERIC_PASS':
            continue
        payload = dict(kind=KIND, evaluation_id=row['evaluation_id'], observed_at=stamp,
            semantics='FIRST_OBSERVED_AFTER_RESULT_COMMIT_NOT_BROWSER_DELIVERY',
            s1_evaluation_id=row['strategy_comparison']['s1']['evaluation_id'],
            input_fingerprint=row.get('runtime_inputs', {}).get('input_fingerprint'))
        entries.append((common.digest([KIND, row['evaluation_id']]), row['session'], row['symbol'],
            'RESEARCH_AVAILABILITY', stamp, row['strategy_comparison']['s1'].get('deadline_at', stamp),
            'COMPLETED', common.canonical(payload)))
    if len(entries) > 222:
        raise ValueError('AVAILABILITY_BATCH_BOUND_EXCEEDED')
    if not entries:
        return
    with closing(connect_store(path, timeout=.05)) as db, db:
        # Original judgments remain immutable. A crash in this second transaction
        # leaves an explicit missing observation, not a guessed earlier timestamp.
        db.executemany('''INSERT OR IGNORE INTO two_hour_jobs
            VALUES (?,?,?,?,?,?,?,NULL,NULL,0,NULL,NULL,?)''', entries)


def attach(db, rows):
    comparisons = [row for row in rows if row.get('strategy_comparison')]
    if not comparisons or not db.execute("SELECT 1 FROM sqlite_master WHERE name='two_hour_jobs'").fetchone():
        return
    ids = [common.digest([KIND, row['evaluation_id']]) for row in comparisons]
    raw = db.execute('SELECT payload_json FROM two_hour_jobs WHERE job_id IN (' + ','.join('?' * len(ids)) + ')', ids)
    observations = {value['evaluation_id']: value for (data,) in raw for value in [json.loads(data)]}
    for row in comparisons:
        observation = observations.get(row['evaluation_id'])
        if observation:
            row['research_ready_at'] = observation['observed_at']
            row['strategy_comparison']['availability'] = observation
