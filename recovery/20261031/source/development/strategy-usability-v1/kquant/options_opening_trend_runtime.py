"""Coalesced CPU/read-only history lane fed by the existing minute owner."""
from __future__ import annotations

import threading
from contextlib import contextmanager, nullcontext
from collections import Counter, OrderedDict
from datetime import UTC, datetime, timedelta
from time import monotonic
from weakref import WeakSet

from . import options_one_minute as common
from . import options_opening_trend as trend
from . import options_opening_trend_store as store
from .market_clock import session_bounds_utc
from .options_opening_trend_history import HistoryCache
from . import options_opening_momentum_journal as journal

_source_listeners = WeakSet()
_source_listeners_lock = threading.Lock()
# Each admitted direction now persists an S0 parent and an S1 child. Keep the
# write transaction's row budget near the original lane rather than doubling it.
LANE_BATCH_BOUND = 8


def notify_price_sources(symbols, session):
    from datetime import date
    with _source_listeners_lock:
        listeners = list(_source_listeners)
    result = {"woken": 0, "errors": []}
    for listener in listeners:
        for symbol in symbols:
            try:
                result["woken"] += int(listener.source_facts_ready(symbol, date.fromisoformat(session)))
            except Exception as exc:
                result["errors"].append({"symbol": symbol, "error_type": type(exc).__name__})
    return result


class TrendLane:
    def __init__(self, minute_path, hub, *, path=store.STORE, clock=None, on_recheck=None,
                 source_root=None, source_reviews_path=None):
        # Load deterministic rule/approval modules before the first market batch;
        # this does not fetch data, accept a policy, or acquire a qualification.
        from . import options_opening_momentum, options_price_reference, options_opening_trend_approval
        options_opening_momentum.load_policy()
        self.minute_path, self.path, self.hub = minute_path, path, hub
        self.clock = clock or (lambda: datetime.now(UTC))
        self.on_recheck = on_recheck
        self.source_root, self.source_reviews_path = source_root, source_reviews_path
        self.rechecked = set()
        self.pending = OrderedDict()
        self.incoming = OrderedDict()
        self.admitting = set()
        self.waiting = {}
        self.lock = threading.Condition()
        self.stopped = False
        self.latest_inputs = {}
        self.input_epochs = {}
        self.checkpoints = {}
        self.reference_checks = {}
        self.clock_registry = set()
        self.clock_admitted = set()
        self.comparison_policy_check = None
        self.persist_retries = {}
        self.timings = {}
        self.journal_lock = threading.Lock()
        self.input_read_context = threading.local()
        self.state = {"state": "SHADOW_RESEARCH", "completed": 0, "coalesced": 0,
                      "qualified_publication_enabled": False}
        store.initialize(path)
        journal.initialize(path)
        from .options_data_paths import connect_store
        # Keep WAL open for this lane. Last-connection close otherwise checkpoints
        # each short journal transaction, contending with the next writer.
        self.wal_anchor = connect_store(path, timeout=.1) if path.is_file() else None
        if self.wal_anchor is not None:
            self.wal_anchor.execute("PRAGMA query_only=ON")
            self.wal_anchor.execute("SELECT job_id FROM two_hour_jobs LIMIT 1").fetchone()
        try:
            self.pending.update(journal.restore(path, self.clock()))
            self.state["restored_checkpoints"] = len(self.pending)
        except Exception as exc:
            self.state["restore_error"] = type(exc).__name__
        self.history = HistoryCache(self._history, clock=self.clock, on_ready=self._history_ready)
        self.writer = threading.Thread(target=self._write_ready, name="opening-checkpoint-journal", daemon=True)
        self.writer.start()
        self.thread = threading.Thread(target=self._run, name="opening-trend-research", daemon=True)
        self.thread.start()
        with _source_listeners_lock:
            _source_listeners.add(self)

    def enqueue(self, symbol, day, bars, scope_hash, reference=None):
        now = self.clock()
        opening, _ = session_bounds_utc(day)
        if not opening + timedelta(minutes=5) <= now < opening + timedelta(minutes=30):
            return
        slot = int((now - opening).total_seconds() // 300)
        comparison = self._comparison_available(now) if slot >= 3 else False
        with self.lock:
            if not hasattr(self, "input_epochs"):
                self.input_epochs = {}
            if not hasattr(self, "checkpoints"):
                self.checkpoints = {}
            self.latest_inputs = {k: v for k, v in self.latest_inputs.items() if k[1] == day}
            self.checkpoints = {k: v for k, v in self.checkpoints.items() if k[1] == day.isoformat()}
            self.latest_inputs[(symbol, day)] = (symbol, day, list(bars), scope_hash, dict(reference or {}))
            self.input_epochs[(symbol, day)] = self.input_epochs.get((symbol, day), 0) + 1
            for strategy in ("opening_momentum", "opening_trend"):
                if strategy == "opening_trend" and not comparison:
                    continue
                key = strategy, day.isoformat(), symbol, slot
                self.timings.setdefault(key, {"enqueue_monotonic": monotonic()})
                if key in self.pending or key in self.incoming:
                    self.state["coalesced"] += 1
                target = self.incoming if strategy == "opening_momentum" else self.pending
                target[key] = self.latest_inputs[(symbol, day)]
                self.checkpoints[key] = self.latest_inputs[(symbol, day)]
            self._wake_original_locked(symbol, day)
            self.state["volatile_pending"] = len(self.incoming)
            self.lock.notify_all()
        self.history.request(symbol, day, urgent=True)

    def _comparison_available(self, now):
        # A missing comparison policy is a diagnosed exclusion, not work for
        # the active calculation lane. Re-stat every time so recovery is visible.
        try:
            info = trend.CONFIG.stat()
            version = str(trend.CONFIG.absolute()), info.st_mtime_ns, info.st_ctime_ns, info.st_size
            if getattr(self, "comparison_policy_check", None) != version:
                trend.load_policy()
                self.comparison_policy_check = version
            diagnostic = {"state": "READY", "policy_id": trend.POLICY_ID}
            ready = True
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.comparison_policy_check = None
            diagnostic = {"state": "UNAVAILABLE", "policy_id": trend.POLICY_ID,
                "reason": "POLICY_CONFIG_MISSING" if isinstance(exc, FileNotFoundError) else "POLICY_CONFIG_INVALID",
                "error_type": type(exc).__name__}
            ready = False
        with self.lock:
            self.state.setdefault("strategies", {}).setdefault("opening_trend", {}).update(
                **diagnostic, checked_at=now.isoformat())
        return ready

    def warm_history(self, symbols, day):
        for symbol in symbols:
            self.history.request(symbol, day)
        self.state["history_cache"] = self.history.snapshot()

    def recover_registered(self, registered, day, scope_hash):
        """Rebuild only the still-live checkpoint after a pre-journal crash.

        The registered session and persisted raw bars, not volatile enqueue ACKs,
        define the bounded recovery plan. Missing inputs remain WAIT_INPUT.
        """
        if len(registered) > 111:
            raise ValueError("REGISTERED_RECOVERY_BOUND_EXCEEDED")
        now = self.clock()
        self.tick_registered(registered,day,scope_hash,now)
        opening, _ = session_bounds_utc(day)
        if now >= opening + timedelta(minutes=30):
            self.state['checkpoint_recovery'] = 'ENTRY_WINDOW_CLOSED_NO_BACKFILL'
            return
        for row in registered:
            if row.get("identity_status") == "verified":
                opening, _ = session_bounds_utc(day)
                elapsed = int((self.clock() - opening).total_seconds() // 300)
                for slot in range(1, min(elapsed, 6)):
                    key = "opening_momentum", day.isoformat(), row["symbol"], slot
                    journal.record_missed(self.path, key, (row["symbol"], day, [], scope_hash, {}), self.clock())
                self.enqueue(row["symbol"], day, [], scope_hash)

    def tick_registered(self, registered, day, scope_hash, now):
        """Existing worker clock admits every due position, even without a first bar."""
        opening,_=session_bounds_utc(day)
        signature=(day.isoformat(),scope_hash)
        if signature not in self.clock_registry and now<opening+timedelta(minutes=30):
            with self._journal_guard():
                self.state['checkpoint_registry']=journal.register_clock_positions(
                    self.path,registered,day,scope_hash,now)
            with self.lock:
                for row in registered:
                    if row.get('identity_status')=='verified':
                        self.latest_inputs.setdefault((row['symbol'],day),(row['symbol'],day,[],scope_hash,{}))
            self.clock_registry.add(signature)
        cursor=(signature,int((now-opening).total_seconds()//300))
        if getattr(self,'clock_registry_cursor',None)==cursor:
            return
        with self._journal_guard():
            self.state['checkpoint_clock']=journal.advance_clock_positions(
                self.path,registered,day,scope_hash,now)
        self.clock_registry_cursor=cursor
        with self.lock:
            for row in registered:
                if row.get('identity_status')!='verified':
                    continue
                for slot in range(1,6):
                    key=('opening_momentum',day.isoformat(),row['symbol'],slot)
                    end=opening+timedelta(minutes=slot*5)
                    deadline=min(end+timedelta(seconds=300),opening+timedelta(minutes=30))
                    if now>=deadline:
                        self.waiting.pop(key,None)
                        continue
                    if now<end or key in self.clock_admitted:
                        continue
                    job=self.latest_inputs[(row['symbol'],day)]
                    self.checkpoints.setdefault(key,job)
                    self.incoming.setdefault(key,job)
                    self.timings.setdefault(key,{'enqueue_monotonic':monotonic()})
                    self.clock_admitted.add(key)
            self.lock.notify_all()

    def _history_ready(self, symbol, day):
        with self.lock:
            if not self.stopped:
                self.input_epochs[(symbol, day)] = self.input_epochs.get((symbol, day), 0) + 1
                self._wake_original_locked(symbol, day)
                self.lock.notify_all()

    def reference_ready(self, symbol, day, reference):
        with self.lock:
            job = self.latest_inputs.get((symbol, day))
            if job and not self.stopped:
                self.latest_inputs[(symbol, day)] = (*job[:4], reference)
                if not hasattr(self, "input_epochs"):
                    self.input_epochs = {}
                self.input_epochs[(symbol, day)] = self.input_epochs.get((symbol, day), 0) + 1
                self._wake_original_locked(symbol, day)
                self.lock.notify_all()

    def source_facts_ready(self, symbol, day):
        with self.lock:
            job = self.latest_inputs.get((symbol, day))
            if not job or self.stopped:
                return False
        from .options_price_reference import build
        extra = {"root": self.source_root} if self.source_root is not None else {}
        value = build(job[4].get("raw_quote", {}), symbol=symbol, session=day.isoformat(),
                      now=self.clock(), reviews=self._source_reviews(), **extra)
        self.reference_ready(symbol, day, value)
        return True

    def _wake_original_locked(self, symbol, day):
        job = self.latest_inputs.get((symbol, day))
        originals = {**getattr(self, "checkpoints", {}), **self.waiting}
        for key, original in list(originals.items()):
            if key[1:3] != (day.isoformat(), symbol):
                continue
            if (key[0] == "opening_trend" and getattr(self, "state", {}).get("strategies", {})
                    .get("opening_trend", {}).get("state") == "UNAVAILABLE"):
                continue
            # READY preserves the old slot/deadline, including when expiring it.
            opening, _ = session_bounds_utc(day)
            deadline=min(opening+timedelta(minutes=(key[-1]+1)*5),opening+timedelta(minutes=30))
            if self.clock()>=deadline:
                self.waiting.pop(key,None)
                continue
            if key[0] == "opening_momentum" and (key in self.waiting or self.clock() < min(
                    opening + timedelta(minutes=(key[-1] + 1) * 5), opening + timedelta(minutes=30))):
                self.incoming[key] = job or original
            elif self.clock() < min(opening + timedelta(minutes=(key[-1] + 1) * 5), opening + timedelta(minutes=30)):
                self.pending[key] = job or original
            self.waiting.pop(key, None)

    def _checkpoint_inputs(self, key, job, now, reviews=None, *, rebuild_reference=True):
        """Read durable versions for the original slot, never from SDK or a later slot."""
        from .bounded_sqlite import read_connection
        from .options_minute_decisions import read as read_decisions
        import json
        symbol, day, _, scope, reference = job
        opening, _ = session_bounds_utc(day)
        context = getattr(self, "input_read_context", None)
        captured = getattr(context, "versions", None)
        if captured is not None and key in captured:
            versions = captured[key]
        else:
            active = getattr(context, "connection", None)
            with (nullcontext(active) if active is not None else read_connection(self.minute_path, seconds=.3)) as db:
                versions = self._read_versions(db, key, job)
        if len(versions) > 2000:
            raise ValueError("MINUTE_VERSION_READ_BOUND_EXCEEDED")
        native = symbol, day, [json.loads(row[0]) for row in versions], scope, reference
        from .options_opening_trend_reference import load_reviews
        from .options_minute_decisions import resolve
        reviews = self._source_reviews() if reviews is None else reviews
        interface = reviews.get("previous_close_interface")
        if (rebuild_reference and isinstance(interface, dict)
                and interface.get("contract_version") == "INTERFACE_FACT_V1"):
            from .options_price_reference import build as build_price
            extra = {"root": self.source_root} if self.source_root is not None else {}
            reference = build_price(reference.get("raw_quote", {}), symbol=symbol, session=day.isoformat(),
                                    now=now, reviews=reviews, **extra)
            native = (*native[:4], reference)
        method = reviews.get("canonical_resolution_method")
        decisions = []
        if method:
            extra = {"root": self.source_root} if self.source_root is not None else {}
            resolve(self.path, native[2], symbol=symbol, session=day.isoformat(), now=now, proof=method, **extra)
            decisions = read_decisions(self.path, symbol=symbol, session=day.isoformat(), now=now)
        return native, decisions

    @contextmanager
    def _input_batch(self, enabled=True, *, entries=None):
        if not enabled:
            yield
            return
        from .bounded_sqlite import read_connection
        if entries is not None:
            if len(entries) > LANE_BATCH_BOUND:
                raise ValueError("CHECKPOINT_INPUT_BATCH_BOUND_EXCEEDED")
            started = monotonic()
            with read_connection(self.minute_path, seconds=.3) as db:
                captured = {key: self._read_versions(db, key, job) for key, job in entries}
            # Close the SQL budget before hashing source files or writing decisions.
            # These captured versions are scoped only to this input generation.
            self.input_read_context.versions = captured
            elapsed = monotonic() - started
            for key, _ in entries:
                self.timings.setdefault(key, {})["input_batch_read_seconds"] = elapsed
            try:
                yield
            finally:
                self.input_read_context.versions = None
            return
        # Reuse a connection, not an input snapshot or a previous generation.
        # The entire bounded batch keeps the original 300ms read budget.
        with read_connection(self.minute_path, seconds=.3) as db:
            self.input_read_context.connection = db
            try:
                yield
            finally:
                self.input_read_context.connection = None

    @staticmethod
    def _read_versions(db, key, job):
        symbol, day = job[:2]
        opening, _ = session_bounds_utc(day)
        return db.execute("""SELECT payload_json FROM one_minute_bars
            WHERE session=? AND symbol=? AND open_at>=? AND open_at<?
            ORDER BY received_at LIMIT 2001""", (day.isoformat(), symbol,
            opening.isoformat(), (opening + timedelta(minutes=key[-1] * 5)).isoformat())).fetchall()

    def _write_ready(self):
        import sqlite3
        while True:
            with self.lock:
                self.lock.wait_for(lambda: self.incoming or self.stopped)
                if self.stopped:
                    return
                batch = [self.incoming.popitem(last=False) for _ in range(min(LANE_BATCH_BOUND, len(self.incoming)))]
                self.admitting.update(key for key, _ in batch)
            try:
                from .options_opening_trend_reference import load_reviews
                reviews = self._source_reviews()
                entries = []
                with self._input_batch(entries=batch):
                    for key, job in batch:
                        try:
                            # Persist the captured input first. The compute read
                            # rebuilds current facts, re-admitting any new fingerprint.
                            job, decisions = self._checkpoint_inputs(key, job, self.clock(), reviews,
                                                                     rebuild_reference=False)
                            entries.append((key, job, self.clock(), journal.input_fingerprint(job, decisions)))
                        except (sqlite3.Error, OSError, TimeoutError, ValueError) as exc:
                            self._retry_admission([(key, job)], exc)
                if not entries:
                    continue
                with self._journal_guard():
                    admitted = journal.ready_many(self.path, entries)
                with self.lock:
                    for (key, job, _, _), accepted in zip(entries, admitted):
                        if accepted:
                            self.timings.setdefault(key, {})["durable_admission_monotonic"] = monotonic()
                            self.pending[key] = job
                            self.state["durable_queued"] = self.state.get("durable_queued", 0) + 1
                    if admitted and all(admitted):
                        self.state.pop("journal_error", None)
                    self.state["volatile_pending"] = len(self.incoming)
                    self.lock.notify_all()
            except (sqlite3.Error, OSError, TimeoutError, ValueError) as exc:
                self._retry_admission(batch, exc)
            finally:
                with self.lock:
                    self.admitting.difference_update(key for key, _ in batch)
                    self.lock.notify_all()

    def _retry_admission(self, batch, exc):
        expired = []
        with self.lock:
            for key, job in batch:
                opening, _ = session_bounds_utc(job[1])
                if self.clock() < min(opening + timedelta(minutes=(key[-1] + 1) * 5),
                                      opening + timedelta(minutes=30)):
                    self.incoming.setdefault(key, job)
                else:
                    expired.append((key, job))
                    self.state["expired_admission_errors"] = self.state.get("expired_admission_errors", 0) + 1
            self.state["journal_error"] = type(exc).__name__
            self.lock.wait(timeout=.05)
        for key, job in expired:
            try:
                journal.record_missed(self.path, key, job, self.clock(), reason="INPUT_ADMISSION_FAILED")
            except Exception as error:
                self.state["expired_admission_archive_error"] = type(error).__name__

    def _history(self, symbol, day, now):
        from .options_opening_trend_prewarm import history_context
        return history_context(symbol, day, self.minute_path, now)

    def _source_reviews(self):
        from .options_opening_trend_reference import load_reviews
        return load_reviews(self.source_reviews_path) if self.source_reviews_path is not None else load_reviews()

    def _run(self):
        while True:
            with self.lock:
                self.lock.wait_for(lambda: self.pending or self.stopped)
                if self.stopped:
                    return
                # The old comparison strategy must not occupy a CPU batch while
                # the active S0 checkpoint is still being durably admitted.
                active = [key for key in self.pending if key[0] == "opening_momentum"]
                if not active and (self.incoming or self.admitting) and not self.state.get("journal_error"):
                    self.lock.wait(timeout=.05)
                    continue
                # Commit completed results promptly instead of holding an entire
                # 64-job transaction batch while all source proofs are checked.
                keys = sorted(active or self.pending, key=lambda key: key[-1])[:LANE_BATCH_BOUND]
                batch = []
                for key in keys:
                    job = self.pending.pop(key)
                    batch.append((key, job, self.input_epochs.get((job[0], job[1]), 0)))
            from .options_opening_trend_reference import load_reviews
            reviews = self._source_reviews()
            prepared, momentum = [], []
            try:
                inputs = [(key, job) for key, job, _ in batch if key[0] == "opening_momentum"]
                with self._input_batch(bool(inputs), entries=inputs):
                    for key, job, epoch in batch:
                        try:
                            now = self.clock()
                            decisions = []
                            if key[0] == "opening_momentum":
                                input_started = monotonic()
                                job, decisions = self._checkpoint_inputs(key, job, now, reviews)
                                self.timings.setdefault(key, {})["input_read_seconds"] = monotonic() - input_started
                                momentum.append((key, job, now, journal.input_fingerprint(job, decisions)))
                            prepared.append((key, job, epoch, now, decisions))
                        except Exception as exc:
                            self._retry(key, job, exc)
            except Exception as exc:
                for key, job, _ in batch:
                    self._retry(key, job, exc)
                continue
            try:
                with self._journal_guard():
                    leases = iter(journal.begin_many(self.path, momentum)) if momentum else iter(())
            except Exception as exc:
                for key, job, _, _, _ in prepared:
                    self._retry(key, job, exc)
                continue
            computed = []
            for key, job, epoch, now, decisions in prepared:
                lease = next(leases) if key[0] == "opening_momentum" else None
                if key[0] == "opening_momentum" and lease is None:
                    # Durable bars may have changed before the callback or crash.
                    # Re-admit this original slot; unchanged COMPLETED is a no-op.
                    with self.lock:
                        self.incoming.setdefault(key, job)
                        self.lock.notify_all()
                    continue
                try:
                    compute_started = monotonic()
                    rows, history_state, model = self._calculate(key, job, now, decisions, lease, reviews)
                    self.timings.setdefault(key, {})["calculation_seconds"] = monotonic() - compute_started
                    computed.append((key, job, epoch, now, lease, rows, history_state, model))
                except Exception as exc:
                    self._retry(key, job, exc)
            if not computed:
                continue
            try:
                prepared_commits = [(lease, any(row["state"] == "INCOMPLETE" for row in rows),
                    store.prepare_evaluations(rows)) for _, _, _, _, lease, rows, _, _ in computed]
                commit_started = monotonic()
                with self._journal_guard():
                    outcomes = journal.finish_many(self.path, prepared_commits)
                commit_seconds = monotonic() - commit_started
            except Exception as exc:
                for key, job, _, _, _, _, _, _ in computed:
                    self._retry(key, job, exc)
                continue
            availability_started = monotonic()
            try:
                from .options_research_availability import record_many
                with self._journal_guard():
                    record_many(self.path, [row for item, accepted in zip(computed, outcomes) if accepted
                        for row in item[5]], observed_at=self.clock())
                self.state.pop("research_availability_error", None)
            except Exception as exc:
                # Results already committed; do not retry or rewrite their availability.
                self.state["research_availability_error"] = type(exc).__name__
            availability_seconds = monotonic() - availability_started
            for (key, job, epoch, now, _, results, history_state, model), committed in zip(computed, outcomes):
                symbol, day = job[:2]
                strategy = key[0]
                opening, _ = session_bounds_utc(day)
                waiting = any(row["state"] == "INCOMPLETE" for row in results)
                with self.lock:
                    if waiting and committed:
                        self.waiting[key] = job
                    # Register WAIT_INPUT before checking the epoch. A callback
                    # between compute and registration therefore cannot be lost.
                    if not committed or self.input_epochs.get((symbol, day), 0) != epoch:
                        self.waiting[key] = job
                        self._wake_original_locked(symbol, day)
                        self.lock.notify_all()
                if not committed:
                    self.state["stale_generations_discarded"] = self.state.get("stale_generations_discarded", 0) + 1
                    continue
                if waiting:
                    if history_state.get("state") != "READY" and self.history.get(symbol, day, self.clock())[1].get("state") == "READY":
                        self._history_ready(symbol, day)
                self.persist_retries.pop(key, None)
                self.state.update(completed=self.state["completed"] + 2, last_evaluation_at=now.isoformat(),
                                  last_symbol=symbol, error=None, history_cache=self.history.snapshot())
                self.state.setdefault("strategies", {}).setdefault(strategy, {}).update(
                    last_evaluation_at=now.isoformat(), last_symbol=symbol, policy_id=model.load_policy()["policy_id"])
                self.hub.publish({"type": "options_one_minute_progress", "research_strategy": strategy,
                                  "symbol": symbol, "bar_end": (opening + timedelta(minutes=key[-1] * 5)).isoformat(),
                                  "at": now.isoformat(), "qualified_signal": False,
                                  "runtime_timing": {**{name: value for name, value in self.timings.get(key, {}).items()
                                      if name.endswith("_seconds")}, "commit_batch_seconds": commit_seconds,
                                      "availability_record_seconds": availability_seconds,
                                      "enqueue_to_commit_seconds": monotonic() - self.timings.get(key, {}).get("enqueue_monotonic", monotonic())}})

    @contextmanager
    def _journal_guard(self):
        lock = getattr(self, "journal_lock", None)
        if lock is None:
            yield
            return
        requested = monotonic()
        if not lock.acquire(timeout=.3):
            self.state["journal_lock_last_timeout"] = {"wait_seconds": monotonic() - requested,
                "thread": threading.current_thread().name, "observed_at": self.clock().isoformat()}
            raise TimeoutError("CHECKPOINT_INTERNAL_WRITER_BUSY")
        acquired = monotonic()
        try:
            yield
        finally:
            self.state["journal_lock_last_hold_seconds"] = monotonic() - acquired
            self.state["journal_lock_last_wait_seconds"] = acquired - requested
            lock.release()

    def _calculate(self, key, job, now, source_decisions, journal_id, reviews):
        symbol, day, bars, scope, reference = job
        opening, closing = session_bounds_utc(day)
        history, history_state = self.history.get(symbol, day, now)
        from .options_opening_trend_reference import build
        if key[0] == "opening_momentum":
            from .options_price_reference import build as price_build
            extra = {"root": self.source_root} if self.source_root is not None else {}
            # The current durable-input read already assembled V3. The model
            # revalidates its original source bytes before evaluating both rights.
            if reference.get("contract_version") != "PRICE_REFERENCE_V3":
                try:
                    reference = price_build(reference.get("raw_quote", {}), symbol=symbol, session=day.isoformat(),
                        now=now, reviews=reviews, prior_close_bar=history.get("prior_close_bar"), **extra)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    reference = {"raw_quote": reference.get("raw_quote", {}),
                        "reference_blockers": ["PRICE_REFERENCE_ASSEMBLY_UNAVAILABLE"],
                        "assembly_error_type": type(exc).__name__}
        else:
            reference = build(reference.get("raw_quote", {}), symbol=symbol, session=day.isoformat(),
                              now=now, reviews=reviews, prior_close_bar=history.get("prior_close_bar"))
        strategy, _, _, slot = key
        model, extras = trend, {}
        if strategy == "opening_momentum":
            from . import options_opening_momentum as model
            extras.update(checkpoint=opening + timedelta(minutes=slot * 5), source_decisions=source_decisions)
        arguments = dict(symbol=symbol, bars=bars, history=history, reference=reference,
                         opening=opening, closing=closing, now=now, scope_hash=scope, **extras)
        if strategy == "opening_momentum":
            from .options_intraday_comparison import evaluate_comparison_pair
            results = evaluate_comparison_pair(**arguments)
        else:
            results = [model.evaluate(right=right, **arguments) for right in ("CALL", "PUT")]
        reasons = list(reference.get("reference_blockers", ["REFERENCE_ASSEMBLY_UNAVAILABLE"]))
        if strategy == "opening_momentum":
            checked = results[0].get("input_checks", {}).get("reference", {})
            if checked.get("state") != "VERIFIED":
                reasons = checked.get("reasons") or ["PRICE_REFERENCE_UNVERIFIED"]
        self.reference_checks = {key: value for key, value in self.reference_checks.items() if key[1] == day}
        self.reference_checks[(symbol, day)] = reasons
        self.state["assembled_reference"] = {
            "session": day.isoformat(), "checked_symbols": len(self.reference_checks),
            "verified_symbols": sum(not reasons for reasons in self.reference_checks.values()),
            "blockers": dict(Counter(reason for reasons in self.reference_checks.values() for reason in reasons)),
            "checked_at": now.isoformat(), "view": "LATEST_PER_SYMBOL_NOT_CHECKPOINT_COVERAGE"}
        recheck_key = symbol, day, slot
        if (strategy == "opening_momentum" and self.on_recheck and recheck_key not in self.rechecked
                and any(r["state"] == "INCOMPLETE" or "FIRST_MINUTE_SOURCE_RECHECK_REQUIRED" in r.get("warnings", []) for r in results)):
            try:
                self.on_recheck(symbol, day, extras["checkpoint"])
                self.rechecked.add(recheck_key)
            except Exception as exc:
                # A failed recovery request must not discard the completed input verdict.
                self.state["source_recheck_error"] = {"symbol": symbol, "checkpoint": slot,
                    "error_type": type(exc).__name__, "at": self.clock().isoformat()}
        for result in results:
            result["runtime_inputs"] = {"history_cache": history_state,
                "input_generation": getattr(journal_id, "generation", None),
                "input_fingerprint": getattr(journal_id, "fingerprint", None)}
            result["computed_at"] = self.clock().isoformat()
            comparison = result.get("strategy_comparison")
            if comparison:
                comparison["s1"]["runtime_inputs"] = dict(result["runtime_inputs"])
                comparison["s1"]["computed_at"] = result["computed_at"]
                comparison["s1"]["evaluation_id"] = common.digest([
                    comparison["s1"]["evaluation_id"], result["runtime_inputs"].get("input_fingerprint")])
            if journal_id and result["state"] == "NUMERIC_PASS":
                result["evaluation_id"] = common.digest([result["evaluation_id"], journal_id.fingerprint])
            if comparison:
                comparison["s1"]["parent_evaluation_id"] = result["evaluation_id"]
                comparison["s0"]["evaluation_id"] = result["evaluation_id"]
        return results, history_state, model

    def _retry(self, key, job, exc):
        import sqlite3
        self.state.update(error=type(exc).__name__, last_failed_symbol=job[0],
                          last_failed_checkpoint=key[-1], last_failed_strategy=key[0])
        if isinstance(exc, (sqlite3.OperationalError, TimeoutError)):
            attempts = self.persist_retries.get(key, 0) + 1
            self.persist_retries[key] = attempts
            opening, _ = session_bounds_utc(job[1])
            deadline = min(opening + timedelta(minutes=(key[-1] + 1) * 5), opening + timedelta(minutes=30))
            if self.clock() < deadline:
                with self.lock:
                    self.pending.setdefault(key, job)
                    self.state["checkpoint_retries"] = self.state.get("checkpoint_retries", 0) + 1
                    self.lock.wait(timeout=min(.5, .05 * attempts))
            else:
                self.state["unpersisted_checkpoints"] = self.state.get("unpersisted_checkpoints", 0) + 1

    def close(self):
        with _source_listeners_lock:
            _source_listeners.discard(self)
        with self.lock:
            self.stopped = True
            self.lock.notify_all()
        self.writer.join(timeout=2)
        self.thread.join(timeout=2)
        self.history.close()
        if self.wal_anchor is not None:
            self.wal_anchor.close()
