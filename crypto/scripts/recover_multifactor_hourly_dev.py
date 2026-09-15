"""Immutable source-log audit and isolated recovery, no network or model loading."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_clock import digest
from kquant_crypto.hybrid_factor_journal import FactorJournal
from kquant_crypto.hybrid_hourly_recovery import validate_log, replay_actions


def recover(source, out):
    if out.exists():
        raise ValueError('Recovery output must be new')
    manifest = json.loads((source/'manifest.json').read_text())
    if manifest['scope'] != 'DEV_ONLY' or manifest['execution_enabled'] is not False:
        raise ValueError('Only independent DEV receiver logs accepted')
    for name in ('hybrid_hourly_receipt.py', 'hybrid_clock.py', 'hybrid_factor_journal.py'):
        path = ROOT/'kquant_crypto'/name
        expected = manifest['source_hashes'].get(str(path.relative_to(ROOT)))
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Receiver dependency changed; use archived version')
    with (source/'receipts.jsonl').open('rb') as handle:
        raw = handle.read(160*1024*1024+1)
    if len(raw) > 160*1024*1024 or (raw and not raw.endswith(b'\n')):
        raise ValueError('Oversize or truncated log; explicit tail salvage required')
    source_hash = hashlib.sha256(raw).hexdigest()
    if (source/'report.json').exists():
        report = json.loads((source/'report.json').read_text())
        if report['receipts_sha256'] != source_hash or report['manifest_hash'] != digest(manifest):
            raise ValueError('Completed source integrity mismatch')
    rows = [json.loads(line) for line in raw.decode('utf-8').splitlines()]
    contract, actions, counts = validate_log(rows)
    out.mkdir(parents=True, exist_ok=False)
    snapshots = 0
    if contract is not None:
        journal = FactorJournal(out/'factors.sqlite3', **contract)
        try:
            snapshots = replay_actions(journal, actions)
            journal.replay()
        finally:
            journal.close()
    result = dict(scope='DEV_ONLY_RECEIPT_RECOVERY', source=str(source),
        receipts_sha256=source_hash, manifest_hash=digest(manifest), counts=counts,
        recovered_snapshots=snapshots, execution_enabled=False, model_loading=False,
        live_acceptance=False, labels=0, original_files_modified=False,
        status='RECOVERED' if contract else 'AUDIT_ONLY_NO_DURABLE_JOURNAL_CONTRACT')
    (out/'report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--source', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    print(json.dumps(recover(Path(args.source).resolve(), Path(args.output).resolve())))
