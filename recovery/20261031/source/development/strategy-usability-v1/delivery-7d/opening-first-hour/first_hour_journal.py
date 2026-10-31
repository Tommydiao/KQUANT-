# Isolated first-hour candidate derived from the existing journal; not installed.
"""Checkpoint recovery in the existing research continuation journal, not a ledger."""
from contextlib import closing
from datetime import date, timedelta
import json

from kquant import options_one_minute as common
from kquant.bounded_sqlite import read_connection
from kquant.options_data_paths import connect_store
from kquant.market_clock import session_bounds_utc
from first_hour import policies


def load_policy():
    return policies()["S0"]

KIND = "OPENING_MOMENTUM_CALCULATION"
BATCH_BOUND = 64


class InputLease(str):
    """A checkpoint identity plus the immutable input generation being computed."""
    def __new__(cls, job_id, generation, fingerprint):
        value = super().__new__(cls, job_id)
        value.generation, value.fingerprint = generation, fingerprint
        return value


def input_fingerprint(job, source_decisions=()):
    symbol, day, bars, scope, reference = job
    # Repeated delivery timestamps do not create a new price version. Source,
    # OHLC, availability, and the accepted source decision do.
    fields = ("symbol", "open_at", "close_at", "available_at", "provider_time",
              "open", "high", "low", "close", "volume", "turnover", "amount", "confirmed")
    versions = []
    for bar in bars:
        row = {name: bar.get(name) for name in fields if name in bar}
        row["interface"] = bar.get("sdk_evidence", {}).get("interface")
        try:
            end, received = common.timestamp(bar["available_at"]), common.timestamp(bar["received_at"])
            row["received_before_available"] = received < end
        except (KeyError, TypeError, ValueError):
            row["received_before_available"] = "UNVERIFIED"
        versions.append(common.digest(row))
    ignored = {"checked_at", "requested_at", "received_at", "reference_hash", "computed_at"}
    def stable(value):
        if isinstance(value, dict):
            return {k: stable(v) for k, v in value.items() if k not in ignored}
        if isinstance(value, list):
            return [stable(v) for v in value]
        return value
    if isinstance(reference.get("raw_quote"), dict):
        native = reference["raw_quote"]
        binding = native.get("session_price_binding", {})
        quote_time = native.get("quote_time")
        try:
            business_day = common.timestamp(quote_time).astimezone(common.NY).date().isoformat()
        except (TypeError, ValueError, AttributeError):
            business_day = "UNKNOWN"
        reference = dict(previous_close=native.get("previous_close"), currency=native.get("currency"),
            currency_identity=stable({k: v for k, v in native.get("currency_evidence", {}).items() if k != "source_hash"}),
            business_day=business_day, reference_session=native.get("reference_session"),
            binding_status=binding.get("status"), binding_reasons=binding.get("reasons"),
            interface_claim=binding.get("interface_fact", {}).get("claim_hash") if binding.get("interface_fact") else None,
            basis=binding.get("price_basis_method"), actions=binding.get("action_coverage"))
    return common.digest([symbol, day.isoformat(), scope, sorted(set(versions)), stable(reference),
                          sorted(d["decision_hash"] if "decision_hash" in d else common.digest(d)
                                 for d in source_decisions)])


def _payload(key, job, fingerprint, *, policy_hash=None, policy=None):
    symbol, day, _, scope, reference = job
    policy = load_policy() if policy is None else policy
    if key[-1] * 5 not in policy['checkpoint_minutes']:
        raise ValueError('INVALID_FIRST_HOUR_CHECKPOINT')
    opening, closing = session_bounds_utc(day)
    deadline = min(opening + timedelta(minutes=(key[-1] + 1) * 5),
                   opening + timedelta(minutes=policy["entry_window_minutes"]), closing)
    return dict(kind=KIND, strategy=key[0], session=day.isoformat(), symbol=symbol,
        scope_hash=scope, policy_hash=policy_hash if policy_hash is not None else policy["policy_hash"],
        checkpoint_slot=key[-1], window_id=policy['window_id'],
        reference=reference, input_fingerprint=fingerprint), deadline


def initialize(path):
    with closing(connect_store(path, timeout=.1)) as db:
        db.executescript("""CREATE TABLE IF NOT EXISTS two_hour_jobs (
            job_id TEXT PRIMARY KEY, session TEXT NOT NULL, symbol TEXT NOT NULL,
            slot TEXT NOT NULL, queued_at TEXT NOT NULL, deadline_at TEXT NOT NULL,
            state TEXT NOT NULL, lease_owner TEXT, lease_until TEXT, attempts INTEGER NOT NULL DEFAULT 0,
            retry_at TEXT, reason TEXT, payload_json TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS trend_input_pending ON two_hour_jobs(state,retry_at,queued_at);
            CREATE INDEX IF NOT EXISTS trend_input_source ON two_hour_jobs(session,symbol,queued_at);""")


def identity(key, scope, *, policy_hash=None):
    policy_hash = policy_hash if policy_hash is not None else load_policy()["policy_hash"]
    return common.digest([KIND, key, scope, policy_hash])


def register_clock_positions(path, registered, day, scope_hash, now):
    """Manifest positions precede market input; elapsed positions are not backfilled."""
    if len(registered)>111 or not scope_hash:
        raise ValueError('CHECKPOINT_REGISTERED_SCOPE_INVALID')
    policy=load_policy()
    policy_hash=policy['policy_hash']
    opening,_=session_bounds_utc(day)
    planned=[]
    for row in registered:
        if row.get('identity_status')!='verified':
            continue
        for slot in (minute // 5 for minute in policy["checkpoint_minutes"]):
            key=('opening_momentum',day.isoformat(),row['symbol'],slot)
            job=(row['symbol'],day,[],scope_hash,{})
            payload,deadline=_payload(key,job,None,policy_hash=policy_hash,policy=policy)
            if now>=deadline:
                continue
            checkpoint=opening+timedelta(minutes=slot*5)
            payload.update(input_generation=0,completed_generation=0,deadline_at=deadline.isoformat(),
                           checkpoint_at=checkpoint.isoformat(),registered_at=now.isoformat(),
                           registered_from='MANIFEST_AND_SESSION_CLOCK',input_received=False)
            planned.append((identity(key,scope_hash,policy_hash=policy_hash),day.isoformat(),row['symbol'],str(slot),
                now.isoformat(),deadline.isoformat(),'WAIT_CLOCK' if now<checkpoint else 'WAIT_INPUT',
                common.canonical(payload)))
    if not planned:
        return {'positions_planned':0,'inserted':0,'no_historical_backfill':True}
    with closing(connect_store(path,timeout=.05)) as db,db:
        before=db.total_changes
        db.executemany('''INSERT OR IGNORE INTO two_hour_jobs VALUES
            (?,?,?,?,?,?,?,NULL,NULL,0,NULL,'WAIT_FOR_CHECKPOINT_INPUT',?)''',planned)
        inserted=db.total_changes-before
    return {'positions_planned':len(planned),'inserted':inserted,'no_historical_backfill':True}


def advance_clock_positions(path, registered, day, scope_hash, now):
    policy=load_policy()
    policy_hash=policy['policy_hash']
    ids=[identity(('opening_momentum',day.isoformat(),row['symbol'],slot),scope_hash,policy_hash=policy_hash)
         for row in registered if row.get('identity_status')=='verified' for slot in (minute // 5 for minute in policy["checkpoint_minutes"])]
    if len(registered)>111 or not ids:
        return {'advanced':0,'expired_no_minute':0,'expired_incomplete':0}
    with read_connection(path,seconds=.3) as db:
        rows=db.execute('SELECT job_id,state,deadline_at,payload_json FROM two_hour_jobs WHERE job_id IN ('+
                        ','.join('?' for _ in ids)+')',ids).fetchall()
    changes=[]
    counts={'advanced':0,'expired_no_minute':0,'expired_incomplete':0}
    for job_id,state,deadline,raw in rows:
        value=common.timestamp(deadline)
        if state not in {'WAIT_CLOCK','WAIT_INPUT','READY','LEASED'}:
            continue
        payload=json.loads(raw)
        if now>=value:
            no_input=not payload.get('input_received',True) or payload.get('minute_input_count')==0
            reason='DATA_UNAVAILABLE_NO_MINUTE' if no_input else 'DATA_INCOMPLETE_AT_ORIGINAL_DEADLINE'
            payload['terminal_observed_at']=now.isoformat()
            changes.append(('expired_no_minute' if no_input else 'expired_incomplete',
                            ('EXPIRED',reason,common.canonical(payload),job_id,state,raw)))
        elif state=='WAIT_CLOCK' and now>=common.timestamp(payload['checkpoint_at']):
            changes.append(('advanced',('WAIT_INPUT','WAIT_FOR_CHECKPOINT_INPUT',raw,job_id,state,raw)))
    if changes:
        with closing(connect_store(path,timeout=.05)) as db,db:
            for category, values in changes:
                changed=db.execute('''UPDATE two_hour_jobs SET state=?,reason=?,payload_json=?,lease_owner=NULL,lease_until=NULL
                    WHERE job_id=? AND state=? AND payload_json=?''',values).rowcount
                counts[category]+=changed
    return counts


def ready(path, key, job, now, *, fingerprint=None):
    """Commit the original checkpoint before admitting it to the compute queue."""
    return ready_many(path, [(key, job, now, fingerprint)])[0]


def ready_many(path, entries, *, return_leases=False):
    """Bounded checkpoint admission shares one commit, never one logical job."""
    if len(entries) > BATCH_BOUND:
        raise ValueError("CHECKPOINT_ADMISSION_BATCH_BOUND_EXCEEDED")
    if not entries:
        return []
    # One immutable policy identity per bounded operation, never a cross-batch
    # cache or file I/O while holding the SQLite writer.
    policy = load_policy()
    policy_hash = policy["policy_hash"]
    prepared = [(key, job, now, fingerprint or input_fingerprint(job))
                for key, job, now, fingerprint in entries]
    ids = [identity(key, job[3], policy_hash=policy_hash) for key, job, _, _ in prepared]
    with read_connection(path, seconds=.3) as db:
        existing = {row[0]: row[1:] for row in db.execute(
            "SELECT job_id,state,payload_json FROM two_hour_jobs WHERE job_id IN ("
            + ",".join("?" for _ in ids) + ")", ids).fetchall()}
    needed, results = [], [False] * len(prepared)
    for index, (key, job, now, fingerprint) in enumerate(prepared):
        old = existing.get(ids[index])
        payload, deadline = _payload(key, job, fingerprint, policy_hash=policy_hash, policy=policy)
        if old and (old[0] == "EXPIRED" or (now < deadline and
                json.loads(old[1]).get("input_fingerprint") == fingerprint)):
            # Admission is also the handoff to the volatile compute queue.
            # Recover an unconsumed READY notification without rewriting its
            # generation. begin_many still rechecks state/fingerprint/deadline.
            # The unique compute lane may be abandoning an equivalent lease.
            # Returning its identity never changes state or lets another owner
            # supersede it; begin/finish still use the durable generation CAS.
            accepted = (old[0] == 'READY' or return_leases and old[0] == 'LEASED') and now < deadline
            previous = json.loads(old[1])
            results[index] = (InputLease(ids[index], previous['input_generation'], fingerprint)
                              if accepted and return_leases else accepted)
            continue
        needed.append((index, key, job, now, ids[index], payload, deadline))
    if not needed:
        return results
    # Changed inputs still recheck the current row inside the write transaction.
    # Duplicate wakeups never acquire a writer or cache a prior admission result.
    with closing(connect_store(path, timeout=.05)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        for index, key, job, now, job_id, payload, deadline in needed:
            results[index] = _ready(db, key, job, now, job_id, payload, deadline,
                                    return_lease=return_leases)
    return results


def _ready(db, key, job, now, job_id, payload, deadline, *, return_lease=False):
    symbol, day = job[:2]
    old = db.execute("SELECT state,payload_json FROM two_hour_jobs WHERE job_id=?", (job_id,)).fetchone()
    previous = json.loads(old[1]) if old else {}
    if old and old[0] == "EXPIRED":
        return False
    state = "EXPIRED" if now >= deadline else "READY"
    changed = payload["input_fingerprint"] != previous.get("input_fingerprint")
    if old and not changed and state != "EXPIRED":
        accepted = old[0] == 'READY' or return_lease and old[0] == 'LEASED'
        return (InputLease(job_id, previous['input_generation'], payload['input_fingerprint'])
                if return_lease and accepted else accepted)
    payload["input_generation"] = previous.get("input_generation", 0) + int(changed)
    payload["completed_generation"] = previous.get("completed_generation", 0)
    payload["deadline_at"] = deadline.isoformat()
    payload['input_received']=bool(job[2])
    payload['minute_input_count']=len(job[2])
    if previous.get('registered_from'):
        payload.update({name:previous[name] for name in ('registered_from','registered_at','checkpoint_at') if name in previous})
    db.execute("""INSERT INTO two_hour_jobs VALUES (?,?,?,?,?,?,?,NULL,NULL,0,NULL,NULL,?)
        ON CONFLICT(job_id) DO UPDATE SET state=excluded.state,payload_json=excluded.payload_json,
            lease_owner=NULL,lease_until=NULL""",
        (job_id, day.isoformat(), symbol, str(key[-1]), now.isoformat(), deadline.isoformat(), state, common.canonical(payload)))
    return (InputLease(job_id, payload['input_generation'], payload['input_fingerprint'])
            if return_lease and state == 'READY' else state == 'READY')


def begin(path, key, job, now, *, fingerprint=None):
    _, _, _, scope, _ = job
    fingerprint = fingerprint or input_fingerprint(job)
    job_id = identity(key, scope)
    with read_connection(path, seconds=.3) as db:
        admitted = db.execute("SELECT payload_json FROM two_hour_jobs WHERE job_id=?", (job_id,)).fetchone()
    if not admitted or json.loads(admitted[0]).get("input_fingerprint") != fingerprint:
        ready(path, key, job, now, fingerprint=fingerprint)
    with closing(connect_store(path, timeout=.05)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT state,payload_json,deadline_at FROM two_hour_jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row or row[0] in {"EXPIRED", "COMPLETED"} or now >= common.timestamp(row[2]):
            return None
        payload = json.loads(row[1])
        if payload["input_fingerprint"] != fingerprint:
            return None
        db.execute("UPDATE two_hour_jobs SET state='LEASED',attempts=attempts+1 WHERE job_id=?", (job_id,))
    return InputLease(job_id, payload["input_generation"], fingerprint)


def begin_many(path, entries):
    if len(entries) > BATCH_BOUND:
        raise ValueError("CHECKPOINT_COMPUTE_BATCH_BOUND_EXCEEDED")
    if not entries:
        return []
    policy_hash = load_policy()["policy_hash"]
    ids = [identity(key, job[3], policy_hash=policy_hash) for key, job, _, _ in entries]
    leases = []
    with closing(connect_store(path, timeout=.05)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        for job_id, (_, _, now, fingerprint) in zip(ids, entries):
            row = db.execute("SELECT state,payload_json,deadline_at FROM two_hour_jobs WHERE job_id=?", (job_id,)).fetchone()
            # Admission is authoritative. Do not write an older fingerprint back
            # over a concurrent newer READY generation.
            if not row or row[0] in {"EXPIRED", "COMPLETED"} or now >= common.timestamp(row[2]):
                leases.append(None)
                continue
            payload = json.loads(row[1])
            if payload["input_fingerprint"] != fingerprint:
                leases.append(None)
                continue
            db.execute("UPDATE two_hour_jobs SET state='LEASED',attempts=attempts+1 WHERE job_id=?", (job_id,))
            leases.append(InputLease(job_id, payload["input_generation"], fingerprint))
    return leases


def finish(path, job_id, *, waiting=False, rows=None, now=None):
    """CAS the result and evidence together; stale workers cannot commit either."""
    from kquant.options_input_commit_fence import commit_fence
    with commit_fence(), closing(connect_store(path, timeout=.05)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        return _finish(db, job_id, waiting, rows, now=now)


def release(path, lease, now):
    """Invalidate this computation without overwriting a newer admitted input."""
    if not isinstance(lease, InputLease):
        return False
    with closing(connect_store(path, timeout=.05)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT state,payload_json,deadline_at FROM two_hour_jobs WHERE job_id=?',
                         (str(lease),)).fetchone()
        if not row or row[0] != 'LEASED':
            return False
        payload = json.loads(row[1])
        if (payload.get('input_generation') != lease.generation or
                payload.get('input_fingerprint') != lease.fingerprint):
            return False
        state = 'EXPIRED' if now >= common.timestamp(row[2]) else 'READY'
        db.execute("UPDATE two_hour_jobs SET state=?,lease_owner=NULL,lease_until=NULL WHERE job_id=?",
                   (state, str(lease)))
        return True


def _finish(db, job_id, waiting, rows, *, now=None):
    row = db.execute("SELECT state,payload_json,deadline_at FROM two_hour_jobs WHERE job_id=?", (str(job_id),)).fetchone()
    if not row or row[0] != "LEASED" or not isinstance(job_id, InputLease):
        return False
    payload = json.loads(row[1])
    if (payload.get("input_generation") != job_id.generation
            or payload.get("input_fingerprint") != job_id.fingerprint):
        return False
    if now is not None and now >= common.timestamp(row[2]):
        db.execute("UPDATE two_hour_jobs SET state='EXPIRED',reason='COMPUTE_AT_ORIGINAL_DEADLINE' WHERE job_id=?",
                   (str(job_id),))
        return False
    if ((now is not None and getattr(job_id, 'valid_before', None) is not None
         and now >= job_id.valid_before) or
            (getattr(job_id, 'boundary_guard', None) is not None and not job_id.boundary_guard())):
        db.execute("UPDATE two_hour_jobs SET state='READY',reason='PREPARED_BOUNDARY_CHANGED' WHERE job_id=?",
                   (str(job_id),))
        return False
    payload["completed_generation"] = job_id.generation
    if rows is not None:
        from kquant.options_opening_trend_store import persist_in_transaction
        persist_in_transaction(db, rows)
    db.execute("UPDATE two_hour_jobs SET state=?,reason=NULL,payload_json=? WHERE job_id=?",
               ("WAIT_INPUT" if waiting else "COMPLETED", common.canonical(payload), str(job_id)))
    return True


def finish_many(path, entries, *, now=None):
    if len(entries) > BATCH_BOUND:
        raise ValueError("CHECKPOINT_RESULT_BATCH_BOUND_EXCEEDED")
    from kquant.options_input_commit_fence import commit_fence
    outcomes = []
    with commit_fence(), closing(connect_store(path, timeout=.05)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        for lease, waiting, rows in entries:
            if lease is None:
                from kquant.options_opening_trend_store import persist_in_transaction
                persist_in_transaction(db, rows)
                outcomes.append(True)
            else:
                outcomes.append(_finish(db, lease, waiting, rows, now=now() if callable(now) else now))
    return outcomes


def restore(path, now):
    jobs = {}
    with read_connection(path, seconds=.3) as db:
        rows = db.execute("""SELECT job_id,state,payload_json FROM two_hour_jobs
            WHERE session=? AND state IN ('READY','LEASED','WAIT_INPUT') AND deadline_at>?
            AND json_extract(payload_json,'$.kind')=?
            AND json_extract(payload_json,'$.policy_hash')=? ORDER BY queued_at LIMIT 223""",
            (now.astimezone(common.NY).date().isoformat(), now.isoformat(), KIND, load_policy()["policy_hash"])).fetchall()
    if len(rows) > 222:
        raise ValueError("CHECKPOINT_RESTORE_BOUND_EXCEEDED")
    if not rows:
        return jobs
    # This is a restart of the unique lane, not a second lease owner. Re-arm the
    # same generation/deadline; the new process must rebuild its volatile handoff.
    with closing(connect_store(path, timeout=.05)) as db, db:
        db.executemany("""UPDATE two_hour_jobs SET state='READY',lease_owner=NULL,lease_until=NULL
            WHERE job_id=? AND state='LEASED' AND payload_json=? AND deadline_at>?""",
            [(job_id, raw, now.isoformat()) for job_id, state, raw in rows if state == 'LEASED'])
    policy_hash = load_policy()["policy_hash"]
    for _, _, raw in rows:
        value = json.loads(raw)
        if value["policy_hash"] != policy_hash:
            continue
        day = date.fromisoformat(value["session"])
        key = value["strategy"], value["session"], value["symbol"], value["checkpoint_slot"]
        jobs[key] = value["symbol"], day, [], value["scope_hash"], value["reference"]
    return jobs


def record_missed(path, key, job, now, *, reason="MISSED_BEFORE_DURABLE_ENQUEUE"):
    """Explain a registered, elapsed checkpoint without manufacturing a result."""
    policy_hash = load_policy()["policy_hash"]
    payload, deadline = _payload(key, job, input_fingerprint(job), policy_hash=policy_hash)
    if now < deadline:
        return
    payload.update(input_generation=0, completed_generation=0, deadline_at=deadline.isoformat())
    job_id = identity(key, job[3], policy_hash=policy_hash)
    with closing(connect_store(path, timeout=.05)) as db, db:
        db.execute("""INSERT OR IGNORE INTO two_hour_jobs VALUES
            (?,?,?,?,?,?,'EXPIRED',NULL,NULL,0,NULL,?,?)""",
            (job_id, job[1].isoformat(), job[0], str(key[-1]),
             now.isoformat(), deadline.isoformat(), reason, common.canonical(payload)))
