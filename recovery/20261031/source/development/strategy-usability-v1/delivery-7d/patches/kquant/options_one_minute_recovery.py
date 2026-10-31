"""Bounded asynchronous bar recovery using the existing durable research queue."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
import json
import sqlite3
import queue
import threading

from . import options_one_minute as rules
from . import options_two_hour as jobs
from .market_clock import session_bounds_utc
from .options_data_paths import connect_store

KIND = "ONE_MINUTE_BAR_RECOVERY"


class RecoveryLane:
    def __init__(self, evidence_path, recover, *, queue_path=None, clock=None, kind=KIND, owner=None):
        from .options_data_paths import queue_store
        queue_path = queue_store(queue_path)
        self.evidence_path, self.queue_path, self.recover = evidence_path, queue_path, recover
        self.clock = clock or (lambda: datetime.now(UTC))
        self.kind = kind
        self.owner = owner or "foundation-minute-bar-recovery"
        self.io = ThreadPoolExecutor(max_workers=1, thread_name_prefix="minute-recovery-journal")
        self.provider = ThreadPoolExecutor(max_workers=1, thread_name_prefix="minute-bar-recovery")
        self.pending = {}
        self.io_future = self.provider_future = self.job = None
        self.completion = None
        self.restore_day = None
        self.next_at = datetime.min.replace(tzinfo=UTC)
        self.state = {"state": "STARTING", "queued_in_memory": 0}
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.pump = None
        self.context = None
        self.deliveries = queue.SimpleQueue()

    def start(self):
        if self.pump is not None:
            return
        self.pump = threading.Thread(target=self._pump, name="minute-recovery-dispatch", daemon=True)
        self.pump.start()

    def _pump(self):
        while not self.stop.wait(0.02):
            with self.lock:
                if self.context is None:
                    continue
                try:
                    result = self._tick(*self.context)
                    if result is not None:
                        self.deliveries.put(result)
                except Exception as exc:
                    self.state.update(state="DISPATCH_UNAVAILABLE", reason=type(exc).__name__)

    @staticmethod
    def task(symbol, opened, bars, policy, scope_hash):
        opening, closing = session_bounds_utc(opened.astimezone(rules.NY).date())
        required = min(max(0, int((opened - opening).total_seconds() // 60)), policy["prior_intraday_bars_max"])
        missing = []
        for offset in range(required, -1, -1):
            target = opened - timedelta(minutes=offset)
            bar = bars.get(target)
            if bar is None or rules.timestamp(bar["received_at"]) < target + timedelta(minutes=1):
                missing.append(target.isoformat())
        if not missing:
            return None
        deadline = min(opened + timedelta(minutes=1, seconds=policy["signal_deadline_seconds"]),
                       closing - timedelta(minutes=policy["entry_cutoff_minutes_before_close"]))
        return {"kind": KIND, "symbol": symbol, "session": opened.astimezone(rules.NY).date().isoformat(),
                "dependent_bar": opened.isoformat(), "missing_bars": missing,
                "deadline_at": deadline.isoformat(), "policy_hash": policy["policy_hash"], "scope_hash": scope_hash}

    def observe(self, symbol, opened, bars, policy, scope_hash):
        task = self.task(symbol, opened, bars, policy, scope_hash)
        if task:
            # Identity depends on the dependent bar, never on the latest retry or missing subset.
            key = rules.digest([self.kind, symbol, task["dependent_bar"], task["policy_hash"], scope_hash])
            with self.lock:
                self.pending[key] = task

    def bar_ready(self, symbol, target, bar):
        if not bar or bar.get("symbol") != symbol:
            return False
        try:
            return rules.timestamp(bar["received_at"]) >= target + timedelta(minutes=1)
        except (KeyError, TypeError, ValueError):
            return False

    def _restore(self, day, policy, scope_hash):
        now = self.clock()
        with sqlite3.connect(f"file:{self.evidence_path.resolve().as_posix()}?mode=ro", uri=True, timeout=0.05) as connection:
            rows = connection.execute("SELECT payload_json FROM one_minute_bars WHERE session=? ORDER BY received_at", (day,)).fetchall()
        symbols = {}
        for raw, in rows:
            bar = json.loads(raw)
            symbols.setdefault(bar["symbol"], {})[rules.timestamp(bar["open_at"])] = bar
        tasks = {}
        for symbol, bars in symbols.items():
            for opened in bars:
                if now - timedelta(seconds=90) <= opened <= now:
                    task = self.task(symbol, opened, bars, policy, scope_hash)
                    if task:
                        key = rules.digest([self.kind, symbol, task["dependent_bar"], task["policy_hash"], scope_hash])
                        tasks[key] = task
        return tasks

    def _cycle(self, pending, completion, day, policy, scope_hash, restore):
        now = self.clock()
        stamp = now.isoformat()
        if restore:
            pending = {**self._restore(day, policy, scope_hash), **pending}
        delivered = None
        # Save evidence before acknowledging the task; a crash can only cause an idempotent replay.
        if completion:
            job, result = completion
            payload = job["payload"]
            bars = []
            for bar in result.get("bars", [result["bar"]] if result.get("bar") else []):
                opened = rules.timestamp(bar["open_at"])
                received = rules.timestamp(bar["received_at"])
                requested = rules.timestamp(bar.get("request_started_at", bar["received_at"]))
                if (bar.get("symbol") == job["symbol"] and bar.get("interval") == "1m"
                        and opened.astimezone(rules.NY).date().isoformat() == job["session"]
                        and opened + timedelta(minutes=1) <= requested <= received <= now):
                    bars.append(bar)
            rules.save_bars(bars, job["session"], self.evidence_path)
            delivered = {"job": job, "bars": bars, "completed_at": stamp, "status": result["status"]}
            # Never hold the shared queue write lock while reading a second database.
            stored = rules.stored_bars(job["symbol"], job["session"], self.evidence_path)
            ready = all(self.bar_ready(job["symbol"], rules.timestamp(value),
                                      stored.get(rules.timestamp(value)))
                        for value in job["payload"]["missing_bars"])
        now = self.clock()
        stamp = now.isoformat()
        with closing(connect_store(self.queue_path, timeout=0.05)) as connection, connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            for key, task in pending.items():
                connection.execute("INSERT OR IGNORE INTO two_hour_jobs VALUES (?,?,?,?,?,?,'PENDING',NULL,NULL,0,NULL,NULL,?)",
                    (key, task["session"], task["symbol"], task["dependent_bar"], stamp, task["deadline_at"], rules.canonical(task)))
            if completion:
                job, result = completion
                expired = now >= rules.timestamp(job["deadline_at"])
                state = "MISSED_EVALUATION_WINDOW" if expired else "DONE" if ready else "PENDING"
                connection.execute("""UPDATE two_hour_jobs SET state=?,reason=?,retry_at=?,lease_owner=NULL,lease_until=NULL
                    WHERE job_id=? AND state='LEASED' AND lease_owner=?""",
                    (state, "ORIGINAL_DEADLINE_EXCEEDED" if expired else None if ready else result["status"],
                     None if ready or expired else (now + timedelta(seconds=2)).isoformat(),
                     job["job_id"], self.owner))
            connection.execute("""UPDATE two_hour_jobs SET state='MISSED_EVALUATION_WINDOW',reason='ORIGINAL_DEADLINE_EXCEEDED'
                WHERE state IN ('PENDING','LEASED') AND julianday(deadline_at)<=julianday(?) AND json_extract(payload_json,'$.kind')=?""", (stamp, self.kind))
            row = connection.execute("""SELECT j.* FROM two_hour_jobs j WHERE session=? AND julianday(deadline_at)>julianday(?)
                AND json_extract(payload_json,'$.kind')=? AND json_extract(payload_json,'$.policy_hash')=?
                AND json_extract(payload_json,'$.scope_hash')=? AND
                julianday(json_extract(payload_json,'$.dependent_bar'), '+1 minute')<=julianday(?) AND
                ((state='PENDING' AND (retry_at IS NULL OR julianday(retry_at)<=julianday(?))) OR (state='LEASED' AND julianday(lease_until)<=julianday(?)))
                ORDER BY COALESCE(json_extract(payload_json,'$.priority'),1),attempts, julianday(deadline_at),julianday(queued_at),symbol LIMIT 1""",
                (day, stamp, self.kind, policy["policy_hash"], scope_hash, stamp, stamp, stamp)).fetchone()
            selected = None
            if row:
                until = min(rules.timestamp(row["deadline_at"]), now + timedelta(seconds=6)).isoformat()
                connection.execute("UPDATE two_hour_jobs SET state='LEASED',lease_owner=?,lease_until=?,attempts=attempts+1 WHERE job_id=?",
                                   (self.owner, until, row["job_id"]))
                selected = {**dict(row), "payload": json.loads(row["payload_json"]), "lease_until": until}
        return selected, delivered

    def _fetch(self, job):
        now = self.clock()
        if now >= rules.timestamp(job["deadline_at"]):
            return {"status": "ORIGINAL_DEADLINE_EXCEEDED"}
        bars = rules.stored_bars(job["symbol"], job["session"], self.evidence_path)
        missing = [rules.timestamp(value) for value in job["payload"]["missing_bars"]
                   if not self.bar_ready(job["symbol"], rules.timestamp(value),
                                         bars.get(rules.timestamp(value)))]
        if not missing:
            # Another dependent task's shared snapshot already supplied these bars.
            return {"status": "RECOVERED", "bars": [bars[rules.timestamp(value)] for value in job["payload"]["missing_bars"]]}
        try:
            return self.recover(job["symbol"], max(missing))
        except Exception as exc:
            from .options_one_minute_data import classify_failure
            return {"status": classify_failure(exc)}

    def tick(self, day, policy, scope_hash):
        with self.lock:
            if self.pump is None:
                return self._tick(day, policy, scope_hash)
            self.context = day, policy, scope_hash
            try:
                return self.deliveries.get_nowait()
            except queue.Empty:
                return None

    def _tick(self, day, policy, scope_hash):
        now = self.clock()
        delivered = None
        if self.provider_future and self.provider_future.done():
            try:
                result = self.provider_future.result()
            except Exception as exc:
                result = {"status": type(exc).__name__}
            self.completion = self.job, result
            self.provider_future = self.job = None
        if self.io_future and self.io_future.done():
            batch, completion, restoring = self.io_future.context
            try:
                job, delivered = self.io_future.result()
                if restoring:
                    self.restore_day = day
                self.completion = None
                if job:
                    self.job = job
                    self.provider_future = self.provider.submit(self._fetch, job)
                self.state.update(state="RUNNING", last_journal_at=now.isoformat())
                self.state.pop("reason", None)
            except (sqlite3.Error, OSError) as exc:
                self.pending = {**batch, **self.pending}
                self.completion = completion
                self.next_at = now + timedelta(seconds=0.5)
                self.state.update(state="JOURNAL_UNAVAILABLE", reason=type(exc).__name__)
            finally:
                self.io_future = None
        if not self.io_future and not self.provider_future and now >= self.next_at:
            batch, self.pending = self.pending, {}
            restore = self.restore_day != day
            self.io_future = self.io.submit(self._cycle, batch, self.completion, day, policy, scope_hash, restore)
            self.io_future.context = batch, self.completion, restore
            self.next_at = now + timedelta(seconds=0.1)
        self.state.update(queued_in_memory=len(self.pending), provider_inflight=bool(self.provider_future))
        return delivered

    def close(self):
        self.stop.set()
        if self.pump is not None:
            self.pump.join(timeout=2)
        self.io.shutdown(wait=False, cancel_futures=True)
        self.provider.shutdown(wait=False, cancel_futures=True)
