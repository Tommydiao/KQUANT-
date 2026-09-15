"""Read-only, point-in-time audit of the independent observation ledger."""
from collections import Counter
import json
import math
from pathlib import Path
import sqlite3
import time

from .candidate_policy import digest
from .hybrid_contracts import DecisionTimeline
from .hybrid_quote_contract_v12 import SYMBOLS, describe_quote, covered_seconds


def snapshot_database(source, destination, timeout=20):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists():
        raise ValueError('New independent snapshot destination required')
    started = time.monotonic()
    def progress(status, remaining, total):
        if time.monotonic() - started > timeout:
            raise TimeoutError('Read-only observation snapshot deadline exceeded')
    origin = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=2)
    target = sqlite3.connect(destination)
    try:
        origin.backup(target, pages=128, progress=progress, sleep=.01)
    finally:
        target.close()
        origin.close()


def audit_database(path, *, observation_window=None):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    errors = []
    reasons = Counter()
    modes = Counter()
    counts = Counter()
    intervals = {s: [] for s in SYMBOLS}
    clock_points = []
    labels = {}
    try:
        for identity, hashed, payload, audit in db.execute('SELECT id,hash,payload,audit FROM observer_events'):
            event = json.loads(payload)
            if observation_window is not None and event.get('observation_window_hash') != digest(observation_window):
                errors.append({'id': identity, 'reason': 'OBSERVATION_WINDOW_BINDING_MISMATCH'})
            if digest(event) != hashed:
                errors.append({'id': identity, 'reason': 'EVENT_HASH_MISMATCH'})
            counts[event['type']] += 1
            mono = event.get('received_at_monotonic')
            if type(mono) in (int, float) and math.isfinite(mono):
                clock_points.append(mono)
            for note in json.loads(audit):
                if note.get('reason'):
                    reasons[note['reason']] += 1
                if note.get('kind') == 'CLOSED_BAR_DECISION':
                    modes[(note['symbol'], note['mode'])] += 1
            if event['type'] == 'quote':
                detail = describe_quote(event)
                if detail['eligible_sample'] and mono is not None:
                    expiry = mono + event['source_time'] + 30 - event['received_at_upper']
                    if expiry >= mono:
                        intervals[event['symbol']].append((mono, expiry))
                else:
                    reasons['SEMANTIC_QUOTE_RECHECK_REJECTED'] += 1
            if event['type'] == 'closed_batch' and 'inputs_available_at_upper' in event:
                if event['inputs_available_at_upper'] > event['received_at_lower']:
                    errors.append({'id': identity, 'reason': 'CLOSED_INPUT_AVAILABILITY_NOT_PROVEN'})
        for sid, version, hashed, payload in db.execute(
                'SELECT signal_id,version,hash,payload FROM observer_labels ORDER BY signal_id,version'):
            row = json.loads(payload)
            if digest(row) != hashed:
                errors.append({'id': sid, 'version': version, 'reason': 'LABEL_HASH_MISMATCH'})
            labels[sid] = row
        saved = db.execute('SELECT state FROM observer_checkpoint WHERE id=1').fetchone()
        opportunities = json.loads(saved[0])['opportunities'] if saved else {}
        if set(opportunities) != set(labels):
            errors.append({'reason': 'CHECKPOINT_LABEL_ID_SET_MISMATCH'})
        for sid in set(opportunities) & set(labels):
            if digest(opportunities[sid]) != digest(labels[sid]):
                errors.append({'id': sid, 'reason': 'CHECKPOINT_LATEST_LABEL_MISMATCH'})
        grouped = {}
        for sid, row in labels.items():
            group = (row['symbol'], row['mode'], row['label_execution_policy_id'])
            bucket = grouped.setdefault(group, Counter())
            bucket['opportunities'] += 1
            bucket['fill:' + row['fill_status']] += 1
            bucket['label:' + row['label_status']] += 1
            if row.get('outcome_reason'):
                bucket['outcome:' + row['outcome_reason']] += 1
            if row['fill_status'] == 'UNFILLED' and (row.get('net_r') is not None or
                    row['label_status'] != 'NOT_APPLICABLE_UNFILLED'):
                errors.append({'id': sid, 'reason': 'UNFILLED_RETURN_OR_LABEL_CONFLICT'})
            if row['label_status'] == 'MATURE' and row['fill_status'] != 'FILLED':
                errors.append({'id': sid, 'reason': 'MATURE_WITHOUT_FILL'})
            if row['fill_status'] == 'FILLED':
                quote = row.get('entry_quote')
                try:
                    valid = quote is not None and DecisionTimeline(**row['timeline']).permits_fill(
                        quote['source_time'], quote['received_at'])
                except (KeyError, TypeError, ValueError):
                    valid = False
                if not valid:
                    errors.append({'id': sid, 'reason': 'ENTRY_TIME_CONTRACT_FAILED'})
            if row['label_status'] == 'MATURE':
                trade = row.get('trade', {})
                try:
                    risk = trade['quantity'] * trade['unit_net_risk']
                    valid = risk > 0 and math.isclose(row['net_r'], trade['net_pnl'] / risk, rel_tol=1e-12)
                    valid = valid and row['label_available_at'] >= trade['exit_time']
                except (KeyError, TypeError, ValueError):
                    valid = False
                if not valid:
                    errors.append({'id': sid, 'reason': 'MATURE_R_OR_AVAILABILITY_CONTRACT_FAILED'})
        coverage = None
        planned_coverage = None
        if clock_points and max(clock_points) > min(clock_points):
            start, end = min(clock_points), max(clock_points)
            coverage = {'basis': 'COMMITTED_EVENT_ENVELOPE_NOT_PREREGISTERED_SLO',
                        'start_monotonic': start, 'end_monotonic': end,
                        'per_symbol': {s: covered_seconds(parts, start, end) for s, parts in intervals.items()}}
            if observation_window is not None:
                planned_start = observation_window['start_monotonic']
                planned_end = observation_window['end_monotonic']
                if start < planned_start or end > planned_end + 30:
                    errors.append({'reason': 'EVENT_OUTSIDE_BOUND_OBSERVATION_WINDOW'})
                planned_coverage = {
                    'window': observation_window, 'observed_event_end_monotonic': end,
                    'per_symbol': {s: covered_seconds([(a, min(b, end)) for a, b in parts],
                                                        planned_start, planned_end)
                                   for s, parts in intervals.items()},
                    'duration_completed_not_inferred_from_quote_span': True,
                    'minimum_72h_window': planned_end - planned_start >= 259200,
                    'G3_passed': False}
        return {'integrity_errors': errors, 'ledger_integrity_pass': not errors,
                'event_counts': dict(counts), 'audit_reasons': dict(reasons),
                'mode_decisions': [{'symbol': s, 'mode': m, 'count': n} for (s, m), n in sorted(modes.items())],
                'label_funnel': [{'symbol': s, 'mode': m, 'policy': p, 'counts': dict(c)}
                                 for (s, m, p), c in sorted(grouped.items())],
                'latest_opportunities': len(labels), 'descriptive_quote_coverage': coverage,
                'preregistered_slo_window': planned_coverage, 'G3_passed': False,
                'exchange_fill_evidence': False, 'model_gate_pass': False, 'performance_gate_pass': False,
                'limitations': ['Raw rejected messages are outside the committed ledger counts',
                                ('Window origin unavailable for legacy run' if observation_window is None else
                                 'Bound planned denominator is not proof of full duration or protection availability'),
                                'Snapshot presence does not prove process liveness or protection availability']}
    finally:
        db.close()
