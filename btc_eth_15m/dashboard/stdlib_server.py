from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import re
import sqlite3
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import Request, urlopen

from btc_eth_15m.agent_harness.eval import AgentEvaluator
from btc_eth_15m.agent_harness.runtime import default_runtime
from btc_eth_15m.live_market import BINANCE_FAPI_BASE, DEFAULT_LIVE_SYMBOL, safe_live_ticker
from btc_eth_15m.options_lab import (
    options_atm_alerts,
    options_atm_alerts_latest,
    options_chain,
    options_contract,
    options_daily_candidates,
    options_live_pilot_status,
    options_model_surface,
    options_price_history,
    options_underlyings,
    options_worthiness_report,
)
from btc_eth_15m.options_broker import (
    broker_account as options_broker_account,
    broker_positions as options_broker_positions,
    broker_status as options_broker_status,
    cancel_option_paper_order,
    create_option_order_intent,
    submit_option_paper_order,
)
from btc_eth_15m.options_pilot_journal import load_pilot_journal, record_pilot_journal_entry
from btc_eth_15m.options_snapshots import (
    annotate_options_payload,
    attach_chain_snapshot,
    attach_price_history_snapshot,
    attach_scan_snapshot,
    latest_options_chain_payload,
    latest_options_snapshot,
    latest_price_history_payload,
)
from kquant.stock_signals import (
    api_stock_ai_daily_agent,
    api_stock_ai_daily_report_latest,
    api_stock_ai_decision,
    api_stock_ai_review,
    api_stock_ai_review_status,
    api_stock_analyze,
    api_stock_candles,
    api_stock_live_data_health,
    api_stock_live_data_health_latest,
    api_stock_market_regime,
    api_stock_market_data_status,
    api_stock_market_data_self_check,
    api_stock_monday_readiness_latest,
    api_stock_provider_health,
    api_stock_quote,
    api_stock_realtime_snapshot,
    api_stock_research_chat,
    api_stock_search,
    api_stock_signal_journal,
    api_stock_signal_journal_entry,
    api_stock_signals,
    api_stock_signals_latest,
    api_stock_strategy_validation,
    api_stock_universe,
)
from kquant.mstr_cycle import api_mstr_cycle_history, api_mstr_cycle_journal, api_mstr_cycle_journal_entry, api_mstr_cycle_radar


RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
MAX_CHART_BARS = 500
INTERVAL = "15m"
INTERVAL_MS = 15 * 60 * 1000
SYMBOLS = ["BTCUSDT", "ETHUSDT"]


class ReadOnlyDashboard:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.db_path = self.root / "work" / "market.sqlite3"
        self.stock_db_path = self.root / "work" / "kquant_us.sqlite3"
        self.runs_dir = self.root / "work" / "runs"
        self.outputs_dir = self.root / "outputs"
        dist_index = self.root / "web" / "dist" / "index.html"
        self.index_path = dist_index if dist_index.exists() else self.root / "btc_eth_15m" / "dashboard" / "static" / "index.html"
        self.agent_runtime = default_runtime(self.db_path, self.outputs_dir)
        self._live_market_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._btc_kline_refresh_cache: Tuple[float, Dict[str, Any]] | None = None

    def status(self, mode: str) -> Dict[str, Any]:
        freshness = self.market_freshness()
        btc_refresh = self.legacy_btc_kline_refresh_status()
        budget = self.risk_budget(mode)
        live_market = self.live_market(DEFAULT_LIVE_SYMBOL)
        return {
            "app": "kquant ATM Options Signal Assistant",
            "product_focus": "US ATM options local workbench",
            "mode": mode,
            "symbols": SYMBOLS,
            "interval": INTERVAL,
            "exchange": "Alpaca Paper US Options",
            "live_locked": True,
            "kill_switch_enabled": False,
            "leverage_range": [7, 15],
            "margin_caps": {
                "single_order_usdt": budget["single_order_cap_usdt"],
                "open_usdt": budget["open_margin_cap_usdt"],
                "daily_usdt": budget["daily_margin_cap_usdt"],
                "daily_loss_usdt": budget["daily_loss_cap_usdt"],
                "max_notional_at_15x_usdt": budget["max_notional_at_max_leverage_usdt"],
                "max_notional_at_max_leverage_usdt": budget["max_notional_at_max_leverage_usdt"],
            },
            "risk_budget": budget,
            "broker": options_broker_status(),
            "legacy_crypto": {
                "exchange": "Binance USD-M Futures",
                "broker": self.broker_status(mode),
                "symbols": SYMBOLS,
                "interval": INTERVAL,
                "live_market": live_market,
                "live_btc_kline_refresh": btc_refresh,
            },
            "last_self_check": self.exchange_self_check_summary(mode),
            "last_sync": self.exchange_sync_summary(mode),
            "market_freshness": freshness,
            "live_market": live_market,
            "live_btc_kline_refresh": btc_refresh,
            "risk_gates": self.risk_gates(mode, freshness),
        }

    def live_market(self, symbol: str = DEFAULT_LIVE_SYMBOL) -> Dict[str, Any]:
        normalized = "".join(ch for ch in str(symbol).upper() if ch.isalnum())[:24] or DEFAULT_LIVE_SYMBOL
        cached = self._live_market_cache.get(normalized)
        if cached and time.monotonic() - cached[0] <= 3:
            return cached[1]
        payload = safe_live_ticker(normalized, timeout=4.0)
        self._live_market_cache[normalized] = (time.monotonic(), payload)
        return payload

    def refresh_live_btc_klines(self) -> Dict[str, Any]:
        if self._btc_kline_refresh_cache and time.monotonic() - self._btc_kline_refresh_cache[0] <= 60:
            return self._btc_kline_refresh_cache[1]
        try:
            result = self.fetch_recent_btc_klines()
            payload = {
                "ok": True,
                "symbol": DEFAULT_LIVE_SYMBOL,
                "rows": result["rows"],
                "start_time": result["start_time"],
                "end_time": result["end_time"],
                "source": "Binance USD-M Futures public REST",
                "refreshed_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            }
        except Exception as exc:  # pragma: no cover - network and SQLite defensive path
            payload = {
                "ok": False,
                "symbol": DEFAULT_LIVE_SYMBOL,
                "rows": 0,
                "start_time": None,
                "end_time": None,
                "source": "Binance USD-M Futures public REST",
                "refreshed_at": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            }
        self._btc_kline_refresh_cache = (time.monotonic(), payload)
        return payload

    def legacy_btc_kline_refresh_status(self) -> Dict[str, Any]:
        if self._btc_kline_refresh_cache and time.monotonic() - self._btc_kline_refresh_cache[0] <= 60:
            return self._btc_kline_refresh_cache[1]
        return {
            "ok": False,
            "skipped": True,
            "symbol": DEFAULT_LIVE_SYMBOL,
            "rows": 0,
            "start_time": None,
            "end_time": None,
            "source": "Legacy Binance USD-M Futures public REST",
            "refreshed_at": None,
            "error": "Legacy BTC refresh is not triggered by /api/status.",
        }

    def fetch_recent_btc_klines(self) -> Dict[str, Any]:
        end_ms = int(time.time() * 1000) - INTERVAL_MS
        start_ms = end_ms - 15 * INTERVAL_MS
        query = urlencode(
            {
                "symbol": DEFAULT_LIVE_SYMBOL,
                "interval": INTERVAL,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 16,
            }
        )
        request = Request(
            f"{BINANCE_FAPI_BASE}/fapi/v1/klines?{query}",
            headers={"User-Agent": "kquant-live-btc-klines/0.1"},
        )
        with urlopen(request, timeout=8) as response:  # noqa: S310 - fixed public Binance endpoint
            rows = json.loads(response.read().decode("utf-8"))
        parsed = [self.parse_kline_row(DEFAULT_LIVE_SYMBOL, row) for row in rows]
        if parsed:
            with sqlite3.connect(self.db_path) as connection:
                connection.execute("PRAGMA busy_timeout=5000")
                self.ensure_kline_schema(connection)
                connection.executemany(
                    """
                    INSERT OR REPLACE INTO klines (
                        symbol, interval, open_time, open_time_iso, close_time,
                        open, high, low, close, volume, quote_volume, trades, fetched_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    parsed,
                )
                connection.commit()
        return {
            "rows": len(parsed),
            "start_time": iso_from_millis(parsed[0][2]) if parsed else None,
            "end_time": iso_from_millis(parsed[-1][2]) if parsed else None,
        }

    @staticmethod
    def ensure_kline_schema(connection: sqlite3.Connection) -> None:
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

    @staticmethod
    def parse_kline_row(symbol: str, row: List[Any]) -> Tuple[Any, ...]:
        open_time = int(row[0])
        return (
            symbol,
            INTERVAL,
            open_time,
            iso_from_millis(open_time),
            int(row[6]),
            float(row[1]),
            float(row[2]),
            float(row[3]),
            float(row[4]),
            float(row[5]),
            float(row[7]),
            int(row[8]),
            datetime.now(timezone.utc).isoformat(),
        )

    def latest_signals(self, mode: str) -> Dict[str, Any]:
        return {"mode": mode, "signals": []}

    def replay_drafts(self, limit: int) -> Dict[str, Any]:
        return {"mode": "paper", "drafts": []}

    def positions(self, mode: str) -> Dict[str, Any]:
        rows = self.table_rows(
            "SELECT * FROM dashboard_positions WHERE mode = ? AND status = 'open' ORDER BY updated_at DESC",
            (mode,),
        )
        return {"mode": mode, "positions": rows}

    def orders(self, mode: str) -> Dict[str, Any]:
        rows = self.table_rows(
            "SELECT * FROM dashboard_orders WHERE mode = ? ORDER BY updated_at DESC LIMIT 80",
            (mode,),
        )
        return {"mode": mode, "orders": rows}

    def logs(self, limit: int) -> Dict[str, Any]:
        rows = self.table_rows(
            "SELECT level, message, payload_json, created_at FROM dashboard_events ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return {"events": rows}

    def readiness(self) -> Dict[str, Any]:
        freshness = self.market_freshness()
        testnet_self_check = self.exchange_self_check_summary("testnet")
        testnet_sync = self.exchange_sync_summary("testnet")
        blockers: List[str] = []
        if not testnet_self_check or not testnet_self_check.get("passed"):
            blockers.append("Binance Testnet self-check has not passed.")
        if testnet_self_check and not testnet_self_check.get("is_fresh"):
            blockers.append("Binance Testnet self-check is stale.")
        blockers.append("Binance Testnet credentials/sync are not verified.")
        if not testnet_sync or not testnet_sync.get("passed"):
            blockers.append("Binance Testnet sync snapshot has not passed.")
        if testnet_sync and not testnet_sync.get("is_fresh"):
            blockers.append("Binance Testnet sync snapshot is stale.")
        if not all(item.get("is_fresh") for item in freshness):
            blockers.append("Market data is stale or missing.")
        blockers.append("Live trading is locked in config.")
        blockers.append("Live order submission is not wired.")
        live_budget = self.risk_budget("live")
        return {
            "ready_for_live": False,
            "blockers": blockers,
            "readiness_checks": [
                {
                    "name": "live_locked",
                    "passed": False,
                    "message": "Live trading is locked in config.",
                },
                {
                    "name": "market_data",
                    "passed": all(item.get("is_fresh") for item in freshness),
                    "message": "BTC/ETH market data freshness check.",
                },
            ],
            "paper": self.broker_status("paper"),
            "testnet": self.broker_status("testnet"),
            "testnet_self_check": None,
            "testnet_self_check_summary": testnet_self_check,
            "testnet_sync": testnet_sync,
            "market_freshness": freshness,
            "live": self.broker_status("live"),
            "live_risk_budget": live_budget,
            "live_rules": {
                "manual_confirmation_required": True,
                "leverage_range": [7, 15],
                "single_order_margin_cap_usdt": live_budget["single_order_cap_usdt"],
                "open_margin_cap_usdt": live_budget["open_margin_cap_usdt"],
                "daily_margin_cap_usdt": live_budget["daily_margin_cap_usdt"],
                "daily_loss_cap_usdt": live_budget["daily_loss_cap_usdt"],
                "order_submission_enabled": False,
            },
        }

    def latest_research_summary(self) -> Dict[str, Any]:
        summary_path = self.latest_path("*-summary.json")
        summary = self.load_json(summary_path) if summary_path else {}
        daily = summary.get("daily_return_stats", {}) if isinstance(summary, dict) else {}
        v2_path = self.latest_path("*-v2-research-report.md")
        v2 = self.parse_v2_report(v2_path)
        sweep_path = self.latest_path("*-sweep.csv")
        best_sweep = self.best_sweep_row(sweep_path)
        best = best_sweep or v2.get("best_variant") or {}
        metric_source = best or summary
        generated_from = sweep_path if best_sweep else v2_path or summary_path
        return {
            "status": "ready" if summary or v2 or best else "empty",
            "summary_path": str(summary_path) if summary_path else None,
            "summary_error": None,
            "v2_report_path": str(v2_path) if v2_path else None,
            "latest_sweep_path": str(sweep_path) if sweep_path else None,
            "run_id": metric_source.get("run_id") if metric_source else None,
            "total_return_pct": number(metric_source.get("total_return_pct")) if metric_source else None,
            "profit_factor": number(metric_source.get("profit_factor")) if metric_source else None,
            "avg_r": number(metric_source.get("avg_r")) if metric_source else None,
            "avg_daily_return_pct": number(best.get("avg_daily_return_pct") or v2.get("best_avg_daily_return_pct"))
            if best
            else number(daily.get("avg_daily_return_pct")),
            "target_range_hit_rate_pct": number(
                best.get("target_range_hit_rate_pct") or v2.get("best_target_range_hit_rate_pct")
            )
            if best
            else number(daily.get("target_range_hit_rate_pct")),
            "loss_day_rate_pct": number(best.get("loss_day_rate_pct")) if best else number(daily.get("loss_day_rate_pct")),
            "paper_observation_decision": v2.get("paper_observation_decision") or "NO",
            "daily_target_decision": v2.get("daily_target_decision") or "NO",
            "best_variant": best.get("variant") or v2.get("best_variant_name"),
            "best_run_id": best.get("run_id") or v2.get("best_variant", {}).get("run_id"),
            "generated_at": mtime_iso(generated_from),
        }

    def research_runs(self, limit: int) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        for path in self.outputs_dir.glob("*"):
            if not path.is_file():
                continue
            item = self.run_item(path)
            if item:
                rows.append(item)
        rows.sort(key=lambda item: item["modified_at_epoch"], reverse=True)
        return {"runs": [{k: v for k, v in row.items() if k != "modified_at_epoch"} for row in rows[:limit]]}

    def research_trades(self, run_id: Optional[str], symbol: Optional[str], limit: int, offset: int) -> Dict[str, Any]:
        resolved_run_id = self.resolve_replay_run_id(run_id)
        rows = self.filter_trades(self.load_trade_rows(resolved_run_id), symbol)
        return {
            "run_id": resolved_run_id,
            "symbol": symbol,
            "total": len(rows),
            "limit": limit,
            "offset": offset,
            "trades": rows[offset : offset + limit],
        }

    def research_chart(
        self,
        run_id: Optional[str],
        symbol: Optional[str],
        trade_id: Optional[str],
        pre_bars: int,
        post_bars: int,
    ) -> Dict[str, Any]:
        resolved_run_id = self.resolve_replay_run_id(run_id)
        rows = self.filter_trades(self.load_trade_rows(resolved_run_id), symbol)
        if not rows:
            return {
                "run_id": resolved_run_id,
                "symbol": symbol,
                "selected_trade": None,
                "trades": [],
                "candles": [],
                "window": None,
            }
        selected = self.selected_trade(rows, trade_id)
        selected_symbol = str(selected["symbol"])
        entry_ms = millis_from_trade_time(str(selected["entry_time"]))
        exit_ms = millis_from_trade_time(str(selected["exit_time"]))
        start_ms = entry_ms - pre_bars * INTERVAL_MS
        end_ms = exit_ms + post_bars * INTERVAL_MS
        max_span = (MAX_CHART_BARS - 1) * INTERVAL_MS
        if end_ms - start_ms > max_span:
            end_ms = start_ms + max_span
        candles = self.load_candles(selected_symbol, start_ms, end_ms)
        window_trades = [
            row
            for row in rows
            if row.get("symbol") == selected_symbol and trade_overlaps(row, start_ms=start_ms, end_ms=end_ms)
        ]
        return {
            "run_id": resolved_run_id,
            "symbol": selected_symbol,
            "selected_trade": selected,
            "trades": window_trades,
            "candles": candles,
            "window": {
                "start_time": iso_from_millis(start_ms),
                "end_time": iso_from_millis(end_ms),
                "pre_bars": pre_bars,
                "post_bars": post_bars,
                "interval": INTERVAL,
            },
        }

    def market_freshness(self) -> List[Dict[str, Any]]:
        rows = self.table_rows(
            """
            SELECT symbol, COUNT(*) AS rows, MAX(open_time) AS latest_open_time,
                   MAX(open_time_iso) AS latest_open_time_iso
            FROM klines
            WHERE interval = ?
            GROUP BY symbol
            """,
            (INTERVAL,),
        )
        by_symbol = {row["symbol"]: row for row in rows}
        now = datetime.now(timezone.utc)
        result: List[Dict[str, Any]] = []
        for symbol in SYMBOLS:
            row = by_symbol.get(symbol, {})
            latest_iso = row.get("latest_open_time_iso")
            age_seconds: Optional[float] = None
            if latest_iso:
                try:
                    age_seconds = (now - parse_dt(str(latest_iso))).total_seconds()
                except ValueError:
                    age_seconds = None
            result.append(
                {
                    "symbol": symbol,
                    "interval": INTERVAL,
                    "rows": int(row.get("rows") or 0),
                    "latest_open_time": row.get("latest_open_time"),
                    "latest_open_time_iso": latest_iso,
                    "age_seconds": age_seconds,
                    "is_fresh": bool(age_seconds is not None and age_seconds <= 60 * 60),
                }
            )
        return result

    def risk_budget(self, mode: str) -> Dict[str, Any]:
        single_cap = 25.0
        open_cap = 50.0
        daily_cap = 50.0
        daily_loss_cap = 200.0
        open_used = 0.0
        daily_used = 0.0
        daily_loss_used = 0.0
        return {
            "mode": mode,
            "single_order_cap_usdt": single_cap,
            "open_margin_cap_usdt": open_cap,
            "open_margin_used_usdt": open_used,
            "open_margin_remaining_usdt": open_cap - open_used,
            "daily_margin_cap_usdt": daily_cap,
            "daily_margin_used_usdt": daily_used,
            "daily_margin_remaining_usdt": daily_cap - daily_used,
            "daily_loss_cap_usdt": daily_loss_cap,
            "daily_loss_used_usdt": daily_loss_used,
            "daily_loss_remaining_usdt": daily_loss_cap - daily_loss_used,
            "max_notional_at_max_leverage_usdt": single_cap * 15.0,
        }

    def broker_status(self, mode: str) -> Dict[str, Any]:
        if mode == "paper":
            return {
                "mode": mode,
                "connected": True,
                "order_submission_enabled": True,
                "message": "Paper broker is local and read-only in stdlib fallback.",
            }
        return {
            "mode": mode,
            "connected": False,
            "order_submission_enabled": False,
            "message": "Exchange credentials are not verified in stdlib fallback.",
        }

    def risk_gates(self, mode: str, freshness: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        market_ok = all(item.get("is_fresh") for item in freshness)
        return [
            {
                "name": "live_locked",
                "passed": mode != "live",
                "message": "Live trading is locked in config.",
            },
            {
                "name": "market_data",
                "passed": market_ok,
                "message": "BTC/ETH market data is fresh." if market_ok else "BTC/ETH market data is stale or missing.",
            },
            {
                "name": "manual_confirmation",
                "passed": True,
                "message": "Manual confirmation remains required for any state-changing action.",
            },
        ]

    def exchange_self_check_summary(self, mode: str) -> Optional[Dict[str, Any]]:
        rows = self.table_rows(
            "SELECT mode, passed, checked_at, checks_json FROM dashboard_exchange_self_checks WHERE mode = ?",
            (mode,),
        )
        if not rows:
            return None
        row = rows[0]
        checked_at = row.get("checked_at")
        age_seconds = age_since(checked_at)
        checks = parse_json_value(row.get("checks_json"), [])
        failed = [item.get("name") for item in checks if isinstance(item, dict) and not item.get("passed")]
        return {
            "mode": mode,
            "passed": bool(row.get("passed")),
            "checked_at": checked_at,
            "age_seconds": age_seconds,
            "max_age_seconds": 900,
            "is_fresh": bool(age_seconds is not None and age_seconds <= 900),
            "failed_checks": failed,
        }

    def exchange_sync_summary(self, mode: str) -> Optional[Dict[str, Any]]:
        rows = self.table_rows(
            """
            SELECT mode, passed, synced_at, checks_json, positions_json, orders_json
            FROM dashboard_exchange_syncs
            WHERE mode = ?
            """,
            (mode,),
        )
        if not rows:
            return None
        row = rows[0]
        synced_at = row.get("synced_at")
        age_seconds = age_since(synced_at)
        checks = parse_json_value(row.get("checks_json"), [])
        failed = [item.get("name") for item in checks if isinstance(item, dict) and not item.get("passed")]
        positions = parse_json_value(row.get("positions_json"), [])
        orders = parse_json_value(row.get("orders_json"), [])
        return {
            "mode": mode,
            "passed": bool(row.get("passed")),
            "synced_at": synced_at,
            "age_seconds": age_seconds,
            "max_age_seconds": 900,
            "is_fresh": bool(age_seconds is not None and age_seconds <= 900),
            "position_count": len(positions) if isinstance(positions, list) else 0,
            "order_count": len(orders) if isinstance(orders, list) else 0,
            "failed_checks": failed,
        }

    def parse_v2_report(self, path: Optional[Path]) -> Dict[str, Any]:
        if path is None:
            return {}
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return {}
        payload: Dict[str, Any] = {
            "best_variant_name": markdown_value(text, r"Best variant:\s*`([^`]+)`"),
            "best_avg_daily_return_pct": number(markdown_value(text, r"Best average daily return:\s*`([^`%]+)%`")),
            "best_target_range_hit_rate_pct": number(markdown_value(text, r"Best 5%-7% daily hit rate:\s*`([^`%]+)%`")),
            "daily_target_decision": markdown_value(text, r"Daily target decision:\s*\*\*(YES|NO)\*\*"),
            "paper_observation_decision": markdown_value(text, r"Paper observation decision:\s*\*\*(YES|NO)\*\*"),
        }
        for line in text.splitlines():
            if not line.startswith("| daily_"):
                continue
            cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
            if len(cells) >= 13 and cells[0] == payload.get("best_variant_name"):
                payload["best_variant"] = {
                    "variant": cells[0],
                    "mode": cells[1],
                    "regime_filter": cells[2],
                    "trade_count": number(cells[3]),
                    "profit_factor": number(cells[4]),
                    "avg_r": number(cells[5]),
                    "avg_daily_return_pct": number(cells[6].rstrip("%")),
                    "target_range_hit_rate_pct": number(cells[7].rstrip("%")),
                    "loss_day_rate_pct": number(cells[8].rstrip("%")),
                    "total_return_pct": number(cells[9].rstrip("%")),
                    "max_drawdown_pct": number(cells[10].rstrip("%")),
                    "positive_years": cells[11],
                    "run_id": cells[12],
                }
                break
        return payload

    def best_sweep_row(self, path: Optional[Path]) -> Optional[Dict[str, Any]]:
        if path is None:
            return None
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except OSError:
            return None
        if not rows:
            return None
        rows.sort(
            key=lambda row: (
                number(row.get("profit_factor")) or 0.0,
                number(row.get("avg_r")) or 0.0,
                number(row.get("total_return_pct")) or -999999.0,
            ),
            reverse=True,
        )
        row = dict(rows[0])
        for key in (
            "trade_count",
            "final_equity",
            "total_return_pct",
            "max_drawdown_pct",
            "win_rate_pct",
            "profit_factor",
            "expectancy",
            "avg_r",
            "avg_daily_return_pct",
            "target_range_hit_rate_pct",
            "above_target_min_rate_pct",
            "loss_day_rate_pct",
        ):
            row[key] = number(row.get(key))
        return row

    def run_item(self, path: Path) -> Optional[Dict[str, Any]]:
        kind = run_type(path)
        if kind is None:
            return None
        stat = path.stat()
        return {
            "type": kind,
            "path": str(path),
            "name": path.name,
            "run_id": run_id_from_output(path),
            "modified_at": mtime_iso(path),
            "modified_at_epoch": stat.st_mtime,
            "size_bytes": stat.st_size,
        }

    def resolve_replay_run_id(self, run_id: Optional[str]) -> str:
        if run_id:
            return validate_run_id(run_id)
        latest = self.latest_research_summary()
        candidate = latest.get("best_run_id") or latest.get("run_id")
        if not candidate:
            raise FileNotFoundError("No research run is available for replay.")
        return validate_run_id(str(candidate))

    def load_trade_rows(self, run_id: str) -> List[Dict[str, Any]]:
        path = self.trades_path(run_id)
        rows: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            for index, row in enumerate(csv.DictReader(handle)):
                parsed = trade_row(run_id, index, row)
                if parsed is not None:
                    rows.append(parsed)
        return rows

    def filter_trades(self, rows: List[Dict[str, Any]], symbol: Optional[str]) -> List[Dict[str, Any]]:
        if not symbol:
            return rows
        return [row for row in rows if row.get("symbol") == symbol]

    def selected_trade(self, rows: List[Dict[str, Any]], trade_id: Optional[str]) -> Dict[str, Any]:
        if trade_id:
            for row in rows:
                if row["id"] == trade_id:
                    return row
            raise FileNotFoundError("Trade was not found: {}".format(trade_id))
        return rows[0]

    def load_candles(self, symbol: str, start_ms: int, end_ms: int) -> List[Dict[str, Any]]:
        return self.table_rows(
            """
            SELECT symbol, interval, open_time, open_time_iso, close_time,
                   open, high, low, close, volume, quote_volume, trades
            FROM klines
            WHERE symbol = ? AND interval = ? AND open_time BETWEEN ? AND ?
            ORDER BY open_time ASC
            LIMIT ?
            """,
            (symbol, INTERVAL, start_ms, end_ms, MAX_CHART_BARS),
        )

    def trades_path(self, run_id: str) -> Path:
        safe_run_id = validate_run_id(run_id)
        runs_root = self.runs_dir.resolve()
        path = (runs_root / safe_run_id / "trades.csv").resolve()
        if path.parent.parent != runs_root:
            raise ValueError("Invalid run_id path.")
        if not path.exists():
            raise FileNotFoundError("Missing trades file for run_id: {}".format(safe_run_id))
        return path

    def latest_path(self, pattern: str) -> Optional[Path]:
        candidates = [path for path in self.outputs_dir.glob(pattern) if path.is_file()]
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_mtime)

    def load_json(self, path: Optional[Path]) -> Dict[str, Any]:
        if path is None:
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def table_rows(self, query: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        if not self.db_path.exists():
            return []
        connection = sqlite3.connect("file:{}?mode=ro".format(self.db_path), uri=True, timeout=5)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=5000")
            return [dict(row) for row in connection.execute(query, params).fetchall()]
        except sqlite3.Error:
            return []
        finally:
            connection.close()


class Handler(BaseHTTPRequestHandler):
    dashboard: ReadOnlyDashboard

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = unquote(parsed.path)
        try:
            if path in ("/", "/index.html"):
                self.send_file(self.dashboard.index_path, "text/html; charset=utf-8")
                return
            if path.startswith("/assets/"):
                asset_path = self.dashboard.root / "web" / "dist" / path.lstrip("/")
                self.send_file(asset_path, mimetypes.guess_type(asset_path.name)[0] or "application/octet-stream")
                return
            if path == "/vendor/three.module.js":
                three_path = Path(__file__).resolve().parents[2] / "web" / "node_modules" / "three" / "build" / "three.module.js"
                self.send_file(three_path, "text/javascript; charset=utf-8")
                return
            if path == "/vendor/lightweight-charts.standalone.production.js":
                charts_path = self.dashboard.index_path.parent / "vendor" / "lightweight-charts.standalone.production.js"
                self.send_file(charts_path, "text/javascript; charset=utf-8")
                return
            if path.startswith("/api/"):
                self.send_json(self.route_api(path, query))
                return
            if path == "/stream":
                self.send_stream()
                return
            self.send_file(self.dashboard.index_path, "text/html; charset=utf-8")
        except ValueError as exc:
            self.send_json({"detail": str(exc)}, HTTPStatus.BAD_REQUEST)
        except KeyError as exc:
            self.send_json({"detail": str(exc)}, HTTPStatus.NOT_FOUND)
        except FileNotFoundError as exc:
            self.send_json({"detail": str(exc)}, HTTPStatus.NOT_FOUND)
        except Exception as exc:  # pragma: no cover - defensive server boundary
            self.send_json({"detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path == "/api/options/pilot-journal/entry":
                self.send_json(record_pilot_journal_entry(self.dashboard.outputs_dir, self.read_json_body(), db_path=self.dashboard.db_path))
                return
            if path == "/api/mstr/cycle-journal/entry":
                self.send_json(api_mstr_cycle_journal_entry(self.read_json_body(), db_path=self.dashboard.stock_db_path))
                return
            if path == "/api/stocks/signal-journal/entry":
                self.send_json(api_stock_signal_journal_entry(self.read_json_body(), db_path=self.dashboard.stock_db_path))
                return
            if path == "/api/stocks/ai-review":
                self.send_json(api_stock_ai_review(self.read_json_body(), db_path=self.dashboard.stock_db_path))
                return
            if path == "/api/stocks/ai-decision":
                self.send_json(api_stock_ai_decision(self.read_json_body(), db_path=self.dashboard.stock_db_path))
                return
            if path == "/api/stocks/research-chat":
                self.send_json(api_stock_research_chat(self.read_json_body(), db_path=self.dashboard.stock_db_path))
                return
            if path == "/api/stocks/ai-daily-agent":
                self.send_json(
                    api_stock_ai_daily_agent(
                        self.read_json_body(),
                        db_path=self.dashboard.stock_db_path,
                        outputs_dir=self.dashboard.outputs_dir,
                    )
                )
                return
            if path == "/api/options/order-intents":
                self.send_json(
                    create_option_order_intent(
                        db_path=self.dashboard.db_path,
                        outputs_dir=self.dashboard.outputs_dir,
                        payload=self.read_json_body(),
                    )
                )
                return
            if path == "/api/options/paper-orders":
                body = self.read_json_body()
                self.send_json(
                    submit_option_paper_order(
                        db_path=self.dashboard.db_path,
                        intent_id=str(body.get("intent_id") or ""),
                        manual_confirmed=bool(body.get("manual_confirmed")),
                    )
                )
                return
            if path.startswith("/api/options/paper-orders/") and path.endswith("/cancel"):
                segments = path.strip("/").split("/")
                if len(segments) != 5:
                    raise FileNotFoundError("Unknown options paper order action: {}".format(path))
                self.send_json(cancel_option_paper_order(db_path=self.dashboard.db_path, order_id=segments[3]))
                return
            if path.startswith("/api/agent/"):
                self.send_json(self.route_agent_post(path, self.read_json_body()))
                return
        except ValueError as exc:
            self.send_json({"detail": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        except KeyError as exc:
            self.send_json({"detail": str(exc)}, HTTPStatus.NOT_FOUND)
            return
        except Exception as exc:  # pragma: no cover - defensive server boundary
            self.send_json({"detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.send_json(
            {
                "detail": "Read-only stdlib fallback does not execute state-changing actions.",
                "read_only": True,
            },
            HTTPStatus.METHOD_NOT_ALLOWED,
        )

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_cors_headers()
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def route_api(self, path: str, query: Dict[str, List[str]]) -> Dict[str, Any]:
        mode = query_value(query, "mode", "paper")
        if mode not in ("paper", "testnet", "live"):
            raise ValueError("Invalid mode.")
        if path == "/api/health":
            return self.api_health()
        if path == "/api/status":
            return self.dashboard.status(mode)
        if path == "/api/signals/latest":
            return self.dashboard.latest_signals(mode)
        if path == "/api/paper/replay-drafts":
            return self.dashboard.replay_drafts(query_int(query, "limit", 3, 1, 20))
        if path == "/api/positions":
            return self.dashboard.positions(mode)
        if path == "/api/orders":
            return self.dashboard.orders(mode)
        if path == "/api/logs":
            return self.dashboard.logs(query_int(query, "limit", 80, 1, 250))
        if path == "/api/readiness":
            return self.dashboard.readiness()
        if path == "/api/market/live":
            return self.dashboard.live_market(query_value(query, "symbol", DEFAULT_LIVE_SYMBOL))
        if path == "/api/stocks/universe":
            return api_stock_universe(
                universe=query_value(query, "universe", "default"),
                db_path=self.dashboard.stock_db_path,
            )
        if path == "/api/stocks/search":
            return api_stock_search(
                q=query_value(query, "q", ""),
                universe=query_value(query, "universe", "all"),
                limit=query_int(query, "limit", 24, 1, 50),
            )
        if path == "/api/stocks/candles":
            source = stock_live_only_source(query)
            return api_stock_candles(
                symbol=query_value(query, "symbol", "SPY"),
                range_value=query_value(query, "range", "1y"),
                interval=query_value(query, "interval", "1d"),
                source=source,
                db_path=self.dashboard.stock_db_path,
            )
        if path == "/api/stocks/quote":
            return api_stock_quote(
                symbol=query_value(query, "symbol", "SPY"),
                db_path=self.dashboard.stock_db_path,
            )
        if path == "/api/stocks/realtime-snapshot":
            return api_stock_realtime_snapshot(
                symbol=query_value(query, "symbol", "SPY"),
                db_path=self.dashboard.stock_db_path,
            )
        if path == "/api/stocks/market-data/status":
            return api_stock_market_data_status(db_path=self.dashboard.stock_db_path)
        if path == "/api/stocks/market-data/self-check":
            return api_stock_market_data_self_check(
                symbol=query_value(query, "symbol", "SPY"),
                db_path=self.dashboard.stock_db_path,
            )
        if path == "/api/stocks/strategy-validation":
            return api_stock_strategy_validation(
                db_path=self.dashboard.stock_db_path,
                profile=query_value(query, "profile", "") or None,
            )
        if path == "/api/stocks/signals":
            source = stock_live_only_source(query)
            return api_stock_signals(
                source=source,
                universe=query_value(query, "universe", "default"),
                profile=query_value(query, "profile", "swing_long_v1"),
                db_path=self.dashboard.stock_db_path,
                outputs_dir=self.dashboard.outputs_dir,
                limit=query_int(query, "limit", 100, 1, 300),
                layer=query_value(query, "layer", "") or None,
            )
        if path == "/api/stocks/signals/latest":
            source = stock_live_only_source(query)
            return api_stock_signals_latest(
                source=source,
                universe=query_value(query, "universe", "default"),
                profile=query_value(query, "profile", "swing_long_v1"),
                db_path=self.dashboard.stock_db_path,
                outputs_dir=self.dashboard.outputs_dir,
            )
        if path == "/api/stocks/provider-health":
            return api_stock_provider_health(db_path=self.dashboard.stock_db_path)
        if path == "/api/stocks/ai-review/status":
            return api_stock_ai_review_status()
        if path == "/api/stocks/ai-daily-report/latest":
            return api_stock_ai_daily_report_latest(outputs_dir=self.dashboard.outputs_dir)
        if path == "/api/stocks/analyze":
            source = stock_live_only_source(query)
            return api_stock_analyze(
                symbol=query_value(query, "symbol", "NVDA"),
                source=source,
                profile=query_value(query, "profile", "swing_long_v1"),
                db_path=self.dashboard.stock_db_path,
            )
        if path == "/api/stocks/market-regime":
            source = stock_live_only_source(query)
            return api_stock_market_regime(source=source, db_path=self.dashboard.stock_db_path)
        if path == "/api/stocks/signal-journal":
            return api_stock_signal_journal(
                db_path=self.dashboard.stock_db_path,
                symbol=query_value(query, "symbol", "") or None,
                limit=query_int(query, "limit", 50, 1, 200),
            )
        if path == "/api/stocks/live-data-health":
            universes = [
                item.strip()
                for item in query_value(query, "universes", "default,ai_five_layer").split(",")
                if item.strip()
            ]
            return api_stock_live_data_health(
                universes=universes,
                db_path=self.dashboard.stock_db_path,
                outputs_dir=self.dashboard.outputs_dir,
                limit=query_int(query, "limit", 20, 1, 300),
            )
        if path == "/api/stocks/live-data-health/latest":
            return api_stock_live_data_health_latest(outputs_dir=self.dashboard.outputs_dir)
        if path == "/api/stocks/monday-readiness/latest":
            return api_stock_monday_readiness_latest(outputs_dir=self.dashboard.outputs_dir)
        if path == "/api/mstr/cycle-radar":
            source = stock_live_only_source(query)
            return api_mstr_cycle_radar(
                source=source,
                db_path=self.dashboard.stock_db_path,
                outputs_dir=self.dashboard.outputs_dir,
            )
        if path == "/api/mstr/cycle-radar/history":
            return api_mstr_cycle_history(
                limit=query_int(query, "limit", 30, 1, 200),
                db_path=self.dashboard.stock_db_path,
            )
        if path == "/api/mstr/cycle-journal":
            return api_mstr_cycle_journal(
                db_path=self.dashboard.stock_db_path,
                limit=query_int(query, "limit", 50, 1, 200),
            )
        if path == "/api/options/underlyings":
            symbols = query.get("symbol") or query.get("symbols") or []
            return annotate_options_payload(
                options_underlyings(
                    symbols=symbols if symbols else None,
                    source=query_value(query, "source", "live"),
                    universe=query_value(query, "universe", "default"),
                )
            )
        if path == "/api/options/daily-candidates":
            symbols = query.get("symbol") or query.get("symbols") or []
            payload = options_daily_candidates(
                symbols=symbols if symbols else None,
                source=query_value(query, "source", "live"),
                universe=query_value(query, "universe", "default"),
            )
            return attach_scan_snapshot(self.dashboard.db_path, payload)
        if path == "/api/options/atm-alerts":
            symbols = query.get("symbol") or query.get("symbols") or []
            payload = options_atm_alerts(
                symbols=symbols if symbols else None,
                outputs_dir=self.dashboard.outputs_dir,
                db_path=self.dashboard.db_path,
                source=query_value(query, "source", "live"),
                universe=query_value(query, "universe", "default"),
                profile=query_value(query, "profile", "strict"),
            )
            return attach_scan_snapshot(self.dashboard.db_path, payload)
        if path == "/api/options/atm-alerts/latest":
            return annotate_options_payload(
                options_atm_alerts_latest(
                    outputs_dir=self.dashboard.outputs_dir,
                    db_path=self.dashboard.db_path,
                    universe=query_value(query, "universe", "default"),
                    profile=query_value(query, "profile", "strict"),
                )
            )
        if path == "/api/options/chain":
            payload = options_chain(
                query_value(query, "symbol", "SPY"),
                source=query_value(query, "source", "live"),
                expiration=query_value(query, "expiration", None),
            )
            return attach_chain_snapshot(self.dashboard.db_path, payload)
        if path == "/api/options/chain/latest":
            return latest_options_chain_payload(
                self.dashboard.db_path,
                symbol=query_value(query, "symbol", "SPY"),
            )
        if path == "/api/options/contract":
            option_symbol = query_value(query, "option_symbol", "")
            if not option_symbol:
                raise ValueError("option_symbol is required.")
            return annotate_options_payload(
                options_contract(
                    option_symbol,
                    source=query_value(query, "source", "live"),
                )
            )
        if path == "/api/options/model/surface":
            option_symbol = query_value(query, "option_symbol", "")
            if not option_symbol:
                raise ValueError("option_symbol is required.")
            return annotate_options_payload(
                options_model_surface(
                    option_symbol,
                    source=query_value(query, "source", "live"),
                )
            )
        if path == "/api/options/price-history":
            return attach_price_history_snapshot(
                self.dashboard.db_path,
                options_price_history(
                    instrument=query_value(query, "instrument", "underlying"),
                    symbol=query_value(query, "symbol", None),
                    option_symbol=query_value(query, "option_symbol", None),
                    range_value=query_value(query, "range", "5d"),
                    interval=query_value(query, "interval", "15m"),
                    source=query_value(query, "source", "live"),
                ),
            )
        if path == "/api/options/price-history/latest":
            return latest_price_history_payload(
                self.dashboard.db_path,
                instrument_type=query_value(query, "instrument", "underlying"),
                symbol=query_value(query, "symbol", None),
                option_symbol=query_value(query, "option_symbol", None),
                range_value=query_value(query, "range", "5d"),
                interval=query_value(query, "interval", "15m"),
            )
        if path == "/api/options/eval/latest":
            symbols = query.get("symbol") or query.get("symbols") or []
            selected = symbols if symbols else None
            payload = options_worthiness_report(
                symbols=selected,
                outputs_dir=self.dashboard.outputs_dir,
                source=query_value(query, "source", "live"),
                universe=query_value(query, "universe", "default"),
            )
            return {
                "eval": attach_scan_snapshot(self.dashboard.db_path, payload)
            }
        if path == "/api/options/snapshots/latest":
            return latest_options_snapshot(self.dashboard.db_path, symbol=query_value(query, "symbol", None))
        if path == "/api/options/pilot-journal":
            return load_pilot_journal(self.dashboard.outputs_dir, db_path=self.dashboard.db_path)
        if path == "/api/options/live-pilot/status":
            return options_live_pilot_status(outputs_dir=self.dashboard.outputs_dir, db_path=self.dashboard.db_path)
        if path == "/api/broker/options/status":
            return options_broker_status()
        if path == "/api/broker/options/account":
            return options_broker_account()
        if path == "/api/broker/options/positions":
            return options_broker_positions()
        if path == "/api/research/latest":
            return self.dashboard.latest_research_summary()
        if path == "/api/research/runs":
            return self.dashboard.research_runs(query_int(query, "limit", 20, 1, 100))
        if path == "/api/research/trades":
            return self.dashboard.research_trades(
                query_value(query, "run_id", None),
                query_value(query, "symbol", None),
                query_int(query, "limit", 100, 1, 500),
                query_int(query, "offset", 0, 0, 1000000),
            )
        if path == "/api/research/chart":
            return self.dashboard.research_chart(
                query_value(query, "run_id", None),
                query_value(query, "symbol", None),
                query_value(query, "trade_id", None),
                query_int(query, "pre_bars", 96, 12, 240),
                query_int(query, "post_bars", 48, 12, 240),
            )
        if path.startswith("/api/agent/"):
            return self.route_agent_get(path, query)
        raise FileNotFoundError("Unknown API path: {}".format(path))

    def route_agent_get(self, path: str, query: Dict[str, List[str]]) -> Dict[str, Any]:
        runtime = self.dashboard.agent_runtime
        segments = path.strip("/").split("/")
        if path == "/api/agent/tasks":
            return {
                "tasks": runtime.store.list_tasks(
                    limit=query_int(query, "limit", 10, 1, 100),
                    task_type=query_value(query, "task_type", None),
                )
            }
        if path == "/api/agent/evals":
            return {
                "evals": runtime.store.list_agent_eval_runs(
                    limit=query_int(query, "limit", 10, 1, 100),
                    suite=query_value(query, "suite", None),
                )
            }
        if len(segments) == 4 and segments[:3] == ["api", "agent", "evals"]:
            payload = runtime.store.get_agent_eval_run(segments[3], include_cases=True)
            if payload is None:
                raise KeyError("Agent eval run was not found: {}".format(segments[3]))
            return {"eval": payload}
        if path == "/api/agent/approvals/pending":
            return {"approvals": runtime.approval_manager.pending()}
        if len(segments) == 4 and segments[:3] == ["api", "agent", "approvals"]:
            approval = runtime.approval_manager.get(segments[3])
            if approval is None:
                raise KeyError("Approval was not found: {}".format(segments[3]))
            return approval
        if path == "/api/agent/audit/events":
            return {
                "events": runtime.store.list_audit_events(
                    query_value(query, "task_id", None),
                    limit=query_int(query, "limit", 100, 1, 500),
                )
            }
        if len(segments) == 4 and segments[:3] == ["api", "agent", "tasks"]:
            return runtime.get_task_status(segments[3])
        if len(segments) == 5 and segments[:3] == ["api", "agent", "tasks"] and segments[4] == "events":
            return {"task_id": segments[3], "events": runtime.store.list_audit_events(segments[3])}
        raise FileNotFoundError("Unknown API path: {}".format(path))

    def api_health(self) -> Dict[str, Any]:
        ai_status = api_stock_ai_review_status()
        market_data_status = api_stock_market_data_status(db_path=self.dashboard.stock_db_path)
        return {
            "product": "KQUANT US Stock Signal Terminal",
            "status": "online",
            "backend": "stdlib_server",
            "live_data_enabled": True,
            "market_data": market_data_status,
            "market_data_provider": market_data_status["provider"],
            "longbridge_status": market_data_status["status"],
            "stock_database": str(self.dashboard.stock_db_path),
            "frontend": str(self.dashboard.index_path),
            "ai_review_status": ai_status["status"],
            "ai_models": ai_status["models"],
            "read_only_research": True,
            "fixture_user_visible": False,
            "broker_order_wiring_enabled": False,
            "account_access_enabled": False,
            "order_submission_enabled": False,
        }

    def route_agent_post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        runtime = self.dashboard.agent_runtime
        segments = path.strip("/").split("/")
        if path == "/api/agent/tasks":
            task_id = runtime.create_task(
                str(body.get("task_type") or body.get("type") or "dry_run"),
                dict(body.get("payload") or {}),
                priority=int(body.get("priority", 0)),
                created_by=str(body.get("created_by", "stdlib_api")),
            )
            return runtime.get_task_status(task_id)
        if path == "/api/agent/evals/run":
            evaluator = AgentEvaluator(runtime, self.dashboard.outputs_dir)
            return {"eval": evaluator.run_suite(str(body.get("suite", "safety_core")))}
        if len(segments) == 5 and segments[:3] == ["api", "agent", "tasks"]:
            task_id = segments[3]
            action = segments[4]
            if action == "run":
                runtime.run_task(task_id)
            elif action == "pause":
                runtime.pause_task(task_id, str(body.get("reason", "stdlib api pause")))
            elif action == "resume":
                runtime.resume_task(task_id)
            elif action == "cancel":
                runtime.cancel_task(task_id, str(body.get("reason", "stdlib api cancel")))
            else:
                raise FileNotFoundError("Unknown task action: {}".format(action))
            return runtime.get_task_status(task_id)
        if len(segments) == 5 and segments[:3] == ["api", "agent", "approvals"]:
            approval_id = segments[3]
            action = segments[4]
            if action == "approve":
                return runtime.approval_manager.approve(
                    approval_id,
                    decided_by=str(body.get("decided_by", "stdlib_api")),
                    reason=str(body.get("reason", "")),
                )
            if action == "reject":
                return runtime.approval_manager.reject(
                    approval_id,
                    decided_by=str(body.get("decided_by", "stdlib_api")),
                    reason=str(body.get("reason", "")),
                )
            raise FileNotFoundError("Unknown approval action: {}".format(action))
        raise FileNotFoundError("Unknown API path: {}".format(path))

    def read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON body.") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object.")
        return payload

    def send_file(self, path: Path, content_type: str) -> None:
        if not path.exists() or not path.is_file():
            self.send_json({"detail": "File not found."}, HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: Dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            return

    def send_cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Credentials", "true")
        else:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, CF-Access-Client-Id, CF-Access-Client-Secret")

    def send_stream(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_cors_headers()
        self.end_headers()
        while True:
            payload = {
                "status": self.dashboard.status("paper"),
                "signals": {"signals": []},
                "positions": {"positions": []},
                "orders": {"orders": []},
            }
            data = ("data: " + json.dumps(payload, ensure_ascii=False, default=str) + "\n\n").encode("utf-8")
            try:
                self.wfile.write(data)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            time.sleep(5)

    def log_message(self, format: str, *args: Any) -> None:
        return


def trade_row(run_id: str, index: int, row: Dict[str, str]) -> Optional[Dict[str, Any]]:
    symbol = row.get("symbol")
    if not symbol:
        return None
    payload: Dict[str, Any] = {
        "id": "{}:{}".format(run_id, index),
        "run_id": run_id,
        "row_index": index,
        "symbol": symbol,
        "side": row.get("side"),
        "entry_time": row.get("entry_time"),
        "exit_time": row.get("exit_time"),
        "exit_reason": row.get("exit_reason"),
    }
    for key in (
        "entry_price",
        "exit_price",
        "qty",
        "stop",
        "target",
        "gross_pnl",
        "fees",
        "net_pnl",
        "r_multiple",
        "hold_bars",
        "signal_close",
        "signal_rsi",
        "signal_atr_pct",
        "signal_regime_atr_pct",
        "signal_volume_ratio",
        "signal_htf_gap_bps",
        "signal_distance_ema_mid_atr",
        "signal_hour_utc",
    ):
        payload[key] = number(row.get(key))
    return payload


def trade_overlaps(row: Dict[str, Any], start_ms: int, end_ms: int) -> bool:
    try:
        entry_ms = millis_from_trade_time(str(row["entry_time"]))
        exit_ms = millis_from_trade_time(str(row["exit_time"]))
    except ValueError:
        return False
    return entry_ms <= end_ms and exit_ms >= start_ms


def millis_from_trade_time(value: str) -> int:
    parsed = parse_dt(value)
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def iso_from_millis(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def age_since(value: Any) -> Optional[float]:
    if not value:
        return None
    try:
        return (datetime.now(timezone.utc) - parse_dt(str(value))).total_seconds()
    except ValueError:
        return None


def validate_run_id(run_id: str) -> str:
    if not RUN_ID_PATTERN.match(run_id):
        raise ValueError("Invalid run_id.")
    return run_id


def run_type(path: Path) -> Optional[str]:
    name = path.name
    if name.endswith("-v2-research-report.md"):
        return "v2_research"
    if name.endswith("-replay-filter.md") or name.endswith("-replay-filter.csv"):
        return "replay_filter_sweep"
    if name.endswith("-replay-diagnosis.md"):
        return "replay_diagnosis"
    if name.endswith("-sweep.md") or name.endswith("-sweep.csv"):
        return "sweep"
    if name.endswith("-summary.json"):
        return "backtest_summary"
    if name.endswith("-report.md") and not name.endswith("-live-readiness.md"):
        return "backtest_report"
    if "-meta-filter" in name:
        return "meta_filter"
    return None


def run_id_from_output(path: Path) -> Optional[str]:
    name = path.name
    for suffix in ("-summary.json", "-report.md", "-trades.csv", "-equity.csv"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return None


def markdown_value(text: str, pattern: str) -> Optional[str]:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def number(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def mtime_iso(path: Optional[Path]) -> Optional[str]:
    if path is None:
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def parse_json_value(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return default


def query_value(query: Dict[str, List[str]], key: str, default: Optional[str]) -> Optional[str]:
    values = query.get(key)
    if not values:
        return default
    return values[0]


def stock_live_only_source(query: Dict[str, List[str]]) -> str:
    source = str(query_value(query, "source", "live") or "live").lower()
    if source == "fixture":
        raise ValueError("Stock terminal is live-only; fixture stock data is internal test data and not available through user-facing APIs.")
    if source != "live":
        raise ValueError("Invalid stock data source. Use source=live.")
    return "live"


def query_int(query: Dict[str, List[str]], key: str, default: int, minimum: int, maximum: int) -> int:
    raw = query_value(query, key, None)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError("Invalid integer for {}.".format(key))
    if value < minimum or value > maximum:
        raise ValueError("{} must be between {} and {}.".format(key, minimum, maximum))
    return value


def make_handler(dashboard: ReadOnlyDashboard) -> type:
    class BoundHandler(Handler):
        pass

    BoundHandler.dashboard = dashboard
    return BoundHandler


def serve(host: str, port: int, root: Path) -> None:
    dashboard = ReadOnlyDashboard(root)
    server = ThreadingHTTPServer((host, port), make_handler(dashboard))
    print("Read-only kquant dashboard: http://{}:{}/".format(host, port), flush=True)
    server.serve_forever()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m btc_eth_15m.dashboard.stdlib_server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    args = parser.parse_args(argv)
    serve(args.host, args.port, Path(args.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
