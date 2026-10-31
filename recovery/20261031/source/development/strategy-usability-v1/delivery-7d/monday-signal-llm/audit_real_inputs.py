"""Existing real records only. No SDK, production writes, or historical publication."""
from collections import Counter
from contextlib import closing
from datetime import UTC, datetime, date
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from time import monotonic

from bootstrap import activate
HERE, BASE, ROOT = activate()
from kquant import options_one_minute as common
from kquant import options_intraday_comparison as model
from kquant.market_clock import session_bounds_utc


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def save(name, value):
    target = HERE / 'evidence' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def main():
    replay = HERE.parents[1] / 'evidence/replay-2026-10-15-145659'
    positions = read(replay / 'positions.json')
    applicable = [r for r in positions if r.get('state') != 'IDENTITY_UNRESOLVED']
    primary, multiple = Counter(), Counter()
    for row in applicable:
        state = row.get('s1_state', row.get('state', 'UNKNOWN'))
        reasons = list(dict.fromkeys(row.get('reasons', [])))
        primary[reasons[0] if state == 'INCOMPLETE' and reasons else state] += 1
        if state == 'INCOMPLETE':
            multiple.update(reasons or ['UNEXPLAINED_INCOMPLETE'])
    audit = dict(observed_at=datetime.now(UTC).isoformat(), session='2026-10-15',
        registered_positions=len(positions), applicable_positions=len(applicable),
        identity_excluded=len(positions)-len(applicable), primary_reason_rule='FIRST_RECORDED_REASON_ONLY_FOR_INCOMPLETE',
        exclusive_primary=dict(primary), multiple_incomplete_reasons=dict(multiple),
        original_positions_sha256=sha256((replay/'positions.json').read_bytes()).hexdigest(),
        production_writes=0, sdk_calls=0, retrospective=True)
    save('s1-primary-and-multiple-reasons.json', audit)
    example = next(r for r in read(replay/'page_examples.json') if r['symbol'] == 'BTDR' and r['right'] == 'CALL')
    mapping = read(ROOT/'runtime/config/new-epoch-store-paths.json')
    minute = Path(mapping['stores']['minute'])
    asof = common.timestamp(example['evaluated_at'])
    with closing(sqlite3.connect(minute.as_uri()+'?mode=ro', uri=True, timeout=.2)) as db:
        db.execute('PRAGMA query_only=ON')
        end = monotonic()+3
        db.set_progress_handler(lambda: int(monotonic()>end), 1000)
        raw = db.execute('''SELECT payload_json FROM one_minute_bars WHERE session=? AND symbol=?
            AND received_at<=? ORDER BY received_at LIMIT 5001''',
            (example['session'], example['symbol'], asof.isoformat())).fetchall()
    if len(raw)>5000:
        raise ValueError('REAL_INPUT_VERSION_BOUND_EXCEEDED')
    bars = [json.loads(r[0]) for r in raw]
    opening, closing_at = session_bounds_utc(date.fromisoformat(example['session']))
    args = dict(symbol=example['symbol'], bars=bars, history={}, reference=example['reference_evidence'],
        opening=opening, closing=closing_at, now=asof, checkpoint=common.timestamp(example['calculation_bar_end']),
        scope_hash=example['scope_hash'], source_decisions=[])
    results = model.evaluate_comparison_pair(**args)
    save('real-btdr-input.json', dict(schema='SAVED_REAL_ASOF_INPUT_V1',
        source_role='minute', source_path=str(minute), source_example=str(replay/'page_examples.json'),
        original_evaluation_id=example['research_replay']['source_evaluation_id'],
        saved_at=datetime.now(UTC).isoformat(), historical_instant_signal=False,
        original_asof=asof.isoformat(), arguments={k:v.isoformat() if isinstance(v,datetime) else v for k,v in args.items()},
        raw_payload_sha256=[sha256(r[0].encode()).hexdigest() for r in raw],
        bars_hash=common.digest(bars), original_bars_hash=example['research_replay']['bars_hash']))
    complete = all(r['strategy_comparison']['s1'].get('factor_evidence',{}).get('state')=='FULL_INTRADAY_RESEARCH' for r in results)
    save('real-btdr-s1-result.json', dict(observed_at=datetime.now(UTC).isoformat(),
        real_saved_input=True, complete=complete, results=results, historical_instant_signal=False,
        source_module_sha256=sha256(Path(model.__file__).read_bytes()).hexdigest()))
    print(json.dumps(dict(audit=audit, real_sample_complete=complete,
        s1_states=[r['strategy_comparison']['s1']['state'] for r in results],
        s0_states=[r['state'] for r in results], saved_bar_versions=len(bars))))


if __name__ == '__main__':
    main()
