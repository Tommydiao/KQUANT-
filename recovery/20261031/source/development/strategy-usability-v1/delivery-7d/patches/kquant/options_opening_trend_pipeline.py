"""Bounded research qualification continuations on the shared provider connection."""
from datetime import UTC, date, datetime, timedelta
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from threading import Event, Lock, Thread
from time import monotonic
from contextlib import nullcontext

from . import options_one_minute as common
from . import options_opening_trend as trend
from . import options_opening_trend_jobs as jobs
from . import options_opening_trend_store as store
from .options_opening_trend_contracts import compare, preferred_from_inspections, reference_from_inspections


def contract_record(snapshot, *, evidence=None, now=None, root=None, chain_evidence=None):
    # Neither a multiplier of 100 nor contract_size proves deliverables or depth units.
    row = {"contract_id": snapshot.get("contract_symbol"), "underlying": snapshot.get("underlying_symbol"),
            "right": snapshot.get("direction"), "expiry_date": snapshot.get("expiry_date"),
            "strike": snapshot.get("strike_price"), "quote_currency": snapshot.get("currency"),
            "delta": snapshot.get("delta"), "multiplier": None,
            "raw_multiplier": snapshot.get("contract_multiplier"), "multiplier_status": "UNVERIFIED",
            "deliverable": "UNKNOWN", "adjusted": None, "bid": snapshot.get("bid"), "ask": snapshot.get("ask"),
            "bid_size": None, "ask_size": None, "raw_bid_size": snapshot.get("bid_size"),
            "raw_ask_size": snapshot.get("ask_size"), "size_unit_status": "UNVERIFIED_NOT_ASSUMED_CONTRACTS",
            "snapshot": snapshot, "provider_standard_evidence": chain_evidence}
    from .options_opening_trend_reference import multiplier_matches, reviewed_contract_proof, contract_proofs, ROOT
    proof = evidence or {}
    now = now or datetime.now(UTC)
    proofs = contract_proofs(row, proof)
    units = reviewed_contract_proof(proofs["depth_units"], root=root or ROOT, now=now)
    deliverable = reviewed_contract_proof(proofs["deliverable"], root=root or ROOT, now=now)
    multiplier = reviewed_contract_proof(proofs["quote_multiplier"], root=root or ROOT, now=now)
    if units and units.get("interface") == "US_OPTION_DEPTH" and common.finite(units.get("raw_units_per_contract")) and units["raw_units_per_contract"] > 0:
        factor = units["raw_units_per_contract"]
        for side in ("bid", "ask"):
            raw = row["raw_" + side + "_size"]
            row[side + "_size"] = raw / factor if common.finite(raw) else None
        row.update(size_unit_status="VERIFIED_CONTRACTS", quantity_evidence=units)
    if (deliverable and deliverable.get("contract_symbol") == row["contract_id"]
            and deliverable.get("underlying") == row["underlying"]
            and deliverable.get("deliverable_type") == "STANDARD" and deliverable.get("adjusted") is False):
        row.update(deliverable="STANDARD", adjusted=False, deliverable_evidence=deliverable)
    if multiplier and multiplier_matches(multiplier, {**row, "multiplier": row["raw_multiplier"],
                                                       "multiplier_status": "VERIFIED_NATIVE_FIELD"}):
        row.update(multiplier=row["raw_multiplier"], multiplier_status="VERIFIED_NATIVE_FIELD", multiplier_evidence=multiplier)
    return row


class Services:
    def __init__(self, main_db, *, clock=None):
        self.main_db = main_db
        self.clock = clock or (lambda: datetime.now(UTC))
        self._static_lock = Lock()
        self._static_cache, self._static_pending = {}, {}

    def _static(self, key, loader):
        now = self.clock()
        key = (now.astimezone(common.NY).date().isoformat(), *key)
        with self._static_lock:
            cached = self._static_cache.get(key)
            if cached and 0 <= (now - cached[0]).total_seconds() < 60:
                return deepcopy(cached[1])
            future = self._static_pending.get(key)
            owner = future is None
            if owner:
                future = self._static_pending[key] = Future()
        if not owner:
            from .options_expression import LONG_BRIDGE_TIMEOUT_SECONDS
            return deepcopy(future.result(timeout=LONG_BRIDGE_TIMEOUT_SECONDS))
        try:
            value = loader()
            with self._static_lock:
                if value.get("provider_status") == "available":
                    self._static_cache[key] = (now, deepcopy(value))
                    while len(self._static_cache) > 1024:
                        oldest = min(self._static_cache, key=lambda item: self._static_cache[item][0])
                        self._static_cache.pop(oldest)
            future.set_result(value)
            return deepcopy(value)
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._static_lock:
                self._static_pending.pop(key, None)

    def event(self, original, now, policy):
        from .options_opening_trend_events import event_context
        return event_context(self.main_db, original["symbol"], now=now, policy=policy, scope_hash=original["scope_hash"])

    def expiries(self, symbol):
        from .options_expression import option_expiries
        return self._static(("expiries", symbol), lambda: option_expiries(symbol))

    def chain(self, symbol, expiry):
        from .options_expression import option_chain
        return self._static(("chain", symbol, expiry), lambda: option_chain(symbol, expiry))

    def contract(self, contract_id, *, chain_evidence=None):
        from .options_expression import option_contract_snapshot
        from .options_opening_trend_reference import load_reviews, ROOT
        # Static fields are collected before prices, so this request cannot
        # renew or age a previously fetched BBO while waiting for metadata.
        metadata = self._static(("metadata", contract_id), lambda: self._contract_metadata(contract_id))
        snapshot = option_contract_snapshot(contract_id, self.main_db)
        native_currency = snapshot.get("currency")
        currency = metadata.get("currency")
        snapshot["currency_evidence"] = metadata
        if metadata.get("provider_status") == "available" and currency:
            if native_currency is not None and native_currency != currency:
                snapshot.update(currency=None, currency_status="CONFLICTING_NATIVE_FIELDS")
            else:
                snapshot.update(currency=currency, currency_status="VERIFIED_STATIC_RESPONSE_FIELD")
        elif native_currency is None:
            snapshot.update(currency=None, currency_status="UNAVAILABLE")
        return contract_record(snapshot,
            evidence=load_reviews(ROOT / "config/review_acceptances/options_contract_units_sources.json"), now=self.clock(),
            chain_evidence=chain_evidence)

    def _contract_metadata(self, contract_id):
        from .options_expression import _attr, _identified_option_rows, LONG_BRIDGE_TIMEOUT_SECONDS
        from .longbridge_provider import longbridge_runtime
        started = self.clock().isoformat()
        try:
            rows = list(longbridge_runtime().static_info([contract_id], LONG_BRIDGE_TIMEOUT_SECONDS) or [])
            identified, errors = _identified_option_rows(rows, [contract_id])
            row = identified.get(contract_id)
            currency = _attr(row, "currency")
            if row is None or not isinstance(currency, str) or not currency.isascii() or not currency.isupper() or len(currency) != 3:
                raise ValueError(errors.get(contract_id, "CONTRACT_CURRENCY_UNAVAILABLE"))
            evidence = {"contract_symbol": contract_id, "currency": currency,
                        "response_symbol": _attr(row, "symbol"), "currency_field": "currency",
                        "source": "LONGBRIDGE_SECURITY_STATIC_INFO", "request_started_at": started,
                        "received_at": self.clock().isoformat(), "provider_status": "available"}
            return {**evidence, "source_hash": common.digest(evidence)}
        except Exception as exc:
            return {"contract_symbol": contract_id, "currency": None, "provider_status": "unavailable",
                    "request_started_at": started, "received_at": self.clock().isoformat(),
                    "error_type": type(exc).__name__,
                    "error_code": str(exc) if isinstance(exc, ValueError) else "CONTRACT_STATIC_METADATA_UNAVAILABLE"}

    def contract_evidence(self, row, *, now, binding=None):
        from .options_opening_trend_reference import contract_sources, load_reviews, ROOT
        return contract_sources(row,
            load_reviews(ROOT / "config/review_acceptances/options_contract_units_sources.json"),
            now=now, binding=binding)

    def greeks(self, contract_ids):
        from .options_expression import option_contract_snapshots
        return option_contract_snapshots(contract_ids, greeks_only=True)

    def spot(self, symbol):
        from .stock_signals import api_stock_quotes_batch
        rows = api_stock_quotes_batch([symbol], db_path=self.main_db)
        return next((r for r in rows.get("items", []) if r.get("symbol") == symbol and r.get("provider_status") == "available"), {})

    def scope_hash(self):
        from .options_one_minute_data import universe
        return universe(self.main_db)["scope_hash"]

    def current_trend(self, original, now):
        from .options_opening_trend_current import snapshot
        return snapshot(original, now=now)

    def approval(self, policy, scope_hash):
        from .options_opening_trend_approval import status
        return status(policy, scope_hash)


def step(job, services, *, clock, policy=None, _research_stage=False):
    """At most one collection stage; yield between contracts for deadline fairness."""
    original, progress = job["evaluation"], dict(job["progress"])
    if original.get("policy_id") == "STRAT-INTRADAY-MOMENTUM-S1-RESEARCH-V1" and not _research_stage:
        from .options_intraday_reference import research_step
        return research_step(job, services, clock=clock)
    from .options_opening_momentum import policy_for
    p = policy or policy_for(original, validate=False)
    now = clock()
    revision = None
    if now >= common.timestamp(original["deadline_at"]):
        return progress, True, {"state": "EXPIRED", "checked_at": now.isoformat(), "reasons": ["ORIGINAL_DEADLINE_EXCEEDED"]}
    if original["policy_hash"] != p["policy_hash"]:
        return progress, True, {"state": "WITHDRAWN", "checked_at": now.isoformat(), "reasons": ["POLICY_OR_SCOPE_CHANGED"]}
    phase = progress.get("phase", "EVENT")
    if phase == "EVENT":
        progress["event"] = services.event(original, now, p)
        progress["phase"] = "EXPIRIES"
    elif phase == "EXPIRIES":
        response = services.expiries(original["symbol"])
        if response.get("provider_status") not in {None, "available"}:
            raise RuntimeError("EXPIRY_SOURCE_UNAVAILABLE")
        if _research_stage:
            progress["expiry_response_verified_available"] = response.get("provider_status") == "available"
            progress["expiry_observation"] = {
                "observed_at": now.isoformat(), "provider_status": response.get("provider_status"),
                "source": response.get("source"), "symbol": response.get("symbol"),
                "expiries": response.get("expiries", []), "response_hash": common.digest(response),
                "provider_request_time": None, "provider_receipt_time": None}
        choice = "extended" if _research_stage else services.approval(p, original["scope_hash"]).get("selected_expiry_group") or "extended"
        allowed = set(p["expiry_comparison"][choice])
        progress["collection_group"] = choice
        expiries = []
        for value in response.get("expiries", []):
            try:
                if (date.fromisoformat(value) - date.fromisoformat(original["session"])).days in allowed:
                    expiries.append(value)
            except (ValueError, TypeError):
                raise ValueError("EXPIRY_SOURCE_MALFORMED")
        progress.update(expiries=sorted(set(expiries)), expiry_index=0, contract_ids=[], contracts=[], phase="CHAIN")
        if not expiries:
            if _research_stage and not progress["expiry_response_verified_available"]:
                raise RuntimeError("EXPIRY_SOURCE_UNAVAILABLE")
            progress["phase"] = "REVIEW"
            progress["collection_reason"] = "NO_MATCHING_CALENDAR_DTE"
    elif phase == "CHAIN":
        expiry = progress["expiries"][progress["expiry_index"]]
        response = services.chain(original["symbol"], expiry)
        if response.get("provider_status") not in {None, "available"}:
            raise RuntimeError("CHAIN_SOURCE_UNAVAILABLE")
        field = "call_symbol" if original["right"] == "CALL" else "put_symbol"
        contracts = response.get("contracts", [])
        contracts = sorted(contracts, key=lambda r: abs(float(r.get("strike_price") or 0) - original["bar_evidence"]["close"]))
        progress["contract_ids"] = list(dict.fromkeys([*progress["contract_ids"], *[r[field] for r in contracts if r.get(field)]]))
        bindings = progress.setdefault("chain_bindings", {})
        responses = progress.setdefault("chain_responses", {})
        responses[expiry] = response
        for row in contracts:
            if row.get(field):
                bindings[row[field]] = {"expiry": expiry, "row": row, "right": original["right"]}
        progress["expiry_index"] += 1
        if progress["expiry_index"] == len(progress["expiries"]):
            progress.update(phase="GREEKS", batch_index=0, eligible_ids=[], greek_rejections=[])
    elif phase == "GREEKS":
        index = progress["batch_index"]
        batch = progress["contract_ids"][index:index + 50]
        response = services.greeks(batch) if batch else {"items": []}
        by_id = {r.get("contract_symbol"): r for r in response.get("items", [])}
        eligible, rejected = list(progress["eligible_ids"]), list(progress["greek_rejections"])
        for contract_id in batch:
            row = by_id.get(contract_id, {})
            delta = row.get("delta")
            if (common.finite(delta) and p["contracts"]["delta_abs_min"] <= abs(delta) <= p["contracts"]["delta_abs_max"]):
                eligible.append(contract_id)
            else:
                rejected.append({"contract_id": contract_id, "reason": "DELTA_UNAVAILABLE_OR_OUT_OF_RANGE"})
        progress.update(batch_index=index + len(batch), eligible_ids=eligible, greek_rejections=rejected)
        if progress["batch_index"] >= len(progress["contract_ids"]):
            progress.update(phase="CONTRACT", contract_index=0, contract_ids=eligible)
    elif phase == "CONTRACT":
        index = progress["contract_index"]
        if index < len(progress["contract_ids"]):
            row = collect_contract(services, progress["contract_ids"][index], progress)
            row["inspected_at"] = clock().isoformat()
            progress["contracts"] = [*progress["contracts"], row]
            progress["contract_index"] = index + 1
        if progress["contract_index"] >= len(progress["contract_ids"]):
            progress["phase"] = "REVIEW"
    elif phase == "REVIEW":
        spot = services.spot(original["symbol"])
        now = clock()
        current_trend = services.current_trend(original, now)
        now = clock()
        comparisons = compare(original, progress.get("contracts", []), now=now, policy=p)
        progress["comparison"] = comparisons
        scope = services.scope_hash()
        approval = services.approval(p, scope)
        group = comparisons["groups"].get(approval.get("selected_expiry_group"), {})
        selected = group.get("selected")
        source_row = next((row for row in progress.get("contracts", [])
                           if row.get("contract_id") == progress.get("selected_contract_id")), None) if progress.get("selected_contract_id") else selected
        source_check = services.contract_evidence(source_row, now=now,
            binding=progress.get("selected_source_binding", {}) if progress.get("selected_contract_id") else None) if source_row else {
                "status": "NOT_RUN", "checked_at": now.isoformat(), "reasons": []}
        preferred = None
        if approval.get("selected_expiry_group") and not progress.get("selected_contract_id"):
            preferred = preferred_from_inspections(original, progress.get("contracts", []),
                group=approval["selected_expiry_group"], policy=p)
        needs_refresh = bool(preferred and (not selected or selected["contract_id"] != preferred))
        event = progress.get("event", {})
        event_decision = event.get("event_decision")
        event_valid = bool(event.get("trade_eligible"))
        try:
            if "valid_until" in event:
                event_valid = event_valid and now < common.timestamp(event["valid_until"])
            for source in event.get("sources", {}).values():
                event_valid = event_valid and now < common.timestamp(source["valid_until"])
                if source.get("official_checked_at"):
                    age = (now - common.timestamp(source["official_checked_at"])).total_seconds()
                    event_valid = event_valid and 0 <= age < p["event_snapshot_max_age_seconds"]
        except (KeyError, TypeError, ValueError):
            event_valid = False
        revision = trend.current_eligibility(original, quote=spot, now=now,
            event_valid=event_valid,
            contract_valid=group.get("status") == "PASS" and not needs_refresh and source_check["status"] == "PASS",
            policy_approved=approval["qualified_signal_pipeline_enabled"], trend_evidence=current_trend,
            event_decision=event_decision)
        revision.update(underlying_quote=spot, event_coverage=progress.get("event", {}),
                        current_trend=current_trend,
                        expiry_comparison=comparisons, contract_id=progress.get("selected_contract_id") or (selected.get("contract_id") if selected else None),
                        contract_qualification=group, contract_source_check=source_check, approval=approval)
        research_group = comparisons["groups"].get("extended", {})
        revision["reference_contract"] = research_group.get("selected") or reference_from_inspections(
            original, progress.get("contracts", []), policy=p)
        revision["reference_contract_status"] = "PASS" if research_group.get("selected") else "UNVERIFIED_REFERENCE"
        revision["reference_contract_rejections"] = [r for r in research_group.get("rejected", [])
            if r.get("contract_id") == (revision["reference_contract"] or {}).get("contract_id")]
        revision["research_only"] = not approval["qualified_signal_pipeline_enabled"]
        if source_check["status"] == "BLOCKED":
            revision["reasons"].extend(source_check["reasons"])
            if progress.get("selected_contract_id"):
                revision["state"] = "WITHDRAWN"
        if scope != original["scope_hash"]:
            revision.update(state="WITHDRAWN", reasons=["POLICY_OR_SCOPE_CHANGED"])
        if progress.get("selected_contract_id") and (not approval["qualified_signal_pipeline_enabled"]
                or progress.get("selected_group") != approval.get("selected_expiry_group")):
            revision.update(state="WITHDRAWN", reasons=["POLICY_OR_SCOPE_CHANGED"])
        if revision["state"] == "QUALIFIED":
            until = min(common.timestamp(original["deadline_at"]), common.timestamp(spot["received_at"]) + timedelta(seconds=3),
                        common.timestamp(current_trend['valid_until']),
                        common.timestamp(source_check["valid_until"]),
                        common.timestamp(selected["snapshot"]["bbo_received_at"]) + timedelta(seconds=3),
                        common.timestamp(selected["snapshot"]["calc_received_at"]) + timedelta(seconds=60))
            if event_decision is not None:
                until = min(until, common.timestamp(event_decision["valid_until"]))
            else:
                for source in progress["event"].get("sources", {}).values():
                    until = min(until, common.timestamp(source["valid_until"]))
                    if source.get("official_checked_at"):
                        until = min(until, common.timestamp(source["official_checked_at"]) + timedelta(seconds=900))
                if "valid_until" in event:
                    until = min(until, common.timestamp(event["valid_until"]))
            revision["valid_until"] = until.isoformat()
            if until <= now:
                revision.update(state="PENDING", reasons=["EVIDENCE_VALIDITY_EXCEEDED"])
            else:
                progress.update(selected_contract_id=selected["contract_id"], selected_group=approval["selected_expiry_group"],
                                selected_source_binding=source_check["source_binding"])
        if progress.get("collection_reason"):
            revision["reasons"].append(progress["collection_reason"])
        if revision["state"] in {"WITHDRAWN", "EXPIRED"}:
            return progress, True, revision
        if progress.get("selected_contract_id"):
            progress["phase"] = "REFRESH_SELECTED"
        elif needs_refresh:
            progress.update(phase="REFRESH_PROVISIONAL", provisional_contract_id=preferred)
        elif progress.get("contract_index", 0) < len(progress.get("contract_ids", [])):
            progress["phase"] = "CONTRACT"
        else:
            progress["phase"] = "REFRESH_EVENT"
    elif phase == "REFRESH_EVENT":
        previous = progress.get("event", {}).get("event_decision")
        progress["event"] = services.event(original, now, p)
        if progress["event"].get("event_decision") is not None or previous is not None:
            from .options_opening_trend_event_decision import decide
            from .market_clock import session_bounds_utc
            opening, closing = session_bounds_utc(date.fromisoformat(original["session"]))
            horizon = common.timestamp(trend.exit_times(opening, closing, now, p)["planned_exit_at"])
            progress["event"]["event_decision"] = decide(progress["event"], now=clock(),
                                                         horizon=horizon, previous=previous)
        if not progress.get("selected_contract_id") and progress.get("contract_ids"):
            progress.update(phase="CONTRACT", contract_index=0, contracts=[])
        else:
            progress["phase"] = "REVIEW"
    elif phase == "REFRESH_SELECTED":
        selected = progress["selected_contract_id"]
        row = collect_contract(services, selected, progress)
        if row.get("contract_id") != selected:
            return progress, True, {"state": "WITHDRAWN", "contract_id": selected,
                "checked_at": clock().isoformat(), "reasons": ["SELECTED_CONTRACT_CHANGED"]}
        progress["contracts"] = [row]
        progress["phase"] = "REFRESH_EVENT"
    elif phase == "REFRESH_PROVISIONAL":
        selected = progress["provisional_contract_id"]
        row = collect_contract(services, selected, progress)
        if row.get("contract_id") != selected:
            raise ValueError("PROVIDER_CONTRACT_IDENTITY_MISMATCH")
        row["inspected_at"] = clock().isoformat()
        progress["contracts"] = [r for r in progress["contracts"] if r["contract_id"] != selected] + [row]
        progress["phase"] = "REVIEW"
    else:
        raise ValueError("UNKNOWN_QUALIFICATION_PHASE")
    return progress, False, revision


def collect_contract(services, contract_id, progress):
    if isinstance(services, Services):
        binding = progress.get("chain_bindings", {}).get(contract_id)
        if binding:
            response = progress["chain_responses"][binding["expiry"]]
            projection = {**{k: v for k, v in response.items() if k not in {"contracts", "source_hash"}},
                "contracts": [binding["row"]], "original_response_hash": response.get("source_hash"),
                "evidence_selection": "CAPTURED_ROW_PROJECTION"}
            binding = {**binding, "response": {**projection, "source_hash": common.digest(projection)}}
        return services.contract(contract_id, chain_evidence=binding)
    return services.contract(contract_id)


class QualificationLane:
    def __init__(self, main_db, path, hub, *, clock=None, services=None, elapsed_clock=monotonic,
                 write_guard=nullcontext):
        self.path, self.hub = path, hub
        self.clock = clock or (lambda: datetime.now(UTC))
        self.write_guard = write_guard
        self.services = services or Services(main_db, clock=self.clock)
        from .options_opening_trend_clock import ClockContinuity
        self.clock_guard = ClockContinuity(elapsed_clock=elapsed_clock)
        self.stop = Event()
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="trend-qualification-step")
        self.inflight = {}
        self.next_claim_at = self.next_publication_at = 0
        self.state = {"mode": "SHADOW_RESEARCH", "steps": 0, "qualified_publication_enabled": False,
                      "max_inflight": 3, "inflight": 0}
        self.thread = Thread(target=self._run, name="opening-trend-qualification", daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stop.is_set():
            self.state["clock_health"] = self.clock_guard.sample(self.clock())
            # Publication recovery must not starve independent qualification jobs.
            if not self.clock_guard.fault and monotonic() >= self.next_publication_at:
                try:
                    from .options_opening_trend_publication import reconcile
                    with self.write_guard():
                        reconcile(self.path, now=self.clock())
                    self.state["publication_error"] = None
                except Exception as exc:
                    self.state["publication_error"] = type(exc).__name__
                self.next_publication_at = monotonic() + .5
            try:
                self._harvest()
                if monotonic() >= self.next_claim_at:
                    while len(self.inflight) < 3 and not self.stop.is_set():
                        with self.write_guard():
                            job = jobs.claim(self.path, now=self.clock(), exclude=tuple(self.inflight))
                        if job is None:
                            self.next_claim_at = monotonic() + .5
                            break
                        evaluation_id = job["evaluation"]["evaluation_id"]
                        if self.clock_guard.fault:
                            revision = {"state": "WITHDRAWN", "checked_at": self.clock().isoformat(),
                                        "reasons": ["CLOCK_DISCONTINUITY"], "clock_health": self.state["clock_health"]}
                            self._settle(job, now=self.clock(), progress=job["progress"],
                                         finished=True, revision=revision)
                            self.hub.publish({"type": "options_one_minute_eligibility", "research_strategy": job.get("evaluation", {}).get("research_strategy", "opening_trend"),
                                              "evaluation_id": evaluation_id, "qualified_signal": False})
                            continue
                        future = self.pool.submit(step, job, self.services, clock=self.clock)
                        self.inflight[evaluation_id] = (job, future)
                self.state["inflight"] = len(self.inflight)
            except Exception as exc:
                self.state["error"] = type(exc).__name__
            self.stop.wait(.05 if self.inflight else .5)

    def _harvest(self):
        for evaluation_id, (job, future) in list(self.inflight.items()):
            if not future.done():
                continue
            self.inflight.pop(evaluation_id)
            self.next_claim_at = 0
            try:
                progress, finished, revision = future.result()
                self.state["clock_health"] = self.clock_guard.sample(self.clock())
                if self.clock_guard.fault:
                    finished = True
                    revision = {"state": "WITHDRAWN", "checked_at": self.clock().isoformat(),
                                "reasons": ["CLOCK_DISCONTINUITY"], "clock_health": self.state["clock_health"]}
                outcome = self._settle(job, now=self.clock(), progress=progress,
                    finished=finished, retry_seconds=1 if revision else 0, revision=revision,
                    return_revision=True)
                self.state.update(steps=self.state["steps"] + 1, last_at=self.clock().isoformat(), error=None)
                committed = outcome["revision"] if outcome["committed"] else None
                if committed:
                    self.hub.publish({"type": "options_one_minute_eligibility", "research_strategy": job.get("evaluation", {}).get("research_strategy", "opening_trend"),
                        "evaluation_id": evaluation_id, "revision": committed,
                        "qualified_signal": committed["state"] == "QUALIFIED"
                            and bool(committed.get("approval", {}).get("qualified_signal_pipeline_enabled"))})
            except Exception as exc:
                self.state["error"] = type(exc).__name__
                try:
                    self._settle(job, now=self.clock(), progress=job["progress"],
                                retry_seconds=5, error=type(exc).__name__)
                except Exception:
                    pass  # Lease recovery retains the original deadline.

    def _settle(self, job, **kwargs):
        with self.write_guard():
            return jobs.settle(self.path, job, **kwargs)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)
        self.pool.shutdown(wait=False, cancel_futures=True)
