"""Read-only candidate views. Never instantiate the writer or accept file paths."""
from __future__ import annotations

from contextlib import closing
import json
import math
from pathlib import Path
import re
import sqlite3
import time

from fastapi import APIRouter, HTTPException, Query, Response

RUN_ID = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
PRIVATE = re.compile(r"secret|password|token|credential|api.?key|(?:^|_)path$|directory|config|manifest$", re.I)
QUOTE_FRESH_SECONDS = 30


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _latest_forward(db):
    # Read only small metadata rows until a forward run is found, not checkpoints.
    cursor = db.execute("SELECT run_id, metadata FROM candidate_runs ORDER BY created_at DESC, run_id DESC")
    for row in cursor:
        if _mapping(json.loads(row["metadata"])).get("command") == "forward":
            return db.execute("SELECT * FROM candidate_runs WHERE run_id=?", (row["run_id"],)).fetchone()
    return None


def _historical_run(db, reports):
    selection = reports / "candidate_selection.json"
    if not selection.is_file():
        return None
    try:
        if not selection.resolve().is_relative_to(reports.resolve()) or selection.stat().st_size > 1_000_000:
            return None
        frozen = json.loads(selection.read_text(encoding="utf-8"))
        candidate = frozen["selected"]
        run_id = frozen["candidates"][candidate]["run_id"]
        if not isinstance(run_id, str) or not re.fullmatch(RUN_ID, run_id):
            return None
        row = db.execute("SELECT metadata, status FROM candidate_runs WHERE run_id=?", (run_id,)).fetchone()
        if row:
            meta = json.loads(row["metadata"])
            if (row["status"] == "completed" and meta.get("command") == "replay"
                    and meta.get("candidate") == candidate and meta.get("cost_multiplier") == 1
                    and not meta.get("only_mode")):
                return run_id
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return None


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _valuation(state, account, initial, now):
    forward = _mapping(state.get("forward"))
    quotes = _mapping(forward.get("last_quote"))
    positions = _mapping(state.get("positions"))
    stale = [symbol for symbol in positions if forward.get("connected") is not True
             or not _finite(quotes.get(symbol)) or not 0 <= now - quotes[symbol] <= QUOTE_FRESH_SECONDS]
    last_known = account.get("equity")
    equity = None if stale else last_known if positions else state.get("cash")
    equity = equity if _finite(equity) else None
    return {"equity": equity, "last_known_equity": last_known if _finite(last_known) else None,
            "net_pnl": equity - initial if equity is not None and _finite(initial) else None,
            "unable_to_value": equity is None, "stale_quote_symbols": stale,
            "valuation_status": "unable_to_value" if equity is None else "available",
            "valuation_checked_at": now, "quote_fresh_seconds": QUOTE_FRESH_SECONDS}


def _public(value):
    """Strip private metadata and filesystem references from nested evidence."""
    if isinstance(value, dict):
        return {k: _public(v) for k, v in value.items() if not PRIVATE.search(k)}
    if isinstance(value, list):
        return [_public(v) for v in value]
    if isinstance(value, str) and (re.search(r"[A-Za-z]:[\\/]|\\\\|(?:^|[\s=\"'])/\S+", value)):
        return "[redacted]"
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def create_candidate_router(root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/crypto/candidate-simulation")
    database = root / "work" / "candidate_simulation.sqlite3"
    reports = root / "outputs" / "dual_regime_v1"

    def read(kind, run_id, response):
        response.headers["Cache-Control"] = "no-store"
        base = {"evidence_scope": "candidate_simulation", "research_only": True,
                "order_submission": False}
        if not database.is_file():
            return {**base, "status": "not_started"}
        try:
            with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA query_only=ON")
                db.execute("BEGIN")
                if kind == "status":
                    base.update(status_scope="forward", historical_report_run_id=_historical_run(db, reports))
                row = db.execute("SELECT * FROM candidate_runs WHERE run_id=?", (run_id,)).fetchone() if run_id else _latest_forward(db)
                if row is None:
                    if run_id:
                        raise HTTPException(404, "candidate run not found")
                    return {**base, "status": "not_started"}
                run_id = row["run_id"]
                if not re.fullmatch(RUN_ID, run_id):
                    raise ValueError("invalid stored run id")
                state = _mapping(json.loads(row["state"]))
                metadata = _mapping(json.loads(row["metadata"]))
                base.update(run_id=run_id, status=row["status"], updated_at=row["updated_at"])
                base.update(status_basis="PERSISTED_LEDGER_NOT_PROCESS_HEALTH",
                            process_liveness="UNVERIFIED", process_liveness_verified=False)
                if kind == "trades":
                    items = [json.loads(r[0]) for r in db.execute(
                        "SELECT payload FROM candidate_records WHERE run_id=? AND kind='trades' ORDER BY rowid DESC LIMIT 200",
                        (run_id,))]
                    count = db.execute("SELECT COUNT(*) FROM candidate_records WHERE run_id=? AND kind='trades'", (run_id,)).fetchone()[0]
                    return _public({**base, "items": items, "total": count, "limit": 200})
                if kind == "status":
                    latest = db.execute("SELECT payload FROM candidate_records WHERE run_id=? AND kind='equity' ORDER BY CAST(record_id AS REAL) DESC LIMIT 1", (run_id,)).fetchone()
                    account = _mapping(json.loads(latest[0])) if latest else {}
                    selected = {k: state.get(k) for k in ("cash", "positions", "pending", "decisions", "last_bars", "day_paused", "pause_until")}
                    selected["forward"] = {k: _mapping(state.get("forward")).get(k) for k in ("last_close", "connected", "reason")}
                    selected["last_hours"] = {}
                    for symbol, kernel in _mapping(state.get("kernels")).items():
                        bars = _mapping(kernel).get("hour_bars")
                        start = _mapping(bars[-1]).get("start") if isinstance(bars, list) and bars else None
                        if _finite(start):
                            selected["last_hours"][symbol] = start + 3600
                    initial = _mapping(metadata.get("policy")).get("initial_cash", _mapping(metadata.get("config")).get("initial_cash"))
                    selected.update(_valuation(state, account, initial, time.time()))
                    return _public({**base, "state": selected, "stop_requested": bool(row["stop_requested"]),
                                    "metadata": {k: metadata.get(k) for k in ("strategy_version", "policy_hash", "data_manifest_hash", "execution", "command", "candidate", "source_hashes")}})
            # Only the fixed run report is accessible; symlinks cannot escape it.
            report = reports / run_id / "metrics.json"
            if not report.resolve().is_relative_to(reports.resolve()):
                raise ValueError("invalid report location")
            if not report.is_file():
                return {**base, "report_status": "not_available", "performance_status": "PERFORMANCE_UNPROVEN"}
            if report.stat().st_size > 8_000_000:
                raise ValueError("report too large")
            metrics = json.loads(report.read_text(encoding="utf-8"))
            if not isinstance(metrics, dict) or metrics.get("run_id", run_id) != run_id:
                raise ValueError("invalid report")
            if metrics.get("policy_hash") and metrics["policy_hash"] != metadata.get("policy_hash"):
                raise ValueError("report policy mismatch")
            return _public({**base, "report_status": "available", "report_updated_at": report.stat().st_mtime, "metrics": metrics})
        except (sqlite3.Error, OSError, ValueError, TypeError, KeyError, AttributeError):
            raise HTTPException(503, "candidate evidence temporarily unavailable") from None

    @router.get("/status")
    def status(response: Response):
        return read("status", None, response)

    @router.get("/trades")
    def trades(response: Response, run_id: str = Query(..., pattern=RUN_ID)):
        return read("trades", run_id, response)

    @router.get("/report")
    def report(response: Response, run_id: str = Query(..., pattern=RUN_ID)):
        return read("report", run_id, response)

    return router
