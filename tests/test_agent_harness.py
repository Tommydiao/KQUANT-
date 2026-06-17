from __future__ import annotations

from pathlib import Path
import sqlite3

from btc_eth_15m.__main__ import main
from btc_eth_15m.agent_harness.audit_log import AuditLogger
from btc_eth_15m.agent_harness.eval import AgentEvaluator
from btc_eth_15m.agent_harness.risk_manager import RiskConfig, RiskManager
from btc_eth_15m.agent_harness.runtime import default_runtime
from btc_eth_15m.agent_harness.state_store import StateStore
from btc_eth_15m.agent_harness.tool_base import READ_ONLY, ToolBase
from btc_eth_15m.agent_harness.tool_registry import ToolRegistry


def _runtime(tmp_path: Path):
    return default_runtime(tmp_path / "harness.sqlite3", tmp_path / "outputs")


def test_create_task(tmp_path):
    runtime = _runtime(tmp_path)

    task_id = runtime.create_task("noop", {"goal": "test"}, created_by="test")

    task = runtime.store.get_task(task_id)
    assert task is not None
    assert task["status"] == "created"
    assert task["payload"] == {"goal": "test"}
    assert runtime.store.list_audit_events(task_id)[0]["event_type"] == "task.created"


def test_run_noop_task(tmp_path):
    runtime = _runtime(tmp_path)
    task_id = runtime.create_task("noop", {})

    runtime.run_task(task_id)

    task = runtime.store.get_task(task_id)
    assert task["status"] == "completed"
    assert task["result"]["message"] == "noop completed"


def test_tool_registry_register_and_execute(tmp_path):
    store = StateStore(tmp_path / "harness.sqlite3")
    audit = AuditLogger(store)
    registry = ToolRegistry(store, audit)
    registry.register(EchoTool())

    result = registry.execute("echo", {"message": "hello"}, {"task_id": None, "store": store, "audit": audit})

    assert result == {"echo": "hello"}
    assert registry.list_tools()[0]["name"] == "echo"


def test_tool_call_audit_log(tmp_path):
    store = StateStore(tmp_path / "harness.sqlite3")
    audit = AuditLogger(store)
    registry = ToolRegistry(store, audit)
    registry.register(EchoTool())
    task_id = store.create_task("noop", {})["id"]

    registry.execute("echo", {"message": "hello"}, {"task_id": task_id, "store": store, "audit": audit})

    calls = store.list_tool_calls(task_id)
    events = store.list_audit_events(task_id)
    assert calls[0]["tool_name"] == "echo"
    assert calls[0]["status"] == "succeeded"
    assert "tool.called" in [event["event_type"] for event in events]
    assert "tool.succeeded" in [event["event_type"] for event in events]


def test_risk_manager_blocks_live_trading_by_default(tmp_path):
    store = StateStore(tmp_path / "harness.sqlite3")
    audit = AuditLogger(store)
    risk = RiskManager(store, audit, RiskConfig(live_trading_enabled=False))
    task_id = store.create_task("live_order", {})["id"]
    audit.record("task.created", task_id=task_id, message="created")

    result = risk.check_action(
        task_id=task_id,
        action_type="live_order",
        payload={"strategy_id": "s1", "notional": 10.0},
    )

    assert result["passed"] is False
    assert any("RULE-002" in violation for violation in result["violations"])
    assert any(event["event_type"] == "risk.rejected" for event in store.list_audit_events(task_id))


def test_approval_required_for_high_risk_action(tmp_path):
    runtime = _runtime(tmp_path)
    task_id = runtime.create_task("live_order", {"strategy_id": "s1", "request_live_order": True})

    runtime.run_task(task_id)

    status = runtime.get_task_status(task_id)
    assert status["task"]["status"] == "waiting_approval"
    assert status["pending_approvals"]
    assert status["pending_approvals"][0]["approval_type"] == "live_order"


def test_approval_approve_changes_status(tmp_path):
    runtime = _runtime(tmp_path)
    approval = runtime.approval_manager.create_request(
        task_id=None,
        approval_type="live_order",
        request_summary="test",
        risk_summary="test",
        payload={"risk_level": "write_high_risk"},
    )

    decided = runtime.approval_manager.approve(approval["id"], decided_by="test", reason="ok")

    assert decided["status"] == "approved"
    assert decided["decided_by"] == "test"


def test_approval_reject_blocks_task(tmp_path):
    runtime = _runtime(tmp_path)
    task_id = runtime.create_task("live_order", {"strategy_id": "s1", "request_live_order": True})
    runtime.run_task(task_id)
    approval_id = runtime.get_task_status(task_id)["pending_approvals"][0]["id"]

    runtime.approval_manager.reject(approval_id, decided_by="test", reason="too risky")
    runtime.resume_task(task_id)

    task = runtime.store.get_task(task_id)
    assert task["status"] == "failed"
    assert task["current_step"] == "approval_rejected"


def test_paper_order_created_without_live_exchange_call(tmp_path):
    runtime = _runtime(tmp_path)
    task_id = runtime.create_task(
        "paper_trade",
        {"symbols": ["BTCUSDT"], "strategy_id": "paper-strategy", "quantity": 0.01, "price": 100.0},
    )

    runtime.run_task(task_id)

    task = runtime.store.get_task(task_id)
    paper_order = task["result"]["paper_order"]["paper_order"]
    assert paper_order["strategy_id"] == "paper-strategy"
    assert paper_order["metadata_json"]["exchange_call"] is False


def test_end_to_end_dry_run_flow(tmp_path):
    runtime = _runtime(tmp_path)
    task_id = runtime.create_task(
        "dry_run",
        {"symbols": ["BTCUSDT", "ETHUSDT"], "strategy_id": "dry-run-strategy", "create_paper_order": True},
    )

    runtime.run_task(task_id)

    status = runtime.get_task_status(task_id)
    task = status["task"]
    assert task["status"] == "completed"
    assert task["result"]["market_data"]["source_type"] == "mock"
    assert task["result"]["backtest"]["strategy_id"] == "dry-run-strategy"
    assert task["result"]["risk_result"]["passed"] is True
    assert task["result"]["paper_order"]["exchange_call"] is False
    report_path = Path(task["result"]["report"]["report_path"])
    assert report_path.exists()


def test_live_market_data_tool_reads_public_btc_state(monkeypatch, tmp_path):
    runtime = _runtime(tmp_path)
    _record_kline(runtime.store.db_path, "BTCUSDT")
    monkeypatch.setattr(
        "btc_eth_15m.agent_harness.tools.safe_live_ticker",
        lambda symbol, timeout=4.0: {
            "ok": True,
            "symbol": symbol,
            "source_type": "public_live_market_data",
            "price": 61234.5,
            "price_change_pct_24h": -1.2,
            "error": None,
        },
    )

    result = runtime.registry.execute(
        "live_market_data",
        {"symbol": "BTCUSDT"},
        runtime._context("tool-test"),
    )

    assert result["source_type"] == "public_live_market_data"
    assert result["ticker"]["price"] == 61234.5
    assert result["kline_freshness"]["symbol"] == "BTCUSDT"
    assert result["kline_freshness"]["is_fresh"] is True


def test_btc_market_review_completes_without_default_paper_order(monkeypatch, tmp_path):
    runtime = _runtime(tmp_path)
    _record_kline(runtime.store.db_path, "BTCUSDT")
    monkeypatch.setattr(
        "btc_eth_15m.agent_harness.tools.safe_live_ticker",
        lambda symbol, timeout=4.0: {
            "ok": True,
            "symbol": symbol,
            "source_type": "public_live_market_data",
            "price": 61234.5,
            "price_change_pct_24h": -1.2,
            "error": None,
        },
    )
    task_id = runtime.create_task(
        "btc_market_review",
        {"symbols": ["BTCUSDT"], "strategy_id": "btc-live-review", "create_paper_order": False},
    )

    runtime.run_task(task_id)

    task = runtime.store.get_task(task_id)
    assert task["status"] == "completed"
    assert task["result"]["market_data"]["source_type"] == "public_live_market_data"
    assert task["result"]["risk_result"]["passed"] is True
    assert task["result"]["paper_order"] is None
    report_path = Path(task["result"]["report"]["report_path"])
    assert report_path.exists()
    assert "Market Data" in report_path.read_text(encoding="utf-8")
    assert _paper_order_count(runtime.store.db_path, task_id) == 0


def test_us_options_scan_completes_without_default_paper_order(monkeypatch, tmp_path):
    runtime = _runtime(tmp_path)

    def fake_options_worthiness_report(*, symbols=None, outputs_dir="outputs", source="live", timeout=8.0, max_chain_symbols=4):
        return {
            "generated_at": "2026-06-10T00:00:00+00:00",
            "source_type": "public_live_us_options",
            "module": "US Options Live Scanner v1",
            "symbols": symbols or ["AAPL"],
            "daily_candidates": [
                {
                    "symbol": "AAPL",
                    "scan_time": "2026-06-10T00:00:00+00:00",
                    "quote_updated_at": "2026-06-10T00:00:00+00:00",
                    "preferred_side": "call",
                    "data_quality": "live",
                    "momentum_score": 82.0,
                }
            ],
            "overall_recommendation": "OBSERVE",
            "evaluations": [
                {
                    "symbol": "AAPL",
                    "recommendation": "OBSERVE",
                    "best_contract": {
                        "option_symbol": "AAPL260717C00300000",
                        "total_score": 78.0,
                        "contract": {"underlying": "AAPL", "option_type": "call", "strike": 300, "dte": 37},
                    },
                }
            ],
            "provider_errors": [],
            "limitations": ["read-only test scanner"],
            "safety": {"broker_key_required": False, "order_submission_wired": False, "live_locked": True},
            "report_path": str(tmp_path / "outputs" / "options-worthiness-report.md"),
            "report_json_path": str(tmp_path / "outputs" / "options-worthiness-report.json"),
        }

    monkeypatch.setattr("btc_eth_15m.agent_harness.tools.options_worthiness_report", fake_options_worthiness_report)
    task_id = runtime.create_task(
        "us_options_scan",
        {"symbols": ["AAPL"], "strategy_id": "us-options-live-scanner", "create_paper_order": False},
    )

    runtime.run_task(task_id)

    task = runtime.store.get_task(task_id)
    assert task["status"] == "completed"
    assert task["result"]["scanner"]["source_type"] == "public_live_us_options"
    assert task["result"]["scanner"]["snapshot_id"].startswith("options-scan-")
    assert task["result"]["scanner"]["provider_error_count"] == 0
    assert task["result"]["data_audit"]["snapshot_id"] == task["result"]["scanner"]["snapshot_id"]
    assert "is_fresh" in task["result"]["data_audit"]["freshness"]
    assert task["result"]["data_audit"]["provider_status"]["provider_available"] is True
    assert task["result"]["scanner"]["daily_candidates"][0]["symbol"] == "AAPL"
    assert task["result"]["risk_result"]["passed"] is True
    assert task["result"]["paper_order"] is None
    assert Path(task["result"]["report"]["report_path"]).exists()
    report_md = Path(task["result"]["report"]["report_path"]).read_text(encoding="utf-8")
    assert "Data Freshness / Provider Status" in report_md
    assert task["result"]["scanner"]["snapshot_id"] in report_md
    assert _paper_order_count(runtime.store.db_path, task_id) == 0
    assert _options_scan_snapshot_count(runtime.store.db_path) == 1
    events = runtime.store.list_audit_events(task_id)
    assert "tool.called" in {event["event_type"] for event in events}
    assert any(event.get("tool_name") == "us_options_scanner" for event in events)


def test_us_options_scan_high_risk_payload_waits_for_approval(monkeypatch, tmp_path):
    runtime = _runtime(tmp_path)

    monkeypatch.setattr(
        "btc_eth_15m.agent_harness.tools.options_worthiness_report",
        lambda **kwargs: {
            "source_type": "public_live_us_options",
            "overall_recommendation": "OBSERVE",
            "evaluations": [],
            "provider_errors": [],
            "safety": {"live_locked": True},
        },
    )
    task_id = runtime.create_task(
        "us_options_scan",
        {"symbols": ["AAPL"], "request_live_order": True, "create_paper_order": False},
    )

    runtime.run_task(task_id)

    status = runtime.get_task_status(task_id)
    assert status["task"]["status"] == "waiting_approval"
    assert status["task"]["result"]["paper_order"] is None
    assert status["pending_approvals"]
    assert _paper_order_count(runtime.store.db_path, task_id) == 0


def test_list_tasks_returns_recent_tasks(tmp_path):
    runtime = _runtime(tmp_path)
    first = runtime.create_task("noop", {})
    second = runtime.create_task("btc_market_review", {"symbols": ["BTCUSDT"]})

    tasks = runtime.store.list_tasks(limit=2)

    assert [task["id"] for task in tasks] == [second, first]


def test_agent_eval_happy_path_passes(tmp_path):
    runtime = _runtime(tmp_path)
    result = AgentEvaluator(runtime).run_suite("safety_core")

    assert result["passed"] is True
    assert result["total_score"] >= 90
    assert result["safety_passed"] is True
    assert {case["case_name"] for case in result["cases"]} >= {
        "us_options_scan_happy_path",
        "us_options_scan_provider_unavailable",
        "us_options_contract_detail",
    }


def test_agent_eval_blocks_live_order(tmp_path):
    runtime = _runtime(tmp_path)
    result = AgentEvaluator(runtime).run_suite("safety_core")
    case = next(case for case in result["cases"] if case["case_name"] == "live_order_blocked")
    task = runtime.store.get_task(case["task_id"])

    assert case["passed"] is True
    assert task["status"] == "waiting_approval"
    assert runtime.approval_manager.pending(case["task_id"])


def test_agent_eval_fails_when_paper_order_created_by_default(tmp_path):
    runtime = _runtime(tmp_path)
    result = AgentEvaluator(runtime).run_suite(
        "safety_core",
        fault_injection={"default_no_paper_order_create_paper_order": True},
    )
    case = next(case for case in result["cases"] if case["case_name"] == "default_no_paper_order")

    assert result["passed"] is False
    assert result["safety_passed"] is False
    assert case["passed"] is False
    assert any("paper order" in failure for failure in case["failures"])


def test_agent_eval_records_case_scores(tmp_path):
    runtime = _runtime(tmp_path)
    result = AgentEvaluator(runtime).run_suite("safety_core")
    stored = runtime.store.get_agent_eval_run(result["id"], include_cases=True)

    assert stored["id"] == result["id"]
    assert stored["metadata"]["category_scores"]["safety"] == 25.0
    assert len(stored["cases"]) == 6
    assert all(case["category_scores"] for case in stored["cases"])


def test_agent_eval_writes_markdown_and_json_report(tmp_path):
    runtime = _runtime(tmp_path)
    result = AgentEvaluator(runtime).run_suite("safety_core")
    md_path = Path(result["report_path"])
    json_path = Path(result["report_json_path"])

    assert md_path.exists()
    assert json_path.exists()
    assert "Agent Eval Report" in md_path.read_text(encoding="utf-8")
    assert json_path.read_text(encoding="utf-8")


def test_agent_eval_cli_run(tmp_path, capsys):
    db_path = tmp_path / "cli.sqlite3"
    outputs_dir = tmp_path / "outputs"

    code = main(
        [
            "agent",
            "--db-path",
            str(db_path),
            "--outputs-dir",
            str(outputs_dir),
            "eval",
            "run",
            "--suite",
            "safety_core",
        ]
    )

    output = capsys.readouterr().out
    payload = __import__("json").loads(output)
    assert code == 0
    assert payload["passed"] is True
    assert payload["report_path"].endswith("-agent-eval.md")


def test_agent_eval_api_run_and_list(tmp_path):
    from btc_eth_15m.agent_harness.api import install_agent_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    install_agent_routes(app, db_path=tmp_path / "api.sqlite3", outputs_dir=tmp_path / "outputs")
    client = TestClient(app)

    created = client.post("/api/agent/evals/run", json={"suite": "safety_core"}).json()["eval"]
    listed = client.get("/api/agent/evals").json()["evals"]
    fetched = client.get(f"/api/agent/evals/{created['id']}").json()["eval"]

    assert created["passed"] is True
    assert listed[0]["id"] == created["id"]
    assert len(fetched["cases"]) == 6


class EchoTool(ToolBase):
    name = "echo"
    description = "Echo test tool."
    permission_level = READ_ONLY
    requires_approval = False

    def input_schema(self):
        return {"type": "object", "required": ["message"]}

    def execute(self, input_data, context):
        return {"echo": input_data["message"]}


def _record_kline(db_path: Path, symbol: str) -> None:
    from datetime import datetime, timezone

    opened_at = datetime.now(tz=timezone.utc).replace(second=0, microsecond=0)
    open_ms = int(opened_at.timestamp() * 1000)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS klines (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                open_time INTEGER NOT NULL,
                open_time_iso TEXT NOT NULL,
                close_time INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                quote_volume REAL NOT NULL,
                trades INTEGER NOT NULL,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY (symbol, interval, open_time)
            )
            """
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO klines (
                symbol, interval, open_time, open_time_iso, close_time,
                open, high, low, close, volume, quote_volume, trades, fetched_at
            ) VALUES (?, '15m', ?, ?, ?, 100, 101, 99, 100.5, 10, 1000, 20, ?)
            """,
            (symbol, open_ms, opened_at.isoformat(), open_ms + 899999, datetime.now(timezone.utc).isoformat()),
        )
        connection.commit()


def _paper_order_count(db_path: Path, task_id: str) -> int:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM paper_orders WHERE task_id = ?", (task_id,)).fetchone()
    return int(row[0] or 0)


def _options_scan_snapshot_count(db_path: Path) -> int:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM options_scan_snapshots").fetchone()
    return int(row[0] or 0)
