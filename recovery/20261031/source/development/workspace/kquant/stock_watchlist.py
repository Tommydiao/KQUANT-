from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .longbridge_provider import longbridge_runtime
from .market_clock import market_clock
from .stock_signals import LONG_BRIDGE_TIMEOUT_SECONDS, api_stock_quotes_batch
from .stock_store import connect


WATCHLIST_VERSION = "stock_watchlist_groups_v1.0.0"
DAILY_REPORT_POLICY = "options_daily_scope_report_v1.1.0"
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "stock_watchlist_groups_v1.json"
NEW_YORK = ZoneInfo("America/New_York")
_US_TICKER = re.compile(r"^[A-Z][A-Z0-9.-]{0,15}$")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _attr(value: Any, *names: str) -> Any:
    if isinstance(value, dict):
        for name in names:
            if name in value:
                return value[name]
        return None
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return None


def _provider_candidate(raw_symbol: str) -> tuple[str | None, str, str]:
    normalized = raw_symbol.strip().upper()
    if not _US_TICKER.fullmatch(normalized):
        return None, "identity_unconfirmed", "provider_mapping_requires_manual_review"
    return f"{normalized}.US", "provider_candidate", "awaiting_provider_metadata"


def _config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != WATCHLIST_VERSION:
        raise ValueError("Unexpected watchlist configuration version.")
    return payload


def ensure_stock_watchlist_seed(db_path: Path, config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    payload = _config(config_path)
    now = _now()
    inserted_groups = 0
    inserted_members = 0
    with connect(db_path) as conn:
        for group_order, group in enumerate(payload["groups"]):
            group_id = str(group["group_id"])
            existing = conn.execute("SELECT 1 FROM stock_watchlist_groups WHERE group_id=?", (group_id,)).fetchone()
            conn.execute(
                """
                INSERT INTO stock_watchlist_groups(group_id, display_name, source_ref, sort_order, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(group_id) DO UPDATE SET
                  display_name=excluded.display_name,
                  source_ref=excluded.source_ref,
                  sort_order=excluded.sort_order,
                  updated_at=excluded.updated_at
                """,
                (group_id, str(group["name"]), str(payload["source"]), group_order, now, now),
            )
            inserted_groups += 0 if existing else 1
            for symbol_order, raw in enumerate(group["symbols"]):
                raw_symbol = str(raw).strip().upper()
                provider_symbol, identity_status, identity_reason = _provider_candidate(raw_symbol)
                existing_member = conn.execute(
                    "SELECT member_id FROM stock_watchlist_members WHERE group_id=? AND raw_symbol=?",
                    (group_id, raw_symbol),
                ).fetchone()
                if existing_member:
                    continue
                conn.execute(
                    """
                    INSERT INTO stock_watchlist_members(
                      member_id, group_id, raw_symbol, normalized_symbol, provider_symbol,
                      display_name, security_type, market, identity_status, identity_reason,
                      quote_support_status, history_support_status, options_support_status,
                      sort_order, status, metadata_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, 'not_checked', 'not_checked',
                              'not_checked', ?, 'active', '{}', ?, ?)
                    """,
                    (
                        f"watch-{uuid.uuid4().hex}", group_id, raw_symbol, raw_symbol,
                        provider_symbol, identity_status, identity_reason, symbol_order, now, now,
                    ),
                )
                inserted_members += 1
        conn.commit()
    return {
        "version": WATCHLIST_VERSION,
        "inserted_groups": inserted_groups,
        "inserted_members": inserted_members,
        **watchlist_counts(db_path),
    }


def watchlist_counts(db_path: Path) -> dict[str, int]:
    with connect(db_path) as conn:
        group_count = int(conn.execute("SELECT COUNT(*) FROM stock_watchlist_groups WHERE is_active=1").fetchone()[0])
        membership_count = int(conn.execute("SELECT COUNT(*) FROM stock_watchlist_members WHERE status='active'").fetchone()[0])
        distinct_symbols = int(conn.execute("SELECT COUNT(DISTINCT normalized_symbol) FROM stock_watchlist_members WHERE status='active'").fetchone()[0])
    return {"group_count": group_count, "membership_count": membership_count, "distinct_symbol_count": distinct_symbols}


def list_stock_watchlist_groups(db_path: Path) -> dict[str, Any]:
    ensure_stock_watchlist_seed(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT g.*, COUNT(m.member_id) AS member_count
            FROM stock_watchlist_groups g
            LEFT JOIN stock_watchlist_members m ON m.group_id=g.group_id AND m.status='active'
            WHERE g.is_active=1
            GROUP BY g.group_id
            ORDER BY g.sort_order, g.group_id
            """
        ).fetchall()
    return {"groups": [dict(row) for row in rows], **watchlist_counts(db_path), "version": WATCHLIST_VERSION}


def list_stock_watchlist_members(
    db_path: Path,
    *,
    group_id: str = "",
    query: str = "",
    include_removed: bool = False,
) -> dict[str, Any]:
    ensure_stock_watchlist_seed(db_path)
    clauses = [] if include_removed else ["m.status='active'"]
    values: list[Any] = []
    if group_id:
        clauses.append("m.group_id=?")
        values.append(group_id)
    if query.strip():
        clauses.append("(m.raw_symbol LIKE ? OR COALESCE(m.display_name, '') LIKE ?)")
        token = f"%{query.strip()}%"
        values.extend([token, token])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT m.*, g.display_name AS group_name, g.sort_order AS group_sort_order
            FROM stock_watchlist_members m
            JOIN stock_watchlist_groups g ON g.group_id=m.group_id
            {where}
            ORDER BY g.sort_order, m.sort_order, m.raw_symbol
            """,
            values,
        ).fetchall()
    return {"items": [dict(row) for row in rows], "count": len(rows), **watchlist_counts(db_path), "version": WATCHLIST_VERSION}


def add_stock_watchlist_member(db_path: Path, group_id: str, raw_symbol: str) -> dict[str, Any]:
    symbol = raw_symbol.strip().upper()
    if not symbol or len(symbol) > 32:
        raise ValueError("A watchlist symbol between 1 and 32 characters is required.")
    ensure_stock_watchlist_seed(db_path)
    provider_symbol, identity_status, identity_reason = _provider_candidate(symbol)
    now = _now()
    with connect(db_path) as conn:
        group = conn.execute("SELECT 1 FROM stock_watchlist_groups WHERE group_id=? AND is_active=1", (group_id,)).fetchone()
        if not group:
            raise ValueError("Unknown watchlist group.")
        prior = conn.execute(
            "SELECT * FROM stock_watchlist_members WHERE group_id=? AND raw_symbol=?",
            (group_id, symbol),
        ).fetchone()
        if prior:
            conn.execute("UPDATE stock_watchlist_members SET status='active', updated_at=? WHERE member_id=?", (now, prior["member_id"]))
            member_id = str(prior["member_id"])
        else:
            order_value = int(conn.execute("SELECT COALESCE(MAX(sort_order), -1)+1 FROM stock_watchlist_members WHERE group_id=?", (group_id,)).fetchone()[0])
            member_id = f"watch-{uuid.uuid4().hex}"
            conn.execute(
                """
                INSERT INTO stock_watchlist_members(
                  member_id, group_id, raw_symbol, normalized_symbol, provider_symbol,
                  display_name, security_type, market, identity_status, identity_reason,
                  quote_support_status, history_support_status, options_support_status,
                  sort_order, status, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, 'not_checked', 'not_checked',
                          'not_checked', ?, 'active', '{}', ?, ?)
                """,
                (member_id, group_id, symbol, symbol, provider_symbol, identity_status, identity_reason, order_value, now, now),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM stock_watchlist_members WHERE member_id=?", (member_id,)).fetchone()
    return dict(row)


def remove_stock_watchlist_member(db_path: Path, member_id: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM stock_watchlist_members WHERE member_id=?", (member_id,)).fetchone()
        if not row:
            raise ValueError("Unknown watchlist member.")
        conn.execute("UPDATE stock_watchlist_members SET status='removed', updated_at=? WHERE member_id=?", (_now(), member_id))
        conn.commit()
    return {"member_id": member_id, "status": "removed"}


def refresh_stock_watchlist_identities(db_path: Path) -> dict[str, Any]:
    ensure_stock_watchlist_seed(db_path)
    with connect(db_path) as conn:
        members = conn.execute(
            "SELECT DISTINCT normalized_symbol, provider_symbol FROM stock_watchlist_members WHERE status='active' AND provider_symbol IS NOT NULL ORDER BY normalized_symbol"
        ).fetchall()
    provider_symbols = [str(row["provider_symbol"]) for row in members]
    result = {"requested": len(provider_symbols), "verified": 0, "missing": 0, "status": "completed"}
    try:
        provider_rows = list(longbridge_runtime().static_info(provider_symbols, LONG_BRIDGE_TIMEOUT_SECONDS) or [])
        by_symbol = {str(_attr(row, "symbol", "code") or "").upper(): row for row in provider_rows}
        with connect(db_path) as conn:
            for member in members:
                provider_symbol = str(member["provider_symbol"])
                row = by_symbol.get(provider_symbol.upper())
                if row is None:
                    conn.execute(
                        """UPDATE stock_watchlist_members SET identity_status='identity_unconfirmed',
                           identity_reason='provider_returned_no_metadata', updated_at=?
                           WHERE normalized_symbol=? AND status='active'""",
                        (_now(), member["normalized_symbol"]),
                    )
                    result["missing"] += 1
                    continue
                name = str(_attr(row, "name_en", "name", "name_cn", "name_hk") or "")
                market = str(_attr(row, "exchange", "market") or "")
                security_type = str(_attr(row, "security_type", "type", "board") or "")
                metadata = {
                    "currency": str(_attr(row, "currency") or ""),
                    "lot_size": _attr(row, "lot_size"),
                    "provider_symbol": provider_symbol,
                    "source": "longbridge_static_info",
                }
                conn.execute(
                    """UPDATE stock_watchlist_members SET display_name=?, market=?, security_type=?,
                       identity_status='verified', identity_reason='longbridge_static_info',
                       metadata_json=?, updated_at=? WHERE normalized_symbol=? AND status='active'""",
                    (name or None, market or None, security_type or None, json.dumps(metadata, ensure_ascii=True, default=str), _now(), member["normalized_symbol"]),
                )
                result["verified"] += 1
            conn.commit()
    except Exception as exc:  # pragma: no cover - provider/network dependent
        result.update({"status": "provider_error", "error_type": type(exc).__name__, "message": str(exc)[:240]})
    return {**result, **watchlist_counts(db_path)}


def stock_watchlist_quotes(db_path: Path, group_id: str, *, selected_symbol: str = "") -> dict[str, Any]:
    members = list_stock_watchlist_members(db_path, group_id=group_id)["items"]
    supported = [item for item in members if item.get("provider_symbol")]
    quote_payload = api_stock_quotes_batch(
        [str(item["normalized_symbol"]) for item in supported],
        selected_symbol=selected_symbol,
        db_path=db_path,
    )
    quote_by_symbol = {str(item.get("symbol") or ""): item for item in quote_payload.get("items", [])}
    now = _now()
    with connect(db_path) as conn:
        for symbol, quote in quote_by_symbol.items():
            status = "available" if quote.get("provider_status") == "available" else "unavailable"
            conn.execute(
                "UPDATE stock_watchlist_members SET quote_support_status=?, updated_at=? WHERE normalized_symbol=? AND status='active'",
                (status, now, symbol),
            )
        conn.commit()
    items = []
    for member in members:
        quote = quote_by_symbol.get(str(member["normalized_symbol"]))
        items.append({**member, "quote": quote, "data_status": (quote or {}).get("provider_status") or member.get("identity_status")})
    available = sum(1 for item in items if (item.get("quote") or {}).get("provider_status") == "available")
    return {
        "group_id": group_id,
        "items": items,
        "count": len(items),
        "available_count": available,
        "unavailable_count": len(items) - available,
        "provider": quote_payload.get("provider", "longbridge"),
        "session": quote_payload.get("session"),
        "received_at": quote_payload.get("received_at"),
        "refresh_after_seconds": 15 if quote_payload.get("session") in {"pre", "regular", "post"} else 120,
        "read_only_market_data": True,
    }


def record_stock_watchlist_capability(db_path: Path, symbol: str, capability: str, status: str) -> None:
    """Record only capabilities that were actually requested from the provider."""
    column_by_capability = {
        "quote": "quote_support_status",
        "history": "history_support_status",
        "options": "options_support_status",
    }
    if capability not in column_by_capability:
        raise ValueError("Unknown stock watchlist capability.")
    if status not in {"available", "unavailable", "not_checked"}:
        raise ValueError("Unknown stock watchlist capability status.")
    normalized = symbol.strip().upper().split(".")[0]
    with connect(db_path) as conn:
        conn.execute(
            f"UPDATE stock_watchlist_members SET {column_by_capability[capability]}=?, updated_at=? "
            "WHERE normalized_symbol=? AND status='active'",
            (status, _now(), normalized),
        )
        conn.commit()


def watchlist_audit(db_path: Path) -> dict[str, Any]:
    payload = list_stock_watchlist_members(db_path, include_removed=False)
    items = payload["items"]
    membership_statuses: dict[str, int] = {}
    for item in items:
        key = str(item.get("identity_status") or "unknown")
        membership_statuses[key] = membership_statuses.get(key, 0) + 1
    grouped: dict[str, dict[str, Any]] = {}
    for item in items:
        symbol = str(item["normalized_symbol"])
        target = grouped.setdefault(
            symbol,
            {
                "symbol": symbol,
                "raw_symbols": [],
                "groups": [],
                "provider_symbol": item.get("provider_symbol"),
                "display_name": item.get("display_name"),
                "market": item.get("market"),
                "security_type": item.get("security_type"),
                "identity_statuses": [],
                "identity_reasons": [],
                "quote_support_statuses": [],
                "history_support_statuses": [],
                "options_support_statuses": [],
            },
        )
        target["raw_symbols"].append(str(item["raw_symbol"]))
        target["groups"].append({"group_id": item["group_id"], "name": item["group_name"]})
        for key in ("identity_status", "identity_reason", "quote_support_status", "history_support_status", "options_support_status"):
            plural_key = f"{key}es" if key.endswith("status") else f"{key}s"
            target[plural_key].append(str(item.get(key) or "unknown"))

    def merged_status(values: list[str]) -> str:
        if "available" in values:
            return "available"
        if "unavailable" in values:
            return "unavailable"
        return "not_checked"

    audited = []
    for symbol in sorted(grouped):
        target = grouped[symbol]
        identity_values = target.pop("identity_statuses")
        reason_values = target.pop("identity_reasons")
        quote_values = target.pop("quote_support_statuses")
        history_values = target.pop("history_support_statuses")
        options_values = target.pop("options_support_statuses")
        target.update(
            {
                "identity_status": "verified" if "verified" in identity_values else identity_values[0],
                "identity_reason": next((value for value in reason_values if value != "unknown"), "unknown"),
                "quote_support_status": merged_status(quote_values),
                "history_support_status": merged_status(history_values),
                "options_support_status": merged_status(options_values),
            }
        )
        target["raw_symbols"] = sorted(set(target["raw_symbols"]))
        audited.append(target)

    distinct_statuses: dict[str, int] = {}
    for item in audited:
        key = str(item.get("identity_status") or "unknown")
        distinct_statuses[key] = distinct_statuses.get(key, 0) + 1
    return {
        **{key: payload[key] for key in ("group_count", "membership_count", "distinct_symbol_count")},
        "identity_status_counts": distinct_statuses,
        "membership_identity_status_counts": membership_statuses,
        "unconfirmed": [
            {"symbol": item["symbol"], "groups": item["groups"], "reason": item["identity_reason"]}
            for item in audited if item.get("identity_status") != "verified"
        ],
        "items": audited,
        "version": WATCHLIST_VERSION,
        "price_values_imported": False,
    }


def _forward_daily_evidence(
    market_date: str,
    *,
    store_path: Path | None,
    run_id: str | None,
) -> dict[str, Any]:
    if store_path is None or not run_id:
        return {
            "status": "NOT_CONFIGURED",
            "error": None,
            "cycle": None,
            "observations": [],
            "candidates": [],
        }
    try:
        from .options_forward_paper import forward_status

        payload = forward_status(store_path=store_path, run_id=run_id)
    except Exception as exc:
        return {
            "status": "READ_FAILED",
            "error": f"{type(exc).__name__}: {str(exc)[:160]}",
            "cycle": None,
            "observations": [],
            "candidates": [],
        }

    cycles = [item for item in payload.get("cycles", []) if str(item.get("market_date")) == market_date]
    observations = [item for item in payload.get("observations", []) if str(item.get("market_date")) == market_date]
    records = payload.get("paper_records") or []
    records_by_scope = {
        (str(item.get("symbol") or ""), str(item.get("right") or "")): item
        for item in records
    }
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for observation in observations:
        if str(observation.get("state")) != "ELIGIBLE_RESEARCH_CANDIDATE":
            continue
        opportunity_id = str(observation.get("economic_opportunity_id") or observation.get("observation_id") or "")
        if not opportunity_id or opportunity_id in seen:
            continue
        seen.add(opportunity_id)
        evidence = observation.get("payload") or {}
        candidate = evidence.get("candidate") or {}
        selection = evidence.get("selection") or {}
        selected = selection.get("selected") or {}
        symbol = str(observation.get("symbol") or candidate.get("symbol") or "")
        right = str(observation.get("option_right") or candidate.get("right") or "")
        paper = records_by_scope.get((symbol, right), {})
        candidates.append(
            {
                "opportunity_id": opportunity_id,
                "symbol": symbol,
                "right": right,
                "profile_id": str(candidate.get("profile_id") or "SHORT_ATM_DAYS_WEEK"),
                "formed_at": observation.get("created_at"),
                "contract_symbol": selected.get("contract_id") or paper.get("contract_symbol"),
                "selection_status": selection.get("status"),
                "plan_state": paper.get("plan_state"),
                "evidence_class": candidate.get("evidence_class"),
                "decision_committed_at": candidate.get("decision_committed_at"),
                "reasons": list(candidate.get("reasons") or []),
                "strict_native_bbo_used": False,
                "real_order": False,
            }
        )
    return {
        "status": str(payload.get("status") or "NOT_STARTED"),
        "error": None,
        "cycle": cycles[0] if cycles else None,
        "observations": observations,
        "candidates": candidates,
    }


def daily_option_scope_report(
    db_path: Path,
    *,
    now: datetime | None = None,
    persist: bool = False,
    forward_store_path: Path | None = None,
    forward_run_id: str | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    local = current.astimezone(NEW_YORK)
    clock = market_clock(current)
    configured = _config()
    frozen_pool = [str(item) for item in configured["frozen_option_research_pool"]]
    watch_symbols = {
        str(item["normalized_symbol"])
        for item in list_stock_watchlist_members(db_path)["items"]
    }
    overlap = [symbol for symbol in frozen_pool if symbol in watch_symbols]
    original_pool_only = [symbol for symbol in frozen_pool if symbol not in watch_symbols]
    forward = _forward_daily_evidence(
        str(clock.market_date),
        store_path=forward_store_path,
        run_id=forward_run_id,
    )
    candidates = list(forward["candidates"])
    observations = list(forward["observations"])
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        by_symbol.setdefault(str(item.get("symbol") or ""), []).append(item)
    latest_observation: dict[tuple[str, str], dict[str, Any]] = {}
    for item in observations:
        key = (str(item.get("symbol") or ""), str(item.get("option_right") or ""))
        if key not in latest_observation:
            latest_observation[key] = item
    trading_day = bool(clock.is_trading_day)
    after_report = local.time() >= time(8, 30)
    after_confirmation = local.time() >= time(9, 40)
    if not trading_day:
        report_status, global_reason = "MARKET_CLOSED", "market_closed"
    elif not after_report:
        report_status, global_reason = "WAIT_PREMARKET_REPORT", "before_0830_et"
    elif not after_confirmation:
        report_status, global_reason = "WAIT_CONFIRMATION", "before_0940_et"
    elif forward["status"] == "READ_FAILED":
        report_status, global_reason = "TASK_FAILED", "frozen_forward_read_failed"
    elif forward["cycle"] is None:
        report_status, global_reason = "TASK_NOT_RUN", "frozen_forward_task_not_run"
    elif candidates:
        report_status, global_reason = "CANDIDATES_RECORDED", "frozen_scope_candidates_present"
    else:
        detail = (forward["cycle"] or {}).get("detail") or {}
        counts = detail.get("counts") or {}
        if int(counts.get("data_blocked") or 0) > 0:
            report_status, global_reason = "DATA_LIMITED", "frozen_evidence_or_market_data_blocked"
        else:
            report_status, global_reason = "NO_CANDIDATE", "frozen_conditions_not_met"
    checks = []
    for symbol in frozen_pool:
        symbol_candidates = by_symbol.get(symbol, [])
        if symbol_candidates:
            checks.append(
                {
                    "symbol": symbol,
                    "scope": "SHORT_ATM_DAYS_WEEK",
                    "status": "candidate",
                    "reason": "frozen_scope_candidate_recorded",
                    "rights": sorted({str(item.get("right") or "") for item in symbol_candidates}),
                    "opportunities": symbol_candidates,
                }
            )
            continue
        symbol_observations = [
            item for (observed_symbol, _), item in latest_observation.items()
            if observed_symbol == symbol
        ]
        blocked = [item for item in symbol_observations if str(item.get("state")) == "DATA_BLOCKED"]
        no_candidate = [item for item in symbol_observations if str(item.get("state")) == "NO_CANDIDATE"]
        evidence = blocked or no_candidate
        reasons: list[str] = []
        for item in evidence:
            candidate = (item.get("payload") or {}).get("candidate") or {}
            reasons.extend(str(value) for value in candidate.get("reasons") or [])
        status = "blocked" if blocked else "no_candidate"
        reason = reasons[0] if reasons else global_reason
        checks.append(
            {
                "symbol": symbol,
                "scope": "SHORT_ATM_DAYS_WEEK",
                "status": status,
                "reason": reason,
                "reasons": sorted(set(reasons)),
                "observed_rights": sorted({str(item.get("option_right") or "") for item in symbol_observations}),
            }
        )
    report = {
        "report_id": f"daily-scope-{clock.market_date}-{hashlib.sha256(DAILY_REPORT_POLICY.encode()).hexdigest()[:10]}",
        "market_date": str(clock.market_date),
        "generated_at": current.isoformat(),
        "status": report_status,
        "reason": global_reason,
        "task_source": "FROZEN_FORWARD_PAPER",
        "forward_run_id": forward_run_id,
        "forward_status": forward["status"],
        "forward_read_error": forward["error"],
        "counts": {
            "watchlist_distinct_symbols": len(watch_symbols),
            "frozen_scope_checked": len(frozen_pool),
            "watchlist_in_frozen_scope": len(overlap),
            "original_research_pool_only": len(original_pool_only),
            "watchlist_not_strategy_covered": len(watch_symbols - set(frozen_pool)),
            "candidates": len(candidates),
            "candidate_symbols": len(by_symbol),
            "blocked_or_no_candidate": len(frozen_pool) - len(by_symbol),
        },
        "checks": checks,
        "candidates": candidates,
        "watchlist_not_strategy_covered_reason": "market_data_covered_strategy_not_covered",
        "original_research_pool_only": original_pool_only,
        "policy_version": DAILY_REPORT_POLICY,
        "strategy_changed": False,
        "order_submission_enabled": False,
        "performance_claim": "NOT_EVALUATED",
    }
    if persist and trading_day and after_report:
        with connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO stock_watchlist_daily_reports(report_id, market_date, policy_version, status, generated_at, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(market_date, policy_version) DO UPDATE SET
                  status=excluded.status, generated_at=excluded.generated_at, payload_json=excluded.payload_json
                """,
                (report["report_id"], report["market_date"], DAILY_REPORT_POLICY, report_status, report["generated_at"], json.dumps(report, ensure_ascii=True)),
            )
            conn.commit()
    return report
