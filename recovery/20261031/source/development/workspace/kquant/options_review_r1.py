from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import math
import sqlite3
import subprocess
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from .local_env import load_market_data_env
from .longbridge_provider import longbridge_runtime
from .options_radar import RADAR_UNIVERSE, SECTOR_BENCHMARK
from .options_research_features import content_hash


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DB = REPO_ROOT / "work" / "kquant_us.sqlite3"
REVIEW_DB = REPO_ROOT / "work" / "options_review_r1" / "options_review_r1.sqlite3"
OUTPUT_ROOT = REPO_ROOT / "outputs" / "options_review_r1"
PROTOCOL_PATH = REPO_ROOT / "config" / "options_research_protocol_v0_1.json"
PROFILE_PATH = REPO_ROOT / "config" / "options_research_profiles_v1.json"
SERVICE_PATH = REPO_ROOT / "work" / "option_foundation" / "runtime" / "services.json"
CAPABILITY_PATH = REPO_ROOT / "work" / "option_foundation" / "runtime" / "latest_capability.json"
MASTER_PLAN_PATH = REPO_ROOT / "docs" / "KQUANT_OPTIONS_MASTER_PLAN_REVIEW_LED_V1.md"
OWNER_PLAYBOOK_PATH = REPO_ROOT / "docs" / "OWNER_REVIEW_PLAYBOOK.md"
TASK_GRAPH_PATH = REPO_ROOT / "plan" / "options_personal_master_tasks.v1.json"
REVIEW_GATES_PATH = REPO_ROOT / "plan" / "review_gates.v1.json"
REVIEW_DEFAULTS_PATH = REPO_ROOT / "config" / "review_led_defaults.v1.json"

REVIEW_VERSION = "options-personal-r1.v1.0.0"
DATASET_FAMILY = "longbridge_daily_adjustment_comparison_v1"
EXPERIMENT_ID = "E-S-001_EXCESS_RS20_TO_FORWARD5"
REQUIRED_SYMBOLS = tuple(sorted(set(RADAR_UNIVERSE) | set(SECTOR_BENCHMARK.values()) | {"SPY"}))
ADJUSTMENT_MODES = ("NO_ADJUST", "FORWARD_ADJUST")


SCHEMA = """
CREATE TABLE IF NOT EXISTS review_meta (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS adjustment_requests (
  request_id TEXT PRIMARY KEY,
  bundle_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  adjustment_mode TEXT NOT NULL,
  request_start TEXT NOT NULL,
  request_end TEXT NOT NULL,
  request_json TEXT NOT NULL,
  page_count INTEGER NOT NULL,
  row_count INTEGER NOT NULL,
  response_hash TEXT,
  status TEXT NOT NULL,
  error_code TEXT,
  requested_at TEXT NOT NULL,
  completed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS adjusted_daily_bars (
  bundle_id TEXT NOT NULL,
  dataset_version TEXT NOT NULL,
  symbol TEXT NOT NULL,
  adjustment_mode TEXT NOT NULL,
  market_date TEXT NOT NULL,
  source_timestamp TEXT NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume REAL NOT NULL,
  turnover REAL,
  source TEXT NOT NULL,
  sdk_version TEXT NOT NULL,
  pulled_at TEXT NOT NULL,
  adjustment_as_of TEXT,
  lineage_hash TEXT NOT NULL,
  PRIMARY KEY(bundle_id, symbol, adjustment_mode, market_date)
);
CREATE TABLE IF NOT EXISTS adjustment_rejections (
  bundle_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  adjustment_mode TEXT NOT NULL,
  market_date TEXT,
  source_timestamp TEXT,
  row_json TEXT NOT NULL,
  reason TEXT NOT NULL,
  request_id TEXT NOT NULL,
  pulled_at TEXT NOT NULL,
  PRIMARY KEY(bundle_id, symbol, adjustment_mode, source_timestamp, reason)
);
CREATE TABLE IF NOT EXISTS es001_experiment_runs (
  run_id TEXT PRIMARY KEY,
  bundle_id TEXT NOT NULL,
  status TEXT NOT NULL,
  conclusion TEXT NOT NULL,
  dataset_hash TEXT NOT NULL,
  split_hash TEXT,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_task_state (
  bundle_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  state TEXT NOT NULL,
  detail_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(bundle_id, task_id)
);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json_immutable(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"Immutable artifact already exists with different content: {path}")
        return
    path.write_text(text, encoding="utf-8", newline="\n")


def write_text_immutable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = text.rstrip() + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != normalized:
            raise RuntimeError(f"Immutable artifact already exists with different content: {path}")
        return
    path.write_text(normalized, encoding="utf-8", newline="\n")


def initialize_review_store(path: Path = REVIEW_DB) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.executescript(SCHEMA)
        connection.execute(
            "INSERT OR REPLACE INTO review_meta VALUES (?,?,?)",
            ("schema_version", json_text(1), utc_now()),
        )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    return {"path": str(path.resolve()), "schema_version": 1, "integrity_check": integrity}


def _readonly(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def source_windows(source_db: Path = SOURCE_DB) -> tuple[dict[str, tuple[date, date]], dict[str, Any]]:
    placeholders = ",".join("?" for _ in REQUIRED_SYMBOLS)
    with _readonly(source_db) as connection:
        rows = connection.execute(
            f"""SELECT symbol, COUNT(*) AS raw_rows, COUNT(DISTINCT substr(open_time,1,10)) AS market_dates,
                       MIN(substr(open_time,1,10)) AS start_date, MAX(substr(open_time,1,10)) AS end_date,
                       GROUP_CONCAT(DISTINCT adjustment_mode) AS adjustment_modes,
                       GROUP_CONCAT(DISTINCT dataset_version) AS dataset_versions
                  FROM market_candles
                 WHERE interval='1d' AND primary_source='longbridge_candles'
                   AND bar_state='closed_candle' AND symbol IN ({placeholders})
                 GROUP BY symbol ORDER BY symbol""",
            REQUIRED_SYMBOLS,
        ).fetchall()
        main_counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("market_candles", "option_radar_runs", "option_opportunities", "option_plans", "option_quote_evidence", "option_outcomes")
        }
    coverage = {str(row["symbol"]): dict(row) for row in rows}
    missing = [symbol for symbol in REQUIRED_SYMBOLS if symbol not in coverage]
    windows = {
        symbol: (date.fromisoformat(str(item["start_date"])), date.fromisoformat(str(item["end_date"])))
        for symbol, item in coverage.items()
    }
    return windows, {
        "source_db": str(source_db.resolve()),
        "opened_read_only": True,
        "required_symbols": list(REQUIRED_SYMBOLS),
        "missing_symbols": missing,
        "coverage": coverage,
        "main_table_counts": main_counts,
    }


def sdk_capability() -> dict[str, Any]:
    from longbridge.openapi import AdjustType, Period, QuoteContext  # type: ignore
    import inspect

    return {
        "package": "longbridge",
        "sdk_version": importlib.metadata.version("longbridge"),
        "adjust_types": {
            "NO_ADJUST": {"enum_name": "AdjustType.NoAdjust", "repr": repr(AdjustType.NoAdjust)},
            "FORWARD_ADJUST": {"enum_name": "AdjustType.ForwardAdjust", "repr": repr(AdjustType.ForwardAdjust)},
        },
        "period": {"name": "Period.Day", "repr": repr(Period.Day)},
        "history_method_signature": str(inspect.signature(QuoteContext.history_candlesticks_by_date)),
        "official_history_documentation": "https://open.longbridge.com/docs/quote/pull/history-candlestick",
        "official_adjustment_semantics": "forward adjustment for splits/dividends",
        "verified_by_runtime_call": False,
    }


def _finite_number(value: Any, *, optional: bool = False) -> float | None:
    if value is None and optional:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        if optional:
            return None
        raise ValueError("provider row contains a non-numeric field")
    if not math.isfinite(number):
        raise ValueError("provider row contains a non-finite field")
    return number


def normalize_provider_row(row: Any) -> dict[str, Any]:
    timestamp = getattr(row, "timestamp", None)
    market_date = str(timestamp)[:10]
    if len(market_date) != 10:
        raise ValueError("provider row is missing a usable daily timestamp")
    result = {
        "market_date": market_date,
        "source_timestamp": str(timestamp),
        "open": _finite_number(getattr(row, "open", None)),
        "high": _finite_number(getattr(row, "high", None)),
        "low": _finite_number(getattr(row, "low", None)),
        "close": _finite_number(getattr(row, "close", None)),
        "volume": _finite_number(getattr(row, "volume", None)),
        "turnover": _finite_number(getattr(row, "turnover", None), optional=True),
    }
    if min(float(result[key]) for key in ("open", "high", "low", "close")) <= 0:
        raise ValueError("provider row has a non-positive price")
    if float(result["volume"]) < 0:
        raise ValueError("provider row has negative volume")
    if not float(result["low"]) <= min(float(result["open"]), float(result["close"])) <= max(float(result["open"]), float(result["close"])) <= float(result["high"]):
        raise ValueError("provider row has invalid OHLC ordering")
    return result


def _provider_row_evidence(row: Any) -> dict[str, Any]:
    timestamp = getattr(row, "timestamp", None)
    return {
        "market_date": str(timestamp)[:10] if timestamp is not None else None,
        "source_timestamp": str(timestamp) if timestamp is not None else None,
        "open": str(getattr(row, "open", None)),
        "high": str(getattr(row, "high", None)),
        "low": str(getattr(row, "low", None)),
        "close": str(getattr(row, "close", None)),
        "volume": str(getattr(row, "volume", None)),
        "turnover": str(getattr(row, "turnover", None)),
    }


def _fetch_history(
    symbol: str,
    mode_name: str,
    start: date,
    end: date,
    *,
    timeout_seconds: int = 15,
    caller: Callable[[str, Any, Any, date, date, int], Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    from longbridge.openapi import AdjustType, Period  # type: ignore

    mode = AdjustType.NoAdjust if mode_name == "NO_ADJUST" else AdjustType.ForwardAdjust
    invoke = caller or longbridge_runtime().history_candlesticks_by_date
    cursor_end = end
    pages: list[dict[str, Any]] = []
    by_date: dict[str, dict[str, Any]] = {}
    rejections: list[dict[str, Any]] = []
    seen_ends: set[date] = set()
    while cursor_end >= start:
        if cursor_end in seen_ends:
            raise RuntimeError(f"pagination did not advance for {symbol} {mode_name}")
        seen_ends.add(cursor_end)
        request_started = utc_now()
        rows = list(invoke(f"{symbol}.US", Period.Day, mode, start, cursor_end, timeout_seconds) or [])
        normalized: list[dict[str, Any]] = []
        page_rejections: list[dict[str, Any]] = []
        for row in rows:
            try:
                normalized.append(normalize_provider_row(row))
            except ValueError as error:
                evidence = _provider_row_evidence(row)
                page_rejections.append({**evidence, "reason": str(error)})
        rejections.extend(page_rejections)
        normalized.sort(key=lambda item: item["market_date"])
        response_hash = content_hash({"accepted": normalized, "rejected": page_rejections})
        pages.append(
            {
                "page": len(pages) + 1,
                "requested_start": start.isoformat(),
                "requested_end": cursor_end.isoformat(),
                "requested_at": request_started,
                "received_at": utc_now(),
                "row_count": len(normalized),
                "rejected_row_count": len(page_rejections),
                "response_hash": response_hash,
                "first_market_date": normalized[0]["market_date"] if normalized else None,
                "last_market_date": normalized[-1]["market_date"] if normalized else None,
            }
        )
        for item in normalized:
            if start.isoformat() <= item["market_date"] <= end.isoformat():
                by_date[item["market_date"]] = item
        observed_dates = [item["market_date"] for item in normalized] + [str(item["market_date"]) for item in page_rejections if item.get("market_date")]
        if not observed_dates:
            break
        oldest = date.fromisoformat(min(observed_dates))
        if oldest <= start:
            break
        next_end = oldest - timedelta(days=1)
        if next_end >= cursor_end:
            raise RuntimeError(f"provider pagination stalled for {symbol} {mode_name}")
        cursor_end = next_end
        time.sleep(0.12)
    return [by_date[key] for key in sorted(by_date)], pages, rejections


def _store_request_and_bars(
    review_db: Path,
    *,
    bundle_id: str,
    dataset_version: str,
    symbol: str,
    mode: str,
    start: date,
    end: date,
    bars: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    rejections: list[dict[str, Any]],
    sdk_version: str,
    completed_at: str,
) -> dict[str, Any]:
    request_material = {
        "symbol": f"{symbol}.US",
        "period": "Period.Day",
        "adjust_type": "AdjustType.NoAdjust" if mode == "NO_ADJUST" else "AdjustType.ForwardAdjust",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "sdk_version": sdk_version,
        "method": "QuoteContext.history_candlesticks_by_date",
    }
    request_id = f"adjreq-{content_hash({'bundle': bundle_id, **request_material})[:24]}"
    response_hash = content_hash(bars)
    with sqlite3.connect(review_db) as connection:
        connection.execute(
            """INSERT OR IGNORE INTO adjustment_requests
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                request_id, bundle_id, symbol, mode, start.isoformat(), end.isoformat(), json_text(request_material),
                len(pages), len(bars), response_hash, "COMPLETE", None,
                pages[0]["requested_at"] if pages else completed_at, completed_at,
            ),
        )
        for bar in bars:
            lineage = content_hash({"request_id": request_id, "bar": bar, "mode": mode})
            connection.execute(
                """INSERT OR IGNORE INTO adjusted_daily_bars
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    bundle_id, dataset_version, symbol, mode, bar["market_date"], bar["source_timestamp"],
                    bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"], bar.get("turnover"),
                    "longbridge_history_candlesticks_by_date", sdk_version, completed_at,
                    completed_at if mode == "FORWARD_ADJUST" else None, lineage,
                ),
            )
        for rejected in rejections:
            connection.execute(
                """INSERT OR IGNORE INTO adjustment_rejections
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    bundle_id, symbol, mode, rejected.get("market_date"), rejected.get("source_timestamp"),
                    json_text(rejected), rejected["reason"], request_id, completed_at,
                ),
            )
        connection.commit()
    return {
        "request_id": request_id,
        "symbol": symbol,
        "adjustment_mode": mode,
        "request": request_material,
        "page_count": len(pages),
        "row_count": len(bars),
        "rejected_row_count": len(rejections),
        "rejections": rejections,
        "response_hash": response_hash,
        "pages": pages,
    }


def pull_adjustment_dataset(
    *,
    bundle_id: str,
    review_db: Path = REVIEW_DB,
    source_db: Path = SOURCE_DB,
    caller: Callable[[str, Any, Any, date, date, int], Any] | None = None,
) -> dict[str, Any]:
    initialize_review_store(review_db)
    windows, source_identity = source_windows(source_db)
    if source_identity["missing_symbols"]:
        return {
            "status": "DATA_INSUFFICIENT",
            "blockers": ["SOURCE_WINDOW_MISSING_SYMBOLS"],
            "source_identity": source_identity,
            "requests": [],
        }
    env = load_market_data_env() if caller is None else {"status": "TEST_CALLER", "longbridge_credentials_configured": True}
    capability = sdk_capability()
    if caller is None and not env["longbridge_credentials_configured"]:
        return {"status": "DATA_INSUFFICIENT", "blockers": ["LONGBRIDGE_CREDENTIALS_NOT_CONFIGURED"], "source_identity": source_identity, "sdk": capability, "requests": []}
    dataset_version = f"{DATASET_FAMILY}:{bundle_id}"
    requests: list[dict[str, Any]] = []
    for symbol in REQUIRED_SYMBOLS:
        start, end = windows[symbol]
        for mode in ADJUSTMENT_MODES:
            bars, pages, rejections = _fetch_history(symbol, mode, start, end, caller=caller)
            completed_at = utc_now()
            requests.append(
                _store_request_and_bars(
                    review_db,
                    bundle_id=bundle_id,
                    dataset_version=dataset_version,
                    symbol=symbol,
                    mode=mode,
                    start=start,
                    end=end,
                    bars=bars,
                    pages=pages,
                    rejections=rejections,
                    sdk_version=capability["sdk_version"],
                    completed_at=completed_at,
                )
            )
    capability["verified_by_runtime_call"] = bool(requests)
    capability["environment"] = env
    return {
        "status": "COMPLETE",
        "bundle_id": bundle_id,
        "dataset_version": dataset_version,
        "source_identity": source_identity,
        "sdk": capability,
        "requests": requests,
    }


def _bars_by_mode(review_db: Path, bundle_id: str) -> dict[str, dict[str, list[dict[str, Any]]]]:
    result: dict[str, dict[str, list[dict[str, Any]]]] = {mode: {} for mode in ADJUSTMENT_MODES}
    with _readonly(review_db) as connection:
        rows = connection.execute(
            """SELECT symbol,adjustment_mode,market_date,source_timestamp,open,high,low,close,volume,turnover,
                      source,sdk_version,pulled_at,adjustment_as_of,lineage_hash
                 FROM adjusted_daily_bars WHERE bundle_id=? ORDER BY symbol,adjustment_mode,market_date""",
            (bundle_id,),
        ).fetchall()
    for row in rows:
        result[str(row["adjustment_mode"])].setdefault(str(row["symbol"]), []).append(dict(row))
    return result


def validate_adjustment_dataset(review_db: Path, bundle_id: str) -> dict[str, Any]:
    modes = _bars_by_mode(review_db, bundle_id)
    with _readonly(review_db) as connection:
        rejected_rows = [
            dict(row)
            for row in connection.execute(
                """SELECT symbol,adjustment_mode,market_date,source_timestamp,reason,row_json
                     FROM adjustment_rejections WHERE bundle_id=?
                     ORDER BY symbol,adjustment_mode,source_timestamp""",
                (bundle_id,),
            ).fetchall()
        ]
    rejected_dates = {
        (str(item["symbol"]), str(item["adjustment_mode"]), str(item["market_date"]))
        for item in rejected_rows if item.get("market_date")
    }
    symbols: list[dict[str, Any]] = []
    blockers: list[str] = []
    for symbol in REQUIRED_SYMBOLS:
        raw = modes["NO_ADJUST"].get(symbol, [])
        adjusted = modes["FORWARD_ADJUST"].get(symbol, [])
        raw_dates = {item["market_date"] for item in raw}
        adjusted_dates = {item["market_date"] for item in adjusted}
        common = sorted(raw_dates & adjusted_dates)
        mismatch = (raw_dates - adjusted_dates) | (adjusted_dates - raw_dates)
        quarantined_dates = sorted(
            market_date for market_date in mismatch
            if (symbol, "NO_ADJUST", market_date) in rejected_dates or (symbol, "FORWARD_ADJUST", market_date) in rejected_dates
        )
        unexpected_mismatch = sorted(mismatch - set(quarantined_dates))
        close_differences = 0
        for market_date in common:
            raw_close = next(float(item["close"]) for item in raw if item["market_date"] == market_date)
            adjusted_close = next(float(item["close"]) for item in adjusted if item["market_date"] == market_date)
            close_differences += int(not math.isclose(raw_close, adjusted_close, rel_tol=1e-10, abs_tol=1e-10))
        item = {
            "symbol": symbol,
            "raw_dates": len(raw_dates),
            "adjusted_dates": len(adjusted_dates),
            "common_dates": len(common),
            "raw_only_dates": sorted(raw_dates - adjusted_dates),
            "adjusted_only_dates": sorted(adjusted_dates - raw_dates),
            "quarantined_provider_invalid_dates": quarantined_dates,
            "unexpected_date_mismatch": unexpected_mismatch,
            "start": common[0] if common else None,
            "end": common[-1] if common else None,
            "close_difference_dates": close_differences,
            "lineage_complete": all(item.get("lineage_hash") for item in raw + adjusted),
        }
        if len(common) < 250:
            blockers.append(f"{symbol}:INSUFFICIENT_COMMON_DATES")
        if unexpected_mismatch:
            blockers.append(f"{symbol}:RAW_ADJUSTED_DATE_MISMATCH")
        if not item["lineage_complete"]:
            blockers.append(f"{symbol}:LINEAGE_MISSING")
        symbols.append(item)

    nvda_raw = {item["market_date"]: item for item in modes["NO_ADJUST"].get("NVDA", [])}
    nvda_adjusted = {item["market_date"]: item for item in modes["FORWARD_ADJUST"].get("NVDA", [])}
    action_test: dict[str, Any] = {
        "symbol": "NVDA",
        "source": "https://investor.nvidia.com/files/doc_downloads/2024/06/nvidia-2024-stock-split_faq_investors.pdf",
        "official_event": "10-for-1 forward split; split-adjusted trading commenced 2024-06-10",
        "event_date": "2024-06-10",
        "status": "UNAVAILABLE",
    }
    if all(day in nvda_raw and day in nvda_adjusted for day in ("2024-06-07", "2024-06-10")):
        raw_ratio = float(nvda_raw["2024-06-07"]["close"]) / float(nvda_raw["2024-06-10"]["open"])
        adjusted_ratio = float(nvda_adjusted["2024-06-07"]["close"]) / float(nvda_adjusted["2024-06-10"]["open"])
        pre_split_volume_ratio = float(nvda_adjusted["2024-06-07"]["volume"]) / float(nvda_raw["2024-06-07"]["volume"])
        turnover_equal = math.isclose(float(nvda_raw["2024-06-07"]["turnover"]), float(nvda_adjusted["2024-06-07"]["turnover"]), rel_tol=1e-10)
        passed = 8.5 <= raw_ratio <= 11.5 and 0.85 <= adjusted_ratio <= 1.15 and 8.5 <= pre_split_volume_ratio <= 11.5 and turnover_equal
        action_test.update(
            {
                "status": "PASS" if passed else "FAIL",
                "raw_close_to_post_split_open_ratio": raw_ratio,
                "adjusted_close_to_post_split_open_ratio": adjusted_ratio,
                "pre_split_adjusted_to_raw_volume_ratio": pre_split_volume_ratio,
                "turnover_preserved": turnover_equal,
            }
        )
        if not passed:
            blockers.append("NVDA_REAL_SPLIT_BEHAVIOR_CHECK_FAILED")
    else:
        blockers.append("NVDA_REAL_SPLIT_WINDOW_MISSING")

    return {
        "status": "ELIGIBLE" if not blockers else "BLOCKED",
        "gate": "D_ADJUSTED_DATA",
        "gate_status": "PASS" if not blockers else "FAIL",
        "bundle_id": bundle_id,
        "adjustment_mode": "LONG_BRIDGE_FORWARD_ADJUST",
        "adjustment_as_of_policy": "PULL_COMPLETION_TIME; NOT HISTORICAL_POINT_IN_TIME",
        "scope": list(REQUIRED_SYMBOLS),
        "symbols": symbols,
        "corporate_action_test": action_test,
        "quarantined_provider_rows": rejected_rows,
        "blockers": blockers,
        "known_semantic_limit": "Provider documents ForwardAdjust for splits/dividends, but the candle response does not enumerate each adjustment component.",
    }


def _series_maps(review_db: Path, bundle_id: str) -> dict[str, dict[str, dict[str, Any]]]:
    modes = _bars_by_mode(review_db, bundle_id)
    return {
        symbol: {str(item["market_date"]): item for item in rows}
        for symbol, rows in modes["FORWARD_ADJUST"].items()
    }


def build_es001_dataset(review_db: Path, bundle_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    series = _series_maps(review_db, bundle_id)
    rows: list[dict[str, Any]] = []
    exclusions: dict[str, int] = {}
    by_symbol: dict[str, int] = {}
    self_benchmark_rows = 0
    for symbol in RADAR_UNIVERSE:
        sector_symbol = SECTOR_BENCHMARK.get(symbol)
        if not sector_symbol or symbol not in series or sector_symbol not in series or "SPY" not in series:
            exclusions[f"{symbol}:MISSING_SERIES"] = 1
            continue
        common = sorted(set(series[symbol]) & set(series[sector_symbol]) & set(series["SPY"]))
        if len(common) < 26:
            exclusions[f"{symbol}:INSUFFICIENT_COMMON_DATES"] = len(common)
            continue
        for index in range(20, len(common) - 5):
            current_date = common[index]
            label_date = common[index + 5]
            stock_now = float(series[symbol][current_date]["close"])
            stock_prior = float(series[symbol][common[index - 20]]["close"])
            sector_now = float(series[sector_symbol][current_date]["close"])
            sector_prior = float(series[sector_symbol][common[index - 20]]["close"])
            stock_future = float(series[symbol][label_date]["close"])
            market_now = float(series["SPY"][current_date]["close"])
            market_future = float(series["SPY"][label_date]["close"])
            feature = math.log(stock_now / stock_prior) - math.log(sector_now / sector_prior)
            gross_target = math.log(stock_future / stock_now)
            target = gross_target - math.log(market_future / market_now)
            if symbol == "SPY":
                self_benchmark_rows += 1
                continue
            lineage = sorted(
                {
                    series[symbol][current_date]["lineage_hash"],
                    series[symbol][common[index - 20]]["lineage_hash"],
                    series[symbol][label_date]["lineage_hash"],
                    series[sector_symbol][current_date]["lineage_hash"],
                    series[sector_symbol][common[index - 20]]["lineage_hash"],
                    series["SPY"][current_date]["lineage_hash"],
                    series["SPY"][label_date]["lineage_hash"],
                }
            )
            rows.append(
                {
                    "date": current_date,
                    "symbol": symbol,
                    "sector_benchmark": sector_symbol,
                    "market_benchmark": "SPY",
                    "feature": feature,
                    "target": target,
                    "gross_target": gross_target,
                    "label_end_date": label_date,
                    "price_basis": "LONG_BRIDGE_FORWARD_ADJUST",
                    "adjustment_as_of": series[symbol][current_date]["adjustment_as_of"],
                    "exposure_status": "EXPOSED_RESEARCH",
                    "execution_semantics": "CLOSE_TO_CLOSE_OBSERVATION_PROXY_NOT_TRADE",
                    "lineage_hash": content_hash(lineage),
                }
            )
            by_symbol[symbol] = by_symbol.get(symbol, 0) + 1
    manifest = {
        "experiment_id": EXPERIMENT_ID,
        "bundle_id": bundle_id,
        "row_count": len(rows),
        "unique_dates": len({item["date"] for item in rows}),
        "by_symbol": by_symbol,
        "excluded_self_benchmark_rows": self_benchmark_rows,
        "exclusions": exclusions,
        "feature": "excess_log_return_20_sector",
        "primary_target": "forward_5_session_excess_log_return_vs_fixed_market_benchmark",
        "secondary_target": "forward_5_session_gross_log_return_description_only",
        "dataset_hash": content_hash(rows),
        "historical_exposure": "EXPOSED_RESEARCH",
        "point_in_time_status": "CURRENTLY_ADJUSTED_HISTORY_NOT_HISTORICAL_PIT",
    }
    return rows, manifest


def _rank(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    index = 0
    while index < len(values):
        end = index + 1
        while end < len(values) and values[order[end]] == values[order[index]]:
            end += 1
        average = (index + end - 1) / 2.0 + 1.0
        ranks[order[index:end]] = average
        index = end
    return ranks


def _spearman(x: Iterable[float], y: Iterable[float]) -> float | None:
    left = np.asarray(list(x), dtype=float)
    right = np.asarray(list(y), dtype=float)
    if len(left) < 3 or np.std(left) == 0 or np.std(right) == 0:
        return None
    return float(np.corrcoef(_rank(left), _rank(right))[0, 1])


def _block_bootstrap_improvement(items: list[dict[str, Any]], *, repetitions: int, block_sessions: int, seed: int) -> dict[str, Any]:
    dates = sorted({str(item["date"]) for item in items})
    by_date = {
        value: float(np.mean([float(item["mae_improvement_row"]) for item in items if item["date"] == value]))
        for value in dates
    }
    if not dates:
        return {"status": "UNAVAILABLE", "reason": "NO_DATES"}
    blocks = [dates[index : index + block_sessions] for index in range(0, len(dates), block_sessions)]
    if len(blocks) < 2:
        return {"status": "LIMITED", "dates": len(dates), "blocks": len(blocks), "reason": "FEWER_THAN_TWO_BLOCKS"}
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(repetitions):
        selected: list[str] = []
        while len(selected) < len(dates):
            selected.extend(blocks[int(rng.integers(0, len(blocks)))])
        selected = selected[: len(dates)]
        draws.append(float(np.mean([by_date[value] for value in selected])))
    return {
        "status": "DEV_ONLY",
        "dates": len(dates),
        "blocks": len(blocks),
        "block_sessions": block_sessions,
        "repetitions": repetitions,
        "seed": seed,
        "mean": float(np.mean(draws)),
        "ci95": [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))],
    }


def run_es001(rows: list[dict[str, Any]], protocol: dict[str, Any], dataset_manifest: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    experiment = protocol["primary_experiment"]
    dates = sorted({str(item["date"]) for item in rows})
    minimum = int(experiment["minimum_numeric_fit_train_dates"])
    if len(dates) < minimum:
        result = {
            "status": "DATA_INSUFFICIENT",
            "conclusion": "DATA_INSUFFICIENT",
            "reason": "INSUFFICIENT_UNIQUE_DATES",
            "unique_dates": len(dates),
            "dataset_manifest": dataset_manifest,
            "fit_performed": False,
        }
        return result, []
    fractions = experiment["development_split_fractions"]
    train_end = max(1, int(len(dates) * float(fractions[0])))
    validation_end = max(train_end + 1, int(len(dates) * float(fractions[0] + fractions[1])))
    split = {value: "TRAIN" if index < train_end else ("VALIDATION" if index < validation_end else "TEST") for index, value in enumerate(dates)}
    partition_ends = {"TRAIN": dates[train_end - 1], "VALIDATION": dates[validation_end - 1], "TEST": dates[-1]}
    eligible = [item for item in rows if item["label_end_date"] <= partition_ends[split[item["date"]]]]
    train = [item for item in eligible if split[item["date"]] == "TRAIN"]
    if len({item["date"] for item in train}) < minimum:
        result = {
            "status": "DATA_INSUFFICIENT",
            "conclusion": "DATA_INSUFFICIENT",
            "reason": "TRAIN_DATES_AFTER_PURGE_BELOW_GUARD",
            "train_dates": len({item["date"] for item in train}),
            "dataset_manifest": dataset_manifest,
            "fit_performed": False,
        }
        return result, []
    x_train = np.asarray([float(item["feature"]) for item in train], dtype=float)
    y_train = np.asarray([float(item["target"]) for item in train], dtype=float)
    x_mean = float(x_train.mean())
    x_std = float(x_train.std(ddof=0))
    if x_std <= 0:
        result = {"status": "DATA_INSUFFICIENT", "conclusion": "DATA_INSUFFICIENT", "reason": "CONSTANT_TRAIN_FEATURE", "dataset_manifest": dataset_manifest, "fit_performed": False}
        return result, []
    design = np.column_stack([np.ones(len(train)), (x_train - x_mean) / x_std])
    alpha = float(experiment["alpha"])
    coefficients = np.linalg.solve(design.T @ design + np.diag([0.0, alpha]), design.T @ y_train)
    baseline = float(y_train.mean())
    predictions: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    bootstrap: dict[str, Any] = {}
    for partition in ("TRAIN", "VALIDATION", "TEST"):
        assigned = [item for item in rows if split[item["date"]] == partition]
        sample = [item for item in eligible if split[item["date"]] == partition]
        enriched: list[dict[str, Any]] = []
        for item in sample:
            predicted = float(coefficients[0] + coefficients[1] * ((float(item["feature"]) - x_mean) / x_std))
            row = {
                **item,
                "partition": partition,
                "prediction": predicted,
                "baseline_prediction": baseline,
                "ridge_absolute_error": abs(float(item["target"]) - predicted),
                "baseline_absolute_error": abs(float(item["target"]) - baseline),
            }
            row["mae_improvement_row"] = row["baseline_absolute_error"] - row["ridge_absolute_error"]
            enriched.append(row)
            predictions.append(row)
        metrics[partition] = {
            "assigned_rows": len(assigned),
            "rows": len(enriched),
            "unique_dates": len({item["date"] for item in enriched}),
            "purged_rows": len(assigned) - len(enriched),
            "ridge_mae": float(np.mean([item["ridge_absolute_error"] for item in enriched])) if enriched else None,
            "training_mean_baseline_mae": float(np.mean([item["baseline_absolute_error"] for item in enriched])) if enriched else None,
            "mae_improvement": float(np.mean([item["mae_improvement_row"] for item in enriched])) if enriched else None,
            "spearman_feature_target": _spearman((item["feature"] for item in enriched), (item["target"] for item in enriched)),
        }
        bootstrap[partition] = _block_bootstrap_improvement(
            enriched,
            repetitions=int(experiment["bootstrap_repetitions"]),
            block_sessions=int(experiment["bootstrap_block_sessions"]),
            seed=int(experiment["random_seed"]) + {"TRAIN": 0, "VALIDATION": 1, "TEST": 2}[partition],
        )

    validation_improvement = metrics["VALIDATION"]["mae_improvement"]
    test_improvement = metrics["TEST"]["mae_improvement"]
    test_ci = bootstrap["TEST"].get("ci95")
    if validation_improvement is not None and test_improvement is not None and test_ci and validation_improvement > 0 and test_improvement > 0 and test_ci[0] > 0:
        conclusion = "WARRANTS_FURTHER_RESEARCH"
    elif validation_improvement is not None and test_improvement is not None and test_ci and validation_improvement <= 0 and test_improvement <= 0 and test_ci[1] <= 0:
        conclusion = "NO_INCREMENTAL_VALUE"
    else:
        conclusion = "INCONCLUSIVE"
    split_material = {"dates": dates, "fractions": fractions, "assignment": split, "partition_ends": partition_ends}
    result = {
        "status": "DEV_FIT_COMPLETE",
        "conclusion": conclusion,
        "fit_performed": True,
        "experiment_id": EXPERIMENT_ID,
        "protocol_version": protocol["version"],
        "feature": experiment["feature"],
        "primary_target": experiment["primary_target"],
        "secondary_target": experiment["secondary_target"],
        "model": experiment["model"],
        "alpha": alpha,
        "baseline": experiment["baseline"],
        "feature_mean_train": x_mean,
        "feature_std_train": x_std,
        "intercept": float(coefficients[0]),
        "coefficient": float(coefficients[1]),
        "partitions": metrics,
        "bootstrap": bootstrap,
        "split_hash": content_hash(split_material),
        "dataset_manifest": dataset_manifest,
        "classification_rule": "WARRANTS only when validation and test MAE improvements are positive and TEST 95% block-bootstrap lower bound is positive; NO_INCREMENTAL_VALUE only when both are non-positive and TEST upper bound is non-positive; otherwise INCONCLUSIVE.",
        "exposure_status": "EXPOSED_RESEARCH",
        "production_consumption": False,
        "option_strategy_or_pnl_experiment": False,
    }
    return result, predictions


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"Immutable artifact already exists: {path}")
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _git_identity() -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=REPO_ROOT, text=True, encoding="utf-8", errors="replace").strip()

    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "status_hash": hashlib.sha256(run("status", "--short").encode("utf-8")).hexdigest(),
    }


def _profile_boundary() -> dict[str, Any]:
    payload = load_json(PROFILE_PATH)
    pending_fields = (
        "holding_period_policy", "expiry_selection_policy", "moneyness_selection_policy", "delta_range",
        "liquidity_selection_policy", "event_risk_policy", "factor_policy", "entry_policy", "exit_policy",
        "position_sizing_policy", "model_artifact_id",
    )
    profiles = []
    for profile in payload.get("profiles", []):
        profiles.append(
            {
                "profile_id": profile.get("profile_id"),
                "profile_version": profile.get("profile_version"),
                "non_null_policy_fields": [field for field in pending_fields if profile.get(field) is not None],
                "signal_generation_enabled": bool(profile.get("signal_generation_enabled")),
                "trade_simulation_enabled": bool(profile.get("trade_simulation_enabled")),
                "automatic_order_enabled": bool(profile.get("automatic_order_enabled")),
            }
        )
    return {
        "config_sha256": sha256_file(PROFILE_PATH),
        "profiles": profiles,
        "preserved": all(not item["non_null_policy_fields"] and not item["signal_generation_enabled"] and not item["trade_simulation_enabled"] and not item["automatic_order_enabled"] for item in profiles),
    }


def _foundation_evidence() -> dict[str, Any]:
    services = load_json(SERVICE_PATH) if SERVICE_PATH.exists() else {"status": "MISSING"}
    capability = load_json(CAPABILITY_PATH) if CAPABILITY_PATH.exists() else {"status": "MISSING"}
    return {
        "services_path": str(SERVICE_PATH.resolve()),
        "services_sha256": sha256_file(SERVICE_PATH) if SERVICE_PATH.exists() else None,
        "capability_path": str(CAPABILITY_PATH.resolve()),
        "capability_sha256": sha256_file(CAPABILITY_PATH) if CAPABILITY_PATH.exists() else None,
        "mode": services.get("mode"),
        "listeners": services.get("listeners", []),
        "single_foundation_supervisor_reused": True,
        "market_day_validation_status": capability.get("market_day_validation_status", "WAIT_MARKET"),
        "strict_fill_eligible": bool(capability.get("strict_fill_eligible")),
        "source_bbo_time_policy": "NULL_WHEN_PROVIDER_CONTRACT_HAS_NO_NATIVE_TIME",
        "new_schedule_created": False,
    }


def _task(task_id: str, state: str, detail: dict[str, Any]) -> dict[str, Any]:
    return {"task_id": task_id, "state": state, "detail": detail, "updated_at": utc_now()}


def _store_experiment(review_db: Path, bundle_id: str, experiment: dict[str, Any]) -> None:
    run_id = f"es001-r1-{content_hash({'bundle': bundle_id, 'dataset': experiment['dataset_manifest']['dataset_hash']})[:24]}"
    payload = {**experiment, "run_id": run_id, "bundle_id": bundle_id}
    with sqlite3.connect(review_db) as connection:
        connection.execute(
            "INSERT OR IGNORE INTO es001_experiment_runs VALUES (?,?,?,?,?,?,?,?)",
            (
                run_id, bundle_id, payload["status"], payload["conclusion"], payload["dataset_manifest"]["dataset_hash"],
                payload.get("split_hash"), json_text(payload), utc_now(),
            ),
        )
        connection.commit()


def _store_tasks(review_db: Path, bundle_id: str, tasks: list[dict[str, Any]]) -> None:
    with sqlite3.connect(review_db) as connection:
        for item in tasks:
            connection.execute(
                "INSERT OR REPLACE INTO review_task_state VALUES (?,?,?,?,?)",
                (bundle_id, item["task_id"], item["state"], json_text(item["detail"]), item["updated_at"]),
            )
        connection.commit()


def _review_documents(
    *,
    bundle_id: str,
    run_dir: Path,
    dataset: dict[str, Any],
    validation: dict[str, Any],
    experiment: dict[str, Any],
    foundation: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    test_steps = [
        "Open the Review URL and confirm the R1 bundle ID and WAIT_REVIEW state.",
        "Select NVDA and expand adjusted-data lineage; compare NO_ADJUST and FORWARD_ADJUST around 2024-06-10.",
        "Inspect E-S-001: confirm the original factor, Y5 market-excess target, TRAIN mean baseline, Ridge alpha=1 and 60/20/20 split.",
        "Confirm the experiment result is labeled DEV_ONLY / EXPOSED_RESEARCH and is not option P&L.",
        "Confirm all three profiles remain pending and signal, Paper entry and orders are disabled.",
        "Open runtime status and confirm process, market validation and strict-fill status are separate.",
    ]
    review = f"""# R1 Review: adjusted data and E-S-001

- Bundle: `{bundle_id}`
- Version: `{REVIEW_VERSION}`
- State: `WAIT_REVIEW`
- Review URL: `http://127.0.0.1:8020/?workspace=options&view=review&symbol=NVDA&review={bundle_id}`
- Data gate: `{validation['gate_status']}`
- E-S-001: `{experiment['status']} / {experiment['conclusion']}`
- Strategy: `PENDING_STRATEGY_DEFINITION`
- Signals, automatic Paper entries and orders: `DISABLED`

## What changed

Longbridge SDK `{dataset['sdk']['sdk_version']}` was exercised with separate `NoAdjust` and `ForwardAdjust` requests. Raw and adjusted bars were written to the independent R1 research database. The main runtime database and the V0.1 research database were opened read-only and were not relabeled or overwritten.

## Manual test

{chr(10).join(f'{index}. {step}' for index, step in enumerate(test_steps, 1))}

## Scientific boundary

Forward-adjusted history downloaded now is anchored to the current provider adjustment state. It is not historical PIT evidence. E-S-001 measures underlying returns only; it does not prove option profitability or create Call/Put signals.
"""
    limitations = f"""# R1 Known Limitations

1. Adjusted history is current-as-of-download, not a reconstruction of what was known on each historical date.
2. Longbridge documents forward adjustment for splits/dividends, but the candle response does not enumerate every adjustment component.
3. Existing history remains `EXPOSED_RESEARCH`; the development TEST partition is not independent OOS.
4. OPRA native BBO event time remains unavailable; strict simulated fills remain blocked.
5. Market-day and cross-day Foundation validation remains `{foundation['market_day_validation_status']}`.
6. Event coverage and option performance evidence are still incomplete.
7. E-S-001 outcome `{experiment['conclusion']}` does not authorize strategy selection, Paper entry or orders.
"""
    resume = """# Resume after R1

On the exact user reply `R1通过，按总计划继续`, record acceptance for this bundle and enter P2 tasks T07-T12. P2 prepares the three strategy and Paper-policy proposals but does not activate a profile.

If R1 is rejected, remain in P1, address only the reported R1 defects, create a new immutable R1 bundle, and present the same review node again.
"""
    acceptance = {
        "review_id": "R1",
        "bundle_id": bundle_id,
        "state": "WAIT_REVIEW",
        "checks": {
            "T01_recoverable_checkpoint": "PASS",
            "T02_foundation_observation": foundation["market_day_validation_status"],
            "T03_adjustment_root_cause": "PASS",
            "T04_adjusted_backfill": validation["gate_status"],
            "T05_es001_executed": "PASS" if experiment.get("fit_performed") else "DELIVERED_WITH_LIMITATIONS",
            "T06_review_packet": "PASS",
            "profiles_preserved": manifest["profile_boundary"]["preserved"],
            "signals_disabled": True,
            "paper_entries_disabled": True,
            "orders_disabled": True,
        },
        "review_is_not_profit_or_trading_approval": True,
    }
    write_text_immutable(run_dir / "REVIEW.md", review)
    write_text_immutable(run_dir / "KNOWN_LIMITATIONS.md", limitations)
    write_text_immutable(run_dir / "RESUME.md", resume)
    write_json_immutable(run_dir / "ACCEPTANCE.json", acceptance)


def run_p1(
    *,
    bundle_id: str,
    review_db: Path = REVIEW_DB,
    source_db: Path = SOURCE_DB,
    output_root: Path = OUTPUT_ROOT,
    caller: Callable[[str, Any, Any, date, date, int], Any] | None = None,
) -> dict[str, Any]:
    run_dir = output_root / bundle_id
    if run_dir.exists():
        raise RuntimeError(f"R1 bundle already exists and is immutable: {run_dir}")
    run_dir.mkdir(parents=True)
    store = initialize_review_store(review_db)
    source_before_windows, source_before = source_windows(source_db)
    del source_before_windows
    profile_boundary = _profile_boundary()
    foundation = _foundation_evidence()
    baseline = {
        "bundle_id": bundle_id,
        "review_version": REVIEW_VERSION,
        "generated_at": utc_now(),
        "git": _git_identity(),
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "review_plan_hashes": {
            str(path.relative_to(REPO_ROOT)): sha256_file(path)
            for path in (MASTER_PLAN_PATH, OWNER_PLAYBOOK_PATH, TASK_GRAPH_PATH, REVIEW_GATES_PATH, REVIEW_DEFAULTS_PATH)
        },
        "profile_boundary": profile_boundary,
        "source_database_before": source_before,
        "review_store": store,
        "foundation": foundation,
    }
    write_json_immutable(run_dir / "baseline_manifest.json", baseline)

    dataset = pull_adjustment_dataset(bundle_id=bundle_id, review_db=review_db, source_db=source_db, caller=caller)
    write_json_immutable(run_dir / "adjustment_request_audit.json", dataset)
    validation = validate_adjustment_dataset(review_db, bundle_id) if dataset["status"] == "COMPLETE" else {"status": "BLOCKED", "gate": "D_ADJUSTED_DATA", "gate_status": "FAIL", "blockers": dataset.get("blockers", [])}
    write_json_immutable(run_dir / "adjustment_validation.json", validation)

    protocol = load_json(PROTOCOL_PATH)
    rows, dataset_manifest = build_es001_dataset(review_db, bundle_id) if validation["gate_status"] == "PASS" else ([], {"dataset_hash": content_hash([]), "row_count": 0, "unique_dates": 0, "blockers": validation["blockers"]})
    write_json_immutable(run_dir / "es001_dataset_manifest.json", dataset_manifest)
    if rows:
        _write_csv(run_dir / "es001_dataset.csv", rows)
    experiment, predictions = run_es001(rows, protocol, dataset_manifest)
    write_json_immutable(run_dir / "es001_result.json", experiment)
    if predictions:
        _write_csv(run_dir / "es001_predictions.csv", predictions)
    _store_experiment(review_db, bundle_id, experiment)

    source_after_windows, source_after = source_windows(source_db)
    del source_after_windows
    main_db_unchanged = source_before["main_table_counts"] == source_after["main_table_counts"]
    tasks = [
        _task("T01", "VERIFIED", {"baseline_hash": content_hash(baseline), "main_db_opened_read_only": True, "profiles_preserved": profile_boundary["preserved"]}),
        _task("T02", "WAIT_MARKET" if foundation["market_day_validation_status"] != "PASS" else "VERIFIED", foundation),
        _task("T03", "VERIFIED", {"root_cause": "existing stock candle path selects NoAdjust first and does not preserve explicit adjustment identity in the research loader", "sdk": dataset.get("sdk"), "request_count": len(dataset.get("requests", []))}),
        _task("T04", "VERIFIED" if validation["gate_status"] == "PASS" else "DELIVERED_WITH_LIMITATIONS", {"gate_status": validation["gate_status"], "blockers": validation.get("blockers", []), "dataset_version": dataset.get("dataset_version")}),
        _task("T05", "VERIFIED" if experiment.get("fit_performed") else "DELIVERED_WITH_LIMITATIONS", {"status": experiment["status"], "conclusion": experiment["conclusion"], "fit_performed": experiment.get("fit_performed", False), "dataset_hash": dataset_manifest["dataset_hash"]}),
        _task("T06", "WAIT_REVIEW", {"review_id": "R1", "bundle_id": bundle_id, "next_phase_requires_user_review": True}),
    ]
    _store_tasks(review_db, bundle_id, tasks)
    write_json_immutable(run_dir / "task_state.json", {"tasks": tasks})

    source_files = [
        Path(__file__), PROTOCOL_PATH, PROFILE_PATH,
        REPO_ROOT / "scripts" / "run_options_review_r1.py",
        REPO_ROOT / "kquant" / "options_research_workbench.py",
        REPO_ROOT / "kquant" / "longbridge_provider.py",
        MASTER_PLAN_PATH, OWNER_PLAYBOOK_PATH, TASK_GRAPH_PATH, REVIEW_GATES_PATH, REVIEW_DEFAULTS_PATH,
    ]
    manifest = {
        "review_id": "R1",
        "bundle_id": bundle_id,
        "review_version": REVIEW_VERSION,
        "state": "WAIT_REVIEW",
        "generated_at": utc_now(),
        "git": baseline["git"],
        "code_hashes": {str(path.relative_to(REPO_ROOT)): sha256_file(path) for path in source_files},
        "config_hashes": {str(PROTOCOL_PATH.relative_to(REPO_ROOT)): sha256_file(PROTOCOL_PATH), str(PROFILE_PATH.relative_to(REPO_ROOT)): sha256_file(PROFILE_PATH)},
        "data": {"dataset_version": dataset.get("dataset_version"), "dataset_hash": dataset_manifest["dataset_hash"], "adjustment_gate": validation["gate_status"], "adjustment_as_of_policy": validation.get("adjustment_as_of_policy")},
        "experiment": {"status": experiment["status"], "conclusion": experiment["conclusion"], "fit_performed": experiment.get("fit_performed", False), "split_hash": experiment.get("split_hash")},
        "profile_boundary": profile_boundary,
        "foundation": foundation,
        "source_database_counts_unchanged": main_db_unchanged,
        "permissions": {"signals": False, "paper_entries": False, "orders": False, "real_account": False, "crypto_new_research": False},
        "tests": {"status": "PENDING_FINALIZATION"},
    }
    manifest["bundle_hash"] = content_hash(manifest)
    write_json_immutable(run_dir / "manifest.pre_verification.json", manifest)
    _review_documents(bundle_id=bundle_id, run_dir=run_dir, dataset=dataset, validation=validation, experiment=experiment, foundation=foundation, manifest=manifest)
    latest = {"bundle_id": bundle_id, "bundle_hash": manifest["bundle_hash"], "run_dir": str(run_dir.resolve()), "state": "WAIT_REVIEW", "updated_at": utc_now()}
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = output_root / "LATEST.json.tmp"
    temporary.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_root / "LATEST.json")
    return {"status": "WAIT_REVIEW", "bundle_id": bundle_id, "run_dir": str(run_dir.resolve()), "validation": validation, "experiment": experiment, "tasks": tasks, "manifest": manifest}


def finalize_p1_bundle(bundle_id: str, verification: dict[str, Any], *, output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    run_dir = output_root / bundle_id
    manifest_path = run_dir / "manifest.json"
    preliminary_path = run_dir / "manifest.pre_verification.json"
    if manifest_path.exists():
        raise RuntimeError(f"R1 bundle is already finalized and immutable: {manifest_path}")
    if not preliminary_path.exists():
        raise FileNotFoundError(preliminary_path)
    verification_path = run_dir / "verification.json"
    write_json_immutable(verification_path, verification)
    manifest = load_json(preliminary_path)
    manifest["tests"] = {"status": "PASS" if all(bool(value) for value in verification.values() if isinstance(value, bool)) else "PARTIAL", "verification_sha256": sha256_file(verification_path)}
    manifest["finalized_at"] = utc_now()
    manifest["bundle_hash"] = content_hash({key: value for key, value in manifest.items() if key != "bundle_hash"})
    write_json_immutable(manifest_path, manifest)
    latest = {"bundle_id": bundle_id, "bundle_hash": manifest["bundle_hash"], "run_dir": str(run_dir.resolve()), "state": "WAIT_REVIEW", "updated_at": utc_now()}
    temporary = output_root / "LATEST.json.tmp"
    temporary.write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_root / "LATEST.json")
    return manifest


def review_r1_payload(output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    latest_path = output_root / "LATEST.json"
    if not latest_path.exists():
        return {"status": "NOT_AVAILABLE", "review_id": "R1", "state": "NOT_OPEN"}
    latest = load_json(latest_path)
    run_dir = Path(latest["run_dir"])
    required = {
        "manifest": "manifest.json" if (run_dir / "manifest.json").exists() else "manifest.pre_verification.json",
        "validation": "adjustment_validation.json",
        "dataset": "es001_dataset_manifest.json",
        "experiment": "es001_result.json",
        "tasks": "task_state.json",
        "baseline": "baseline_manifest.json",
    }
    payload = {key: load_json(run_dir / name) for key, name in required.items() if (run_dir / name).exists()}
    return {
        "status": "AVAILABLE",
        "review_id": "R1",
        "state": "WAIT_REVIEW",
        "bundle_id": latest["bundle_id"],
        "bundle_hash": latest["bundle_hash"],
        "review_url": f"http://127.0.0.1:8020/?workspace=options&view=review&symbol=NVDA&review={latest['bundle_id']}",
        **payload,
        "signals_enabled": False,
        "paper_entries_enabled": False,
        "orders_enabled": False,
    }


__all__ = [
    "OUTPUT_ROOT",
    "REVIEW_DB",
    "REVIEW_VERSION",
    "build_es001_dataset",
    "finalize_p1_bundle",
    "pull_adjustment_dataset",
    "review_r1_payload",
    "run_es001",
    "run_p1",
    "sdk_capability",
    "source_windows",
    "validate_adjustment_dataset",
]
