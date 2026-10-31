"""Background-only research reads and bounded, memory-only HTTP projections."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from threading import Event, Thread
from time import monotonic
from zoneinfo import ZoneInfo
import json

from .status_snapshot import SnapshotUnavailable, StatusSnapshot


class ResearchHttpSnapshots:
    def __init__(self, worker, loader, observer, *, on_complete=None, on_tick=None, clock=None,
                 strategy_availability=None):
        self.worker, self.loader, self.observer = worker, loader, observer
        self.on_tick = on_tick
        self.on_complete = on_complete
        self.strategy_availability = strategy_availability
        self.availability = {}
        self.published = {}
        self.clock = clock or (lambda: datetime.now(UTC))
        # Fewer workers than the previous per-route pools; no SDK in this lane.
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="research-status")
        self.caches = {(strategy, kind): StatusSnapshot(ttl=1 if kind == "current" else 3,
            retain_invalidated=True, executor=self.pool,
            on_complete=None)
            for strategy in ("opening_momentum", "opening_trend") for kind in ("current", "compact")}
        self.observation = StatusSnapshot(ttl=5, retain_invalidated=True)
        self.stop_event = Event()
        self.thread = None
        self.context = None
        self.context_at = None
        self.tick_at = None
        self.error_type = None
        self.event_loop = {"state": "NOT_OBSERVED", "samples": 0}
        self.task_observation = {"state": "NOT_OBSERVED"}

    def start(self):
        if self.thread is None:
            self.thread = Thread(target=self._run, name="research-http-snapshots", daemon=True)
            self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            self.tick()
            self.stop_event.wait(.25)

    def tick(self):
        self.tick_at = datetime.now(UTC).isoformat()
        self.observation.refresh("runtime", self.observer)
        try:
            worker = deepcopy(self.worker())
            day = self.clock().astimezone(ZoneInfo("America/New_York")).date().isoformat()
            scope = worker.get("scope_hash") if worker.get("session") == day else None
            self.context = (day, scope, worker)
            self.context_at = monotonic()
            self.error_type = None
            if self.on_tick:
                self.on_tick(day)
            availability = {}
            for strategy in ("opening_momentum", "opening_trend"):
                try:
                    state = (self.strategy_availability(strategy) if self.strategy_availability else {"enabled": True})
                    if not isinstance(state, dict) or not isinstance(state.get("enabled"), bool):
                        raise ValueError("INVALID_STRATEGY_AVAILABILITY")
                    availability[strategy] = dict(state)
                except Exception as exc:
                    availability[strategy] = {"enabled": False, "reason": "POLICY_AVAILABILITY_UNCONFIRMED",
                                              "error_type": type(exc).__name__}
                if not availability[strategy]["enabled"] and self.availability.get(strategy, {}).get("enabled"):
                    self.invalidate(strategy)
            self.availability = availability
            # Current cards are scheduled before progress summaries.
            for kind in ("current", "compact"):
                for strategy in ("opening_momentum", "opening_trend"):
                    if not availability[strategy]["enabled"]:
                        continue
                    self.caches[strategy, kind].refresh((day, scope),
                        lambda s=strategy, k=kind, w=worker: self.loader(s, k, w))
            # Publish only after collection, and only for a changed business
            # watermark. TTL refreshes are not new market/qualification events.
            notify_strategies = set()
            for (strategy, kind), cache in self.caches.items():
                if not availability[strategy]["enabled"]:
                    continue
                if cache.value is None or cache.cache_key != (day, scope):
                    continue
                value = cache.value
                diagnostics = value.get("worker", {})
                source = diagnostics.get("price_action_sources", {})
                budget = diagnostics.get("source_request_budget", {})
                source_call = diagnostics.get("source_call", {})
                watermark = json.dumps({"error": cache.error,
                    "worker": {key: diagnostics.get(key) for key in ("state", "research_ready", "error_id")},
                    "source": {key: source.get(key) for key in
                        ("observation_revision", "status", "coverage_counts", "states")},
                    "source_budget": {key: budget.get(key) for key in
                        ("used", "local_cap", "provider_limit_verified", "status")},
                    "source_call": {key: source_call.get(key) for key in
                        ("in_flight", "wait_expired", "state", "error_type")},
                    "session": value.get("session"), "summary": value.get("summary"),
                    "latest": value.get("last_evaluation_at"), "blockers": value.get("blockers"),
                    "evaluations": [(row.get("evaluation_id"), row.get("state"), row.get("current_eligibility"))
                        for row in value.get("evaluations", [])],
                    "research_revisions": [(row.get("evaluation_id"),
                        (row.get("strategy_comparison") or {}).get("s1", {}).get("evaluation_id"),
                        (row.get("strategy_comparison") or {}).get("reference_eligibility"),
                        (row.get("strategy_comparison") or {}).get("reference_contract"),
                        (row.get("strategy_comparison") or {}).get("option_cost"),
                        (row.get("strategy_comparison") or {}).get("outcome"))
                        for row in value.get("evaluations", [])],
                    "ai_reviews": [(event.get("evaluation_id"), event.get("ai_review"))
                        for row in value.get("evaluations", [])
                        for event in (row, (row.get("strategy_comparison") or {}).get("s1", {}))
                        if event.get("ai_review")],
                    "candidates": [(row.get("evaluation_id"), row.get("current_eligibility"))
                        for row in value.get("candidates", [])]}, sort_keys=True, default=str)
                if watermark != self.published.get((strategy, kind)):
                    self.published[strategy, kind] = watermark
                    if self.on_complete and cache.error is None:
                        notify_strategies.add(strategy)
            for strategy in sorted(notify_strategies):
                self.on_complete(strategy)
            self.task_observation = {"state": "OBSERVED", "projection_worker_limit": 2,
                "tasks": [{"strategy": strategy, "kind": kind,
                    "enabled": availability[strategy]["enabled"],
                    "unavailable_reason": availability[strategy].get("reason"),
                    "inflight": cache.future is not None,
                    "inflight_age_seconds": monotonic() - cache.pending_started
                        if cache.future is not None and cache.pending_started is not None else None,
                    "error_type": cache.error} for (strategy, kind), cache in self.caches.items()]}
        except Exception as exc:
            self.error_type = type(exc).__name__

    def invalidate(self, strategy):
        for kind in ("current", "compact"):
            if (strategy, kind) in self.caches:
                self.caches[strategy, kind].invalidate()

    def health(self):
        try:
            result = self.observation.peek("runtime")
            if result["snapshot"]["state"] != "FRESH":
                result["state"] = "UNKNOWN_STALE"
        except SnapshotUnavailable:
            result = {"state": "UNAVAILABLE", "exit_reason": "UNKNOWN",
                      "market_data_checked": False, "database_accessed": False}
        result["snapshot_pump"] = {"last_tick_at": self.tick_at, "error_type": self.error_type}
        result["event_loop"] = dict(self.event_loop)
        result["projection_tasks"] = self.task_observation
        context = self.context
        result["research_worker"] = ({key: context[2].get(key) for key in (
            "state", "thread_alive", "research_ready", "first_loop_at", "loop_count", "error_id", "error_type", "failed_stage",
            "runtime_health", "health_checked_at", "stage", "stage_started_at", "last_cycle_at",
            "research_progress", "last_persisted_bar", "stage_age_seconds")} if context else {"state": "UNAVAILABLE"})
        age = monotonic() - self.context_at if self.context_at is not None else None
        result["research_worker"]["snapshot_age_seconds"] = age
        if age is None or age > 5 or self.error_type:
            result["research_worker"]["runtime_health"] = "UNCONFIRMED_STALE"
            result["research_worker"]["research_ready"] = False
        return result

    def read(self, strategy, kind):
        available = self.availability.get(strategy)
        if available is not None and not available["enabled"]:
            raise SnapshotUnavailable(available.get("reason") or "RESEARCH_POLICY_UNAVAILABLE")
        context = self.context
        day = self.clock().astimezone(ZoneInfo("America/New_York")).date().isoformat()
        if context is None or context[0] != day:
            raise SnapshotUnavailable("CURRENT_SESSION_SNAPSHOT_UNAVAILABLE")
        payload = self.caches[strategy, kind].peek(context[:2])
        observation = self.health()
        payload["service_observation"] = observation
        if self.context_at is None or monotonic() - self.context_at > 5 or self.error_type:
            payload["snapshot"].update(state="STALE", error_type="WORKER_SNAPSHOT_UNAVAILABLE")
        if observation.get("enforced") and observation["state"] != "RUNNING":
            payload["snapshot"].update(state="STALE", error_type="SERVICE_RUNTIME_UNCONFIRMED")
        if observation.get("research_worker", {}).get("research_ready") is False:
            payload["snapshot"].update(state="STALE", error_type="RESEARCH_WORKER_NOT_READY")
        if payload["snapshot"]["state"] != "FRESH":
            payload["candidates"] = []
            for row in payload.get("evaluations", []):
                if row.get("current_eligibility"):
                    row["current_eligibility"] = {**row["current_eligibility"],
                        "state": "UNCONFIRMED", "reasons": ["HTTP_SNAPSHOT_STALE"]}
        else:
            from .options_one_minute import timestamp
            now = self.clock()
            for row in payload.get("evaluations", []):
                current = row.get("current_eligibility", {})
                if current.get("state") == "QUALIFIED":
                    try:
                        fresh = now < min(timestamp(current["valid_until"]), timestamp(row["deadline_at"]))
                    except (KeyError, TypeError, ValueError):
                        fresh = False
                    if not fresh:
                        row["current_eligibility"] = {**current, "state": "UNCONFIRMED",
                            "reasons": ["QUALIFICATION_EVIDENCE_EXPIRED"]}
            valid = []
            for row in payload.get("candidates", []):
                current = row.get("current_eligibility", {})
                try:
                    # valid_until already includes the BBO bound; never renew it.
                    if current.get("state") == "QUALIFIED" and now < min(
                            timestamp(current["valid_until"]), timestamp(row["deadline_at"])):
                        valid.append(row)
                except (KeyError, TypeError, ValueError):
                    pass
            payload["candidates"] = valid
        if kind == "compact":
            from .options_opening_trend_summary import compact_status
            payload = compact_status(payload)
        return payload

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1)
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.observation.close()
