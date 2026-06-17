import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import yaml
import pandas as pd
from fastapi.testclient import TestClient

from btc_eth_15m.__main__ import main
from btc_eth_15m.config import AppConfig
from btc_eth_15m.data import FetchResult, connect, interval_to_millis, market_freshness
from btc_eth_15m.dashboard.app import create_app
from btc_eth_15m.dashboard.binance import BinanceCredentials, SymbolRules
from btc_eth_15m.dashboard.broker import BinanceFuturesBroker, BrokerError, PaperBroker, broker_for_mode
from btc_eth_15m.dashboard.models import OrderDraft
from btc_eth_15m.dashboard.risk import leverage_from_confidence, risk_gates
from btc_eth_15m.dashboard.signals import _mode_sync_healthy, _snapshot_from_row
from btc_eth_15m.dashboard.state import (
    dashboard_connection,
    daily_loss_used,
    daily_margin_used,
    latest_exchange_self_check,
    latest_exchange_self_check_summary,
    latest_exchange_sync,
    latest_exchange_sync_summary,
    latest_orders,
    now_iso,
    open_position_count,
    open_positions,
    record_exchange_self_check,
    record_exchange_sync,
    set_kill_switch,
)


def test_leverage_mapping_and_high_tier_gates():
    assert _leverage(0.59) == 7
    assert _leverage(0.60) == 10
    assert _leverage(0.75) == 12
    assert _leverage(0.85) == 15
    reduced = leverage_from_confidence(
        0.90,
        volatility_ok=False,
        drawdown_ok=True,
        order_sync_ok=True,
        position_sync_ok=True,
        min_leverage=7,
        max_leverage=15,
    )
    assert reduced.leverage == 12


def test_daily_loss_gate_blocks_at_exact_cap():
    config = AppConfig(symbols=["BTCUSDT"])

    gates = risk_gates(
        config,
        mode="paper",
        kill_switch=False,
        order_sync_ok=True,
        position_sync_ok=True,
        market_data_ok=True,
        api_error_ok=True,
        rate_limit_ok=True,
        open_margin_usdt=0.0,
        daily_margin_used_usdt=0.0,
        daily_loss_used_usdt=200.0,
    )

    gate = next(gate for gate in gates if gate.name == "daily_loss_cap")
    assert gate.passed is False
    assert gate.message == "Daily realized loss 200.00 / 200.00 USDT."


def test_margin_budget_gates_block_at_exact_cap():
    config = AppConfig(symbols=["BTCUSDT"])

    gates = risk_gates(
        config,
        mode="paper",
        kill_switch=False,
        order_sync_ok=True,
        position_sync_ok=True,
        market_data_ok=True,
        api_error_ok=True,
        rate_limit_ok=True,
        open_margin_usdt=50.0,
        daily_margin_used_usdt=50.0,
        daily_loss_used_usdt=0.0,
    )

    open_cap = next(gate for gate in gates if gate.name == "open_margin_cap")
    open_budget = next(gate for gate in gates if gate.name == "open_margin_budget")
    daily_cap = next(gate for gate in gates if gate.name == "daily_margin_cap")
    daily_budget = next(gate for gate in gates if gate.name == "daily_margin_budget")
    assert open_cap.passed is True
    assert open_budget.passed is False
    assert open_budget.message == "Open margin budget is exhausted: 50.00 / 50.00 USDT."
    assert daily_cap.passed is True
    assert daily_budget.passed is False
    assert daily_budget.message == "Daily margin budget is exhausted: 50.00 / 50.00 USDT."


def test_paper_broker_fills_order_and_opens_position(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    broker = PaperBroker(config)
    result = broker.submit_order_draft(_draft())

    assert result["status"] == "FILLED"
    orders = latest_orders(config.db_path)
    positions = open_positions(config.db_path)
    assert orders[0]["symbol"] == "BTCUSDT"
    assert orders[0]["leverage"] == 12
    assert positions[0]["symbol"] == "BTCUSDT"
    assert positions[0]["status"] == "OPEN"


def test_paper_broker_closes_position_and_writes_close_order(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    broker = PaperBroker(config)
    opened = broker.submit_order_draft(_draft())

    result = broker.close_position(opened["position_id"], reason="test")

    assert result["status"] == "CLOSED"
    assert open_positions(config.db_path) == []
    orders = latest_orders(config.db_path)
    assert orders[0]["id"].startswith("paper-close-")
    assert orders[0]["status"] == "FILLED"
    assert orders[0]["margin_usdt"] == 0.0
    assert daily_margin_used(config.db_path, "paper") == 25.0


def test_paper_broker_rejects_second_open_position_for_symbol(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    broker = PaperBroker(config)
    broker.submit_order_draft(_draft())

    try:
        broker.submit_order_draft(_draft())
    except BrokerError as exc:
        assert "Open position cap reached" in str(exc)
    else:
        raise AssertionError("Expected duplicate position rejection.")

    assert open_position_count(config.db_path, "paper", "BTCUSDT") == 1
    assert len(open_positions(config.db_path)) == 1


def test_paper_broker_rejects_after_daily_loss_cap_is_reached(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    broker = PaperBroker(config)
    opened = broker.submit_order_draft(_draft())
    with dashboard_connection(config.db_path) as connection:
        connection.execute("UPDATE dashboard_positions SET mark_price = ? WHERE id = ?", (0.0, opened["position_id"]))
        connection.commit()
    broker.close_position(opened["position_id"], reason="loss-cap-test")

    try:
        broker.submit_order_draft(_draft())
    except BrokerError as exc:
        assert "Daily loss cap reached" in str(exc)
    else:
        raise AssertionError("Expected daily loss cap rejection.")

    assert daily_loss_used(config.db_path, "paper") == 300.0
    assert open_positions(config.db_path) == []


def test_paper_broker_rejects_when_daily_loss_cap_is_exactly_reached(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    _record_closed_position_loss(config, mode="paper", loss_usdt=200.0)
    broker = PaperBroker(config)

    try:
        broker.submit_order_draft(_draft())
    except BrokerError as exc:
        assert "Daily loss cap reached: 200.00 / 200.00 USDT." in str(exc)
    else:
        raise AssertionError("Expected exact daily loss cap rejection.")

    assert daily_loss_used(config.db_path, "paper") == 200.0
    assert open_positions(config.db_path) == []


def test_paper_broker_rejects_stale_ready_draft_after_daily_margin_cap(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    _record_filled_order_margin(config, mode="paper", symbol="ETHUSDT", margin_usdt=50.0, order_id="paper-daily-cap")
    broker = PaperBroker(config)

    try:
        broker.submit_order_draft(_draft())
    except BrokerError as exc:
        assert "Daily margin cap would be exceeded: 75.00 / 50.00 USDT." in str(exc)
    else:
        raise AssertionError("Expected daily margin cap rejection.")

    assert daily_margin_used(config.db_path, "paper") == 50.0
    assert open_positions(config.db_path) == []


def test_paper_broker_rejects_stale_ready_draft_after_open_margin_cap(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    _record_open_position_margin(config, mode="paper", symbol="ETHUSDT", margin_usdt=50.0, position_id="pos-open-cap")
    broker = PaperBroker(config)

    try:
        broker.submit_order_draft(_draft())
    except BrokerError as exc:
        assert "Open margin cap would be exceeded: 75.00 / 50.00 USDT." in str(exc)
    else:
        raise AssertionError("Expected open margin cap rejection.")

    assert len(open_positions(config.db_path)) == 1


def test_paper_broker_rejects_stale_ready_draft_after_kill_switch(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    set_kill_switch(config.db_path, True, reason="test")
    broker = PaperBroker(config)

    try:
        broker.submit_order_draft(_draft())
    except BrokerError as exc:
        assert "Kill switch is active." in str(exc)
    else:
        raise AssertionError("Expected kill-switch rejection.")

    assert open_positions(config.db_path) == []
    assert latest_orders(config.db_path) == []


def test_paper_broker_rejects_leverage_above_strategy_limit(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    broker = PaperBroker(config)
    try:
        broker.submit_order_draft(_draft(), leverage=15)
    except BrokerError as exc:
        assert "strategy-approved" in str(exc)
    else:
        raise AssertionError("Expected leverage rejection.")


def test_symbol_rules_round_and_validate_market_order():
    rules = _rules(step_size="0.001", min_qty="0.001", min_notional="100")

    rounded = rules.round_quantity(Decimal("0.123456"))
    assert rounded == Decimal("0.123")
    assert rules.validate_market_order(rounded, Decimal("1000")) == []
    assert rules.validate_market_order(Decimal("0.000"), Decimal("1000"))
    assert rules.validate_market_order(Decimal("0.050"), Decimal("100"))


def test_testnet_order_plan_sets_leverage_then_test_order(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    _record_fresh_exchange_sync(config, mode="testnet")
    _record_fresh_kline(config)
    broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
    fake = FakeBinanceClient()
    broker.credentials = BinanceCredentials("key", "secret")
    broker.client = fake

    result = broker.submit_order_draft(_draft(mode="testnet"), leverage=12)

    assert result["status"] == "TEST_ORDER_ACCEPTED"
    assert result["order_plan"]["rounded_quantity"] == "3"
    assert fake.posts[0][0] == "/fapi/v1/leverage"
    assert fake.posts[0][1] == {"symbol": "BTCUSDT", "leverage": 12}
    assert fake.posts[1][0] == "/fapi/v1/order/test"
    assert fake.posts[1][1]["quantity"] == "3"


def test_testnet_order_plan_rejects_exchange_rule_failure(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    _record_fresh_exchange_sync(config, mode="testnet")
    _record_fresh_kline(config)
    broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
    fake = FakeBinanceClient(min_notional="500")
    broker.credentials = BinanceCredentials("key", "secret")
    broker.client = fake

    try:
        broker.submit_order_draft(_draft(mode="testnet"), leverage=12)
    except BrokerError as exc:
        assert "minNotional" in str(exc)
    else:
        raise AssertionError("Expected exchange rule validation failure.")


def test_testnet_broker_rejects_blocked_draft_before_exchange_calls(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    _record_fresh_exchange_sync(config, mode="testnet")
    broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
    fake = FakeBinanceClient()
    broker.credentials = BinanceCredentials("key", "secret")
    broker.client = fake

    try:
        broker.submit_order_draft(
            _draft(mode="testnet", status="blocked", blocked_reasons=["Position sync is not healthy."]),
            leverage=12,
        )
    except BrokerError as exc:
        assert "Order draft is blocked" in str(exc)
    else:
        raise AssertionError("Expected blocked draft rejection.")

    assert fake.posts == []


def test_testnet_broker_rejects_mode_mismatch_before_exchange_calls(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    _record_fresh_exchange_sync(config, mode="testnet")
    broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
    fake = FakeBinanceClient()
    broker.credentials = BinanceCredentials("key", "secret")
    broker.client = fake

    try:
        broker.submit_order_draft(_draft(mode="paper"), leverage=12)
    except BrokerError as exc:
        assert "does not match broker mode" in str(exc)
    else:
        raise AssertionError("Expected draft mode mismatch rejection.")

    assert fake.posts == []


def test_testnet_broker_rejects_missing_sync_before_exchange_calls(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
    fake = FakeBinanceClient()
    broker.credentials = BinanceCredentials("key", "secret")
    broker.client = fake

    try:
        broker.submit_order_draft(_draft(mode="testnet"), leverage=12)
    except BrokerError as exc:
        assert "Testnet sync snapshot has not passed." in str(exc)
    else:
        raise AssertionError("Expected missing sync rejection.")

    assert fake.gets == []
    assert fake.posts == []


def test_testnet_broker_rejects_missing_self_check_before_exchange_calls(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    record_exchange_sync(
        config.db_path,
        {
            "mode": "testnet",
            "passed": True,
            "synced_at": now_iso(),
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "account_summary": {"availableBalance": "1000"},
            "positions": [],
            "orders": [],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        },
    )
    broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
    fake = FakeBinanceClient()
    broker.credentials = BinanceCredentials("key", "secret")
    broker.client = fake

    try:
        broker.submit_order_draft(_draft(mode="testnet"), leverage=12)
    except BrokerError as exc:
        assert "Testnet self-check has not passed." in str(exc)
    else:
        raise AssertionError("Expected missing self-check rejection.")

    assert fake.gets == []
    assert fake.posts == []


def test_testnet_broker_rejects_stale_self_check_before_exchange_calls(tmp_path):
    config = AppConfig(
        symbols=["BTCUSDT"],
        db_path=tmp_path / "market.sqlite3",
        exchange_self_check_max_age_seconds=60,
    )
    record_exchange_sync(
        config.db_path,
        {
            "mode": "testnet",
            "passed": True,
            "synced_at": now_iso(),
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "account_summary": {"availableBalance": "1000"},
            "positions": [],
            "orders": [],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        },
    )
    record_exchange_self_check(
        config.db_path,
        {
            "mode": "testnet",
            "passed": True,
            "checked_at": _seconds_ago(120),
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        },
    )
    broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
    fake = FakeBinanceClient()
    broker.credentials = BinanceCredentials("key", "secret")
    broker.client = fake

    try:
        broker.submit_order_draft(_draft(mode="testnet"), leverage=12)
    except BrokerError as exc:
        assert "Testnet self-check is stale." in str(exc)
    else:
        raise AssertionError("Expected stale self-check rejection.")

    assert fake.gets == []
    assert fake.posts == []


def test_testnet_broker_rejects_kill_switch_before_exchange_calls(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    set_kill_switch(config.db_path, True, reason="test")
    broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
    fake = FakeBinanceClient()
    broker.credentials = BinanceCredentials("key", "secret")
    broker.client = fake

    try:
        broker.submit_order_draft(_draft(mode="testnet"), leverage=12)
    except BrokerError as exc:
        assert "Kill switch is active." in str(exc)
    else:
        raise AssertionError("Expected kill-switch rejection.")

    assert fake.gets == []
    assert fake.posts == []


def test_testnet_broker_rejects_existing_exchange_position_before_order_calls(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    _record_fresh_exchange_sync(config, mode="testnet")
    _record_fresh_kline(config)
    broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
    fake = FakeBinanceClient(position_rows=[{"symbol": "BTCUSDT", "positionAmt": "0.01"}])
    broker.credentials = BinanceCredentials("key", "secret")
    broker.client = fake

    try:
        broker.submit_order_draft(_draft(mode="testnet"), leverage=12)
    except BrokerError as exc:
        assert "Open position cap reached" in str(exc)
    else:
        raise AssertionError("Expected existing position rejection.")

    assert fake.posts == []


def test_testnet_broker_rejects_stale_market_before_exchange_calls(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    _record_fresh_exchange_sync(config, mode="testnet")
    broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
    fake = FakeBinanceClient()
    broker.credentials = BinanceCredentials("key", "secret")
    broker.client = fake

    try:
        broker.submit_order_draft(_draft(mode="testnet"), leverage=12)
    except BrokerError as exc:
        assert "Market data is stale or missing for BTCUSDT." in str(exc)
    else:
        raise AssertionError("Expected stale-market rejection.")

    assert fake.gets == []
    assert fake.posts == []


def test_testnet_broker_rejects_daily_loss_cap_before_order_calls(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    _record_fresh_exchange_sync(config, mode="testnet")
    paper = PaperBroker(config)
    opened = paper.submit_order_draft(_draft())
    with dashboard_connection(config.db_path) as connection:
        connection.execute(
            "UPDATE dashboard_positions SET mode = 'testnet', mark_price = ? WHERE id = ?",
            (0.0, opened["position_id"]),
        )
        connection.execute("UPDATE dashboard_orders SET mode = 'testnet' WHERE id = ?", (opened["order_id"],))
        connection.commit()
    paper.mode = "testnet"
    paper.close_position(opened["position_id"], reason="loss-cap-test")
    broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
    fake = FakeBinanceClient()
    broker.credentials = BinanceCredentials("key", "secret")
    broker.client = fake

    try:
        broker.submit_order_draft(_draft(mode="testnet"), leverage=12)
    except BrokerError as exc:
        assert "Daily loss cap reached" in str(exc)
    else:
        raise AssertionError("Expected daily loss cap rejection.")

    assert fake.posts == []


def test_testnet_broker_rejects_daily_margin_cap_before_order_calls(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    _record_fresh_exchange_sync(config, mode="testnet")
    _record_filled_order_margin(config, mode="testnet", symbol="ETHUSDT", margin_usdt=50.0, order_id="testnet-daily-cap")
    broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
    fake = FakeBinanceClient()
    broker.credentials = BinanceCredentials("key", "secret")
    broker.client = fake

    try:
        broker.submit_order_draft(_draft(mode="testnet"), leverage=12)
    except BrokerError as exc:
        assert "Daily margin cap would be exceeded: 75.00 / 50.00 USDT." in str(exc)
    else:
        raise AssertionError("Expected daily margin cap rejection.")

    assert fake.posts == []


def test_testnet_self_check_reports_sync_and_time(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
    fake = FakeBinanceClient()
    broker.credentials = BinanceCredentials("key", "secret")
    broker.client = fake

    payload = broker.self_check()

    assert payload["passed"] is True
    assert payload["credentials_configured"] is True
    assert payload["base_url"] == "https://example.test"
    checks = {check["name"]: check for check in payload["checks"]}
    assert checks["server_time"]["passed"] is True
    assert "2 assets" in checks["account"]["message"]
    assert "0 open positions" in checks["positions"]["message"]
    assert checks["open_orders"]["passed"] is True
    assert checks["user_data_stream"]["passed"] is True
    assert fake.user_stream_starts == 1
    assert "hidden-test-listen-key" not in str(payload)
    assert payload["symbol_rules"][0]["symbol"] == "BTCUSDT"


def test_testnet_status_uses_persisted_sync_without_signed_request(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
    fake = FakeBinanceClient()
    broker.credentials = BinanceCredentials("key", "secret")
    broker.client = fake

    payload = broker.status()

    assert payload["connected"] is False
    assert payload["order_submission_enabled"] is False
    assert payload["message"] == "No exchange self-check has been recorded."
    assert fake.gets == []

    _record_fresh_exchange_sync(config, mode="testnet")

    payload = broker.status()

    assert payload["connected"] is True
    assert payload["order_submission_enabled"] is True
    assert payload["message"] == "Binance USD-M Futures sync is fresh; test-order rehearsal is available."
    assert fake.gets == []


def test_status_reports_missing_self_check_when_sync_exists(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    db_path = tmp_path / "market.sqlite3"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(db_path),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )
    record_exchange_sync(
        db_path,
        {
            "mode": "testnet",
            "passed": True,
            "synced_at": now_iso(),
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "account_summary": {"availableBalance": "1000"},
            "positions": [],
            "orders": [],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        },
    )
    fake = FakeBinanceClient()

    def fake_broker_for_mode(config, mode):
        if mode != "testnet":
            return broker_for_mode(config, mode)
        broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
        broker.credentials = BinanceCredentials("key", "secret")
        broker.client = fake
        return broker

    monkeypatch.setattr("btc_eth_15m.dashboard.app.broker_for_mode", fake_broker_for_mode)
    client = TestClient(create_app(config_path))

    status = client.get("/api/status?mode=testnet").json()

    assert status["broker"]["broker"] == "alpaca"
    assert status["broker"]["mode"] == "paper"
    assert status["broker"]["live_order_submission_enabled"] is False
    assert status["legacy_crypto"]["broker"]["connected"] is False
    assert status["legacy_crypto"]["broker"]["message"] == "No exchange self-check has been recorded."
    assert status["last_self_check"] is None
    assert status["last_sync"]["passed"] is True
    assert any(gate["name"] == "exchange_self_check" and not gate["passed"] for gate in status["risk_gates"])
    assert any(gate["name"] == "order_sync" and gate["passed"] for gate in status["risk_gates"])
    assert fake.gets == []
    assert fake.posts == []


def test_testnet_positions_and_orders_use_persisted_sync_without_signed_requests(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    db_path = tmp_path / "market.sqlite3"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(db_path),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )
    record_exchange_sync(
        db_path,
        {
            "mode": "testnet",
            "passed": True,
            "synced_at": now_iso(),
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "account_summary": {"availableBalance": "1000"},
            "positions": [{"id": "sync-position", "mode": "testnet", "symbol": "BTCUSDT", "status": "OPEN"}],
            "orders": [{"id": "sync-order", "mode": "testnet", "symbol": "BTCUSDT", "status": "NEW"}],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        },
    )
    fake = FakeBinanceClient(
        position_rows=[
            {
                "symbol": "BTCUSDT",
                "positionAmt": "0.01",
                "leverage": "12",
                "isolatedMargin": "10",
                "notional": "120",
                "entryPrice": "100",
                "markPrice": "101",
                "unRealizedProfit": "1",
            }
        ]
    )

    def fake_broker_for_mode(config, mode):
        if mode != "testnet":
            return broker_for_mode(config, mode)
        broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
        broker.credentials = BinanceCredentials("key", "secret")
        broker.client = fake
        return broker

    monkeypatch.setattr("btc_eth_15m.dashboard.app.broker_for_mode", fake_broker_for_mode)
    client = TestClient(create_app(config_path))

    positions = client.get("/api/positions?mode=testnet").json()["positions"]
    orders = client.get("/api/orders?mode=testnet").json()["orders"]

    assert positions == [{"id": "sync-position", "mode": "testnet", "symbol": "BTCUSDT", "status": "OPEN"}]
    assert orders == [{"id": "sync-order", "mode": "testnet", "symbol": "BTCUSDT", "status": "NEW"}]
    assert fake.gets == []


def test_testnet_self_check_redacts_sensitive_endpoint_errors(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
    broker.credentials = BinanceCredentials("key", "secret")
    broker.client = FailingBinanceClient()

    payload = broker.self_check()

    assert payload["passed"] is False
    rendered = str(payload)
    assert "https://example.test/fapi/v3/account?<redacted>" in rendered
    assert "signature=secret" not in rendered
    assert "listenKey=abc123" not in rendered
    assert "timestamp=1" not in rendered


def test_exchange_self_check_api_records_summary(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    db_path = tmp_path / "market.sqlite3"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(db_path),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )
    fake = FakeBinanceClient()

    def fake_broker_for_mode(config, mode):
        if mode != "testnet":
            return broker_for_mode(config, mode)
        broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
        broker.credentials = BinanceCredentials("key", "secret")
        broker.client = fake
        return broker

    monkeypatch.setattr("btc_eth_15m.dashboard.app.broker_for_mode", fake_broker_for_mode)
    client = TestClient(create_app(config_path))

    response = client.post("/api/exchange/self-check?mode=testnet")

    assert response.status_code == 200
    payload = response.json()
    assert payload["passed"] is True
    assert payload["last_self_check"]["passed"] is True
    assert payload["last_self_check"]["is_fresh"] is True
    assert fake.user_stream_starts == 1
    stored = client.get("/api/exchange/last-self-check?mode=testnet").json()["self_check"]
    assert stored["passed"] is True
    assert stored["checks"][0]["name"] == "server_time"
    summary = latest_exchange_self_check_summary(db_path, "testnet", max_age_seconds=900)
    assert summary["passed"] is True
    logs = client.get("/api/logs?limit=1").json()["events"]
    assert logs[0]["level"] == "self-check"
    assert logs[0]["message"] == "Exchange self-check: testnet"


def test_exchange_self_check_get_is_passive(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    db_path = tmp_path / "market.sqlite3"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(db_path),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )
    record_exchange_self_check(
        db_path,
        {
            "mode": "testnet",
            "passed": True,
            "checked_at": now_iso(),
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        },
    )
    fake = FakeBinanceClient()

    def fake_broker_for_mode(config, mode):
        if mode != "testnet":
            return broker_for_mode(config, mode)
        broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
        broker.credentials = BinanceCredentials("key", "secret")
        broker.client = fake
        return broker

    monkeypatch.setattr("btc_eth_15m.dashboard.app.broker_for_mode", fake_broker_for_mode)
    client = TestClient(create_app(config_path))

    response = client.get("/api/exchange/self-check?mode=testnet")

    assert response.status_code == 200
    payload = response.json()
    assert payload["self_check"]["passed"] is True
    assert payload["last_self_check"]["passed"] is True
    assert fake.gets == []
    assert fake.posts == []
    assert fake.user_stream_starts == 0


def test_exchange_sync_and_readiness_report_redact_sensitive_sync_errors(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )

    def fake_broker_for_mode(config, mode):
        if mode != "testnet":
            return broker_for_mode(config, mode)
        broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
        broker.credentials = BinanceCredentials("key", "secret")
        broker.client = FailingBinanceClient()
        return broker

    monkeypatch.setattr("btc_eth_15m.dashboard.app.broker_for_mode", fake_broker_for_mode)
    monkeypatch.setattr("btc_eth_15m.dashboard.app.market_freshness", lambda config: [_fresh_market("BTCUSDT")])
    client = TestClient(create_app(config_path))

    sync = client.post("/api/exchange/sync?mode=testnet").json()
    report = client.post("/api/readiness/report").json()
    report_text = Path(report["path"]).read_text(encoding="utf-8")

    rendered = json.dumps({"sync": sync, "report": report, "report_text": report_text}, ensure_ascii=False)
    assert "https://example.test/fapi/v3/account?<redacted>" in rendered
    assert "signature=secret" not in rendered
    assert "listenKey=abc123" not in rendered
    assert "recvWindow=5000" not in rendered


def test_testnet_sync_snapshot_is_read_only(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
    fake = FakeBinanceClient()
    broker.credentials = BinanceCredentials("key", "secret")
    broker.client = fake

    payload = broker.sync_snapshot()

    assert payload["passed"] is True
    assert payload["account_summary"]["availableBalance"] == "1000"
    assert payload["account_summary"]["asset_count"] == 2
    assert payload["positions"] == []
    assert payload["orders"] == []
    assert fake.posts == []
    assert fake.user_stream_starts == 0
    assert "user_data_stream" not in {check["name"] for check in payload["checks"]}


def test_exchange_sync_api_records_second_stage_snapshot_failure(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    db_path = tmp_path / "market.sqlite3"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(db_path),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )
    fake = AccountSnapshotFailingBinanceClient()

    def fake_broker_for_mode(config, mode):
        if mode != "testnet":
            return broker_for_mode(config, mode)
        broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
        broker.credentials = BinanceCredentials("key", "secret")
        broker.client = fake
        return broker

    monkeypatch.setattr("btc_eth_15m.dashboard.app.broker_for_mode", fake_broker_for_mode)
    client = TestClient(create_app(config_path))

    response = client.post("/api/exchange/sync?mode=testnet")

    assert response.status_code == 200
    payload = response.json()
    assert payload["passed"] is False
    assert payload["account_summary"] is None
    assert payload["positions"] == []
    assert payload["orders"] == []
    assert fake.user_stream_starts == 0
    assert "snapshot_fetch" in {check["name"] for check in payload["checks"]}
    assert payload["last_sync"]["passed"] is False
    assert payload["last_sync"]["failed_checks"] == ["snapshot_fetch"]
    last_sync = client.get("/api/exchange/last-sync?mode=testnet").json()["sync"]
    assert last_sync["passed"] is False
    assert last_sync["account_summary"] is None
    rendered = json.dumps({"payload": payload, "last_sync": last_sync}, ensure_ascii=False)
    assert "https://example.test/fapi/v3/account?<redacted>" in rendered
    assert "signature=secret" not in rendered
    assert "listenKey=abc123" not in rendered
    assert "recvWindow=5000" not in rendered


def test_exchange_sync_get_is_passive(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    db_path = tmp_path / "market.sqlite3"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(db_path),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )
    record_exchange_sync(
        db_path,
        {
            "mode": "testnet",
            "passed": True,
            "synced_at": now_iso(),
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "account_summary": {"availableBalance": "1000"},
            "positions": [{"id": "sync-position", "mode": "testnet", "symbol": "BTCUSDT"}],
            "orders": [{"id": "sync-order", "mode": "testnet", "symbol": "BTCUSDT"}],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        },
    )
    fake = FakeBinanceClient()

    def fake_broker_for_mode(config, mode):
        if mode != "testnet":
            return broker_for_mode(config, mode)
        broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
        broker.credentials = BinanceCredentials("key", "secret")
        broker.client = fake
        return broker

    monkeypatch.setattr("btc_eth_15m.dashboard.app.broker_for_mode", fake_broker_for_mode)
    client = TestClient(create_app(config_path))

    response = client.get("/api/exchange/sync?mode=testnet")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sync"]["passed"] is True
    assert payload["last_sync"]["passed"] is True
    assert payload["last_sync"]["position_count"] == 1
    assert payload["last_sync"]["order_count"] == 1
    assert fake.gets == []
    assert fake.posts == []


def test_readiness_uses_persisted_self_check_without_running_self_check(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    db_path = tmp_path / "market.sqlite3"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(db_path),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
                "live_enabled": True,
            }
        ),
        encoding="utf-8",
    )
    record_exchange_sync(
        db_path,
        {
            "mode": "testnet",
            "passed": True,
            "synced_at": now_iso(),
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "account_summary": {"availableBalance": "1000"},
            "positions": [],
            "orders": [],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        },
    )

    class NoSelfCheckBroker:
        def __init__(self, mode):
            self.mode = mode

        def status(self):
            return {
                "mode": self.mode,
                "connected": True,
                "order_sync_ok": True,
                "position_sync_ok": True,
                "exchange_rules_ok": True,
                "order_submission_enabled": self.mode != "live",
                "message": f"{self.mode} ok",
            }

        def self_check(self):
            raise AssertionError("readiness must use persisted self-check state")

    monkeypatch.setattr("btc_eth_15m.dashboard.app.broker_for_mode", lambda config, mode: NoSelfCheckBroker(mode))
    monkeypatch.setattr("btc_eth_15m.dashboard.app.market_freshness", lambda config: [_fresh_market("BTCUSDT")])
    client = TestClient(create_app(config_path))

    readiness = client.get("/api/readiness").json()
    report = client.post("/api/readiness/report").json()
    report_text = Path(report["path"]).read_text(encoding="utf-8")

    assert readiness["ready_for_live"] is False
    assert "Binance Testnet self-check has not passed." in readiness["blockers"]
    assert readiness["testnet_self_check"] is None
    assert readiness["testnet_self_check_summary"] is None
    assert "- none" in report_text


def test_exchange_sync_post_api_records_summary(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("btc_eth_15m.dashboard.binance.BinanceFuturesClient.server_time_delta_ms", lambda self: 42)
    client = TestClient(create_app(config_path))

    response = client.post("/api/exchange/sync?mode=testnet")

    assert response.status_code == 200
    assert response.json()["passed"] is False
    assert response.json()["last_sync"]["passed"] is False
    last_sync = client.get("/api/exchange/last-sync?mode=testnet").json()["sync"]
    assert last_sync["passed"] is False
    logs = client.get("/api/logs?limit=1").json()["events"]
    assert logs[0]["level"] == "sync"
    assert logs[0]["message"] == "Exchange sync snapshot: testnet"


def test_exchange_sync_persistence_summarizes_without_listen_key(tmp_path):
    db_path = tmp_path / "market.sqlite3"
    record_exchange_sync(
        db_path,
        {
            "mode": "testnet",
            "passed": True,
            "synced_at": "2026-06-02T00:00:00+00:00",
            "checks": [{"name": "user_data_stream", "passed": True, "message": "listenKey acquired; value hidden."}],
            "account_summary": {"availableBalance": "1000"},
            "positions": [{"symbol": "BTCUSDT"}],
            "orders": [{"symbol": "ETHUSDT"}],
            "symbol_rules": [{"symbol": "BTCUSDT"}, {"symbol": "ETHUSDT"}],
        },
    )

    payload = latest_exchange_sync(db_path, "testnet")
    summary = latest_exchange_sync_summary(db_path, "testnet")

    assert payload["passed"] is True
    assert payload["account_summary"]["availableBalance"] == "1000"
    assert summary == {
        "mode": "testnet",
        "passed": True,
        "synced_at": "2026-06-02T00:00:00+00:00",
        "updated_at": summary["updated_at"],
        "age_seconds": summary["age_seconds"],
        "max_age_seconds": None,
        "is_fresh": True,
        "position_count": 1,
        "order_count": 1,
        "symbol_rule_count": 2,
        "failed_checks": [],
    }
    assert summary["age_seconds"] is not None
    assert "listenKey" not in str(summary)


def test_exchange_sync_cli_persists_snapshot(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("btc_eth_15m.dashboard.binance.BinanceFuturesClient.server_time_delta_ms", lambda self: 42)

    exit_code = main(["exchange-sync", "--config", str(config_path), "--mode", "testnet"])

    assert exit_code == 1
    summary = latest_exchange_sync_summary(tmp_path / "market.sqlite3", "testnet")
    assert summary["passed"] is False
    assert summary["failed_checks"] == ["credentials"]


def test_dashboard_api_reports_live_locked(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT", "ETHUSDT"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
                "live_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("btc_eth_15m.dashboard.binance.BinanceFuturesClient.server_time_delta_ms", lambda self: 42)
    client = TestClient(create_app(config_path))

    status = client.get("/api/status?mode=live")
    assert status.status_code == 200
    payload = status.json()
    assert payload["live_locked"] is True
    assert payload["risk_budget"]["daily_loss_cap_usdt"] == 200.0
    assert payload["risk_budget"]["daily_loss_used_usdt"] == 0.0
    assert payload["margin_caps"]["daily_loss_usdt"] == 200.0
    assert any(gate["name"] == "live_enabled" and not gate["passed"] for gate in payload["risk_gates"])

    signals = client.get("/api/signals/latest")
    assert signals.status_code == 200
    assert len(signals.json()["signals"]) == 2

    kill = client.post("/api/kill-switch", json={"enabled": True, "reason": "test"})
    assert kill.status_code == 200
    paper_status = client.get("/api/status?mode=paper").json()
    assert paper_status["kill_switch_enabled"] is True
    assert any(gate["name"] == "kill_switch" and not gate["passed"] for gate in paper_status["risk_gates"])

    report = client.post("/api/readiness/report")
    assert report.status_code == 200
    assert (tmp_path / "outputs").exists()
    assert report.json()["path"].endswith("-live-readiness.md")
    report_text = Path(report.json()["path"]).read_text(encoding="utf-8")
    assert "## Readiness Checks" in report_text
    assert "- FAIL live_enabled: Live trading is locked in config." in report_text
    assert "- FAIL testnet_self_check_passed: Binance Testnet self-check has not passed." in report_text
    assert "## Live Risk Budget" in report_text
    assert "- daily_loss_used_usdt: 0.0" in report_text
    assert "- daily_loss_cap_usdt: 200.0" in report_text


def test_readiness_blocks_when_live_submission_is_not_wired(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    db_path = tmp_path / "market.sqlite3"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(db_path),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
                "live_enabled": True,
            }
        ),
        encoding="utf-8",
    )
    record_exchange_sync(
        db_path,
        {
            "mode": "testnet",
            "passed": True,
            "synced_at": now_iso(),
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "account_summary": {"availableBalance": "1000"},
            "positions": [],
            "orders": [],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        },
    )
    _record_fresh_exchange_self_check(AppConfig(symbols=["BTCUSDT"], db_path=db_path), mode="testnet")

    class FakeBroker:
        def __init__(self, mode):
            self.mode = mode

        def status(self):
            if self.mode == "paper":
                return {
                    "mode": "paper",
                    "connected": True,
                    "order_sync_ok": True,
                    "position_sync_ok": True,
                    "exchange_rules_ok": True,
                    "order_submission_enabled": True,
                    "message": "paper ok",
                }
            if self.mode == "testnet":
                return {
                    "mode": "testnet",
                    "connected": True,
                    "order_sync_ok": True,
                    "position_sync_ok": True,
                    "exchange_rules_ok": True,
                    "order_submission_enabled": True,
                    "message": "testnet ok",
                }
            return {
                "mode": "live",
                "connected": True,
                "order_sync_ok": True,
                "position_sync_ok": True,
                "exchange_rules_ok": True,
                "order_submission_enabled": False,
                "message": "live account sync ok, submission not wired",
            }

        def self_check(self):
            return {
                "mode": self.mode,
                "passed": True,
                "checks": [{"name": "all", "passed": True, "message": "ok"}],
                "symbol_rules": [{"symbol": "BTCUSDT"}],
            }

    monkeypatch.setattr("btc_eth_15m.dashboard.app.broker_for_mode", lambda config, mode: FakeBroker(mode))
    monkeypatch.setattr("btc_eth_15m.dashboard.app.market_freshness", lambda config: [_fresh_market("BTCUSDT")])
    client = TestClient(create_app(config_path))

    readiness = client.get("/api/readiness").json()

    assert readiness["ready_for_live"] is False
    assert readiness["blockers"] == ["Live order submission is not wired."]
    assert readiness["live_rules"]["order_submission_enabled"] is False
    readiness_checks = {check["name"]: check for check in readiness["readiness_checks"]}
    assert readiness_checks["testnet_self_check_passed"]["passed"] is True
    assert readiness_checks["testnet_sync_passed"]["passed"] is True
    assert readiness_checks["live_order_submission"] == {
        "name": "live_order_submission",
        "passed": False,
        "message": "Live order submission is not wired.",
    }

    report = client.post("/api/readiness/report").json()
    assert "Live order submission is not wired." in report["readiness"]["blockers"]


def test_readiness_blocks_when_live_daily_loss_cap_is_exactly_reached(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    db_path = tmp_path / "market.sqlite3"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(db_path),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
                "live_enabled": True,
            }
        ),
        encoding="utf-8",
    )
    record_exchange_sync(
        db_path,
        {
            "mode": "testnet",
            "passed": True,
            "synced_at": now_iso(),
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "account_summary": {"availableBalance": "1000"},
            "positions": [],
            "orders": [],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        },
    )
    _record_fresh_exchange_self_check(AppConfig(symbols=["BTCUSDT"], db_path=db_path), mode="testnet")
    _record_closed_position_loss(AppConfig(symbols=["BTCUSDT"], db_path=db_path), mode="live", loss_usdt=200.0)

    class FakeBroker:
        def __init__(self, mode):
            self.mode = mode

        def status(self):
            return {
                "mode": self.mode,
                "connected": True,
                "order_sync_ok": True,
                "position_sync_ok": True,
                "exchange_rules_ok": True,
                "order_submission_enabled": True,
                "message": f"{self.mode} ok",
            }

        def self_check(self):
            return {
                "mode": self.mode,
                "passed": True,
                "checks": [{"name": "all", "passed": True, "message": "ok"}],
                "symbol_rules": [{"symbol": "BTCUSDT"}],
            }

    monkeypatch.setattr("btc_eth_15m.dashboard.app.broker_for_mode", lambda config, mode: FakeBroker(mode))
    monkeypatch.setattr("btc_eth_15m.dashboard.app.market_freshness", lambda config: [_fresh_market("BTCUSDT")])
    client = TestClient(create_app(config_path))

    readiness = client.get("/api/readiness").json()

    assert readiness["ready_for_live"] is False
    assert readiness["blockers"] == ["Live daily loss cap is exceeded."]
    assert readiness["live_risk_budget"]["daily_loss_used_usdt"] == 200.0


def test_readiness_blocks_when_live_open_margin_budget_is_exactly_exhausted(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    db_path = tmp_path / "market.sqlite3"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(db_path),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
                "live_enabled": True,
            }
        ),
        encoding="utf-8",
    )
    record_exchange_sync(
        db_path,
        {
            "mode": "testnet",
            "passed": True,
            "synced_at": now_iso(),
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "account_summary": {"availableBalance": "1000"},
            "positions": [],
            "orders": [],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        },
    )
    _record_fresh_exchange_self_check(AppConfig(symbols=["BTCUSDT"], db_path=db_path), mode="testnet")
    config = AppConfig(symbols=["BTCUSDT"], db_path=db_path)
    _record_open_position_margin(config, mode="live", symbol="BTCUSDT", margin_usdt=50.0, position_id="live-open-budget")

    monkeypatch.setattr("btc_eth_15m.dashboard.app.broker_for_mode", lambda config, mode: _HealthyBroker(mode))
    monkeypatch.setattr("btc_eth_15m.dashboard.app.market_freshness", lambda config: [_fresh_market("BTCUSDT")])
    client = TestClient(create_app(config_path))

    readiness = client.get("/api/readiness").json()

    assert readiness["ready_for_live"] is False
    assert readiness["blockers"] == ["Live open margin budget is exhausted."]
    assert readiness["live_risk_budget"]["open_margin_used_usdt"] == 50.0
    assert readiness["live_risk_budget"]["open_margin_remaining_usdt"] == 0.0
    report = client.post("/api/readiness/report").json()
    report_text = Path(report["path"]).read_text(encoding="utf-8")
    assert "- open_margin_remaining_usdt: 0.0" in report_text


def test_readiness_blocks_when_live_daily_margin_budget_is_exactly_exhausted(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    db_path = tmp_path / "market.sqlite3"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(db_path),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
                "live_enabled": True,
            }
        ),
        encoding="utf-8",
    )
    record_exchange_sync(
        db_path,
        {
            "mode": "testnet",
            "passed": True,
            "synced_at": now_iso(),
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "account_summary": {"availableBalance": "1000"},
            "positions": [],
            "orders": [],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        },
    )
    _record_fresh_exchange_self_check(AppConfig(symbols=["BTCUSDT"], db_path=db_path), mode="testnet")
    config = AppConfig(symbols=["BTCUSDT"], db_path=db_path)
    _record_filled_order_margin(config, mode="live", symbol="BTCUSDT", margin_usdt=50.0, order_id="live-daily-budget")

    monkeypatch.setattr("btc_eth_15m.dashboard.app.broker_for_mode", lambda config, mode: _HealthyBroker(mode))
    monkeypatch.setattr("btc_eth_15m.dashboard.app.market_freshness", lambda config: [_fresh_market("BTCUSDT")])
    client = TestClient(create_app(config_path))

    readiness = client.get("/api/readiness").json()

    assert readiness["ready_for_live"] is False
    assert readiness["blockers"] == ["Live daily margin budget is exhausted."]
    assert readiness["live_risk_budget"]["daily_margin_used_usdt"] == 50.0
    assert readiness["live_risk_budget"]["daily_margin_remaining_usdt"] == 0.0
    report = client.post("/api/readiness/report").json()
    report_text = Path(report["path"]).read_text(encoding="utf-8")
    assert "- daily_margin_remaining_usdt: 0.0" in report_text


def test_stale_testnet_sync_blocks_status_readiness_and_signal_gate(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    db_path = tmp_path / "market.sqlite3"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(db_path),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
                "live_enabled": True,
                "exchange_sync_max_age_seconds": 60,
            }
        ),
        encoding="utf-8",
    )
    record_exchange_sync(
        db_path,
        {
            "mode": "testnet",
            "passed": True,
            "synced_at": _seconds_ago(120),
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "account_summary": {"availableBalance": "1000"},
            "positions": [],
            "orders": [],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        },
    )
    _record_fresh_exchange_self_check(
        AppConfig(symbols=["BTCUSDT"], db_path=db_path, exchange_sync_max_age_seconds=60),
        mode="testnet",
    )

    class FakeBroker:
        def __init__(self, mode):
            self.mode = mode

        def status(self):
            return {
                "mode": self.mode,
                "connected": True,
                "order_sync_ok": True,
                "position_sync_ok": True,
                "exchange_rules_ok": True,
                "order_submission_enabled": self.mode != "live",
                "message": f"{self.mode} ok",
            }

        def self_check(self):
            return {
                "mode": self.mode,
                "passed": True,
                "checks": [{"name": "all", "passed": True, "message": "ok"}],
                "symbol_rules": [{"symbol": "BTCUSDT"}],
            }

    monkeypatch.setattr("btc_eth_15m.dashboard.app.broker_for_mode", lambda config, mode: FakeBroker(mode))
    client = TestClient(create_app(config_path))

    status = client.get("/api/status?mode=testnet").json()
    readiness = client.get("/api/readiness").json()
    summary = latest_exchange_sync_summary(db_path, "testnet", max_age_seconds=60)

    assert status["last_sync"]["passed"] is True
    assert status["last_sync"]["is_fresh"] is False
    assert any(gate["name"] == "order_sync" and not gate["passed"] for gate in status["risk_gates"])
    assert "Binance Testnet sync snapshot is stale." in readiness["blockers"]
    assert summary["is_fresh"] is False
    assert _mode_sync_healthy(AppConfig(symbols=["BTCUSDT"], db_path=db_path, exchange_sync_max_age_seconds=60), "testnet") is False


def test_mode_sync_healthy_requires_testnet_self_check(tmp_path):
    db_path = tmp_path / "market.sqlite3"
    config = AppConfig(symbols=["BTCUSDT"], db_path=db_path)
    record_exchange_sync(
        db_path,
        {
            "mode": "testnet",
            "passed": True,
            "synced_at": now_iso(),
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "account_summary": {"availableBalance": "1000"},
            "positions": [],
            "orders": [],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        },
    )

    assert _mode_sync_healthy(config, "testnet") is False

    _record_fresh_exchange_self_check(config, mode="testnet")

    assert _mode_sync_healthy(config, "testnet") is True


def test_market_refresh_api_records_recent_fetch(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT", "ETHUSDT"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )

    def fake_fetch_recent_all(config, lookback_bars=600):
        return [FetchResult("BTCUSDT", 0, None, None), FetchResult("ETHUSDT", 0, None, None)]

    monkeypatch.setattr("btc_eth_15m.dashboard.app.fetch_recent_all", fake_fetch_recent_all)
    client = TestClient(create_app(config_path))

    response = client.post("/api/market/refresh", json={"lookback_bars": 300})

    assert response.status_code == 200
    payload = response.json()
    assert payload["lookback_bars"] == 300
    assert payload["results"][0]["symbol"] == "BTCUSDT"
    assert len(payload["market_freshness"]) == 2
    logs = client.get("/api/logs").json()["events"]
    assert logs[0]["level"] == "market"


def test_paper_replay_drafts_api(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("btc_eth_15m.dashboard.app.replay_order_drafts", lambda config, limit=4: [_draft()])
    client = TestClient(create_app(config_path))

    response = client.get("/api/paper/replay-drafts?limit=2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "paper"
    assert payload["drafts"][0]["symbol"] == "BTCUSDT"
    assert payload["drafts"][0]["status"] == "ready"


def test_dashboard_confirm_order_api_updates_paper_state(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("btc_eth_15m.dashboard.app.find_order_draft", lambda config, draft_id, mode="paper": _draft(mode=mode))
    client = TestClient(create_app(config_path))

    response = client.post("/api/orders/draft-1/confirm", json={"mode": "paper", "leverage": 10})

    assert response.status_code == 200
    assert response.json()["result"]["status"] == "FILLED"
    positions = client.get("/api/positions?mode=paper").json()["positions"]
    orders = client.get("/api/orders?mode=paper").json()["orders"]
    assert positions[0]["leverage"] == 10
    assert orders[0]["source_draft_id"] == "draft-1"
    logs = client.get("/api/logs?limit=1").json()["events"]
    assert logs[0]["level"] == "order"
    assert logs[0]["message"] == "Order confirmation accepted: paper"
    event_payload = json.loads(logs[0]["payload_json"])
    assert event_payload["draft_id"] == "draft-1"
    assert event_payload["requested_leverage"] == 10
    assert event_payload["status"] == "FILLED"
    assert "exchange_response" not in event_payload


def test_dashboard_confirm_order_rejection_is_audited(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "btc_eth_15m.dashboard.app.find_order_draft",
        lambda config, draft_id, mode="paper": _draft(mode=mode, status="blocked", blocked_reasons=["Kill switch is active."]),
    )
    client = TestClient(create_app(config_path))

    response = client.post("/api/orders/draft-1/confirm", json={"mode": "paper", "leverage": 10})

    assert response.status_code == 400
    assert response.json()["detail"] == "Order draft is blocked: Kill switch is active."
    logs = client.get("/api/logs?limit=1").json()["events"]
    assert logs[0]["level"] == "order"
    assert logs[0]["message"] == "Order confirmation rejected: paper"
    event_payload = json.loads(logs[0]["payload_json"])
    assert event_payload["status"] == "REJECTED"
    assert event_payload["draft_id"] == "draft-1"
    assert event_payload["symbol"] == "BTCUSDT"
    assert event_payload["rejection_reason"] == "Order draft is blocked: Kill switch is active."
    assert "exchange_response" not in event_payload


def test_dashboard_confirm_order_rejection_redacts_sensitive_error(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )

    class FakeBroker:
        def submit_order_draft(self, draft, *, leverage=None):
            raise BrokerError(
                "Exchange failed for url: "
                "https://example.test/fapi/v1/order?timestamp=1&signature=secret&recvWindow=5000 "
                "listenKey=abc123"
            )

    monkeypatch.setattr("btc_eth_15m.dashboard.app.find_order_draft", lambda config, draft_id, mode="paper": _draft(mode=mode))
    monkeypatch.setattr("btc_eth_15m.dashboard.app.broker_for_mode", lambda config, mode: FakeBroker())
    client = TestClient(create_app(config_path))

    response = client.post("/api/orders/draft-1/confirm", json={"mode": "testnet", "leverage": 12})

    assert response.status_code == 400
    assert "https://example.test/fapi/v1/order?<redacted>" in response.json()["detail"]
    assert "signature=secret" not in response.json()["detail"]
    assert "listenKey=abc123" not in response.json()["detail"]
    logs = client.get("/api/logs?limit=1").json()["events"]
    event_payload = json.loads(logs[0]["payload_json"])
    assert event_payload["status"] == "REJECTED"
    assert "signature=secret" not in logs[0]["payload_json"]
    assert "listenKey=abc123" not in logs[0]["payload_json"]
    assert "exchange_response" not in logs[0]["payload_json"]


def test_dashboard_confirm_testnet_order_requires_persisted_self_check(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    db_path = tmp_path / "market.sqlite3"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(db_path),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )
    record_exchange_sync(
        db_path,
        {
            "mode": "testnet",
            "passed": True,
            "synced_at": now_iso(),
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "account_summary": {"availableBalance": "1000"},
            "positions": [],
            "orders": [],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        },
    )
    fake = FakeBinanceClient()

    def fake_broker_for_mode(config, mode):
        if mode != "testnet":
            return broker_for_mode(config, mode)
        broker = BinanceFuturesBroker(config, mode="testnet", base_url="https://example.test", env_prefix="MISSING")
        broker.credentials = BinanceCredentials("key", "secret")
        broker.client = fake
        return broker

    monkeypatch.setattr("btc_eth_15m.dashboard.app.find_order_draft", lambda config, draft_id, mode="paper": _draft(mode=mode))
    monkeypatch.setattr("btc_eth_15m.dashboard.app.broker_for_mode", fake_broker_for_mode)
    client = TestClient(create_app(config_path))

    response = client.post("/api/orders/draft-1/confirm", json={"mode": "testnet", "leverage": 12})

    assert response.status_code == 400
    assert response.json()["detail"] == "Testnet self-check has not passed."
    assert fake.gets == []
    assert fake.posts == []
    logs = client.get("/api/logs?limit=1").json()["events"]
    assert logs[0]["level"] == "order"
    assert logs[0]["message"] == "Order confirmation rejected: testnet"
    event_payload = json.loads(logs[0]["payload_json"])
    assert event_payload["status"] == "REJECTED"
    assert event_payload["rejection_reason"] == "Testnet self-check has not passed."
    assert event_payload["draft_status"] == "ready"
    assert "exchange_response" not in event_payload


def test_dashboard_confirm_testnet_order_records_safe_audit_event(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )

    class FakeBroker:
        def submit_order_draft(self, draft, *, leverage=None):
            return {
                "status": "TEST_ORDER_ACCEPTED",
                "exchange_response": {"hidden": "do-not-log"},
                "order_plan": {
                    "symbol": draft.symbol,
                    "requested_leverage": leverage,
                    "raw_quantity": "3.00000000",
                    "rounded_quantity": "3",
                    "notional_usdt": "300",
                    "rules": {"symbol": draft.symbol},
                },
            }

    monkeypatch.setattr("btc_eth_15m.dashboard.app.find_order_draft", lambda config, draft_id, mode="paper": _draft(mode=mode))
    monkeypatch.setattr("btc_eth_15m.dashboard.app.broker_for_mode", lambda config, mode: FakeBroker())
    client = TestClient(create_app(config_path))

    response = client.post("/api/orders/draft-1/confirm", json={"mode": "testnet", "leverage": 12})

    assert response.status_code == 200
    assert response.json()["result"]["status"] == "TEST_ORDER_ACCEPTED"
    logs = client.get("/api/logs?limit=1").json()["events"]
    assert logs[0]["level"] == "order"
    event_payload = json.loads(logs[0]["payload_json"])
    assert event_payload["mode"] == "testnet"
    assert event_payload["status"] == "TEST_ORDER_ACCEPTED"
    assert event_payload["order_plan"] == {
        "symbol": "BTCUSDT",
        "requested_leverage": 12,
        "rounded_quantity": "3",
        "notional_usdt": "300",
    }
    assert "exchange_response" not in event_payload
    assert "do-not-log" not in logs[0]["payload_json"]


def test_dashboard_close_position_success_is_audited(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("btc_eth_15m.dashboard.app.find_order_draft", lambda config, draft_id, mode="paper": _draft(mode=mode))
    client = TestClient(create_app(config_path))
    open_response = client.post("/api/orders/draft-1/confirm", json={"mode": "paper", "leverage": 10})
    position_id = open_response.json()["result"]["position_id"]

    response = client.post(f"/api/positions/{position_id}/close", json={"mode": "paper", "reason": "manual-ui"})

    assert response.status_code == 200
    assert response.json()["result"]["status"] == "CLOSED"
    logs = client.get("/api/logs?limit=1").json()["events"]
    assert logs[0]["level"] == "position"
    assert logs[0]["message"] == "Position close accepted: paper"
    event_payload = json.loads(logs[0]["payload_json"])
    assert event_payload["mode"] == "paper"
    assert event_payload["position_id"] == position_id
    assert event_payload["close_reason"] == "manual-ui"
    assert event_payload["status"] == "CLOSED"
    assert event_payload["close_order_id"].startswith("paper-close-")
    assert "pnl" in event_payload
    assert "exchange_response" not in event_payload


def test_dashboard_close_position_rejection_is_audited(tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(config_path))

    response = client.post("/api/positions/missing-position/close", json={"mode": "paper", "reason": "manual-ui"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Open paper position was not found."
    logs = client.get("/api/logs?limit=1").json()["events"]
    assert logs[0]["level"] == "position"
    assert logs[0]["message"] == "Position close rejected: paper"
    event_payload = json.loads(logs[0]["payload_json"])
    assert event_payload == {
        "mode": "paper",
        "position_id": "missing-position",
        "close_reason": "manual-ui",
        "status": "REJECTED",
        "rejection_reason": "Open paper position was not found.",
    }


def test_market_freshness_reports_missing_data(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")

    freshness = market_freshness(config)

    assert freshness == [
        {
            "symbol": "BTCUSDT",
            "rows": 0,
            "latest_open_time": None,
            "latest_open_time_iso": None,
            "latest_fetched_at": None,
            "age_seconds": None,
            "is_fresh": False,
        }
    ]


def test_status_and_readiness_block_missing_market_data(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yml"
    db_path = tmp_path / "market.sqlite3"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(db_path),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
                "live_enabled": True,
            }
        ),
        encoding="utf-8",
    )
    record_exchange_sync(
        db_path,
        {
            "mode": "testnet",
            "passed": True,
            "synced_at": now_iso(),
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "account_summary": {"availableBalance": "1000"},
            "positions": [],
            "orders": [],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        },
    )
    _record_fresh_exchange_self_check(AppConfig(symbols=["BTCUSDT"], db_path=db_path), mode="testnet")

    class FakeBroker:
        def __init__(self, mode):
            self.mode = mode

        def status(self):
            return {
                "mode": self.mode,
                "connected": True,
                "order_sync_ok": True,
                "position_sync_ok": True,
                "exchange_rules_ok": True,
                "order_submission_enabled": self.mode != "live",
                "message": f"{self.mode} ok",
            }

        def self_check(self):
            return {
                "mode": self.mode,
                "passed": True,
                "checks": [{"name": "all", "passed": True, "message": "ok"}],
                "symbol_rules": [{"symbol": "BTCUSDT"}],
            }

    monkeypatch.setattr("btc_eth_15m.dashboard.app.broker_for_mode", lambda config, mode: FakeBroker(mode))
    client = TestClient(create_app(config_path))

    status = client.get("/api/status?mode=testnet").json()
    readiness = client.get("/api/readiness").json()

    assert any(gate["name"] == "market_data" and not gate["passed"] for gate in status["risk_gates"])
    assert "Market data is stale or missing." in readiness["blockers"]


def test_signal_draft_blocks_when_market_data_is_stale(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    row = pd.Series(
        {
            "symbol": "BTCUSDT",
            "open_datetime": pd.Timestamp("2026-06-02T00:00:00Z"),
            "signal": 1,
            "close": 100.0,
            "signal_atr": 1.0,
            "atr_pct": 0.005,
            "regime_atr_pct": 0.005,
            "rsi": 55.0,
            "volume": 200.0,
            "volume_sma": 100.0,
            "htf_ema_fast": 105.0,
            "htf_ema_slow": 100.0,
            "ema50": 99.0,
        }
    )

    snapshot = _snapshot_from_row(config, row, "paper", sync_healthy=True, market_data_ok=False)

    assert snapshot.order_draft is not None
    assert snapshot.order_draft.status == "blocked"
    assert "Market data is stale or missing." in snapshot.order_draft.blocked_reasons
    gate = next(gate for gate in snapshot.order_draft.explanation["risk_gates"] if gate["name"] == "market_data")
    assert gate["passed"] is False


def test_signal_draft_blocks_when_symbol_position_cap_is_reached(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    PaperBroker(config).submit_order_draft(_draft())
    row = pd.Series(
        {
            "symbol": "BTCUSDT",
            "open_datetime": pd.Timestamp("2026-06-02T00:00:00Z"),
            "signal": 1,
            "close": 100.0,
            "signal_atr": 1.0,
            "atr_pct": 0.005,
            "regime_atr_pct": 0.005,
            "rsi": 55.0,
            "volume": 200.0,
            "volume_sma": 100.0,
            "htf_ema_fast": 105.0,
            "htf_ema_slow": 100.0,
            "ema50": 99.0,
        }
    )

    snapshot = _snapshot_from_row(config, row, "paper", sync_healthy=True, market_data_ok=True)

    assert snapshot.order_draft is not None
    assert snapshot.order_draft.status == "blocked"
    gate = next(gate for gate in snapshot.order_draft.explanation["risk_gates"] if gate["name"] == "position_count_cap")
    assert gate["passed"] is False
    assert "Open positions for this symbol 1 / 1." in snapshot.order_draft.blocked_reasons


def test_signal_draft_blocks_when_daily_loss_cap_is_reached(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    broker = PaperBroker(config)
    opened = broker.submit_order_draft(_draft())
    with dashboard_connection(config.db_path) as connection:
        connection.execute("UPDATE dashboard_positions SET mark_price = ? WHERE id = ?", (0.0, opened["position_id"]))
        connection.commit()
    broker.close_position(opened["position_id"], reason="loss-cap-test")
    row = pd.Series(
        {
            "symbol": "BTCUSDT",
            "open_datetime": pd.Timestamp("2026-06-02T00:00:00Z"),
            "signal": 1,
            "close": 100.0,
            "signal_atr": 1.0,
            "atr_pct": 0.005,
            "regime_atr_pct": 0.005,
            "rsi": 55.0,
            "volume": 200.0,
            "volume_sma": 100.0,
            "htf_ema_fast": 105.0,
            "htf_ema_slow": 100.0,
            "ema50": 99.0,
        }
    )

    snapshot = _snapshot_from_row(config, row, "paper", sync_healthy=True, market_data_ok=True)

    assert snapshot.order_draft is not None
    assert snapshot.order_draft.status == "blocked"
    gate = next(gate for gate in snapshot.order_draft.explanation["risk_gates"] if gate["name"] == "daily_loss_cap")
    assert gate["passed"] is False
    assert "Daily realized loss 300.00 / 200.00 USDT." in snapshot.order_draft.blocked_reasons


def test_signal_draft_reports_exhausted_daily_margin_budget(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3")
    _record_filled_order_margin(config, mode="paper", symbol="ETHUSDT", margin_usdt=50.0, order_id="paper-daily-cap")
    row = pd.Series(
        {
            "symbol": "BTCUSDT",
            "open_datetime": pd.Timestamp("2026-06-02T00:00:00Z"),
            "signal": 1,
            "close": 100.0,
            "signal_atr": 1.0,
            "atr_pct": 0.005,
            "regime_atr_pct": 0.005,
            "rsi": 55.0,
            "volume": 200.0,
            "volume_sma": 100.0,
            "htf_ema_fast": 105.0,
            "htf_ema_slow": 100.0,
            "ema50": 99.0,
        }
    )

    snapshot = _snapshot_from_row(config, row, "paper", sync_healthy=True, market_data_ok=True)

    assert snapshot.order_draft is not None
    assert snapshot.order_draft.status == "blocked"
    daily_budget = next(
        gate for gate in snapshot.order_draft.explanation["risk_gates"] if gate["name"] == "daily_margin_budget"
    )
    assert daily_budget["passed"] is False
    assert "Daily margin budget is exhausted: 50.00 / 50.00 USDT." in snapshot.order_draft.blocked_reasons
    assert "No margin budget remains for this mode." in snapshot.order_draft.blocked_reasons


def test_live_broker_is_disabled_by_default(tmp_path):
    config = AppConfig(symbols=["BTCUSDT"], db_path=tmp_path / "market.sqlite3", live_enabled=False)
    status = broker_for_mode(config, "live").status()
    assert status["connected"] is False
    assert "locked" in status["message"].lower()


def test_status_reports_kquant_product_name(tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT", "ETHUSDT"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(config_path))

    payload = client.get("/api/status?mode=paper").json()

    assert payload["app"] == "kquant ATM Options Signal Assistant"
    assert payload["live_locked"] is True


def test_research_latest_api_reports_latest_outputs(tmp_path):
    config_path = tmp_path / "config.yml"
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT", "ETHUSDT"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(outputs_dir),
            }
        ),
        encoding="utf-8",
    )
    (outputs_dir / "20260608T000000Z-run-summary.json").write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "total_return_pct": -12.5,
                "profit_factor": 0.9,
                "avg_r": -0.12,
                "daily_return_stats": {
                    "avg_daily_return_pct": -0.5,
                    "target_range_hit_rate_pct": 0.0,
                    "loss_day_rate_pct": 62.5,
                },
            }
        ),
        encoding="utf-8",
    )
    (outputs_dir / "20260608T000100Z-sweep.csv").write_text(
        "\n".join(
            [
                "sweep_id,variant,run_id,trade_count,final_equity,total_return_pct,max_drawdown_pct,win_rate_pct,profit_factor,expectancy,avg_r,avg_daily_return_pct,target_range_hit_rate_pct,above_target_min_rate_pct,loss_day_rate_pct,strategy_overrides,app_overrides",
                "sweep-1,daily_target_eth_short_htf,best-run,12,9900,-1.0,-4.0,40.0,0.95,-1.0,-0.03,-0.01,0.0,0.0,7.5,{},{}",
            ]
        ),
        encoding="utf-8",
    )
    (outputs_dir / "20260608T000200Z-v2-research-report.md").write_text(
        "\n".join(
            [
                "# BTC/ETH 15m v2 Research Report",
                "- Best variant: `daily_target_eth_short_htf`",
                "- Best average daily return: `-0.006%`",
                "- Best 5%-7% daily hit rate: `0.00%`",
                "- Daily target decision: **NO**",
                "- Paper observation decision: **NO**",
                "| Variant | Mode | Regime | Trades | PF | Avg R | Avg Daily | 5%-7% Hit | Loss Days | Return | Max DD | Positive Years | Run ID |",
                "| daily_target_eth_short_htf | trend_pullback | none | 12 | 0.950 | -0.030 | -0.010% | 0.00% | 7.50% | -1.00% | -4.00% | 0/1 | `best-run` |",
            ]
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(config_path))

    payload = client.get("/api/research/latest").json()

    assert payload["status"] == "ready"
    assert payload["run_id"] == "run-1"
    assert payload["total_return_pct"] == -12.5
    assert payload["avg_daily_return_pct"] == -0.5
    assert payload["target_range_hit_rate_pct"] == 0.0
    assert payload["loss_day_rate_pct"] == 62.5
    assert payload["paper_observation_decision"] == "NO"
    assert payload["daily_target_decision"] == "NO"
    assert payload["best_variant"] == "daily_target_eth_short_htf"
    assert payload["best_run_id"] == "best-run"


def test_research_apis_handle_empty_and_bad_outputs(tmp_path):
    config_path = tmp_path / "config.yml"
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(outputs_dir),
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(config_path))

    assert client.get("/api/research/runs").json()["runs"] == []
    empty_latest = client.get("/api/research/latest").json()
    assert empty_latest["status"] == "empty"
    assert empty_latest["summary_error"] is None

    (outputs_dir / "20260608T000000Z-bad-summary.json").write_text("{bad json", encoding="utf-8")
    (outputs_dir / "20260608T000100Z-live-readiness.md").write_text("# readiness", encoding="utf-8")

    bad_latest = client.get("/api/research/latest").json()
    assert bad_latest["status"] == "empty"
    assert bad_latest["summary_error"]
    assert client.get("/api/research/runs").json()["runs"] == [
        {
            "type": "backtest_summary",
            "path": str(outputs_dir / "20260608T000000Z-bad-summary.json"),
            "name": "20260608T000000Z-bad-summary.json",
            "run_id": "20260608T000000Z-bad",
            "modified_at": bad_latest["generated_at"],
            "size_bytes": 9,
        }
    ]


class _HealthyBroker:
    def __init__(self, mode: str):
        self.mode = mode

    def status(self):
        return {
            "mode": self.mode,
            "connected": True,
            "order_sync_ok": True,
            "position_sync_ok": True,
            "exchange_rules_ok": True,
            "order_submission_enabled": True,
            "message": f"{self.mode} ok",
        }

    def self_check(self):
        return {
            "mode": self.mode,
            "passed": True,
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        }


def _leverage(confidence: float) -> int:
    return leverage_from_confidence(
        confidence,
        volatility_ok=True,
        drawdown_ok=True,
        order_sync_ok=True,
        position_sync_ok=True,
        min_leverage=7,
        max_leverage=15,
    ).leverage


def _draft(mode: str = "paper", status: str = "ready", blocked_reasons: list[str] | None = None) -> OrderDraft:
    return OrderDraft(
        id="draft-1",
        symbol="BTCUSDT",
        side="long",
        mode=mode,  # type: ignore[arg-type]
        bar_time="2026-06-02T00:00:00+00:00",
        entry_price=100.0,
        stop_price=95.0,
        target_price=110.0,
        quantity=3.0,
        margin_usdt=25.0,
        notional_usdt=300.0,
        leverage=12,
        max_allowed_leverage=12,
        confidence=0.80,
        status=status,  # type: ignore[arg-type]
        blocked_reasons=blocked_reasons or [],
        explanation={"strategy_mode": "trend_pullback"},
    )


def _record_fresh_exchange_sync(config: AppConfig, *, mode: str) -> None:
    _record_fresh_exchange_self_check(config, mode=mode)
    record_exchange_sync(
        config.db_path,
        {
            "mode": mode,
            "passed": True,
            "synced_at": now_iso(),
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "account_summary": {"availableBalance": "1000"},
            "positions": [],
            "orders": [],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        },
    )


def _record_fresh_exchange_self_check(config: AppConfig, *, mode: str) -> None:
    record_exchange_self_check(
        config.db_path,
        {
            "mode": mode,
            "passed": True,
            "checked_at": now_iso(),
            "checks": [{"name": "all", "passed": True, "message": "ok"}],
            "symbol_rules": [{"symbol": "BTCUSDT"}],
        },
    )


def _record_fresh_kline(config: AppConfig, *, symbol: str = "BTCUSDT") -> None:
    opened_at = datetime.now(tz=UTC)
    open_time = int(opened_at.timestamp() * 1000)
    close_time = open_time + interval_to_millis(config.interval) - 1
    with connect(config.db_path) as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO klines (
                symbol, interval, open_time, open_time_iso, close_time,
                open, high, low, close, volume, quote_volume, trades, fetched_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                config.interval,
                open_time,
                opened_at.isoformat(),
                close_time,
                100.0,
                110.0,
                95.0,
                100.0,
                1000.0,
                100000.0,
                100,
                now_iso(),
            ),
        )
        connection.commit()


def _record_filled_order_margin(config: AppConfig, *, mode: str, symbol: str, margin_usdt: float, order_id: str) -> None:
    timestamp = now_iso()
    with dashboard_connection(config.db_path) as connection:
        connection.execute(
            """
            INSERT INTO dashboard_orders (
                id, mode, symbol, side, leverage, margin_usdt, notional_usdt,
                quantity, entry_price, stop_price, target_price, status,
                source_draft_id, explanation_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                mode,
                symbol,
                "long",
                12,
                margin_usdt,
                margin_usdt * 12,
                margin_usdt * 12 / 100,
                100.0,
                95.0,
                110.0,
                "FILLED",
                f"{order_id}-draft",
                "{}",
                timestamp,
                timestamp,
            ),
        )
        connection.commit()


def _record_open_position_margin(config: AppConfig, *, mode: str, symbol: str, margin_usdt: float, position_id: str) -> None:
    timestamp = now_iso()
    with dashboard_connection(config.db_path) as connection:
        connection.execute(
            """
            INSERT INTO dashboard_positions (
                id, order_id, mode, symbol, side, leverage, margin_usdt,
                notional_usdt, quantity, entry_price, mark_price,
                unrealized_pnl, status, opened_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                position_id,
                f"{position_id}-order",
                mode,
                symbol,
                "long",
                12,
                margin_usdt,
                margin_usdt * 12,
                margin_usdt * 12 / 100,
                100.0,
                100.0,
                0.0,
                "OPEN",
                timestamp,
                timestamp,
            ),
        )
        connection.commit()


def _record_closed_position_loss(config: AppConfig, *, mode: str, loss_usdt: float) -> None:
    timestamp = now_iso()
    with dashboard_connection(config.db_path) as connection:
        connection.execute(
            """
            INSERT INTO dashboard_positions (
                id, order_id, mode, symbol, side, leverage, margin_usdt,
                notional_usdt, quantity, entry_price, mark_price,
                unrealized_pnl, status, opened_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "pos-loss-cap",
                "paper-loss-cap",
                mode,
                "BTCUSDT",
                "long",
                12,
                25.0,
                300.0,
                3.0,
                100.0,
                100.0,
                -loss_usdt,
                "CLOSED",
                timestamp,
                timestamp,
            ),
        )
        connection.commit()


def _rules(step_size: str = "0.001", min_qty: str = "0.001", min_notional: str = "100") -> SymbolRules:
    return SymbolRules(
        symbol="BTCUSDT",
        min_qty=Decimal(min_qty),
        max_qty=Decimal("100000"),
        step_size=Decimal(step_size),
        min_notional=Decimal(min_notional),
        tick_size=Decimal("0.01"),
    )


def _seconds_ago(seconds: int) -> str:
    return (datetime.now(tz=UTC) - timedelta(seconds=seconds)).isoformat()


def _fresh_market(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "rows": 1,
        "latest_open_time": 0,
        "latest_open_time_iso": now_iso(),
        "latest_fetched_at": now_iso(),
        "age_seconds": 0,
        "is_fresh": True,
    }


class FakeBinanceClient:
    def __init__(self, *, min_notional: str = "100", position_rows: list[dict] | None = None) -> None:
        self.min_notional = min_notional
        self.position_rows = position_rows or []
        self.gets: list[tuple[str, dict]] = []
        self.posts: list[tuple[str, dict]] = []
        self.user_stream_starts = 0

    def get(self, path: str, params: dict | None = None):
        self.gets.append((path, params or {}))
        if path == "/fapi/v3/account":
            return {"availableBalance": "1000", "assets": [{}, {}], "positions": [{}, {}]}
        if path == "/fapi/v3/positionRisk":
            return self.position_rows
        if path == "/fapi/v1/openOrders":
            return []
        raise AssertionError(f"Unexpected GET {path}")

    def post(self, path: str, params: dict | None = None):
        self.posts.append((path, params or {}))
        return {}

    def public_get(self, path: str, params: dict | None = None):
        assert path == "/fapi/v1/exchangeInfo"
        return {
            "symbols": [
                {
                    "symbol": params["symbol"],
                    "filters": [
                        {"filterType": "MARKET_LOT_SIZE", "minQty": "0.001", "maxQty": "100000", "stepSize": "0.001"},
                        {"filterType": "MIN_NOTIONAL", "notional": self.min_notional},
                        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                    ],
                }
            ]
        }

    def server_time_delta_ms(self):
        return 42

    def start_user_data_stream(self):
        self.user_stream_starts += 1
        return {"listenKey": "hidden-test-listen-key"}


class AccountSnapshotFailingBinanceClient(FakeBinanceClient):
    def __init__(self) -> None:
        super().__init__()
        self.account_gets = 0

    def get(self, path: str, params: dict | None = None):
        if path == "/fapi/v3/account":
            self.account_gets += 1
            if self.account_gets > 1:
                raise ValueError(FailingBinanceClient.sensitive_error)
        return super().get(path, params)


class FailingBinanceClient:
    sensitive_error = (
        "Exchange failed for url: "
        "https://example.test/fapi/v3/account?timestamp=1&signature=secret&recvWindow=5000 "
        "listenKey=abc123 apiKey=abc secret=def"
    )

    def get(self, path: str, params: dict | None = None):
        raise ValueError(self.sensitive_error)

    def public_get(self, path: str, params: dict | None = None):
        raise ValueError(self.sensitive_error)

    def server_time_delta_ms(self):
        return 42

    def start_user_data_stream(self):
        raise ValueError(self.sensitive_error)
