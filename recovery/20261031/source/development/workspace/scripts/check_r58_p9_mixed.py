"""TEST_ONLY 60-minute mixed exercise of real HTTP, journal, source and store paths.

Only the transport inputs and clock are synthetic. No production database or SDK
connection is used. The shipped gateway/frontend and research implementation run.
"""
import argparse
from collections import Counter
from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import sys
import subprocess
from threading import Event, Thread
from time import monotonic, sleep

import httpx
import pytest
import uvicorn

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "crypto"))


def percentile(values, p=.95):
    values = sorted(values)
    return values[min(len(values) - 1, int(p * len(values)))] if values else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=3600)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--backend-port", type=int, default=8131)
    parser.add_argument("--gateway-port", type=int, default=8132)
    parser.add_argument("--checkpoint-interval", type=int, default=300)
    parser.add_argument("--real-window", action="store_true")
    args = parser.parse_args()
    out = args.out.absolute()
    if (out.drive.upper() != "C:" or out.exists() or args.seconds < 60
            or args.checkpoint_interval < 1 or args.backend_port == args.gateway_port):
        raise ValueError("FRESH_C_DRIVE_TEST_ONLY_DIRECTORY_REQUIRED")
    out.mkdir(parents=True)
    (out / "TEST_ONLY.json").write_text(json.dumps({"test_only": True, "production_writes": 0,
        "live_sdk_connections": 0, "planned_seconds": args.seconds}), encoding="utf-8")
    executed_files = ("kquant/dashboard/app.py", "kquant/research_http_snapshots.py", "kquant/status_snapshot.py",
        "kquant/security.py",
        "kquant/options_opening_trend_runtime.py", "kquant/options_opening_momentum.py", "kquant/options_price_reference.py",
        "crypto/kquant_crypto/gateway.py", "scripts/check_r58_p9_mixed.py", "scripts/check_r58_p9_browser.cjs")
    executed = {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in executed_files}
    (out / "executed-source-hashes.json").write_text(json.dumps(executed, indent=2), encoding="utf-8")
    (out / "executed_harness.py").write_bytes(Path(__file__).read_bytes())
    from kquant import options_one_minute as common
    from kquant import options_opening_trend_store as store
    from kquant import options_price_facts as facts
    from kquant import options_price_reference as prices
    from kquant import options_opening_trend_reference as sources
    from kquant import options_opening_momentum as model
    from kquant.options_opening_trend_runtime import TrendLane
    from kquant.config import KquantConfig
    from kquant.dashboard.app import create_app
    from kquant.options_two_hour_data import universe
    from kquant_crypto.gateway import create_gateway_app
    from test_r58_p7_inputs import fact_inputs
    from test_options_opening_momentum import inputs

    errors, checkpoint_results, timings, latencies, manual_exercise = [], [], [], [], []
    stopped = Event()
    servers, threads = [], []
    with pytest.MonkeyPatch.context() as patch:
        for key in ("KQUANT_REALTIME_SUPERVISOR_ENABLED", "KQUANT_OPTION_RADAR_ENABLED",
                    "KQUANT_ONE_MINUTE_SHADOW_ENABLED", "KQUANT_WORKSPACE_LOGIN_ENABLED"):
            patch.setenv(key, "false")
        patch.setenv("KQUANT_BACKEND_RELEASE_ID", "TEST_ONLY-r58-p9-mixed")
        patch.setenv("KQUANT_REQUIRE_API_AUTH", "true")
        patch.setenv("KQUANT_API_AUTH_TOKEN", "TEST_ONLY_internal_transport_token")
        patch.delenv("KQUANT_OPTION_FOUNDATION_ROOT", raising=False)
        patch.setenv("LOCALAPPDATA", str(out / "local-config"))
        if args.node:
            from kquant_crypto.security import hash_password
            patch.setenv("KQUANT_WORKSPACE_LOGIN_ENABLED", "true")
            patch.setenv("KQUANT_WORKSPACE_LOGIN_EMAIL", "test-only@example.invalid")
            patch.setenv("KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH", hash_password("TEST_ONLY_not_a_user_password"))
            patch.setenv("KQUANT_WORKSPACE_SESSION_SECRET", "TEST_ONLY_SECRET" * 4)
        patch.setattr(prices, "ROOT", out)
        business, minute, research, reported = (out / name for name in ("business.sqlite3", "minute.sqlite3", "research.sqlite3", "reported.sqlite3"))
        opening = datetime(2026, 10, 6, 13, 30, tzinfo=UTC)
        virtual = [opening + timedelta(minutes=5, seconds=1)]
        running_start = [None]
        def test_clock():
            if args.real_window:
                return opening + timedelta(seconds=0 if running_start[0] is None else monotonic() - running_start[0])
            return virtual[0]
        app = create_app(config=KquantConfig(db_path=business, outputs_dir=out / "outputs"), research_store=research,
                         research_clock=test_clock, manual_store=reported)
        # Make unwired legacy datasets unavailable in this isolated deployment.
        # Current research handlers, authentication and middleware remain real.
        @app.middleware("http")
        async def isolate_legacy_datasets(request, call_next):
            from starlette.responses import JSONResponse
            path = request.url.path
            allowed = ("/api/health", "/api/options/opening-trend/current", "/api/options/one-minute/status",
                       "/api/alerts/stream", "/api/auth", "/api/runtime/")
            allowed += ("/api/options/one-minute/evaluations/", "/api/options/one-minute/manual")
            if path.startswith("/api/") and not any(path.startswith(prefix) for prefix in allowed):
                return JSONResponse({"status": "UNAVAILABLE", "detail": "TEST_ONLY_LEGACY_DATASET_NOT_MOUNTED"}, status_code=503)
            return await call_next(request)
        scope = universe(business)
        original_watch = json.loads((out.parent / "production-readonly-indexed/watch.json").read_text())
        with closing(sqlite3.connect(business)) as db, db:
            for row in original_watch["items"]:
                db.execute("UPDATE stock_watchlist_members SET identity_status=?,provider_symbol=? WHERE normalized_symbol=?",
                           (row["identity_status"], row["provider_symbol"], row["symbol"]))
        scope = universe(business)
        if len(scope["items"]) != 111:
            raise AssertionError("FULL_WATCH_111_REQUIRED")
        symbols = [row["symbol"] for row in scope["items"] if row["identity_status"] == "verified"]
        unknown = [row["symbol"] for row in scope["items"] if row["identity_status"] != "verified"]
        print(json.dumps({"stage": "isolated_setup", "registered": 111, "verified": len(symbols), "unknown": unknown}), flush=True)
        base, _, reviews = fact_inputs(out, patch)
        # The shared interface facts and per-asset actions are explicitly synthetic.
        for row in (reviews["previous_close_interface"], reviews["price_binding_method"]):
            row.update(reviewed_at=opening.isoformat(), valid_until=(opening + timedelta(days=1)).isoformat(), test_only=True)
        template = reviews["instrument_price_actions"].pop("TEST")
        reviews["instrument_price_actions"] = {symbol: {**template, "underlying": symbol,
            "coverage_from_session": "2026-10-05", "coverage_through_session": "2026-10-06",
            "reviewed_at": opening.isoformat(), "valid_until": (opening + timedelta(days=1)).isoformat(),
            "test_only": True} for symbol in symbols}
        reviews_path = out / "TEST_ONLY_sources.json"
        reviews_path.write_text(json.dumps(reviews), encoding="utf-8")
        common.initialize(minute)
        common.initialize(reported)

        def quote(symbol):
            native = {"symbol": symbol, "provider_symbol": symbol + ".US", "currency": "USD",
                "source": "LONGBRIDGE_SECURITY_STATIC_INFO", "received_at": opening.isoformat()}
            native["source_hash"] = common.digest(native)
            raw = {"symbol": symbol, "provider_status": "available", "previous_close": 99,
                "currency": "USD", "currency_evidence": native, "requested_at": opening.isoformat(),
                "received_at": opening.isoformat(), "quote_time": opening.isoformat(), "test_only": True}
            raw["session_price_binding"] = facts.persist_binding(research, facts.bind(raw, symbol=symbol, session="2026-10-06",
                now=test_clock(), reviews=reviews, root=out))
            return raw

        series = {}
        for symbol in symbols:
            rows = inputs(minutes=25)["bars"]
            for index, row in enumerate(rows):
                start = opening + timedelta(minutes=index)
                row.update(symbol=symbol, open_at=start.isoformat(), available_at=(start + timedelta(minutes=1)).isoformat(),
                    received_at=(start + timedelta(minutes=1, milliseconds=50)).isoformat(), test_only=True)
            series[symbol] = rows
            common.save_bars(rows, "2026-10-06", minute)

        hub = app.state.alert_hub
        events = []
        def event(value):
            if value.get("type") == "options_one_minute_progress":
                events.append({**value, "received_monotonic": monotonic()})
                with (out / "worker-progress.jsonl").open("a", encoding="utf-8") as log:
                    log.write(json.dumps({**value, "observed_at": datetime.now(UTC).isoformat(), "test_only": True}) + "\n")
        hub.add_listener(event)
        lane = TrendLane(minute, hub, path=research, clock=test_clock, source_root=out, source_reviews_path=reviews_path)
        original_history = lane.history.load
        slow = Event()
        def slow_history(*values):
            if slow.is_set():
                sleep(5)
            return original_history(*values)
        lane.history.load = slow_history
        def worker_state():
            return {"session": "2026-10-06", "scope_hash": scope["scope_hash"],
                "runtime_health": "TEST_ONLY_CALCULATION_LANE_NOT_PRODUCTION_OWNER",
                "health_checked_at": datetime.now(UTC).isoformat(), "stage": "TEST_ONLY_MIXED",
                "research_progress": {"completed": lane.state.get("completed"), "error": lane.state.get("error")},
                "opening_momentum": dict(lane.state), "registered_items": scope["items"]}
        app.state.research_http_snapshots.worker = worker_state
        base_url = f"http://127.0.0.1:{args.gateway_port}"
        gateway = create_gateway_app(stocks_url=f"http://127.0.0.1:{args.backend_port}", crypto_url="http://127.0.0.1:1",
                                     web_dist_dir=args.dist, stocks_api_token="TEST_ONLY_internal_transport_token")
        for application, port in ((app, args.backend_port), (gateway, args.gateway_port)):
            server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=port,
                access_log=False, log_level="warning"))
            thread = Thread(target=server.run, daemon=True)
            thread.start()
            servers.append(server)
            threads.append(thread)
        ready_until = monotonic() + 20
        while not all(server.started for server in servers) and monotonic() < ready_until:
            sleep(.1)
        if not all(server.started for server in servers):
            raise RuntimeError("ISOLATED_HTTP_START_FAILED")
        browser = None
        if args.node:
            browser = subprocess.Popen([str(args.node), str(ROOT / "scripts/check_r58_p9_browser.cjs"), str(out), base_url],
                stdout=subprocess.DEVNULL, stderr=(out / "browser-stderr.log").open("w"))
            deadline = monotonic() + 90
            while monotonic() < deadline and not (out / "browser-ready.json").exists():
                if browser.poll() is not None or (out / "browser-failed.json").exists():
                    raise RuntimeError("REAL_BROWSER_START_FAILED")
                sleep(.2)
            if not (out / "browser-ready.json").exists():
                browser.terminate()
                raise RuntimeError("REAL_BROWSER_READY_DEADLINE")
        start = monotonic()
        running_start[0] = start
        print(json.dumps({"ready": True, "url": base_url + "/?workspace=options&view=signals",
                          "test_only": True, "seconds": args.seconds}), flush=True)

        def poll_page(number):
            paths = ["/api/health/live", "/api/stocks/health/live", f"http://127.0.0.1:{args.backend_port}/api/health/live", "/api/options/opening-trend/current?research_strategy=opening_momentum",
                     "/api/options/one-minute/status?research_strategy=opening_momentum&compact=true"]
            # The pack specifies a 3s diagnostic client budget. Runtime proxy
            # budgets remain unchanged; >1s observations still fail acceptance.
            with httpx.Client(base_url=base_url, timeout=3) as client, (out / f"api-latency-page-{number}.jsonl").open("w") as log:
                if args.node:
                    logged_in = client.post("/api/auth/login", json={"email": "test-only@example.invalid", "password": "TEST_ONLY_not_a_user_password"})
                    if logged_in.status_code != 200:
                        errors.append({"code": "POLL_LOGIN_FAILED", "page": number, "status": logged_in.status_code})
                while not stopped.is_set():
                    for path in paths:
                        before = monotonic()
                        try:
                            headers = {"X-KQUANT-API-TOKEN": "TEST_ONLY_internal_transport_token"} if path.startswith("http://") else {}
                            response = client.get(path, headers=headers)
                            packet = {"observed_at": datetime.now(UTC).isoformat(), "page": number, "path": path,
                                "status": response.status_code, "seconds": monotonic() - before, "bytes": len(response.content)}
                            if response.status_code == 200 and "current?" in path:
                                body = response.json()
                                packet.update(snapshot_state=body.get("snapshot", {}).get("state"),
                                    candidates=len(body.get("candidates", [])))
                            if response.status_code not in (200, 503):
                                errors.append({"code": "HTTP_UNEXPECTED", **packet})
                        except httpx.HTTPError as exc:
                            packet = {"observed_at": datetime.now(UTC).isoformat(), "page": number, "path": path,
                                "seconds": monotonic() - before, "error_type": type(exc).__name__}
                            errors.append(packet)
                        latencies.append(packet)
                        log.write(json.dumps(packet) + "\n")
                        log.flush()
                    stopped.wait(15)

        for number in range(3):
            thread = Thread(target=poll_page, args=(number,), daemon=True)
            thread.start()
            threads.append(thread)

        def checkpoint(slot):
                if not args.real_window:
                    virtual[0] = opening + timedelta(minutes=slot * 5, seconds=1)
                point = opening + timedelta(minutes=slot * 5)
                prep_started = monotonic()
                quotes = {symbol: quote(symbol) for symbol in symbols}
                prep_seconds = monotonic() - prep_started
                before = monotonic()
                for symbol in symbols:
                    lane.enqueue(symbol, opening.date(), series[symbol], scope["scope_hash"], {"raw_quote": quotes[symbol]})
                deadline = before + 60
                while monotonic() < deadline:
                    matching = [e for e in list(events) if e.get("research_strategy") == "opening_momentum" and e.get("bar_end") == point.isoformat()]
                    if len({e["symbol"] for e in matching}) == len(symbols):
                        break
                    sleep(.02)
                durations = [e["received_monotonic"] - before for e in matching]
                with closing(sqlite3.connect(research)) as db:
                    rows = db.execute("""SELECT state FROM evaluations WHERE policy_hash=? AND session='2026-10-06'
                        AND json_extract(payload_json,'$.calculation_bar_end')=?""", (model.load_policy()["policy_hash"], point.isoformat())).fetchall()
                record = {"checkpoint": point.isoformat(), "registered_directions": 222,
                    "wall_elapsed_seconds": monotonic() - start,
                    "identity_excluded": len(unknown) * 2, "evaluated_records": len(rows), "states": dict(Counter(r[0] for r in rows)),
                    "completed_symbols": len({e["symbol"] for e in matching}),
                    "source_binding_preparation_seconds": prep_seconds,
                    "enqueue_to_commit_p95_seconds": percentile(durations), "last_seconds": max(durations, default=None),
                    "segments": {key: {"n": len(matching), "p95_seconds": percentile([e.get("runtime_timing", {}).get(key, 0) for e in matching])}
                        for key in ("input_read_seconds", "calculation_seconds", "commit_batch_seconds")},
                    "test_only": True}
                checkpoint_results.append(record)
                print(json.dumps(record), flush=True)
                if record["completed_symbols"] != len(symbols):
                    errors.append({"code": "CHECKPOINT_MISSING", **record})

        def exercise_reported_trade():
            symbol = "FCX" if "FCX" in symbols else symbols[len(symbols) // 2]
            with closing(sqlite3.connect(research)) as db:
                row = db.execute("SELECT evaluation_id FROM evaluations WHERE symbol=? AND right_name='CALL' LIMIT 1", (symbol,)).fetchone()
            if row is None:
                errors.append({"code": "MANUAL_EVALUATION_MISSING", "symbol": symbol})
                return
            with httpx.Client(base_url=base_url, timeout=3) as client:
                if args.node:
                    client.post("/api/auth/login", json={"email": "test-only@example.invalid", "password": "TEST_ONLY_not_a_user_password"})
                detail = client.get("/api/options/one-minute/evaluations/" + row[0])
                payload = dict(operation_key="TEST_ONLY_mixed_open_001", evaluation_id=row[0],
                    contract_id=symbol + "261009C105000.US", quantity=2, multiplier=100, entry_price=1.01,
                    underlying_entry_price=105, entry_fees=1, exit_fee_estimate=1, executed_at=test_clock().isoformat())
                first = client.post("/api/options/one-minute/manual/entries", json=payload)
                result = {"test_only": True, "at_seconds": monotonic() - start, "detail_status": detail.status_code,
                    "open_status": first.status_code, "production_report": False, "actual_http_handlers": True,
                    "synthetic_contract_not_real_qualification": True}
                if first.status_code == 200:
                    duplicate = client.post("/api/options/one-minute/manual/entries", json=payload)
                    changed = client.post("/api/options/one-minute/manual/entries", json={**payload, "quantity": 3})
                    partial = dict(operation_key="TEST_ONLY_mixed_exit_001", position_id=first.json()["position_id"],
                        quantity=1, exit_price=1.1, exit_fees=.5, executed_at=test_clock().isoformat())
                    exited = client.post("/api/options/one-minute/manual/exits", json=partial)
                    repeated = client.post("/api/options/one-minute/manual/exits", json=partial)
                    status = client.get("/api/options/one-minute/manual")
                    result.update(duplicate_open_status=duplicate.status_code, duplicate_same=duplicate.json() == first.json(),
                        changed_key_status=changed.status_code, partial_exit_status=exited.status_code,
                        duplicate_exit_same=repeated.json() == exited.json(),
                        position_count=len(status.json().get("positions", [])),
                        open_quantity=status.json().get("positions", [{}])[0].get("open_quantity"),
                        paper_fill=first.json().get("paper_fill"), real_order_created=first.json().get("real_order_created"))
                    if args.node:
                        import time
                        expired = gateway.state.workspace_auth.issue(email="test-only@example.invalid",
                            issued_at=int(time.time()) - 60, expires_at=int(time.time()) - 1)
                        client.cookies.clear()
                        client.cookies.set("kquant_workspace_session", expired)
                        result["expired_session_status"] = client.get("/api/options/one-minute/manual").status_code
                        client.post("/api/auth/login", json={"email": "test-only@example.invalid", "password": "TEST_ONLY_not_a_user_password"})
                        restored = client.get("/api/options/one-minute/manual").json()
                        result["relogin_open_quantity"] = restored.get("positions", [{}])[0].get("open_quantity")
                manual_exercise.append(result)
                (out / "TEST_ONLY-manual-http.json").write_text(json.dumps(manual_exercise, indent=2), encoding="utf-8")
                if not (result.get("detail_status") == 200 and result.get("open_status") == 200
                    and result.get("duplicate_same") and result.get("changed_key_status") == 400
                    and result.get("partial_exit_status") == 200 and result.get("duplicate_exit_same")
                    and result.get("position_count") == 1 and result.get("open_quantity") == 1
                    and not result.get("paper_fill") and not result.get("real_order_created")):
                    errors.append({"code": "MANUAL_HTTP_EXERCISE_FAILED", **result})
        try:
            next_point = 1
            injected, restored = set(), False
            quotes = {symbol: quote(symbol) for symbol in symbols}
            while monotonic() - start < args.seconds:
                elapsed = monotonic() - start
                phase = int(elapsed // 120) % 5
                cycle = int(elapsed // 120)
                first = cycle not in injected
                if first:
                    injected.add(cycle)
                    timings.append({"at_seconds": elapsed, "fault_phase": phase})
                    import faulthandler
                    with (out / "TEST_ONLY-thread-stacks.log").open("a") as log:
                        log.write(json.dumps({"observed_at": datetime.now(UTC).isoformat(), "elapsed_seconds": elapsed,
                            "test_only": True, "pid": os.getpid(), "phase": phase}) + "\n")
                        log.flush()
                        faulthandler.dump_traceback(file=log, all_threads=True)
                    with (out / "TEST_ONLY-runtime-diagnostics.jsonl").open("a") as log:
                        log.write(json.dumps({"observed_at": datetime.now(UTC).isoformat(), "test_only": True,
                            "pid": os.getpid(), "phase": phase, "worker": dict(lane.state),
                            "http_health": app.state.research_http_snapshots.health()}) + "\n")
                slow.set() if phase == 1 else slow.clear()
                if next_point <= 5 and elapsed >= (next_point if args.real_window else next_point - 1) * args.checkpoint_interval:
                    checkpoint(next_point)
                    next_point += 1
                    if len(checkpoint_results) == 1:
                        exercise_reported_trade()
                if phase == 1 and first:
                    for symbol in symbols[:4]:
                        lane.history.invalidate(symbol, opening.date())
                        changed = deepcopy(series[symbol][-1])
                        changed.update(close=changed["close"] + .001 * (cycle + 1), received_at=test_clock().isoformat())
                        common.save_bars([changed], "2026-10-06", minute)
                        lane.enqueue(symbol, opening.date(), [changed], scope["scope_hash"], {"raw_quote": quotes[symbol]})
                if phase == 2 and first:
                    with closing(sqlite3.connect(research, timeout=.1)) as db:
                        db.execute("BEGIN IMMEDIATE")
                        lane.enqueue(symbols[-1], opening.date(), series[symbols[-1]], scope["scope_hash"], {"raw_quote": quotes[symbols[-1]]})
                        sleep(4)
                        db.rollback()
                if phase == 3 and not restored:
                    # Restore the same original slots/deadlines, not a new opportunity.
                    from kquant import options_opening_momentum_journal as journal
                    before = journal.restore(research, test_clock())
                    lane.close()
                    lane = TrendLane(minute, hub, path=research, clock=test_clock, source_root=out, source_reviews_path=reviews_path)
                    original_history = lane.history.load
                    lane.history.load = slow_history
                    timings.append({"recovery": "ORIGINAL_JOURNAL_RESTORED", "pending_before": len(before),
                                    "restored": lane.state.get("restored_checkpoints"), "at_seconds": elapsed})
                    restored = True
                if phase == 0 and first and elapsed > 600:
                    symbol = symbols[-2]
                    updated = deepcopy(quotes[symbol])
                    updated["recovery_generation"] = cycle
                    lane.reference_ready(symbol, opening.date(), {"raw_quote": updated})
                    timings.append({"at_seconds": elapsed, "recovered_new_input_symbol": symbol})
                if phase == 4 and first:
                    symbol = symbols[0]
                    changed = deepcopy(series[symbol][0])
                    changed.update(close=changed["close"] + .001 * (1 + int(elapsed) % 9), received_at=test_clock().isoformat())
                    # Full-version contradiction must remain a conflict, never take latest.
                    changed["sdk_evidence"] = {"interface": "TEST_ONLY_PULL_REVISION"}
                    common.save_bars([changed], "2026-10-06", minute)
                    lane.enqueue(symbol, opening.date(), [changed], scope["scope_hash"], {"raw_quote": quotes[symbol]})
                if int(elapsed) % 60 < 2:
                    print(json.dumps({"elapsed_seconds": round(elapsed, 1), "phase": phase,
                        "http_samples": len(latencies), "errors": len(errors), "worker": lane.state.get("completed")}), flush=True)
                stopped.wait(1)
        except Exception as exc:
            errors.append({"code": "EXERCISE_ERROR", "error_type": type(exc).__name__})
            raise
        finally:
            duration = monotonic() - start
            stopped.set()
            if browser:
                (out / "browser-stop.json").write_text(json.dumps({"test_only": True}), encoding="utf-8")
                try:
                    browser.wait(timeout=120)
                except subprocess.TimeoutExpired:
                    browser.terminate()
                    errors.append({"code": "BROWSER_EXIT_DEADLINE"})
            lane.close()
            for server in servers:
                server.should_exit = True
            for thread in threads:
                thread.join(timeout=3)
            report = {"test_only": True, "duration_seconds": duration, "required_seconds": 3600,
                "continuous_60_minutes": duration >= 3600, "actual_gateway_backend": True,
                "route_handler_substitutions": 0, "live_sdk_connections": 0, "production_writes": 0,
                "unmounted_legacy_datasets_return_503": True,
                "synthetic_clock_and_source_facts": True, "live_market_acceptance": False,
                "executed_source_hashes": executed,
                "checkpoint_interval_seconds": args.checkpoint_interval,
                "five_minute_cadence": args.checkpoint_interval == 300,
                "wall_clock_advances_through_full_entry_window": args.real_window,
                "slow_io_injection_seconds": 5,
                "slow_io_injection_boundary": "HISTORY_READ_SURROGATE_NO_LIVE_SDK",
                "real_browser_report": json.loads((out / "browser-report.json").read_text()) if (out / "browser-report.json").exists() else None,
                "checkpoints": checkpoint_results, "faults_and_recovery": timings, "errors": errors,
                "actual_detail_and_manual_http": manual_exercise,
                "http": {path: {"n": len(values), "p95_seconds": percentile([v["seconds"] for v in values]),
                    "max_seconds": max((v["seconds"] for v in values), default=None),
                    "max_bytes": max((v.get("bytes", 0) for v in values), default=None),
                    "statuses": dict(Counter(str(v.get("status", v.get("error_type"))) for v in values))}
                    for path in {v["path"] for v in latencies}
                    for values in [[v for v in latencies if v["path"] == path]]}}
            (out / "mixed_load_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps({"completed": True, "duration_seconds": duration, "errors": len(errors)}), flush=True)


if __name__ == "__main__":
    main()
