"""Local delivery evidence ledger. Never an execution or authorization service."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, UTC
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import tomllib


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        f.write(encoded(value) + '\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


@contextmanager
def lock(path):
    """OS lock dies with the process; no stealing PID leases or service locks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as f:
        if f.tell() == 0:
            f.write(b'0')
            f.flush()
        f.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


class Delivery:
    """Task completion is evidence bookkeeping, not a financial gate token.

    SQLite is authoritative. JSON projections are recoverable; corrupt/tampered
    projections cannot grant permissions. No arbitrary shell or trading handler.
    """
    def __init__(self, root, work=None):
        self.root = Path(root).resolve()
        self.work = Path(work or self.root / 'work/hybrid_delivery').resolve()
        if not self.work.is_relative_to(self.root / 'work'):
            raise ValueError('Delivery storage must be under independent work directory')
        self.work.mkdir(parents=True, exist_ok=True)
        self.board_path = self.root / 'plan/hybrid_to_live_tasks.v1_2.json'
        self.policy_path = self.root / 'plan/hybrid_gate_policy.v1_2.json'
        self.board = load(self.board_path)
        self.policy = load(self.policy_path)
        self.tasks = {t['id']: t for t in self.board['tasks']}
        self.db = sqlite3.connect(self.work / 'delivery.sqlite3', timeout=1)
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS receipts(task TEXT PRIMARY KEY, path TEXT NOT NULL, hash TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, at TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS attempts(task TEXT, input_hash TEXT, count INTEGER NOT NULL, PRIMARY KEY(task,input_hash));
          CREATE TABLE IF NOT EXISTS claims(task TEXT PRIMARY KEY, owner TEXT NOT NULL, files TEXT NOT NULL,
              acquired REAL NOT NULL, expires REAL NOT NULL);
        ''')
        for key, path in [('board_hash', self.board_path), ('policy_hash', self.policy_path)]:
            actual = sha(path)
            old = self.db.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()
            if old and old[0] != actual:
                self.db.close()
                raise ValueError('Version mismatch: explicit migration required: ' + key)
            self.db.execute('INSERT OR IGNORE INTO metadata VALUES (?,?)', (key, actual))
        self.db.commit()

    def close(self):
        self.db.close()

    def safe_path(self, relative):
        p = (self.root / relative).resolve()
        if not p.is_relative_to(self.root) or p.name.startswith('.env') or p.suffix in ('.pem', '.key'):
            raise ValueError('Evidence path not allowed')
        # Evidence must be explicit code, plan, test or output, not a secret directory.
        if p.relative_to(self.root).parts[0] not in ('outputs', 'docs', 'plan', 'config', 'scripts', 'kquant_crypto', 'tests'):
            raise ValueError('Evidence namespace not allowed')
        return p

    def approved_existing_schedule(self):
        """Only reuse the exact preexisting heartbeat requested by the user.

        This does not approve installing a scheduler, account access or money.
        No approval template or state boolean is consulted.
        """
        p = Path.home() / '.codex/automations/kquant/automation.toml'
        try:
            a = tomllib.loads(p.read_text('utf-8'))
            return (a.get('id') == 'kquant' and a.get('kind') == 'heartbeat'
                    and a.get('status') == 'ACTIVE'
                    and a.get('created_at') == 1788589081851
                    and a.get('target_thread_id') == '019ed077-55f9-7843-baa7-9f9970d6dcf0'
                    and a.get('rrule') == 'FREQ=HOURLY;INTERVAL=2'
                    and 'Hybrid V1.2' in a.get('prompt', ''))
        except (OSError, ValueError):
            return False

    def approval_available(self, task):
        key = task['requires_approval']
        return not key or (key == 'A1_SCHEDULER_IF_INSTALL_REQUIRED' and self.approved_existing_schedule())

    def validate_receipt(self, task, path, expected=None):
        p = self.safe_path(path)
        if expected and sha(p) != expected:
            raise ValueError('Receipt changed')
        r = load(p)
        t = self.tasks[task]
        if r['task_id'] != task or r['board_sha256'] != sha(self.board_path):
            raise ValueError('Receipt identity/version mismatch')
        if r['status'] not in ('VERIFIED', 'WAIT_DATA', 'WAIT_OWNER', 'WAIT_EXTERNAL', 'BLOCKED_CONTRACT', 'NO_GO'):
            raise ValueError('Invalid receipt status')
        if not r.get('evidence'):
            raise ValueError('Missing evidence')
        for item in r['evidence']:
            if sha(self.safe_path(item['path'])) != item['sha256']:
                raise ValueError('Evidence hash mismatch: ' + item['path'])
        if r['status'] == 'VERIFIED':
            if set(r['acceptance']) != set(t['acceptance']):
                raise ValueError('Acceptance mapping incomplete')
            names = {e['path'] for e in r['evidence']}
            if any(not refs or not set(refs) <= names for refs in r['acceptance'].values()):
                raise ValueError('Acceptance must reference evidence')
        elif not all(r.get(k) for k in ('owner', 'reason', 'next_trigger', 'blocked_scope')):
            raise ValueError('Waiting result needs scoped blocker and recovery trigger')
        return r

    def event(self, kind, body):
        self.db.execute('INSERT INTO events(at,kind,body) VALUES (?,?,?)',
                        (datetime.now(UTC).isoformat(), kind, encoded(body)))

    def record(self, path):
        r = load(self.safe_path(path))
        task = r['task_id']
        if task not in self.tasks:
            raise ValueError('Unknown task')
        if self.tasks[task]['scope'] in ('owner_only', 'owner_runtime_only', 'production_readonly', 'testnet_only'):
            raise ValueError('External/owner tasks require a separate trusted verifier; no local promotion')
        r = self.validate_receipt(task, path)
        with lock(self.work / 'locks/development.lock'), self.db:
            prior = self.db.execute('SELECT hash FROM receipts WHERE task=?', (task,)).fetchone()
            digest = sha(self.safe_path(path))
            if prior and prior[0] == digest:
                return False
            if r['status'] == 'VERIFIED':
                view = self.status()
                if any(view['tasks'][d]['status'] != 'VERIFIED' for d in self.tasks[task]['depends_on']):
                    raise ValueError('Dependencies not verified')
                if any(view['gates'][g]['state'] != 'PASS' for g in self.tasks[task]['requires_gates']):
                    raise ValueError('Required gate not verified')
                if not self.approval_available(self.tasks[task]):
                    raise ValueError('Approval-required task cannot be locally self-approved')
            self.db.execute('INSERT OR REPLACE INTO receipts VALUES (?,?,?)', (task, path, digest))
            self.event('RECEIPT', {'task': task, 'path': path, 'sha256': digest, 'status': r['status']})
        self.project()
        return True

    def claim(self, task, owner, files, seconds=3600):
        if task not in self.tasks or not owner or not files or not 0 < seconds <= 5400:
            raise ValueError('Bounded task ownership required')
        normalized = [str(self.safe_path(p).relative_to(self.root)).replace('\\', '/') for p in files]
        with lock(self.work / 'locks/development.lock'), self.db:
            for tid, prior_owner, prior_files in self.db.execute('SELECT task,owner,files FROM claims'):
                if tid == task or set(json.loads(prior_files)) & set(normalized):
                    raise ValueError('Existing ownership; inspect owner and explicitly release, never steal')
            now=time.time()
            self.db.execute('INSERT INTO claims VALUES (?,?,?,?,?)',(task,owner,encoded(normalized),now,now+seconds))
            self.event('CLAIM',{'task':task,'owner':owner,'files':normalized,'expires_at_raw_local':now+seconds})
        self.project()

    def release(self, task, owner):
        with lock(self.work / 'locks/development.lock'), self.db:
            row=self.db.execute('SELECT owner FROM claims WHERE task=?',(task,)).fetchone()
            if not row or row[0]!=owner: raise ValueError('Only matching development owner may release')
            self.db.execute('DELETE FROM claims WHERE task=?',(task,))
            self.event('RELEASE',{'task':task,'owner':owner})
        self.project()

    def gates(self, records):
        result = {g['id']: {'state': 'NOT_EVALUATED', 'reason': 'No task boolean grants a gate'} for g in self.policy['gates']}
        # Only implemented evidence-specific checks can pass. All other gates
        # remain closed until their dedicated verifier is implemented and tested.
        for gid, tid, field in [('G0', 'T00', 'baseline_integrity'), ('G1', 'T13', 'development_data_eligible')]:
            r = records.get(tid)
            if not r or r.get('status') != 'VERIFIED':
                continue
            try:
                evidence = load(self.safe_path(r['machine_evidence']))
                if evidence.get(field) is not True:
                    raise ValueError('Evidence-specific checks failed')
                if not evidence.get('checks') or not all(evidence['checks'].values()):
                    raise ValueError('Missing or failed checks')
                if r['machine_evidence'] not in {e['path'] for e in r['evidence']}:
                    raise ValueError('Unchecked machine evidence')
                # Re-run the underlying fixed audit, not just a saved PASS field.
                from kquant_crypto.hybrid_delivery_audit import verify_frozen_inputs
                verify_frozen_inputs(self.root)
                result[gid] = {'state': 'PASS', 'scope': 'EXPOSED_BAR_DEV' if gid == 'G1' else 'INCREMENTAL_BASELINE',
                               'reason': 'Fixed artifact and label audit revalidated; no trading permission'}
            except (ValueError, KeyError, OSError) as exc:
                result[gid] = {'state': 'BLOCKED', 'reason': str(exc)}
        return result

    def status(self):
        records, views = {}, {}
        for task, path, digest in self.db.execute('SELECT task,path,hash FROM receipts'):
            try:
                records[task] = self.validate_receipt(task, path, digest)
            except (ValueError, KeyError, OSError) as exc:
                records[task] = {'status': 'BLOCKED_CONTRACT', 'reason': str(exc)}
        gates = self.gates(records)
        # Stable topological resolution also invalidates descendants when an
        # upstream receipt/artifact changes after its original verification.
        remaining = set(self.tasks)
        while remaining:
            eligible = [k for k in remaining if set(self.tasks[k]['depends_on']) <= views.keys()]
            if not eligible:
                raise ValueError('Task graph cycle')
            for k in sorted(eligible):
                t, r = self.tasks[k], records.get(k, {})
                blockers = [d for d in t['depends_on'] if views[d]['status'] != 'VERIFIED']
                blockers += [g for g in t['requires_gates'] if gates[g]['state'] != 'PASS']
                status = r.get('status', 'TODO')
                if t['scope'] in ('owner_only', 'owner_runtime_only') or not self.approval_available(t):
                    status = 'WAIT_OWNER'
                elif blockers:
                    status = 'TODO' if not r else 'BLOCKED_CONTRACT'
                elif not r:
                    status = 'READY'
                views[k] = {'status': status, 'title': t['title'], 'blockers': blockers,
                            'reason': r.get('reason'), 'next_trigger': r.get('next_trigger')}
                remaining.remove(k)
        paused = self.db.execute("SELECT value FROM metadata WHERE key='paused'").fetchone()
        claims = {t:{'owner':o,'files':json.loads(f),'expires_at_raw_local':e,'expired_not_stolen':e<time.time()}
                  for t,o,f,e in self.db.execute('SELECT task,owner,files,expires FROM claims')}
        for t,c in claims.items():
            if views[t]['status']=='READY':
                views[t]['status']='RUNNING' if not c['expired_not_stolen'] else 'WAIT_EXTERNAL'
                views[t]['reason']='Owned development task; verify owner before recovery'
        ready = sorted((k for k, v in views.items() if v['status'] == 'READY'), key=lambda k: (self.tasks[k]['priority'], k))
        return {'tasks': views, 'gates': gates, 'ready': ready, 'next_task': ready[0] if ready else None,
                'file_ownership':claims,
                'paused': bool(paused and paused[0] == 'true'), 'live_enabled': False,
                'math_filtering_enabled': False, 'sizing_enabled': False,
                'authorization_source': 'NOT_THIS_LEDGER', 'state_kind': 'DEVELOPMENT_PROGRESS_ONLY'}

    def project(self):
        with lock(self.work / 'locks/projection.lock'):
            atomic_json(self.work / 'state.json', self.status())
            # Repair a missing/torn append-only export from authoritative SQL IDs.
            rows = self.db.execute('SELECT id,at,kind,body FROM events ORDER BY id').fetchall()
            target = self.work / 'events.jsonl'
            previous = target.read_text('utf-8').splitlines() if target.exists() else []
            lines = [encoded({'id': i, 'at_raw_local_utc': at, 'kind': kind, 'body': json.loads(body)}) for i, at, kind, body in rows]
            if previous != lines[:len(previous)]:
                # A crash may tear only the final exported line. Preserve bytes
                # and regenerate this projection from committed SQL, not history.
                data=target.read_bytes()
                if previous and not data.endswith(b'\n') and previous[:-1]==lines[:len(previous)-1] and len(previous)<=len(lines) and lines[len(previous)-1].startswith(previous[-1]):
                    backup=self.work/('events_torn_'+hashlib.sha256(data).hexdigest()+'.jsonl')
                    if not backup.exists():
                        with backup.open('xb') as f: f.write(data)
                    with target.open('w',encoding='utf-8') as f:
                        for line in lines: f.write(line+'\n')
                        f.flush();os.fsync(f.fileno())
                    previous=lines
                else:
                    raise ValueError('Event export mismatch; preserve and investigate, do not overwrite')
            with target.open('a', encoding='utf-8') as f:
                for line in lines[len(previous):]:
                    f.write(line + '\n')
                f.flush()
                os.fsync(f.fileno())

    def pause(self, enabled):
        with lock(self.work / 'locks/development.lock'), self.db:
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES ('paused',?)", ('true' if enabled else 'false',))
            self.event('PAUSE' if enabled else 'RESUME', {'protection_processes_affected': False})
        self.project()

    def run_ready(self, receipt_directory, budget_seconds=60):
        """Verify completed work then select next implementation, never shell plans.

        The coding session performs code work. This bounded dispatcher validates
        available receipts only; it does not pretend it can autonomously write code.
        """
        if not 0 < budget_seconds <= 5400:
            raise ValueError('Budget outside local development bound')
        start, completed, failures = time.monotonic(), [], []
        directory = self.safe_path(receipt_directory)
        with lock(self.work / 'locks/runner.lock'):
            if self.status()['paused']:
                return {'paused': True, 'completed': []}
            while time.monotonic() - start < budget_seconds:
                progress = False
                for tid in self.status()['ready']:
                    p = directory / (tid + '.json')
                    if not p.is_file():
                        continue
                    digest = sha(p)
                    n = self.db.execute('SELECT count FROM attempts WHERE task=? AND input_hash=?', (tid, digest)).fetchone()
                    if n and n[0] >= 3:
                        continue
                    try:
                        changed = self.record(str(p.relative_to(self.root)))
                        if changed:
                            completed.append(tid)
                            progress = True
                    except (ValueError, KeyError, OSError) as exc:
                        with self.db:
                            self.db.execute('INSERT INTO attempts VALUES (?,?,1) ON CONFLICT(task,input_hash) DO UPDATE SET count=count+1', (tid, digest))
                            self.event('VERIFY_FAILED', {'task': tid, 'input_hash': digest, 'reason': str(exc)})
                        failures.append(tid)
                if not progress:
                    break
            self.project()
        return {'completed': completed, 'failed': failures, 'next_implementation_tasks': self.status()['ready'],
                'budget_seconds': budget_seconds, 'elapsed_seconds': time.monotonic() - start,
                'background_worker_started': False}

    def prepare_live_approval(self):
        # This version has no trusted G2..G9 verifier or protected approval reader.
        # A draft of missing requirements is useful, but cannot be a READY package.
        s = self.status()
        needed = self.policy['aggregate_rules']['ready_for_owner_live_approval_requires']
        return {'status': 'NOT_READY', 'missing_gates': [g for g in needed if s['gates'][g]['state'] != 'PASS'],
                'capital_cap': None, 'account': None, 'expires_at': None,
                'live_enabled': False, 'codex_may_submit_orders': False,
                'reason': 'Readiness report only; protected user activation is not implemented by this runner'}
