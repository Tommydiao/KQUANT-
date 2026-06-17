from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from btc_eth_15m.live_market import DEFAULT_LIVE_SYMBOL, safe_live_ticker
from btc_eth_15m.agent_harness.risk_manager import RiskManager
from btc_eth_15m.agent_harness.state_store import StateStore
from btc_eth_15m.agent_harness.tool_base import READ_ONLY, SIMULATION, WRITE_LOW_RISK, ToolBase
from btc_eth_15m.options_lab import options_worthiness_report, write_options_worthiness_report
from btc_eth_15m.options_snapshots import attach_scan_snapshot


class MockMarketDataTool(ToolBase):
    name = "mock_market_data"
    description = "Return deterministic mock OHLCV data for dry-run harness tasks."
    permission_level = READ_ONLY
    requires_approval = False

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "required": ["symbols"]}

    def execute(self, input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        symbols = [str(symbol).upper() for symbol in input_data.get("symbols", [])]
        timeframe = str(input_data.get("timeframe", "15m"))
        candles = []
        for symbol in symbols:
            candles.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "source_type": "mock",
                    "open": 100.0,
                    "high": 102.0,
                    "low": 99.0,
                    "close": 101.0,
                    "volume": 1000.0,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        return {
            "source_type": "mock",
            "symbols": symbols,
            "timeframe": timeframe,
            "candles": candles,
            "warning": "Mock market data is not real-time market data.",
        }


class BacktestTool(ToolBase):
    name = "backtest"
    description = "Create a dry-run backtest record from task payload or mock market data."
    permission_level = READ_ONLY
    requires_approval = False

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "required": ["strategy_id"]}

    def execute(self, input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        store: StateStore = context["store"]
        task_id = context.get("task_id")
        strategy_id = str(input_data.get("strategy_id"))
        symbols = input_data.get("symbols") or ["BTCUSDT", "ETHUSDT"]
        metrics = {
            "total_return_pct": float(input_data.get("total_return_pct", 0.0)),
            "max_drawdown_pct": float(input_data.get("max_drawdown_pct", 0.0)),
            "win_rate_pct": float(input_data.get("win_rate_pct", 0.0)),
            "trade_count": int(input_data.get("trade_count", 0)),
            "source_type": input_data.get("source_type", "mock"),
        }
        result = store.create_backtest_result(
            task_id=task_id,
            strategy_id=strategy_id,
            symbol=",".join(str(symbol).upper() for symbol in symbols),
            timeframe=str(input_data.get("timeframe", "15m")),
            start_time=input_data.get("start_time"),
            end_time=input_data.get("end_time"),
            metrics=metrics,
            summary=str(input_data.get("summary", "Dry-run backtest record created by Agent Harness.")),
        )
        return {"backtest_result_id": result["id"], "strategy_id": strategy_id, "metrics": metrics}


class LiveMarketDataTool(ToolBase):
    name = "live_market_data"
    description = "Read BTCUSDT public live ticker and local BTC 15m freshness without credentials."
    permission_level = READ_ONLY
    requires_approval = False

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "required": []}

    def execute(self, input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        symbol = str(input_data.get("symbol") or DEFAULT_LIVE_SYMBOL).upper()
        ticker = input_data.get("ticker_override")
        if ticker is not None:
            ticker = dict(ticker)
            ticker.setdefault("symbol", symbol)
            ticker.setdefault("source_type", "public_live_market_data")
        else:
            ticker = safe_live_ticker(symbol, timeout=float(input_data.get("timeout", 4.0)))
        freshness = self._freshness(context["store"].db_path, symbol)
        return {
            "source_type": "public_live_market_data",
            "symbol": symbol,
            "ticker": ticker,
            "kline_freshness": freshness,
            "kline_refresh": input_data.get("kline_refresh") or {},
            "limitations": [
                "Public live ticker is read-only and does not authorize trading.",
                "Strategy signals still require validated 15m kline freshness and research evidence.",
            ],
        }

    def _freshness(self, db_path: Path, symbol: str) -> dict[str, Any]:
        try:
            with sqlite3.connect(db_path) as connection:
                connection.row_factory = sqlite3.Row
                row = connection.execute(
                    """
                    SELECT symbol, COUNT(*) AS rows, MAX(open_time) AS latest_open_time,
                           MAX(open_time_iso) AS latest_open_time_iso
                    FROM klines
                    WHERE symbol = ? AND interval = '15m'
                    GROUP BY symbol
                    """,
                    (symbol,),
                ).fetchone()
        except sqlite3.Error as exc:
            return {
                "symbol": symbol,
                "interval": "15m",
                "rows": 0,
                "latest_open_time": None,
                "latest_open_time_iso": None,
                "age_seconds": None,
                "is_fresh": False,
                "error": str(exc),
            }
        if not row:
            return {
                "symbol": symbol,
                "interval": "15m",
                "rows": 0,
                "latest_open_time": None,
                "latest_open_time_iso": None,
                "age_seconds": None,
                "is_fresh": False,
                "error": None,
            }
        latest_iso = row["latest_open_time_iso"]
        age_seconds = None
        if latest_iso:
            try:
                latest_dt = datetime.fromisoformat(str(latest_iso).replace("Z", "+00:00"))
                if latest_dt.tzinfo is None:
                    latest_dt = latest_dt.replace(tzinfo=timezone.utc)
                age_seconds = (datetime.now(timezone.utc) - latest_dt.astimezone(timezone.utc)).total_seconds()
            except ValueError:
                age_seconds = None
        return {
            "symbol": symbol,
            "interval": "15m",
            "rows": int(row["rows"] or 0),
            "latest_open_time": row["latest_open_time"],
            "latest_open_time_iso": latest_iso,
            "age_seconds": age_seconds,
            "is_fresh": bool(age_seconds is not None and age_seconds <= 60 * 60),
            "error": None,
        }


class RiskCheckTool(ToolBase):
    name = "risk_check"
    description = "Run harness risk checks and persist the risk result."
    permission_level = READ_ONLY
    requires_approval = False

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "required": ["action_type"]}

    def execute(self, input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        risk_manager: RiskManager = context["risk_manager"]
        return risk_manager.check_action(
            task_id=context.get("task_id"),
            action_type=str(input_data["action_type"]),
            payload=dict(input_data.get("payload") or {}),
        )


class USOptionsScannerTool(ToolBase):
    name = "us_options_scanner"
    description = "Read public US equities momentum and public option-chain data for options research."
    permission_level = READ_ONLY
    requires_approval = False

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "required": []}

    def execute(self, input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if input_data.get("scanner_override") is not None:
            override = dict(input_data["scanner_override"])
            override.setdefault("source_type", "eval_fixture_override")
            override.setdefault("overall_recommendation", "NO TRADE")
            override.setdefault("evaluations", [])
            override.setdefault("daily_candidates", [])
            override.setdefault("provider_errors", [])
            override.setdefault("limitations", ["Deterministic scanner override for Agent evaluation."])
            override.setdefault("safety", {"broker_key_required": False, "order_submission_wired": False, "live_locked": True})
            return _finalize_options_scan_payload(context, override)
        symbols = input_data.get("symbols")
        if symbols is not None:
            symbols = [str(symbol).upper() for symbol in symbols]
        report_kwargs = {
            "symbols": symbols,
            "outputs_dir": context.get("outputs_dir") or "outputs",
            "source": str(input_data.get("source", "live")),
            "timeout": float(input_data.get("timeout", 8.0)),
            "max_chain_symbols": int(input_data.get("max_chain_symbols", 4)),
        }
        if "universe" in input_data:
            report_kwargs["universe"] = str(input_data.get("universe") or "default")
        payload = options_worthiness_report(**report_kwargs)
        return _finalize_options_scan_payload(context, payload)


class ReportTool(ToolBase):
    name = "report"
    description = "Write a dry-run markdown and JSON report for a harness task."
    permission_level = WRITE_LOW_RISK
    requires_approval = False

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "required": ["task_id"]}

    def execute(self, input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        outputs_dir = Path(context.get("outputs_dir") or "outputs")
        outputs_dir.mkdir(parents=True, exist_ok=True)
        task_id = str(input_data["task_id"])
        payload = dict(input_data.get("payload") or {})
        base = outputs_dir / f"{task_id}-agent-report"
        md_path = base.with_suffix(".md")
        json_path = base.with_suffix(".json")
        report = {
            "task_id": task_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": payload.get("summary", "Agent Harness dry-run report."),
            "data_source": payload.get("data_source", "mock/read-only"),
            "strategy_id": payload.get("strategy_id"),
            "market_data": payload.get("market_data"),
            "data_audit": payload.get("data_audit") or _options_data_audit(payload.get("market_data") or {}),
            "risk_result": payload.get("risk_result"),
            "approval_status": payload.get("approval_status"),
            "limitations": payload.get("limitations") or [
                "This MVP report does not authorize live trading.",
                "Mock data must not be treated as real-time market data.",
            ],
        }
        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        md_path.write_text(render_report_markdown(report), encoding="utf-8")
        return {"report_path": str(md_path), "report_json_path": str(json_path), "report": report}


class PaperTradingTool(ToolBase):
    name = "paper_trading"
    description = "Create a local simulated paper order without calling any exchange API."
    permission_level = SIMULATION
    requires_approval = False

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "required": ["symbol", "side", "quantity", "price"]}

    def execute(self, input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        store: StateStore = context["store"]
        order = store.create_paper_order(
            task_id=context.get("task_id"),
            symbol=str(input_data["symbol"]).upper(),
            side=str(input_data["side"]).lower(),
            order_type=str(input_data.get("order_type", "market")),
            quantity=float(input_data["quantity"]),
            price=float(input_data["price"]),
            status="filled",
            strategy_id=input_data.get("strategy_id"),
            metadata={
                "source": "agent_harness",
                "exchange_call": False,
                "notes": input_data.get("notes", "Simulated paper order."),
            },
        )
        context["audit"].record(
            "order.paper.created",
            task_id=context.get("task_id"),
            actor="paper_trading_tool",
            message=f"Paper order created: {order['symbol']} {order['side']}",
            status="filled",
            metadata={"paper_order_id": order["id"], "exchange_call": False},
        )
        return {"paper_order": order, "exchange_call": False}


def render_report_markdown(report: dict[str, Any]) -> str:
    audit = report.get("data_audit") or _options_data_audit(report.get("market_data") or {})
    freshness = audit.get("freshness") or {}
    provider = audit.get("provider_status") or {}
    lines = [
        "# Agent Harness Report",
        "",
        f"- task_id: `{report.get('task_id')}`",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- data_source: `{report.get('data_source')}`",
        f"- strategy_id: `{report.get('strategy_id')}`",
        "",
        "## Summary",
        "",
        str(report.get("summary") or "-"),
        "",
        "## Data Freshness / Provider Status",
        "",
        f"- snapshot_id: `{audit.get('snapshot_id') or '-'}`",
        f"- fresh: `{freshness.get('is_fresh', 'unknown')}`",
        f"- age_seconds: `{freshness.get('age_seconds', '-')}`",
        f"- provider_available: `{provider.get('provider_available', 'unknown')}`",
        f"- provider_error_count: `{audit.get('provider_error_count', provider.get('provider_error_count', 0))}`",
        f"- decision_available: `{provider.get('decision_available', 'unknown')}`",
        "",
        "## Market Data",
        "",
        "```json",
        json.dumps(report.get("market_data") or {}, indent=2, ensure_ascii=False),
        "```",
        "",
        "## Risk Result",
        "",
        "```json",
        json.dumps(report.get("risk_result") or {}, indent=2, ensure_ascii=False),
        "```",
        "",
        "## Approval Status",
        "",
        str(report.get("approval_status") or "none"),
        "",
        "## Limitations",
        "",
    ]
    lines.extend([f"- {item}" for item in report.get("limitations", [])])
    return "\n".join(lines) + "\n"


def _finalize_options_scan_payload(context: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    enriched = _attach_options_scan_snapshot(context, payload)
    outputs_dir = Path(context.get("outputs_dir") or "outputs")
    report_paths = write_options_worthiness_report(enriched, outputs_dir)
    enriched.update(report_paths)
    return enriched


def _attach_options_scan_snapshot(context: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    store = context.get("store")
    if not isinstance(store, StateStore):
        next_payload = dict(payload)
        next_payload.setdefault("provider_error_count", len(next_payload.get("provider_errors") or []))
        return next_payload
    return attach_scan_snapshot(store.db_path, payload)


def _options_data_audit(scanner: dict[str, Any]) -> dict[str, Any]:
    provider_status = scanner.get("provider_status") if isinstance(scanner.get("provider_status"), dict) else {}
    provider_errors = scanner.get("provider_errors") or provider_status.get("provider_errors") or []
    return {
        "snapshot_id": scanner.get("snapshot_id"),
        "freshness": scanner.get("freshness") if isinstance(scanner.get("freshness"), dict) else {},
        "provider_status": provider_status,
        "provider_error_count": scanner.get("provider_error_count", provider_status.get("provider_error_count", len(provider_errors))),
        "provider_errors": provider_errors,
    }


def register_default_tools(registry: Any) -> None:
    registry.register(MockMarketDataTool())
    registry.register(LiveMarketDataTool())
    registry.register(USOptionsScannerTool())
    registry.register(BacktestTool())
    registry.register(RiskCheckTool())
    registry.register(ReportTool())
    registry.register(PaperTradingTool())
