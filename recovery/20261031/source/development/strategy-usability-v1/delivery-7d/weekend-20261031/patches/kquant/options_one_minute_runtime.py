"""Shadow one-minute worker owned by the existing Foundation Supervisor."""
from __future__ import annotations

import queue
import os
import threading
import traceback
import uuid
import sqlite3
from time import monotonic
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from . import options_one_minute as rules
from . import options_one_minute_data as data
from .longbridge_provider import longbridge_runtime
from .market_clock import is_trading_day, session_bounds_utc


def worker_phase(now: datetime, opening: datetime, closing: datetime, cutoff_minutes: int) -> str:
    if now < opening:
        local = now.astimezone(rules.NY).time()
        return ("WAIT_PREWARM_WINDOW" if local < time(8, 30) else
                "PREWARM" if local < time(9, 25) else "PREMARKET_CHECK")
    if now < closing - timedelta(minutes=cutoff_minutes):
        return "SHADOW_MONITORING"
    return "EXIT_MONITORING" if now < closing else "MARKET_CLOSED"


class OneMinuteResearchWorker:
    def __init__(self, main_db: Path, hub, *, path: Path = rules.STORE, runtime=None, clock=None):
        self.main_db, self.hub, self.path = Path(main_db), hub, Path(path)
        self.owner = "foundation-one-minute-shadow"
        self.entry_cutoff_minutes = rules.load_policy()["entry_cutoff_minutes_before_close"]
        self.runtime = runtime or longbridge_runtime()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.sink = self.runtime.event_queue(self.owner, kinds=("candle",), confirmed_only=True)
        self._pending_input_commit = None  # One dequeued item, cleared only after consume succeeds.
        self.provider_jobs = ThreadPoolExecutor(max_workers=3, thread_name_prefix="one-minute-provider")
        self.risk_jobs = ThreadPoolExecutor(max_workers=1, thread_name_prefix="one-minute-risk")
        self.prewarm_future: Future | None = None
        self.subscribe_future: Future | None = None
        self.recovery_future: Future | None = None
        self.recovery_target = None
        self.risk_quote_future: Future | None = None
        self.risk_quote_position = None
        self.next_risk_at = datetime.min.replace(tzinfo=UTC)
        self.next_risk_quote_at = datetime.min.replace(tzinfo=UTC)
        self.risk_cursor = 0
        self.day = None
        self.manifest = None
        self.mapping = {}
        self.provider_by_symbol = {}
        self.subscribed = set()
        self.subscription_retry = {}
        self.bars = {}
        self.recovery_pending = {}
        self.recovery_deadlines = {}
        self.recovery_attempted = {}
        self.recovery_retry_at = {}
        self.evaluated = set()
        self.qualification_lane = None
        self.recovery_lane = None
        self.trend_lane = None
        self.trend_recovery_lane = None
        self.trend_recovery_bucket = None
        self.trend_reference_future = None
        self.price_preflight_future = None
        self.price_preflight_target = None
        self.price_preflight_attempted = set()
        self.price_preflight_quotes = {}
        self.price_preflight_source_hash = None
        self.trend_references = {}
        self.reference_currencies = {}
        self.next_trend_reference_at = datetime.min.replace(tzinfo=UTC)
        self.next_prewarm_at = datetime.min.replace(tzinfo=UTC)
        self.next_status_at = datetime.min.replace(tzinfo=UTC)
        self.next_recovery_at = datetime.min.replace(tzinfo=UTC)
        self.state = {"state": "NOT_STARTED", "mode": "SHADOW_RESEARCH", "paper_enabled": False,
                      "real_orders_enabled": False, "qualified_alerts_enabled": False,
                      "stage": "CREATED", "stage_started_at": self.clock().isoformat()}

    def _stage(self, name):
        self.state.update(stage=name, stage_started_at=self.clock().isoformat())

    def prepare(self, now: datetime) -> None:
        day = now.astimezone(rules.NY).date()
        if self.day == day:
            return
        if self.subscribed:
            self.runtime.release_subscriptions(self.owner)
        self.sink = self.runtime.event_queue(self.owner, kinds=("candle",), confirmed_only=True)
        self.manifest = data.universe(self.main_db)
        data.seed(day, self.manifest, self.path)
        self.mapping = {item["provider_symbol"]: item["symbol"] for item in self.manifest["items"]
                        if item["identity_status"] == "verified" and item["provider_symbol"]}
        self.provider_by_symbol = {symbol: provider for provider, symbol in self.mapping.items()}
        self.day, self.subscribed, self.bars = day, set(), {}
        self.trend_references.clear()
        self.reference_currencies.clear()
        self.trend_recovery_bucket = None
        self.state.update(session=day.isoformat(),
                          scope_hash=self.manifest["scope_hash"],
                          registered_items=[{"symbol": row["symbol"], "identity_status": row["identity_status"]}
                                            for row in self.manifest["items"]],
                          first_bar_expected_at=(session_bounds_utc(day)[0] + timedelta(minutes=1)).isoformat(),
                          last_persisted_bar=None, last_evaluation_at=None)
        self.recovery_pending.clear()
        self.recovery_deadlines.clear()
        self.recovery_attempted.clear()
        self.recovery_retry_at.clear()
        self.evaluated.clear()
        if self.trend_lane:
            self.trend_lane.recover_registered(self.manifest["items"], day, self.manifest["scope_hash"])

    def _queue_missing_predecessors(self, symbol: str, opened: datetime, now: datetime) -> None:
        opening, closing = session_bounds_utc(self.day)
        deadline = min(opened + timedelta(minutes=1, seconds=30),
                       closing - timedelta(minutes=self.entry_cutoff_minutes))
        if now > deadline:
            return
        required = min(int((opened - opening).total_seconds() // 60),
                       rules.load_policy()["prior_intraday_bars_max"])
        for minute in range(required, 0, -1):
            prior_open = opened - timedelta(minutes=minute)
            prior = self.bars[symbol].get(prior_open)
            if prior is not None and rules.timestamp(prior["received_at"]) >= prior_open + timedelta(minutes=1):
                continue
            key = symbol, prior_open
            self.recovery_pending.setdefault(key, "MISSING_PRIOR_CLOSED_BAR")
            self.recovery_deadlines[key] = max(self.recovery_deadlines.get(key, deadline), deadline)

    def _reevaluate_following(self, symbol: str, opened: datetime, now: datetime) -> None:
        for minute in range(1, rules.load_policy()["prior_intraday_bars_max"] + 1):
            following = opened + timedelta(minutes=minute)
            if following in self.bars.get(symbol, {}) and (symbol, following) not in self.evaluated:
                self.evaluate_bar(symbol, following, now)

    def _start_prewarm(self, now: datetime) -> None:
        opening, closing = session_bounds_utc(self.day)
        local = now.astimezone(rules.NY)
        if self.prewarm_future and not self.prewarm_future.done():
            return
        if self.prewarm_future:
            try:
                self.state["prewarm_last"] = self.prewarm_future.result()
                result = self.state["prewarm_last"]
                if (result.get("reason") in {"PROVIDER_RATE_LIMIT", "SDK_THROTTLE"}
                        and result.get("retry_at")):
                    self.next_prewarm_at = max(self.next_prewarm_at, rules.timestamp(result["retry_at"]))
                if (self.trend_lane is not None and result.get("state") == "FETCHED"
                        and result.get("symbol") and result.get("session", self.day.isoformat()) == self.day.isoformat()):
                    self.trend_lane.history.invalidate(result["symbol"], self.day)
            except Exception as exc:
                self.state["prewarm_last"] = {"state": "FAILED", "error_type": type(exc).__name__}
            self.prewarm_future = None
        trend_prewarm = self.trend_lane is not None
        cutoff = opening + timedelta(minutes=30) if trend_prewarm else closing - timedelta(minutes=self.entry_cutoff_minutes)
        self.state["prewarm_scope"] = ("OPENING_TREND_20D_0940_0950_AND_PRIOR_CLOSE" if trend_prewarm
                                       else "LEGACY_ONE_MINUTE_FULL_ENTRY_WINDOW")
        self.state["prewarm_cutoff_at"] = cutoff.isoformat()
        request = None
        if trend_prewarm:
            from .options_opening_trend_prewarm import repair_request
            request = repair_request(self.day, self.manifest, now)
        if trend_prewarm and hasattr(self.trend_lane, "state"):
            self.trend_lane.state["historical_prewarm"] = {
                "scope": self.state["prewarm_scope"], "cutoff_at": cutoff.isoformat(),
                "last": self.state.get("prewarm_last"), "automatic_provider_requests_before_0830": bool(request),
                "data_repair_request": request,
                "legacy_full_day_readiness_not_reused": True}
        if (local.time() < time(8, 30) and not request) or now >= cutoff or now < self.next_prewarm_at:
            return
        if now >= opening and (now < opening + timedelta(minutes=1) or now.second < 35
                               or now.second > 55 or self.recovery_pending or self.recovery_future
                               or self.risk_quote_future):
            return
        self.next_prewarm_at = now + timedelta(seconds=20 if now >= opening else 1)
        if trend_prewarm:
            from .options_opening_trend_prewarm import prewarm_one
        else:
            prewarm_one = data.prewarm_one
        self.prewarm_future = self.provider_jobs.submit(
            prewarm_one, self.runtime, self.manifest, self.day, path=self.path, now=now,
            **({"preferred_symbols": request["preferred_symbols"], "request_limit": request["request_limit"]}
               if request else {}))

    def _start_subscription(self, now: datetime) -> None:
        from longbridge.openapi import Period
        local = now.astimezone(rules.NY)
        if local.time() < time(9, 15):
            return
        if self.subscribe_future and not self.subscribe_future.done():
            return
        if self.subscribe_future:
            symbol = self.subscribe_future.symbol
            try:
                self.subscribe_future.result()
                self.subscribed.add(symbol)
            except Exception as exc:
                self.subscription_retry[symbol] = now + timedelta(seconds=60)
                self.state["subscription_last_error"] = {"symbol": symbol,
                    "reason": data.classify_failure(exc)}
            self.subscribe_future = None
        for symbol in sorted(self.provider_by_symbol):
            if symbol in self.subscribed or now < self.subscription_retry.get(symbol, now):
                continue
            self.subscribe_future = self.provider_jobs.submit(
                self.runtime.retain_subscription, self.owner, self.provider_by_symbol[symbol],
                period=Period.Min_1, timeout_seconds=10)
            self.subscribe_future.symbol = symbol
            break

    def _record(self, bar: dict, *, persisted: bool = False) -> None:
        symbol = bar["symbol"]
        if symbol not in self.bars:
            self.bars[symbol] = rules.stored_bars(symbol, self.day.isoformat(), self.path)
        if not persisted:
            from .options_input_commit_fence import InputCommitBusy
            try:
                rules.save_bar(bar, self.day.isoformat(), self.path)
            except InputCommitBusy as exc:
                exc.raw_bar = bar
                raise
        opened = rules.timestamp(bar["open_at"])
        old = self.bars[symbol].get(opened)
        if old is None or rules.timestamp(bar["received_at"]) >= rules.timestamp(old["received_at"]):
            self.bars[symbol][opened] = bar
        lane = getattr(self, "trend_lane", None)
        if lane is not None:
            lane.enqueue(symbol, self.day, self.bars[symbol].values(), self.manifest["scope_hash"],
                         self.trend_references.get(symbol))

    def _recheck_opening_source(self, symbol, day, checkpoint):
        lane = self.trend_recovery_lane
        if lane is None or day != self.day:
            return
        opening, _ = session_bounds_utc(day)
        bars = dict(self.bars.get(symbol, {}))
        if opening in bars:
            bars[opening] = {**bars[opening], "source_recheck_required": True}
        from .options_opening_momentum import load_policy
        lane.observe(symbol, checkpoint - timedelta(minutes=1), bars, load_policy(), self.manifest["scope_hash"])

    def consume(self, item: tuple, now: datetime, *, _saved_bar=None) -> None:
        from longbridge.openapi import Period
        from .stock_signals import _parse_longbridge_time
        kind, provider, event, received_at = item
        if kind != "candle" or not getattr(event, "is_confirmed", False) or getattr(event, "period", None) != Period.Min_1:
            return
        symbol = self.mapping.get(provider)
        if not symbol:
            return
        candle = event.candlestick
        opened = _parse_longbridge_time(candle.timestamp)
        if opened is None:
            return
        opening, closing = session_bounds_utc(self.day)
        if not opening <= opened < closing:
            return
        end = opened + timedelta(minutes=1)
        received = rules.timestamp(received_at)
        bar = {"symbol": symbol, "interval": "1m", "open_at": opened.isoformat(),
               "available_at": end.isoformat(), "received_at": received.isoformat(),
               "closed": True, "provider_confirmed": True,
               "source": "LONGBRIDGE_CONFIRMED_PUSH", "raw_timestamp": str(candle.timestamp),
               "turnover_source": "NATIVE", "currency": "USD"}
        for key in ("open", "high", "low", "close", "volume", "turnover"):
            value = getattr(candle, key, None)
            bar[key] = float(value) if value is not None else None
        if opened < opening + timedelta(minutes=30):
            from .options_opening_trend_sdk import candle_evidence
            bar["sdk_evidence"] = candle_evidence(candle, provider_symbol=provider,
                interface="QuoteContext.set_on_candlestick", received_at=received.isoformat(), confirmed=True)
        self._record(bar if _saved_bar is None else _saved_bar)
        self._queue_missing_predecessors(symbol, opened, received)
        if self.recovery_lane is not None:
            self.recovery_lane.observe(symbol, opened, self.bars[symbol], rules.load_policy(), self.manifest["scope_hash"])
        if received < end:
            self.recovery_pending[(symbol, opened)] = "EARLY_CONFIRMED_PUSH"
            return
        self.evaluate_bar(symbol, opened, now)

    def evaluate_bar(self, symbol: str, opened: datetime, now: datetime) -> None:
        if (symbol, opened) in self.evaluated:
            return
        opening, closing = session_bounds_utc(self.day)
        bar = self.bars.get(symbol, {}).get(opened)
        if not bar:
            return
        end = opened + timedelta(minutes=1)
        deadline = min(end + timedelta(seconds=rules.load_policy()["signal_deadline_seconds"]),
                       closing - timedelta(minutes=self.entry_cutoff_minutes))
        if now <= deadline and (now < end or rules.timestamp(bar["received_at"]) < end):
            self.recovery_pending.setdefault((symbol, opened), "EARLY_CONFIRMED_PUSH")
            return
        required = min(int((opened - opening).total_seconds() // 60), rules.load_policy()["prior_intraday_bars_max"])
        previous = [self.bars[symbol].get(opened - timedelta(minutes=n)) for n in range(required, 0, -1)]
        if any(item is None for item in previous):
            previous = [item for item in previous if item is not None]
        slot = opened.astimezone(rules.NY).strftime("%H:%M")
        late = now > deadline
        history = None if late else data.history_context(symbol, self.day, self.path, slot=slot)
        schedule = {"is_trading_day": True, "regular_open_utc": opening.isoformat(),
                    "regular_close_utc": closing.isoformat()}
        event = {"status": "NOT_EVALUATED_QUALIFICATION_LANE", "trade_eligible": False,
                 "coverage_until": (closing - timedelta(minutes=30)).isoformat()}
        results = []
        for right in ("CALL", "PUT"):
            if late:
                result = rules.missed_evaluation(symbol=symbol, right=right, bar=bar,
                    scope_hash=self.manifest["scope_hash"], now=now, deadline=deadline)
            else:
                result = rules.evaluate(symbol=symbol, right=right, bar=bar, previous=previous,
                    history=history, schedule=schedule, scope_hash=self.manifest["scope_hash"],
                    now=now, event=event)
            result["runtime_mode"] = "SHADOW_RESEARCH"
            result["contract_qualification"] = {"status": "QUEUED_AFTER_NUMERIC_TRIGGER" if result["state"] in
                {"NUMERIC_PASS", "NUMERIC_PASS_EVENT_PENDING"} else
                "NOT_EVALUATED_AFTER_DEADLINE" if late else "NOT_APPLICABLE_NO_NUMERIC_TRIGGER"}
            results.append(result)
        rules.persist_evaluations(results, self.path)
        last_bar = self.state.get("last_persisted_bar")
        self.state.update(last_persisted_bar=max(end, rules.timestamp(last_bar) if last_bar else end).isoformat(),
                          last_evaluation_at=now.isoformat())
        for result in results:
            lane = getattr(self, "qualification_lane", None)
            if lane is not None:
                lane.enqueue(result, now)
        if (len(previous) == required and all(
                rules.timestamp(item["received_at"]) >= rules.timestamp(item["available_at"])
                for item in previous)) or now > opened + timedelta(minutes=1, seconds=30):
            self.evaluated.add((symbol, opened))
        self.hub.publish({"type": "options_one_minute_progress", "symbol": symbol,
                          "bar_end": (opened + timedelta(minutes=1)).isoformat(),
                          "at": now.isoformat(), "qualified_signal": False})

    def _recover(self, symbol: str, opened: datetime, *, snapshot_count=8) -> dict:
        from longbridge.openapi import AdjustType, Period
        from .stock_signals import _parse_longbridge_time
        requested = self.clock()
        if requested < opened + timedelta(minutes=1):
            return {"status": "PRE_BOUNDARY_REQUEST_NOT_EVIDENCE"}
        opening, closing = session_bounds_utc(opened.astimezone(rules.NY).date())
        rows = self.runtime.candlesticks(self.provider_by_symbol[symbol], Period.Min_1, snapshot_count,
                                         AdjustType.NoAdjust, 4)
        received = self.clock()
        bars = []
        for candle in rows:
            candle_open = _parse_longbridge_time(candle.timestamp)
            if (candle_open is None or not opening <= candle_open < closing
                    or candle_open + timedelta(minutes=1) > requested):
                continue
            bar = {"symbol": symbol, "interval": "1m", "open_at": candle_open.isoformat(),
                   "available_at": (candle_open + timedelta(minutes=1)).isoformat(),
                   "received_at": received.isoformat(), "request_started_at": requested.isoformat(),
                   "closed": True, "source": "LONGBRIDGE_POST_BOUNDARY_SNAPSHOT",
                   "raw_timestamp": str(candle.timestamp), "provider_confirmed": None,
                   "turnover_source": "NATIVE", "currency": "USD"}
            for key in ("open", "high", "low", "close", "volume", "turnover"):
                value = getattr(candle, key, None)
                bar[key] = float(value) if value is not None else None
            if candle_open < opening + timedelta(minutes=30):
                from .options_opening_trend_sdk import candle_evidence
                bar["sdk_evidence"] = candle_evidence(candle,
                    provider_symbol=self.provider_by_symbol[symbol], interface="QuoteContext.candlesticks",
                    received_at=received.isoformat(), requested_at=requested.isoformat())
            bars.append(bar)
        target = next((bar for bar in bars if rules.timestamp(bar["open_at"]) == opened), None)
        if target is not None:
            return {"status": "RECOVERED", "bar": target, "bars": bars}
        return {"status": "MISSING_CLOSED_BAR"}

    def _process_trend_recovery(self, now):
        from .options_opening_momentum import load_policy
        lane = self.trend_recovery_lane
        if lane is None:
            return
        p = load_policy()
        opening, closing = session_bounds_utc(self.day)
        bucket = min(int((now-opening).total_seconds()//300)*5,
                     int((closing-opening).total_seconds()//60))
        symbols = set(lane.risk_symbols)
        if 5 <= bucket <= 25:
            symbols.update(self.provider_by_symbol)
        key = self.day, bucket, tuple(sorted(symbols))
        if bucket > 0 and key != self.trend_recovery_bucket:
            opened = opening + timedelta(minutes=bucket-1)
            for symbol in sorted(symbols & self.provider_by_symbol.keys()):
                lane.observe(symbol, opened, self.bars.get(symbol, {}), p, self.manifest['scope_hash'])
            self.trend_recovery_bucket = key
        for _ in range(3):
            delivery = lane.tick(self.day.isoformat(), p, self.manifest['scope_hash'])
            if delivery is None:
                break
            if delivery['job']['session'] == self.day.isoformat():
                for bar in delivery['bars']:
                    self._record(bar, persisted=True)
        self.state['trend_input_recovery'] = dict(lane.state)

    def _process_recovery(self, now: datetime) -> None:
        if self.recovery_lane is not None:
            result = self.recovery_lane.tick(self.day.isoformat(), rules.load_policy(), self.manifest["scope_hash"])
            self.state["recovery_queue"] = dict(self.recovery_lane.state)
            if result and result["job"]["session"] == self.day.isoformat():
                symbol = result["job"]["symbol"]
                dependent = rules.timestamp(result["job"]["payload"]["dependent_bar"])
                targets = {opened for pending_symbol, opened in self.recovery_pending if pending_symbol == symbol}
                targets.add(dependent)
                recovered = []
                for bar in result["bars"]:
                    self._record(bar, persisted=True)
                    opened = rules.timestamp(bar["open_at"])
                    recovered.append(opened)
                # A snapshot contains supporting bars, not eight new scan requests.
                # Current qualification gets priority over expired audit work.
                for opened in sorted(targets, reverse=True):
                    current = self.clock()
                    if current > opened + timedelta(minutes=1, seconds=30):
                        self.recovery_pending.setdefault((symbol, opened), "RECOVERED_LATE_AUDIT")
                        continue
                    self.recovery_pending.pop((symbol, opened), None)
                    self.recovery_deadlines.pop((symbol, opened), None)
                    self.evaluate_bar(symbol, opened, current)
                self.state["recovery_last_snapshot_bars"] = len(recovered)
            expired_processed = 0
            for key in list(self.recovery_pending):
                if now > self.recovery_deadlines.get(key, key[1] + timedelta(minutes=1, seconds=30)):
                    self.recovery_pending.pop(key, None)
                    self.recovery_deadlines.pop(key, None)
                    self.evaluate_bar(*key, now)
                    expired_processed += 1
                    if expired_processed >= 1:
                        break
            return
        if self.recovery_future and self.recovery_future.done():
            symbol, opened = self.recovery_target
            try:
                result = self.recovery_future.result()
                if opened.astimezone(rules.NY).date() != self.day:
                    self.state["recovery_last"] = "DISCARDED_PREVIOUS_SESSION"
                elif result["status"] == "RECOVERED":
                    recovered = []
                    for bar in result.get("bars", [result["bar"]]):
                        bar_open = rules.timestamp(bar["open_at"])
                        key = symbol, bar_open
                        if (bar.get("symbol") != symbol or bar.get("interval") != "1m"
                                or bar_open.astimezone(rules.NY).date() != self.day
                                or rules.timestamp(bar["received_at"]) < bar_open + timedelta(minutes=1)
                                or (key != (symbol, opened) and key not in self.recovery_pending)):
                            continue
                        self._record(bar)
                        recovered.append(bar_open)
                        self.recovery_pending.pop(key, None)
                        self.recovery_deadlines.pop(key, None)
                        self.recovery_retry_at.pop(key, None)
                    # Install the whole shared snapshot before evaluating dependent minutes.
                    for bar_open in sorted(set(recovered)):
                        self.evaluate_bar(symbol, bar_open, now)
                        self._reevaluate_following(symbol, bar_open, now)
                    self.state["recovery_last_snapshot_bars"] = len(recovered)
                else:
                    self.recovery_pending[(symbol, opened)] = result["status"]
                    self.recovery_retry_at[(symbol, opened)] = now + timedelta(seconds=2)
            except Exception as exc:
                self.recovery_pending[(symbol, opened)] = data.classify_failure(exc)
                self.recovery_retry_at[(symbol, opened)] = now + timedelta(seconds=2)
            self.recovery_future = None
            self.recovery_target = None
        if self.recovery_future or now < self.next_recovery_at:
            return
        cutoff = session_bounds_utc(self.day)[1] - timedelta(minutes=self.entry_cutoff_minutes)
        # Give unattempted symbols priority within a minute; failures cannot monopolize recovery.
        pending = sorted(self.recovery_pending, key=lambda key: (
            key[1], self.recovery_attempted.get(key[0], datetime.min.replace(tzinfo=UTC)), key[0]))
        for symbol, opened in pending:
            end = opened + timedelta(minutes=1)
            deadline = min(self.recovery_deadlines.get((symbol, opened), end + timedelta(seconds=30)), cutoff)
            if now > deadline:
                self.recovery_pending.pop((symbol, opened), None)
                self.recovery_deadlines.pop((symbol, opened), None)
                self.recovery_retry_at.pop((symbol, opened), None)
                self.evaluate_bar(symbol, opened, now)
                self._reevaluate_following(symbol, opened, now)
                continue
            if now < end:
                continue
            if now < self.recovery_retry_at.get((symbol, opened), now):
                continue
            self.next_recovery_at = now + timedelta(seconds=0.5)
            self.recovery_target = symbol, opened
            self.recovery_attempted[symbol] = now
            self.recovery_future = self.provider_jobs.submit(self._recover, symbol, opened)
            break

    def _publish_exit_alert(self, alert: dict, now: datetime) -> None:
        from urllib.parse import urlencode
        from .stock_store import connect
        alert_id = f"one-minute-exit-{alert['alert_id']}"
        payload = {"type": "options_one_minute_exit_review", "severity": "RISK",
                   "alert_id": alert_id, "position_id": alert["position_id"],
                   "symbol": alert["symbol"], "right": alert["right"],
                   "contract_id": alert["contract_id"], "reason": alert["reason"],
                   "title": "KQUANT · Review reported position / 核查自报持仓",
                   "body": f"{alert['symbol']} {alert['right']} · {alert['reason']} · Exit not confirmed / 未确认退出",
                   "tag": alert_id, "paper_enabled": False, "real_orders_enabled": False,
                   "url": "/?" + urlencode({"workspace": "options", "view": "plans"})}
        stamp = now.isoformat()
        with connect(self.main_db) as connection:
            inserted = connection.execute("""INSERT OR IGNORE INTO alert_events
                (alert_id,instruction_id,dedupe_key,symbol,severity,event_type,title,message,payload_json,
                 delivery_status,acknowledged_at,created_at,updated_at)
                 VALUES (?,NULL,?,?,'RISK','options_one_minute_exit_review',?,?,?,'web_queued',NULL,?,?)""",
                (alert_id, alert_id, alert["symbol"], payload["title"], payload["body"],
                 rules.canonical(payload), stamp, stamp)).rowcount
            connection.commit()
        if inserted:
            self.hub.publish({"type": "options_one_minute_exit_review", "alert_id": alert_id,
                              "position_id": alert["position_id"], "reason": alert["reason"],
                              "exit_confirmed": False})

    def _price_fact_quotes(self, rows, session, now, reviews, *, persist=True):
        from contextlib import nullcontext
        from .options_price_facts import bind, prepare_binding, persist_bindings, PRICE_FACT_BATCH_BOUND
        from .options_opening_trend_reference import ROOT
        root = getattr(self.trend_lane, "source_root", None) or ROOT
        for start in range(0, len(rows), PRICE_FACT_BATCH_BOUND):
            group = rows[start:start + PRICE_FACT_BATCH_BOUND]
            bindings = [bind(row, symbol=row["symbol"], session=session.isoformat(),
                             now=now, reviews=reviews, root=root) for row in group]
            if persist:
                guard = getattr(self.trend_lane, "_journal_guard", nullcontext)
                from .options_input_commit_fence import commit_fence
                with commit_fence(), guard():
                    saved = persist_bindings(self.trend_lane.path, bindings)
            else:
                # Live journal admission retains these inputs; the accepted CAS
                # transaction persists facts together with evaluation evidence.
                saved = [prepare_binding(value) for value in bindings]
            yield from zip(group, saved)

    def _refresh_trend_references(self, now: datetime) -> None:
        from .options_opening_trend_reference import build, load_reviews
        if self.trend_reference_future is not None and self.trend_reference_future.done():
            try:
                batch = self.trend_reference_future.result()
                reviews = load_reviews()
                rows = [row for row in batch.get("items", []) if row.get("symbol") in self.provider_by_symbol]
                for row, binding in self._price_fact_quotes(rows, self.day, now, reviews, persist=False):
                    symbol = row.get("symbol")
                    if symbol in self.provider_by_symbol:
                        row["session_price_binding"] = binding
                        self.trend_references[symbol] = build(row, symbol=symbol,
                            session=self.day.isoformat(), now=now, reviews=reviews)
                        if self.trend_lane:
                            self.trend_lane.reference_ready(symbol, self.day, self.trend_references[symbol])
                self.state["trend_reference"] = {
                    "received_symbols": len(self.trend_references),
                    "verified_symbols": None,
                    "verification_stage": "AWAITING_HISTORY_ASSEMBLY",
                    "session_bindings": {state: sum(
                        row.get("session_price_binding", {}).get("status", "NOT_BOUND") == state
                        for row in batch.get("items", [])) for state in ("VERIFIED", "PREPARED_WITH_GAPS")},
                    "checked_at": now.isoformat()}
            except Exception as exc:
                self.state["trend_reference"] = {"error": type(exc).__name__, "checked_at": now.isoformat()}
            self.trend_reference_future = None
        opening, _ = session_bounds_utc(self.day)
        if (self.trend_reference_future is not None or now < self.next_trend_reference_at
                or not opening - timedelta(hours=1) <= now < opening + timedelta(minutes=30)
                or self.risk_quote_future is not None or now.second < 10):
            return
        self.trend_reference_future = self.provider_jobs.submit(
            self._collect_trend_reference_quotes, list(self.provider_by_symbol))
        self.next_trend_reference_at = now + timedelta(seconds=60)

    def _prepare_price_facts(self, now):
        """One bounded shared-connection preflight per upcoming session, not a scan."""
        from .options_opening_trend_reference import load_reviews
        if self.price_preflight_future is not None:
            if not self.price_preflight_future.done():
                return
            target = self.price_preflight_target
            try:
                batch = self.price_preflight_future.result()
                self.price_preflight_quotes[target] = batch.get("items", [])
                reviews = load_reviews()
                self.price_preflight_source_hash = reviews.get("source_bundle", {}).get("sha256")
                bindings = [value for _, value in self._price_fact_quotes(
                    batch.get("items", []), target, now, reviews)]
                from collections import Counter
                self.state["price_fact_preflight"] = dict(session=target.isoformat(), checked_at=now.isoformat(),
                    bound_records=len(bindings), verified_records=sum(b["status"] == "VERIFIED" for b in bindings),
                    reasons=dict(Counter(r for b in bindings for r in b["reasons"])),
                    stage="PERSISTED_PREPARATION_NOT_LIVE_SIGNAL", source="EXISTING_SHARED_CONNECTION",
                    snapshot_only=True)
            except Exception as exc:
                self.state["price_fact_preflight"] = dict(session=target.isoformat(), checked_at=now.isoformat(),
                    stage="UNAVAILABLE", error_type=type(exc).__name__, retry="REUSE_CAPTURED_QUOTES")
                self.price_preflight_write_pending = target in self.price_preflight_quotes
            self.price_preflight_future = None
        target = now.astimezone(rules.NY).date()
        while not is_trading_day(target) or session_bounds_utc(target)[1] <= now:
            target += timedelta(days=1)
        reviews = load_reviews()
        source_hash = reviews.get("source_bundle", {}).get("sha256")
        retry_identity = (target, source_hash)
        if getattr(self, "price_preflight_retry_identity", None) != retry_identity:
            self.price_preflight_retry_identity = retry_identity
            self.price_preflight_write_attempts = 0
        if (target in self.price_preflight_quotes
                and (source_hash != self.price_preflight_source_hash
                     or getattr(self, "price_preflight_write_pending", False))
                and now >= getattr(self, "price_preflight_retry_at", now)
                and self.price_preflight_write_attempts < 3):
            self.price_preflight_write_attempts += 1
            try:
                bindings = [value for _, value in self._price_fact_quotes(
                    self.price_preflight_quotes[target], target, now, reviews)]
                self.price_preflight_source_hash = source_hash
                self.price_preflight_write_pending = False
                from collections import Counter
                self.state["price_fact_preflight"] = dict(session=target.isoformat(), checked_at=now.isoformat(),
                    bound_records=len(bindings), verified_records=sum(b["status"] == "VERIFIED" for b in bindings),
                    reasons=dict(Counter(r for b in bindings for r in b["reasons"])),
                    stage="REBOUND_EXISTING_REAL_QUOTES_AFTER_SOURCE_CHANGE", provider_requests=0)
            except Exception as exc:
                # A busy research writer must not terminate the owner loop or
                # discard the captured batch. Rebinding is hash-idempotent.
                self.price_preflight_write_pending = True
                self.price_preflight_retry_at = now + timedelta(seconds=1)
                self.state["price_fact_preflight"] = dict(session=target.isoformat(), checked_at=now.isoformat(),
                    stage="WAIT_PERSIST" if self.price_preflight_write_attempts < 3 else "PERSIST_RETRY_EXHAUSTED",
                    error_type=type(exc).__name__, attempts=self.price_preflight_write_attempts,
                    retry="REUSE_CAPTURED_QUOTES", provider_requests=0)
        if target in self.price_preflight_attempted or self.risk_quote_future is not None:
            return
        from .options_two_hour_data import universe
        rows = universe(self.main_db)["items"]
        providers = {r["symbol"]: r["provider_symbol"] for r in rows if r["identity_status"] == "verified"}
        self.price_preflight_attempted.add(target)
        self.price_preflight_target = target
        self.price_preflight_future = self.provider_jobs.submit(self._collect_trend_reference_quotes, list(providers), providers)

    def _collect_trend_reference_quotes(self, symbols, provider_by_symbol=None):
        from .stock_signals import api_stock_quotes_batch
        from .options_expression import _attr, LONG_BRIDGE_TIMEOUT_SECONDS
        started = self.clock().isoformat()
        provider_by_symbol = provider_by_symbol or self.provider_by_symbol
        missing = [symbol for symbol in symbols if symbol not in self.reference_currencies]
        if missing:
            providers = {provider_by_symbol[symbol]: symbol for symbol in missing}
            try:
                rows = self.runtime.static_info(list(providers), LONG_BRIDGE_TIMEOUT_SECONDS)
                for row in rows or []:
                    native = _attr(row, "symbol")
                    symbol = providers.get(native)
                    currency = _attr(row, "currency")
                    if symbol and isinstance(currency, str) and len(currency) == 3 and currency.isupper() and currency.isascii():
                        evidence = dict(symbol=symbol, provider_symbol=native, currency=currency,
                            source="LONGBRIDGE_SECURITY_STATIC_INFO", requested_at=started,
                            received_at=self.clock().isoformat(), native_field="currency")
                        evidence["native_static_fields"] = {name: str(_attr(row, name)) for name in
                            ("exchange", "board", "name_en", "stock_derivatives") if _attr(row, name) is not None}
                        self.reference_currencies[symbol] = {**evidence, "source_hash": rules.digest(evidence)}
            except Exception as exc:
                self.state["reference_currency_error"] = type(exc).__name__
        batch = api_stock_quotes_batch(symbols, db_path=self.main_db)
        for row in batch.get("items", []):
            currency = self.reference_currencies.get(row.get("symbol"))
            if currency:
                row.update(currency=currency["currency"], currency_evidence=currency)
        return batch

    def _monitor_reported_positions(self, now: datetime) -> None:
        from .options_one_minute_manual import exit_reasons, manual_status, persist_exit_alert, persist_monitor_state
        if self.risk_quote_future and self.risk_quote_future.done():
            position = self.risk_quote_position
            try:
                evidence = self.risk_quote_future.result()
                snapshot = evidence["option"]
                latest = manual_status(self.path, limit=1000)["positions"]
                position = next((row for row in latest if row["position_id"] == position["position_id"]
                                 and row["contract_id"] == position["contract_id"] and row["open_quantity"] > 0), None)
                quote = {"contract_id": snapshot.get("contract_symbol"),
                         "multiplier": snapshot.get("contract_multiplier"),
                         "bid": snapshot.get("bid"), "depth_status": snapshot.get("depth_status"),
                         "bbo_received_at": snapshot.get("bbo_received_at")}
                bars = list(self.bars.get(position["symbol"], {}).values()) if position else []
                updates = []
                for reason in exit_reasons(position, bars, now=self.clock(), quote=quote,
                                          underlying_quote=evidence["underlying"], monitor_updates=updates) if position else []:
                    persist_exit_alert(position, reason, path=self.path)
                for update in updates:
                    persist_monitor_state(position, update, path=self.path)
                self.state["risk_quote"] = {"status": "REFERENCE_ONLY" if position else "POSITION_ALREADY_CLOSED", "position_id": self.risk_quote_position["position_id"],
                                             "bbo_received_at": quote["bbo_received_at"],
                                             "errors": evidence["errors"]}
            except Exception as exc:
                self.state["risk_quote"] = {"status": "UNAVAILABLE", "reason": data.classify_failure(exc)}
            self.risk_quote_future = None
            self.risk_quote_position = None
        if now < self.next_risk_at:
            return
        self.next_risk_at = now + timedelta(seconds=2)
        status = manual_status(self.path, limit=1000)
        open_positions = [row for row in status["positions"] if row["open_quantity"] > 0]
        trend_recovery = getattr(self, 'trend_recovery_lane', None)
        if trend_recovery is not None:
            trend_recovery.risk_symbols = {row['symbol'] for row in open_positions}
        self.state["reported_open_positions"] = len(open_positions)
        for position in open_positions:
            if position["symbol"] not in self.bars:
                self.bars[position["symbol"]] = rules.stored_bars(position["symbol"], now.astimezone(rules.NY).date().isoformat(), self.path)
            updates = []
            for reason in exit_reasons(position, list(self.bars[position["symbol"]].values()), now=now, monitor_updates=updates):
                persist_exit_alert(position, reason, path=self.path, now=now)
            for update in updates:
                persist_monitor_state(position, update, path=self.path)
        # Restore page alerts after a crash; system notification delivery remains deferred.
        for alert in status["alerts"]:
            if any(row["position_id"] == alert["position_id"] for row in open_positions):
                self._publish_exit_alert(alert, now)
        if open_positions and self.risk_quote_future is None and now >= self.next_risk_quote_at:
            from .options_reported_risk_quotes import fetch
            position = open_positions[self.risk_cursor % len(open_positions)]
            self.risk_cursor += 1
            self.risk_quote_position = position
            self.risk_quote_future = self.risk_jobs.submit(
                fetch, dict(position), self.main_db)
            self.next_risk_quote_at = now + timedelta(seconds=5)

    def _drain_events(self, *, budget_seconds=0.5) -> None:
        from .options_input_commit_fence import InputCommitBusy
        started = monotonic()
        for _ in range(300):
            if monotonic() - started >= budget_seconds:
                break
            if self._pending_input_commit is None:
                try:
                    self._pending_input_commit = self.sink.get_nowait(), None
                except queue.Empty:
                    break
            item, saved_bar = self._pending_input_commit
            try:
                self.consume(item, self.clock(), _saved_bar=saved_bar)
            except InputCommitBusy as exc:
                self._pending_input_commit = item, getattr(exc, 'raw_bar', saved_bar)
                self.state.update(input_commit_state='WAIT_COMMIT',
                    input_commit_busy_count=self.state.get('input_commit_busy_count', 0)+1,
                    input_commit_pending_received_at=str(item[3]))
                return  # Existing owner tick retries once; do not drain past this item.
            self._pending_input_commit = None
            self.state.update(input_commit_state='COMMITTED', input_commit_pending_received_at=None)

    def run(self, stop) -> None:
        eligibility_lane = None
        trend_qualification_lane = None
        resources = []
        try:
            self._stage("INIT_ROLE_PATHS")
            from .options_data_paths import resolve_stores
            stores = resolve_stores(rules.ROOT)
            self.state["store_paths"] = {key: str(value) for key, value in stores.items()}
            self._stage("INIT_ELIGIBILITY")
            from .options_one_minute_eligibility import EligibilityLane
            eligibility_lane = EligibilityLane(self.main_db, self.path, clock=self.clock)
            resources.append(("eligibility", eligibility_lane.close))
            from .options_one_minute_pipeline import QualificationLane
            from .options_one_minute_recovery import RecoveryLane
            self._stage("INIT_QUALIFICATION")
            self.qualification_lane = QualificationLane(self.main_db, self.path, queue_path=stores["full_watch"], clock=self.clock)
            resources.append(("qualification", self.qualification_lane.close))
            self._stage("INIT_RECOVERY")
            self.recovery_lane = RecoveryLane(self.path, self._recover, queue_path=stores["full_watch"], clock=self.clock)
            resources.append(("recovery", self.recovery_lane.close))
            self.recovery_lane.start()
            from .options_opening_trend_runtime import TrendLane
            self._stage("INIT_OPENING_RESEARCH")
            self.trend_lane = TrendLane(self.path, self.hub,
                path=stores["opening_research"], clock=self.clock,
                on_recheck=self._recheck_opening_source)
            resources.append(("opening_research", self.trend_lane.close))
            from .options_opening_trend_recovery import TrendRecoveryLane
            self._stage("INIT_OPENING_RECOVERY")
            self.trend_recovery_lane = TrendRecoveryLane(self.path,
                lambda symbol, opened: self._recover(symbol, opened, snapshot_count=30),
                queue_path=self.trend_lane.path, clock=self.clock)
            resources.append(("opening_recovery", self.trend_recovery_lane.close))
            self.trend_recovery_lane.start()
            from .options_opening_trend_pipeline import QualificationLane as TrendQualificationLane
            self._stage("INIT_OPENING_QUALIFICATION")
            trend_qualification_lane = TrendQualificationLane(self.main_db, self.trend_lane.path, self.hub,
                clock=self.clock, write_guard=self.trend_lane._journal_guard)
            resources.append(("opening_qualification", trend_qualification_lane.close))
            ai_config=rules.ROOT/'config/options_opening_research_ai.json'
            ai_receipt=rules.ROOT/'config/review_acceptances/opening_ai_budget.json'
            isolated=stores['signal_copilot'].parent
            if stores['signal_copilot'].name.startswith('TEST_ONLY-') and (isolated/'TEST_ONLY.json').is_file():
                ai_config=isolated/'config/options_opening_research_ai.json'
                ai_receipt=isolated/'config/review_acceptances/opening_ai_budget.json'
            if ai_config.is_file():
                from .options_research_ai_worker import ResearchAIWorker
                ai_worker=ResearchAIWorker(research_path=stores['opening_research'],copilot_path=stores['signal_copilot'],
                    config_path=ai_config,receipt_path=ai_receipt,
                    cursor_path=stores['signal_copilot'].parent/'opening-ai-cursor.json',hub=self.hub,clock=self.clock)
                self.state['research_ai']=ai_worker.state
                resources.append(('research_ai',ai_worker.close))
            while not stop.is_set():
                try:
                    if not self.state.get("first_loop_at"):
                        self.state["first_loop_at"] = self.clock().isoformat()
                    self.state["loop_count"] = self.state.get("loop_count", 0) + 1
                    now = self.clock()
                    day = now.astimezone(rules.NY).date()
                    self._prepare_price_facts(now)
                    if not is_trading_day(day):
                        self._stage("OFF_SESSION_POSITION_RISK")
                        self._monitor_reported_positions(now)
                        self.state.update(state="WAIT_MARKET", last_cycle_at=now.isoformat())
                        self._stage("WAIT_MARKET")
                        stop.wait(5)
                        continue
                    self._stage("PREPARE_SESSION")
                    self.prepare(now)
                    if self.trend_lane:
                        self.trend_lane.tick_registered(self.manifest['items'],self.day,self.manifest['scope_hash'],now)
                    revision = eligibility_lane.tick(now)
                    self.state["current_eligibility"] = dict(eligibility_lane.state)
                    if revision:
                        self.hub.publish({"type": "options_one_minute_eligibility", "revision": revision})
                    opening, closing = session_bounds_utc(day)
                    self._stage("CONSUME_BARS")
                    self._drain_events()
                    now = self.clock()
                    if opening <= now < closing:
                        self._stage("RECOVER_BARS")
                        self._process_recovery(now)
                        self._process_trend_recovery(now)
                        self._stage("CONTRACT_QUALIFICATION")
                        qualified = self.qualification_lane.tick(now)
                        self.state["qualification_queue"] = dict(self.qualification_lane.state)
                        if qualified:
                            self.state["qualification_last"] = {
                                "evaluation_id": qualified["evaluation_id"],
                                "blockers": qualified.get("qualification_blockers", []),
                                "contract_status": qualified.get("contract_qualification", {}).get("status"),
                                "at": qualified["evaluated_at"], "mode": "SHADOW_RESEARCH"}
                            self.hub.publish({"type": "options_one_minute_signal" if qualified.get("published_candidate") else "options_one_minute_progress",
                                "symbol": qualified["symbol"], "evaluation_id": qualified["evaluation_id"],
                                "at": now.isoformat(), "qualified_signal": bool(qualified.get("published_candidate"))})
                    self._stage("POSITION_RISK")
                    self._monitor_reported_positions(now)
                    self._refresh_trend_references(now)
                    self.state["opening_trend"] = dict(self.trend_lane.state)
                    self.state["opening_momentum"] = dict(self.trend_lane.state.get("strategies", {}).get("opening_momentum", {}))
                    assembled = self.trend_lane.state.get("assembled_reference", {})
                    if assembled.get("session") == self.day.isoformat():
                        self.state.setdefault("trend_reference", {}).update(
                            verified_symbols=assembled["verified_symbols"],
                            verification_stage="HISTORY_AND_QUOTE_ASSEMBLED",
                            assembled=assembled)
                    self.state["opening_trend"]["qualification"] = dict(trend_qualification_lane.state)
                    self.state["opening_momentum"]["qualification"] = dict(trend_qualification_lane.state)
                    # Queue market evidence and risk work before lower-priority history requests.
                    if now < closing - timedelta(minutes=self.entry_cutoff_minutes) and (now < opening or now.second >= 35):
                        self._stage("SUBSCRIPTIONS")
                        self._start_subscription(now)
                    self._stage("HISTORY_PREWARM")
                    self._start_prewarm(now)
                    if now < opening + timedelta(minutes=30):
                        self.trend_lane.warm_history(sorted(self.provider_by_symbol), day)
                    self.state.update(state=worker_phase(now, opening, closing, self.entry_cutoff_minutes),
                                      subscribed_symbols=len(self.subscribed), event_queue_size=self.sink.qsize(),
                                      pending_boundary_recovery=len(self.recovery_pending),
                                      last_cycle_at=now.isoformat())
                    if now >= self.next_status_at:
                        self.hub.publish({"type": "options_one_minute_progress", "state": self.state["state"],
                                          "at": now.isoformat(), "qualified_signal": False})
                        self.next_status_at = now + timedelta(seconds=5)
                    self._stage("WAIT_NEXT_CYCLE")
                    stop.wait(0.05 if opening <= now < closing else 1)
                except Exception as exc:
                    self.state.update(state="DEGRADED", error_type=type(exc).__name__,
                                      reason=data.classify_failure(exc), last_cycle_at=datetime.now(UTC).isoformat(),
                                      cycle_error_frames=[{"file": frame.filename, "line": frame.lineno, "function": frame.name}
                                          for frame in traceback.extract_tb(exc.__traceback__)[-8:]])
                    stop.wait(5)
        except Exception as exc:
            self.state.update(state="FAILED_RUNTIME" if self.state.get("first_loop_at") else "FAILED_INIT",
                error_id=uuid.uuid4().hex, error_type=type(exc).__name__,
                sqlite_errorname=getattr(exc, "sqlite_errorname", None),
                failed_at=datetime.now(UTC).isoformat(), failed_stage=self.state.get("stage"),
                pid=os.getpid(), thread=threading.current_thread().name,
                candidate=os.environ.get("KQUANT_BACKEND_RELEASE_ID"),
                error_frames=[{"file": frame.filename, "line": frame.lineno, "function": frame.name}
                              for frame in traceback.extract_tb(exc.__traceback__)[-12:]])
        finally:
            cleanup_errors = []
            for name, close in reversed(resources):
                try:
                    close()
                except Exception as exc:
                    cleanup_errors.append({"resource": name, "error_type": type(exc).__name__})
            self.provider_jobs.shutdown(wait=False, cancel_futures=True)
            self.risk_jobs.shutdown(wait=False, cancel_futures=True)
            if self.subscribed:
                try:
                    self.runtime.release_subscriptions(self.owner)
                except Exception as exc:
                    cleanup_errors.append({"resource": "subscriptions", "error_type": type(exc).__name__})
            self.state.update(stopped_at=self.clock().isoformat(), cleanup_errors=cleanup_errors)
            owners = [self, *(getattr(close, "__self__", None) for _, close in resources)]
            owners += [getattr(owner, "history", None) for owner in owners if owner is not None]
            owned_threads = set()
            for owner in owners:
                for value in vars(owner).values() if owner is not None else ():
                    threads = value._threads if isinstance(value, ThreadPoolExecutor) else (
                        (value,) if isinstance(value, threading.Thread) else ())
                    owned_threads.update(threads)
            cleanup_deadline = monotonic() + .5
            for thread in owned_threads:
                if thread is not threading.current_thread() and thread.is_alive():
                    thread.join(timeout=max(0, cleanup_deadline - monotonic()))
            alive = {thread.name for thread in owned_threads if thread.is_alive()}
            self.state["cleanup_pending_threads"] = sorted(alive)
            self.state["cleanup_complete"] = not cleanup_errors and not alive
            if not self.state.get("error_id"):
                self.state["state"] = "STOPPED" if self.state["cleanup_complete"] else "CLEANUP_PENDING"
