import ast
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from kquant_crypto.candidate_metrics import DAY, evaluate_gates, fixed_cost_stress, summarize
from kquant_crypto.candidate_simulation_store import CandidateStore


def trade(i=0, pnl=20, r=2, symbol="BTCUSDT", mode="trend", day=0, **extra):
    return {"trade_id": str(i), "net_pnl": pnl, "net_r": r, "symbol": symbol,
            "mode": mode, "entry_time": day * DAY + 100, "exit_time": day * DAY + 200,
            "fees": 1, "risk_amount": 10, **extra}


def test_store_restart_dedup_and_checkpoints(tmp_path):
    path = tmp_path / "nested" / "candidate.sqlite"
    store = CandidateStore(path)
    metadata = {"config": {"b": 2, "a": 1}, "policy": {"version": "A"},
                "data_manifest": {"source": "test"}}
    store.create_run("r", metadata)
    store.create_run("r", metadata)
    state = {"status": "running", "positions": [{"symbol": "BTC"}],
             "checkpoints": {"BTC:5m": 123}, "custom": {"nested": [1, 2]}}
    event = {"symbol": "BTC", "reason": "closed_bar", "signal_time": 123}
    store.save("r", state, events=[event], trades=[trade()], equity=[{"time": 123, "equity": 9999}])
    restarted = CandidateStore(path)
    restarted.save("r", state, events=[event], trades=[trade()], equity=[{"time": 123.0, "equity": 9999}])
    assert restarted.load("r") == state
    restarted.save("r", {"status": "done", "checkpoints": {"BTC:5m": 456}})
    report = restarted.report_data("r")
    assert len(report["events"]) == len(report["trades"]) == len(report["equity"]) == 1
    assert len(report["events"][0]["event_id"]) == 64
    assert report["checkpoints"] == {"BTC:5m": 456}
    assert report["status"] == "done"
    assert all(len(report["metadata"][k]) == 64 for k in ("config_hash", "policy_hash", "data_manifest_hash"))
    assert report["metadata"]["order_submission"] is False
    assert restarted.list_runs()[0]["run_id"] == "r"


def test_atomic_rollback_and_no_trade_erasure(tmp_path):
    store = CandidateStore(tmp_path / "candidate.sqlite")
    store.create_run("r", {})
    store.save("r", {"checkpoints": {"x": 1}}, trades=[trade()])
    with pytest.raises(ValueError, match="conflicting"):
        store.save("r", {"checkpoints": {"x": 2}}, events=[{"event_id": "new"}],
                   trades=[trade(1), trade(pnl=999)])
    assert store.load("r") == {"checkpoints": {"x": 1}}
    assert len(store.report_data("r")["trades"]) == 1
    assert store.report_data("r")["events"] == []
    with pytest.raises(ValueError):
        store.save("r", {}, trades=[{"net_pnl": 0}])
    with pytest.raises(ValueError):
        store.save("r", {}, equity=[{"time": float("nan")}])


def test_run_identity_stop_and_isolation(tmp_path):
    store = CandidateStore(tmp_path / "candidate.sqlite")
    store.create_run("one", {"config": {"x": 1}})
    store.create_run("two", {})
    with pytest.raises(ValueError, match="different metadata"):
        store.create_run("one", {"config": {"x": 2}})
    store.create_run("external_hash", {"policy": {"database": "local"}, "policy_hash": "frozen-subset-hash"})
    hashes = store.report_data("external_hash")["metadata"]
    assert hashes["policy_hash"] == "frozen-subset-hash"
    assert len(hashes["policy_payload_hash"]) == 64
    with pytest.raises(ValueError, match="invariant"):
        store.create_run("bad", {"order_submission": True})
    store.request_stop("one")
    store.save("one", {"stop_requested": False})
    assert store.should_stop("one")
    assert not store.should_stop("two")
    for run in ("one", "two"):
        store.save(run, {}, trades=[trade()])
        assert len(store.report_data(run)["trades"]) == 1
    with pytest.raises(ValueError, match="another run"):
        store.save("one", {}, trades=[trade(run_id="two")])
    for method in (store.load, store.report_data, store.request_stop, store.should_stop):
        with pytest.raises(KeyError):
            method("absent")


def test_process_lock_contention_expiry_and_stop(tmp_path, monkeypatch):
    import kquant_crypto.candidate_simulation_store as module
    now = [100.0]
    monkeypatch.setattr(module.time, "time", lambda: now[0])
    a = CandidateStore(tmp_path / "candidate.sqlite")
    b = CandidateStore(a.path)
    a.create_run("r", {})
    with a.process_lock("r", lease_seconds=10):
        with pytest.raises(RuntimeError):
            b.acquire_lock("r")
        with pytest.raises(RuntimeError):
            b.save("r", {})
        b.request_stop("r")
        assert a.should_stop("r")
        a.save("r", {"value": 1})
        a.acquire_lock("r", lease_seconds=20)
        now[0] = 121
        with pytest.raises(RuntimeError, match="expired"):
            a.save("r", {})
        b.acquire_lock("r")
        with pytest.raises(RuntimeError):
            a.save("r", {})
    b.save("r", {"value": 2})  # Old owner's release did not delete the new lease.
    b.release_lock("r")
    a.save("r", {"value": 3})


def test_reject_original_database_and_no_forbidden_imports(tmp_path):
    path = tmp_path / "production.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE crypto_validation_runs (id TEXT)")
    with pytest.raises(ValueError, match="dedicated"):
        CandidateStore(path)
    import kquant_crypto.candidate_simulation_store as module
    tree = ast.parse(Path(module.__file__).read_text())
    imported = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any("store" in name or "execution" in name for name in imported if name)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("crypto_validation_runs",)]


def test_net_metrics_drawdowns_groups_and_exclusions():
    rows = [trade(0, 20, 2), trade(1, -10, -1, symbol="ETHUSDT", mode="range"),
            trade(2, 40, 2, symbol="ETHUSDT", mode="range"), trade(3, -30, -3)]
    # Explicit exit ordering, independent of input order.
    for i, row in enumerate(rows):
        row["exit_time"] += i
    report = summarize(list(reversed(rows)), [{"time": 0, "equity": 10000},
                                            {"time": 1, "equity": 11000},
                                            {"time": 2, "equity": 9900}])
    assert report["payoff"] == 1.5
    assert report["payoff_r"] == 1
    assert report["profit_factor"] == 1.5
    assert report["expectancy"] == 5
    assert report["expectancy_r"] == 0
    assert report["max_drawdown_pct"] == 10
    assert report["max_drawdown_r"] == 3
    assert report["by_mode"]["range"]["sample_count"] == 2
    assert report["by_symbol_mode"]["BTCUSDT"]["trend"]["net_pnl"] == -10
    assert report["exclude_best_symbol"]["excluded_symbol"] == "ETHUSDT"
    assert report["exclude_best_symbol"]["net_pnl"] == -10
    assert report["exclude_best_trade"]["excluded_trade_id"] == "2"
    assert report["exclude_best_trade"]["net_pnl"] == -20
    assert report["performance_status"] == "TARGET_NOT_MET"
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("rows", [[], [trade()], [trade(pnl=0, r=0)], [trade(pnl=-10, r=-1)]])
def test_boundary_samples_never_false_pass(rows):
    report = summarize(rows, [])
    assert report["payoff"] is None
    assert report["performance_status"] != "TARGET_MET"
    assert report["max_drawdown_pct"] is None
    if not rows or rows[0]["net_pnl"] >= 0:
        assert report["profit_factor"] is None
    json.dumps(report, allow_nan=False)


def test_synchronized_bootstrap_includes_empty_days_and_is_deterministic():
    rows = []
    for day in (0, 14, 35, 60, 83):
        rows += [trade(f"{day}a", 10, 1, day=day),
                 trade(f"{day}b", -10, -1, day=day, symbol="ETHUSDT")]
    equity = [{"time": 0, "equity": 10000}, {"time": 84 * DAY, "equity": 10000}]
    first = summarize(rows, equity)["bootstrap"]
    second = summarize(list(reversed(rows)), equity)["bootstrap"]
    assert first == second
    assert first["calendar_days"] == 84
    assert first["no_trade_days"] == 79
    assert first["interval_95"] == [0, 0]  # Cross-symbol hedges remain synchronized.
    assert first["complete_week_blocks"] == 12
    assert first["iterations"] == 2000
    assert not first["stable"]
    assert first["empty_replicates"] > 0
    assert not summarize(rows[:2], equity[:1])["bootstrap"]["stable"]


def test_fixed_cost_stress_frozen_risk_and_quote_spread():
    base = trade(entry_reference=100, exit_reference=110, q=2, fee_bps=10,
                 ohlcv_execution_cost_bps=5, base_unit_risk=4)
    result = fixed_cost_stress([base])
    expected = 2 * (109.89 - 100.1) - 2 * .002 * (109.89 + 100.1)
    assert result["available"]
    assert result["trades"][0]["net_pnl"] == pytest.approx(expected)
    assert result["trades"][0]["net_r"] == pytest.approx(expected / 8)
    assert not result["full_stress_replay"]
    quote = {**base, "execution_source": "quote", "quote_extra_slippage_bps": 2}
    result = fixed_cost_stress([quote])
    expected = 2 * (110 * .9996 - 100 * 1.0004) - 2 * .002 * (110 * .9996 + 100 * 1.0004)
    assert result["trades"][0]["net_pnl"] == pytest.approx(expected)
    assert base["net_pnl"] == 20
    assert not fixed_cost_stress([base, trade(1)])["available"]
    assert not fixed_cost_stress([{**base, "base_unit_risk": 0}])["available"]
    assert not fixed_cost_stress([])["available"]


def test_gates_require_external_evidence_and_full_stress():
    rows = []
    for i in range(240):
        win = i % 4 != 0
        rows.append(trade(i, 30 if win else -10, 3 if win else -1,
                          symbol="BTCUSDT" if i % 2 else "ETHUSDT",
                          mode="trend" if (i // 2) % 2 else "range", day=i // 2,
                          entry_reference=100, exit_reference=130 if win else 90,
                          q=1, fee_bps=10, ohlcv_execution_cost_bps=5, base_unit_risk=10))
    # Ensure each mode has winners and losers without making symbols independent units.
    for i, row in enumerate(rows):
        row["mode"] = "trend" if i < 120 else "range"
        row["symbol"] = "BTCUSDT" if (i // 4) % 2 else "ETHUSDT"
    result = summarize(rows, [{"time": 0, "equity": 10000}, {"time": 120 * DAY, "equity": 12000}])
    assert result["performance_status"] == "PERFORMANCE_UNPROVEN"
    evidence = {"unexposed_test": True, "policy_frozen": True, "data_continuous": True,
                "equity_complete": True, "full_stress_expectancy_r": 1}
    assert evaluate_gates(result, evidence)["status"] == "TARGET_MET"
    assert evaluate_gates(result, {**evidence, "unexposed_test": False})["status"] == "PERFORMANCE_UNPROVEN"
    assert evaluate_gates(result, {**evidence, "full_stress_expectancy_r": -1})["status"] == "TARGET_NOT_MET"
    assert evaluate_gates(result, {**evidence, "claimed_symbol_modes": [("SOLUSDT", "range")]})["status"] == "PERFORMANCE_UNPROVEN"


def test_invalid_numbers_and_equity_conflicts():
    with pytest.raises(ValueError):
        summarize([trade(net_r=float("nan"))], [])
    with pytest.raises(ValueError):
        summarize([], [], initial_cash=0)
    with pytest.raises(ValueError, match="conflicting equity"):
        summarize([], [{"time": 1, "equity": 10}, {"time": 1, "equity": 20}])
    with pytest.raises(ValueError, match="precedes"):
        summarize([trade(exit_time=0)], [])


def test_equity_timestamp_upsert_and_atomic_invalid_equity(tmp_path):
    store = CandidateStore(tmp_path / "candidate.sqlite")
    store.create_run("r", {})
    store.save("r", {}, equity=[{"time": 1, "equity": 9999, "open_positions": 1}])
    store.save("r", {"checkpoints": {"last": 1}}, equity=[
        {"time": 1, "equity": 9999, "open_positions": 0},
        {"time": 2, "equity": 10000, "open_positions": 0}])
    assert len(store.report_data("r")["equity"]) == 2
    assert store.report_data("r")["equity"][0]["open_positions"] == 0
    with pytest.raises(ValueError):
        store.save("r", {}, events=[{"event_id": "rolled-back"}], trades=[trade()],
                   equity=[{"time": 2, "equity": float("nan")}])
    report = store.report_data("r")
    assert report["events"] == report["trades"] == []
    assert report["checkpoints"] == {"last": 1}


@pytest.mark.parametrize("source,execution_cost", [("ohlcv", 5), ("quotes", 2)])
def test_concrete_portfolio_trade_contract(source, execution_cost):
    row = trade(mode="UP_TREND", entry_market_reference=100, exit_market_reference=110,
                quantity=2, entry_price=100.05, exit_price=109.945, entry_fee=.2001,
                base_unit_net_risk=5, execution_source=source, fee_bps=10,
                execution_cost_bps=execution_cost, cost_multiplier=1)
    result = fixed_cost_stress([row])
    assert result["available"]
    stressed = result["trades"][0]
    slip = execution_cost * 2 / 10000
    assert stressed["entry_price"] == pytest.approx(100 * (1 + slip))
    assert stressed["exit_price"] == pytest.approx(110 * (1 - slip))
    assert stressed["net_r"] == pytest.approx(stressed["net_pnl"] / row["risk_amount"])
    assert stressed["fee_bps"] == 20
    assert not fixed_cost_stress([stressed])["available"]
    report = summarize([row], [{"time": 0, "equity": 10000, "cash": 10000,
                              "open_positions": 0, "pending": 0}])
    assert report["gates"]["checks"]["trend.sample_count"]["observed"] == 1


def test_lock_is_enforced_across_python_processes(tmp_path):
    store = CandidateStore(tmp_path / "candidate.sqlite")
    store.create_run("r", {})
    script = """
import sys
from kquant_crypto.candidate_simulation_store import CandidateStore
store = CandidateStore(sys.argv[1])
for operation in (lambda: store.acquire_lock('r'), lambda: store.save('r', {}),
                  lambda: store.clear_stop('r')):
    try:
        operation()
    except RuntimeError:
        pass
    else:
        raise AssertionError('other process bypassed writer lock')
store.request_stop('r')
"""
    with store.process_lock("r"):
        process = subprocess.run([sys.executable, "-c", script, str(store.path)],
                                 env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
                                 capture_output=True, text=True, timeout=20)
        assert process.returncode == 0, process.stderr
        assert store.should_stop("r")


def test_unavailable_stress_and_nonfinite_external_evidence():
    assert not fixed_cost_stress([trade(costs=None)])["available"]
    report = summarize([trade()], [])
    gates = evaluate_gates(report, {"full_stress_expectancy_r": float("inf")})
    assert gates["checks"]["full_stress_expectancy_r"]["status"] == "INSUFFICIENT"
    assert gates["checks"]["unexposed_test"]["observed"] is None
    json.dumps(gates, allow_nan=False)


def test_clear_stop_requires_owned_live_lock_and_preserves_run(tmp_path, monkeypatch):
    import kquant_crypto.candidate_simulation_store as module
    now = [100.0]
    monkeypatch.setattr(module.time, "time", lambda: now[0])
    owner = CandidateStore(tmp_path / "candidate.sqlite")
    other = CandidateStore(owner.path)
    owner.create_run("r", {"policy_hash": "frozen"})
    owner.create_run("other", {})
    owner.save("r", {"status": "stopped", "checkpoints": {"last": 3}}, trades=[trade()])
    owner.request_stop("r")
    owner.request_stop("other")
    with pytest.raises(KeyError):
        owner.clear_stop("absent")
    with pytest.raises(RuntimeError, match="owned, unexpired"):
        owner.clear_stop("r")
    with owner.process_lock("r", lease_seconds=10):
        with pytest.raises(RuntimeError):
            other.clear_stop("r")
        with pytest.raises(RuntimeError):
            owner.clear_stop("other")
        assert owner.should_stop("r")
        before = owner.report_data("r")
        now[0] = 101
        owner.clear_stop("r")
        owner.clear_stop("r")  # Explicit resume is idempotent while the lease is owned.
        after = owner.report_data("r")
        assert not after["stop_requested"]
        assert after["updated_at"] == 101
        for key in ("state", "status", "metadata", "events", "trades", "equity", "checkpoints"):
            assert before[key] == after[key]
        other.request_stop("r")
        now[0] = 110
        with pytest.raises(RuntimeError):
            owner.clear_stop("r")
        assert owner.should_stop("r")
        other.acquire_lock("r")
        with pytest.raises(RuntimeError):
            owner.clear_stop("r")
        other.clear_stop("r")
    other.request_stop("r")
    other.clear_stop("r")  # Stale owner's context exit preserves the replacement lease.
    other.release_lock("r")
    with pytest.raises(RuntimeError):
        other.clear_stop("r")
    assert owner.should_stop("other")


def test_parent_attached_provenance_round_trips_without_mutation(tmp_path):
    store = CandidateStore(tmp_path / "candidate.sqlite")
    provenance = {"strategy_version": "candidate-v1", "policy_hash": "policy",
                  "data_manifest_hash": "manifest", "evidence_scope": "candidate_simulation",
                  "source_ids": ["quote-42", "quote-43"], "closed_bar_id": "BTC:5m:100",
                  "available_at": 101, "signal_time": 100}
    store.create_run("r", {"policy_hash": "policy", "data_manifest_hash": "manifest"})
    event = {**provenance, "event_id": "event-1"}
    row = {**trade(), **provenance}
    equity = {**provenance, "time": 200, "equity": 10020}
    store.save("r", {}, events=[event], trades=[row], equity=[equity])
    result = store.report_data("r")
    for key in ("events", "trades", "equity"):
        assert result[key][0]["run_id"] == "r"
        for field, value in provenance.items():
            assert result[key][0][field] == value
    assert "run_id" not in event and "run_id" not in row and "run_id" not in equity
    with pytest.raises(ValueError, match="conflicting"):
        store.save("r", {}, trades=[{**row, "source_ids": ["later-enrichment"]}])
