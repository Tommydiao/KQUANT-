from __future__ import annotations

import json

import yaml
from fastapi.testclient import TestClient

from btc_eth_15m.dashboard.app import create_app
from btc_eth_15m.options_broker import (
    create_option_order_intent,
    submit_option_paper_order,
    cancel_option_paper_order,
)
from btc_eth_15m.options_lab import options_chain
from btc_eth_15m.options_pilot_journal import (
    load_pilot_journal,
    record_pilot_journal_entry,
)


class FakeAlpacaPaperBroker:
    def __init__(self) -> None:
        self.submitted = []
        self.cancelled = []

    def submit_order(self, ticket):
        payload = ticket.to_alpaca_payload()
        self.submitted.append(payload)
        return {
            "id": "alpaca-paper-order-1",
            "status": "accepted",
            "symbol": payload["symbol"],
            "side": payload["side"],
            "position_intent": payload["position_intent"],
        }

    def cancel_order(self, broker_order_id: str):
        self.cancelled.append(broker_order_id)
        return {"id": broker_order_id, "status": "cancel_requested"}


def test_pilot_journal_uses_sqlite_and_imports_legacy_json(tmp_path):
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()
    db_path = tmp_path / "market.sqlite3"
    legacy_entry = {
        "entry_id": "2026-06-15:strict_local_v1:fixture_read_only:SPY260626C00530000",
        "market_date": "2026-06-15",
        "symbol": "SPY",
        "option_symbol": "SPY260626C00530000",
        "status": "reviewed",
        "source_type": "fixture_read_only",
        "profile_id": "strict_local_v1",
        "stock_kline_checked": True,
        "option_kline_checked": True,
        "lens_checked": True,
        "created_at": "2026-06-15T00:00:00+00:00",
        "updated_at": "2026-06-15T00:00:00+00:00",
    }
    (outputs_dir / "options-pilot-journal.json").write_text(
        json.dumps({"entries": [legacy_entry]}),
        encoding="utf-8",
    )

    journal = load_pilot_journal(outputs_dir, db_path=db_path)

    assert journal["storage"] == "sqlite"
    assert journal["journal_path"].endswith("market.sqlite3")
    assert journal["entries"][0]["option_symbol"] == "SPY260626C00530000"
    assert journal["entries"][0]["review_step_complete"] is True


def test_option_order_intent_requires_manual_journal_and_blocks_agent(tmp_path):
    db_path = tmp_path / "market.sqlite3"
    outputs_dir = tmp_path / "outputs"
    option_symbol = options_chain("SPY", source="fixture")["contracts"][0]["option_symbol"]

    blocked = create_option_order_intent(
        db_path=db_path,
        outputs_dir=outputs_dir,
        payload={
            "option_symbol": option_symbol,
            "source_type": "fixture",
            "limit_price": 1.25,
            "manual_confirmed": True,
        },
    )["intent"]
    assert blocked["status"] == "blocked"
    assert any("journal checklist" in item for item in blocked["blockers"])

    record_pilot_journal_entry(
        outputs_dir,
        {
            "symbol": "SPY",
            "option_symbol": option_symbol,
            "status": "reviewed",
            "source_type": "fixture",
            "profile_id": "strict_local_v1",
            "market_date": "2026-06-15",
            "stock_kline_checked": True,
            "option_kline_checked": True,
            "lens_checked": True,
        },
        db_path=db_path,
    )
    agent_blocked = create_option_order_intent(
        db_path=db_path,
        outputs_dir=outputs_dir,
        payload={
            "option_symbol": option_symbol,
            "source_type": "fixture",
            "limit_price": 1.25,
            "manual_confirmed": True,
            "requested_by": "agent",
        },
    )["intent"]
    ready = create_option_order_intent(
        db_path=db_path,
        outputs_dir=outputs_dir,
        payload={
            "option_symbol": option_symbol,
            "source_type": "fixture",
            "limit_price": 1.25,
            "manual_confirmed": True,
            "requested_by": "manual",
        },
    )["intent"]

    assert agent_blocked["status"] == "blocked"
    assert any("LLM/Agent" in item for item in agent_blocked["blockers"])
    assert ready["status"] == "ready"
    assert ready["quantity"] == 1
    assert ready["estimated_premium_usd"] == 125.0
    assert ready["risk"]["max_daily_premium_usd"] == 500.0


def test_option_paper_order_submits_limit_ticket_and_cancel_with_fake_broker(tmp_path):
    db_path = tmp_path / "market.sqlite3"
    outputs_dir = tmp_path / "outputs"
    option_symbol = options_chain("SPY", source="fixture")["contracts"][0]["option_symbol"]
    record_pilot_journal_entry(
        outputs_dir,
        {
            "symbol": "SPY",
            "option_symbol": option_symbol,
            "status": "reviewed",
            "source_type": "fixture",
            "profile_id": "strict_local_v1",
            "market_date": "2026-06-15",
            "stock_kline_checked": True,
            "option_kline_checked": True,
            "lens_checked": True,
        },
        db_path=db_path,
    )
    intent = create_option_order_intent(
        db_path=db_path,
        outputs_dir=outputs_dir,
        payload={
            "option_symbol": option_symbol,
            "source_type": "fixture",
            "limit_price": 1.25,
            "manual_confirmed": True,
        },
    )["intent"]
    fake = FakeAlpacaPaperBroker()

    submitted = submit_option_paper_order(
        db_path=db_path,
        intent_id=intent["id"],
        manual_confirmed=True,
        broker=fake,
    )
    cancelled = cancel_option_paper_order(db_path=db_path, order_id=submitted["order"]["id"], broker=fake)

    assert fake.submitted[0]["type"] == "limit"
    assert fake.submitted[0]["time_in_force"] == "day"
    assert fake.submitted[0]["position_intent"] == "buy_to_open"
    assert fake.submitted[0]["side"] == "buy"
    assert submitted["order"]["broker_order_id"] == "alpaca-paper-order-1"
    assert submitted["safety"]["live_order_submission_enabled"] is False
    assert cancelled["order"]["status"] == "cancel_requested"
    assert fake.cancelled == ["alpaca-paper-order-1"]


def test_options_broker_api_endpoints_are_visible_and_safe(tmp_path):
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
    option_symbol = options_chain("SPY", source="fixture")["contracts"][0]["option_symbol"]

    status = client.get("/api/broker/options/status").json()
    intent = client.post(
        "/api/options/order-intents",
        json={
            "option_symbol": option_symbol,
            "source_type": "fixture",
            "limit_price": 1.25,
            "manual_confirmed": True,
        },
    ).json()["intent"]

    assert status["broker"] == "alpaca"
    assert status["mode"] == "paper"
    assert status["live_order_submission_enabled"] is False
    assert intent["status"] == "blocked"
    assert any("journal checklist" in item for item in intent["blockers"])
