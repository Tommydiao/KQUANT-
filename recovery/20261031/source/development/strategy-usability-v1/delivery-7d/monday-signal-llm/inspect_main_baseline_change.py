"""Bounded read-only row/column comparison, never prints business payloads."""
from contextlib import closing
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from time import monotonic

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]


def encoded(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'),
        default=lambda x: {'bytes_hex': x.hex()} if isinstance(x, bytes) else str(x)).encode()


def main():
    proof = json.loads((ROOT / 'source/evidence/new-machine-20261008/portable-activation/bound-9cecac4ccc5f768e/main-activation.json').read_bytes())
    deadline = monotonic() + 2
    results = []
    with closing(sqlite3.connect(Path(proof['database_path']).as_uri() + '?mode=ro', uri=True, timeout=0)) as active, closing(sqlite3.connect(Path(proof['baseline_snapshot']).as_uri() + '?mode=ro', uri=True, timeout=0)) as baseline:
        for db in (active, baseline):
            db.execute('PRAGMA query_only=ON')
            db.set_progress_handler(lambda: int(monotonic() >= deadline), 100)
            db.execute('BEGIN')
        for mark in proof['watermarks']:
            table = mark['table']
            assert table.replace('_', '').isalnum() and mark['column'] == 'rowid'
            query = f'SELECT rowid,* FROM {table} WHERE rowid<=? ORDER BY rowid'
            old_cursor = baseline.execute(query, (mark['minimum'],))
            columns = [x[0] for x in old_cursor.description]
            old = {r[0]: r[1:] for r in old_cursor.fetchall()}
            new = {r[0]: r[1:] for r in active.execute(query, (mark['minimum'],))}
            before, after = sha256(), sha256()
            for row in old.values(): before.update(encoded(row) + b'\n')
            for row in new.values(): after.update(encoded(row) + b'\n')
            changed = []
            for key in sorted(old.keys() & new.keys()):
                if old[key] != new[key]:
                    fields = [columns[i + 1] for i, (a, b) in enumerate(zip(old[key], new[key])) if a != b]
                    changed.append({'rowid': key, 'changed_columns': fields,
                        'safe_context': {columns[i+1]: {'before': a, 'after': b}
                            for i, (a, b) in enumerate(zip(old[key], new[key]))
                            if columns[i+1] in {'status','state','created_at','updated_at','started_at','completed_at','symbol','session','task_type'}}})
            results.append(dict(table=table, baseline_digest_matches=before.hexdigest() == mark['prefix_sha256'],
                active_digest_matches=after.hexdigest() == mark['prefix_sha256'],
                baseline_count=len(old), active_prefix_count=len(new),
                added_prefix_rowids=sorted(new.keys() - old.keys()),
                missing_prefix_rowids=sorted(old.keys() - new.keys()), changed=changed,
                current_max=active.execute(f'SELECT MAX(rowid) FROM {table}').fetchone()[0]))
        active.rollback()
        baseline.rollback()
    result = dict(observed_at=datetime.now(UTC).isoformat(), read_only=True,
        production_writes=0, database_copies=0, tables=results)
    target = HERE / 'evidence/main-baseline-change-20261018.json'
    with target.open('x', encoding='utf-8') as stream: json.dump(result, stream, indent=2)
    print(json.dumps(result))


if __name__ == '__main__': main()
