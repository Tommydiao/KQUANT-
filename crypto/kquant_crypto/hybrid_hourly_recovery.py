"""Validate receipt chronology before replaying into an independent journal."""
from dataclasses import asdict
import json
import math

from .hybrid_clock import calibrate, digest
from .hybrid_hourly_receipt import normalize_hourly


def validate_log(rows):
    probes, segment, contract = [], None, None
    current, normalized, intent = None, False, None
    actions, counts = [], dict(messages=0, accepted=0, rejected=0, freezes=0)
    last_mono = None
    terminal = False
    for row in rows:
        if terminal:
            raise ValueError('Records after terminal failure')
        kind = row.get('kind')
        if kind == 'terminal_failure':
            terminal = True
        elif row.get('state') == 'RECEIVED':
            if segment is not None:
                raise ValueError('Clock probes after segment')
            probes.append(row['sample'])
        elif kind == 'clock_segment':
            if segment is not None:
                raise ValueError('Multiple clock segments require separate recovery')
            segment = calibrate(probes)
            if asdict(segment) != row['segment'] or segment.segment_id != row['segment_id']:
                raise ValueError('Clock segment differs from recorded probes')
            last_mono = segment.mono_anchor
        elif kind == 'journal_contract':
            if segment is None or contract is not None or counts['messages']:
                raise ValueError('Journal contract order invalid')
            contract = {k: row[k] for k in ('first_close', 'receipt_basis', 'source')}
            if contract['receipt_basis'] != 'OBSERVED_RECEIPT' or contract['source'] != 'binance_spot_native_utc_kline_1h':
                raise ValueError('Unsupported journal contract')
            if type(contract['first_close']) is not int or contract['first_close'] % 3600:
                raise ValueError('Invalid first close')
        elif kind == 'raw_message':
            if segment is None or row['sequence'] != counts['messages']+1:
                raise ValueError('Raw sequence discontinuity')
            mono, local = row['received_at_monotonic'], row['received_at_local_utc']
            if row['clock_segment_id'] != segment.segment_id or mono < last_mono:
                raise ValueError('Receipt clock order invalid')
            last_mono = mono
            counts['messages'] += 1
            try:
                result = normalize_hourly(json.loads(row['raw']), segment, monotonic_at=mono, local_at=local)
            except (ValueError, TypeError, AttributeError) as exc:
                result = dict(accepted=False, reason='malformed_message', error_type=type(exc).__name__)
            current, normalized, intent = result, False, None
            if result['accepted']:
                if contract is None:
                    raise ValueError('Accepted legacy receipt lacks durable journal contract')
                counts['accepted'] += 1
                event = result['event']
                actions.append(dict(kind='ingest', event=event))
            else:
                counts['rejected'] += 1
        elif kind == 'normalization':
            if current is None or normalized or row['sequence'] != counts['messages'] or row['result'] != current:
                raise ValueError('Recorded normalization mismatch')
            normalized = True
        elif kind == 'freeze_intent':
            if current is None or not current['accepted'] or not normalized or intent is not None:
                raise ValueError('Freeze without qualified normalized receipt')
            event, receipt = current['event'], row['receipt']
            mono, local = receipt['received_at_monotonic'], receipt['received_at_local_utc']
            if (row['sequence'] != counts['messages'] or row['event_id'] != event['event_id']
                or row['event_hash'] != digest(event) or mono < last_mono
                or segment.bounds(mono, local) != receipt
                or type(row['frozen_at']) is not int
                or row['frozen_at'] != math.ceil(receipt['received_at_upper'])):
                raise ValueError('Freeze evidence mismatch')
            last_mono = mono
            intent = row
            counts['freezes'] += 1
            actions.append(dict(kind='freeze', sequence=row['sequence'], frozen_at=row['frozen_at']))
        elif kind == 'journal_commit':
            if (intent is None or row.get('sequence') != counts['messages']
                or row['event_id'] != intent['event_id'] or row['frozen_at'] != intent['frozen_at']):
                raise ValueError('Commit lacks matching durable freeze intent')
            actions.append(dict(kind='verify_commit', recorded=row))
            intent = None
            # A second freeze for this receipt is not a new observation.
            normalized = False
        elif row.get('state') == 'FAILED' and segment is None:
            continue
        else:
            raise ValueError('Unsupported receipt log record')
    return contract, actions, dict(counts, terminal_failure=terminal,
        accepted_without_freeze=counts['accepted']-counts['freezes'])


def replay_actions(journal, actions):
    applied, snapshots, count = None, None, 0
    for action in actions:
        if action['kind'] == 'ingest':
            event = action['event']
            applied = journal.append(event['event_id'], event['payload'])
        elif action['kind'] == 'freeze':
            snapshots = journal.advance('freeze:'+str(action['sequence']), action['frozen_at'])
            count += len(snapshots)
        else:
            recorded = action['recorded']
            if applied != recorded['result'] or len(snapshots) != recorded['snapshot_count']:
                raise ValueError('Recovered result differs from original commit')
    return count
