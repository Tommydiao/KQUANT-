from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .db.migrations import connect, migrate
from .evaluation_models import stable_hash
from .execution_models import AccountRiskSnapshot, ExecutionIntent, ExecutionRiskDecision
from .strategy_manifest import STRATEGY_MANIFESTS


def register_strategy_manifests(db_path: Path) -> None:
    migrate(db_path)
    now = datetime.now(UTC).isoformat()
    with connect(db_path) as conn:
        for manifest in STRATEGY_MANIFESTS:
            payload = manifest.as_dict()
            conn.execute(
                """
                INSERT INTO crypto_strategy_manifests(
                  strategy_version,market_type,direction,signal_interval,status,
                  executable,manifest_json,manifest_hash,registered_at
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(strategy_version) DO UPDATE SET
                  market_type=excluded.market_type,direction=excluded.direction,
                  signal_interval=excluded.signal_interval,status=excluded.status,
                  executable=excluded.executable,manifest_json=excluded.manifest_json,
                  manifest_hash=excluded.manifest_hash
                """,
                (
                    manifest.strategy_version, manifest.market_type, manifest.direction,
                    manifest.signal_interval, manifest.status, int(manifest.executable),
                    json.dumps(payload, ensure_ascii=True, sort_keys=True), stable_hash(payload), now,
                ),
            )


def save_execution_intent(db_path: Path, intent: ExecutionIntent) -> dict[str, Any]:
    migrate(db_path)
    with connect(db_path) as conn:
        existing = conn.execute(
            "SELECT payload_json FROM crypto_execution_intents WHERE evaluation_id=? AND material_state_hash=?",
            (intent.evaluation_id, intent.material_state_hash),
        ).fetchone()
        if existing is not None:
            return json.loads(existing["payload_json"])
        payload = intent.as_dict()
        conn.execute(
            """
            INSERT INTO crypto_execution_intents(
              intent_id,evaluation_id,strategy_version,symbol,market_type,direction,
              status,validation_gate_status,material_state_hash,payload_json,created_at,expires_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                intent.intent_id, intent.evaluation_id, intent.strategy_version, intent.symbol,
                intent.market_type, intent.direction, "pending", intent.validation_gate_status,
                intent.material_state_hash, json.dumps(payload, ensure_ascii=True, sort_keys=True),
                intent.created_at, intent.expires_at,
            ),
        )
    return payload


def save_risk_decision(
    db_path: Path,
    account: AccountRiskSnapshot,
    decision: ExecutionRiskDecision,
) -> None:
    migrate(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO crypto_account_risk_snapshots(
              snapshot_id,execution_mode,equity_usdt,available_usdt,
              daily_realized_pnl_usdt,open_risk_usdt,payload_json,captured_at
            ) VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                account.snapshot_id, account.mode, account.equity_usdt, account.available_usdt,
                account.daily_realized_pnl_usdt, account.open_risk_usdt,
                json.dumps(account.as_dict(), ensure_ascii=True, sort_keys=True), account.captured_at,
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO crypto_execution_risk_decisions(
              decision_id,intent_id,account_snapshot_id,allowed,blockers_json,warnings_json,
              quantity,estimated_notional,estimated_risk_usdt,decision_json,decided_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                decision.decision_id, decision.intent_id, account.snapshot_id, int(decision.allowed),
                json.dumps(list(decision.blockers), ensure_ascii=True),
                json.dumps(list(decision.warnings), ensure_ascii=True), decision.quantity,
                decision.estimated_notional, decision.estimated_risk_usdt,
                json.dumps(decision.as_dict(), ensure_ascii=True, sort_keys=True), decision.decided_at,
            ),
        )
        conn.execute(
            "UPDATE crypto_execution_intents SET status=? WHERE intent_id=?",
            ("risk_approved" if decision.allowed else "risk_blocked", decision.intent_id),
        )


def list_execution_orders(db_path: Path, *, limit: int = 100) -> list[dict[str, Any]]:
    migrate(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM crypto_exchange_orders ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [dict(row) for row in rows]


def list_orders_for_intent(db_path: Path, intent_id: str) -> list[dict[str, Any]]:
    migrate(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM crypto_exchange_orders WHERE intent_id=? ORDER BY created_at",
            (intent_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def save_exchange_order(
    db_path: Path,
    *,
    intent_id: str,
    client_order_id: str,
    execution_mode: str,
    symbol: str,
    market_type: str,
    order_role: str,
    side: str,
    order_type: str,
    status: str,
    quantity: float,
    price: float | None,
    stop_price: float | None,
    reduce_only: bool,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any] | None = None,
    local_order_id: str | None = None,
) -> dict[str, Any]:
    migrate(db_path)
    now = datetime.now(UTC).isoformat()
    local_id = local_order_id or f"order_{uuid4().hex}"
    response = response_payload or {}
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO crypto_exchange_orders(
              local_order_id,intent_id,client_order_id,exchange_order_id,execution_mode,symbol,
              market_type,order_role,side,order_type,status,quantity,price,stop_price,
              reduce_only,request_hash,response_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(client_order_id) DO UPDATE SET
              exchange_order_id=excluded.exchange_order_id,status=excluded.status,
              response_json=excluded.response_json,updated_at=excluded.updated_at
            """,
            (
                local_id, intent_id, client_order_id,
                str(response.get("orderId")) if response.get("orderId") is not None else None,
                execution_mode, symbol, market_type, order_role, side, order_type, status, quantity,
                price, stop_price, int(reduce_only), stable_hash(request_payload),
                json.dumps(response, ensure_ascii=True, sort_keys=True), now, now,
            ),
        )
        row = conn.execute("SELECT * FROM crypto_exchange_orders WHERE client_order_id=?", (client_order_id,)).fetchone()
    return dict(row)


def save_exchange_fill(
    db_path: Path,
    *,
    local_order_id: str,
    exchange_trade_id: str,
    quantity: float,
    price: float,
    commission: float = 0.0,
    commission_asset: str | None = None,
    realized_pnl_usdt: float | None = None,
    funding_usdt: float | None = None,
    filled_at: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    migrate(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO crypto_exchange_fills(
              fill_id,local_order_id,exchange_trade_id,quantity,price,commission,
              commission_asset,realized_pnl_usdt,funding_usdt,filled_at,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"fill_{uuid4().hex}", local_order_id, exchange_trade_id, quantity, price,
                commission, commission_asset, realized_pnl_usdt, funding_usdt,
                filled_at or datetime.now(UTC).isoformat(),
                json.dumps(payload or {}, ensure_ascii=True, sort_keys=True),
            ),
        )


def local_daily_realized_pnl(db_path: Path, risk_date: str) -> float:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(COALESCE(realized_pnl_usdt,0)-commission+COALESCE(funding_usdt,0)),0)
            FROM crypto_exchange_fills WHERE substr(filled_at,1,10)=?
            """,
            (risk_date,),
        ).fetchone()
    return float(row[0] or 0.0)


def save_account_event(
    db_path: Path,
    *,
    execution_mode: str,
    market_type: str,
    event_type: str,
    source_time: str,
    received_at: str,
    sequence_key: str,
    payload: dict[str, Any],
) -> bool:
    migrate(db_path)
    payload_json = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    payload_hash = stable_hash(payload)
    with connect(db_path) as conn:
        before = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO crypto_exchange_account_events(
              event_id,execution_mode,market_type,event_type,source_time,
              received_at,sequence_key,payload_json,content_hash
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                f"account_event_{uuid4().hex}", execution_mode, market_type,
                event_type, source_time, received_at, sequence_key,
                payload_json, payload_hash,
            ),
        )
        return conn.total_changes > before


def update_order_from_account_event(
    db_path: Path,
    *,
    client_order_id: str,
    status: str,
    response_payload: dict[str, Any],
) -> dict[str, Any] | None:
    migrate(db_path)
    now = datetime.now(UTC).isoformat()
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT local_order_id FROM crypto_exchange_orders WHERE client_order_id=?",
            (client_order_id,),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE crypto_exchange_orders SET status=?,response_json=?,updated_at=? WHERE client_order_id=?",
            (status, json.dumps(response_payload, ensure_ascii=True, sort_keys=True), now, client_order_id),
        )
        updated = conn.execute(
            "SELECT * FROM crypto_exchange_orders WHERE client_order_id=?", (client_order_id,)
        ).fetchone()
    return dict(updated)


def latest_validation_gate_for_strategy(db_path: Path, strategy_version: str) -> dict[str, Any] | None:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT report_json FROM crypto_validation_runs WHERE strategy_version=? ORDER BY created_at DESC LIMIT 1",
            (strategy_version,),
        ).fetchone()
    if row is None:
        return None
    report = json.loads(row["report_json"])
    return report.get("validation_gate")


def testnet_release_gate(db_path: Path) -> dict[str, Any]:
    migrate(db_path)
    with connect(db_path) as conn:
        fill_window = conn.execute(
            """
            SELECT MIN(f.filled_at),MAX(f.filled_at),COUNT(*)
            FROM crypto_exchange_fills f
            JOIN crypto_exchange_orders o ON o.local_order_id=f.local_order_id
            WHERE o.execution_mode='testnet'
            """
        ).fetchone()
        closed = conn.execute(
            """
            SELECT COUNT(*) FROM (
              SELECT o.intent_id
              FROM crypto_exchange_orders o
              JOIN crypto_exchange_fills f ON f.local_order_id=o.local_order_id
              WHERE o.execution_mode='testnet'
              GROUP BY o.intent_id
              HAVING SUM(CASE WHEN o.order_role='entry' THEN 1 ELSE 0 END)>0
                 AND SUM(CASE WHEN o.order_role IN ('stop','target','emergency_exit') THEN 1 ELSE 0 END)>0
            )
            """
        ).fetchone()[0]
        unsafe = conn.execute(
            """
            SELECT COUNT(*) FROM crypto_exchange_orders
            WHERE execution_mode='testnet' AND status IN ('unknown','protection_failed')
            """
        ).fetchone()[0]
        latest_reconciliation = conn.execute(
            "SELECT status,discrepancy_count FROM crypto_reconciliation_runs WHERE execution_mode='testnet' ORDER BY finished_at DESC LIMIT 1"
        ).fetchone()
    duration_days = 0.0
    if fill_window[0] and fill_window[1]:
        first = datetime.fromisoformat(str(fill_window[0]).replace("Z", "+00:00"))
        last = datetime.fromisoformat(str(fill_window[1]).replace("Z", "+00:00"))
        duration_days = max(0.0, (last - first).total_seconds() / 86400.0)
    checks = {
        "calendar_days": duration_days >= 14.0,
        "closed_trades": int(closed) >= 30,
        "unsafe_orders": int(unsafe) == 0,
        "reconciliation": bool(latest_reconciliation and latest_reconciliation["status"] == "matched" and int(latest_reconciliation["discrepancy_count"]) == 0),
    }
    return {
        "status": "PASS" if all(checks.values()) else "NO_GO",
        "checks": checks,
        "observed": {
            "calendar_days": duration_days,
            "closed_trades": int(closed),
            "fill_count": int(fill_window[2] or 0),
            "unsafe_orders": int(unsafe),
        },
    }


def list_execution_positions(db_path: Path) -> list[dict[str, Any]]:
    migrate(db_path)
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM crypto_exchange_positions WHERE ABS(quantity)>0 ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def latest_account_snapshot(db_path: Path) -> dict[str, Any] | None:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT payload_json FROM crypto_account_risk_snapshots ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()
    return json.loads(row["payload_json"]) if row else None


def record_kill_switch(db_path: Path, *, action: str, reason: str, source: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    migrate(db_path)
    value = {
        "event_id": f"kill_{uuid4().hex}",
        "action": action,
        "reason": reason,
        "source": source,
        "details": details or {},
        "created_at": datetime.now(UTC).isoformat(),
    }
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO crypto_kill_switch_events(event_id,action,reason,source,details_json,created_at) VALUES(?,?,?,?,?,?)",
            (value["event_id"], action, reason, source, json.dumps(value["details"], ensure_ascii=True, sort_keys=True), value["created_at"]),
        )
    return value


def save_reconciliation(db_path: Path, *, mode: str, status: str, discrepancies: list[dict[str, Any]], started_at: str) -> dict[str, Any]:
    migrate(db_path)
    value = {
        "reconciliation_id": f"reconcile_{uuid4().hex}",
        "execution_mode": mode,
        "status": status,
        "discrepancy_count": len(discrepancies),
        "discrepancies": discrepancies,
        "started_at": started_at,
        "finished_at": datetime.now(UTC).isoformat(),
    }
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO crypto_reconciliation_runs(reconciliation_id,execution_mode,status,discrepancy_count,details_json,started_at,finished_at) VALUES(?,?,?,?,?,?,?)",
            (
                value["reconciliation_id"], mode, status, len(discrepancies),
                json.dumps(discrepancies, ensure_ascii=True, sort_keys=True), started_at, value["finished_at"],
            ),
        )
    return value
