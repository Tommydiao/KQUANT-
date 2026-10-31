"""Worker owned by the existing Foundation Supervisor. Research only."""
from __future__ import annotations

import json
import queue
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from . import options_two_hour as engine
from . import options_two_hour_data as data
from .longbridge_provider import longbridge_runtime
from .market_clock import is_trading_day, session_bounds_utc
from .option_event_coverage import option_event_context


class TwoHourResearchWorker:
    def __init__(self, main_db, hub, *, path=engine.STORE, copilot_path=None):
        self.main_db, self.hub, self.path = main_db, hub, path
        self.copilot_path = Path(copilot_path) if copilot_path is not None else Path(main_db).parent / "options_signal_copilot/signal_copilot.sqlite3"
        self.owner = "foundation-two-hour-research"
        self.runtime = longbridge_runtime()
        self.sink = self.runtime.event_queue(self.owner, kinds=("candle",), confirmed_only=True)
        self.day = None
        self.manifest = None
        self.subscribed = set()
        self.subscription_retry = {}
        self.bar_cache = {}
        self.recovery_cursor = 0
        self.next_recovery = datetime.min.replace(tzinfo=UTC)
        self.recovery_state = {}
        self.last_progress = None
        self.expired_entry_day = None
        self.contract_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="two-hour-contract-reference")
        self.contract_future = None
        self.contract_job = None
        self.state = {"state": "NOT_STARTED", "paper_enabled": False, "device_delivery": "NOT_VERIFIED"}

    def prepare(self, now):
        day = now.astimezone(engine.NY).date()
        if self.day == day:
            return
        if self.subscribed:
            self.runtime.release_subscriptions(self.owner)
        self.sink = self.runtime.event_queue(self.owner, kinds=("candle",), confirmed_only=True)
        engine.initialize(self.path)
        data.initialize(self.path)
        self.manifest = data.universe(self.main_db)
        data.seed_jobs(day, self.manifest, self.path)
        data.reuse_turnover_cache(day, {item["symbol"] for item in self.manifest["items"]},
                                 engine.ROOT / "work/cbrm_v0_2/cbrm.sqlite3", self.path)
        self.day, self.subscribed, self.bar_cache = day, set(), {}
        self.mapping = {item["provider_symbol"]: item["symbol"] for item in self.manifest["items"]}
        self.providers = {value: key for key, value in self.mapping.items()}

    def subscribe_ready(self):
        from longbridge.openapi import Period
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute("SELECT symbol,payload_json FROM two_hour_prewarm WHERE session=? AND state='READY' ORDER BY symbol", (self.day.isoformat(),)).fetchall()
        for symbol, payload in rows:
            if symbol in self.subscribed:
                continue
            now = datetime.now(UTC)
            if self.subscription_retry.get(symbol, now) > now:
                continue
            try:
                self.runtime.retain_subscription(self.owner, json.loads(payload)["provider_symbol"], period=Period.Min_5)
                self.subscribed.add(symbol)
            except Exception as exc:
                self.subscription_retry[symbol] = now + timedelta(seconds=60)
                self.state = {"state": "SUBSCRIPTION_DEFERRED", "symbol": symbol, "reason": data.classify_failure(exc)}
            # Bound subscription work so a burst of ready symbols cannot starve events.
            break

    def consume(self, item, now):
        from longbridge.openapi import Period
        kind, provider_symbol, event, received_at = item
        if kind != "candle" or not getattr(event, "is_confirmed", False) or getattr(event, "period", None) != Period.Min_5:
            return
        symbol = self.mapping.get(provider_symbol)
        if not symbol:
            return
        candle = event.candlestick
        from .stock_signals import _parse_longbridge_time
        opened = _parse_longbridge_time(candle.timestamp)
        if opened is None:
            return
        opening, closing = session_bounds_utc(self.day)
        cutoff = min(opening + timedelta(hours=2), closing)
        if not opening <= opened < cutoff:
            return
        bar = {"symbol": symbol, "open_at": opened.isoformat(), "available_at": (opened + timedelta(minutes=5)).isoformat(),
               "received_at": received_at, "closed": True, "interval": "5m", "close": float(candle.close),
               "turnover": float(candle.turnover) if getattr(candle, "turnover", None) is not None else None,
               "turnover_source": "NATIVE", "currency": "USD"}
        bar["source"] = "LONGBRIDGE_CONFIRMED_PUSH"
        bar["provider_confirmed"] = True
        bar["bar_end"] = bar["available_at"]
        bar["usable_at"] = received_at if engine.timestamp(received_at) >= engine.timestamp(bar["available_at"]) else None
        self.record_bar(symbol, bar)
        if bar["usable_at"] is None:
            return
        self.evaluate_latest(symbol, opened, now)

    def record_bar(self, symbol, bar):
        if symbol not in self.bar_cache:
            self.bar_cache[symbol] = engine.stored_bars(symbol, self.day.isoformat(), self.path)
        engine.save_bar(bar, self.day.isoformat(), self.path)
        opened = engine.timestamp(bar["open_at"])
        old = self.bar_cache[symbol].get(opened)
        if old is None or engine.timestamp(bar["received_at"]) >= engine.timestamp(old["received_at"]):
            self.bar_cache[symbol][opened] = bar

    def evaluate_latest(self, symbol, opened, now):
        opening, closing = session_bounds_utc(self.day)
        cutoff = min(opening + timedelta(hours=2), closing)
        bar = self.bar_cache[symbol][opened]
        prior = self.bar_cache[symbol].get(opened - timedelta(minutes=5))
        if opened < opening + timedelta(minutes=5):
            return
        end = opened + timedelta(minutes=5)
        if now <= end + timedelta(seconds=60) and (prior is None or any(
                engine.timestamp(item["received_at"]) < engine.timestamp(item["available_at"])
                for item in (prior, bar))):
            return
        with sqlite3.connect(self.path) as connection:
            row = connection.execute("SELECT payload_json FROM two_hour_baselines WHERE session=? AND symbol=? AND scope_hash=?",
                (self.day.isoformat(), symbol, self.manifest["scope_hash"])).fetchone()
        baseline = json.loads(row[0]) if row else {}
        policy = engine.load_policy()
        payload = {"baseline": baseline, "bars": [prior, bar] if prior else [bar], "policy_hash": policy["policy_hash"],
                   "scope_hash": self.manifest["scope_hash"], "schedule": {"is_trading_day": True,
                    "regular_open_utc": opening.isoformat(), "regular_close_utc": closing.isoformat()}}
        if now > end + timedelta(seconds=60) or end >= cutoff:
            # Keep missed-window evidence; do not publish catch-up alerts.
            for right in ("CALL", "PUT"):
                result = engine.evaluate_pair(symbol=symbol, right=right, baseline=baseline, bars=payload["bars"],
                    schedule=payload["schedule"], event_clear=False, now=now, scope_hash=payload["scope_hash"])
                result["timing_state"] = "MISSED_EVALUATION_WINDOW" if end < cutoff else "ENTRY_WINDOW_CLOSED"
                result["state"] = result["timing_state"]
                result["blockers"] = [reason for reason in result["blockers"] if reason != "EVENT_UNKNOWN_OR_BLOCKED"]
                result["event_reason"] = "NOT_EVALUATED_LATE"
                result["event_coverage"] = {"status": "NOT_EVALUATED_LATE", "trade_eligible": False}
                result["data_complete"] = False
                engine.persist_evaluation(result, self.path)
            return
        engine.enqueue(session=self.day.isoformat(), symbol=symbol, slot=opened.isoformat(), payload=payload, now=now,
                       deadline=min(end + timedelta(seconds=60), cutoff), path=self.path)

    def recover_one(self, now):
        """Fair bounded snapshot recovery; actual receipt time is never backdated."""
        from longbridge.openapi import Period, AdjustType
        from .stock_signals import _parse_longbridge_time
        opening, closing = session_bounds_utc(self.day)
        if now < opening + timedelta(minutes=10) or now >= min(opening + timedelta(hours=2), closing):
            return
        if now < self.next_recovery or not self.subscribed:
            return
        self.next_recovery = now + timedelta(seconds=0.5)
        symbols = sorted(self.subscribed)
        symbol = symbols[self.recovery_cursor % len(symbols)]
        self.recovery_cursor += 1
        expected = opening + timedelta(minutes=5 * (int((now - opening).total_seconds()) // 300 - 1))
        if symbol not in self.bar_cache:
            self.bar_cache[symbol] = engine.stored_bars(symbol, self.day.isoformat(), self.path)
        cache = self.bar_cache[symbol]
        pair = [cache.get(expected - timedelta(minutes=5)), cache.get(expected)]
        if all(bar and engine.timestamp(bar["received_at"]) >= engine.timestamp(bar["available_at"]) for bar in pair):
            return
        try:
            request_started = datetime.now(UTC).isoformat()
            # A pull requested before the nominal boundary cannot cure an early push.
            if engine.timestamp(request_started) < expected + timedelta(minutes=5):
                return
            def pull(context):
                rows = context.realtime_candlesticks(self.providers[symbol], Period.Min_5, 32)
                starts = {_parse_longbridge_time(row.timestamp) for row in rows}
                if expected not in starts or expected - timedelta(minutes=5) not in starts:
                    rows = context.candlesticks(self.providers[symbol], Period.Min_5, 32, AdjustType.NoAdjust)
                return rows
            rows = self.runtime.call("two_hour_gap_recovery", pull, 3)
            received = datetime.now(UTC)
            wanted = {expected - timedelta(minutes=5), expected}
            for candle in rows:
                opened = _parse_longbridge_time(candle.timestamp)
                if opened not in wanted or opened + timedelta(minutes=5) > received:
                    continue
                previous = cache.get(opened)
                if previous and engine.timestamp(previous["received_at"]) >= engine.timestamp(previous["available_at"]):
                    continue
                bar = {"symbol": symbol, "open_at": opened.isoformat(), "available_at": (opened + timedelta(minutes=5)).isoformat(),
                       "received_at": received.isoformat(), "request_started_at": request_started,
                       "closed": True, "interval": "5m", "close": float(candle.close),
                       "turnover": float(candle.turnover) if getattr(candle, "turnover", None) is not None else None,
                       "turnover_source": "NATIVE", "currency": "USD", "source": "LONGBRIDGE_GAP_SNAPSHOT",
                       "closure_evidence": "ELAPSED_REGULAR_INTERVAL"}
                bar.update(bar_end=bar["available_at"], usable_at=received.isoformat(), provider_confirmed=None,
                           closure_evidence="POST_BOUNDARY_NEW_PROVIDER_SNAPSHOT")
                self.record_bar(symbol, bar)
            usable_pair = all(cache.get(start) and engine.timestamp(cache[start]["received_at"]) >= engine.timestamp(cache[start]["available_at"])
                              for start in wanted)
            self.recovery_state[symbol] = {"state": "RECOVERED" if usable_pair else "MISSING_CLOSED_BAR", "at": received.isoformat()}
            if usable_pair:
                self.evaluate_latest(symbol, expected, received)
        except Exception as exc:
            self.recovery_state[symbol] = {"state": "DEFERRED", "reason": data.classify_failure(exc), "at": datetime.now(UTC).isoformat()}

    def calculate_one(self, now):
        job = engine.claim(owner=self.owner, now=now, path=self.path)
        if not job:
            return False
        payload = job["payload"]
        try:
            policy = engine.load_policy()
            if payload["policy_hash"] != policy["policy_hash"]:
                raise ValueError("POLICY_HASH_MISMATCH")
            # Event coverage is evaluated at the decision, not carried from an old scan.
            event = option_event_context(self.main_db, job["symbol"], now.isoformat(),
                                         until=(now + timedelta(days=7)).isoformat(),
                                         policy_id=policy["policy_id"], policy_hash=policy["policy_hash"],
                                         scope_hash=payload["scope_hash"])
            for right in ("CALL", "PUT"):
                result = engine.evaluate_pair(symbol=job["symbol"], right=right, baseline=payload["baseline"], bars=payload["bars"],
                    schedule=payload["schedule"], event_clear=bool(event.get("trade_eligible")), now=datetime.now(UTC),
                    scope_hash=payload["scope_hash"], policy=policy)
                result["event_coverage"] = event
                result["event_reason"] = "KNOWN_EVENT_RISK" if event.get("blocking_events") else ("EVENT_COVERAGE_MISSING" if event.get("missing_categories") else None)
                if result["state"] == "RESEARCH_CANDIDATE":
                    result["state"] = "PENDING_CONTRACT_VERIFICATION"
                    result["contract_qualification"] = {"status": "QUEUED"}
                    result["contract_qualification"]["retry"] = "PERSISTENT_WITHIN_ORIGINAL_DEADLINE"
                result["timing_state"] = "MISSED_EVALUATION_WINDOW" if datetime.now(UTC) > engine.timestamp(job["deadline_at"]) else "ON_TIME"
                engine.persist_evaluation(result, self.path)
                if result["state"] == "PENDING_CONTRACT_VERIFICATION":
                    engine.enqueue(session=result["session"], symbol=result["symbol"], slot=result["slot"],
                        payload={"kind": "CONTRACT", "evaluation_id": result["evaluation_id"], "original": result,
                                 "policy_hash": result["policy_hash"], "scope_hash": result["scope_hash"]},
                        now=datetime.now(UTC), deadline=engine.timestamp(result["deadline_at"]), path=self.path)
            engine.finish(job, owner=self.owner, now=datetime.now(UTC), path=self.path)
        except Exception as exc:
            engine.finish(job, owner=self.owner, now=datetime.now(UTC), reason=data.classify_failure(exc), path=self.path)
        return True

    def qualify_contract(self, original, policy):
        from .options_forward_paper import _default_contract_provider
        from .options_paper_engineering import select_contract
        result = dict(original)
        try:
            if datetime.now(UTC) >= engine.timestamp(original["deadline_at"]):
                raise TimeoutError("ORIGINAL_DEADLINE_EXCEEDED")
            spot = float(result["bar_evidence"][-1]["close"])
            contracts = _default_contract_provider({**result, "market_session_date": result["session"]},
                {"underlying_price": spot}, self.main_db, policy["inherited_contracts"], deadline_at=engine.timestamp(result["deadline_at"]))
            selection = select_contract(result, contracts, underlying_price=spot, policy=policy["inherited_contracts"])
            selected = selection.get("selected")
            result["contract_qualification"] = {**selection, "status": "PASS" if selected else "BLOCKED", "contract_id": selected.get("contract_id") if selected else None,
                "checked_at": datetime.now(UTC).isoformat(), "evidence": contracts}
            if selected:
                result["contract_id"] = selected["contract_id"]
            # This append records a new check, never rewrites the original decision.
            current_policy = engine.load_policy()
            current_scope = data.universe(self.main_db)["scope_hash"]
            event = option_event_context(self.main_db, result["symbol"], datetime.now(UTC).isoformat(),
                                         until=(datetime.now(UTC) + timedelta(days=7)).isoformat(),
                                         policy_id=current_policy["policy_id"], policy_hash=current_policy["policy_hash"],
                                         scope_hash=current_scope)
            result["qualification_event_coverage"] = event
            result["blockers"] = list(result.get("blockers", []))
            if current_policy["policy_hash"] != original["policy_hash"] or current_scope != original["scope_hash"]:
                result["blockers"].append("QUALIFICATION_CONFIG_CHANGED")
            if not event.get("trade_eligible"):
                result["blockers"].append("QUALIFICATION_EVENT_COVERAGE_INVALID")
        except Exception as exc:
            result["contract_qualification"] = {"status": "UNAVAILABLE", "error_type": type(exc).__name__}
        completed = datetime.now(UTC)
        result["parent_evaluation_id"] = original["evaluation_id"]
        result["evaluated_at"] = completed.isoformat()
        result["evaluation_id"] = engine.digest({"parent": original["evaluation_id"], "qualification": result["contract_qualification"], "at": result["evaluated_at"]})
        result["timing_state"] = "MISSED_EVALUATION_WINDOW" if completed > engine.timestamp(result["deadline_at"]) else "ON_TIME"
        result["state"] = "RESEARCH_CANDIDATE" if engine.display_state(result, completed) == "QUALIFIED_SIGNAL" else "PENDING_CONTRACT_VERIFICATION"
        return result

    def publish_pending(self, now):
        if self.contract_future is not None and self.contract_future.done():
            try:
                result = self.contract_future.result()
                engine.persist_evaluation(result, self.path)
                retry = result["contract_qualification"]["status"] == "UNAVAILABLE" and self.contract_job["attempts"] < 2
                engine.finish(self.contract_job, owner=self.owner, now=now, path=self.path,
                    reason="CONTRACT_PROVIDER_UNAVAILABLE" if retry else None,
                    retry_at=now + timedelta(seconds=1) if retry else None)
            except Exception as exc:
                engine.finish(self.contract_job, owner=self.owner, now=now, path=self.path, reason=type(exc).__name__)
            self.contract_future = None
            self.contract_job = None
        if self.contract_future is None:
            job = engine.claim(owner=self.owner, now=now, path=self.path, kind="CONTRACT", lease_seconds=60)
            if job:
                self.contract_job = job
                self.contract_future = self.contract_executor.submit(self.qualify_contract, job["payload"]["original"], engine.load_policy())
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute("SELECT event_id,payload_json FROM two_hour_candidates WHERE published_at IS NULL ORDER BY rowid LIMIT 20").fetchall()
        for event_id, raw in rows:
            result = json.loads(raw)
            if now > engine.timestamp(result["deadline_at"]):
                state = "EXPIRED_BEFORE_PUBLICATION"
            elif engine.display_state(result, now) != "QUALIFIED_SIGNAL":
                state = "REFERENCE_ONLY_CONTRACT_NOT_QUALIFIED"
            else:
                signal = self.record_qualified_signal(result)
                self.queue_research_alert(result, now, signal_id=signal["signal_id"])
                self.hub.publish({"type": "options_two_hour_research", "event_id": event_id, "symbol": result["symbol"],
                                  "signal_id": signal["signal_id"], "state": "RESEARCH_CANDIDATE", "paper_enabled": False, "evidence": result})
                state = "SSE_PUBLISHED_PUSH_QUEUED_DEVICE_UNVERIFIED"
            with sqlite3.connect(self.path) as connection:
                connection.execute("UPDATE two_hour_candidates SET published_at=? WHERE event_id=? AND published_at IS NULL",
                                   (canonical_publication(now, state), event_id))

    def record_qualified_signal(self, result):
        from .options_signal_copilot import create_signal
        evidence_id = result["evaluation_id"]
        session = date.fromisoformat(result["session"])
        opening, closing = session_bounds_utc(session)
        return create_signal({
            "source": "FROZEN_RULE", "state": "REVIEW_READY",
            "strategy_id": result["policy_id"], "strategy_hash": result["policy_hash"],
            "scope_hash": result["scope_hash"], "economic_opportunity_id": result["event_id"],
            "evaluation_id": evidence_id, "symbol": result["symbol"], "right": result["right"],
            "contract_id": result["contract_id"], "observed_at": result["bar_end"],
            "valid_until": result["deadline_at"], "evidence_refs": [f"two_hour_evaluation:{evidence_id}"],
            "market_schedule": {"is_trading_day": is_trading_day(session),
                                "regular_open_utc": opening.isoformat(), "regular_close_utc": closing.isoformat()},
            "rule_evidence": result["rule_evidence"], "contract_qualification": result["contract_qualification"],
            "event_coverage": result.get("qualification_event_coverage", result.get("event_coverage")),
            "paper_enabled": False, "real_orders_enabled": False,
        }, store_path=self.copilot_path)

    def queue_research_alert(self, result, now, *, signal_id):
        from .stock_store import connect
        from urllib.parse import urlencode
        alert_id = f"two-hour-{result['event_id']}"
        payload = {"type": "options_two_hour_research", "event_id": result["event_id"], "signal_id": signal_id,
                   "symbol": result["symbol"], "right": result["right"], "severity": "INFO",
                   "qualified": engine.display_state(result, now) == "QUALIFIED_SIGNAL",
                   "policy_hash": result["policy_hash"], "scope_hash": result["scope_hash"],
                   "contract_id": result.get("contract_id"), "bar_end": result["bar_end"],
                   "title": "KQUANT research / 研究候选", "body": f"{result['symbol']} {result['right']} · Research only / 仅研究",
                   "deadline_at": result["deadline_at"], "paper_enabled": False, "real_orders_enabled": False,
                   "url": "/?" + urlencode({"workspace": "options", "view": "signals", "symbol": result["symbol"], "evaluation": result["evaluation_id"]})}
        stamp = now.isoformat()
        with connect(self.main_db) as connection:
            connection.execute("""INSERT OR IGNORE INTO alert_events
                (alert_id,instruction_id,dedupe_key,symbol,severity,event_type,title,message,payload_json,delivery_status,acknowledged_at,created_at,updated_at)
                VALUES (?,NULL,?,?,'INFO','options_two_hour_research',?,?,?,'web_queued',NULL,?,?)""",
                (alert_id, alert_id, result["symbol"], payload["title"], payload["body"], engine.canonical(payload), stamp, stamp))
            connection.execute("INSERT OR IGNORE INTO option_delivery_outbox VALUES (?,'queued',?,?,?,'{}')",
                               (alert_id, engine.canonical(payload), stamp, stamp))
            connection.commit()

    def run(self, stop):
        while not stop.is_set():
            try:
                now = datetime.now(UTC)
                day = now.astimezone(engine.NY).date()
                if not is_trading_day(day):
                    self.state = {"state": "WAIT_MARKET", "paper_enabled": False}
                    stop.wait(60)
                    continue
                opening, closing = session_bounds_utc(day)
                self.prepare(now)
                if now < opening:
                    # Consume the filtered stream even before opening; never accumulate ticks overnight.
                    while True:
                        try:
                            self.consume(self.sink.get_nowait(), datetime.now(UTC))
                        except queue.Empty:
                            break
                    self.state = data.prewarm_one(self.runtime, self.manifest, day, path=self.path)
                    # Historical backfill can run now; live subscriptions start at prewarm.
                    if now >= opening - timedelta(hours=1):
                        self.subscribe_ready()
                    stop.wait(1)
                    continue
                cutoff = min(opening + timedelta(hours=2), closing)
                if now >= cutoff and self.expired_entry_day != day:
                    from .options_signal_copilot import expire_two_hour_entry_intents
                    expire_two_hour_entry_intents(now=now)
                    self.expired_entry_day = day
                if now > cutoff + timedelta(minutes=1):
                    if self.subscribed:
                        self.runtime.release_subscriptions(self.owner)
                        self.subscribed.clear()
                    self.state = {"state": "ENTRY_WINDOW_CLOSED", "paper_enabled": False}
                    self.publish_pending(now)
                    stop.wait(30)
                    continue
                for _ in range(200):
                    try:
                        self.consume(self.sink.get_nowait(), datetime.now(UTC))
                    except queue.Empty:
                        break
                calculated = 0
                for _ in range(100):
                    if not self.calculate_one(datetime.now(UTC)):
                        break
                    calculated += 1
                self.publish_pending(datetime.now(UTC))
                if not calculated and self.sink.empty():
                    self.subscribe_ready()
                    self.recover_one(datetime.now(UTC))
                self.state = {"state": "RESEARCH_MONITORING", "subscribed_symbols": len(self.subscribed), "paper_enabled": False,
                              "last_cycle_at": datetime.now(UTC).isoformat(), "device_delivery": "NOT_VERIFIED",
                              "event_queue_size": self.sink.qsize(), "recovery": dict(self.recovery_state), "provider_runtime": self.runtime.health()}
                if self.last_progress is None or now - self.last_progress >= timedelta(seconds=5):
                    self.hub.publish({"type": "options_two_hour_progress", "state": self.state["state"], "at": now.isoformat()})
                    self.last_progress = now
                stop.wait(0.05)
            except Exception as exc:
                self.state = {"state": "DEGRADED", "reason": data.classify_failure(exc), "error_type": type(exc).__name__, "paper_enabled": False}
                stop.wait(5)
        self.contract_executor.shutdown(wait=False, cancel_futures=True)


def canonical_publication(now, state):
    return engine.canonical({"at": now.isoformat(), "state": state})
