"""Export already audited real-bar/synthetic-clock evidence, not live receipts."""
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha, write_json


def main():
    source = ROOT/'outputs/hybrid_delivery/multifactor_journal_recovery_20260908_02'
    report = json.loads((source/'report.json').read_text())
    dbpath = source/'factor_recovery.sqlite3'
    if sha(dbpath) != report['database_hash']:
        raise ValueError('Source recovery database changed')
    output = ROOT/'outputs/hybrid_delivery/multifactor_ingress_cli_fixture_20260908_01'
    output.mkdir(exist_ok=False)
    with sqlite3.connect(dbpath.as_uri()+'?mode=ro', uri=True) as db:
        contract = json.loads(db.execute('SELECT contract FROM factor_metadata WHERE id=1').fetchone()[0])
        write_json(output/'contract.json', {k:contract[k] for k in ('first_close','receipt_basis','source')})
        with (output/'events.jsonl').open('x', encoding='utf-8') as handle:
            for event_id, payload in db.execute('SELECT event_id,payload FROM factor_events ORDER BY seq'):
                handle.write(json.dumps(dict(event_id=event_id,payload=json.loads(payload)))+'\n')
    write_json(output/'manifest.json', dict(source_database_hash=report['database_hash'],
        input_hash=sha(output/'events.jsonl'), receipt_basis='REPLAY_CLOCK_FIXTURE',
        execution_enabled=False, live_evidence=False))
    print(str(output))


if __name__ == '__main__':
    main()
