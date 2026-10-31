"""TEST_ONLY spawned backend/Gateway mixed exercise; never starts production.

The actual middleware, API, journal, calculation lane and compiled frontend run.
Source facts, market inputs and clock are explicitly synthetic. This does not
prove live SDK qualification, business recovery or production OWNER acceptance.
"""
import argparse
from collections import Counter
from contextlib import closing
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
from math import ceil
import multiprocessing as mp
import os
from pathlib import Path
import socket
import sqlite3
import stat
import subprocess
import sys
from threading import Event, Thread, current_thread
from time import monotonic, sleep
import traceback

import httpx

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "crypto"))
TOKEN = "TEST_ONLY_internal_transport_token"
EMAIL = "test-only@example.invalid"
PASSWORD = "TEST_ONLY_not_a_user_password"


def safe(path):
    path = Path(path).absolute()
    if path.drive.upper() == "F:":
        raise ValueError("FAULT_DRIVE_FORBIDDEN")
    if not path.drive or path.drive.startswith("\\\\"):
        raise ValueError("ISOLATION_ONLY_LOCAL_DRIVE")
    for entry in reversed([path, *path.parents]):
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("REPARSE_ISOLATION_PATH")
    return path.resolve(strict=False)


def write(path, value):
    safe(path).write_text(json.dumps(value, indent=2), encoding="utf-8")


def percentile(values):
    values = sorted(values)
    return values[max(0, ceil(.95 * len(values)) - 1)] if values else None


def install_loop_observer(loop, out, role):
    """Keep asynchronous transport errors visible without raw context/secrets."""
    path = safe(Path(out) / f"TEST_ONLY-loop-{role}-{os.getpid()}.jsonl")
    count = 0

    def handler(active_loop, context):
        nonlocal count
        count += 1
        exc = context.get('exception')
        callback = getattr(context.get('handle'), '_callback', None)
        name = getattr(callback, '__qualname__', '')
        row = {'test_only': True, 'pid': os.getpid(), 'role': role,
               'observed_at': datetime.now(UTC).isoformat(), 'monotonic': monotonic(),
               'sequence': count, 'request_id': None, 'classification': 'UNATTRIBUTED_LOOP_EXCEPTION',
               'exception_type': type(exc).__name__ if isinstance(exc, BaseException) else 'UNKNOWN',
               'exception_frames': [{'file': Path(frame.filename).name, 'line': frame.lineno,
                    'function': frame.name} for frame in traceback.extract_tb(exc.__traceback__)[-8:]]
                    if isinstance(exc, BaseException) else [],
               'winerror': getattr(exc, 'winerror', None) if isinstance(exc, OSError) else None,
               'callback': 'PROACTOR_CONNECTION_LOST' if name == '_ProactorBasePipeTransport._call_connection_lost' else 'OTHER'}
        # One small record per callback, with a durable overflow marker.
        if count <= 1001:
            if count == 1001:
                row['classification'] = 'LOOP_OBSERVATION_LIMIT_REACHED'
            try:
                with path.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(row) + '\n')
            except OSError:
                active_loop.default_exception_handler({'message': 'TEST_ONLY_LOOP_EVIDENCE_WRITE_FAILED'})
        active_loop.default_exception_handler({'message': json.dumps(row)})

    loop.set_exception_handler(handler)
    return handler


def observed_server(server, out, role):
    import asyncio
    async def serve():
        install_loop_observer(asyncio.get_running_loop(), out, role)
        await server.serve()
    asyncio.run(serve(), loop_factory=server.config.get_loop_factory())


def loop_observations(out, errors):
    rows = []
    for path in sorted(Path(out).glob('TEST_ONLY-loop-*.jsonl')):
        try:
            if path.stat().st_size > 1024 * 1024:
                raise ValueError('LOOP_EVIDENCE_SIZE_LIMIT')
            records = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
            if len(records) > 1001 or not all(isinstance(row, dict) for row in records):
                raise ValueError('LOOP_EVIDENCE_INVALID')
            rows.extend(records)
        except (OSError, ValueError):
            errors.append({'code': 'LOOP_EVIDENCE_UNREADABLE', 'file': path.name})
    if rows:
        errors.append({'code': 'UNATTRIBUTED_EVENT_LOOP_EXCEPTIONS', 'count': len(rows)})
    return rows


def observe_http(client, path, page, sequence):
    """Preserve failed attempts as timed observations, without automatic retries."""
    request_id = f"TEST_ONLY-{os.getpid()}-{page}-{sequence}"
    before = monotonic()
    item = {"path": path, "page": page, "request_id": request_id,
            "sequence": sequence, "observer_pid": os.getpid(),
            "started_at": datetime.now(UTC).isoformat(), "monotonic_start": before}
    try:
        response = client.get(path, headers={"X-Request-ID": request_id})
        item.update(status=response.status_code, bytes=len(response.content))
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = None
            detail = payload.get("detail") if isinstance(payload, dict) else None
            allowed = {"CURRENT_CARDS_UNAVAILABLE", "TREND_STATUS_UNAVAILABLE",
                       "CURRENT_SESSION_SNAPSHOT_UNAVAILABLE", "SNAPSHOT_READ_CAPACITY",
                       "LOGIN_CONFIGURATION_CHECK_UNAVAILABLE", "TEST_ONLY_LEGACY_NOT_MOUNTED"}
            item["response_error_code"] = detail if isinstance(detail, str) and detail in allowed else "UNCLASSIFIED_RESPONSE"
            if (isinstance(payload, dict) and payload.get("error_origin") == "GATEWAY_UPSTREAM"
                    and payload.get("error_code") in {"UPSTREAM_CONNECTION_FAILED", "UPSTREAM_TIMEOUT", "UPSTREAM_TRANSPORT_FAILED"}):
                item["response_error_code"] = payload["error_code"]
                item["response_error_origin"] = "GATEWAY_UPSTREAM"
                if payload.get('failure_stage') in {'CONNECT', 'CONNECTED', 'SEND', 'RECEIVE', 'NOT_STARTED', 'UNKNOWN'}:
                    item['response_failure_stage'] = payload['failure_stage']
    except httpx.HTTPError as exc:
        # Exception strings may contain URLs or authentication details.
        item.update(error=type(exc).__name__, status=None, bytes=None)
    item.update(seconds=monotonic() - before, observed_at=datetime.now(UTC).isoformat())
    return item


def crash_http_contract(target_pid, observer_pid):
    contract = {"version": "P11_BACKEND_CRASH_HTTP_V2", "target_pid": target_pid,
                "observer_pid": observer_pid, "registered_monotonic": monotonic(),
                "max_recovery_seconds": 15, "max_request_seconds": 3,
                "allowed": {
                    "/api/stocks/health/live": ["UPSTREAM_CONNECTION_FAILED", "UPSTREAM_TIMEOUT"],
                    "/api/options/opening-trend/current?research_strategy=opening_momentum": ["UPSTREAM_CONNECTION_FAILED", "UPSTREAM_TIMEOUT", "CURRENT_CARDS_UNAVAILABLE"],
                    "/api/options/one-minute/status?research_strategy=opening_momentum&compact=true": ["UPSTREAM_CONNECTION_FAILED", "UPSTREAM_TIMEOUT", "TREND_STATUS_UNAVAILABLE"]}}
    contract["sha256"] = sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()
    return contract


def matches_crash_contract(row, fault, samples):
    contract = fault.get("http_contract")
    if not isinstance(contract, dict):
        return False
    unsigned = {k: v for k, v in contract.items() if k != "sha256"}
    if contract.get("sha256") != sha256(json.dumps(unsigned, sort_keys=True).encode()).hexdigest():
        return False
    try:
        start, end = fault["fault_monotonic_start"], fault["snapshot_ready_monotonic"]
        path, code = row.get("path"), row.get("response_error_code")
        if (contract["version"] != "P11_BACKEND_CRASH_HTTP_V2"
                or contract["target_pid"] != fault["killed_pid"]
                or contract["observer_pid"] != row.get("observer_pid")
                or fault["observer_pid"] != row.get("observer_pid")
                or contract["registered_monotonic"] > start
                or not 0 <= end - start <= min(15, contract["max_recovery_seconds"])
                or not 0 <= row["seconds"] <= min(3, contract["max_request_seconds"])
                or not start <= row["monotonic_start"] <= row["monotonic_start"] + row["seconds"] <= end
                or row.get("status") != 503 or row.get("error")
                or code not in contract["allowed"].get(path, [])
                or fault["replacement_pid"] == fault["killed_pid"]
                or fault["pending_before"] <= 0 or fault["restored"] < fault["pending_before"]
                or fault["original_deadlines_preserved"] is not True
                or fault["initial_snapshots"]["states"] != {"current": "FRESH", "compact": "FRESH"}):
            return False
        if code == "UPSTREAM_CONNECTION_FAILED" and row.get("response_error_origin") != "GATEWAY_UPSTREAM":
            return False
        if code == 'UPSTREAM_TIMEOUT' and not (
                row.get('response_error_origin') == 'GATEWAY_UPSTREAM'
                and row.get('response_failure_stage') == 'CONNECT'
                and row['monotonic_start'] < fault['replacement_ready_monotonic']):
            return False
        return any(r.get("path") == path and r.get("observer_pid") == row.get("observer_pid")
                   and r.get("status") == 200 and not r.get("error")
                   and end <= r.get("monotonic_start", -1) <= end + 15 for r in samples)
    except (KeyError, TypeError, ValueError):
        return False


def classify_http_failures(samples, recovery):
    findings = []
    for row in samples:
        if row.get("status") == 200 and not row.get("error"):
            continue
        start = row.get("monotonic_start")
        duration = row.get("seconds")
        overlaps = []
        if isinstance(start, (int, float)) and isinstance(duration, (int, float)) and duration >= 0:
            for fault in recovery:
                left = fault.get("fault_monotonic_start")
                right = fault.get("replacement_ready_monotonic")
                snapshot_recovery = (row.get("response_error_code") in {
                    "CURRENT_CARDS_UNAVAILABLE", "TREND_STATUS_UNAVAILABLE"})
                if snapshot_recovery:
                    right = fault.get("snapshot_ready_monotonic", right)
                if (row.get("observer_pid") is not None
                        and row.get("observer_pid") == fault.get("observer_pid")
                        and isinstance(left, (int, float)) and isinstance(right, (int, float))
                        and left <= right and start <= right and start + duration >= left):
                    overlaps.append(fault["killed_pid"])
        matched = [fault["http_contract"]["sha256"] for fault in recovery
                   if matches_crash_contract(row, fault, samples)]
        findings.append({"request_id": row.get("request_id"), "path": row.get("path"),
                         "status": row.get("status"), "error": row.get("error"),
                         "response_error_code": row.get("response_error_code"),
                         "classification": "EXPECTED_INJECTED_FAILURE" if matched else "UNEXPLAINED",
                         "matched_contracts": matched,
                         "temporal_classification": "OVERLAPS_INJECTED_RECOVERY" if overlaps else "NO_OVERLAP",
                         "overlapping_killed_pids": overlaps,
                         "causal_attribution_proven": False})
    return findings


def wait_http_started(server, thread, budget=5):
    deadline = monotonic() + budget
    while not server.started:
        if not thread.is_alive() or monotonic() >= deadline:
            raise RuntimeError("ISOLATED_HTTP_START_NOT_CONFIRMED")
        sleep(.01)


def wait_initial_snapshots(snapshots, budget=5):
    from kquant.status_snapshot import SnapshotUnavailable
    start = monotonic()
    states = {}
    while True:
        for kind in ("current", "compact"):
            try:
                states[kind] = snapshots.read("opening_momentum", kind)["snapshot"]["state"]
            except SnapshotUnavailable:
                states[kind] = "UNAVAILABLE"
        if all(value == "FRESH" for value in states.values()):
            return {"states": states, "seconds": monotonic() - start}
        if monotonic() - start >= budget:
            raise RuntimeError("ISOLATED_INITIAL_SNAPSHOTS_NOT_READY")
        sleep(.01)


def tested_sources():
    names = ("scripts/check_r58_p10_topology.py", "scripts/check_r58_p9_browser.cjs",
        "start_kquant_workspace.ps1", "scripts/FoundationLifecycle.ps1",
        "scripts/Launch-FoundationDetached.ps1", "scripts/Invoke-FoundationDetached.ps1",
        "scripts/Stop-Foundation.ps1",
        "scripts/browser_response_evidence.cjs",
        "kquant/options_opening_trend_runtime.py", "kquant/options_opening_momentum.py",
        "kquant/options_opening_momentum_journal.py", "kquant/options_price_reference.py",
        "kquant/options_price_facts.py", "kquant/options_opening_trend_reference.py",
        "kquant/options_one_minute_runtime.py", "kquant/options_price_action_source.py",
        "kquant/security.py",
        "kquant/status_worker.py", "kquant/status_snapshot.py", "kquant/dashboard/app.py",
        "kquant/research_http_snapshots.py", "kquant/options_one_minute_manual.py",
        "kquant/options_data_paths.py", "kquant/options_one_minute.py",
        "kquant/options_opening_trend_store.py", "kquant/recovery_preflight.py",
        "crypto/kquant_crypto/gateway.py", "config/options_opening_momentum_v1.json")
    # Bind the entire backend/config candidate, including newly added epoch modules.
    names = set(names)
    for directory, pattern in (("kquant", "*.py"), ("crypto/kquant_crypto", "*.py"), ("config", "*.json")):
        names.update(path.relative_to(ROOT).as_posix() for path in (ROOT / directory).rglob(pattern))
    names.update(("tests/test_r58_p7_inputs.py", "tests/test_r58_signal_recovery.py",
                  "tests/test_options_opening_momentum.py"))
    names.update("web/" + name for name in ("package.json", "package-lock.json", "tsconfig.json",
                  "tsconfig.unified.json", "tsconfig.stock.recovery.json", "vite.config.ts",
                  "vite.unified.config.ts", "vite.stock.recovery.config.ts", "vitest.config.ts",
                  "vitest.recovery.config.ts", "unified.html", "index.html", "tokens.css"))
    names.update(path.relative_to(ROOT).as_posix() for path in (ROOT / "config").glob("*.yml"))
    return {name: sha256(safe(ROOT / name).read_bytes()).hexdigest() for name in sorted(names)}


def tested_tree(path):
    root = safe(path)
    pending, result = [root], {}
    while pending:
        directory = pending.pop()
        for entry in directory.iterdir():
            entry = safe(entry)
            if entry.is_dir():
                pending.append(entry)
            else:
                if len(result) >= 256 or entry.stat().st_size > 2097152:
                    raise ValueError("FRONTEND_FINGERPRINT_BUDGET")
                result[entry.relative_to(root).as_posix()] = sha256(entry.read_bytes()).hexdigest()
    return result


def load_watch(path):
    raw = safe(path).read_bytes()
    if len(raw) > 2097152:
        raise ValueError("WATCH_INPUT_BUDGET")
    watch = json.loads(raw.decode("utf-8-sig"))
    items = watch.get("items") if isinstance(watch, dict) else None
    if not isinstance(items, list) or len(items) != 111:
        raise ValueError("FULL_WATCH_111_INPUT_REQUIRED")
    symbols = set()
    for row in items:
        if not isinstance(row, dict) or not isinstance(row.get("symbol"), str) or not row["symbol"]:
            raise ValueError("WATCH_INPUT_SYMBOL")
        if row["symbol"] in symbols or not isinstance(row.get("identity_status"), str):
            raise ValueError("WATCH_INPUT_IDENTITY_OR_DUPLICATE")
        if row["identity_status"] == "verified" and not isinstance(row.get("provider_symbol"), str):
            raise ValueError("WATCH_INPUT_PROVIDER_MISSING")
        symbols.add(row["symbol"])
    return watch


def load_browser_report(path, errors):
    if not path.exists():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("BROWSER_REPORT_OBJECT_REQUIRED")
        return report
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append({"code": "BROWSER_REPORT_UNREADABLE", "error_type": type(exc).__name__})
        return None


def first_timings(events, point):
    first = {}
    for event in events:
        if event.get("research_strategy") == "opening_momentum" and event.get("bar_end") == point:
            first.setdefault(event["symbol"], event)
    keys = ("input_batch_read_seconds", "input_read_seconds", "calculation_seconds",
            "commit_batch_seconds", "enqueue_to_commit_seconds")
    return {key: {"n": len(values), "p95_seconds": percentile(values)}
            for key in keys for values in [[e.get("runtime_timing", {}).get(key)
                for e in first.values() if e.get("runtime_timing", {}).get(key) is not None]]}


def configure(cfg):
    from kquant.security import generate_password_hash
    for key in list(os.environ):
        if key.startswith("KQUANT_"):
            del os.environ[key]
    os.environ.update(
        KQUANT_REALTIME_SUPERVISOR_ENABLED="false", KQUANT_OPTION_RADAR_ENABLED="false",
        KQUANT_ONE_MINUTE_SHADOW_ENABLED="false", KQUANT_WORKSPACE_LOGIN_ENABLED="true",
        KQUANT_REQUIRE_API_AUTH="true", KQUANT_API_AUTH_TOKEN=TOKEN,
        KQUANT_BACKEND_RELEASE_ID="TEST_ONLY-r58-p10-spawned",
        KQUANT_WORKSPACE_LOGIN_EMAIL=EMAIL,
        KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH=generate_password_hash(PASSWORD),
        KQUANT_WORKSPACE_SESSION_SECRET="TEST_ONLY_SECRET" * 4,
        LOCALAPPDATA=str(Path(cfg["out"]) / "TEST_ONLY-local-config"),
    )
    if cfg.get("actual_assembly"):
        root = Path(cfg['out'])
        binding = root / 'TEST_ONLY-role-map.json'
        if binding.exists():
            os.environ.update(KQUANT_RUNTIME_DATA_ROOT=str(root),
                KQUANT_RUNTIME_PATH_BINDING=str(binding),
                KQUANT_RUNTIME_PATH_BINDING_SHA256=sha256(binding.read_bytes()).hexdigest(),
                KQUANT_OPTION_RADAR_ENABLED='true', KQUANT_OPTION_RADAR_MODE='foundation',
                KQUANT_OPTION_ONE_MINUTE_SHADOW_ENABLED='true')


def minute_path(cfg):
    out = Path(cfg['out'])
    return (out / 'work/options_one_minute-epoch-20261008/one_minute.sqlite3'
            if cfg.get('actual_assembly') else out / 'TEST_ONLY-minute.sqlite3')


def manual_path(cfg):
    return minute_path(cfg) if cfg.get('actual_assembly') else Path(cfg['out']) / 'TEST_ONLY-reported.sqlite3'


def setup(cfg):
    import pytest
    from kquant import options_one_minute as common
    from kquant.config import KquantConfig
    from kquant.dashboard.app import create_app
    from kquant.options_two_hour_data import universe
    from kquant.market_clock import previous_trading_day
    from test_r58_p7_inputs import fact_inputs
    from test_options_opening_momentum import inputs
    out = Path(cfg["out"])
    watch = load_watch(cfg["watch"])
    opening = datetime.fromisoformat(cfg["opening"])
    business = out / "TEST_ONLY-business.sqlite3"
    # This explicitly isolated app initialization cannot open recovery databases.
    create_app(config=KquantConfig(db_path=business, outputs_dir=out / "outputs"),
               research_store=out / "TEST_ONLY-research.sqlite3",
               manual_store=manual_path(cfg))
    with closing(sqlite3.connect(business)) as db, db:
        for row in watch["items"]:
            db.execute("UPDATE stock_watchlist_members SET identity_status=?,provider_symbol=? WHERE normalized_symbol=?",
                       (row["identity_status"], row["provider_symbol"], row["symbol"]))
    scope = universe(business)
    if len(scope["items"]) != 111:
        raise ValueError("FULL_WATCH_111_REQUIRED")
    symbols = [r["symbol"] for r in scope["items"] if r["identity_status"] == "verified"]
    with pytest.MonkeyPatch.context() as patch:
        _, _, reviews = fact_inputs(out, patch)
    for key in ("previous_close_interface", "price_binding_method"):
        reviews[key].update(reviewed_at=opening.isoformat(),
                            valid_until=(opening + timedelta(days=1)).isoformat(), test_only=True)
    previous = previous_trading_day(date.fromisoformat(cfg["session"])).isoformat()
    template = reviews["instrument_price_actions"]["TEST"]
    reviews["instrument_price_actions"] = {s: {
        **template, "underlying": s, "coverage_from_session": previous,
        "coverage_through_session": cfg["session"], "reviewed_at": opening.isoformat(),
        "valid_until": (opening + timedelta(days=1)).isoformat(), "test_only": True,
    } for s in symbols}
    write(out / "TEST_ONLY-sources.json", reviews)
    write(out / "TEST_ONLY-scope.json", scope)
    common.initialize(minute_path(cfg))
    if manual_path(cfg) != minute_path(cfg):
        common.initialize(manual_path(cfg))
    if cfg.get("test_only_epoch_boundary"):
        with closing(sqlite3.connect(manual_path(cfg))) as db, db:
            db.execute("CREATE TABLE data_epoch_boundary(id INTEGER PRIMARY KEY CHECK(id=1), payload_json TEXT NOT NULL)")
            boundary = {"schema": "KQUANT_NEW_MINUTE_EPOCH_V1", "test_only": True,
                "epoch_id": "TEST_ONLY-isolated-new-epoch", "session": cfg["session"],
                "record_kind": "NEW_DATA_NOT_OLD_RECOVERY", "old_position_continuity": "UNKNOWN",
                "complete_restoration_claimed": False,
                "unresolved_old_records": ["manual_position_revisions"]}
            db.execute("INSERT INTO data_epoch_boundary VALUES(1,?)", (json.dumps(boundary),))
    for symbol in symbols:
        rows = inputs(minutes=25)["bars"]
        for index, row in enumerate(rows):
            start = opening + timedelta(minutes=index)
            row.update(symbol=symbol, open_at=start.isoformat(),
                       available_at=(start + timedelta(minutes=1)).isoformat(),
                       received_at=(start + timedelta(minutes=1, milliseconds=50)).isoformat(),
                       sdk_evidence={"interface": "QuoteContext.set_on_candlestick", "test_only": True}, test_only=True)
        common.save_bars(rows, cfg["session"], minute_path(cfg))
    if cfg.get('actual_assembly'):
        from kquant.options_full_watch import initialize_full_watch_store
        from kquant.options_two_hour import initialize as queue_init
        from kquant.options_signal_copilot import initialize_copilot_store
        from kquant.options_opening_trend_store import initialize as opening_init
        full = out / 'TEST_ONLY-full-watch.sqlite3'
        copilot = out / 'TEST_ONLY-copilot.sqlite3'
        initialize_full_watch_store(full)
        queue_init(full)
        initialize_copilot_store(copilot)
        opening_init(out/'TEST_ONLY-research.sqlite3')
        write(out / 'TEST_ONLY-role-map.json', dict(schema='KQUANT_NEW_EPOCH_RUNTIME_PATHS_V1',
            runtime_root=str(out), epoch_id='TEST_ONLY-P12-MIXED', session='2026-10-08',
            data_scope_acceptance_sha256='a'*64, minute_path=str(minute_path(cfg)),
            opening_research_path=str(out/'TEST_ONLY-research.sqlite3'), stores=dict(
                main=str(business), minute=str(minute_path(cfg)),
                opening_research=str(out/'TEST_ONLY-research.sqlite3'),
                full_watch=str(full), signal_copilot=str(copilot))))


def backend(cfg, offset, connection):
    configure(cfg)
    import uvicorn
    from kquant import options_one_minute as common
    from kquant import options_price_facts as facts
    from kquant import options_price_reference as prices
    from kquant.config import KquantConfig
    from kquant.dashboard.app import create_app
    from kquant.options_opening_trend_runtime import TrendLane
    from kquant.options_one_minute_runtime import OneMinuteResearchWorker
    from starlette.responses import JSONResponse
    out = Path(cfg["out"])
    prices.ROOT = out
    opening = datetime.fromisoformat(cfg["opening"])
    clock = lambda: opening + timedelta(seconds=offset.value)
    scope = json.loads((out / "TEST_ONLY-scope.json").read_text())
    reviews = json.loads((out / "TEST_ONLY-sources.json").read_text())
    symbols = [r["symbol"] for r in scope["items"] if r["identity_status"] == "verified"]
    research = out / "TEST_ONLY-research.sqlite3"
    minute = minute_path(cfg)
    app = create_app(config=KquantConfig(db_path=out / "TEST_ONLY-business.sqlite3", outputs_dir=out / "outputs"),
                     research_store=research, research_clock=clock,
                     manual_store=manual_path(cfg))
    original_loader = app.state.research_http_snapshots.loader
    projection_log = (out / f"TEST_ONLY-projection-errors-{os.getpid()}.jsonl").open("a", encoding="utf-8")

    def observed_loader(strategy, kind, worker):
        try:
            return original_loader(strategy, kind, worker)
        except Exception as exc:
            policy_name = "options_opening_momentum_v1.json" if strategy == "opening_momentum" else "options_opening_trend_v1.json"
            projection_log.write(json.dumps({"strategy": strategy, "kind": kind,
                "diagnostic": getattr(exc, "diagnostic", {"error_type": type(exc).__name__}),
                "business_present": (out / "TEST_ONLY-business.sqlite3").is_file(),
                "research_present": research.is_file(), "policy_present": (ROOT / "config" / policy_name).is_file(),
                "observed_at": datetime.now(UTC).isoformat(), "test_only": True}) + "\n")
            projection_log.flush()
            raise

    app.state.research_http_snapshots.loader = observed_loader

    @app.middleware("http")
    async def isolate_legacy(request, call_next):
        allowed = ("/api/health", "/api/options/opening-trend/current", "/api/options/one-minute/status",
                   "/api/alerts/stream", "/api/auth", "/api/runtime/",
                   "/api/options/one-minute/evaluations/", "/api/options/one-minute/manual")
        if request.url.path.startswith("/api/") and not request.url.path.startswith(allowed):
            return JSONResponse({"detail": "TEST_ONLY_LEGACY_NOT_MOUNTED"}, status_code=503,
                                headers={"X-Kquant-Test-Isolation": "legacy-not-mounted"})
        return await call_next(request)

    events = []
    event_log = (out / f"TEST_ONLY-progress-{os.getpid()}.jsonl").open("a", encoding="utf-8")

    def event(value):
        if value.get("type") == "options_one_minute_progress":
            packet = {**value, "pid": os.getpid(), "monotonic": monotonic(), "test_only": True}
            events.append(packet)
            event_log.write(json.dumps(packet) + "\n")
            event_log.flush()

    app.state.alert_hub.add_listener(event)
    bootstrap_patches = None
    if cfg.get('actual_assembly'):
        from contextlib import ExitStack
        from unittest.mock import patch
        import queue
        from kquant import options_one_minute_runtime as worker_module
        from scripts.test_clock_transport import LoopbackClockTransport
        class TestClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock().astimezone(tz)
        class TestTransport:
            def event_queue(self, *args, **kwargs):
                return queue.Queue()
            def static_info(self, *args, **kwargs):
                return []
            def release_subscriptions(self, *args, **kwargs):
                pass
            def request(self, *args, **kwargs):
                raise RuntimeError('TEST_ONLY_SOURCE_UNAVAILABLE')
        bootstrap_patches = ExitStack()
        bootstrap_patches.enter_context(patch.object(worker_module, 'datetime', TestClock))
        bootstrap_patches.enter_context(patch('kquant.research_runtime_health.datetime', TestClock))
        bootstrap_patches.enter_context(patch.object(worker_module, 'longbridge_runtime', return_value=TestTransport()))
        bootstrap_patches.enter_context(patch('kquant.stock_signals.api_stock_quotes_batch', return_value={'items': [], 'test_only': True}))
        bootstrap_patches.enter_context(patch('kquant.option_calendar_source.CalendarSourceRunner._context', return_value=TestTransport()))
        bootstrap_patches.enter_context(LoopbackClockTransport(fail_second=cfg.get('observation_safe_hour', False)))
        app.state.option_radar_supervisor.start()
        deadline = monotonic() + 10
        while monotonic() < deadline:
            producer = app.state.option_radar_supervisor._one_minute_worker
            if producer and producer.state.get('first_loop_at'):
                break
            if producer and producer.state.get('error_id'):
                write(out/'TEST_ONLY-bootstrap-failure.json', producer.state)
                raise RuntimeError('ACTUAL_ASSEMBLY_FAILED_INIT')
            sleep(.05)
        else:
            raise RuntimeError('ACTUAL_ASSEMBLY_HANDSHAKE_MISSING')
        lane = producer.trend_lane
        lane.source_root, lane.source_reviews_path = out, out/'TEST_ONLY-sources.json'
        write(out/'TEST_ONLY-bootstrap-start.json', dict(worker=producer.state, minute_path=str(producer.path),
            opening_path=str(lane.path), actual_supervisor_start=True, actual_worker_init_run=True,
            qualification_queue=str(producer.qualification_lane.queue_path), recovery_queue=str(producer.recovery_lane.queue_path)))
    else:
        lane = TrendLane(minute, app.state.alert_hub, path=research, clock=clock,
                         source_root=out, source_reviews_path=out / "TEST_ONLY-sources.json")
        producer = OneMinuteResearchWorker.__new__(OneMinuteResearchWorker)
        producer.trend_lane = lane
    blocked, slow = Event(), Event()
    original_inputs = lane._checkpoint_inputs
    original_history = lane.history.load

    def gated_inputs(*args, **kwargs):
        if blocked.is_set() and current_thread().name == "opening-trend-research":
            sleep(30)  # Synthetic pending read fault, not a claimed live SDK test.
        return original_inputs(*args, **kwargs)

    def slow_history(*args):
        if slow.is_set():
            sleep(5)
        return original_history(*args)

    lane._checkpoint_inputs = gated_inputs
    lane.history.load = slow_history
    profiles = {}
    if cfg.get("profile"):
        def profiled(name, function):
            def call(*args, **kwargs):
                key = name + "-" + current_thread().name
                started = monotonic()
                error_type = None
                result = None
                try:
                    result = function(*args, **kwargs)
                    return result
                except Exception as exc:
                    error_type = type(exc).__name__
                    raise
                finally:
                    rows = profiles.setdefault(key, [])
                    if len(rows) < 5000:
                        sample = {"seconds": monotonic() - started, "error_type": error_type}
                        if name == "journal-ready_many":
                            sample["entries"] = len(args[1])
                            sample["admitted"] = sum(value is True for value in result) if result is not None else None
                        rows.append(sample)
            return call
        lane._checkpoint_inputs = profiled("checkpoint-input", lane._checkpoint_inputs)
        lane._calculate = profiled("calculation", lane._calculate)
        from kquant import options_opening_momentum_journal as journal
        from kquant import options_opening_trend_reference as reference
        from kquant import options_price_facts as price_facts
        for name in ("ready_many", "begin_many", "finish_many", "input_fingerprint"):
            setattr(journal, name, profiled("journal-" + name, getattr(journal, name)))
        reference._reviewed_file = profiled("source-file", reference._reviewed_file)
        for name in ("bind", "persist_bindings"):
            setattr(price_facts, name, profiled("price-facts-" + name, getattr(price_facts, name)))
    if not cfg.get('actual_assembly'):
      app.state.research_http_snapshots.worker = lambda: {
        "session": cfg["session"], "scope_hash": scope["scope_hash"],
        "stage": "TEST_ONLY_SPAWNED", "health_checked_at": datetime.now(UTC).isoformat(),
        "opening_momentum": dict(lane.state), "registered_items": scope["items"],
        "research_progress": {"completed": lane.state.get("completed"), "error": lane.state.get("error")},
    }
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cfg["backend_port"],
                                          access_log=False, log_level="warning",
                                          loop="asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto"))
    thread = Thread(target=observed_server, args=(server, out, 'backend'), daemon=True)
    thread.start()
    wait_http_started(server, thread)
    http_started_at = monotonic()
    try:
        initial_snapshots = wait_initial_snapshots(app.state.research_http_snapshots)
    except Exception:
        write(out/'TEST_ONLY-startup-snapshot-failure.json', dict(
            worker=app.state.option_radar_supervisor.one_minute_worker_status(),
            health=app.state.research_http_snapshots.health()))
        if cfg.get('actual_assembly'):
            app.state.option_radar_supervisor.stop()
        else:
            lane.close()
        server.should_exit = True
        thread.join(timeout=10)
        if bootstrap_patches:
            bootstrap_patches.close()
        raise
    connection.send({"ready": True, "pid": os.getpid(), "restored": lane.state.get("restored_checkpoints"),
                     "http_started_monotonic": http_started_at,
                     "initial_snapshots": initial_snapshots})
    try:
        while True:
            command = connection.recv()
            action = command["action"]
            if action == "stop":
                connection.send({"stopping": True})
                break
            if action in {"enqueue", "crash_prepare"}:
                if action == "crash_prepare":
                    blocked.set()
                selected = symbols if command.get("all", True) else symbols[:3]
                before = monotonic()
                source_seconds, enqueue_seconds = [], []
                quotes = []
                for symbol in selected:
                    native = {"symbol": symbol, "provider_symbol": symbol + ".US", "currency": "USD",
                              "source": "LONGBRIDGE_SECURITY_STATIC_INFO", "received_at": clock().isoformat()}
                    native["source_hash"] = common.digest(native)
                    raw = {"symbol": symbol, "provider_status": "available", "previous_close": 99,
                           "currency": "USD", "currency_evidence": native, "requested_at": clock().isoformat(),
                           "received_at": clock().isoformat(), "quote_time": clock().isoformat(), "test_only": True}
                    quotes.append(raw)
                prepared = producer._price_fact_quotes(quotes, date.fromisoformat(cfg["session"]), clock(), reviews)
                source_profile = None
                if cfg.get("profile"):
                    import cProfile
                    source_profile = cProfile.Profile()
                    source_profile.enable()
                while True:
                    source_started = monotonic()
                    try:
                        raw, binding = next(prepared)
                    except StopIteration:
                        break
                    source_seconds.append(monotonic() - source_started)
                    raw["session_price_binding"] = binding
                    enqueue_started = monotonic()
                    lane.enqueue(raw["symbol"], date.fromisoformat(cfg["session"]), [], scope["scope_hash"], {"raw_quote": raw})
                    enqueue_seconds.append(monotonic() - enqueue_started)
                if source_profile is not None:
                    import io
                    import pstats
                    source_profile.disable()
                    summary = io.StringIO()
                    pstats.Stats(source_profile, stream=summary).strip_dirs().sort_stats('cumulative').print_stats(55)
                    safe(out / f"TEST_ONLY-source-profile-{os.getpid()}-{action}-{round(offset.value)}.txt").write_text(
                        summary.getvalue(), encoding="utf-8")
                connection.send({"enqueued": len(selected), "source_and_enqueue_seconds": monotonic() - before,
                                 "source_fact_seconds": {"n": len(source_seconds), "sum": sum(source_seconds), "p95": percentile(source_seconds)},
                                 "source_fact_producer": "OneMinuteResearchWorker._price_fact_quotes",
                                 "source_fact_samples": "generator_advances_including_bounded_group_commit_not_per_asset_cost",
                                 "enqueue_seconds": {"n": len(enqueue_seconds), "sum": sum(enqueue_seconds), "p95": percentile(enqueue_seconds)},
                                 "state": dict(lane.state)})
            elif action == "slow":
                slow.set() if command["enabled"] else slow.clear()
                connection.send({"slow_history": slow.is_set()})
            elif action == "revision":
                symbol = symbols[0]
                with closing(sqlite3.connect(minute, timeout=.1)) as db:
                    row = db.execute("SELECT payload_json FROM one_minute_bars WHERE session=? AND symbol=? ORDER BY open_at LIMIT 1",
                                     (cfg["session"], symbol)).fetchone()
                changed = json.loads(row[0])
                changed.update(close=changed["close"] + .01, received_at=clock().isoformat(),
                               sdk_evidence={"interface": "QuoteContext.candlesticks", "test_only": True})
                common.save_bars([changed], cfg["session"], minute)
                lane.enqueue(symbol, date.fromisoformat(cfg["session"]), [changed], scope["scope_hash"])
                connection.send({"revision_symbol": symbol})
            elif action == "dump_stacks":
                import faulthandler
                with (out / "TEST_ONLY-backend-stacks.txt").open("w") as handle:
                    faulthandler.dump_traceback(file=handle, all_threads=True)
                connection.send({"captured": True})
            elif action == "stats":
                connection.send({"state": dict(lane.state), "events": events[-2000:], "pid": os.getpid(),
                    "actual_worker": app.state.option_radar_supervisor.one_minute_worker_status() if cfg.get('actual_assembly') else None})
            elif action == "missing_sources":
                source_path = out / "TEST_ONLY-sources.json"
                saved = source_path.read_bytes()
                try:
                    write(source_path, {})
                    invalid = {"symbol": symbols[0], "previous_close": 99,
                        "requested_at": clock().isoformat(), "received_at": clock().isoformat(),
                        "quote_time": clock().isoformat(), "test_only": True}
                    lane.enqueue(symbols[0], date.fromisoformat(cfg["session"]), [], scope["scope_hash"],
                                 {"raw_quote": invalid})
                    limit = monotonic() + 8
                    degraded = None
                    while monotonic() < limit:
                        with closing(sqlite3.connect(research, timeout=.1)) as db:
                            db.execute("PRAGMA query_only=ON")
                            record = db.execute("SELECT payload_json FROM evaluations "
                                "WHERE symbol=? ORDER BY rowid DESC LIMIT 1", (symbols[0],)).fetchone()
                        if record:
                            observed = json.loads(record[0])
                            if observed.get("state") == "INCOMPLETE":
                                degraded = observed
                                break
                        sleep(.05)
                    worker = app.state.option_radar_supervisor.one_minute_worker_status()
                    connection.send({"test_only": True, "missing_source_result": degraded,
                        "actual_worker": worker, "pid": os.getpid(),
                        "supervisor_assembly": cfg.get('actual_assembly'),
                        "sources_restored_in_finally": True})
                finally:
                    source_path.write_bytes(saved)
            else:
                raise ValueError("UNKNOWN_ISOLATED_COMMAND")
    finally:
        blocked.clear()
        slow.clear()
        if cfg.get('actual_assembly'):
            app.state.option_radar_supervisor.stop()
            write(out/'TEST_ONLY-bootstrap-stop.json', app.state.option_radar_supervisor.one_minute_worker_status())
        else:
            lane.close()
        server.should_exit = True
        thread.join(timeout=10)
        if bootstrap_patches:
            bootstrap_patches.close()
        for name, rows in profiles.items():
            write(out / f"TEST_ONLY-{os.getpid()}-{name}.json", {"test_only": True,
                "segments": rows, "p95_seconds": percentile([row["seconds"] for row in rows])})
        event_log.close()
        projection_log.close()


def gateway(cfg, offset, connection):
    import uvicorn
    from kquant_crypto.gateway import create_gateway_app
    configure(cfg)
    app = create_gateway_app(stocks_url=f"http://127.0.0.1:{cfg['backend_port']}",
                             crypto_url="http://127.0.0.1:1", web_dist_dir=cfg["dist"], stocks_api_token=TOKEN)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cfg["gateway_port"],
                                          access_log=False, log_level="warning",
                                          loop="asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto"))
    thread = Thread(target=observed_server, args=(server, Path(cfg['out']), 'gateway'), daemon=True)
    thread.start()
    wait_http_started(server, thread)
    connection.send({"ready": True, "pid": os.getpid()})
    try:
        while True:
            action = connection.recv()["action"]
            if action == "stop":
                connection.send({"stopping": True})
                break
            if action == "dump_stacks":
                import faulthandler
                with (Path(cfg["out"]) / "TEST_ONLY-gateway-stacks.txt").open("w") as handle:
                    faulthandler.dump_traceback(file=handle, all_threads=True)
                connection.send({"captured": True})
            elif action == "expired_cookie":
                import time
                now = int(time.time())
                connection.send({"cookie": app.state.workspace_auth.issue(email=EMAIL, issued_at=now - 60, expires_at=now - 1)})
            else:
                connection.send({"status": "UNKNOWN_COMMAND"})
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def spawn(ctx, target, cfg, offset):
    parent, child = ctx.Pipe()
    process = ctx.Process(target=target, args=(cfg, offset, child), daemon=False)
    process.start()
    child.close()
    if not parent.poll(40):
        process.terminate()
        process.join(10)
        raise RuntimeError("SPAWN_READY_TIMEOUT_" + target.__name__)
    ready = parent.recv()
    return process, parent, ready


def command(connection, action, **values):
    connection.send({"action": action, **values})
    if not connection.poll(40):
        raise RuntimeError("ISOLATED_CONTROL_DEADLINE_" + action)
    return connection.recv()


def journal_snapshot(path):
    with closing(sqlite3.connect(path, timeout=.1)) as db:
        db.execute("PRAGMA query_only=ON")
        rows = db.execute("SELECT job_id,state,slot,deadline_at,payload_json FROM two_hour_jobs").fetchall()
    return {r[0]: {"state": r[1], "slot": r[2], "deadline": r[3],
                   "kind": json.loads(r[4]).get("kind"),
                   "generation": json.loads(r[4]).get("input_generation")} for r in rows}


def checkpoint_record(path, cfg, slot, events):
    from kquant.options_opening_momentum import load_policy
    point = datetime.fromisoformat(cfg["opening"]) + timedelta(minutes=slot * 5)
    with closing(sqlite3.connect(path, timeout=.1)) as db:
        db.execute("PRAGMA query_only=ON")
        rows = db.execute("SELECT symbol,right_name,state,payload_json FROM evaluations WHERE policy_hash=? AND session=? AND json_extract(payload_json,'$.calculation_bar_end')=?",
                          (load_policy()["policy_hash"], cfg["session"], point.isoformat())).fetchall()
    scope = json.loads((Path(cfg["out"]) / "TEST_ONLY-scope.json").read_text())
    expected = {(r["symbol"], right) for r in scope["items"] if r["identity_status"] == "verified" for right in ("CALL", "PUT")}
    observed = {(r[0], r[1]) for r in rows}
    matching = {e["symbol"] for e in events if e.get("research_strategy") == "opening_momentum" and e.get("bar_end") == point.isoformat()}
    return {"checkpoint": point.isoformat(), "registered_directions": 222,
            "identity_excluded": 222 - len(expected), "evaluated_directions": len(observed),
            "raw_evaluation_records": len(rows), "states": dict(Counter(r[2] for r in rows)),
            "unexplained_missing": sorted(expected - observed), "test_only": True,
            "source_conflict_directions": [[r[0], r[1]] for r in rows if "SOURCE_CONFLICT" in json.loads(r[3]).get("reasons", [])],
            "first_timing_symbols": len(matching), "expected_timing_symbols": len(expected) // 2,
            "segments": first_timings(events, point.isoformat())}


def manual_http(base, cfg, gateway_pipe):
    """Exercise real handlers with a clearly synthetic self-reported contract."""
    path = Path(cfg["out"]) / "TEST_ONLY-research.sqlite3"
    with closing(sqlite3.connect(path, timeout=.1)) as db:
        row = db.execute("SELECT evaluation_id,symbol FROM evaluations WHERE right_name='CALL' AND state='NUMERIC_PASS' ORDER BY symbol LIMIT 1").fetchone()
    if row is None:
        raise RuntimeError("MANUAL_TEST_EVALUATION_MISSING")
    now = (datetime.fromisoformat(cfg["opening"]) + timedelta(seconds=301)).isoformat()
    expiry = (date.fromisoformat(cfg["session"]) + timedelta(days=3)).strftime("%y%m%d")
    trace = Path(cfg["out"]) / "TEST_ONLY-manual-requests.jsonl"

    def request_started(request):
        request.extensions["observation_start"] = monotonic()
        with trace.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"event": "started", "method": request.method,
                                     "path": request.url.path,
                                     "at": datetime.now(UTC).isoformat()}) + "\n")

    def response_received(response):
        request = response.request
        with trace.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"event": "response", "method": request.method,
                                     "path": request.url.path, "status": response.status_code,
                                     "elapsed_seconds": monotonic() - request.extensions["observation_start"],
                                     "at": datetime.now(UTC).isoformat()}) + "\n")

    with httpx.Client(base_url=base, timeout=3,
                      event_hooks={"request": [request_started], "response": [response_received]}) as client:
        login = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
        payload = {"operation_key": "TEST_ONLY_topology_open", "evaluation_id": row[0],
                   "contract_id": row[1] + expiry + "C105000.US", "quantity": 2, "multiplier": 100,
                   "entry_price": 1.01, "underlying_entry_price": 105, "entry_fees": 1,
                   "exit_fee_estimate": 1, "executed_at": now}
        opened = client.post("/api/options/one-minute/manual/entries", json=payload)
        result = {"test_only": True, "synthetic_contract_not_live_qualification": True,
                  "login_status": login.status_code, "entry_status": opened.status_code,
                  "actual_http_handlers": True, "production_user_login": False}
        if opened.status_code != 200:
            return result
        duplicate = client.post("/api/options/one-minute/manual/entries", json=payload)
        conflict = client.post("/api/options/one-minute/manual/entries", json={**payload, "quantity": 3})
        partial = {"operation_key": "TEST_ONLY_topology_exit", "position_id": opened.json()["position_id"],
                   "quantity": 1, "exit_price": 1.1, "exit_fees": .5, "executed_at": now}
        exited = client.post("/api/options/one-minute/manual/exits", json=partial)
        repeated = client.post("/api/options/one-minute/manual/exits", json=partial)
        current = client.get("/api/options/one-minute/manual")
        result.update(duplicate_entry_same=duplicate.json() == opened.json(), changed_key_status=conflict.status_code,
                      partial_exit_status=exited.status_code, duplicate_exit_same=repeated.json() == exited.json(),
                      open_quantity=current.json().get("positions", [{}])[0].get("open_quantity"),
                      paper_fill=opened.json().get("paper_fill"), real_order_created=opened.json().get("real_order_created"))
        expired = command(gateway_pipe, "expired_cookie")["cookie"]
        client.cookies.clear()
        client.cookies.set("kquant_workspace_session", expired)
        result["expired_session_status"] = client.get("/api/options/one-minute/manual").status_code
        client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
        result["relogin_quantity"] = client.get("/api/options/one-minute/manual").json().get("positions", [{}])[0].get("open_quantity")
        result["logout_status"] = client.post("/api/auth/logout").status_code
        result["after_logout_status"] = client.get("/api/options/one-minute/manual").status_code
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--watch", type=Path, required=True)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--playwright-module", type=Path)
    parser.add_argument("--browser-executable", type=Path)
    parser.add_argument("--evidence-root", type=Path, default=ROOT.parent / "evidence")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--expected-manifest", type=Path)
    parser.add_argument("--require-hour", action="store_true")
    parser.add_argument("--seconds", type=int, default=3600)
    parser.add_argument("--checkpoint-interval", type=int, default=300)
    parser.add_argument("--profile", action="store_true")
    parser.add_argument("--actual-assembly", action="store_true")
    parser.add_argument("--observation-safe-hour", action="store_true")
    parser.add_argument("--test-only-epoch-boundary", action="store_true")
    parser.add_argument("--backend-port", type=int, default=8141)
    parser.add_argument("--gateway-port", type=int, default=8142)
    parser.add_argument("--session", default="2026-10-07")
    args = parser.parse_args()
    if args.require_hour and (args.seconds < 3600 or args.checkpoint_interval != 300 or args.node is None):
        raise ValueError("HOUR_REQUIRES_3600_SECONDS_300_CADENCE_AND_BROWSER")
    out, dist, watch = safe(args.out), safe(args.dist), safe(args.watch)
    load_watch(watch)
    evidence_root = safe(args.evidence_root)
    allowed_evidence_roots = {safe(ROOT.parent / "evidence"), safe(ROOT.parent.parent / "evidence")}
    if (evidence_root not in allowed_evidence_roots or out.exists() or out == evidence_root
            or not out.is_relative_to(evidence_root) or args.seconds < 60 or args.checkpoint_interval < 1):
        raise ValueError("FRESH_SCOPED_ISOLATION_REQUIRED")
    if len({args.backend_port, args.gateway_port}) != 2 or not all(8100 <= p <= 8999 for p in (args.backend_port, args.gateway_port)):
        raise ValueError("ISOLATION_PORTS_ONLY")
    for port in (args.backend_port, args.gateway_port):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    from kquant.market_clock import session_bounds_utc
    opening, _ = session_bounds_utc(date.fromisoformat(args.session))
    cfg = {**vars(args), "out": str(out), "dist": str(dist), "watch": str(watch), "opening": opening.isoformat()}
    source_start = tested_sources()
    frontend_start = tested_tree(dist)
    frontend_source_start = tested_tree(ROOT / "web/src")
    browser_options = []
    for flag, value in (("--playwright-module", args.playwright_module), ("--browser-executable", args.browser_executable)):
        if value is not None:
            browser_options.extend((flag, str(safe(value))))
    browser_preflight = None
    if args.node:
        browser_check = subprocess.run(
            [str(safe(args.node)), str(ROOT / "scripts/check_r58_p9_browser.cjs"),
             "--preflight-only", *browser_options],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if browser_check.returncode != 0:
            raise RuntimeError("BROWSER_DEPENDENCY_PREFLIGHT_FAILED")
        browser_preflight = json.loads(browser_check.stdout)
    manifest = {"schema": "KQUANT_TEST_ONLY_TOPOLOGY_CANDIDATE_V1",
                "test_only": True, "tested_source_sha256": source_start,
                "tested_frontend_sha256": frontend_start,
                "tested_frontend_source_sha256": frontend_source_start,
                "watch_sha256": sha256(watch.read_bytes()).hexdigest(),
                "browser_dependencies": browser_preflight,
                "planned_seconds": args.seconds, "checkpoint_interval": args.checkpoint_interval,
                "require_hour": args.require_hour, "test_only_epoch_boundary": args.test_only_epoch_boundary,
                "profiling_enabled": args.profile, "backend_port": args.backend_port,
                "gateway_port": args.gateway_port,
                "session": args.session, "live_market_acceptance": False}
    manifest['actual_supervisor_worker_assembly'] = args.actual_assembly
    manifest['observation_safe_hour'] = args.observation_safe_hour
    if args.expected_manifest is not None:
        expected = json.loads(safe(args.expected_manifest).read_text(encoding="utf-8-sig"))
        if expected != manifest:
            raise ValueError("FROZEN_CANDIDATE_MANIFEST_MISMATCH")
    if args.preflight_only:
        print(json.dumps(manifest, indent=2), flush=True)
        return 0
    out.mkdir(parents=True)
    configure(cfg)
    write(out / "TEST_ONLY.json", {"test_only": True, "synthetic_clock_and_sources": True,
          "production_writes": 0, "sdk_connections": 0, "planned_seconds": args.seconds})
    write(out / "candidate_manifest.json", manifest)
    setup(cfg)
    ctx = mp.get_context("spawn")
    offset = ctx.Value("d", 301.0)
    children, browsers, browser_logs, polls, samples, checkpoints, recovery, errors = [], [], [], [], [], [], [], []
    manual = None
    degraded_observation = None
    stopped = Event()
    start = monotonic()
    backend_process = backend_pipe = None
    try:
        backend_process, backend_pipe, ready = spawn(ctx, backend, cfg, offset)
        children.append((backend_process, backend_pipe))
        gateway_process, gateway_pipe, gateway_ready = spawn(ctx, gateway, cfg, offset)
        children.append((gateway_process, gateway_pipe))
        write(out / "TEST_ONLY-topology.json", {"controller_pid": os.getpid(), "backend": ready,
                                              "gateway": gateway_ready, "separate_processes": True})
        base = f"http://127.0.0.1:{args.gateway_port}"
        with httpx.Client(base_url=base, timeout=3) as client:
            deadline = monotonic() + 30
            while True:
                try:
                    if client.get("/api/health/live").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if monotonic() >= deadline:
                    raise RuntimeError("ISOLATED_HTTP_NOT_READY")
                sleep(.1)
        if args.node:
            log = (out / "browser-stderr.log").open("w")
            browser_logs.append(log)
            browser_command = [str(safe(args.node)), str(ROOT / "scripts/check_r58_p9_browser.cjs"), str(out), base, *browser_options]
            if args.test_only_epoch_boundary:
                browser_command.append("--test-only-epoch-boundary")
            browser = subprocess.Popen(browser_command,
                                       stderr=log, stdout=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            browsers.append(browser)
            deadline = monotonic() + 90
            while not (out / "browser-ready.json").exists():
                if browser.poll() is not None or (out / "browser-failed.json").exists() or monotonic() >= deadline:
                    raise RuntimeError("ACTUAL_COMPILED_BROWSER_NOT_READY")
                sleep(.2)
        start = monotonic()

        if args.observation_safe_hour:
            if not args.actual_assembly:
                raise ValueError("OBSERVATION_HOUR_REQUIRES_REAL_ASSEMBLY")
            degraded_observation = command(backend_pipe, "missing_sources")
            with httpx.Client(base_url=base, timeout=3) as client:
                degraded_observation["live_http"] = client.get("/api/health/live").status_code
            row = degraded_observation.get("missing_source_result") or {}
            if (degraded_observation["live_http"] != 200 or row.get("qualified_signal")
                    or row.get("state") != "INCOMPLETE"
                    or not degraded_observation.get("actual_worker", {}).get("loop_count")):
                errors.append({"code": "SAFE_MISSING_SOURCE_ASSEMBLY_FAILED"})
            write(out / "TEST_ONLY-degraded-observation.json", degraded_observation)

        def poll_page(number):
            with httpx.Client(base_url=base, timeout=3) as client, (out / f"TEST_ONLY-http-{number}.jsonl").open("w") as log:
                login = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
                if login.status_code != 200:
                    errors.append({"code": "POLL_LOGIN", "status": login.status_code})
                    return
                sequence = 0
                while not stopped.is_set():
                    for path in ("/api/health/live", "/api/stocks/health/live", "/api/options/opening-trend/current?research_strategy=opening_momentum",
                                 "/api/options/one-minute/status?research_strategy=opening_momentum&compact=true"):
                        sequence += 1
                        item = observe_http(client, path, number, sequence)
                        samples.append(item)
                        log.write(json.dumps(item) + "\n")
                        log.flush()
                    stopped.wait(5)

        for number in range(3):
            thread = Thread(target=poll_page, args=(number,), daemon=True)
            thread.start()
            polls.append(thread)
        research = out / "TEST_ONLY-research.sqlite3"
        # Stop the actual backend while durable work is pending, not after completion.
        command(backend_pipe, "crash_prepare", all=False)
        deadline = monotonic() + 5
        before = {}
        while monotonic() < deadline:
            before = journal_snapshot(research)
            all_pending = {k: v for k, v in before.items() if v["state"] in {"READY", "LEASED", "WAIT_INPUT"}}
            pending = {k: v for k, v in all_pending.items() if v.get('kind') == 'OPENING_MOMENTUM_CALCULATION'}
            if len(pending) >= 3:
                break
            sleep(.02)
        if len(pending) < 3:
            raise RuntimeError("CRASH_REQUIRES_DURABLE_PENDING")
        killed_pid = backend_process.pid
        http_contract = crash_http_contract(killed_pid, os.getpid())
        write(out / "TEST_ONLY-crash-http-contract.json", http_contract)
        crash_started = monotonic()
        backend_process.terminate()
        backend_process.join(10)
        if backend_process.is_alive():
            raise RuntimeError("ISOLATED_BACKEND_CRASH_NOT_TERMINATED")
        backend_process, backend_pipe, resumed = spawn(ctx, backend, cfg, offset)
        replacement_ready = monotonic()
        children.append((backend_process, backend_pipe))
        after = journal_snapshot(research)
        preserved = all(k in after and after[k]["deadline"] == row["deadline"] and after[k]["slot"] == row["slot"] for k, row in all_pending.items())
        recovery.append({"killed_pid": killed_pid, "replacement_pid": backend_process.pid,
                         "http_contract": http_contract,
                         "observer_pid": os.getpid(),
                         "fault_monotonic_start": crash_started,
                         "replacement_ready_monotonic": resumed["http_started_monotonic"],
                         "snapshot_ready_monotonic": replacement_ready,
                         "initial_snapshots": resumed["initial_snapshots"],
                         "pending_before": len(pending), "restored": resumed["restored"],
                         "pending_count_basis": "OPENING_MOMENTUM_CALCULATION_ONLY",
                         "other_pending": {k: v for k, v in all_pending.items() if k not in pending},
                         "original_deadlines_preserved": preserved, "before": pending, "after": after})
        if not preserved or resumed["restored"] < 3:
            raise RuntimeError("ORIGINAL_PENDING_NOT_RECOVERED")
        for slot in range(1, 6):
            target = (slot - 1) * args.checkpoint_interval
            while monotonic() - start < target:
                if args.checkpoint_interval == 300:
                    offset.value = 301 + monotonic() - start
                stopped.wait(.2)
            offset.value = slot * 300 + 1
            admission = command(backend_pipe, "enqueue")
            until = monotonic() + 60
            while True:
                packet = command(backend_pipe, "stats")
                record = checkpoint_record(research, cfg, slot, packet["events"])
                if (not record["unexplained_missing"] and record["first_timing_symbols"] == record["expected_timing_symbols"]) or monotonic() >= until:
                    break
                sleep(.05)
            record["source_and_enqueue_seconds"] = admission["source_and_enqueue_seconds"]
            record["source_fact_seconds"] = admission["source_fact_seconds"]
            record["source_fact_producer"] = admission["source_fact_producer"]
            record["source_fact_samples"] = admission["source_fact_samples"]
            record["enqueue_seconds"] = admission["enqueue_seconds"]
            checkpoints.append(record)
            write(out / f"TEST_ONLY-checkpoint-{slot}.json", record)
            print(json.dumps({"stage": "checkpoint", **record}), flush=True)
            if record["unexplained_missing"]:
                errors.append({"code": "CHECKPOINT_MISSING", "slot": slot})
            if record["first_timing_symbols"] != record["expected_timing_symbols"]:
                errors.append({"code": "CHECKPOINT_TIMING_INCOMPLETE", "slot": slot})
            if slot == 1:
                manual = manual_http(base, cfg, gateway_pipe)
                write(out / "TEST_ONLY-manual-http.json", manual)
                if not (manual.get("entry_status") == 200 and manual.get("duplicate_entry_same")
                        and manual.get("changed_key_status") == 400 and manual.get("partial_exit_status") == 200
                        and manual.get("duplicate_exit_same") and manual.get("open_quantity") == 1
                        and manual.get("expired_session_status") == 401 and manual.get("relogin_quantity") == 1
                        and manual.get("after_logout_status") == 401 and not manual.get("paper_fill")
                        and not manual.get("real_order_created")):
                    errors.append({"code": "ACTUAL_MANUAL_HTTP_FAILED"})
            if slot == 2:
                command(backend_pipe, "slow", enabled=True)
                command(backend_pipe, "revision")
                with closing(sqlite3.connect(research, timeout=.1)) as db:
                    db.execute("BEGIN IMMEDIATE")
                    sleep(4)
                    db.rollback()
                command(backend_pipe, "slow", enabled=False)
            if slot >= 3 and not record["source_conflict_directions"]:
                errors.append({"code": "UNEXPLAINED_REVISION_NOT_BLOCKED", "slot": slot})
        while monotonic() - start < args.seconds:
            if args.checkpoint_interval == 300:
                offset.value = min(3600, 301 + monotonic() - start)
            sleep(.5)
    except Exception as exc:
        errors.append({"code": "TOPOLOGY_EXERCISE_FAILED", "error_type": type(exc).__name__, "detail": str(exc)})
        for process, pipe in children:
            if process.is_alive():
                try:
                    pipe.send({"action": "dump_stacks"})
                    if pipe.poll(2):
                        pipe.recv()
                except (OSError, EOFError):
                    pass
    finally:
        duration = monotonic() - start
        stopped.set()
        for thread in polls:
            thread.join(5)
        if browsers:
            write(out / "browser-stop.json", {"test_only": True})
        for browser in browsers:
            try:
                browser.wait(90)
            except subprocess.TimeoutExpired:
                browser.terminate()
                browser.wait(10)
                errors.append({"code": "BROWSER_STOP_TIMEOUT"})
        for process, pipe in reversed(children):
            if process.is_alive():
                try:
                    command(pipe, "stop")
                except (EOFError, OSError, RuntimeError):
                    pass
                process.join(15)
            if process.is_alive():
                process.terminate()
                process.join(10)
                errors.append({"code": "CHILD_GRACEFUL_STOP_TIMEOUT", "pid": process.pid})
            pipe.close()
        for log in browser_logs:
            log.close()
        browser_report = load_browser_report(out / "browser-report.json", errors)
        source_end = tested_sources()
        if source_start != source_end:
            errors.append({"code": "TESTED_SOURCE_CHANGED_DURING_RUN"})
        frontend_end = tested_tree(dist)
        frontend_source_end = tested_tree(ROOT / "web/src")
        if frontend_start != frontend_end or frontend_source_start != frontend_source_end:
            errors.append({"code": "TESTED_FRONTEND_CHANGED_DURING_RUN"})
        failure_classification = classify_http_failures(samples, recovery)
        unexplained = [row for row in failure_classification if row["classification"] == "UNEXPLAINED"]
        if unexplained:
            errors.append({"code": "UNEXPLAINED_HTTP_FAILURES", "count": len(unexplained)})
        loop_errors = loop_observations(out, errors)
        report = {"test_only": True, "actual_backend_gateway_separate_processes": True,
                  "safe_degraded_observation": degraded_observation,
                  "event_loop_exception_observations": loop_errors,
                  "http_failure_classification": failure_classification,
                  "duration_seconds": duration, "continuous_60_minutes": duration >= 3600,
                  "five_minute_cadence": args.checkpoint_interval == 300,
                  "checkpoints": checkpoints, "crash_recovery": recovery, "errors": errors,
                  "manual_http": manual,
                  "real_browser": browser_report, "live_sdk_connections": 0, "production_writes": 0,
                  "synthetic_inputs_and_source_facts": True, "live_market_acceptance": False,
                  "profiling_enabled": args.profile,
                  "tested_source_sha256": source_start, "tested_sources_unchanged": source_start == source_end,
                  "tested_frontend_sha256": frontend_start,
                  "tested_frontend_source_sha256": frontend_source_start,
                  "tested_frontend_unchanged": frontend_start == frontend_end and frontend_source_start == frontend_source_end,
                  "production_restored": False, "child_processes_alive": [p.pid for p, _ in children if p.is_alive()],
                  "performance_target_seconds": 2,
                  "performance_pass": len(checkpoints) == 5 and all(
                      p["first_timing_symbols"] == p["expected_timing_symbols"] and
                      p["segments"]["enqueue_to_commit_seconds"]["p95_seconds"] is not None and
                      p["segments"]["enqueue_to_commit_seconds"]["p95_seconds"] <= 2 for p in checkpoints),
                  "full_acceptance": False,
                  "http": {path: {"n": len(rows), "p95_seconds": percentile([r["seconds"] for r in rows]),
                      "statuses": dict(Counter(str(r.get("status", r.get("error"))) for r in rows))}
                      for path in {r["path"] for r in samples}
                      for rows in [[r for r in samples if r["path"] == path]]}}
        report['observation_assembly_pass'] = bool(args.observation_safe_hour and args.actual_assembly
            and report['continuous_60_minutes'] and report['five_minute_cadence']
            and not errors and len(checkpoints) == 5 and not report['child_processes_alive']
            and report['tested_sources_unchanged'] and report['tested_frontend_unchanged']
            and degraded_observation and degraded_observation.get('live_http') == 200
            and browser_report and not browser_report.get('problems'))
        report['observation_acceptance_boundary'] = ('ASSEMBLY_AND_SAFE_DEGRADED_ONLY_NOT_MARKET_OR_PERFORMANCE'
            if args.observation_safe_hour else None)
        write(out / "topology_report.json", report)
        print(json.dumps({"completed": True, "duration_seconds": duration, "errors": errors}), flush=True)
    if args.require_hour and (not report["continuous_60_minutes"] or not report["five_minute_cadence"]
                              or (not args.observation_safe_hour and not report["performance_pass"]) or not report["tested_sources_unchanged"]
                              or not report["tested_frontend_unchanged"] or report["child_processes_alive"]):
        return 1
    if errors or len(checkpoints) != 5 or (args.node and (browser_report is None or browser_report["problems"])):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
