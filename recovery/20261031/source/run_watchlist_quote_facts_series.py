"""Serial, resumable quote facts for the exact retained 100 mapped identities.

Default is offline dry-plan. --run alone opts into the existing private loader
and the unmodified bounded quote-facts CLI. No orders, history requests, account
queries, OWNER acceptance, or production publication are available here.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import ctypes
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
SERIES_ROOT = ROOT / "evidence/watchlist-quote-series"
MARKET_OUT = ROOT / "evidence/market-readiness"
MANIFEST = ROOT / "evidence/retained-watchlist.json"
TIMESTAMP = ROOT / "evidence/sdk-timestamp-contract-20261007T071652086437Z.json"
MANIFEST_BYTES_SHA = "d1ad77aa7591ee226490b5b2a229b7e33045c0c175e571d5026f5e6bf4ffbc9c"
MANIFEST_CANONICAL_SHA = "ac88a0dd0b47f822c4ca9b63f526f1565158c37dc6e03ce600c13b5b07795860"
TIMESTAMP_SHA = "0c685b673bca36f30b0fb9e6d807a1ba64c374239c7c85fe5a82561f60c3e8a6"
REQUESTS_PER_ASSET = 11
CHILD_TIMEOUT = 65
WORK_SECONDS = 48
GLOBAL_ERRORS = {"AUTHENTICATION", "TOKEN_EXPIRED", "INVALID_SIGNATURE", "INVALID_APP_KEY", "IP_NOT_ALLOWED"}
ERROR_CATEGORIES = GLOBAL_ERRORS | {"ACCESS_DENIED", "NO_QUOTE_ACCESS", "NO_QUOTES", "UNSUPPORTED",
    "INVALID_REQUEST", "SERVER_ERROR", "RATE_LIMIT", "HISTORY_MONTHLY_SYMBOL_QUOTA", "TIMEOUT", "CONNECTION", "UNCLASSIFIED"}
REPORT_STATUSES = {"FACTS_CAPTURED", "FACTS_CAPTURED_WITH_PROVIDER_ERRORS", "REQUEST_BUDGET_REACHED",
    "RUN_TIME_BUDGET_REACHED", "PROBE_WORKER_FAILED", "QUOTE_PROBE_TIMED_OUT", "BLOCKED_INHERITED_CREDENTIALS_MISSING"} | {
        "BLOCKED_" + name for name in GLOBAL_ERRORS}
INTERFACES = {"QuoteContext." + name for name in (
    "trading_session", "trading_days", "static_info", "quote", "option_chain_expiry_date_list",
    "option_chain_info_by_date", "calc_indexes", "option_quote", "depth")}
FALSE_FLAGS = ("trade_context_created", "orders_enabled", "system_clock_modified", "owner_acceptance_created",
               "production_admission_verified")
REMAINING_GATES = ["ABSOLUTE_CLOCK_NOT_ACCEPTED", "LIVE_CLOSED_MINUTE_INPUT_NOT_PROBED",
    "PRIOR_CLOSE_SCALE_NOT_BOUND", "RAW_VOLUME_AND_TURNOVER_UNITS_NOT_ACCEPTED",
    "CONTRACT_DELIVERABLE_NOT_ACCEPTED", "LIVE_BBO_EVENT_TIME_AND_FRESHNESS_NOT_PROVEN",
    "SOURCE_METHOD_OWNER_ACCEPTANCE_NOT_CREATED"]


class IntegrityError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def wall():
    return datetime.now(timezone.utc).isoformat()


def safe_status(value, allowed, fallback="UNCLASSIFIED"):
    return value if isinstance(value, str) and value in allowed else fallback


def safe_error(value):
    value = value if isinstance(value, dict) else {}
    code = value.get("provider_error_code")
    return {"error_category": safe_status(value.get("error_category"), ERROR_CATEGORIES),
            "provider_error_code": code if isinstance(code, int) and not isinstance(code, bool) else None,
            "provider_error_kind": safe_status(value.get("provider_error_kind"), {"Http", "OpenApi", "Other", "UNKNOWN"}, "UNKNOWN")}


def retained_scope(manifest):
    items = manifest.get("items", [])
    if len(items) != 111 or len({item.get("symbol") for item in items}) != 111:
        raise IntegrityError("RETAINED_111_SCOPE_NOT_UNIQUE")
    verified, skipped = [], []
    providers = set()
    for item in items:
        symbol, provider = item.get("symbol"), item.get("provider_symbol")
        if not isinstance(symbol, str) or len(symbol) > 32:
            raise IntegrityError("RETAINED_SYMBOL_INVALID")
        if item.get("identity_status") == "verified":
            if not re.fullmatch(r"[A-Z0-9.-]+", symbol) or not isinstance(provider, str) or not re.fullmatch(r"[A-Z0-9.-]+\.US", provider):
                raise IntegrityError("VERIFIED_PROVIDER_IDENTITY_INVALID")
            if provider in providers:
                raise IntegrityError("VERIFIED_PROVIDER_IDENTITY_DUPLICATED")
            providers.add(provider)
            verified.append({"symbol": symbol, "provider_symbol": provider})
        else:
            skipped.append({"symbol": symbol, "identity_status": "IDENTITY_UNCONFIRMED",
                            "state": "SKIPPED_NO_QUERY", "provider_symbol": None})
    if len(verified) != 100 or len(skipped) != 11:
        raise IntegrityError("RETAINED_IDENTITY_COUNTS_CHANGED")
    return verified, skipped


def bindings():
    manifest_bytes = MANIFEST.read_bytes()
    manifest = json.loads(manifest_bytes)
    if sha(manifest_bytes) != MANIFEST_BYTES_SHA or sha(canonical(manifest)) != MANIFEST_CANONICAL_SHA:
        raise IntegrityError("RETAINED_MANIFEST_HASH_CHANGED")
    verified, skipped = retained_scope(manifest)
    timestamp_bytes = TIMESTAMP.read_bytes()
    evidence = json.loads(timestamp_bytes)
    if sha(timestamp_bytes) != TIMESTAMP_SHA or evidence.get("status") != "VERIFIED" or evidence.get("sdk_version") != "4.4.1":
        raise IntegrityError("TIMESTAMP_CONTRACT_CHANGED")
    wheel = ROOT / "environment/wheels/longbridge-4.4.1-cp312-cp312-win_amd64.whl"
    if sha(wheel.read_bytes()) != evidence.get("sdk_wheel_sha256"):
        raise IntegrityError("TIMESTAMP_WHEEL_BINDING_CHANGED")
    source_paths = ["probe_market_readiness.py", "probe_minute_history.py", "minute_rebuild.py",
                    "run_quote_facts.py", "development/workspace/kquant/local_env.py",
                    "run_watchlist_quote_facts_series.py"]
    bound = {"manifest_bytes_sha256": MANIFEST_BYTES_SHA, "manifest_canonical_sha256": MANIFEST_CANONICAL_SHA,
             "timestamp_evidence_sha256": TIMESTAMP_SHA, "sdk_wheel_sha256": evidence["sdk_wheel_sha256"],
             "original_source_sha256": {name: sha((ROOT / name).read_bytes()) for name in source_paths},
             "request_limit_per_asset": REQUESTS_PER_ASSET, "child_timeout_seconds": CHILD_TIMEOUT,
             "work_seconds": WORK_SECONDS, "total_request_reservation_limit": 1100}
    return bound, verified, skipped


def decimal(raw):
    try:
        value = Decimal(str(raw)) if raw is not None and not isinstance(raw, bool) else None
        return value if value is not None and value.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def field(row, name):
    value = row.get(name, {}) if isinstance(row, dict) else {}
    return value.get("raw") if isinstance(value, dict) else None


def pick_native(row, names):
    # The immutable probe already whitelists native values. Return only these
    # explicit fields, never an arbitrary error repr or unrelated object.
    return {name: row[name] for name in names if name in row}


def summarize_report(report, asset, binding):
    if report.get("mode") != "quote-facts" or any(report.get(name) is not False for name in FALSE_FLAGS):
        raise IntegrityError("RECEIPT_NOT_READ_ONLY_QUOTE_FACTS")
    if any(report.get(name) not in (False, None) for name in ("production_started", "qualified_publication_enabled")):
        raise IntegrityError("RECEIPT_PRODUCTION_GATE_INVALID")
    status = safe_status(report.get("status"), REPORT_STATUSES, "UNKNOWN_PROBE_STATUS")
    requests = report.get("requests")
    if requests is not None and (not isinstance(requests, int) or isinstance(requests, bool) or not 0 <= requests <= 11):
        raise IntegrityError("PROBE_REQUEST_BOUND_INVALID")
    scope = report.get("scope", {})
    scope_bound = scope == {**asset, "manifest_sha256": binding["manifest_canonical_sha256"]}
    if scope and not scope_bound:
        raise IntegrityError("RECEIPT_ASSET_SCOPE_MISMATCH")
    profile = report.get("timestamp_profile", {})
    if profile and profile.get("evidence_sha256") != binding["timestamp_evidence_sha256"]:
        raise IntegrityError("RECEIPT_TIMESTAMP_SCOPE_MISMATCH")
    observations = report.get("observations", [])
    if not isinstance(observations, list) or len(observations) > 11:
        raise IntegrityError("OBSERVATION_BOUND_INVALID")
    if observations and (requests != len(observations) or not scope_bound or not profile):
        raise IntegrityError("OBSERVATION_COUNT_OR_SOURCE_BINDING_INVALID")
    coverage, errors, static, quotes, option_rows, calc_rows, depths = [], [], [], [], [], [], []
    quote_scope_checks, asset_request_attempts = [], 0
    for ordinal, observation in enumerate(observations):
        interface = observation.get("interface")
        if interface not in INTERFACES:
            raise IntegrityError("NON_QUOTE_INTERFACE_RECEIPT")
        error = safe_error(observation["error"]) if observation.get("error") else None
        if error:
            errors.append({"interface": interface, **error})
        rows = observation.get("rows", [])
        if asset["provider_symbol"] in observation.get("request_symbols", []):
            asset_request_attempts += 1
        coverage.append({"ordinal": ordinal, "interface": interface,
                         "state": safe_status(observation.get("state"), {"RETURNED", "PROVIDER_ERROR"}),
                         "native_rows_captured": len(rows) if isinstance(rows, list) else 0,
                         "error": error})
        if interface.endswith(".static_info"):
            static += [row for row in rows if field(row, "symbol") == asset["provider_symbol"]]
        elif interface.endswith(".quote"):
            matching = [row for row in rows if field(row, "symbol") == asset["provider_symbol"]]
            quotes += matching
            if observation.get("state") == "RETURNED":
                quote_scope_checks.append(len(matching) == 1)
        elif interface.endswith(".option_quote"):
            option_rows += rows
        elif interface.endswith(".calc_indexes"):
            calc_rows += rows
        elif interface.endswith(".depth"):
            depths.append(observation)
    if report.get("error_category"):
        errors.append({"interface": "WORKER_BOUNDARY", **safe_error(report)})
    discovery = report.get("contract_discovery", {})
    selected = discovery.get("selected_contracts", [])
    if not isinstance(selected, list) or len(selected) > 2:
        raise IntegrityError("SELECTED_CONTRACT_BOUND_INVALID")
    selected_codes = set()
    contracts = []
    expiry = discovery.get("expiry_date")
    try:
        calendar_dte = (date.fromisoformat(expiry) - date.fromisoformat(report["market_date"])).days if expiry else None
    except (KeyError, TypeError, ValueError):
        calendar_dte = None
    if selected and (calendar_dte is None or not 3 <= calendar_dte <= 7):
        raise IntegrityError("CONTRACT_OUTSIDE_3_TO_7_CALENDAR_DAYS")
    for item in selected:
        code = item.get("symbol")
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9.-]+\.US", code):
            raise IntegrityError("SELECTED_NATIVE_CODE_INVALID")
        if code in selected_codes:
            raise IntegrityError("SELECTED_NATIVE_CODE_DUPLICATED")
        selected_codes.add(code)
        matches = [row for row in option_rows if field(row, "symbol") == code]
        calc = [row for row in calc_rows if field(row, "symbol") == code]
        depth = [row for row in depths if row.get("contract_symbol") == code]
        native = matches[0] if len(matches) == 1 else {}
        strike_match = decimal(field(native, "strike_price")) == decimal(item.get("strike")) if native else False
        right = item.get("right")
        identity = bool(native and field(native, "underlying_symbol") == asset["provider_symbol"]
                        and field(native, "expiry_date") == expiry and strike_match
                        and field(native, "direction") == "OptionDirection." + {"CALL": "Call", "PUT": "Put"}.get(right, "INVALID"))
        contracts.append({"symbol": code, "right": right if right in {"CALL", "PUT"} else "UNVERIFIED",
                          "strike": item.get("strike"), "calendar_dte": calendar_dte,
                          "native_basic_identity_matches": identity,
                          "native_quote": pick_native(native, ("symbol", "underlying_symbol", "expiry_date", "strike_price",
                            "direction", "trade_status", "contract_type", "contract_size", "contract_multiplier",
                            "timestamp", "last_done", "implied_volatility", "volume", "turnover")),
                          "native_calc": pick_native(calc[0], ("symbol", "delta", "gamma", "theta", "vega", "implied_volatility")) if len(calc) == 1 else {},
                          "native_depth": [{"bids": row.get("bids", []), "asks": row.get("asks", []),
                                            "event_timestamp_available": False} for row in depth],
                          "standard_deliverable_qualified": False, "bbo_freshness_proven": False})
    blockers = list(REMAINING_GATES)
    categories = {error["error_category"] for error in errors}
    if categories:
        blockers += ["PROVIDER_" + category for category in sorted(categories)]
    if not scope_bound:
        blockers.append("NATIVE_SCOPE_NOT_CAPTURED")
    if not static:
        blockers.append("STATIC_REFERENCE_NOT_CAPTURED")
    if not quotes:
        blockers.append("UNDERLYING_NATIVE_QUOTE_NOT_CAPTURED")
    native_trade_status = field(quotes[-1], "trade_status") if quotes else None
    if native_trade_status != "TradeStatus.Normal":
        blockers.append("UNDERLYING_TRADE_STATUS_NOT_NORMAL_OR_MISSING")
    if not selected:
        blockers.append("NO_MATCHING_NATIVE_3_TO_7_DAY_CONTRACT")
    if any(not item["native_basic_identity_matches"] for item in contracts):
        blockers.append("NATIVE_OPTION_IDENTITY_NOT_CONFIRMED")
    if not contracts or any(not item["native_depth"] for item in contracts):
        blockers.append("NATIVE_OPTION_DEPTH_NOT_CAPTURED")
    global_stop = sorted(categories & GLOBAL_ERRORS)
    if status == "BLOCKED_INHERITED_CREDENTIALS_MISSING":
        global_stop.append("CREDENTIALS_MISSING")
    if status.startswith("BLOCKED_") and status[8:] in GLOBAL_ERRORS:
        global_stop.append(status[8:])
    app_scope = report.get("provider_scope_sha256")
    if app_scope is not None and (report.get("provider_scope_kind") != "APP_KEY_SHA256" or not re.fullmatch(r"[a-f0-9]{64}", app_scope)):
        raise IntegrityError("PROVIDER_SCOPE_PROOF_INVALID")
    return {**asset, "probe_status": status, "known_requests": requests, "scope_binding_verified": scope_bound,
            "asset_specific_request_attempts": asset_request_attempts,
            "has_provider_request_evidence": bool(asset_request_attempts),
            "native_underlying_response_scope_verified": bool(quote_scope_checks and all(quote_scope_checks)),
            "source_coverage": coverage, "provider_errors": errors,
            "native_static": [pick_native(row, ("symbol", "exchange", "currency", "lot_size", "stock_derivatives")) for row in static],
            "native_underlying_quotes": [pick_native(row, ("symbol", "trade_status", "timestamp", "last_done", "prev_close", "volume", "turnover")) for row in quotes],
            "discovery_state": safe_status(discovery.get("state"), {"NO_MATCHING_RETURNED_CALENDAR_DTE", "NATIVE_STANDARD_CHAIN_CANDIDATES", "NO_BOUND_CHAIN_CANDIDATE"}, "NOT_CAPTURED"),
            "expiry_date": expiry, "calendar_dte": calendar_dte, "market_date": report.get("market_date"),
            "native_contracts": contracts, "global_stop_reasons": sorted(set(global_stop)),
            "provider_scope_sha256": app_scope, "production_admission_verified": False,
            "eligible": False, "eligibility_state": "NOT_PROVEN_BY_FACT_CAPTURE", "blocking_gates": blockers,
            "clock_precision_verified": False, "owner_acceptance_created": False}


def checked_receipt(summary, asset, binding, *, market_out=MARKET_OUT):
    path = Path(summary.get("receipt_path", "")).resolve()
    if path.parent != market_out.resolve() or not re.fullmatch(r"\d{8}T\d{12}Z-[a-f0-9]{64}\.json", path.name):
        raise IntegrityError("RECEIPT_PATH_OUTSIDE_IMMUTABLE_PROBE_OUTPUT")
    raw = path.read_bytes()
    digest = sha(raw)
    if digest != summary.get("receipt_sha256") or not path.stem.endswith(digest):
        raise IntegrityError("RECEIPT_HASH_MISMATCH")
    report = json.loads(raw)
    facts = summarize_report(report, asset, binding)
    if summary.get("requests") != report.get("requests"):
        raise IntegrityError("SUMMARY_REQUEST_COUNT_MISMATCH")
    return facts, {"path": str(path), "sha256": digest}


def atomic_json(path, value):
    temp = path.with_name(path.name + f".tmp-{os.getpid()}")
    with temp.open("wb") as handle:
        handle.write(canonical(value)); handle.flush(); os.fsync(handle.fileno())
    os.replace(temp, path)


def immutable_json(directory, stem, value):
    raw = canonical(value); digest = sha(raw)
    path = directory / f"{stem}-{digest}.json"
    if path.exists():
        if path.read_bytes() != raw:
            raise IntegrityError("IMMUTABLE_CONTROLLER_RECEIPT_COLLISION")
    else:
        with path.open("xb") as handle:
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
    return {"path": str(path), "sha256": digest}


@contextmanager
def series_lock(directory):
    path = directory / "controller.lock"
    handle = path.open("a+b")
    if path.stat().st_size == 0:
        handle.write(b"0"); handle.flush()
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close(); raise IntegrityError("SERIES_ALREADY_RUNNING")
    try:
        yield
    finally:
        handle.seek(0)
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


class OwnedJob:
    """Windows owned process tree dies when controller/job handle closes."""
    def __init__(self):
        self.handle = None
        if os.name != "nt":
            return
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [("user", ctypes.c_int64), ("kernel", ctypes.c_int64), ("flags", w.DWORD),
                        ("min_work", ctypes.c_size_t), ("max_work", ctypes.c_size_t), ("active", w.DWORD),
                        ("affinity", ctypes.c_size_t), ("priority", w.DWORD), ("schedule", w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]
        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_mem", ctypes.c_size_t), ("job_mem", ctypes.c_size_t),
                        ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]
        class Accounting(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int64) for name in ("total_user", "total_kernel", "period_user", "period_kernel")] + [
                (name, w.DWORD) for name in ("faults", "total", "active", "terminated")]
        self.accounting = Accounting
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]; self.kernel.CreateJobObjectW.restype = w.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.kernel.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        self.kernel.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p]
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        info = Extended(); info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.handle or not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            self.close(); raise OSError("OWNED_JOB_SETUP_FAILED")

    def assign(self, process):
        if self.handle and not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise OSError("OWNED_JOB_ASSIGN_FAILED")

    def stop_tree(self, process):
        if self.handle:
            if not self.kernel.TerminateJobObject(self.handle, 1):
                raise OSError("OWNED_JOB_TERMINATION_FAILED")
            deadline = time.monotonic() + 5
            while True:
                active = self.accounting()
                if not self.kernel.QueryInformationJobObject(self.handle, 1, ctypes.byref(active), ctypes.sizeof(active), None):
                    raise OSError("OWNED_JOB_QUERY_FAILED")
                if active.active == 0:
                    break
                if time.monotonic() >= deadline:
                    raise OSError("OWNED_JOB_TREE_NOT_TERMINATED")
                time.sleep(0.05)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=5)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle); self.handle = None


def command_for(asset):
    return [sys.executable, str(ROOT / "probe_market_readiness.py"), "quote-facts", "--symbol", asset["symbol"],
            "--manifest", str(MANIFEST), "--timestamp-contract", "verified-naive-asia-shanghai",
            "--timestamp-evidence", str(TIMESTAMP), "--max-requests", "11", "--run-seconds", "48"]


def invoke_probe(asset, on_guarded, heartbeat):
    # Only structured CLI output is parsed; stdout/stderr never reach disk/logs.
    job, process, assigned, gate_released = None, None, False, False
    result = {"transport_status": "CHILD_FAILED", "child_tree_termination_verified": False}
    try:
        job = OwnedJob()
        deadline = time.monotonic() + CHILD_TIMEOUT
        # Before assignment the only executable code reads one public byte.
        # Controller death closes stdin: no SDK import or descendant can start.
        bootstrap = ("import sys\n"
                     "if sys.stdin.buffer.read(1) != b'1': raise SystemExit(2)\n"
                     "import runpy\n"
                     "sys.argv = sys.argv[1:]\n"
                     "runpy.run_path(sys.argv[0], run_name='__main__')\n")
        command = command_for(asset)
        process = subprocess.Popen([command[0], "-c", bootstrap, *command[1:]],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace", start_new_session=os.name != "nt")
        job.assign(process)
        assigned = True
        on_guarded(process.pid)
        process.stdin.write("1"); process.stdin.flush()
        gate_released = True
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result["transport_status"] = "CHILD_TIMED_OUT"
                break
            try:
                stdout, _discarded_stderr = process.communicate(timeout=min(20, remaining))
                try:
                    summary = json.loads(stdout)
                    result = {"transport_status": "CHILD_RETURNED", "summary": summary,
                              "returncode": process.returncode, "child_tree_termination_verified": False}
                except (json.JSONDecodeError, TypeError):
                    result["transport_status"] = "CHILD_OUTPUT_NOT_STRUCTURED"
                break
            except subprocess.TimeoutExpired:
                heartbeat()
        job.stop_tree(process)
        result["child_tree_termination_verified"] = True
    except (OSError, subprocess.TimeoutExpired):
        result["transport_status"] = "CHILD_GUARD_OR_TRANSPORT_FAILED"
        if process is None:
            result["child_tree_termination_verified"] = True
        else:
            try:
                if assigned:
                    job.stop_tree(process)
                else:
                    process.kill(); process.wait(timeout=5)
                result["child_tree_termination_verified"] = assigned
                result["unassigned_bootstrap_terminated"] = not assigned
            except (OSError, subprocess.TimeoutExpired):
                pass
    finally:
        if job is not None:
            job.close()
        if process is not None:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
    result["sdk_start_gate_released"] = gate_released
    return result


def validate_state(state, binding, assets, directory, *, market_out=MARKET_OUT):
    if state.get("binding") != binding or state.get("assets") != assets or state.get("schema") != "KQUANT_WATCHLIST_QUOTES_V1":
        raise IntegrityError("RESUME_BINDING_CHANGED")
    names = {asset["symbol"] for asset in assets}
    results = {}
    for symbol, ref in state.get("results", {}).items():
        path = Path(ref["path"]).resolve()
        if symbol not in names or path.parent != (directory / "attempts").resolve():
            raise IntegrityError("RESULT_SCOPE_OR_PATH_INVALID")
        raw = path.read_bytes()
        if sha(raw) != ref["sha256"] or not path.stem.endswith(ref["sha256"]):
            raise IntegrityError("CONTROLLER_RESULT_HASH_MISMATCH")
        result = json.loads(raw)
        if result["asset"]["symbol"] != symbol or result.get("production_admission_verified") is not False:
            raise IntegrityError("RESULT_IDENTITY_OR_GATE_INVALID")
        if result.get("probe_receipt"):
            facts, _ = checked_receipt({"receipt_path": result["probe_receipt"]["path"],
                "receipt_sha256": result["probe_receipt"]["sha256"], "requests": result["facts"]["known_requests"]}, result["asset"], binding,
                market_out=market_out)
            if facts != result["facts"]:
                raise IntegrityError("RESULT_PROJECTION_CHANGED")
        results[symbol] = result
    inflight = state.get("in_flight")
    reservations = len(results) + (1 if inflight else 0)
    if state.get("request_reservations") != reservations * 11 or reservations > 100:
        raise IntegrityError("REQUEST_RESERVATION_LEDGER_INVALID")
    if inflight and (inflight.get("asset") not in assets or inflight["asset"]["symbol"] in results):
        raise IntegrityError("INFLIGHT_SCOPE_INVALID")
    return results


def series_totals(state, results, skipped, status):
    facts = [result.get("facts") or {} for result in results.values()]
    counts = Counter(row.get("probe_status", result.get("transport_status", "UNCONFIRMED"))
                     for result, row in zip(results.values(), facts))
    known = sum(row.get("known_requests") or 0 for row in facts)
    return {"record_kind": "EXACT_RETAINED_WATCHLIST_QUOTE_FACTS_SERIES", "status": status,
            "binding": state["binding"], "manifest_total_identities": 111, "verified_mapped_identities": 100,
            "identity_unconfirmed_no_query": skipped, "asset_attempts_terminal": len(results),
            "assets_with_manifest_bound_receipt_scope": sum(bool(row.get("scope_binding_verified")) for row in facts),
            "assets_with_verified_native_underlying_quote_scope": sum(bool(row.get("native_underlying_response_scope_verified")) for row in facts),
            "assets_with_provider_request_evidence": sum(bool(row.get("has_provider_request_evidence")) for row in facts),
            "assets_with_native_contract_candidates": sum(bool(row.get("native_contracts")) for row in facts),
            "all_100_assets_attempted": len(results) == 100,
            "all_100_provider_requests_observed": len(results) == 100 and all(row.get("has_provider_request_evidence") for row in facts),
            "known_requests": known, "maximum_possible_requests_reserved": state["request_reservations"],
            "unknown_outcome_asset_count": sum(not result.get("probe_receipt") or row.get("known_requests") is None
                                               for result, row in zip(results.values(), facts)),
            "probe_status_counts": dict(counts), "asset_result_refs": state["results"],
            "receipt_market_date_counts": dict(Counter(row.get("market_date", "NOT_CAPTURED") for row in facts)),
            "single_trusted_current_market_snapshot_proven": False,
            "global_stop": state.get("global_stop"), "eligible_assets_proven": 0,
            "eligibility_state": "NOT_PROVEN_BY_FACT_CAPTURE", "clock_precision_verified": False,
            "owner_acceptance_created": False, "production_admission_verified": False,
            "production_started": False, "qualified_publication_enabled": False,
            "token_values_or_hashes_saved": False, "original_probe_source_modified": False,
            "frozen_workspace_modified": False, "system_settings_modified": False,
            "old_business_continuity": "UNKNOWN", "created_at_untrusted_local_wall": wall()}


def recovered_inflight(state, binding, *, market_out=MARKET_OUT):
    inflight = state["in_flight"]
    if inflight.get("guard_state") != "OWNED_CHILD_TREE_GUARDED":
        raise IntegrityError("INTERRUPTED_CHILD_GUARD_NOT_PROVEN")
    before = set(inflight.get("receipt_files_before", []))
    candidates = []
    for path in market_out.glob("*.json"):
        if path.name in before:
            continue
        try:
            report = json.loads(path.read_bytes())
            if report.get("scope", {}).get("symbol") != inflight["asset"]["symbol"]:
                continue
            facts, ref = checked_receipt({"receipt_path": str(path), "receipt_sha256": sha(path.read_bytes()),
                                         "requests": report.get("requests")}, inflight["asset"], binding, market_out=market_out)
            candidates.append((facts, ref))
        except (OSError, ValueError, TypeError):
            continue
    if len(candidates) > 1:
        raise IntegrityError("INTERRUPTED_RECEIPT_AMBIGUOUS")
    return candidates[0] if candidates else (None, None)


def execute_series(directory, binding, assets, skipped, *, max_symbols, max_seconds, resume_global=False,
                   invoke=invoke_probe, env_loader=None, emit=lambda value: print(json.dumps(value), flush=True),
                   market_out=MARKET_OUT, binding_verifier=None):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "attempts").mkdir(exist_ok=True)
    checkpoint = directory / "checkpoint.json"
    started = time.monotonic()
    with series_lock(directory):
        state = json.loads(checkpoint.read_bytes()) if checkpoint.exists() else {
            "schema": "KQUANT_WATCHLIST_QUOTES_V1", "binding": binding, "assets": assets,
            "results": {}, "in_flight": None, "request_reservations": 0, "global_stop": None,
            "provider_scope_sha256": None}
        results = validate_state(state, binding, assets, directory, market_out=market_out)

        def commit(asset, transport, facts=None, receipt=None):
            nonlocal state
            result = {"asset": asset, "transport_status": transport, "facts": facts,
                      "probe_receipt": receipt, "request_reservation": 11,
                      "source_coverage_available": facts is not None,
                      "blocking_gates": facts["blocking_gates"] if facts else ["PROBE_OUTCOME_UNKNOWN_NO_SOURCE_PROOF", *REMAINING_GATES],
                      "eligible": False,
                      "production_admission_verified": False, "created_at_untrusted_local_wall": wall()}
            state["results"][asset["symbol"]] = immutable_json(directory / "attempts", "asset-" + asset["symbol"], result)
            results[asset["symbol"]] = result
            state["in_flight"] = None
            if facts and facts["provider_scope_sha256"]:
                if state["provider_scope_sha256"] and state["provider_scope_sha256"] != facts["provider_scope_sha256"]:
                    state["global_stop"] = ["PROVIDER_IDENTITY_CHANGED"]
                else:
                    state["provider_scope_sha256"] = facts["provider_scope_sha256"]
            if facts and facts["global_stop_reasons"]:
                state["global_stop"] = facts["global_stop_reasons"]
            atomic_json(checkpoint, state)

        if state["in_flight"]:
            asset = state["in_flight"]["asset"]
            try:
                facts, ref = recovered_inflight(state, binding, market_out=market_out)
            except IntegrityError:
                state["global_stop"] = ["INTERRUPTED_CHILD_OR_RECEIPT_UNVERIFIED"]
                atomic_json(checkpoint, state)
                facts, ref = None, None
            if not state["global_stop"]:
                commit(asset, "RECOVERED_IMMUTABLE_RECEIPT" if ref else "INTERRUPTED_OUTCOME_UNKNOWN_NO_REQUERY", facts, ref)
        if state["global_stop"] and resume_global:
            # A fresh source identity is never allowed to reuse this series.
            if set(state["global_stop"]) <= (GLOBAL_ERRORS | {"CREDENTIALS_MISSING"}):
                state["global_stop"] = None
                atomic_json(checkpoint, state)
        status = "ALL_100_ASSET_ATTEMPTS_RECORDED" if len(results) == 100 else "SEGMENT_LIMIT_REACHED"
        if state["global_stop"]:
            status = "SERIES_STOPPED_GLOBAL_BLOCKER"
        elif len(results) < 100:
            loaded = env_loader() if env_loader else {"longbridge_credentials_configured": False}
            if not loaded.get("longbridge_credentials_configured"):
                state["global_stop"] = ["CREDENTIALS_MISSING"]
                atomic_json(checkpoint, state); status = "SERIES_STOPPED_GLOBAL_BLOCKER"
            else:
                count = 0
                for asset in assets:
                    if asset["symbol"] in results:
                        continue
                    if count >= max_symbols or time.monotonic() - started + CHILD_TIMEOUT > max_seconds:
                        break
                    if binding_verifier is not None and binding_verifier() != binding:
                        state["global_stop"] = ["BOUND_SOURCE_CHANGED_DURING_SEGMENT"]
                        atomic_json(checkpoint, state); status = "SERIES_STOPPED_GLOBAL_BLOCKER"; break
                    state["in_flight"] = {"asset": asset, "guard_state": "RESERVED_BEFORE_CHILD_START",
                        "reserved_at_untrusted_local_wall": wall(),
                        "receipt_files_before": sorted(path.name for path in market_out.glob("*.json"))}
                    state["request_reservations"] += 11
                    atomic_json(checkpoint, state)

                    def guarded(pid):
                        state["in_flight"].update(guard_state="OWNED_CHILD_TREE_GUARDED", pid=pid)
                        atomic_json(checkpoint, state)

                    emit({"status": "ASSET_STARTING", "symbol": asset["symbol"], "completed": len(results),
                          "maximum_possible_requests_reserved": state["request_reservations"]})
                    transport = invoke(asset, guarded, lambda: emit({"status": "ASSET_RUNNING", "symbol": asset["symbol"],
                                                                   "completed": len(results)}))
                    if not transport.get("child_tree_termination_verified"):
                        state["global_stop"] = ["OWNED_CHILD_TREE_TERMINATION_UNVERIFIED"]
                        atomic_json(checkpoint, state); status = "SERIES_STOPPED_GLOBAL_BLOCKER"; break
                    facts, ref = None, None
                    transport_state = safe_status(transport.get("transport_status"), {
                        "CHILD_RETURNED", "CHILD_TIMED_OUT", "CHILD_OUTPUT_NOT_STRUCTURED",
                        "CHILD_GUARD_OR_TRANSPORT_FAILED", "CHILD_FAILED"}, "CHILD_FAILED")
                    if transport_state == "CHILD_GUARD_OR_TRANSPORT_FAILED":
                        state["global_stop"] = ["OWNED_CHILD_GUARD_OR_TRANSPORT_FAILURE"]
                    if transport_state == "CHILD_RETURNED":
                        try:
                            facts, ref = checked_receipt(transport.get("summary", {}), asset, binding, market_out=market_out)
                            if Path(ref["path"]).name in state["in_flight"]["receipt_files_before"]:
                                raise IntegrityError("OLD_QUOTE_RECEIPT_REUSED_AS_FRESH_ATTEMPT")
                        except (IntegrityError, OSError, ValueError, TypeError):
                            facts, ref = None, None
                            state["global_stop"] = ["CHILD_RECEIPT_INTEGRITY_UNVERIFIED"]
                    commit(asset, transport_state, facts, ref)
                    count += 1
                    emit({"status": "ASSET_RECORDED", "symbol": asset["symbol"], "completed": len(results),
                          "probe_status": facts["probe_status"] if facts else transport_state,
                          "known_requests": facts["known_requests"] if facts else None,
                          "eligible": False})
                    if state["global_stop"]:
                        status = "SERIES_STOPPED_GLOBAL_BLOCKER"; break
                    if len(results) == 100:
                        status = "ALL_100_ASSET_ATTEMPTS_RECORDED"
        totals = series_totals(state, results, skipped, status)
        ref = immutable_json(directory, datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-segment", totals)
        emit({"status": status, "receipt_path": ref["path"], "receipt_sha256": ref["sha256"],
              "asset_attempts_terminal": len(results), "known_requests": totals["known_requests"],
              "maximum_possible_requests_reserved": state["request_reservations"],
              "all_100_provider_requests_observed": totals["all_100_provider_requests_observed"],
              "eligible_assets_proven": 0, "production_admission_verified": False})
        return totals


def load_private_env():
    # Reuse the existing explicitly invoked loader. Importing its wrapper does
    # not execute the guarded __main__ block. No config value is returned here.
    from run_quote_facts import load_market_data_env
    loaded = load_market_data_env(path=ROOT / ".env")
    return {"longbridge_credentials_configured": bool(loaded.get("longbridge_credentials_configured"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run", action="store_true", help="Explicitly load local credentials and run quote-only children")
    mode.add_argument("--dry-plan", action="store_true", help="Validate retained scope and bindings offline; this is the default")
    parser.add_argument("--series-id", default="watchlist-quote-20261007-v1")
    parser.add_argument("--max-symbols", type=int, default=100, help="Maximum new identity attempts this segment; no automatic per-asset retries")
    parser.add_argument("--max-seconds", type=float, default=1200, help="Monotonic segment bound; reserve65sec before each child")
    parser.add_argument("--resume-after-global-fix", action="store_true", help="Reopen only an authentication/credentials stop after external correction")
    args = parser.parse_args()
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", args.series_id)
            or args.series_id.upper() in {"CON", "PRN", "AUX", "NUL"}):
        parser.error("Invalid isolated series name")
    if not 1 <= args.max_symbols <= 100 or not math.isfinite(args.max_seconds) or not 65 <= args.max_seconds <= 1200:
        parser.error("Permit1..100 identities and65..1200monotonic seconds per segment")
    try:
        binding, assets, skipped = bindings()
        directory = SERIES_ROOT / args.series_id
        if not args.run:
            print(json.dumps({"status": "OFFLINE_DRY_PLAN", "binding": binding, "assets_to_probe": assets,
                "identity_unconfirmed_no_query": skipped, "max_symbols_this_segment": args.max_symbols,
                "segment_seconds": args.max_seconds, "requests": 0, "env_file_read": False,
                "sdk_imported": False, "eligible_assets_proven": 0, "production_admission_verified": False}, indent=2))
            return 0
        totals = execute_series(directory, binding, assets, skipped, max_symbols=args.max_symbols,
                       max_seconds=args.max_seconds, resume_global=args.resume_after_global_fix, env_loader=load_private_env,
                       binding_verifier=lambda: bindings()[0])
        return 2 if totals["global_stop"] else 0
    except (IntegrityError, OSError, ValueError, TypeError):
        # Deliberately discard arbitrary exception strings and private child output.
        print(json.dumps({"status": "SERIES_FAILED_SAFE_BOUNDARY", "production_admission_verified": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
