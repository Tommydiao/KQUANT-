"""A dedicated minute qualification lane in the existing durable research queue."""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from copy import deepcopy
import json
import sqlite3
from datetime import timedelta

from . import options_one_minute as rules
from . import options_one_minute_data as data
from . import options_two_hour as jobs
from .options_one_minute_events import event_context
from .options_one_minute_qualification import select_contract, publication_blockers

KIND = "ONE_MINUTE_QUALIFICATION"


def qualify(original, main_db, *, clock=None, contract_provider=None, quote_provider=None):
    from .options_forward_paper import _default_contract_provider
    from .stock_signals import api_stock_quotes_batch
    clock = clock or (lambda: datetime.now(UTC))
    result = deepcopy(original)
    policy = rules.load_policy()
    now = clock()
    qualification = {"status": "NOT_EVALUATED"}
    blockers = []
    try:
        if now >= rules.timestamp(original["deadline_at"]):
            blockers = ["ORIGINAL_DEADLINE_EXCEEDED"]
        else:
            scope_hash = data.universe(main_db)["scope_hash"]
            if policy["policy_hash"] != original["policy_hash"] or scope_hash != original["scope_hash"]:
                blockers = ["POLICY_OR_SCOPE_CHANGED"]
            else:
                result["qualification_event_coverage"] = event_context(
                    main_db, original["symbol"], now=now, policy=policy, scope_hash=scope_hash)
                limits = policy["contracts"]
                provider_policy = {"contract_selection": {
                    "dte_min": min(limits["allowed_calendar_dtes"]),
                    "dte_max": max(limits["allowed_calendar_dtes"]),
                    "allowed_dtes": limits["allowed_calendar_dtes"],
                    "dte_target": limits["preferred_calendar_dtes"][0]}}
                if clock() >= rules.timestamp(original["deadline_at"]):
                    blockers = ["ORIGINAL_DEADLINE_EXCEEDED"]
                else:
                    contracts = (contract_provider or _default_contract_provider)(
                        {**original, "market_session_date": original["session"]},
                        {"underlying_price": original["bar_evidence"]["close"]}, main_db,
                        provider_policy, deadline_at=rules.timestamp(original["deadline_at"]))
                    qualification = select_contract(original, contracts, now=clock(), policy=policy)
                    qualification["evidence"] = contracts
                    if qualification["status"] != "PASS":
                        blockers = ["CONTRACT_NOT_QUALIFIED"]
                    elif clock() >= rules.timestamp(original["deadline_at"]):
                        blockers = ["ORIGINAL_DEADLINE_EXCEEDED"]
                    else:
                        quote = (quote_provider or api_stock_quotes_batch)([original["symbol"]], db_path=main_db)
                        spot = next((row for row in quote.get("items", []) if row.get("symbol") == original["symbol"]), {})
                        now = clock()
                        policy = rules.load_policy()
                        scope_hash = data.universe(main_db)["scope_hash"]
                        event = event_context(main_db, original["symbol"], now=now, policy=policy, scope_hash=scope_hash)
                        result["qualification_event_coverage"] = event
                        # Recheck field ages after all provider and event work.
                        qualification = {**select_contract(original, contracts, now=now, policy=policy), "evidence": contracts}
                        result["underlying_qualification_quote"] = spot
                        blockers = publication_blockers(original, now=now, policy=policy, scope_hash=scope_hash,
                            event=event, selection=qualification, spot=spot.get("last"),
                            spot_received_at=spot.get("received_at") if spot.get("provider_status") == "available" else None)
                if not result.get("qualification_event_coverage", {}).get("trade_eligible"):
                    blockers.append("EVENT_COVERAGE_NOT_ELIGIBLE")
    except Exception as exc:
        qualification = {"status": "UNAVAILABLE", "error_type": type(exc).__name__}
        blockers.append("QUALIFICATION_UNAVAILABLE")
    completed = clock()
    if completed >= rules.timestamp(original["deadline_at"]):
        blockers.append("ORIGINAL_DEADLINE_EXCEEDED")
    result.update(contract_qualification=qualification, qualification_blockers=list(dict.fromkeys(blockers)),
                  parent_evaluation_id=original["evaluation_id"], evaluated_at=completed.isoformat(),
                  runtime_mode="SHADOW_RESEARCH", qualified_signal=False)
    if result.get("qualification_event_coverage"):
        result["event_coverage"] = result["qualification_event_coverage"]
        result["state"] = "NUMERIC_PASS" if result["event_coverage"].get("trade_eligible") else "NUMERIC_PASS_EVENT_PENDING"
    result["reasons"] = result["qualification_blockers"]
    result["evaluation_id"] = rules.digest([original["evaluation_id"], qualification, result["qualification_blockers"], completed.isoformat()])
    return result


class QualificationLane:
    def __init__(self, main_db, evidence_path, *, queue_path=None, clock=None, qualifier=qualify):
        from .options_data_paths import queue_store
        queue_path = queue_store(queue_path)
        self.main_db, self.evidence_path, self.queue_path = main_db, evidence_path, queue_path
        self.clock = clock or (lambda: datetime.now(UTC))
        self.qualifier = qualifier
        self.owner = "foundation-one-minute-qualification"
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="minute-qualification")
        self.io = ThreadPoolExecutor(max_workers=1, thread_name_prefix="minute-qualification-journal")
        self.pending = {}
        self.io_future = None
        self.completion = None
        self.next_journal_at = datetime.min.replace(tzinfo=UTC)
        self.state = {"state": "STARTING"}
        self.future = self.job = None
        self.recovered = False
        self.recovery_future = None

    def _recover(self):
        from .options_one_minute_publication import reconcile_signals
        now = self.clock()
        reconcile_signals(self.evidence_path)
        with sqlite3.connect(f"file:{self.evidence_path.resolve().as_posix()}?mode=ro", uri=True) as connection:
            recent = connection.execute("""SELECT payload_json FROM one_minute_evaluations
                WHERE session=? AND state IN ('NUMERIC_PASS','NUMERIC_PASS_EVENT_PENDING')
                  AND julianday(created_at)>=julianday(?)
                  AND json_extract(payload_json,'$.parent_evaluation_id') IS NULL""",
                (now.astimezone(rules.NY).date().isoformat(), (now - timedelta(seconds=30)).isoformat())).fetchall()
        for raw, in recent:
            self.enqueue(json.loads(raw), self.clock())

    def _execute(self, original):
        from .options_one_minute_publication import claim_candidate, reconcile_signals
        result = self.qualifier(original, self.main_db, clock=self.clock)
        rules.persist_evaluation(result, self.evidence_path)
        if not result.get("qualification_blockers") and result.get("parent_evaluation_id"):
            candidate = claim_candidate(result, main_db=self.main_db, evidence_path=self.evidence_path,
                now=self.clock(), scope_hash=data.universe(self.main_db)["scope_hash"])
            if candidate:
                reconcile_signals(self.evidence_path, event_id=candidate["event_id"])
                result["notification_state"] = "WINDOWS_DEFERRED_PAGE_ONLY"
                result["published_candidate"] = candidate
        return result

    def enqueue(self, original, now):
        if original["state"] not in {"NUMERIC_PASS", "NUMERIC_PASS_EVENT_PENDING"} or now >= rules.timestamp(original["deadline_at"]):
            return None
        self.pending[original["evaluation_id"]] = original
        return original["evaluation_id"]

    def _journal(self, pending, completion, now):
        for original in pending.values():
            jobs.enqueue(session=original["session"], symbol=original["symbol"], slot=original["bar_end"],
                payload={"kind": KIND, "original": original, "evaluation_id": original["evaluation_id"],
                         "policy_hash": original["policy_hash"], "scope_hash": original["scope_hash"]},
                now=now, deadline=rules.timestamp(original["deadline_at"]), path=self.queue_path, timeout=0.05)
        completed = None
        if completion:
            job, completed, error = completion
            if completed:
                rules.persist_evaluation(completed, self.evidence_path)
            jobs.finish(job, owner=self.owner, now=now, reason=error, path=self.queue_path, timeout=0.05)
        job = jobs.claim(owner=self.owner, now=now, path=self.queue_path, kind=KIND, lease_seconds=30, timeout=0.05)
        return job, completed

    def tick(self, now):
        if not self.recovered:
            if self.recovery_future is None:
                self.recovery_future = self.pool.submit(self._recover)
            elif self.recovery_future.done():
                try:
                    self.recovery_future.result()
                    self.recovered = True
                finally:
                    self.recovery_future = None
            return None
        completed = None
        if self.future is not None and self.future.done():
            try:
                self.completion = self.job, self.future.result(), None
            except Exception as exc:
                self.completion = self.job, None, type(exc).__name__
            finally:
                self.future = self.job = None
        if self.io_future and self.io_future.done():
            pending, completion = self.io_future.context
            try:
                self.job, completed = self.io_future.result()
                self.completion = None
                if self.job:
                    self.future = self.pool.submit(self._execute, self.job["payload"]["original"])
                self.state.update(state="RUNNING", last_journal_at=now.isoformat())
                self.state.pop("reason", None)
            except (sqlite3.Error, OSError) as exc:
                self.pending = {**pending, **self.pending}
                self.completion = completion
                self.next_journal_at = now + timedelta(seconds=0.5)
                self.state.update(state="JOURNAL_UNAVAILABLE", reason=type(exc).__name__)
            finally:
                self.io_future = None
        if self.future is None and self.io_future is None and now >= self.next_journal_at:
            pending, self.pending = self.pending, {}
            self.io_future = self.io.submit(self._journal, pending, self.completion, now)
            self.io_future.context = pending, self.completion
            self.next_journal_at = now + timedelta(seconds=0.1)
        return completed

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.io.shutdown(wait=False, cancel_futures=True)
