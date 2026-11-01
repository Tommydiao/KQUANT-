# Isolated first-hour candidate; no changes to installed runtime.
"""Coalesced CPU/read-only history lane fed by the existing minute owner."""
from __future__ import annotations

import threading
import os
from contextlib import contextmanager, nullcontext
from collections import Counter, OrderedDict
from datetime import UTC, datetime, timedelta
from time import monotonic, thread_time
from weakref import WeakSet

from kquant import options_one_minute as common
from kquant import options_opening_trend as trend
from kquant import options_opening_trend_store as store
from kquant.market_clock import session_bounds_utc
from kquant.options_opening_trend_history import HistoryCache
import first_hour_journal as journal
from first_hour import WINDOW_END_MINUTES
from generation_reads import read_scope

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
        from kquant import options_opening_momentum, options_price_reference, options_opening_trend_approval
        from kquant import options_opening_trend_reference
        from method_snapshot import source_reader
        options_opening_trend_reference._reviewed_file = source_reader(
            options_opening_trend_reference._reviewed_file)
        options_opening_momentum.load_policy()
        self.minute_path, self.path, self.hub = minute_path, path, hub
        self.clock = clock or (lambda: datetime.now(UTC))
        self.on_recheck = on_recheck
        self.source_root, self.source_reviews_path = source_root, source_reviews_path
        from pathlib import Path
        from kquant.options_opening_trend_reference import ROOT
        from kquant.options_price_action_source import fact_data_root
        self.bound_fact_root = fact_data_root(Path(source_root or ROOT))
        self.bound_path_environment = self._path_environment()
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
        self.prepared_generations = {}
        from prepared_minutes import MinutePreparation
        self.minute_preparation = MinutePreparation()
        self.state = {"state": "SHADOW_RESEARCH", "completed": 0, "coalesced": 0,
                      "qualified_publication_enabled": False}
        store.initialize(path)
        journal.initialize(path)
        from kquant.options_data_paths import connect_store
        # Keep WAL open for this lane. Last-connection close otherwise checkpoints
        # each short journal transaction, contending with the next writer.
        self.wal_anchor = connect_store(path, timeout=.1) if path.is_file() else None
        if self.wal_anchor is not None:
            self.wal_anchor.execute("PRAGMA query_only=ON")
            self.wal_anchor.execute("SELECT job_id FROM two_hour_jobs LIMIT 1").fetchone()
        try:
            self.pending.update(journal.restore(path, self.clock()))
            self.checkpoints.update(self.pending)
            for job in self.pending.values():
                self.latest_inputs.setdefault(job[:2], job)
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
        if not opening + timedelta(minutes=5) <= now < opening + timedelta(minutes=WINDOW_END_MINUTES):
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
            self.prepared_generations = {k: v for k, v in self.prepared_generations.items()
                                         if k[1] == day.isoformat() and now < v.deadline}
            previous = self.latest_inputs.get((symbol, day))
            # A bar-only notification carries no new reference. Keep the same
            # scope's original evidence and timestamps; explicit failure replaces it.
            if reference is None and previous and previous[3] == scope_hash:
                reference = previous[4]
            self.latest_inputs[(symbol, day)] = (symbol, day, list(bars), scope_hash, dict(reference or {}))
            self.input_epochs[(symbol, day)] = self.input_epochs.get((symbol, day), 0) + 1
            for strategy in ("opening_momentum", "opening_trend"):
                if strategy == "opening_trend" and not comparison:
                    continue
                key = strategy, day.isoformat(), symbol, slot
                self.timings.setdefault(key, {}).setdefault("enqueue_monotonic", monotonic())
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
        if now >= opening + timedelta(minutes=WINDOW_END_MINUTES):
            self.state['checkpoint_recovery'] = 'ENTRY_WINDOW_CLOSED_NO_BACKFILL'
            return
        for row in registered:
            if row.get("identity_status") == "verified":
                opening, _ = session_bounds_utc(day)
                elapsed = int((self.clock() - opening).total_seconds() // 300)
                for slot in range(1, min(elapsed, 12)):
                    key = "opening_momentum", day.isoformat(), row["symbol"], slot
                    journal.record_missed(self.path, key, (row["symbol"], day, [], scope_hash, {}), self.clock())
                self.enqueue(row["symbol"], day, [], scope_hash)

    def tick_registered(self, registered, day, scope_hash, now):
        """Existing worker clock admits every due position, even without a first bar."""
        opening,_=session_bounds_utc(day)
        signature=(day.isoformat(),scope_hash)
        cursor=(signature,int((now-opening).total_seconds()//300))
        if signature in self.clock_registry and getattr(self,'clock_registry_cursor',None)==cursor:
            return
        policy=journal.load_policy()
        cutoff=opening+timedelta(minutes=policy["entry_window_minutes"])
        if signature not in self.clock_registry and now<cutoff:
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
                for slot in (minute // 5 for minute in policy["checkpoint_minutes"]):
                    key=('opening_momentum',day.isoformat(),row['symbol'],slot)
                    end=opening+timedelta(minutes=slot*5)
                    deadline=min(end+timedelta(seconds=300),cutoff)
                    if now>=deadline:
                        self.waiting.pop(key,None)
                        self.prepared_generations.pop(key,None)
                        continue
                    if now<end or key in self.clock_admitted:
                        continue
                    job=self.latest_inputs[(row['symbol'],day)]
                    self.checkpoints.setdefault(key,job)
                    self.incoming.setdefault(key,job)
                    self.timings.setdefault(key,{}).setdefault('enqueue_monotonic',monotonic())
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
            # Publication invalidates inputs; it must not replace a newer native
            # quote with a reference built outside this lock from an older job.
            # Admission rebuilds from durable facts before the next handoff.
            self.input_epochs[(symbol, day)] = self.input_epochs.get((symbol, day), 0) + 1
            self._wake_original_locked(symbol, day)
            self.lock.notify_all()
            return True

    def _wake_original_locked(self, symbol, day):
        job = self.latest_inputs.get((symbol, day))
        originals = {**getattr(self, "checkpoints", {}), **self.waiting}
        opening, _ = session_bounds_utc(day)
        # The window is defined by this adapter, not an on-disk policy lookup.
        # Never perform filesystem I/O while holding the lane condition lock.
        cutoff=opening+timedelta(minutes=WINDOW_END_MINUTES)
        for key, original in list(originals.items()):
            if key[1:3] != (day.isoformat(), symbol):
                continue
            if (key[0] == "opening_trend" and getattr(self, "state", {}).get("strategies", {})
                    .get("opening_trend", {}).get("state") == "UNAVAILABLE"):
                continue
            # READY preserves the old slot/deadline, including when expiring it.
            deadline=min(opening+timedelta(minutes=(key[-1]+1)*5),cutoff)
            if self.clock()>=deadline:
                self.waiting.pop(key,None)
                self.prepared_generations.pop(key,None)
                continue
            if key[0] == "opening_momentum" and (key in self.waiting or self.clock() < deadline):
                self.incoming[key] = job or original
            elif self.clock() < deadline:
                self.pending[key] = job or original
            self.waiting.pop(key, None)

    def _checkpoint_inputs(self, key, job, now, reviews=None, *, rebuild_reference=True,
                           produce_decisions=False):
        """Read durable versions for the original slot, never from SDK or a later slot."""
        from kquant.bounded_sqlite import read_connection
        from kquant.options_minute_decisions import read as read_decisions
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
        native = symbol, day, [self.minute_preparation.prepare(row[0]) for row in versions], scope, reference
        from prepared_generation import rows_token
        self.input_read_context.minute_token = rows_token(versions)
        from kquant.options_opening_trend_reference import load_reviews
        from first_hour_minute_decisions import resolve
        reviews = self._source_reviews() if reviews is None else reviews
        interface = reviews.get("previous_close_interface")
        if (rebuild_reference and isinstance(interface, dict)
                and interface.get("contract_version") == "INTERFACE_FACT_V1"):
            from kquant.options_price_reference import build as build_price
            from kquant.options_intraday_comparison import independent_reference
            extra = {"root": self.source_root} if self.source_root is not None else {}
            reference_started = monotonic()
            reference = independent_reference(reference, build_price, symbol=symbol, session=day.isoformat(),
                                              now=now, reviews=reviews, **extra)
            self.timings.setdefault(key, {})["cross_day_reference_seconds"] = monotonic() - reference_started
            native = (*native[:4], reference)
        method = reviews.get("canonical_resolution_method")
        decisions = []
        if method:
            resolution_started = monotonic()
            extra = {"root": self.source_root} if self.source_root is not None else {}
            # Admission is the sole producer. Compute checks exact durable tokens
            # before reusing the assembled immutable generation.
            produced = getattr(context, 'decisions_produced_until', {}).get(key)
            if produce_decisions and not (produced and produced[0] <= now < produced[1]):
                resolve(self.path, native[2], symbol=symbol, session=day.isoformat(),
                        now=now, proof=method, **extra)
            self.timings.setdefault(key, {})["canonical_resolution_seconds"] = monotonic() - resolution_started
        from first_hour_minute_decisions import read_with_token
        persisted, token = read_with_token(self.path, symbol=symbol, session=day.isoformat(), now=now)
        decisions = persisted if method else []
        self.input_read_context.decision_token = token
        return native, decisions

    @contextmanager
    def _input_batch(self, enabled=True, *, entries=None, reviews=None):
        if not enabled:
            yield
            return
        from kquant.bounded_sqlite import read_connection
        if entries is not None:
            if len(entries) > LANE_BATCH_BOUND:
                raise ValueError("CHECKPOINT_INPUT_BATCH_BOUND_EXCEEDED")
            started = monotonic()
            with read_connection(self.minute_path, seconds=.3) as db:
                captured = {key: self._read_versions(db, key, job) for key, job in entries}
            # Close the SQL budget before hashing source files or writing decisions.
            # These captured versions are scoped only to this input generation.
            self.input_read_context.versions = captured
            self.input_read_context.decisions_produced_until = {}
            elapsed = monotonic() - started
            for key, _ in entries:
                self.timings.setdefault(key, {})["input_batch_read_seconds"] = elapsed
            try:
                from method_snapshot import calculation_scope
                from generation_reads import read_scope
                with calculation_scope(), read_scope(phase_checked=True):
                    method = reviews.get('canonical_resolution_method') if reviews is not None else None
                    if method and all(len(rows) <= 2000 for rows in captured.values()):
                        from first_hour_minute_decisions import resolve_batch
                        from prepared_generation import next_boundary, method_authority
                        from kquant.options_opening_trend_reference import ROOT
                        root = self.source_root or ROOT
                        at = self.clock()
                        started = monotonic()
                        native = {key: [self.minute_preparation.prepare(row[0]) for row in captured[key]]
                                  for key, _ in entries}
                        requests = [(native[key], job[0], job[1].isoformat(), at) for key, job in entries]
                        if resolve_batch(self.path, requests, proof=method, root=root):
                            authority = method_authority(method, root)
                            for key, job in entries:
                                opening, closing = session_bounds_utc(job[1])
                                deadline = min(opening+timedelta(minutes=(key[-1]+1)*5),
                                               opening+timedelta(minutes=WINDOW_END_MINUTES), closing)
                                self.input_read_context.decisions_produced_until[key] = (at, next_boundary(
                                    (native[key], method, authority), at, deadline))
                        for key, _ in entries:
                            self.timings.setdefault(key, {})['input_batch_decision_seconds'] = monotonic()-started
                    yield
            finally:
                self.input_read_context.versions = None
                self.input_read_context.decisions_produced_until = {}
                self.state['immutable_minute_preparation'] = self.minute_preparation.snapshot()
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
            ORDER BY received_at,payload_json LIMIT 2001""", (day.isoformat(), symbol,
            opening.isoformat(), (opening + timedelta(minutes=key[-1] * 5)).isoformat())).fetchall()

    @staticmethod
    def _clock_epoch():
        from kquant.options_clock_measurement import snapshot
        value = snapshot()  # In-memory measurement owner; no NTP/SDK/system query.
        return common.digest({k: value.get(k) for k in ('state', 'source_hash',
            'checked_at', 'precision_verified', 'uncertainty_ms')})

    def _method_state(self, reviews, now):
        from first_hour_minute_decisions import _method
        from kquant.options_opening_trend_reference import ROOT
        proof = reviews.get('canonical_resolution_method')
        return common.digest(_method(proof, now=now, root=self.source_root or ROOT) if proof else None)

    @staticmethod
    def _path_environment():
        return tuple(os.environ.get(name, '') for name in (
            'KQUANT_RUNTIME_DATA_ROOT', 'KQUANT_RUNTIME_PATH_BINDING',
            'KQUANT_RUNTIME_PATH_BINDING_SHA256'))

    def _check_path_binding(self):
        from prepared_generation import GenerationChanged, file_token
        if self._path_environment() != self.bound_path_environment:
            raise GenerationChanged('RUNTIME_PATH_BINDING_ENVIRONMENT_CHANGED')
        _, path, expected = self.bound_path_environment
        if path and file_token(path) != expected:
            raise GenerationChanged('RUNTIME_PATH_BINDING_BYTES_CHANGED')
        return path

    def _prepare_generation(self, key, job, epoch, reviews, policy_pair):
        from method_snapshot import source_usage
        with source_usage():
            return self._prepare_generation_inputs(key, job, epoch, reviews, policy_pair)

    def _prepare_generation_inputs(self, key, job, epoch, reviews, policy_pair):
        from first_hour import prepare_inputs, s0
        from prepared_generation import build, source_files, method_authority, GenerationChanged, price_fact_token
        from kquant.options_opening_trend_reference import ROOT
        from pathlib import Path
        from method_snapshot import observed_source_paths
        stage_started = monotonic()
        phase_times = {}
        def mark(stage):
            nonlocal stage_started
            ended = monotonic()
            phase_times['prepare_' + stage + '_seconds'] = ended-stage_started
            stage_started = ended
        now = self.clock()
        root = Path(self.source_root or ROOT)
        source_path = self.source_reviews_path
        if source_path is None:
            from kquant.options_opening_trend_reference import REVIEW
            source_path = REVIEW
        # Paths were fully validated during construction. Binding identity is
        # still checked at admission and final CAS; no live root switching.
        binding_path = self._check_path_binding()
        fact = self.bound_fact_root / 'work/option_foundation/price-action-facts' / job[0] / (job[1].isoformat()+'.json')
        method = reviews.get('canonical_resolution_method')
        before = source_files(root, (method, job[4]),
            extra=(source_path, fact, s0.CONFIG, *((binding_path,) if binding_path else ())), scoped=True)
        mark('files_before')
        facts_before = price_fact_token(self.path, job[0], job[1].isoformat(), now)
        mark('facts_before')
        clock_epoch = self._clock_epoch()
        job, decisions = self._checkpoint_inputs(key, job, now, reviews,
                                                 rebuild_reference=True, produce_decisions=True)
        mark('checkpoint')
        opening, closing = session_bounds_utc(job[1])
        # Complete the reference fallback here too; compute never assembles it again.
        if job[4].get('contract_version') not in {'PRICE_REFERENCE_V3', 'PRICE_REFERENCE_BUILD_UNAVAILABLE'}:
            from kquant.options_price_reference import build as price_build
            history, _ = self.history.get(job[0], job[1], now)
            try:
                ref = price_build(job[4].get('raw_quote', {}), symbol=job[0], session=job[1].isoformat(),
                    now=now, reviews=reviews, prior_close_bar=history.get('prior_close_bar'), root=root)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                ref = {'contract_version': 'PRICE_REFERENCE_BUILD_UNAVAILABLE',
                    'raw_quote': job[4].get('raw_quote', {}),
                    'reference_blockers': ['PRICE_REFERENCE_ASSEMBLY_UNAVAILABLE'],
                    'assembly_error_type': type(exc).__name__}
            job = (*job[:4], ref)
        mark('reference_fallback')
        minute_inputs = prepare_inputs(symbol=job[0], bars=job[2], opening=opening,
            checkpoint=opening+timedelta(minutes=key[-1]*5), now=now, source_decisions=decisions)
        mark('aggregate')
        after = source_files(root, (method, job[4], decisions),
                             extra=(source_path, fact, *(p for p, _ in before), *observed_source_paths()), scoped=True)
        if any(dict(after).get(path) != token for path, token in before):
            raise GenerationChanged('SOURCE_CHANGED_DURING_PREPARATION')
        mark('files_after')
        if price_fact_token(self.path, job[0], job[1].isoformat(), now) != facts_before:
            raise GenerationChanged('PRICE_FACT_CHANGED_DURING_PREPARATION')
        mark('facts_after')
        generation = build(key=key, job=job, decisions=decisions, minute_inputs=minute_inputs,
            reviews=reviews, policy_pair=policy_pair, epoch=epoch,
            minute_token=self.input_read_context.minute_token,
            decision_token=self.input_read_context.decision_token, fact_token=facts_before, files=after,
            clock_epoch=clock_epoch, method_state=self._method_state(reviews, now), now=now,
            deadline=min(opening+timedelta(minutes=key[-1]*5, seconds=300),
                         opening+timedelta(minutes=WINDOW_END_MINUTES), closing),
            authority=method_authority(method, root),
            fingerprint=journal.input_fingerprint(job, decisions))
        mark('identity')
        self.timings.setdefault(key, {}).update(phase_times)
        self.state['generation_preparations'] = self.state.get('generation_preparations', 0)+1
        return generation

    def _validate_generation(self, generation, *, reviews, policy_pair):
        from prepared_generation import rows_token, GenerationChanged, price_fact_token
        from first_hour_minute_decisions import read_rows
        from generation_reads import read_connection
        key, job = generation.key, generation.job
        self._check_path_binding()
        now = self.clock()
        with read_connection(self.minute_path, seconds=.3) as db:
            versions = self._read_versions(db, key, job)
        if len(versions) > 2000:
            raise GenerationChanged('MINUTE_VERSION_READ_BOUND_EXCEEDED')
        decisions = read_rows(self.path, symbol=job[0], session=job[1].isoformat(), now=now)
        with self.lock:
            epoch = self.input_epochs.get(job[:2], 0)
        generation.check(now=now, epoch=epoch, clock_epoch=self._clock_epoch(),
            minute_token=rows_token(versions), decision_token=rows_token(decisions),
            fact_token=price_fact_token(self.path, job[0], job[1].isoformat(), now),
            reviews=reviews, policy_pair=policy_pair, method_state=self._method_state(reviews, now), scoped=True)
        self.state['generation_boundary_checks'] = self.state.get('generation_boundary_checks', 0)+1

    def _write_ready(self):
        import sqlite3
        while True:
            with self.lock:
                self.lock.wait_for(lambda: self.incoming or self.stopped)
                if self.stopped:
                    return
                batch = [self.incoming.popitem(last=False) for _ in range(min(LANE_BATCH_BOUND, len(self.incoming)))]
                self.admitting.update(key for key, _ in batch)
                epochs = {key: self.input_epochs.get(job[:2], 0) for key, job in batch}
            try:
                from first_hour import policies
                reviews = self._source_reviews()
                policy_pair = policies()
                entries, generations = [], []
                with self._input_batch(entries=batch, reviews=reviews):
                    for key, job in batch:
                        with self.lock:
                            if self.input_epochs.get(job[:2], 0) != epochs[key]:
                                self.state['admission_superseded_before_prepare'] = self.state.get(
                                    'admission_superseded_before_prepare', 0)+1
                                self._readmit_current(key, job)
                                continue
                        try:
                            started = monotonic()
                            cpu_started = thread_time()
                            timing = self.timings.setdefault(key, {})
                            timing['admission_queue_seconds'] = (started-timing['enqueue_monotonic']
                                if 'enqueue_monotonic' in timing else None)
                            generation = self._prepare_generation(key, job, epochs[key], reviews, policy_pair)
                            timing['generation_preparation_seconds'] = monotonic()-started
                            timing['generation_preparation_cpu_seconds'] = thread_time()-cpu_started
                            entries.append((key, generation.job, self.clock(), generation.fingerprint))
                            generations.append(generation)
                        except (sqlite3.Error, OSError, TimeoutError, ValueError) as exc:
                            self._retry_admission([(key, job)], exc)
                if not entries:
                    continue
                ready_requested = monotonic()
                with self._journal_guard():
                    ready_acquired = monotonic()
                    admitted = journal.ready_many(self.path, entries, return_leases=True)
                ready_finished = monotonic()
                for key, _, _, _ in entries:
                    self.timings.setdefault(key, {}).update(
                        admission_journal_wait_seconds=ready_acquired-ready_requested,
                        admission_journal_seconds=ready_finished-ready_acquired)
                with self.lock:
                    for (key, job, _, _), generation, accepted in zip(entries, generations, admitted):
                        if accepted:
                            if self.input_epochs.get(job[:2], 0) != generation.input_epoch:
                                self._readmit_current(key, job)
                                continue
                            self.prepared_generations[key] = generation.admitted(accepted)
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
                                      opening + timedelta(minutes=WINDOW_END_MINUTES)):
                    self.incoming.setdefault(key, self.latest_inputs.get((job[0], job[1]), job))
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
        from kquant.options_opening_trend_prewarm import history_context
        return history_context(symbol, day, self.minute_path, now)

    def _source_reviews(self):
        from kquant.options_opening_trend_reference import load_reviews
        from prepared_minutes import PreparedSources
        value = load_reviews(self.source_reviews_path) if self.source_reviews_path is not None else load_reviews()
        return PreparedSources(value)

    def _readmit_current(self, key, previous):
        with self.lock:
            # Keep the original slot, but never replay a stale quote captured
            # before a newer source/minute notification completed.
            current = self.latest_inputs.get((previous[0], previous[1]), previous)
            opening, _ = session_bounds_utc(previous[1])
            if self.clock() >= min(opening+timedelta(minutes=(key[-1]+1)*5),
                                   opening+timedelta(minutes=WINDOW_END_MINUTES)):
                self.prepared_generations.pop(key, None)
                return
            self.incoming.setdefault(key, current)
            self.state['input_readmissions'] = self.state.get('input_readmissions', 0) + 1
            self.lock.notify_all()

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
                handoffs = {}
                for key in keys:
                    job = self.pending.pop(key)
                    timing = self.timings.setdefault(key, {})
                    selected_at = monotonic()
                    timing['compute_queue_seconds'] = (selected_at-timing['durable_admission_monotonic']
                        if 'durable_admission_monotonic' in timing else None)
                    batch.append((key, job, self.input_epochs.get((job[0], job[1]), 0)))
                    handoffs[key] = self.prepared_generations.pop(key, None)
            prepared, momentum = [], []
            try:
                from first_hour import policies
                from method_snapshot import calculation_scope
                reviews, policy_pair = self._source_reviews(), policies()
                with calculation_scope(), read_scope(phase_checked=True):
                    for key, job, epoch in batch:
                        try:
                            now = self.clock()
                            decisions = []
                            if key[0] == 'opening_momentum':
                                generation = handoffs[key]
                                if generation is None:
                                    self._readmit_current(key, job)
                                    continue
                                started = monotonic()
                                cpu_started = thread_time()
                                self._validate_generation(generation, reviews=reviews, policy_pair=policy_pair)
                                job, decisions, epoch = generation.job, generation.decisions, generation.input_epoch
                                self.timings.setdefault(key, {})['generation_validation_seconds'] = monotonic()-started
                                self.timings[key]['generation_validation_cpu_seconds'] = thread_time()-cpu_started
                                momentum.append((key, job, now, generation.fingerprint))
                                self.state['generation_handoffs'] = self.state.get('generation_handoffs', 0)+1
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
                if key[0] == "opening_momentum" and (lease is None or
                        lease.generation != handoffs[key].input_generation):
                    # Durable bars may have changed before the callback or crash.
                    # Re-admit this original slot; unchanged COMPLETED is a no-op.
                    if lease is not None:
                        from prepared_generation import GenerationChanged
                        self._retry(key, job, GenerationChanged('LEASE_GENERATION_CHANGED'), lease=lease)
                    else:
                        self._readmit_current(key, job)
                    continue
                try:
                    if lease is not None:
                        lease.valid_before = handoffs[key].valid_before
                        lease.boundary_guard = lambda g=handoffs[key]: self._clock_epoch() == g.clock_epoch
                    compute_started = monotonic()
                    rows, history_state, model = self._calculate(key, job, now, decisions, lease, reviews,
                        policy_pair=policy_pair, generation=handoffs.get(key))
                    self.timings.setdefault(key, {})["calculation_seconds"] = monotonic() - compute_started
                    computed.append((key, job, epoch, now, lease, rows, history_state, model))
                except Exception as exc:
                    self._retry(key, job, exc, lease=lease)
            if not computed:
                continue
            try:
                from kquant.options_input_commit_fence import commit_fence
                prepared_commits = [(lease, any(row["state"] == "INCOMPLETE" for row in rows),
                    store.prepare_evaluations(rows)) for _, _, _, _, lease, rows, _, _ in computed]
                commit_started = monotonic()
                commit_cpu_started = thread_time()
                with commit_fence():
                    fence_acquired = monotonic()
                    # Re-read after acquisition. File validation holds neither the
                    # SQL transaction nor lane condition; producers cannot commit.
                    current_reviews, current_policy = self._source_reviews(), policies()
                    valid_indices = []
                    # End the scope (including fresh byte checks) before any
                    # journal transaction can commit the shared preparation.
                    with calculation_scope(), read_scope(phase_checked=True):
                        for i, item in enumerate(computed):
                            try:
                                generation = handoffs.get(item[0])
                                if generation is not None:
                                    self._validate_generation(generation, reviews=current_reviews,
                                                              policy_pair=current_policy)
                                valid_indices.append(i)
                            except Exception as exc:
                                self.state['generation_invalidations'] = self.state.get('generation_invalidations', 0)+1
                                self.state['generation_invalidation_reason'] = str(exc)
                    validation_finished = monotonic()
                    with self._journal_guard():
                        with self.lock:
                            indices = [i for i in valid_indices
                                       if self.input_epochs.get(computed[i][1][:2], 0) == computed[i][2]]
                            accepted = journal.finish_many(self.path,
                                [prepared_commits[i] for i in indices], now=self.clock)
                            outcomes = [False] * len(computed)
                            for i, result in zip(indices, accepted):
                                outcomes[i] = result
                committed_at = monotonic()
                commit_seconds = committed_at - commit_started
                commit_phases = dict(commit_fence_wait_seconds=fence_acquired-commit_started,
                    commit_validation_seconds=validation_finished-fence_acquired,
                    commit_journal_seconds=committed_at-validation_finished,
                    commit_batch_cpu_seconds=thread_time()-commit_cpu_started)
            except Exception as exc:
                for key, job, _, _, lease, _, _, _ in computed:
                    self._retry(key, job, exc, lease=lease)
                continue
            availability_started = monotonic()
            try:
                from kquant.options_research_availability import record_many
                with self._journal_guard():
                    record_many(self.path, [row for item, accepted in zip(computed, outcomes) if accepted
                        for row in item[5]], observed_at=self.clock())
                self.state.pop("research_availability_error", None)
            except Exception as exc:
                # Results already committed; do not retry or rewrite their availability.
                self.state["research_availability_error"] = type(exc).__name__
            availability_seconds = monotonic() - availability_started
            history_snapshot_started = monotonic()
            history_snapshot = self.history.snapshot()
            history_snapshot_seconds = monotonic() - history_snapshot_started
            for (key, job, epoch, now, result_lease, results, history_state, model), committed in zip(computed, outcomes):
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
                    try:
                        with self._journal_guard():
                            journal.release(self.path, result_lease, self.clock())
                        self._readmit_current(key, job)
                    except Exception as exc:
                        self.state['generation_release_error'] = type(exc).__name__
                    self.state["stale_generations_discarded"] = self.state.get("stale_generations_discarded", 0) + 1
                    continue
                if waiting:
                    if history_state.get("state") != "READY" and self.history.get(symbol, day, self.clock())[1].get("state") == "READY":
                        self._history_ready(symbol, day)
                self.persist_retries.pop(key, None)
                self.state.update(completed=self.state["completed"] + 2, last_evaluation_at=now.isoformat(),
                                  last_symbol=symbol, error=None, history_cache=history_snapshot)
                self.state.setdefault("strategies", {}).setdefault(strategy, {}).update(
                                  last_evaluation_at=now.isoformat(), last_symbol=symbol, policy_id=results[0]["policy_id"])
                self.hub.publish({"type": "options_one_minute_progress", "research_strategy": strategy,
                                  "symbol": symbol, "bar_end": (opening + timedelta(minutes=key[-1] * 5)).isoformat(),
                                  "at": now.isoformat(), "qualified_signal": False,
                                  "input_generation": getattr(result_lease, 'generation', None),
                                  "committed_evaluations": [
                                      {name: value.get(name) for name in ('evaluation_id', 'policy_id', 'variant',
                                          'right', 'state', 'original_enqueued_at', 'timeliness_policy')}
                                      for row in results for value in
                                      ([row, row['strategy_comparison']['s1']]
                                          if row.get('strategy_comparison') else [row])],
                                  "runtime_timing": {**{name: value for name, value in self.timings.get(key, {}).items()
                                      if name.endswith("_seconds")}, "commit_batch_seconds": commit_seconds,
                                      **commit_phases,
                                      "availability_record_seconds": availability_seconds,
                                      "history_snapshot_batch_seconds": history_snapshot_seconds,
                                      "enqueue_to_durable_commit_seconds": (committed_at-self.timings[key]['enqueue_monotonic']
                                          if 'enqueue_monotonic' in self.timings.get(key,{}) else None),
                                      "enqueue_to_commit_seconds": (monotonic()-self.timings[key]['enqueue_monotonic']
                                          if 'enqueue_monotonic' in self.timings.get(key,{}) else None)}})

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

    def _calculate(self, key, job, now, source_decisions, journal_id, reviews, *, policy_pair=None,
                   generation=None):
        symbol, day, bars, scope, reference = job
        opening, closing = session_bounds_utc(day)
        history, history_state = self.history.get(symbol, day, now)
        from kquant.options_opening_trend_reference import build
        if key[0] == "opening_momentum":
            from kquant.options_price_reference import build as price_build
            extra = {"root": self.source_root} if self.source_root is not None else {}
            # A handoff already contains the reference. Direct/offline callers
            # retain the original fallback; the model's reference checks stay live.
            if generation is None and reference.get("contract_version") not in {"PRICE_REFERENCE_V3", "PRICE_REFERENCE_BUILD_UNAVAILABLE"}:
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
            import first_hour as model
            extras.update(checkpoint=opening + timedelta(minutes=slot * 5), source_decisions=source_decisions)
        arguments = dict(symbol=symbol, bars=bars, history=history, reference=reference,
                         opening=opening, closing=closing, now=now, scope_hash=scope, **extras)
        if strategy == "opening_momentum":
            from first_hour import evaluate_comparison_pair
            results = evaluate_comparison_pair(**arguments, _policy_pair=policy_pair,
                _minute_inputs=generation.minute_inputs if generation is not None else None)
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
            if generation is not None:
                result['runtime_inputs']['prepared_generation'] = {
                    'prepared_at': generation.prepared_at.isoformat(),
                    'valid_before': generation.valid_before.isoformat(),
                    'minute_version': generation.minute_token,
                    'decision_version': generation.decision_token,
                    'clock_epoch': generation.clock_epoch,
                    'method_state': generation.method_state,
                    'original_deadline': generation.deadline.isoformat(),
                    'role': 'IMMUTABLE_ADMISSION_HANDOFF_NOT_RESULT_CACHE'}
            result["computed_at"] = self.clock().isoformat()
            comparison = result.get("strategy_comparison")
            if comparison:
                result['timeliness_policy'] = 'ORIGINAL_DURABLE_ENQUEUE_30S_V1'
                result['original_enqueued_at'] = getattr(journal_id, 'original_enqueued_at', None)
                comparison["s1"]["runtime_inputs"] = dict(result["runtime_inputs"])
                comparison["s1"]["computed_at"] = result["computed_at"]
                comparison['s1']['timeliness_policy'] = result['timeliness_policy']
                comparison['s1']['original_enqueued_at'] = result['original_enqueued_at']
                comparison["s1"]["evaluation_id"] = common.digest([
                    comparison["s1"]["evaluation_id"], result["runtime_inputs"].get("input_fingerprint")])
            if journal_id and result["state"] == "NUMERIC_PASS":
                result["evaluation_id"] = common.digest([result["evaluation_id"], journal_id.fingerprint])
            if comparison:
                comparison["s1"]["parent_evaluation_id"] = result["evaluation_id"]
                comparison["s0"]["evaluation_id"] = result["evaluation_id"]
        return results, history_state, model

    def _retry(self, key, job, exc, *, lease=None):
        import sqlite3
        from method_snapshot import SourceSnapshotChanged
        from prepared_generation import GenerationChanged
        self.state.update(error=type(exc).__name__, last_failed_symbol=job[0],
                          last_failed_checkpoint=key[-1], last_failed_strategy=key[0])
        if lease is not None:
            try:
                with self._journal_guard():
                    journal.release(self.path, lease, self.clock())
            except Exception as release_error:
                self.state['generation_release_error'] = type(release_error).__name__
        if isinstance(exc, GenerationChanged):
            self.state['generation_invalidations'] = self.state.get('generation_invalidations', 0)+1
            self.state['generation_invalidation_reason'] = str(exc)
            self._readmit_current(key, job)
            return
        if isinstance(exc, (sqlite3.OperationalError, TimeoutError, SourceSnapshotChanged)):
            attempts = self.persist_retries.get(key, 0) + 1
            self.persist_retries[key] = attempts
            opening, _ = session_bounds_utc(job[1])
            deadline = min(opening + timedelta(minutes=(key[-1] + 1) * 5), opening + timedelta(minutes=WINDOW_END_MINUTES))
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
