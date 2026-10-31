"""Read-only labels for already recorded first technical events, not new signals."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import UTC, date, datetime
import json
from pathlib import Path
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = ROOT / 'source/development/workspace'
sys.path.insert(0, str(BASE))
from capture_delivery import POLICIES, query, read, save, sha, stamp
from kquant import options_one_minute as common
from kquant.market_clock import is_trading_day, session_bounds_utc
from kquant.options_research_availability import KIND
from kquant.options_research_diagnostics import path_label


def connect(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=.2)
    db.execute('PRAGMA query_only=ON')
    return db


def first_events(rows, applicable):
    selected = {}
    for row in sorted(rows, key=lambda value: (value['evaluated_at'], value['evaluation_id'])):
        if row['symbol'] not in applicable or row['state'] != 'NUMERIC_PASS':
            continue
        point, computed, deadline = (stamp(row[key]) for key in
            ('calculation_bar_end', 'evaluated_at', 'deadline_at'))
        if not point <= computed < deadline:
            continue
        selected.setdefault((row['symbol'], row['right']), row)
    return list(selected.values())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--session', required=True)
    args = parser.parse_args()
    day = date.fromisoformat(args.session)
    if not is_trading_day(day):
        raise ValueError('NOT_A_MARKET_SESSION')
    as_of = datetime.now(UTC)
    opening, closes_at = session_bounds_utc(day)
    denominator = read(HERE / 'denominator.json')
    roles_path = ROOT / 'runtime/config/new-epoch-store-paths.json'
    roles = read(roles_path)['stores']
    protocol = HERE.parent / 'input/plan/research_protocol.json'
    result = dict(session=args.session, as_of=as_of.isoformat(),
        source_grade='REAL_ALREADY_PERSISTED_EVENTS_RETROSPECTIVE_LABELS',
        protocol_sha256=sha(protocol), denominator_sha256=sha(HERE / 'denominator.json'),
        role_map_sha256=sha(roles_path), session_complete=as_of >= closes_at,
        scope_applicable=len(denominator['applicable']), scope_registered=len(denominator['items']),
        new_window_after_t0=opening >= stamp(read(HERE / 'constraint.json')['t0_utc']),
        primary_delay_seconds=60, secondary_delay_seconds=[30, 120], horizon_minutes=60,
        production_writes=0, sdk_requests=0, parameter_search=False,
        holdout=False, qualification_claim=False, events=[], errors=[])
    bars_by_symbol = {}
    with closing(connect(roles['opening_research'])) as research, closing(connect(roles['minute'])) as minutes:
        for variant, policy_hash in POLICIES.items():
            try:
                raw_rows = query(research, '''SELECT payload_json FROM evaluations
                    WHERE policy_hash=? AND session=? AND state='NUMERIC_PASS'
                    ORDER BY evaluated_at,evaluation_id LIMIT 2001''', (policy_hash, args.session))
                if len(raw_rows) > 2000:
                    raise ValueError('TECHNICAL_EVENT_READ_BOUND_EXCEEDED')
                events = first_events([json.loads(row[0]) for row in raw_rows], denominator['applicable'])
                for event in events:
                    symbol = event['symbol']
                    availability_raw = query(research, '''SELECT payload_json FROM two_hour_jobs
                        WHERE session=? AND symbol=? AND slot='RESEARCH_AVAILABILITY' LIMIT 1001''',
                        (args.session, symbol))
                    if len(availability_raw) > 1000:
                        raise ValueError('AVAILABILITY_READ_BOUND_EXCEEDED')
                    observations = [json.loads(row[0]) for row in availability_raw]
                    matches = [row for row in observations if row.get('kind') == KIND
                        and event['evaluation_id'] in (row.get('evaluation_id'), row.get('s1_evaluation_id'))]
                    observed = min(matches, key=lambda row: stamp(row['observed_at'])) if matches else None
                    if symbol not in bars_by_symbol:
                        raw_bars = query(minutes, '''SELECT payload_json FROM one_minute_bars
                            WHERE session=? AND symbol=? ORDER BY received_at LIMIT 10001''', (args.session, symbol))
                        if len(raw_bars) > 10000:
                            raise ValueError('MINUTE_VERSION_READ_BOUND_EXCEEDED')
                        decoded = [json.loads(row[0]) for row in raw_bars]
                        bars_by_symbol[symbol] = [row for row in decoded if stamp(row['received_at']) <= as_of]
                    bars = bars_by_symbol[symbol]
                    labels = {str(delay): (path_label(event, bars, ready_at=observed['observed_at'],
                        as_of=as_of, delay_seconds=delay) if observed else
                        dict(state='READY_COMMIT_TIME_UNAVAILABLE', y60_pct=None, delay_seconds=delay))
                        for delay in (60, 30, 120)}
                    references = query(research, '''SELECT payload_json FROM revisions
                        WHERE evaluation_id=? ORDER BY revision_id LIMIT 1001''', (event['evaluation_id'],))
                    if len(references) > 1000:
                        raise ValueError('REFERENCE_READ_BOUND_EXCEEDED')
                    refs = [json.loads(row[0]) for row in references]
                    refs = [row for row in refs if row.get('reference_contract')
                        and stamp(event['calculation_bar_end']) <= stamp(row['checked_at']) < stamp(event['deadline_at'])]
                    result['events'].append(dict(variant=variant, symbol=symbol, right=event['right'],
                        evaluation_id=event['evaluation_id'], event_sha256=common.digest(event),
                        checkpoint=event['calculation_bar_end'], computed_at=event['evaluated_at'],
                        original_deadline=event['deadline_at'], availability=observed,
                        availability_sha256=common.digest(observed) if observed else None,
                        bars_received_by_asof=len(bars), bars_sha256=common.digest(bars),
                        labels=labels, recorded_reference_count=len(refs),
                        recorded_reference_hashes=[common.digest(row) for row in refs],
                        option_pnl=None, option_pnl_reason='MATCHED_CONTRACT_EXECUTABLE_PATH_NOT_AVAILABLE',
                        browser_delivery_proven=False))
            except (sqlite3.Error, ValueError, KeyError, TypeError) as exc:
                result['errors'].append(dict(variant=variant, type=type(exc).__name__, message=str(exc)[:160]))
    result['counts'] = dict(events_by_variant=dict(Counter(row['variant'] for row in result['events'])),
        primary_label_states=dict(Counter(row['labels']['60']['state'] for row in result['events'])),
        paired_complete_events=None, unseen_validation=False)
    result['conclusion'] = 'DESCRIPTIVE_ONLY_NO_OPTION_RETURN_OR_CAUSAL_STRATEGY_ADVANTAGE'
    output = HERE / ('recorded-labels-' + args.session + '-' + as_of.strftime('%H%M%S') + '.json')
    save(output, result)
    print(json.dumps(dict(evidence=str(output), counts=result['counts'], errors=result['errors'],
        events=[dict(variant=row['variant'], symbol=row['symbol'], right=row['right'],
            checkpoint=row['checkpoint'], ready_at=(row['availability'] or {}).get('observed_at'),
            label_states={key: value['state'] for key, value in row['labels'].items()},
            reference_count=row['recorded_reference_count']) for row in result['events']]), ensure_ascii=True))


if __name__ == '__main__':
    main()
