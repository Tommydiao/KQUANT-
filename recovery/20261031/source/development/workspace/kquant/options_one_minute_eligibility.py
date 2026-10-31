"""Refresh only the selected contract, without extending the original deadline."""
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
from queue import Queue, Empty

from . import options_one_minute as rules
from .options_one_minute_qualification import publication_blockers, select_contract


def evaluate(candidate, *, now, policy, scope_hash, event, contract, spot, approved):
    selection = select_contract(candidate, [contract], now=now, policy=policy)
    reasons = publication_blockers(candidate, now=now, policy=policy, scope_hash=scope_hash,
        event=event, selection=selection, spot=spot.get("last"),
        spot_received_at=spot.get("received_at") if spot.get("provider_status") == "available" else None)
    if contract.get("contract_id") != candidate["contract_id"]:
        reasons.append("SELECTED_CONTRACT_CHANGED")
    if not approved:
        reasons.append("EXACT_APPROVAL_REQUIRED")
    if event.get("blocking_events") or event.get("known_risk_state") == "KNOWN_BLOCKER":
        reasons.append("KNOWN_EVENT_RISK")
    deadline = rules.timestamp(candidate["deadline_at"])
    terminal = {"POLICY_OR_SCOPE_CHANGED", "CHASE_LIMIT_EXCEEDED", "STRUCTURE_INVALIDATED",
                "LOCAL_BREAKOUT_INVALIDATED", "SELECTED_CONTRACT_CHANGED", "EXACT_APPROVAL_REQUIRED", "KNOWN_EVENT_RISK"}
    state = "EXPIRED" if now >= deadline else "REVOKED" if terminal.intersection(reasons) else "WAITING_EVIDENCE" if reasons else "QUALIFIED"
    until = deadline
    if state == "QUALIFIED":
        snapshot = contract["snapshot"]
        times = [deadline, rules.timestamp(spot["received_at"]) + timedelta(seconds=3),
                 rules.timestamp(snapshot["bbo_received_at"]) + timedelta(seconds=3),
                 rules.timestamp(snapshot["calc_received_at"]) + timedelta(seconds=60)]
        # Every source's validity bounds the displayed qualification, not just quotes.
        for source in event.get("sources", {}).values():
            times.append(rules.timestamp(source["valid_until"]))
            if source.get("official_checked_at"):
                times.append(rules.timestamp(source["official_checked_at"]) + timedelta(seconds=900))
        until = min(times)
        if until <= now:
            state = "WAITING_EVIDENCE"
            reasons.append("EVIDENCE_VALIDITY_EXCEEDED")
    return {"event_id": candidate["event_id"], "contract_id": candidate["contract_id"],
            "state": state, "checked_at": now.isoformat(), "valid_until": until.isoformat(),
            "deadline_at": candidate["deadline_at"], "reasons": reasons,
            "contract_qualification": selection, "underlying_quote": spot, "event_coverage": event,
            "policy_hash": policy["policy_hash"], "scope_hash": scope_hash,
            "paper_enabled": False, "real_orders_enabled": False}


def refresh(candidate, main_db, *, clock, shared=None):
    from . import options_one_minute_data as data
    from .options_expression import option_contract_snapshot
    from .options_one_minute_events import event_context
    from .stock_signals import api_stock_quotes_batch
    if clock() >= rules.timestamp(candidate["deadline_at"]):
        return {"event_id": candidate["event_id"], "contract_id": candidate["contract_id"],
                "state": "EXPIRED", "checked_at": clock().isoformat(),
                "valid_until": candidate["deadline_at"], "reasons": ["ORIGINAL_DEADLINE_EXCEEDED"]}
    snapshot = (shared["contracts"].get(candidate["contract_id"], {}) if shared is not None
                else option_contract_snapshot(candidate["contract_id"], main_db))
    if shared is not None and snapshot.get("provider_status") == "available":
        snapshot = _with_depth(snapshot, clock=clock)
    # Quantity units are deliberately not inferred from a multiplier or raw size.
    contract = {"contract_id": snapshot.get("contract_symbol"), "underlying": snapshot.get("underlying_symbol"),
                "right": str(snapshot.get("direction") or "").upper(), "expiry_date": snapshot.get("expiry_date"),
                "delta": snapshot.get("delta"), "multiplier": snapshot.get("contract_multiplier"),
                "deliverable": "STANDARD" if snapshot.get("is_standard") else "UNKNOWN",
                "adjusted": not bool(snapshot.get("is_standard")), "bid": snapshot.get("bid"), "ask": snapshot.get("ask"),
                "bid_size": None, "ask_size": None, "size_unit_status": "UNVERIFIED_NOT_ASSUMED_CONTRACTS",
                "snapshot": snapshot}
    quotes = {} if clock() >= rules.timestamp(candidate["deadline_at"]) else (
        shared["quotes"] if shared is not None else api_stock_quotes_batch([candidate["symbol"]], db_path=main_db))
    spot = next((row for row in quotes.get("items", []) if row.get("symbol") == candidate["symbol"]), {})
    policy = rules.load_policy()
    scope = data.universe(main_db)["scope_hash"]
    now = clock()
    event = event_context(main_db, candidate["symbol"], now=now, policy=policy, scope_hash=scope)
    return evaluate(candidate, now=clock(), policy=policy, scope_hash=scope, event=event,
                    contract=contract, spot=spot,
                    approved=rules.approval_status(policy, scope)["qualified_signal_pipeline_enabled"])


def _with_depth(snapshot, *, clock):
    from .options_expression import longbridge_runtime, LONG_BRIDGE_TIMEOUT_SECONDS, _attr, _number
    from .option_quote_evidence import book_fields
    result = dict(snapshot)
    started = clock().isoformat()
    try:
        depth, mode = longbridge_runtime().pull_depth(snapshot["contract_symbol"], LONG_BRIDGE_TIMEOUT_SECONDS)
        received = clock().isoformat()
        bids, asks = list(_attr(depth, "bids", "bid") or []), list(_attr(depth, "asks", "ask") or [])
        bid = _number(_attr(bids[0], "price")) if bids else None
        ask = _number(_attr(asks[0], "price")) if asks else None
        bid_size = _number(_attr(bids[0], "volume", "size", "quantity")) if bids else None
        ask_size = _number(_attr(asks[0], "volume", "size", "quantity")) if asks else None
        status = "available" if bid is not None and ask is not None and ask >= bid else "unavailable"
        result.update(bid=bid, ask=ask, bid_size=bid_size, ask_size=ask_size,
                      bbo_received_at=received, depth_status=status, depth_mode=mode)
        result.update(book_fields(bid=bid, ask=ask, bid_size=bid_size, ask_size=ask_size,
                                  received_at=received, status=status))
    except Exception as exc:
        result.update(bid=None, ask=None, bid_size=None, ask_size=None,
                      bbo_received_at=None, depth_status="unavailable", depth_error_code=type(exc).__name__)
    result.update(bbo_request_started_at=started, bbo_request_finished_at=clock().isoformat(),
                  bbo_event_time=None, bbo_time_source="receipt_time_only", strict_fill_eligible=False)
    return result


def shared_quotes(candidates, main_db, *, clock):
    from .options_expression import option_contract_snapshots
    from .stock_signals import api_stock_quotes_batch
    active = [row for row in candidates if clock() < rules.timestamp(row["deadline_at"])]
    contracts = list(dict.fromkeys(row["contract_id"] for row in active))
    snapshots = option_contract_snapshots(contracts) if contracts else {"items": []}
    active = [row for row in active if clock() < rules.timestamp(row["deadline_at"])]
    symbols = list(dict.fromkeys(row["symbol"] for row in active))
    quotes = api_stock_quotes_batch(symbols, db_path=main_db) if symbols else {"items": []}
    return {"contracts": {row["contract_symbol"]: row for row in snapshots.get("items", [])}, "quotes": quotes}


class EligibilityLane:
    """One submission at a time; SDK work never runs on bar consumption."""
    def __init__(self, main_db, evidence_path, *, clock, store_path=None, refresher=refresh):
        from .options_signal_copilot import DEFAULT_STORE_PATH
        self.main_db, self.path = main_db, evidence_path
        self.store = store_path or DEFAULT_STORE_PATH
        self.clock, self.refresher = clock, refresher
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="minute-current-eligibility")
        self.future = None
        self.next_at = None
        self.last_checked = {}
        self.state = {"status": "IDLE"}
        self.completed = Queue()

    def _cycle(self):
        from .signal_eligibility import append_revision, latest_revision, TERMINAL
        now = self.clock()
        with sqlite3.connect(f"file:{self.path.resolve().as_posix()}?mode=ro", uri=True, timeout=0.25) as db:
            rows = db.execute("SELECT payload_json FROM one_minute_candidates WHERE session=? ORDER BY published_at LIMIT 222",
                              (now.astimezone(rules.NY).date().isoformat(),)).fetchall()
        candidates = [json.loads(row[0]) for row in rows]
        candidates.sort(key=lambda row: (row["deadline_at"], self.last_checked.get(row["event_id"], ""), row["event_id"]))
        due = []
        for candidate in candidates:
            signal_id = "one-minute-" + candidate["event_id"]
            previous = latest_revision(self.store, signal_id)
            if previous and previous["state"] in TERMINAL:
                continue
            last = self.last_checked.get(candidate["event_id"])
            if (last and now < rules.timestamp(candidate["deadline_at"])
                    and now - rules.timestamp(last) < timedelta(seconds=1)):
                continue
            due.append(candidate)
            if len(due) >= (8 if self.refresher is refresh else 1):
                break
        shared = None
        shared_error = None
        if due and self.refresher is refresh:
            try:
                shared = shared_quotes(due, self.main_db, clock=self.clock)
            except Exception as exc:
                shared_error = exc
        for candidate in due:
            signal_id = "one-minute-" + candidate["event_id"]
            try:
                if shared_error is not None:
                    raise shared_error
                revision = self.refresher(candidate, self.main_db, clock=self.clock,
                    **({"shared": shared} if self.refresher is refresh else {}))
            except Exception as exc:
                completed = self.clock()
                revision = {"contract_id": candidate["contract_id"], "event_id": candidate["event_id"],
                    "state": "EXPIRED" if completed >= rules.timestamp(candidate["deadline_at"]) else "WAITING_EVIDENCE", "checked_at": completed.isoformat(),
                    "valid_until": candidate["deadline_at"], "reasons": ["REFRESH_UNAVAILABLE"],
                    "error_type": type(exc).__name__}
            self.last_checked[candidate["event_id"]] = self.clock().isoformat()
            saved = append_revision(self.store, signal_id, revision)
            if self.refresher is not refresh:
                return saved
            self.completed.put(saved)
        return None

    def tick(self, now):
        result = None
        if self.future and self.future.done():
            try:
                result = self.future.result()
                self.state = {"status": "UPDATED" if result else "IDLE", "checked_at": now.isoformat()}
            except Exception as exc:
                self.state = {"status": "UNAVAILABLE", "error_type": type(exc).__name__, "checked_at": now.isoformat()}
            finally:
                self.future = None
        if self.future is None and (self.next_at is None or now >= self.next_at):
            self.future = self.pool.submit(self._cycle)
            self.next_at = now + timedelta(seconds=0.05)
        if result is None:
            try:
                result = self.completed.get_nowait()
            except Empty:
                pass
        return result

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
