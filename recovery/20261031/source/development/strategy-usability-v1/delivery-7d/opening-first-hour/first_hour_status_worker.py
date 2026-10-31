"""Disposable, read-only status queries; no SDK or Supervisor in this process."""
from __future__ import annotations

from kquant.status_child_telemetry import begin_child, capture, emit_stage, empty_transport

if __name__ == "__main__":
    _import_started = begin_child()

import json
import sqlite3
import sys
import logging
from datetime import UTC, datetime
from time import monotonic, perf_counter
from pathlib import Path
from threading import Lock
from os import getpid
from uuid import uuid4
from kquant import __file__ as _package_file

from kquant.options_opening_trend_projection import ProjectionCache


ROOT = Path(_package_file).resolve().parents[1]
_trend_projection = ProjectionCache()
_trend_projection_lock = Lock()
_momentum_projection = ProjectionCache()
_momentum_projection_lock = Lock()
_coverage_pages = {}
_attempt_lock = Lock()
_attempt_counts = {"attempts": 0, "successes": 0, "failures": 0, "deadlines": 0}
_error_types = {"FileNotFoundError", "JSONDecodeError", "TimeoutError", "StatusQueryTimeout",
    "OperationalError", "RuntimeError", "ValueError", "TypeError", "KeyError", "OSError",
    "DatabaseError", "ImportError", "ModuleNotFoundError", "UnicodeEncodeError", "UnicodeDecodeError"}
_sqlite_codes = {None, "SQLITE_BUSY", "SQLITE_LOCKED", "SQLITE_INTERRUPT", "SQLITE_ERROR",
    "SQLITE_READONLY", "SQLITE_CANTOPEN", "SQLITE_CORRUPT", "SQLITE_NOTADB", "SQLITE_IOERR"}
_query_lanes = {"status", "one_minute:status", "opening_trend:current", "opening_trend:compact",
    "opening_trend:status", "opening_momentum:current", "opening_momentum:compact", "opening_momentum:status"}


def observer_boundary(policy_hash, scope_hash):
    import os
    from hashlib import sha256
    try:
        path = Path(os.environ["KQUANT_RUNTIME_MANIFEST"]).resolve()
        if not path.is_relative_to(ROOT / "outputs") or path.stat().st_size > 262144:
            return None
        raw = path.read_bytes()
        if sha256(raw).hexdigest() != os.environ["KQUANT_BACKEND_MANIFEST_SHA256"]:
            return None
        boundary = json.loads(raw)["coverage_boundary"]
        if boundary["policy_hash"] != policy_hash or boundary["scope_hash"] != scope_hash:
            return None
        return boundary["observer_started_at"]
    except (OSError, KeyError, ValueError, TypeError):
        return None


class StatusQueryTimeout(RuntimeError):
    pass


class StatusQueryFailure(RuntimeError):
    def __init__(self, diagnostic):
        super().__init__("STATUS_QUERY_FAILED")
        self.diagnostic = diagnostic


def safe_failure(exc, *, phase="worker", elapsed_ms=None, returncode=None):
    codes = {"FileNotFoundError": "DATABASE_MISSING", "JSONDecodeError": "SERIALIZATION_INVALID",
             "TimeoutError": "QUERY_BUDGET_EXCEEDED", "StatusQueryTimeout": "PROCESS_DEADLINE"}
    code = codes.get(type(exc).__name__, "QUERY_FAILED")
    if isinstance(exc, FileNotFoundError) and phase == "policy":
        code = "POLICY_CONFIG_MISSING"
    sqlite_code = getattr(exc, "sqlite_errorname", None)
    if not isinstance(sqlite_code, (str, type(None))) or sqlite_code not in _sqlite_codes:
        sqlite_code = None
    if sqlite_code in {"SQLITE_BUSY", "SQLITE_LOCKED"}:
        code = "DATABASE_LOCKED"
    elif sqlite_code == "SQLITE_INTERRUPT":
        code = "QUERY_BUDGET_EXCEEDED"
    error_type = type(exc).__name__ if type(exc).__name__ in _error_types else "RuntimeError"
    return {"code": code, "phase": phase, "error_type": error_type,
            "sqlite_code": sqlite_code, "elapsed_ms": elapsed_ms, "returncode": returncode}


def _phase(name, operation):
    started = perf_counter()
    emit_stage(name, "start")
    outcome = "done"
    try:
        return operation()
    except Exception as exc:
        outcome = "failed"
        if not hasattr(exc, "status_query_phase"):
            exc.status_query_phase = name
        raise
    finally:
        elapsed_ms = (perf_counter() - started) * 1000
        emit_stage(name, outcome, elapsed_ms=elapsed_ms)
        logging.getLogger(__name__).info("status_phase observed_at=%s phase=%s elapsed_ms=%.3f",
            datetime.now(UTC).isoformat(), name, elapsed_ms)


def _record_attempt(transport, outcome):
    transport.setdefault('request_id',uuid4().hex)
    with _attempt_lock:
        _attempt_counts["attempts"] += 1
        _attempt_counts["successes" if outcome == "SUCCESS" else "failures"] += 1
        _attempt_counts["deadlines"] += int(outcome == "PROCESS_DEADLINE")
        transport["denominator"] = {**_attempt_counts, "scope": "PARENT_PROCESS"}
    transport.update(outcome=outcome, parent_pid=getpid(), attempt_id=transport["denominator"]["attempts"],
                     observed_at=datetime.now(UTC).isoformat())
    logger = logging.getLogger(__name__)
    (logger.info if outcome == "SUCCESS" else logger.warning)("status_query_attempt %s",
        json.dumps({key: value for key, value in transport.items() if key != "stderr_sanitized"},
                   ensure_ascii=True, separators=(",", ":")))


def run_json(command: list[str], *, timeout: float = 2.0, diagnostics: bool = False, lane="status") -> dict:
    started = perf_counter()
    transport = empty_transport(timeout)
    request_id=uuid4().hex
    transport['request_id']=request_id
    lane = lane if isinstance(lane, str) and lane in _query_lanes else "status"
    transport["query_lane"] = lane
    logging.getLogger(__name__).info('status_query_start request_id=%s lane=%s observed_at=%s budget_ms=%.3f',
        request_id,lane,datetime.now(UTC).isoformat(),timeout*1000)
    try:
        stdout, transport, expired = capture(command, cwd=ROOT, timeout=timeout,request_id=request_id)
    except OSError as exc:
        transport["process_ms"] = round((perf_counter() - started) * 1000, 3)
        _record_attempt(transport, "PROCESS_START_FAILED")
        if not diagnostics:
            raise
        problem = safe_failure(exc, phase="process", elapsed_ms=transport["process_ms"])
        problem.update(code="PROCESS_START_FAILED", query_transport=transport)
        raise StatusQueryFailure(problem) from exc
    transport["query_lane"] = lane
    if expired:
        logging.getLogger(__name__).warning("status_process_deadline observed_at=%s budget_ms=%.3f elapsed_ms=%.3f",
            datetime.now(UTC).isoformat(), timeout * 1000, (perf_counter() - started) * 1000)
        _record_attempt(transport, "PROCESS_DEADLINE")
        problem = StatusQueryTimeout("STATUS_QUERY_DEADLINE")
        problem.diagnostic = safe_failure(problem, phase="process", elapsed_ms=transport["process_ms"],
                                          returncode=transport["returncode"])
        problem.diagnostic["query_transport"] = transport
        raise problem
    if transport["returncode"]:
        _record_attempt(transport, "CHILD_ERROR")
        if diagnostics:
            try:
                packet = json.loads(stdout)
                error = packet["_status_error"]
                if set(error) == {"code", "phase", "error_type", "sqlite_code", "elapsed_ms", "returncode"}:
                    # The protocol contains no provider text, stderr, paths or secrets.
                    allowed = {"code": {"DATABASE_MISSING", "POLICY_CONFIG_MISSING", "SERIALIZATION_INVALID", "QUERY_BUDGET_EXCEEDED", "PROCESS_DEADLINE", "DATABASE_LOCKED", "QUERY_FAILED"},
                               "phase": {"worker", "policy", "universe", "latest_status", "checkpoint_audit", "serialization", "import", "query", "current_cards", "projection_delta", "qualification_stages", "clock", "encode", "ipc"},
                               "error_type": _error_types,
                               "sqlite_code": _sqlite_codes}
                    if all(error[key] in values for key, values in allowed.items()):
                        error.update(returncode=transport["returncode"], elapsed_ms=transport["process_ms"],
                                     query_transport=transport)
                        raise StatusQueryFailure(error)
            except (ValueError, KeyError, TypeError, UnicodeError, RecursionError):
                pass
        if diagnostics:
            raise StatusQueryFailure({"code": "ERROR_PROTOCOL_INVALID", "phase": "process",
                "error_type": "RuntimeError", "sqlite_code": None,
                "elapsed_ms": transport["process_ms"], "returncode": transport["returncode"],
                "query_transport": transport})
        raise RuntimeError("STATUS_QUERY_FAILED")
    received = perf_counter()
    try:
        if transport["response_truncated"]:
            raise ValueError("STATUS_RESPONSE_BOUND_EXCEEDED")
        value = json.loads(stdout)
        if not isinstance(value, dict) or "_status_error" in value:
            raise ValueError("STATUS_QUERY_INVALID_PAYLOAD")
    except (ValueError, UnicodeError, RecursionError) as exc:
        transport["decode_ms"] = round((perf_counter() - received) * 1000, 3)
        _record_attempt(transport, "SERIALIZATION_INVALID")
        if not diagnostics:
            raise
        problem = safe_failure(exc, phase="serialization", returncode=transport["returncode"],
                               elapsed_ms=transport["process_ms"])
        problem.update(code="SERIALIZATION_INVALID", query_transport=transport)
        raise StatusQueryFailure(problem) from exc
    transport["decode_ms"] = round((perf_counter() - received) * 1000, 3)
    _record_attempt(transport, "SUCCESS")
    if diagnostics:
        value["query_transport"] = transport
    return value


def load_one_minute(db_path: str | Path, *, minute_path=None, now=None) -> dict:
    started = perf_counter()
    try:
        context = one_minute_history_context(now)
    except Exception as exc:
        transport = empty_transport()
        transport.update(query_lane="one_minute:status", last_phase="policy",
                         process_ms=0.0, history_context_ms=round((perf_counter()-started)*1000, 3))
        _record_attempt(transport, "HISTORY_CONTEXT_FAILED")
        diagnostic = safe_failure(exc, phase="policy", elapsed_ms=transport["history_context_ms"])
        diagnostic["query_transport"] = transport
        raise StatusQueryFailure(diagnostic) from exc
    context_ms = round((perf_counter() - started) * 1000, 3)
    command = [sys.executable, "-B", "-m", "kquant.status_worker", str(db_path),
                      "--history-context", json.dumps(context, separators=(",", ":")),
                      "--diagnostic-envelope"]
    if minute_path is not None:
        command += ["--minute-store", str(minute_path)]
    result = run_json(command, diagnostics=True, lane="one_minute:status")
    result["history_context_ms"] = context_ms
    return result


def one_minute_history_context(now=None):
    # This is called by the existing background loader, never by a status GET.
    # Reuse its XNYS calendar instead of cold-building one in every short-lived child.
    from kquant.options_one_minute import NY, load_policy, timestamp
    from kquant.options_two_hour_data import sessions_before
    policy = load_policy()
    current = timestamp(now or datetime.now(UTC))
    sessions = sessions_before(current.astimezone(NY).date(), policy["history_sessions"])
    if now is None:
        refreshed = datetime.now(UTC)
        if refreshed.astimezone(NY).date() != current.astimezone(NY).date():
            sessions = sessions_before(refreshed.astimezone(NY).date(), policy["history_sessions"])
        current = refreshed
    return {"as_of": current.isoformat(), "prepared_at": datetime.now(UTC).isoformat(),
            "policy_hash": policy["policy_hash"],
            "calendar_source": "exchange_calendars:XNYS",
            "sessions": sessions}


def _require_policy(research_strategy, *, lane="status"):
    if research_strategy not in {"opening_trend", "opening_momentum"}:
        raise ValueError("INVALID_RESEARCH_STRATEGY")
    started = monotonic()
    name = "options_opening_momentum_v1.json" if research_strategy == "opening_momentum" else "options_opening_trend_v1.json"
    try:
        if not (ROOT / "config" / name).is_file():
            raise FileNotFoundError("STATUS_POLICY_MISSING")
    except OSError as exc:
        elapsed_ms = round((monotonic() - started) * 1000, 3)
        transport = empty_transport()
        transport.update(last_phase="policy", process_ms=elapsed_ms)
        transport["query_lane"] = lane if lane in _query_lanes else "status"
        _record_attempt(transport, "POLICY_CONFIG_MISSING")
        problem = safe_failure(exc, phase="policy", elapsed_ms=elapsed_ms)
        problem["query_transport"] = transport
        raise StatusQueryFailure(problem) from exc


def load_current_cards(db_path, *, research_strategy, trend_path=None, now=None):
    # Background loaders can reject a known missing prerequisite without spawning
    # another process. The child still validates contents on every actual read.
    lane = f"{research_strategy}:current"
    _require_policy(research_strategy, lane=lane)
    return run_json([sys.executable, "-B", "-m", "kquant.status_worker", str(db_path),
                    "--strategy", research_strategy, "--current-cards", "--diagnostic-envelope"] +
                    (["--research-store", str(trend_path)] if trend_path is not None else []) +
                    (["--as-of", now.isoformat()] if now is not None else []), diagnostics=True, lane=lane)


def load_opening_trend(db_path: str | Path, *, compact=False, research_strategy="opening_trend", trend_path=None, now=None) -> dict:
    lane = f"{research_strategy}:{'compact' if compact else 'status'}"
    _require_policy(research_strategy, lane=lane)
    projection, lock = ((_momentum_projection, _momentum_projection_lock)
                        if research_strategy == "opening_momentum" else (_trend_projection, _trend_projection_lock))
    if not lock.acquire(blocking=False):
        error = StatusQueryTimeout("STATUS_QUERY_ALREADY_RUNNING")
        error.diagnostic = safe_failure(error, phase="single_flight")
        error.diagnostic["code"] = "QUERY_ALREADY_RUNNING"
        transport = empty_transport()
        transport["last_phase"] = "single_flight"
        transport["query_lane"] = lane
        _record_attempt(transport, "QUERY_ALREADY_RUNNING")
        error.diagnostic["query_transport"] = transport
        raise error
    try:
        command = [sys.executable, "-B", "-m", "kquant.status_worker", str(db_path),
                   "--strategy", research_strategy, "--projection-after", str(projection.after), "--diagnostic-envelope"]
        if compact:
            command.append("--compact")
        if trend_path is not None:
            command.extend(["--research-store", str(trend_path)])
        if now is not None:
            command.extend(["--as-of", now.isoformat()])
        value = run_json(command, diagnostics=True, lane=lane)
        context = value.pop("_projection_context", None)
        delta = value.pop("_projection_delta", None)
        if delta is not None:
            value["checkpoint_coverage"] = projection.apply(delta,
                registered=context["registered"], now=context["now"], policy=value["policy"], scope_hash=value["scope_hash"],
                observer_started_at=observer_boundary(value["policy"]["policy_hash"], value["scope_hash"]))
            from kquant.options_opening_trend_coverage import attach_qualification_stages
            attach_qualification_stages(value["checkpoint_coverage"], value.pop("_qualification_stages"))
            _coverage_pages[research_strategy] = value["checkpoint_coverage"]
        if compact:
            from kquant.options_opening_trend_summary import compact_status
            value = compact_status(value)
        return value
    finally:
        lock.release()


def coverage_page(*, research_strategy, session, scope_hash, checkpoint, offset=0, limit=50):
    from copy import deepcopy
    if research_strategy not in {"opening_trend", "opening_momentum"} or not 0 <= offset <= 2442 or not 1 <= limit <= 100:
        raise ValueError("INVALID_COVERAGE_PAGE")
    coverage = _coverage_pages.get(research_strategy)
    if not coverage or coverage.get("session") != session or coverage.get("scope_hash") != scope_hash:
        raise StatusQueryTimeout("COVERAGE_SNAPSHOT_NOT_AVAILABLE")
    point = next((p for p in coverage.get("checkpoints", []) if p["bar_end"] == checkpoint), None)
    if point is None:
        raise ValueError("UNKNOWN_CHECKPOINT")
    rows = point["items"]
    return {"session": session, "scope_hash": scope_hash, "checkpoint": checkpoint,
        "as_of": coverage["checked_at"], "items": deepcopy(rows[offset:offset + limit]),
        "total": len(rows), "offset": offset, "next_offset": offset + limit if offset + limit < len(rows) else None,
        "read_only": True}


def query_opening_trend(db_path: Path, *, now=None, trend_path=None, projection_after=None, compact=False,
                        research_strategy="opening_trend", current_cards=False) -> dict:
    from datetime import UTC, datetime
    from kquant.options_two_hour_data import universe
    from kquant import options_one_minute as common
    from kquant import options_opening_trend_store as store
    from kquant.options_opening_trend_coverage import audit
    if not db_path.is_file():
        raise FileNotFoundError("STATUS_DATABASE_MISSING")
    path = trend_path or store.STORE
    if not path.is_file():
        raise FileNotFoundError("TREND_STATUS_DATABASE_MISSING")
    now = common.timestamp(now or datetime.now(UTC))
    started = monotonic()
    scope = _phase("universe", lambda: universe(db_path))
    from kquant import options_opening_momentum, options_opening_trend
    policy = _phase("policy", lambda: (__import__("first_hour") if research_strategy == "opening_momentum" else options_opening_trend).load_policy())
    if current_cards:
        return _phase("current_cards", lambda: store.current_cards(path=path,
            session=now.astimezone(common.NY).date().isoformat(),
            scope_hash=scope["scope_hash"], now=now, policy=policy))
    scope_loaded = monotonic()
    result = _phase("latest_status", lambda: store.status(session=now.astimezone(common.NY).date().isoformat(),
                          path=path, now=now, scope_hash=scope["scope_hash"], compact=compact, policy=policy))
    result["research_strategy"] = research_strategy
    result["scope_hash"] = scope["scope_hash"]
    status_loaded = monotonic()
    if projection_after is None:
        result["checkpoint_coverage"] = _phase("checkpoint_audit", lambda: audit(path,
            scope["items"], now=now, scope_hash=scope["scope_hash"], policy=policy,
            observer_started_at=observer_boundary(policy["policy_hash"], scope["scope_hash"])))
    else:
        from kquant.options_opening_trend_projection import read_delta
        try:
            result["_projection_delta"] = _phase("projection_delta", lambda: read_delta(path,
                session=result["session"], policy_hash=result["policy"]["policy_hash"], after=projection_after))
            result["_projection_context"] = {"registered": scope["items"], "now": now.isoformat()}
            from kquant.options_opening_trend_coverage import qualification_stages
            result["_qualification_stages"] = _phase("qualification_stages", lambda: qualification_stages(path,
                session=result["session"], policy_hash=result["policy"]["policy_hash"],
                scope_hash=scope["scope_hash"], now=now))
        except (sqlite3.Error, TimeoutError, ValueError, OSError) as exc:
            result["checkpoint_coverage"] = {"state": "UNAVAILABLE", "reason": "PROJECTION_READ_FAILED",
                "error_type": type(exc).__name__, "checkpoints": [], "read_only": True,
                "qualified_signal_acceptance": False}
    result["query_phases_ms"] = {
        "universe": round((scope_loaded - started) * 1000, 3),
        "latest_status": round((status_loaded - scope_loaded) * 1000, 3),
        "checkpoint_audit": round((monotonic() - status_loaded) * 1000, 3),
    }
    if compact and projection_after is None:
        from kquant.options_opening_trend_summary import compact_status
        result = compact_status(result)
    return result


def query(db_path: Path, *, history_context=None, minute_path=None) -> dict:
    from kquant.options_one_minute import NY, load_policy, status, timestamp
    from kquant.options_two_hour_data import universe

    # Missing databases must fail, not create an empty replacement.
    if not db_path.is_file():
        raise FileNotFoundError("STATUS_DATABASE_MISSING")
    extra = {}
    if minute_path is not None:
        if not minute_path.is_file():
            raise FileNotFoundError("STATUS_DATABASE_MISSING")
        extra["path"] = minute_path
    scope_hash = universe(db_path)["scope_hash"]
    if history_context is None:
        return status(scope_hash=scope_hash, **extra)
    from kquant.options_one_minute_status import validate_history_sessions
    policy = load_policy()
    if (not isinstance(history_context, dict)
            or set(history_context) != {"as_of", "prepared_at", "policy_hash", "calendar_source", "sessions"}
            or history_context["policy_hash"] != policy["policy_hash"]
            or history_context["calendar_source"] != "exchange_calendars:XNYS"):
        raise ValueError("STATUS_HISTORY_CONTEXT_INVALID")
    current = timestamp(history_context["as_of"])
    age = (datetime.now(UTC) - timestamp(history_context["prepared_at"])).total_seconds()
    if not 0 <= age <= 2.0:
        raise ValueError("STATUS_HISTORY_CONTEXT_STALE")
    sessions = validate_history_sessions(history_context["sessions"],
        session=current.astimezone(NY).date().isoformat(), count=policy["history_sessions"])
    return status(scope_hash=scope_hash, policy=policy, now=current, history_sessions=sessions, **extra)


def _write_encoded(encoded):
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("db_path", type=Path)
    parser.add_argument("--strategy", choices=("one_minute", "opening_trend", "opening_momentum"), default="one_minute")
    parser.add_argument("--projection-after", type=int)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--current-cards", action="store_true")
    parser.add_argument("--diagnostic-envelope", action="store_true")
    parser.add_argument("--research-store", type=Path)
    parser.add_argument("--as-of")
    parser.add_argument("--history-context")
    parser.add_argument("--minute-store", type=Path)
    args = parser.parse_args()
    emit_stage("import", "done", elapsed_ms=(perf_counter() - _import_started) * 1000)
    started = monotonic()
    try:
        result = _phase("query", lambda: query_opening_trend(args.db_path, projection_after=args.projection_after, compact=args.compact,
                                    research_strategy=args.strategy, current_cards=args.current_cards,
                                    trend_path=args.research_store, now=args.as_of) if args.strategy != "one_minute" else query(
                                        args.db_path, history_context=json.loads(args.history_context) if args.history_context else None,
                                        minute_path=args.minute_store))
        if args.strategy != "one_minute":
            from kquant.options_host_clock import read_status
            result["external_clock"] = _phase("clock", read_status)
        encoding_at = perf_counter()
        encoded = _phase("encode", lambda: json.dumps(result, ensure_ascii=True).encode("utf-8"))
        if args.diagnostic_envelope:
            result["worker_serialization_ms"] = round((perf_counter() - encoding_at) * 1000, 3)
            encoded = _phase("encode", lambda: json.dumps(result, ensure_ascii=True).encode("utf-8"))
        _phase("ipc", lambda: _write_encoded(encoded))
    except Exception as exc:
        if not args.diagnostic_envelope:
            raise
        packet = {"_status_error": safe_failure(exc, phase=getattr(exc, "status_query_phase", "worker"),
                                               elapsed_ms=round((monotonic() - started) * 1000, 3))}
        encoded = _phase("encode", lambda: json.dumps(packet, ensure_ascii=True).encode("utf-8"))
        _phase("ipc", lambda: _write_encoded(encoded))
        sys.exit(1)
