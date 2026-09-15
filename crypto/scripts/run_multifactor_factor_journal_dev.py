"""Explicit receipt-event ingestion, no network/provider/model execution."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_factor_journal import FactorJournal


def run(args):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', args.run_id):
        raise ValueError('Simple independent run ID required')
    path = ROOT / 'work/multifactor_ingress' / args.run_id / 'factors.sqlite3'
    if args.command == 'status':
        if not path.exists():
            return dict(status='NOT_STARTED', execution_enabled=False)
        with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as db:
            contract = json.loads(db.execute('SELECT contract FROM factor_metadata WHERE id=1').fetchone()[0])
            count = db.execute('SELECT COUNT(*) FROM factor_events').fetchone()[0]
            last = db.execute('SELECT event_id,payload FROM factor_events ORDER BY seq DESC LIMIT 1').fetchone()
        return dict(status='STORED_RESEARCH_EVENTS', count=count, last_event_id=last[0] if last else None,
                    receipt_basis=contract['receipt_basis'], source=contract['source'],
                    execution_enabled=False, integrity_replay_performed=False)
    if not args.input or not args.contract:
        raise ValueError('Frozen contract and explicit event file required')
    contract = json.loads(Path(args.contract).read_text(encoding='utf-8'))
    if set(contract) != {'first_close','receipt_basis','source'}:
        raise ValueError('Contract must explicitly contain first_close, receipt_basis and source only')
    offset = getattr(args, 'offset', 0)
    if type(offset) is not int or offset < 0:
        raise ValueError('Nonnegative event offset required')
    if type(args.limit) is not int or not 1 <= args.limit <= 10000:
        raise ValueError('Bounded event count required')
    with Path(args.input).open('rb') as handle:
        raw = handle.read(32 * 1024 * 1024 + 1)
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError('Input exceeds 32 MiB frozen-file limit')
    lines = [line for line in raw.decode('utf-8').splitlines() if line.strip()]
    if offset > len(lines):
        raise ValueError('Offset exceeds frozen input event count')
    input_hash = hashlib.sha256(raw).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Separate input binding preserves the original journal schema and code hash.
    with sqlite3.connect(path.with_name('input_binding.sqlite3'), timeout=5) as binding:
        binding.execute('BEGIN IMMEDIATE')
        binding.execute('CREATE TABLE IF NOT EXISTS input_binding (id INTEGER PRIMARY KEY CHECK(id=1), sha256 TEXT NOT NULL)')
        old = binding.execute('SELECT sha256 FROM input_binding WHERE id=1').fetchone()
        if old and old[0] != input_hash:
            raise ValueError('Frozen input mismatch; use a new run ID')
        if not old:
            if path.exists():
                raise ValueError('Existing unbound journal requires a new run ID')
            binding.execute('INSERT INTO input_binding VALUES(1,?)', (input_hash,))
    journal = FactorJournal(path, **contract)
    accepted = 0
    try:
        before = journal.db.execute('SELECT COUNT(*) FROM factor_events').fetchone()[0]
        for line in lines[offset:offset + args.limit]:
            event = json.loads(line)
            if set(event) != {'event_id','payload'}:
                raise ValueError('Explicit event_id and payload required')
            journal.append(event['event_id'], event['payload'])
            accepted += 1
        after = journal.db.execute('SELECT COUNT(*) FROM factor_events').fetchone()[0]
        return dict(status='CONSUMED', input_events=accepted, inserted=after-before,
                    idempotent=accepted-(after-before), total_events=after,
                    next_offset=offset+accepted,
                    input_sha256=input_hash,
                    scope='DEV_ONLY', receipt_basis=contract['receipt_basis'],
                    execution_enabled=False, live_acceptance=False)
    finally:
        journal.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['consume','status'])
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--input')
    parser.add_argument('--contract')
    parser.add_argument('--limit', type=int, default=1000)
    parser.add_argument('--offset', type=int, default=0)
    args = parser.parse_args()
    if not 1 <= args.limit <= 10000:
        raise ValueError('Bounded event count required')
    print(json.dumps(run(args), sort_keys=True))


if __name__ == '__main__':
    main()
