from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "config" / "options_short_atm_offline_policy_v1.json"
ENGINE_VERSION = "options-paper-engineering-v0.5.0"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(value: Any) -> str:
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include an offset")
    return parsed.astimezone(UTC)


def _ordered_timestamps(snapshot: dict[str, Any]) -> bool:
    names = (
        "max_input_available_at",
        "snapshot_frozen_at",
        "evaluation_started_at",
        "evaluation_finished_at",
        "decision_committed_at",
    )
    try:
        values = [_time(str(snapshot[name])) for name in names]
    except (KeyError, TypeError, ValueError):
        return False
    return values == sorted(values)


def _finite_number(value: Any) -> bool:
    try:
        return value is not None and not isinstance(value, bool) and math.isfinite(float(value))
    except (ValueError, TypeError):
        return False


def evaluate_candidate(
    snapshot: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
    seen_opportunities: set[str] | None = None,
) -> dict[str, Any]:
    policy = policy or load_policy()
    right = str(snapshot.get("right") or "").upper()
    symbol = str(snapshot.get("symbol") or "").upper()
    session = str(snapshot.get("market_session_date") or "")
    branch = "ELIGIBLE_RESEARCH_CANDIDATE"
    reasons: list[str] = []

    if right not in policy["scope"]["rights"]:
        reasons.append("RIGHT_OUTSIDE_APPROVED_SCOPE")
    if symbol not in snapshot.get("frozen_universe", []):
        reasons.append("SYMBOL_OUTSIDE_FROZEN_UNIVERSE")
    if not snapshot.get("all_bars_closed", False):
        reasons.append("FORMING_OR_INCOMPLETE_BAR")
    if not _ordered_timestamps(snapshot):
        reasons.append("AS_OF_ORDER_INVALID")
    if snapshot.get("event_status") != "CLEAR":
        reasons.append("EVENT_UNKNOWN_OR_BLOCKED")

    candidate_contract = policy["candidate_contract"]
    compression = snapshot.get("compression_ratio")
    participation = snapshot.get("opening_participation")
    if not _finite_number(compression) or not _finite_number(participation):
        reasons.append("REQUIRED_FEATURE_MISSING")
    if not _finite_number(compression) or float(compression) < 0 or float(compression) > float(candidate_contract["compression_ratio_max"]):
        reasons.append("COMPRESSION_NOT_CONFIRMED")
    if not _finite_number(participation) or float(participation) < float(candidate_contract["opening_participation_min"]):
        reasons.append("PARTICIPATION_NOT_CONFIRMED")

    first_close = snapshot.get("first_5m_close")
    second_close = snapshot.get("second_5m_close")
    high = snapshot.get("prior_range_high")
    low = snapshot.get("prior_range_low")
    spy_close = snapshot.get("spy_prior_close")
    spy_ema20 = snapshot.get("spy_ema20")
    spy_ema50 = snapshot.get("spy_ema50")
    numeric = (first_close, second_close, high, low, spy_close, spy_ema20, spy_ema50)
    if any(not _finite_number(value) or float(value) <= 0 for value in numeric):
        reasons.append("REQUIRED_FEATURE_MISSING")
    elif right == "CALL":
        if not (float(first_close) > float(high) and float(second_close) > float(high)):
            reasons.append("CALL_RANGE_CONFIRMATION_FAILED")
        if float(spy_close) < float(spy_ema50):
            reasons.append("CALL_MARKET_CONFIRMATION_FAILED")
    elif right == "PUT":
        if not (float(first_close) < float(low) and float(second_close) < float(low)):
            reasons.append("PUT_RANGE_CONFIRMATION_FAILED")
        if float(spy_close) >= float(spy_ema20):
            reasons.append("PUT_MARKET_CONFIRMATION_FAILED")

    identity_material = {
        "policy_id": policy["policy_id"],
        "symbol": symbol,
        "right": right,
        "session": session,
        "range_high": high,
        "range_low": low,
    }
    opportunity_id = f"oop_{content_hash(identity_material)[:24]}"
    if seen_opportunities is not None and opportunity_id in seen_opportunities:
        reasons.append("DUPLICATE_ECONOMIC_OPPORTUNITY")

    if reasons:
        branch = "DATA_BLOCKED" if any(
            reason in {"FORMING_OR_INCOMPLETE_BAR", "AS_OF_ORDER_INVALID", "EVENT_UNKNOWN_OR_BLOCKED", "REQUIRED_FEATURE_MISSING"}
            for reason in reasons
        ) else "NO_CANDIDATE"
    elif seen_opportunities is not None:
        seen_opportunities.add(opportunity_id)

    payload = {
        "economic_opportunity_id": opportunity_id,
        "evaluation_id": f"eva_{content_hash({'opportunity': opportunity_id, 'snapshot': snapshot.get('snapshot_id')})[:24]}",
        "policy_id": policy["policy_id"],
        "strategy_policy_id": policy["selected_policy_ids"]["strategy"],
        "profile_id": policy["scope"]["profile_id"],
        "symbol": symbol,
        "right": right,
        "market_session_date": session,
        "state": branch,
        "reasons": reasons,
        "decision_committed_at": snapshot.get("decision_committed_at"),
        "earliest_fill_at": snapshot.get("decision_committed_at"),
        "frozen_breakout_level": high if right == "CALL" else low,
        "snapshot_id": snapshot.get("snapshot_id"),
        "snapshot_hash": content_hash(snapshot),
        "evidence_class": "OFFLINE_CLOSED_BAR_FIXTURE" if snapshot.get("fixture") else "CLOSED_BAR_RESEARCH",
    }
    return payload


def select_contract(
    candidate: dict[str, Any],
    contracts: Iterable[dict[str, Any]],
    *,
    underlying_price: float,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy or load_policy()
    selection = policy["contract_selection"]
    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for raw in contracts:
        row = dict(raw)
        reasons: list[str] = []
        if row.get("underlying") != candidate.get("symbol") or str(row.get("right", "")).upper() != candidate.get("right"):
            reasons.append("IDENTITY_MISMATCH")
        dte = row.get("dte")
        delta = row.get("delta")
        if dte is None or not selection["dte_min"] <= int(dte) <= selection["dte_max"] or (
            selection.get("allowed_dtes") is not None and int(dte) not in selection["allowed_dtes"]
        ):
            reasons.append("DTE_OUT_OF_RANGE")
        if delta is None or not selection["absolute_delta_min"] <= abs(float(delta)) <= selection["absolute_delta_max"]:
            reasons.append("DELTA_OUT_OF_RANGE")
        if int(row.get("multiplier") or 0) != int(selection["contract_multiplier"]):
            reasons.append("MULTIPLIER_UNKNOWN_OR_INVALID")
        if row.get("deliverable") != "STANDARD" or bool(row.get("adjusted")):
            reasons.append("NON_STANDARD_OR_ADJUSTED")
        bid, ask = row.get("bid"), row.get("ask")
        bid_size, ask_size = row.get("bid_size"), row.get("ask_size")
        if bid is None or ask is None or float(bid) <= 0 or float(ask) <= float(bid):
            reasons.append("INVALID_TWO_SIDED_QUOTE")
        else:
            mid = (float(bid) + float(ask)) / 2
            if (float(ask) - float(bid)) / mid > float(selection["max_spread_mid_fraction"]):
                reasons.append("SPREAD_TOO_WIDE")
        if bid_size is None or int(bid_size) < int(selection["minimum_bid_size_contracts"]):
            reasons.append("BID_SIZE_INSUFFICIENT")
        if ask_size is None or int(ask_size) < int(selection["minimum_ask_size_contracts"]):
            reasons.append("ASK_SIZE_INSUFFICIENT")
        if reasons:
            rejected.append({"contract_id": row.get("contract_id"), "reasons": reasons})
            continue
        eligible.append(row)

    if not eligible:
        return {"status": "NO_ELIGIBLE_CONTRACT", "selected": None, "rejected": rejected}
    eligible.sort(
        key=lambda row: (
            abs(int(row["dte"]) - int(selection["dte_target"])),
            abs(abs(float(row["delta"])) - float(selection["delta_target"])),
            abs(float(row["strike"]) - float(underlying_price)),
            str(row["contract_id"]),
        )
    )
    selected = dict(eligible[0])
    selected["selection_hash"] = content_hash(selected)
    return {"status": "SELECTED", "selected": selected, "rejected": rejected}


def freeze_plan(candidate: dict[str, Any], selected_contract: dict[str, Any], *, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or load_policy()
    if candidate.get("state") != "ELIGIBLE_RESEARCH_CANDIDATE":
        raise ValueError("candidate is not eligible")
    contract_id = str(selected_contract["contract_id"])
    material = {
        "opportunity": candidate["economic_opportunity_id"],
        "evaluation": candidate["evaluation_id"],
        "contract": contract_id,
        "policy": policy["policy_id"],
    }
    plan_id = f"opl_{content_hash(material)[:24]}"
    decision = str(candidate["decision_committed_at"])
    return {
        "plan_id": plan_id,
        "intent_id": f"opi_{content_hash({'plan': plan_id, 'class': 'offline'})[:24]}",
        "economic_opportunity_id": candidate["economic_opportunity_id"],
        "evaluation_id": candidate["evaluation_id"],
        "policy_id": policy["policy_id"],
        "strategy_policy_id": policy["selected_policy_ids"]["strategy"],
        "paper_execution_policy_id": policy["selected_policy_ids"]["paper_execution"],
        "profile_id": candidate["profile_id"],
        "symbol": candidate["symbol"],
        "right": candidate["right"],
        "portfolio_id": f"offline-engineering-{str(candidate['right']).lower()}",
        "contract": selected_contract,
        "decision_committed_at": decision,
        "earliest_fill_at": decision,
        "frozen_breakout_level": candidate["frozen_breakout_level"],
        "state": "PAPER_ENTRY_PENDING",
        "fill_assumption": "RECEIPT_TIME_QUOTE_PROXY_NOT_EXCHANGE_FILL",
        "portfolio_version": 0,
        "plan_hash": content_hash(material),
    }


@dataclass(frozen=True)
class QuoteDecision:
    eligible: bool
    reason: str
    fill_price: float | None
    capacity: int
    slippage_per_unit: float | None


def evaluate_quote(
    plan: dict[str, Any],
    quote: dict[str, Any],
    *,
    side: str,
    policy: dict[str, Any] | None = None,
) -> QuoteDecision:
    policy = policy or load_policy()
    proxy = policy["quote_proxy"]
    if quote.get("contract_id") != plan.get("contract", {}).get("contract_id"):
        return QuoteDecision(False, "CONTRACT_IDENTITY_MISMATCH", None, 0, None)
    if quote.get("evidence_class") != proxy["evidence_class"]:
        return QuoteDecision(False, "QUOTE_EVIDENCE_CLASS_MISMATCH", None, 0, None)
    try:
        decision = _time(str(plan["decision_committed_at"]))
        earliest = _time(str(plan["earliest_fill_at"]))
        request = _time(str(quote["request_started_at"]))
        received = _time(str(quote["received_at"]))
    except (KeyError, TypeError, ValueError):
        return QuoteDecision(False, "QUOTE_TIME_INVALID", None, 0, None)
    if request < decision or received < request or received < earliest:
        return QuoteDecision(False, "QUOTE_PRECEDES_DECISION_OR_REQUEST", None, 0, None)
    if (received - request).total_seconds() > float(proxy["quote_age_seconds"]):
        return QuoteDecision(False, "QUOTE_RESPONSE_STALE", None, 0, None)
    if quote.get("session_health") != "HEALTHY" or bool(quote.get("cached")):
        return QuoteDecision(False, "QUOTE_SESSION_UNHEALTHY_OR_CACHED", None, 0, None)
    bid, ask = quote.get("bid"), quote.get("ask")
    bid_size, ask_size = quote.get("bid_size"), quote.get("ask_size")
    multiplier = quote.get("multiplier")
    if any(value is None for value in (bid, ask, bid_size, ask_size, multiplier)):
        return QuoteDecision(False, "QUOTE_FIELD_MISSING", None, 0, None)
    bid, ask = float(bid), float(ask)
    if bid <= 0 or ask <= bid or int(multiplier) != int(plan["contract"]["multiplier"]):
        return QuoteDecision(False, "QUOTE_VALUE_INVALID", None, 0, None)
    mid = (bid + ask) / 2
    spread = ask - bid
    if spread / mid > float(policy["contract_selection"]["max_spread_mid_fraction"]):
        return QuoteDecision(False, "QUOTE_SPREAD_TOO_WIDE", None, 0, None)
    slippage = max(0.01, 0.1 * spread)
    if side == "ENTRY":
        return QuoteDecision(True, "ELIGIBLE", ask + slippage, int(ask_size), slippage)
    if side == "EXIT":
        return QuoteDecision(True, "ELIGIBLE", max(0.0, bid - slippage), int(bid_size), slippage)
    return QuoteDecision(False, "QUOTE_SIDE_INVALID", None, 0, None)


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS ledger_meta (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS opportunities (economic_opportunity_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evaluations (evaluation_id TEXT PRIMARY KEY, economic_opportunity_id TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS plans (plan_id TEXT PRIMARY KEY, economic_opportunity_id TEXT NOT NULL, payload_json TEXT NOT NULL, state TEXT NOT NULL, portfolio_version INTEGER NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quote_events (quote_event_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, side TEXT NOT NULL, payload_json TEXT NOT NULL, decision_json TEXT NOT NULL, received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS paper_fills (paper_fill_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, side TEXT NOT NULL, quantity INTEGER NOT NULL, fill_price REAL NOT NULL, fees REAL NOT NULL, payload_json TEXT NOT NULL, filled_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS positions (position_id TEXT PRIMARY KEY, plan_id TEXT UNIQUE NOT NULL, contract_id TEXT NOT NULL, state TEXT NOT NULL, quantity INTEGER NOT NULL, entry_fill REAL NOT NULL, entry_fees REAL NOT NULL, risk_base REAL NOT NULL, realized_pnl REAL, net_r REAL, exit_reason TEXT, payload_json TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS state_transitions (transition_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, from_state TEXT, to_state TEXT NOT NULL, reason TEXT NOT NULL, event_time TEXT NOT NULL, payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS replay_runs (run_id TEXT PRIMARY KEY, policy_hash TEXT NOT NULL, fixture_hash TEXT NOT NULL, result_json TEXT NOT NULL, created_at TEXT NOT NULL);
"""


class PaperLedger:
    def __init__(self, path: Path, *, policy: dict[str, Any] | None = None) -> None:
        self.path = path
        self.policy = policy or load_policy()
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.executescript(SCHEMA)
            connection.execute("INSERT OR REPLACE INTO ledger_meta VALUES (?,?,?)", ("schema_version", json_text(1), utc_now()))
            connection.execute("INSERT OR REPLACE INTO ledger_meta VALUES (?,?,?)", ("engine_version", json_text(ENGINE_VERSION), utc_now()))
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _portfolio_version(self, connection: sqlite3.Connection, portfolio_id: str) -> int:
        key = f"portfolio_version:{portfolio_id}"
        row = connection.execute("SELECT value_json FROM ledger_meta WHERE key=?", (key,)).fetchone()
        if row is None:
            connection.execute("INSERT INTO ledger_meta VALUES (?,?,?)", (key, json_text(0), utc_now()))
            return 0
        return int(json.loads(row["value_json"]))

    def _advance_portfolio_version(self, connection: sqlite3.Connection, portfolio_id: str) -> int:
        next_version = self._portfolio_version(connection, portfolio_id) + 1
        key = f"portfolio_version:{portfolio_id}"
        connection.execute(
            "INSERT OR REPLACE INTO ledger_meta VALUES (?,?,?)",
            (key, json_text(next_version), utc_now()),
        )
        return next_version

    def record_plan(self, candidate: dict[str, Any], plan: dict[str, Any]) -> bool:
        now = utc_now()
        with self._connect() as connection:
            existing = connection.execute("SELECT payload_json FROM plans WHERE plan_id=?", (plan["plan_id"],)).fetchone()
            if existing:
                if json.loads(existing["payload_json"]) != plan:
                    raise RuntimeError("immutable plan identity collision")
                return False
            connection.execute("INSERT OR IGNORE INTO opportunities VALUES (?,?,?,?)", (candidate["economic_opportunity_id"], json_text(candidate), candidate["state"], now))
            connection.execute("INSERT OR IGNORE INTO evaluations VALUES (?,?,?,?)", (candidate["evaluation_id"], candidate["economic_opportunity_id"], json_text(candidate), now))
            portfolio_version = self._portfolio_version(connection, str(plan["portfolio_id"]))
            connection.execute("INSERT INTO plans VALUES (?,?,?,?,?,?)", (plan["plan_id"], plan["economic_opportunity_id"], json_text(plan), plan["state"], portfolio_version, now))
            self._transition(connection, plan["plan_id"], None, "PAPER_ENTRY_PENDING", "PLAN_FROZEN", plan)
        return True

    def _transition(self, connection: sqlite3.Connection, plan_id: str, old: str | None, new: str, reason: str, payload: dict[str, Any]) -> None:
        material = {"plan_id": plan_id, "old": old, "new": new, "reason": reason, "payload": payload}
        transition_id = f"trn_{content_hash(material)[:24]}"
        connection.execute(
            "INSERT OR IGNORE INTO state_transitions VALUES (?,?,?,?,?,?,?)",
            (transition_id, plan_id, old, new, reason, utc_now(), json_text(payload)),
        )

    def _plan(self, connection: sqlite3.Connection, plan_id: str) -> tuple[dict[str, Any], str, int]:
        row = connection.execute("SELECT payload_json,state,portfolio_version FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
        if not row:
            raise KeyError(plan_id)
        return json.loads(row["payload_json"]), str(row["state"]), int(row["portfolio_version"])

    def attempt_entry(self, plan_id: str, quote: dict[str, Any]) -> dict[str, Any]:
        quote_id = str(quote.get("quote_event_id") or f"qev_{content_hash(quote)[:24]}")
        with self._connect() as connection:
            plan, state, portfolio_version = self._plan(connection, plan_id)
            previous = connection.execute("SELECT decision_json FROM quote_events WHERE quote_event_id=?", (quote_id,)).fetchone()
            if previous:
                return {"status": "IDEMPOTENT_REPLAY", "decision": json.loads(previous["decision_json"])}
            if state != "PAPER_ENTRY_PENDING":
                return {"status": "STATE_REJECTED", "reason": f"PLAN_STATE_{state}"}
            current_portfolio_version = self._portfolio_version(connection, str(plan["portfolio_id"]))
            if portfolio_version != current_portfolio_version:
                return {
                    "status": "NO_FILL",
                    "reason": "STALE_PORTFOLIO_VERSION",
                    "plan_portfolio_version": portfolio_version,
                    "current_portfolio_version": current_portfolio_version,
                }
            decision = evaluate_quote(plan, quote, side="ENTRY", policy=self.policy)
            connection.execute("INSERT INTO quote_events VALUES (?,?,?,?,?,?)", (quote_id, plan_id, "ENTRY", json_text(quote), json_text(decision.__dict__), str(quote.get("received_at") or utc_now())))
            if not decision.eligible:
                return {"status": "NO_FILL", "reason": decision.reason}

            multiplier = int(plan["contract"]["multiplier"])
            commission = float(self.policy["cost_policy"]["commission_usd_per_contract_per_side"])
            risk_budget = float(self.policy["capital_policy"]["reference_capital_usd"]) * float(self.policy["capital_policy"]["per_position_premium_fraction"])
            unit_risk = float(decision.fill_price) * multiplier + commission
            planned = math.floor(risk_budget / unit_risk)
            quantity = min(planned, decision.capacity)
            if quantity < 1:
                return {"status": "EXPIRED_UNFILLED", "reason": "MINIMUM_CONTRACT_EXCEEDS_RISK_BUDGET", "risk_budget": risk_budget, "unit_risk": unit_risk}
            fees = commission * quantity
            risk_base = quantity * float(decision.fill_price) * multiplier + fees
            risk_rejection = self._risk_rejection(connection, plan, risk_base, str(quote["received_at"]))
            if risk_rejection:
                return {"status": "NO_FILL", "reason": risk_rejection, "risk_base": risk_base}
            fill_material = {"plan": plan_id, "quote": quote_id, "side": "ENTRY", "quantity": quantity}
            fill_id = f"pfl_{content_hash(fill_material)[:24]}"
            fill_payload = {**fill_material, "fill_assumption": plan["fill_assumption"], "slippage_per_unit": decision.slippage_per_unit}
            connection.execute("INSERT INTO paper_fills VALUES (?,?,?,?,?,?,?,?)", (fill_id, plan_id, "ENTRY", quantity, float(decision.fill_price), fees, json_text(fill_payload), str(quote["received_at"])))
            position_id = f"pos_{content_hash({'plan': plan_id})[:24]}"
            next_portfolio_version = self._advance_portfolio_version(connection, str(plan["portfolio_id"]))
            position_payload = {"entry_quote_event_id": quote_id, "entry_fill_id": fill_id, "portfolio_version_at_entry": next_portfolio_version}
            connection.execute("INSERT INTO positions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (position_id, plan_id, plan["contract"]["contract_id"], "OPEN", quantity, float(decision.fill_price), fees, risk_base, None, None, None, json_text(position_payload), utc_now()))
            connection.execute("UPDATE plans SET state='PAPER_OPEN',portfolio_version=?,updated_at=? WHERE plan_id=?", (next_portfolio_version, utc_now(), plan_id))
            self._transition(connection, plan_id, state, "PAPER_OPEN", "RECEIPT_PROXY_ENTRY", fill_payload)
            return {"status": "PAPER_OPEN", "position_id": position_id, "quantity": quantity, "fill_price": decision.fill_price, "fees": fees, "risk_base": risk_base}

    def _risk_rejection(self, connection: sqlite3.Connection, plan: dict[str, Any], proposed_risk: float, event_time: str) -> str | None:
        portfolio_id = str(plan["portfolio_id"])
        open_rows = connection.execute("SELECT p.*,pl.payload_json AS plan_json FROM positions p JOIN plans pl ON pl.plan_id=p.plan_id WHERE p.state!='CLOSED'").fetchall()
        portfolio_rows = []
        for row in open_rows:
            stored_plan = json.loads(row["plan_json"])
            if stored_plan.get("portfolio_id") == portfolio_id:
                portfolio_rows.append((row, stored_plan))
        capital = self.policy["capital_policy"]
        if len(portfolio_rows) >= int(capital["maximum_open_positions"]):
            return "MAXIMUM_OPEN_POSITIONS_REACHED"
        same_underlying = sum(1 for _, item in portfolio_rows if item.get("symbol") == plan.get("symbol"))
        if same_underlying >= int(capital["maximum_positions_per_underlying"]):
            return "UNDERLYING_POSITION_LIMIT_REACHED"
        open_risk = sum(float(row["risk_base"]) for row, _ in portfolio_rows)
        total_limit = float(capital["reference_capital_usd"]) * float(capital["total_open_premium_fraction"])
        if open_risk + proposed_risk > total_limit + 1e-9:
            return "TOTAL_OPEN_PREMIUM_LIMIT_REACHED"

        event_date = _time(event_time).date().isoformat()
        realized_rows = connection.execute("SELECT p.realized_pnl,pl.payload_json AS plan_json,f.filled_at FROM positions p JOIN plans pl ON pl.plan_id=p.plan_id JOIN paper_fills f ON f.plan_id=p.plan_id AND f.side='EXIT' WHERE p.state='CLOSED'").fetchall()
        realized_for_portfolio = []
        for row in realized_rows:
            stored_plan = json.loads(row["plan_json"])
            if stored_plan.get("portfolio_id") == portfolio_id:
                realized_for_portfolio.append(row)
        daily_realized = sum(float(row["realized_pnl"] or 0.0) for row in realized_for_portfolio if str(row["filled_at"])[:10] == event_date)
        daily_limit = float(capital["reference_capital_usd"]) * float(capital["daily_realized_loss_fraction"])
        if daily_realized <= -daily_limit:
            return "DAILY_REALIZED_LOSS_LIMIT_REACHED"
        cumulative_realized = sum(float(row["realized_pnl"] or 0.0) for row in realized_for_portfolio)
        drawdown_limit = float(capital["reference_capital_usd"]) * float(capital["cumulative_drawdown_pause_fraction"])
        if cumulative_realized <= -drawdown_limit:
            return "CUMULATIVE_DRAWDOWN_PAUSE"
        return None

    def monitor_exit(self, plan_id: str, quote: dict[str, Any] | None, *, trigger: str) -> dict[str, Any]:
        with self._connect() as connection:
            plan, state, portfolio_version = self._plan(connection, plan_id)
            position = connection.execute("SELECT * FROM positions WHERE plan_id=?", (plan_id,)).fetchone()
            if not position:
                return {"status": "NO_POSITION"}
            if position["state"] == "CLOSED":
                return {"status": "IDEMPOTENT_CLOSED", "net_r": position["net_r"], "realized_pnl": position["realized_pnl"]}
            if trigger == "DATA_OR_QUOTE_RISK_PENDING" or quote is None:
                if state != "PAPER_EXIT_PENDING":
                    connection.execute("UPDATE plans SET state='PAPER_EXIT_PENDING',updated_at=? WHERE plan_id=?", (utc_now(), plan_id))
                    self._transition(connection, plan_id, state, "PAPER_EXIT_PENDING", "EXIT_PENDING_NO_QUOTE", {"trigger": trigger})
                return {"status": "PAPER_EXIT_PENDING", "reason": "EXIT_PENDING_NO_QUOTE"}

            quote_id = str(quote.get("quote_event_id") or f"qev_{content_hash(quote)[:24]}")
            previous = connection.execute("SELECT decision_json FROM quote_events WHERE quote_event_id=?", (quote_id,)).fetchone()
            if previous:
                return {"status": "IDEMPOTENT_REPLAY", "decision": json.loads(previous["decision_json"])}
            decision = evaluate_quote(plan, quote, side="EXIT", policy=self.policy)
            connection.execute("INSERT INTO quote_events VALUES (?,?,?,?,?,?)", (quote_id, plan_id, "EXIT", json_text(quote), json_text(decision.__dict__), str(quote.get("received_at") or utc_now())))
            if not decision.eligible:
                connection.execute("UPDATE plans SET state='PAPER_EXIT_PENDING',updated_at=? WHERE plan_id=?", (utc_now(), plan_id))
                self._transition(connection, plan_id, state, "PAPER_EXIT_PENDING", decision.reason, {"quote_event_id": quote_id})
                return {"status": "PAPER_EXIT_PENDING", "reason": decision.reason}

            known_triggers = {"HARD_LOSS", "UNDERLYING_INVALIDATION", "TIME_EXIT", "PROFIT_REVIEW", "EXPIRY_BUFFER"}
            if trigger not in known_triggers:
                return {"status": "PAPER_EXIT_PENDING", "reason": "EXIT_TRIGGER_UNKNOWN"}
            bid = float(quote["bid"])
            if trigger == "HARD_LOSS" and bid > float(position["entry_fill"]) * (1 - float(self.policy["exit_policy"]["hard_premium_loss_fraction"])):
                return {"status": "PAPER_EXIT_PENDING", "reason": "HARD_LOSS_TRIGGER_NOT_SATISFIED"}
            if trigger == "PROFIT_REVIEW" and bid < float(position["entry_fill"]) * (1 + float(self.policy["exit_policy"]["profit_review_fraction"])):
                return {"status": "PAPER_EXIT_PENDING", "reason": "PROFIT_REVIEW_TRIGGER_NOT_SATISFIED"}

            quantity = min(int(position["quantity"]), int(decision.capacity))
            if quantity < int(position["quantity"]):
                return {"status": "PAPER_EXIT_PENDING", "reason": "PARTIAL_EXIT_NOT_PERMITTED_WITHOUT_REMAINDER_PLAN"}
            commission = float(self.policy["cost_policy"]["commission_usd_per_contract_per_side"])
            exit_fees = commission * quantity
            multiplier = int(plan["contract"]["multiplier"])
            pnl = quantity * multiplier * (float(decision.fill_price) - float(position["entry_fill"])) - float(position["entry_fees"]) - exit_fees
            net_r = pnl / float(position["risk_base"])
            fill_material = {"plan": plan_id, "quote": quote_id, "side": "EXIT", "quantity": quantity}
            fill_id = f"pfl_{content_hash(fill_material)[:24]}"
            fill_payload = {**fill_material, "trigger": trigger, "fill_assumption": plan["fill_assumption"], "slippage_per_unit": decision.slippage_per_unit}
            connection.execute("INSERT INTO paper_fills VALUES (?,?,?,?,?,?,?,?)", (fill_id, plan_id, "EXIT", quantity, float(decision.fill_price), exit_fees, json_text(fill_payload), str(quote["received_at"])))
            connection.execute("UPDATE positions SET state='CLOSED',realized_pnl=?,net_r=?,exit_reason=?,payload_json=?,updated_at=? WHERE plan_id=?", (pnl, net_r, trigger, json_text({**json.loads(position["payload_json"]), "exit_quote_event_id": quote_id, "exit_fill_id": fill_id}), utc_now(), plan_id))
            next_portfolio_version = self._advance_portfolio_version(connection, str(plan["portfolio_id"]))
            connection.execute("UPDATE plans SET state='PAPER_CLOSED',portfolio_version=?,updated_at=? WHERE plan_id=?", (next_portfolio_version, utc_now(), plan_id))
            self._transition(connection, plan_id, state, "PAPER_CLOSED", trigger, fill_payload)
            return {"status": "PAPER_CLOSED", "quantity": quantity, "fill_price": decision.fill_price, "fees": exit_fees, "realized_pnl": pnl, "net_r": net_r, "exit_reason": trigger}

    def open_positions(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM positions WHERE state!='CLOSED' ORDER BY position_id").fetchall()
        return [dict(row) for row in rows]

    def summary(self) -> dict[str, Any]:
        with self._connect() as connection:
            counts = {}
            for table in ("opportunities", "evaluations", "plans", "quote_events", "paper_fills", "positions", "state_transitions", "replay_runs"):
                counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            state_counts = {str(row[0]): int(row[1]) for row in connection.execute("SELECT state,COUNT(*) FROM plans GROUP BY state")}
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        return {"path": str(self.path.resolve()), "integrity_check": integrity, "counts": counts, "plan_states": state_counts}

    def failure_probe(self) -> dict[str, Any]:
        marker = f"failure_probe_{content_hash({'path': str(self.path), 'time': utc_now()})[:12]}"
        try:
            with self._connect() as connection:
                connection.execute("INSERT INTO ledger_meta VALUES (?,?,?)", (marker, json_text(True), utc_now()))
                raise RuntimeError("intentional rollback probe")
        except RuntimeError:
            pass
        with self._connect() as connection:
            survived = connection.execute("SELECT 1 FROM ledger_meta WHERE key=?", (marker,)).fetchone() is not None
        return {"status": "PASS" if not survived else "FAIL", "marker_survived": survived}


def _fixture_snapshot(right: str) -> dict[str, Any]:
    is_call = right == "CALL"
    return {
        "fixture": True,
        "snapshot_id": f"fixture-{right.lower()}-closed-bars",
        "symbol": "NVDA",
        "right": right,
        "market_session_date": "2026-09-18",
        "frozen_universe": ["NVDA", "SPY"],
        "all_bars_closed": True,
        "compression_ratio": 0.72,
        "opening_participation": 1.80,
        "prior_range_high": 180.0,
        "prior_range_low": 160.0,
        "first_5m_close": 181.0 if is_call else 159.0,
        "second_5m_close": 181.5 if is_call else 158.5,
        "spy_prior_close": 610.0 if is_call else 580.0,
        "spy_ema20": 600.0,
        "spy_ema50": 605.0,
        "event_status": "CLEAR",
        "max_input_available_at": "2026-09-18T13:40:00+00:00",
        "snapshot_frozen_at": "2026-09-18T13:40:01+00:00",
        "evaluation_started_at": "2026-09-18T13:40:02+00:00",
        "evaluation_finished_at": "2026-09-18T13:40:03+00:00",
        "decision_committed_at": "2026-09-18T13:40:04+00:00",
    }


def _fixture_contract(right: str) -> dict[str, Any]:
    return {
        "contract_id": f"NVDA261009{right[0]}00180000.US",
        "underlying": "NVDA",
        "right": right,
        "expiry_date": "2026-10-09",
        "dte": 21,
        "delta": 0.52 if right == "CALL" else -0.52,
        "strike": 180.0,
        "multiplier": 100,
        "deliverable": "STANDARD",
        "adjusted": False,
        "bid": 0.33 if right == "CALL" else 0.38,
        "ask": 0.35 if right == "CALL" else 0.40,
        "bid_size": 5,
        "ask_size": 5,
    }


def _fixture_quote(plan: dict[str, Any], *, phase: str, bid: float, ask: float, suffix: str) -> dict[str, Any]:
    base = "2026-09-18T13:40:04" if phase == "ENTRY" else "2026-09-18T17:00:00"
    return {
        "quote_event_id": f"quote-{plan['right'].lower()}-{suffix}",
        "contract_id": plan["contract"]["contract_id"],
        "evidence_class": "RECEIPT_TIME_QUOTE_PROXY",
        "request_started_at": f"{base}.100000+00:00",
        "received_at": f"{base}.200000+00:00",
        "bid": bid,
        "ask": ask,
        "bid_size": 5,
        "ask_size": 5,
        "multiplier": 100,
        "session_health": "HEALTHY",
        "cached": False,
        "source_event_time": None,
        "classification": "SYNTHETIC_ENGINEERING_FIXTURE",
    }


def run_engineering_replay(db_path: Path, run_id: str) -> dict[str, Any]:
    policy = load_policy()
    ledger = PaperLedger(db_path, policy=policy)
    seen: set[str] = set()
    lifecycle: list[dict[str, Any]] = []
    plans: list[dict[str, Any]] = []
    for right in ("CALL", "PUT"):
        snapshot = _fixture_snapshot(right)
        candidate = evaluate_candidate(snapshot, policy=policy, seen_opportunities=seen)
        duplicate = evaluate_candidate(snapshot, policy=policy, seen_opportunities=seen)
        contract_result = select_contract(candidate, [_fixture_contract(right)], underlying_price=180.0, policy=policy)
        plan = freeze_plan(candidate, contract_result["selected"], policy=policy)
        ledger.record_plan(candidate, plan)
        plans.append(plan)
        predecision = _fixture_quote(plan, phase="ENTRY", bid=0.33, ask=0.35, suffix="predecision")
        predecision["request_started_at"] = "2026-09-18T13:40:03.900000+00:00"
        predecision["received_at"] = "2026-09-18T13:40:03.950000+00:00"
        rejected = ledger.attempt_entry(plan["plan_id"], predecision)
        entry = ledger.attempt_entry(plan["plan_id"], _fixture_quote(plan, phase="ENTRY", bid=0.33 if right == "CALL" else 0.38, ask=0.35 if right == "CALL" else 0.40, suffix="entry"))
        lifecycle.append({"right": right, "candidate": candidate, "duplicate": duplicate, "selection": contract_result, "predecision_quote": rejected, "entry": entry})

    call_plan, put_plan = plans
    call_exit = ledger.monitor_exit(call_plan["plan_id"], _fixture_quote(call_plan, phase="EXIT", bid=0.66, ask=0.68, suffix="exit"), trigger="PROFIT_REVIEW")
    put_pending = ledger.monitor_exit(put_plan["plan_id"], None, trigger="DATA_OR_QUOTE_RISK_PENDING")
    restart = PaperLedger(db_path, policy=policy)
    recovered = restart.open_positions()
    put_exit = restart.monitor_exit(put_plan["plan_id"], _fixture_quote(put_plan, phase="EXIT", bid=0.20, ask=0.21, suffix="recovered-exit"), trigger="HARD_LOSS")
    duplicate_exit = restart.monitor_exit(put_plan["plan_id"], _fixture_quote(put_plan, phase="EXIT", bid=0.20, ask=0.21, suffix="recovered-exit"), trigger="HARD_LOSS")
    rollback = restart.failure_probe()
    fixture_material = {"snapshots": [_fixture_snapshot("CALL"), _fixture_snapshot("PUT")], "contracts": [_fixture_contract("CALL"), _fixture_contract("PUT")]}
    ledger_summary = restart.summary()
    ledger_summary["counts"]["replay_runs"] += 1
    result = {
        "run_id": run_id,
        "classification": "SYNTHETIC_ENGINEERING_REPLAY_NOT_PERFORMANCE",
        "policy_id": policy["policy_id"],
        "policy_hash": content_hash(policy),
        "fixture_hash": content_hash(fixture_material),
        "portfolio_ids": {plan["right"]: plan["portfolio_id"] for plan in plans},
        "lifecycle": lifecycle,
        "exit_results": {"call": call_exit, "put_pending": put_pending, "put_recovered": put_exit, "duplicate_exit": duplicate_exit},
        "restart_recovered_open_positions": len(recovered),
        "rollback_probe": rollback,
        "ledger": ledger_summary,
        "performance_eligible": False,
        "signals_enabled": False,
        "forward_paper_enabled": False,
        "orders_enabled": False,
    }
    with restart._connect() as connection:
        existing = connection.execute("SELECT result_json FROM replay_runs WHERE run_id=?", (run_id,)).fetchone()
        if existing:
            stored = json.loads(existing["result_json"])
            return stored
        connection.execute("INSERT INTO replay_runs VALUES (?,?,?,?,?)", (run_id, result["policy_hash"], result["fixture_hash"], json_text(result), utc_now()))
    return result
