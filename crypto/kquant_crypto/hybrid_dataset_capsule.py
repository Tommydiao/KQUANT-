"""Portable authorized DEV rows only; no restricted tail or fabricated receipts."""
import gzip
import json
from pathlib import Path

from .candidate_policy import digest
from .hybrid_dataset import Dataset, SYMBOLS, clean_rows, proven_hours, file_hash


def export_capsule(data, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    files = {}
    for symbol in SYMBOLS:
        files[symbol] = {}
        for tf in ('5m', '1h'):
            rows = [dict(vars(bar), **data.provenance[symbol][tf][bar.start])
                    for bar in data.bars[symbol][tf]]
            name = symbol+'_'+tf+'.json.gz'
            payload = json.dumps(rows, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()
            (out/name).write_bytes(gzip.compress(payload, mtime=0))
            files[symbol][tf] = dict(path=name, sha256=file_hash(out/name), rows=len(rows))
    contract = dict(version='authorized_dev_capsule_v1', scope='DEV_ONLY_EXPOSED_RESEARCH',
        cutoff=data.cutoff, dataset_hash=data.content_hash, original_manifest=data.manifest,
        quarantine=data.quarantine, files=files, execution_enabled=False,
        limits='Historical assumed-close availability; receipts retained, not strict quote evidence. '
               'Only authorized DEV plus warmup bars included; restricted tail absent.')
    contract['capsule_hash'] = digest(contract)
    (out/'capsule.json').write_text(json.dumps(contract, sort_keys=True, indent=2), encoding='utf-8')
    return contract


def load_capsule(root):
    root = Path(root).resolve()
    contract = json.loads((root/'capsule.json').read_text())
    if digest({k:v for k,v in contract.items() if k != 'capsule_hash'}) != contract['capsule_hash']:
        raise ValueError('Capsule contract hash mismatch')
    if (contract['version'] != 'authorized_dev_capsule_v1'
        or contract['scope'] != 'DEV_ONLY_EXPOSED_RESEARCH' or contract['execution_enabled'] is not False):
        raise ValueError('Unsupported capsule scope')
    original = contract['original_manifest']
    if digest({k:v for k,v in original.items() if k != 'manifest_hash'}) != original['manifest_hash']:
        raise ValueError('Original manifest identity mismatch')
    window = original['window']
    cutoff = contract['cutoff']
    if (type(cutoff) is not int or cutoff % 300 or
        not window['start'] < cutoff <= window['start']+int(window['days']*.7)*86400):
        raise ValueError('Restricted or invalid cutoff')
    if tuple(original['symbols']) != SYMBOLS or set(contract['files']) != set(SYMBOLS):
        raise ValueError('Core universe mismatch')
    bars, provenance = {}, {}
    for symbol in SYMBOLS:
        bars[symbol], provenance[symbol] = {}, {}
        if set(contract['files'][symbol]) != {'5m', '1h'}:
            raise ValueError('Dual timeframe contract required')
        for tf, duration in (('5m', 300), ('1h', 3600)):
            entry = contract['files'][symbol][tf]
            path = (root/entry['path']).resolve()
            if not path.is_relative_to(root) or file_hash(path) != entry['sha256']:
                raise ValueError('Capsule file integrity mismatch')
            with gzip.open(path, 'rb') as f:
                raw = f.read(64*1024*1024+1)
            if len(raw) > 64*1024*1024:
                raise ValueError('Capsule member exceeds bound')
            rows = json.loads(raw)
            if len(rows) != entry['rows'] or any(r['start'] < window['warmup_start']
                or r['start']+duration > cutoff for r in rows):
                raise ValueError('Rows outside authorized window')
            clean, source, invalid = clean_rows(rows, duration, cutoff)
            if invalid or len(clean) != len(rows):
                raise ValueError('Capsule contains invalid or duplicate rows')
            # Keep original duplicate receipt provenance, not a synthesized value.
            for row in rows:
                if 'receipt_variants' in row:
                    source[row['start']]['receipt_variants'] = row['receipt_variants']
            bars[symbol][tf], provenance[symbol][tf] = clean, source
        _, invalid = proven_hours(bars[symbol]['5m'], bars[symbol]['1h'])
        if invalid:
            raise ValueError('Unproven hourly capsule bars')
    content = digest({s:{tf:[vars(b) for b in rows] for tf,rows in frames.items()}
                      for s,frames in bars.items()})
    if content != contract['dataset_hash']:
        raise ValueError('Authorized dataset content differs')
    return Dataset(bars, provenance, original, contract['quarantine'], cutoff, content)
