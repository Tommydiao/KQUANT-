from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import statistics
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from .market_clock import is_trading_day
from .options_radar import RADAR_UNIVERSE, SECTOR_BENCHMARK
from .options_research_features import (
    compute_equity_feature_snapshot,
    compute_option_feature_snapshot,
    content_hash,
    feature_dictionary,
)
from .options_research_scenarios import local_greeks_scenario_grid, synthetic_scenario_validation
from .options_research_store import (
    initialize_research_store,
    list_payloads,
    put_cohort,
    put_experiment,
    put_feature_definitions,
    put_feature_snapshot,
    put_hypothesis,
    put_review_card,
    put_scenario,
    put_universe_manifest,
    register_protocol,
    research_status,
    update_task,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = REPO_ROOT / "config" / "options_research_protocol_v0_1.json"
TASK_GRAPH_PATH = REPO_ROOT / "plan" / "options_research_tasks.v0_1.json"
PROFILE_PATH = REPO_ROOT / "config" / "options_research_profiles_v1.json"
DEFAULT_RESEARCH_DB = REPO_ROOT / "work" / "options_research_v0_1" / "options_research_v0_1.sqlite3"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "outputs" / "options_research_v0_1"
DEFAULT_SOURCE_DB = REPO_ROOT / "work" / "kquant_us.sqlite3"
CAPABILITY_PATH = REPO_ROOT / "work" / "option_foundation" / "runtime" / "latest_capability.json"
SERVICE_IDENTITY_PATH = REPO_ROOT / "work" / "option_foundation" / "runtime" / "services.json"

EXPERIMENT_ID = "E-S-001_EXCESS_RS20_TO_FORWARD5"
WORKBENCH_VERSION = "options_research_workbench_v0.1.0"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_immutable(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise RuntimeError(f"Immutable artifact already exists with different content: {path}")
        return
    path.write_text(text, encoding="utf-8", newline="\n")


def _write_text_immutable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = text.rstrip() + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != normalized:
            raise RuntimeError(f"Immutable artifact already exists with different content: {path}")
        return
    path.write_text(normalized, encoding="utf-8", newline="\n")


def _readonly_connection(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _profile_null_check() -> dict[str, Any]:
    payload = _load_json(PROFILE_PATH)
    pending_fields = [
        "holding_period_policy", "expiry_selection_policy", "moneyness_selection_policy", "delta_range",
        "liquidity_selection_policy", "event_risk_policy", "factor_policy", "entry_policy", "exit_policy",
        "position_sizing_policy", "model_artifact_id",
    ]
    results: list[dict[str, Any]] = []
    for profile in payload.get("profiles", []):
        non_null = [field for field in pending_fields if profile.get(field) is not None]
        results.append(
            {
                "profile_id": profile.get("profile_id"),
                "profile_version": profile.get("profile_version"),
                "non_null_pending_fields": non_null,
                "signal_generation_enabled": bool(profile.get("signal_generation_enabled")),
                "trade_simulation_enabled": bool(profile.get("trade_simulation_enabled")),
                "automatic_order_enabled": bool(profile.get("automatic_order_enabled")),
            }
        )
    return {
        "config_path": str(PROFILE_PATH),
        "config_sha256": _sha256(PROFILE_PATH),
        "profiles": results,
        "preserved": all(
            not item["non_null_pending_fields"]
            and not item["signal_generation_enabled"]
            and not item["trade_simulation_enabled"]
            and not item["automatic_order_enabled"]
            for item in results
        ),
    }


def _source_db_identity(db_path: Path) -> dict[str, Any]:
    stat = db_path.stat()
    with _readonly_connection(db_path) as connection:
        schema_version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("market_candles", "option_radar_runs", "option_opportunities", "option_plans", "option_quote_evidence", "option_outcomes")
        }
        query_only = int(connection.execute("PRAGMA query_only").fetchone()[0])
    return {
        "path": str(db_path.resolve()),
        "bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
        "schema_version": schema_version,
        "counts": counts,
        "opened_with_mode_ro": True,
        "query_only": query_only,
    }


def freeze_workbench(
    *,
    research_db: Path = DEFAULT_RESEARCH_DB,
    source_db: Path = DEFAULT_SOURCE_DB,
    run_dir: Path,
) -> dict[str, Any]:
    protocol = _load_json(PROTOCOL_PATH)
    graph = _load_json(TASK_GRAPH_PATH)
    store = initialize_research_store(research_db)
    registration = register_protocol(research_db, protocol)
    for task in graph.get("tasks", []):
        update_task(research_db, task["id"], "TODO", {"title": task["title"], "dependencies": task.get("dependencies", [])})
    profile_check = _profile_null_check()
    service_identity = _load_json(SERVICE_IDENTITY_PATH) if SERVICE_IDENTITY_PATH.exists() else {"status": "MISSING"}
    capability = _load_json(CAPABILITY_PATH) if CAPABILITY_PATH.exists() else {"status": "MISSING"}
    baseline = {
        "workbench_version": WORKBENCH_VERSION,
        "generated_at": _now(),
        "protocol": registration,
        "protocol_source_sha256": _sha256(PROTOCOL_PATH),
        "task_graph_sha256": _sha256(TASK_GRAPH_PATH),
        "profiles": profile_check,
        "source_database": _source_db_identity(source_db),
        "research_store": store,
        "foundation_service_identity": service_identity,
        "foundation_capability": {
            "path": str(CAPABILITY_PATH),
            "sha256": _sha256(CAPABILITY_PATH) if CAPABILITY_PATH.exists() else None,
            "market_day_validation_status": capability.get("market_day_validation_status"),
            "strict_fill_eligible": capability.get("strict_fill_eligible"),
            "strategy_status": capability.get("strategy_status"),
            "performance_status": capability.get("performance_status"),
        },
        "security": protocol.get("security"),
    }
    _write_immutable(run_dir / "baseline_manifest.json", baseline)
    update_task(research_db, "R00", "VERIFIED", {"baseline_hash": content_hash(baseline), "profiles_preserved": profile_check["preserved"]})
    update_task(
        research_db,
        "R01",
        "WAIT_MARKET",
        {
            "existing_supervisor_reused": True,
            "market_day_validation_status": capability.get("market_day_validation_status", "WAIT_MARKET"),
            "next_check": ((service_identity.get("foundation_status") or {}).get("next_foundation_market_check_at")),
            "no_duplicate_schedule_created": True,
        },
    )
    update_task(
        research_db,
        "R02",
        "VERIFIED",
        {
            "capability_evidence_hash": baseline["foundation_capability"]["sha256"],
            "source_bbo_time_policy": "NULL_WHEN_PROVIDER_CONTRACT_HAS_NO_NATIVE_TIME",
            "receipt_time_is_native_time": False,
            "strict_fill_eligible": False,
        },
    )
    return baseline


def _row_values(row: sqlite3.Row) -> tuple[float, float, float, float, float]:
    return tuple(round(float(row[name]), 10) for name in ("open", "high", "low", "close", "volume"))  # type: ignore[return-value]


def _load_daily_series(connection: sqlite3.Connection, symbol: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = connection.execute(
        """SELECT open_time,open,high,low,close,volume,adjustment_mode,dataset_version,primary_source,
                  bar_state,fetched_at,first_seen_at,updated_at
           FROM market_candles
           WHERE symbol=? AND interval='1d' AND primary_source='longbridge_candles' AND bar_state='closed_candle'
           ORDER BY open_time""",
        (symbol,),
    ).fetchall()
    grouped: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        grouped.setdefault(str(row["open_time"])[:10], []).append(row)
    bars: list[dict[str, Any]] = []
    duplicate_aliases = 0
    conflicts: list[str] = []
    for market_date, candidates in sorted(grouped.items()):
        identities = {_row_values(row) for row in candidates}
        if len(identities) > 1:
            conflicts.append(market_date)
            continue
        duplicate_aliases += max(len(candidates) - 1, 0)
        row = sorted(candidates, key=lambda item: str(item["open_time"]))[-1]
        bars.append(
            {
                "market_date": market_date,
                "open_time": row["open_time"],
                "open": row["open"], "high": row["high"], "low": row["low"], "close": row["close"], "volume": row["volume"],
                "adjustment_mode": row["adjustment_mode"], "dataset_version": row["dataset_version"], "source": row["primary_source"],
                "available_at": row["first_seen_at"] or row["fetched_at"],
                "updated_at": row["updated_at"],
                "source_ref": content_hash({"symbol": symbol, "market_date": market_date, "values": _row_values(row), "source": row["primary_source"]}),
            }
        )
    coverage = {
        "symbol": symbol,
        "raw_rows": len(rows),
        "unique_market_dates": len(grouped),
        "usable_dates": len(bars),
        "duplicate_time_alias_rows": duplicate_aliases,
        "conflicting_dates": conflicts,
        "start": bars[0]["market_date"] if bars else None,
        "end": bars[-1]["market_date"] if bars else None,
        "adjustment_modes": sorted({str(item["adjustment_mode"]) for item in bars}),
        "dataset_versions": sorted({str(item["dataset_version"]) for item in bars}),
        "source": "longbridge_candles",
        "historical_exposure": "EXPOSED_RESEARCH",
        "point_in_time_limit": "historical fetch times do not reproduce original market availability",
    }
    return bars, coverage


def _event_coverage(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT e.symbol,e.status,e.as_of,e.created_at,e.payload_json
           FROM option_event_evidence e
           JOIN (SELECT symbol,MAX(created_at) created_at FROM option_event_evidence GROUP BY symbol) latest
             ON latest.symbol=e.symbol AND latest.created_at=e.created_at"""
    ).fetchall()
    by_symbol = {str(row["symbol"]): dict(row) for row in rows}
    result = []
    for symbol in RADAR_UNIVERSE:
        row = by_symbol.get(symbol)
        result.append(
            {
                "symbol": symbol,
                "status": row["status"] if row else "NOT_INGESTED",
                "as_of": row["as_of"] if row else None,
                "coverage_statement": "EVENT_COVERAGE_UNKNOWN",
                "eligible_for_event_claims": False,
            }
        )
    return result


def _universe_manifest(coverage: list[dict[str, Any]]) -> dict[str, Any]:
    members = []
    for symbol in RADAR_UNIVERSE:
        members.append(
            {
                "symbol": symbol,
                "entity_type": "ETF" if symbol in {"SPY", "QQQ", "IWM"} else "STOCK",
                "market_benchmark": "SPY",
                "sector_benchmark": SECTOR_BENCHMARK.get(symbol),
                "membership_source": "options_radar_v1_frozen_universe",
            }
        )
    material = {"members": members, "coverage": coverage, "status": "FROZEN_RESEARCH_UNIVERSE"}
    return {"manifest_id": f"oru-{content_hash(material)[:24]}", "as_of": _now(), **material}


def hypothesis_cards() -> list[dict[str, Any]]:
    shared = {
        "version": "0.1.0",
        "lifecycle_state": "REGISTERED",
        "execution_difference": "Research measurements do not define contract selection, entry, exit, or position sizing.",
        "strategy_policy_mutation": False,
    }
    return [
        {
            **shared,
            "hypothesis_id": "H-S-01", "profile_id": "SHORT_ATM_DAYS_WEEK", "mechanism": "Underlying relative sector strength may contain information about subsequent multi-session direction and magnitude.",
            "observable_information": ["excess_log_return_20_sector", "realized_volatility_20", "relative_volume_20"],
            "target": "forward five-session underlying excess return in E-S-001", "benchmark": "training mean",
            "invalidators": ["no verified adjusted price basis", "sector benchmark unavailable", "no incremental error improvement"],
            "data_gaps": ["historical option NBBO is unavailable", "event coverage is unknown"],
            "experiment_budget": [EXPERIMENT_ID], "next_stage_requirement": "separate policy discussion after honest development evidence",
        },
        {
            **shared,
            "hypothesis_id": "H-M-01", "profile_id": "MEDIUM_ATM_WEEKS_MONTHS", "mechanism": "Industry and underlying trend persistence may support a multi-week observation while option carry remains material.",
            "observable_information": ["log_return_60", "realized_volatility_20", "theta_per_day", "displayed_extrinsic"],
            "target": "data coverage and deterministic carry sensitivity only", "benchmark": "no-position observation",
            "invalidators": ["event coverage unknown", "insufficient comparable IV history", "long outcome not matured"],
            "data_gaps": ["no registered medium-horizon target", "no historical comparable option surface"],
            "experiment_budget": [], "next_stage_requirement": "owner defines target and policy in a later version",
        },
        {
            **shared,
            "hypothesis_id": "H-L-01", "profile_id": "LONG_OTM_MONTHS_YEAR", "mechanism": "A sourced long-horizon catalyst may justify paying OTM premium only if magnitude and timing survive volatility and time-decay scenarios.",
            "observable_information": ["log_moneyness", "displayed_extrinsic", "vega_per_volatility_point", "theta_per_day"],
            "target": "catalyst evidence and deterministic sensitivity comparison", "benchmark": "no-position observation",
            "invalidators": ["catalyst lacks a source", "timing cannot be observed", "long outcome not matured"],
            "data_gaps": ["no long-horizon catalyst dataset", "no 120/252-session mature observations"],
            "experiment_budget": [], "next_stage_requirement": "collect sourced catalysts and mature observations before policy definition",
        },
    ]


def experiment_registration(protocol: dict[str, Any]) -> dict[str, Any]:
    frozen_contract = {
        **protocol["primary_experiment"],
        "protocol_version": protocol["version"],
        "registration_status": "REGISTERED_BEFORE_RESULT_READ",
        "exposure_status": "EXPOSED_RESEARCH",
        "option_strategy_or_pnl_experiment": False,
    }
    return {**frozen_contract, "registered_at": _now(), "registration_hash": content_hash(frozen_contract)}


def _next_trading_dates(anchor: date, counts: list[int]) -> dict[int, dict[str, Any]]:
    targets: dict[int, dict[str, Any]] = {}
    current = anchor
    observed = 0
    maximum = max(counts)
    while observed < maximum:
        current += timedelta(days=1)
        try:
            trading_day = is_trading_day(current)
        except Exception:
            for unresolved in counts:
                if unresolved not in targets:
                    targets[unresolved] = {
                        "target_check_at": None,
                        "calendar_status": "CALENDAR_RANGE_UNAVAILABLE",
                        "last_resolved_calendar_date": (current - timedelta(days=1)).isoformat(),
                    }
            break
        if trading_day:
            observed += 1
            if observed in counts:
                targets[observed] = {"target_check_at": current.isoformat(), "calendar_status": "EXCHANGE_CALENDAR_RESOLVED"}
    return targets


def _build_cohort(capability: dict[str, Any], protocol: dict[str, Any]) -> dict[str, Any]:
    samples = list(capability.get("samples") or [])[: int(protocol["observation_cohort"]["max_live_contracts"])]
    anchor = datetime.fromisoformat(str(capability["generated_at"]).replace("Z", "+00:00"))
    sessions = [*protocol["observation_cohort"]["future_checkpoints_sessions"], *protocol["observation_cohort"]["long_metadata_only_checkpoints_sessions"]]
    targets = _next_trading_dates(anchor.date(), sessions)
    policy = {
        "purpose": protocol["observation_cohort"]["purpose"],
        "fixed_contract_identity": True,
        "silent_contract_roll_allowed": False,
        "future_checkpoints_sessions": sessions,
        "automatic_position_or_cash_ledger": False,
        "profile_fit": "UNSPECIFIED",
        "source_capability_hash": _sha256(CAPABILITY_PATH),
    }
    cohort_id = f"orc-{content_hash({'policy': policy, 'contracts': [item.get('contract_id') for item in samples]})[:24]}"
    checkpoints = []
    for sample in samples:
        for session_count in sessions:
            target = targets[session_count]
            material = {"cohort_id": cohort_id, "contract_id": sample.get("contract_id"), "sessions": session_count, "target": target}
            checkpoints.append(
                {
                    "outcome_id": f"oro-{content_hash(material)[:24]}",
                    "contract_id": sample.get("contract_id"),
                    "checkpoint_sessions": session_count,
                    "target_check_at": target.get("target_check_at") or "UNRESOLVED",
                    "calendar_status": target["calendar_status"],
                    "outcome_status": "PENDING" if target.get("target_check_at") else "WAIT_CALENDAR_RANGE",
                    "measurement": "QUOTE_AND_IV_CHANGE_NOT_TRADE_PNL",
                    "position_created": False,
                }
            )
    return {
        "cohort_id": cohort_id,
        "status": "OBSERVING_NO_POSITION",
        "purpose": "CAPABILITY_OR_DATA_COHORT",
        "profile_fit": "UNSPECIFIED",
        "anchor_observation_at": capability.get("generated_at"),
        "evidence_level": capability.get("evidence_level"),
        "strict_fill_eligible": False,
        "contracts": [
            {"contract_id": item.get("contract_id"), "underlying": item.get("underlying"), "right": item.get("right"), "expiry_date": item.get("expiry_date"), "strike_price": item.get("strike_price")}
            for item in samples
        ],
        "checkpoints": checkpoints,
        "policy": policy,
        "policy_hash": content_hash(policy),
        "entry_policy": None,
        "exit_policy": None,
        "sizing_policy": None,
        "trade_pnl_allowed": False,
    }


def _experiment_preflight(coverage: list[dict[str, Any]]) -> dict[str, Any]:
    blockers = []
    if any("verified_adjusted" not in item.get("adjustment_modes", []) for item in coverage):
        blockers.append("NO_VERIFIED_ADJUSTED_DAILY_PRICE_BASIS")
    if any(item.get("conflicting_dates") for item in coverage):
        blockers.append("CONFLICTING_DAILY_BARS_PRESENT")
    return {
        "eligible": not blockers,
        "blockers": blockers,
        "coverage_symbols": len(coverage),
        "usable_market_dates": {item["symbol"]: item["usable_dates"] for item in coverage},
        "duplicate_time_alias_rows": {item["symbol"]: item["duplicate_time_alias_rows"] for item in coverage if item["duplicate_time_alias_rows"]},
        "price_basis_required": "CONSISTENT_ADJUSTED_CLOSED_DAILY_PRICE",
        "observed_adjustment_modes": {item["symbol"]: item["adjustment_modes"] for item in coverage},
    }


def run_single_feature_ridge(rows: list[dict[str, Any]], protocol: dict[str, Any]) -> dict[str, Any]:
    dates = sorted({str(item["date"]) for item in rows})
    minimum = int(protocol["primary_experiment"]["minimum_numeric_fit_train_dates"])
    if len(dates) < minimum:
        return {"status": "DATA_INSUFFICIENT", "reason": "INSUFFICIENT_UNIQUE_DATES", "unique_dates": len(dates)}
    fractions = protocol["primary_experiment"]["development_split_fractions"]
    train_end = max(1, int(len(dates) * fractions[0]))
    validation_end = max(train_end + 1, int(len(dates) * (fractions[0] + fractions[1])))
    split = {value: "TRAIN" if index < train_end else ("VALIDATION" if index < validation_end else "TEST") for index, value in enumerate(dates)}
    partition_ends = {"TRAIN": dates[train_end - 1], "VALIDATION": dates[validation_end - 1], "TEST": dates[-1]}
    eligible_rows = [
        item for item in rows
        if str(item.get("label_end_date")) <= partition_ends[split[str(item["date"])]]
    ]
    train = [item for item in eligible_rows if split[str(item["date"])] == "TRAIN"]
    if len({item["date"] for item in train}) < minimum:
        return {"status": "DATA_INSUFFICIENT", "reason": "TRAIN_DATES_AFTER_PURGE_BELOW_GUARD", "train_dates": len({item["date"] for item in train})}
    x_train = np.asarray([float(item["feature"]) for item in train], dtype=float)
    y_train = np.asarray([float(item["target"]) for item in train], dtype=float)
    mean = float(x_train.mean())
    std = float(x_train.std(ddof=0))
    if std <= 0:
        return {"status": "DATA_INSUFFICIENT", "reason": "CONSTANT_TRAIN_FEATURE"}
    z_train = (x_train - mean) / std
    alpha = float(protocol["primary_experiment"]["alpha"])
    design = np.column_stack([np.ones(len(z_train)), z_train])
    penalty = np.diag([0.0, alpha])
    coefficients = np.linalg.solve(design.T @ design + penalty, design.T @ y_train)
    training_mean = float(y_train.mean())
    partitions: dict[str, Any] = {}
    for partition in ("TRAIN", "VALIDATION", "TEST"):
        assigned = [item for item in rows if split[str(item["date"])] == partition]
        sample = [item for item in eligible_rows if split[str(item["date"])] == partition]
        if not sample:
            partitions[partition] = {"rows": 0, "purged_rows": len(assigned)}
            continue
        x = np.asarray([float(item["feature"]) for item in sample], dtype=float)
        y = np.asarray([float(item["target"]) for item in sample], dtype=float)
        predictions = coefficients[0] + coefficients[1] * ((x - mean) / std)
        partitions[partition] = {
            "rows": len(sample),
            "unique_dates": len({item["date"] for item in sample}),
            "purged_rows": len(assigned) - len(sample),
            "ridge_mae": float(np.mean(np.abs(y - predictions))),
            "training_mean_baseline_mae": float(np.mean(np.abs(y - training_mean))),
            "mae_improvement": float(np.mean(np.abs(y - training_mean)) - np.mean(np.abs(y - predictions))),
        }
    split_material = {"dates": dates, "fractions": fractions, "assignment": split}
    return {
        "status": "DEV_FIT_COMPLETE",
        "model": "SINGLE_FEATURE_RIDGE_DEV_ONLY",
        "alpha": alpha,
        "feature_mean_train": mean,
        "feature_std_train": std,
        "intercept": float(coefficients[0]),
        "coefficient": float(coefficients[1]),
        "partitions": partitions,
        "split_hash": content_hash(split_material),
        "production_consumption": False,
    }


def strategy_drafts(event_matrix: list[dict[str, Any]], experiment: dict[str, Any]) -> list[dict[str, Any]]:
    shared = {
        "version": "0.1.0",
        "status": "PROPOSAL_ONLY_PENDING_OWNER_DISCUSSION",
        "writes_profile_policy": False,
        "signal_generation_enabled": False,
        "trade_simulation_enabled": False,
        "automatic_order_enabled": False,
        "still_null": ["DTE", "Delta", "factor weights", "entry", "exit", "position sizing"],
    }
    event_ready = sum(1 for item in event_matrix if item["eligible_for_event_claims"])
    return [
        {**shared, "card_id": "DRAFT-SHORT-01", "card_type": "STRATEGY_DRAFT", "profile_id": "SHORT_ATM_DAYS_WEEK", "mechanism_question": "Should sector-relative underlying information be studied as a short-horizon ATM expression?", "available_evidence": ["descriptive equity factors", "reference option observations", "deterministic Greek sensitivity"], "limitations": [experiment.get("status"), f"event coverage eligible {event_ready}/{len(event_matrix)}", "no historical option NBBO returns"], "owner_decisions": ["reference DTE convention", "Call and Put direction mapping", "entry invalidation", "exit and loss budget"]},
        {**shared, "card_id": "DRAFT-MEDIUM-01", "card_type": "STRATEGY_DRAFT", "profile_id": "MEDIUM_ATM_WEEKS_MONTHS", "mechanism_question": "Which trend and event information could justify several weeks of ATM time value?", "available_evidence": ["60-session descriptive return", "realized volatility", "theta and extrinsic sensitivity"], "limitations": ["event coverage unknown", "no comparable IV history", "no registered medium target"], "owner_decisions": ["reference maturity", "event handling", "time decay budget", "exit and review cadence"]},
        {**shared, "card_id": "DRAFT-LONG-01", "card_type": "STRATEGY_DRAFT", "profile_id": "LONG_OTM_MONTHS_YEAR", "mechanism_question": "What sourced catalyst magnitude and timing would justify long-dated OTM premium?", "available_evidence": ["contract moneyness", "vega/theta sensitivity", "future observation checkpoints"], "limitations": ["no sourced catalyst dataset", "120/252-session labels pending", "American exercise and dividends require separate policy"], "owner_decisions": ["catalyst evidence standard", "OTM reference convention", "expiry and exercise handling", "maximum premium at risk"]},
    ]


def build_research_artifacts(
    *,
    research_db: Path = DEFAULT_RESEARCH_DB,
    source_db: Path = DEFAULT_SOURCE_DB,
    run_dir: Path,
) -> dict[str, Any]:
    protocol = _load_json(PROTOCOL_PATH)
    definitions = feature_dictionary()
    put_feature_definitions(research_db, definitions)
    required_symbols = sorted(set(RADAR_UNIVERSE) | set(SECTOR_BENCHMARK.values()) | {"SPY"})
    series: dict[str, list[dict[str, Any]]] = {}
    coverage: list[dict[str, Any]] = []
    with _readonly_connection(source_db) as connection:
        for symbol in required_symbols:
            series[symbol], symbol_coverage = _load_daily_series(connection, symbol)
            coverage.append(symbol_coverage)
        event_matrix = _event_coverage(connection)
        corporate_actions = [dict(row) for row in connection.execute("SELECT symbol,effective_time,action_type,status,source FROM corporate_action_events WHERE interval='1d' ORDER BY effective_time").fetchall()]
    manifest = _universe_manifest(coverage)
    put_universe_manifest(research_db, manifest)
    equity_snapshots = []
    for symbol in RADAR_UNIVERSE:
        snapshot = compute_equity_feature_snapshot(
            symbol=symbol,
            bars=series.get(symbol, []),
            market_bars=series.get("SPY", []),
            sector_bars=series.get(SECTOR_BENCHMARK.get(symbol, ""), []),
            sector_benchmark=SECTOR_BENCHMARK.get(symbol),
        )
        put_feature_snapshot(research_db, snapshot)
        equity_snapshots.append(snapshot)
    capability = _load_json(CAPABILITY_PATH)
    option_snapshots = []
    for sample in capability.get("samples", []):
        snapshot = compute_option_feature_snapshot(sample, as_of=capability["generated_at"])
        put_feature_snapshot(research_db, snapshot)
        option_snapshots.append(snapshot)
    cards = hypothesis_cards()
    for card in cards:
        put_hypothesis(research_db, card)
    registration = experiment_registration(protocol)
    preflight = _experiment_preflight([item for item in coverage if item["symbol"] in required_symbols])
    experiment = {
        "run_id": f"es001-{content_hash({'registration': registration, 'preflight': preflight})[:24]}",
        "experiment_id": EXPERIMENT_ID,
        "protocol_version": protocol["version"],
        "registration": registration,
        "status": "DATA_INSUFFICIENT" if not preflight["eligible"] else "READY_FOR_DEV_FIT",
        "conclusion": "DATA_INSUFFICIENT" if not preflight["eligible"] else "NOT_YET_RUN",
        "preflight": preflight,
        "dataset_hash": content_hash({"manifest": manifest["manifest_id"], "coverage": coverage}),
        "split_hash": None,
        "fit_artifact": None,
        "not_option_performance": True,
        "exposure_status": "EXPOSED_RESEARCH",
    }
    put_experiment(research_db, experiment)
    cohort = _build_cohort(capability, protocol)
    put_cohort(research_db, cohort)
    scenarios = []
    for snapshot in option_snapshots:
        scenario = local_greeks_scenario_grid(snapshot, protocol)
        put_scenario(research_db, scenario)
        scenarios.append(scenario)
    synthetic_validation = synthetic_scenario_validation()
    drafts = strategy_drafts(event_matrix, experiment)
    for draft in drafts:
        put_review_card(research_db, draft)
    source_and_units = {
        "capability_evidence_sha256": _sha256(CAPABILITY_PATH),
        "field_contract": capability.get("time_contract"),
        "option_sample_count": len(option_snapshots),
        "source_bbo_time_known_count": sum(1 for item in capability.get("samples", []) if item.get("source_bbo_time")),
        "strict_fill_eligible_count": sum(1 for item in capability.get("samples", []) if item.get("strict_fill_eligible")),
        "unit_mapping_versions": sorted({str(item.get("unit_mapping_version")) for item in capability.get("samples", [])}),
        "latest_trade_time_used_as_bbo_time": False,
        "receipt_time_used_as_bbo_time": False,
        "sequence_used_as_bbo_time": False,
    }
    input_coverage = {
        "generated_at": _now(),
        "universe": manifest,
        "daily_series": coverage,
        "event_coverage": event_matrix,
        "corporate_actions": corporate_actions,
        "limits": [
            "Daily Longbridge source is unadjusted; E-S-001 adjusted-price contract is not satisfied.",
            "Historical fetch times do not reconstruct original point-in-time availability.",
            "No historical option NBBO dataset is inferred from current OPRA capability.",
        ],
    }
    _write_immutable(run_dir / "input_coverage.json", input_coverage)
    _write_immutable(run_dir / "feature_dictionary.json", {"schema_version": "options_research_features_v0.1.0", "definitions": definitions})
    _write_immutable(run_dir / "feature_lineage.json", {"equity": equity_snapshots, "options": option_snapshots})
    _write_immutable(run_dir / "experiment_registration.json", registration)
    _write_immutable(run_dir / "experiment_result.json", experiment)
    _write_immutable(run_dir / "cohort_quality.json", cohort)
    _write_immutable(run_dir / "scenario_result.json", {"synthetic_validation": synthetic_validation, "real_contract_scenarios": scenarios})
    _write_immutable(run_dir / "source_and_unit_evidence.json", source_and_units)
    _write_immutable(run_dir / "strategy_drafts.json", {"drafts": drafts})
    update_task(research_db, "R03", "DELIVERED_WITH_LIMITATIONS", {"manifest_id": manifest["manifest_id"], "coverage_hash": content_hash(input_coverage), "adjusted_history_ready": False})
    update_task(research_db, "R04", "VERIFIED", {"definition_count": len(definitions), "dictionary_hash": content_hash(definitions)})
    update_task(research_db, "R05", "VERIFIED", {"equity_snapshot_count": len(equity_snapshots), "descriptive_only": True})
    update_task(research_db, "R06", "VERIFIED", {"option_snapshot_count": len(option_snapshots), "cohort_id": cohort["cohort_id"], "strict_fill_eligible": False})
    update_task(research_db, "R07", "DELIVERED_WITH_LIMITATIONS", {"event_ready": 0, "event_total": len(event_matrix), "long_horizon_labels_mature": False})
    update_task(research_db, "R08", "VERIFIED", {"hypotheses": [item["hypothesis_id"] for item in cards], "experiment_registration_hash": registration["registration_hash"]})
    update_task(research_db, "R09", "DELIVERED_WITH_LIMITATIONS", {"status": experiment["status"], "blockers": preflight["blockers"], "fit_performed": False})
    update_task(research_db, "R10", "VERIFIED", {"real_contract_scenario_runs": len(scenarios), "synthetic_validation": synthetic_validation["status"], "probabilities_assigned": False})
    update_task(research_db, "R11", "VERIFIED", {"cohort_id": cohort["cohort_id"], "contract_count": len(cohort["contracts"]), "checkpoint_count": len(cohort["checkpoints"]), "positions_created": 0})
    update_task(research_db, "R13", "VERIFIED", {"draft_count": len(drafts), "profiles_mutated": False})
    update_task(research_db, "R14", "VERIFIED", {"diagram_source_count": len(list((REPO_ROOT / 'docs' / 'diagrams' / 'options_research_v0_1').glob('*.mmd'))), "diagrams_are_implementation_evidence": False})
    return {
        "input_coverage": input_coverage,
        "equity_features": equity_snapshots,
        "option_features": option_snapshots,
        "hypotheses": cards,
        "experiment": experiment,
        "cohort": cohort,
        "scenarios": scenarios,
        "synthetic_scenario_validation": synthetic_validation,
        "drafts": drafts,
    }


def generate_report(*, research_db: Path, run_dir: Path) -> dict[str, Any]:
    status = research_status(research_db)
    experiment = list_payloads(research_db, "research_experiment_runs")[-1]
    cohort = list_payloads(research_db, "research_cohorts")[-1]
    hypotheses = list_payloads(research_db, "research_hypotheses")
    scenario_runs = list_payloads(research_db, "research_scenario_runs")
    report = f"""# KQUANT Options Research Workbench V0.1

Generated: {_now()}

## Status

- Engineering: `ENGINEERING_READY_WAIT_MARKET`
- Market validation: `WAIT_MARKET`
- Strategy: `PENDING_STRATEGY_DEFINITION`
- Performance: `NOT_EVALUATED`
- Trading, automatic simulation, account and order access: `DISABLED`

## Research outputs

- Feature definitions: {status['counts']['research_feature_definitions']}
- Feature snapshots: {status['counts']['research_feature_snapshots']}
- Registered hypotheses: {len(hypotheses)}
- Observation cohort: `{cohort['cohort_id']}` with {len(cohort['contracts'])} fixed contracts and {len(cohort['checkpoints'])} non-position checkpoints
- Deterministic scenario runs: {len(scenario_runs)}; no probabilities or expected profit assigned

## E-S-001

- Status: `{experiment['status']}`
- Conclusion: `{experiment['conclusion']}`
- Fit performed: `{experiment['fit_artifact'] is not None}`
- Blockers: {', '.join(experiment['preflight']['blockers']) or 'none'}
- Exposure: `EXPOSED_RESEARCH`
- This is an underlying-data experiment, not option PnL or a Call/Put signal.

## Data limitations

1. The current Longbridge daily series is unadjusted, so the registered adjusted-price experiment contract is not satisfied.
2. Historical acquisition timestamps do not reconstruct the original point-in-time availability of each old bar.
3. Event coverage remains unknown for the 12-symbol radar universe.
4. Current OPRA capability has no verified native BBO event time; strict simulated fills remain blocked.
5. Long-horizon 120/252-session observation outcomes are not mature.

## Boundaries

The three existing profile policy fields remain null. Research windows and scenario shocks live only in the independent research protocol. No result in this workbench enables signal generation, simulated entry, or order submission.
"""
    runbook = f"""# Options Research Workbench V0.1 Runbook

Repository: `{REPO_ROOT}`
Interpreter: `{Path(__import__('sys').executable).resolve()}`
Research database: `{research_db.resolve()}`
Run directory: `{run_dir.resolve()}`

```powershell
.\\.venv\\Scripts\\python.exe scripts\\run_options_research_workbench.py status
.\\.venv\\Scripts\\python.exe scripts\\run_options_research_workbench.py run-all --run-id <new-run-id>
.\\.venv\\Scripts\\python.exe scripts\\run_options_research_workbench.py report --run-id <existing-run-id>
.\\.venv\\Scripts\\python.exe scripts\\run_options_research_workbench.py pause
.\\.venv\\Scripts\\python.exe scripts\\run_options_research_workbench.py resume
```

Foundation services remain independently controlled by `start_kquant_workspace.ps1 -OptionsFoundation` and `stop_kquant_options_foundation.ps1`. The research runner must not start a second Supervisor.
"""
    _write_text_immutable(run_dir / "REPORT.md", report)
    _write_text_immutable(run_dir / "RUNBOOK.md", runbook)
    payload = {"report": str((run_dir / 'REPORT.md').resolve()), "runbook": str((run_dir / 'RUNBOOK.md').resolve()), "status": status}
    return payload


def mark_engineering_delivery(*, research_db: Path, run_dir: Path, verification: dict[str, Any]) -> dict[str, Any]:
    _write_immutable(run_dir / "tests.json", verification)
    passed = bool(verification.get("backend_passed") and verification.get("frontend_passed") and verification.get("build_passed") and verification.get("readonly_passed"))
    state = "VERIFIED" if passed else "FAILED"
    update_task(research_db, "R12", state, {"readonly_ui": passed, "api_contracts": passed, "frontend_tests": verification.get("frontend_passed")})
    update_task(research_db, "R15", state, verification)
    update_task(research_db, "R16", "DELIVERED_WITH_LIMITATIONS" if passed else "FAILED", {"engineering_ready": passed, "market_status": "WAIT_MARKET", "run_dir": str(run_dir.resolve())})
    update_task(research_db, "R17", "WAIT_MARKET", {"engineering_ready": passed, "market_day_completion": False, "cross_day_completion": False})
    return research_status(research_db)


def workbench_payload(research_db: Path = DEFAULT_RESEARCH_DB) -> dict[str, Any]:
    status = research_status(research_db)
    if status["status"] != "AVAILABLE":
        return {**status, "strategy_status": "PENDING_STRATEGY_DEFINITION", "performance_status": "NOT_EVALUATED", "trading_enabled": False}
    snapshots = list_payloads(research_db, "research_feature_snapshots")
    equity = [item for item in snapshots if item.get("entity_type") == "UNDERLYING"]
    options = [item for item in snapshots if item.get("entity_type") == "OPTION_CONTRACT"]
    experiments = list_payloads(research_db, "research_experiment_runs")
    cohorts = list_payloads(research_db, "research_cohorts")
    scenarios = list_payloads(research_db, "research_scenario_runs")
    return {
        "status": "ENGINEERING_READY_WAIT_MARKET",
        "workbench_version": WORKBENCH_VERSION,
        "strategy_status": "PENDING_STRATEGY_DEFINITION",
        "performance_status": "NOT_EVALUATED",
        "trading_enabled": False,
        "simulation_enabled": False,
        "order_submission_enabled": False,
        "feature_definitions": list_payloads(research_db, "research_feature_definitions"),
        "equity_feature_snapshots": equity,
        "option_feature_snapshots": options,
        "hypotheses": list_payloads(research_db, "research_hypotheses"),
        "experiment": experiments[-1] if experiments else None,
        "cohort": cohorts[-1] if cohorts else None,
        "scenarios": scenarios,
        "drafts": list_payloads(research_db, "research_review_cards"),
        "tasks": status["tasks"],
        "counts": status["counts"],
    }


__all__ = [
    "DEFAULT_OUTPUT_ROOT", "DEFAULT_RESEARCH_DB", "DEFAULT_SOURCE_DB", "EXPERIMENT_ID", "build_research_artifacts",
    "freeze_workbench", "generate_report", "mark_engineering_delivery", "run_single_feature_ridge", "workbench_payload",
]
