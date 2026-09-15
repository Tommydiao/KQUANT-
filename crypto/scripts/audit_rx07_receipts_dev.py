"""Replay an immutable prefix of receiver evidence without touching its writer."""
import argparse
from collections import Counter
from dataclasses import fields
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_clock import ClockSegment, calibrate, digest
from kquant_crypto.hybrid_dual_receipt import normalize_closed, renewal_overlap


def verify(raw, *, require_probes=False):
    if raw and not raw.endswith(b'\n'):
        raise ValueError('Audit requires complete JSONL records')
    segments, pending, identities, batches = {}, {}, {}, {}
    counts = Counter()
    last_sequence = 0
    terminal = False
    probe_group = []
    for line in raw.splitlines():
        row = json.loads(line)
        kind = row.get('kind')
        counts['record:'+str(kind)] += 1
        if row.get('state') == 'RECEIVED' and 'sample' in row:
            if row['sample']['index'] != len(probe_group):
                raise ValueError('probe_group_sequence_mismatch')
            probe_group.append(row['sample'])
        if kind in ('clock_segment', 'clock_renewal'):
            segment = ClockSegment(**{f.name: row['segment'][f.name] for f in fields(ClockSegment)})
            if segment.segment_id != row['segment_id']:
                raise ValueError('clock_segment_hash_mismatch')
            if require_probes:
                rebuilt = calibrate(probe_group)
                if rebuilt != segment:
                    raise ValueError('clock_probe_reconstruction_mismatch')
                counts['probe_calibrations_recomputed'] += 1
                if kind == 'clock_renewal':
                    previous = segments.get(row['previous_segment_id'])
                    if previous is None or not renewal_overlap(previous,segment,
                            monotonic_at=segment.mono_anchor,local_at=segment.local_anchor):
                        raise ValueError('renewal_interval_discontinuity_at_probe_completion')
                    counts['renewal_overlap_recomputed_at_probe_completion'] += 1
            probe_group = []
            segments[segment.segment_id] = segment
        elif kind == 'raw_message':
            seq = row['sequence']
            if seq != last_sequence+1 or pending:
                raise ValueError('raw_sequence_or_unresolved_normalization')
            if row['clock_segment_id'] not in segments:
                raise ValueError('unknown_clock_segment')
            pending[seq] = row
            last_sequence = seq
        elif kind == 'normalization':
            receipt = pending.pop(row['sequence'], None)
            if receipt is None:
                raise ValueError('normalization_without_raw')
            try:
                result = normalize_closed(json.loads(receipt['raw']), segments[receipt['clock_segment_id']],
                    monotonic_at=receipt['received_at_monotonic'], local_at=receipt['received_at_local_utc'])
            except (ValueError, TypeError):
                result = dict(accepted=False, reason='malformed_message')
            if digest(result) != digest(row['result']):
                raise ValueError('normalization_replay_mismatch')
            counts['reason:'+result['reason']] += 1
            if result['accepted']:
                identity = result['event_id']
                content = digest(result['bar'])
                if identity in identities:
                    if identities[identity] != content:
                        counts['conflicting_closed_records'] += 1
                    else:
                        counts['duplicate_closed_records'] += 1
                else:
                    identities[identity] = content
                    counts['unique_closed:'+result['interval']] += 1
                    batches.setdefault((result['interval'], result['close_time']), set()).add(result['symbol'])
        elif kind == 'terminal_failure':
            terminal = True
    for (interval, _), symbols in batches.items():
        if symbols == {'BTCUSDT','ETHUSDT','SOLUSDT'}:
            counts['synchronized_batches:'+interval] += 1
    return dict(counts=dict(counts), clock_segments=len(segments), terminal_failure=terminal,
        unresolved_raw_sequences=list(pending), prefix_only=True, continuity_pass=False,
        signal_ready=False, execution_ready=False, quote_labels=0)


def audit(source, out):
    out.mkdir(parents=True, exist_ok=False)
    manifest_raw = (source/'manifest.json').read_bytes()
    manifest = json.loads(manifest_raw)
    for rel, expected in manifest['source_hashes'].items():
        if hashlib.sha256((ROOT/rel).read_bytes()).hexdigest() != expected:
            raise ValueError('Receiver source changed: '+rel)
    path = source/'receipts.jsonl'
    # Bound reading at the initial file length; an active append cannot extend it.
    with path.open('rb') as handle:
        size = path.stat().st_size
        captured = handle.read(size)
    boundary = captured.rfind(b'\n')+1
    raw, trailing = captured[:boundary], captured[boundary:]
    (out/'captured_prefix.bin').write_bytes(captured)
    (out/'manifest.json').write_bytes(manifest_raw)
    result = verify(raw, require_probes=True)
    result.update(source=str(source), captured_bytes=len(captured), complete_prefix_bytes=boundary,
        incomplete_tail_bytes=len(trailing), captured_sha256=hashlib.sha256(captured).hexdigest(),
        complete_prefix_sha256=hashlib.sha256(raw).hexdigest(), original_manifest_hash=digest(manifest),
        qualification='PREFIX_REPLAY_ONLY_NOT_2H_ACCEPTANCE')
    (out/'report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    print(json.dumps(audit(Path(args.source).resolve(), Path(args.output).resolve())), flush=True)
