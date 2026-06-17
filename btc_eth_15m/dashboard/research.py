from __future__ import annotations

import csv
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from btc_eth_15m.config import AppConfig
from btc_eth_15m.data import connect, interval_to_millis

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
MAX_CHART_BARS = 500


def latest_research_summary(config: AppConfig) -> dict[str, Any]:
    summary_path = _latest_path(config.outputs_dir, "*-summary.json")
    summary, summary_error = _load_summary(summary_path)
    daily = summary.get("daily_return_stats", {}) if summary else {}
    latest_v2_path = _latest_path(config.outputs_dir, "*-v2-research-report.md")
    v2 = _parse_v2_report(latest_v2_path)
    latest_sweep_path = _latest_path(config.outputs_dir, "*-sweep.csv")
    best_sweep = _best_sweep_row(latest_sweep_path)
    best = best_sweep or v2.get("best_variant") or {}
    metric_source = summary
    generated_source_path = latest_sweep_path if best_sweep else latest_v2_path or summary_path

    return {
        "status": "ready" if summary or v2 else "empty",
        "summary_path": str(summary_path) if summary_path else None,
        "summary_error": summary_error,
        "v2_report_path": str(latest_v2_path) if latest_v2_path else None,
        "latest_sweep_path": str(latest_sweep_path) if latest_sweep_path else None,
        "run_id": metric_source.get("run_id") if metric_source else None,
        "total_return_pct": _number(metric_source.get("total_return_pct")) if metric_source else None,
        "profit_factor": _number(metric_source.get("profit_factor")) if metric_source else None,
        "avg_r": _number(metric_source.get("avg_r")) if metric_source else None,
        "avg_daily_return_pct": _number(daily.get("avg_daily_return_pct"))
        if summary
        else _number(best.get("avg_daily_return_pct") or v2.get("best_avg_daily_return_pct")),
        "target_range_hit_rate_pct": _number(daily.get("target_range_hit_rate_pct"))
        if summary
        else _number(best.get("target_range_hit_rate_pct") or v2.get("best_target_range_hit_rate_pct")),
        "loss_day_rate_pct": _number(daily.get("loss_day_rate_pct")) if summary else _number(best.get("loss_day_rate_pct")),
        "paper_observation_decision": v2.get("paper_observation_decision") or _paper_decision_from_summary(summary),
        "daily_target_decision": v2.get("daily_target_decision") or _daily_target_decision(daily),
        "best_variant": best.get("variant") or v2.get("best_variant_name"),
        "best_run_id": best.get("run_id") or v2.get("best_variant", {}).get("run_id"),
        "generated_at": _mtime_iso(generated_source_path),
    }


def research_runs(config: AppConfig, limit: int = 20) -> dict[str, Any]:
    runs: list[dict[str, Any]] = []
    for path in config.outputs_dir.glob("*"):
        if not path.is_file():
            continue
        item = _run_item(path)
        if item is not None:
            runs.append(item)
    runs.sort(key=lambda item: item["modified_at_epoch"], reverse=True)
    return {
        "runs": [
            {key: value for key, value in item.items() if key != "modified_at_epoch"}
            for item in runs[:limit]
        ]
    }


def research_trades(
    config: AppConfig,
    *,
    run_id: str | None = None,
    symbol: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    resolved_run_id = _resolve_replay_run_id(config, run_id)
    rows = _load_trade_rows(config, resolved_run_id)
    filtered = _filter_trades(rows, symbol=symbol)
    total = len(filtered)
    page = filtered[offset : offset + limit]
    return {
        "run_id": resolved_run_id,
        "symbol": symbol,
        "total": total,
        "limit": limit,
        "offset": offset,
        "trades": page,
    }


def research_chart(
    config: AppConfig,
    *,
    run_id: str | None = None,
    symbol: str | None = None,
    trade_id: str | None = None,
    pre_bars: int = 96,
    post_bars: int = 48,
) -> dict[str, Any]:
    resolved_run_id = _resolve_replay_run_id(config, run_id)
    rows = _filter_trades(_load_trade_rows(config, resolved_run_id), symbol=symbol)
    if not rows:
        return {
            "run_id": resolved_run_id,
            "symbol": symbol,
            "selected_trade": None,
            "trades": [],
            "candles": [],
            "window": None,
        }

    selected = _selected_trade(rows, trade_id)
    selected_symbol = str(selected["symbol"])
    entry_ms = _millis_from_trade_time(str(selected["entry_time"]))
    exit_ms = _millis_from_trade_time(str(selected["exit_time"]))
    interval_ms = interval_to_millis(config.interval)
    start_ms = entry_ms - pre_bars * interval_ms
    end_ms = exit_ms + post_bars * interval_ms
    max_span = (MAX_CHART_BARS - 1) * interval_ms
    if end_ms - start_ms > max_span:
        end_ms = start_ms + max_span

    candles = _load_candles(config, selected_symbol, start_ms=start_ms, end_ms=end_ms)
    window_trades = [
        row
        for row in rows
        if row["symbol"] == selected_symbol and _trade_overlaps(row, start_ms=start_ms, end_ms=end_ms)
    ]
    return {
        "run_id": resolved_run_id,
        "symbol": selected_symbol,
        "selected_trade": selected,
        "trades": window_trades,
        "candles": candles,
        "window": {
            "start_time": _iso_from_millis(start_ms),
            "end_time": _iso_from_millis(end_ms),
            "pre_bars": pre_bars,
            "post_bars": post_bars,
            "interval": config.interval,
        },
    }


def _load_summary(path: Path | None) -> tuple[dict[str, Any], str | None]:
    if path is None:
        return {}, None
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return {}, str(exc)


def _resolve_replay_run_id(config: AppConfig, run_id: str | None) -> str:
    if run_id:
        return _validate_run_id(run_id)
    latest = latest_research_summary(config)
    candidate = latest.get("best_run_id") or latest.get("run_id")
    if not candidate:
        raise FileNotFoundError("No research run is available for replay.")
    return _validate_run_id(str(candidate))


def _validate_run_id(run_id: str) -> str:
    if not RUN_ID_PATTERN.match(run_id):
        raise ValueError("Invalid run_id.")
    return run_id


def _trades_path(config: AppConfig, run_id: str) -> Path:
    safe_run_id = _validate_run_id(run_id)
    runs_root = config.runs_dir.resolve()
    path = (runs_root / safe_run_id / "trades.csv").resolve()
    if path.parent.parent != runs_root:
        raise ValueError("Invalid run_id path.")
    if not path.exists():
        raise FileNotFoundError(f"Missing trades file for run_id: {safe_run_id}")
    return path


def _load_trade_rows(config: AppConfig, run_id: str) -> list[dict[str, Any]]:
    path = _trades_path(config, run_id)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for index, row in enumerate(csv.DictReader(handle)):
            parsed = _trade_row(run_id, index, row)
            if parsed is not None:
                rows.append(parsed)
    return rows


def _trade_row(run_id: str, index: int, row: dict[str, str]) -> dict[str, Any] | None:
    symbol = row.get("symbol")
    if not symbol:
        return None
    payload: dict[str, Any] = {
        "id": f"{run_id}:{index}",
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
        payload[key] = _number(row.get(key))
    return payload


def _filter_trades(rows: list[dict[str, Any]], *, symbol: str | None) -> list[dict[str, Any]]:
    if not symbol:
        return rows
    return [row for row in rows if row.get("symbol") == symbol]


def _selected_trade(rows: list[dict[str, Any]], trade_id: str | None) -> dict[str, Any]:
    if trade_id:
        for row in rows:
            if row["id"] == trade_id:
                return row
        raise FileNotFoundError(f"Trade was not found: {trade_id}")
    return rows[0]


def _load_candles(config: AppConfig, symbol: str, *, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    try:
        with connect(config.db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT symbol, interval, open_time, open_time_iso, close_time,
                       open, high, low, close, volume, quote_volume, trades
                FROM klines
                WHERE symbol = ? AND interval = ? AND open_time BETWEEN ? AND ?
                ORDER BY open_time ASC
                LIMIT ?
                """,
                (symbol, config.interval, start_ms, end_ms, MAX_CHART_BARS),
            ).fetchall()
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to load candles: {exc}") from exc
    return [
        {
            "symbol": row["symbol"],
            "interval": row["interval"],
            "open_time": row["open_time"],
            "open_time_iso": row["open_time_iso"],
            "close_time": row["close_time"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
            "quote_volume": row["quote_volume"],
            "trades": row["trades"],
        }
        for row in rows
    ]


def _trade_overlaps(row: dict[str, Any], *, start_ms: int, end_ms: int) -> bool:
    try:
        entry_ms = _millis_from_trade_time(str(row["entry_time"]))
        exit_ms = _millis_from_trade_time(str(row["exit_time"]))
    except ValueError:
        return False
    return entry_ms <= end_ms and exit_ms >= start_ms


def _millis_from_trade_time(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.astimezone(UTC).timestamp() * 1000)


def _iso_from_millis(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()


def _parse_v2_report(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    payload: dict[str, Any] = {}
    payload["best_variant_name"] = _markdown_value(text, r"Best variant:\s*`([^`]+)`")
    payload["best_avg_daily_return_pct"] = _number(_markdown_value(text, r"Best average daily return:\s*`([^`%]+)%`"))
    payload["best_target_range_hit_rate_pct"] = _number(_markdown_value(text, r"Best 5%-7% daily hit rate:\s*`([^`%]+)%`"))
    payload["daily_target_decision"] = _markdown_value(text, r"Daily target decision:\s*\*\*(YES|NO)\*\*")
    payload["paper_observation_decision"] = _markdown_value(text, r"Paper observation decision:\s*\*\*(YES|NO)\*\*")
    for line in text.splitlines():
        if not line.startswith("| daily_"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip("|").split("|")]
        if len(cells) >= 13 and cells[0] == payload.get("best_variant_name"):
            payload["best_variant"] = {
                "variant": cells[0],
                "mode": cells[1],
                "regime_filter": cells[2],
                "trade_count": _number(cells[3]),
                "profit_factor": _number(cells[4]),
                "avg_r": _number(cells[5]),
                "avg_daily_return_pct": _number(cells[6].rstrip("%")),
                "target_range_hit_rate_pct": _number(cells[7].rstrip("%")),
                "loss_day_rate_pct": _number(cells[8].rstrip("%")),
                "total_return_pct": _number(cells[9].rstrip("%")),
                "max_drawdown_pct": _number(cells[10].rstrip("%")),
                "positive_years": cells[11],
                "run_id": cells[12],
            }
            break
    return payload


def _best_sweep_row(path: Path | None) -> dict[str, Any] | None:
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
            _number(row.get("profit_factor")) or 0.0,
            _number(row.get("avg_r")) or 0.0,
            _number(row.get("total_return_pct")) or -999999.0,
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
        row[key] = _number(row.get(key))
    return row


def _run_item(path: Path) -> dict[str, Any] | None:
    kind = _run_type(path)
    if kind is None:
        return None
    stat = path.stat()
    return {
        "type": kind,
        "path": str(path),
        "name": path.name,
        "run_id": _run_id(path),
        "modified_at": _mtime_iso(path),
        "modified_at_epoch": stat.st_mtime,
        "size_bytes": stat.st_size,
    }


def _run_type(path: Path) -> str | None:
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


def _run_id(path: Path) -> str | None:
    name = path.name
    for suffix in ("-summary.json", "-report.md", "-trades.csv", "-equity.csv"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return None


def _paper_decision_from_summary(summary: dict[str, Any]) -> str:
    if not summary:
        return "NO"
    daily = summary.get("daily_return_stats", {})
    profit_factor = _number(summary.get("profit_factor")) or 0.0
    avg_r = _number(summary.get("avg_r")) or 0.0
    max_dd = _number(summary.get("max_drawdown_pct")) or 0.0
    daily_ok = _daily_target_decision(daily) == "YES"
    return "YES" if profit_factor > 1.05 and avg_r > 0 and max_dd > -25 and daily_ok else "NO"


def _daily_target_decision(daily: dict[str, Any]) -> str:
    if not daily:
        return "NO"
    avg = _number(daily.get("avg_daily_return_pct")) or 0.0
    hit = _number(daily.get("target_range_hit_rate_pct")) or 0.0
    loss = _number(daily.get("loss_day_rate_pct")) or 100.0
    return "YES" if 5.0 <= avg <= 7.0 and hit >= 50.0 and loss < 35.0 else "NO"


def _latest_path(directory: Path, pattern: str) -> Path | None:
    candidates = [path for path in directory.glob(pattern) if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _markdown_value(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mtime_iso(path: Path | None) -> str | None:
    if path is None:
        return None
    from datetime import UTC, datetime

    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
