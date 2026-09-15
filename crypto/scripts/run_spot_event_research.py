"""CLI for the isolated spot-event research study."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kquant_crypto.math_action_contract import canonical_hash, file_hash
from kquant_crypto.spot_event_research import (
    DEFAULT_CONFIG,
    ROOT,
    build_event_observations,
    evaluate_qualified_replays,
    load_event_contract,
    load_event_dataset,
    summarize_event_study,
)


ALLOWED_OUTPUT_ROOT = (ROOT / "outputs" / "spot_event_research").resolve()


def _output(value: str) -> Path:
    path = Path(value)
    path = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if not path.is_relative_to(ALLOWED_OUTPUT_ROOT):
        raise ValueError(f"Output must stay below {ALLOWED_OUTPUT_ROOT}")
    return path


def _write_json(path: Path, value: object) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")


def _write_rows(path: Path, rows: list[dict]) -> str:
    if path.exists():
        raise FileExistsError(path)
    payload = "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in rows)
    path.write_bytes(gzip.compress(payload.encode("utf-8"), mtime=0))
    return canonical_hash(rows)


def _read_rows(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    if len({row["sample_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate event sample identity")
    return rows


def _write_csv(path: Path, rows: list[dict]) -> None:
    if path.exists():
        raise FileExistsError(path)
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as stream:
        if not fields:
            stream.write("")
            return
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _load_frozen(output: Path) -> tuple[dict, dict]:
    frozen = json.loads((output / "preregistration.json").read_text(encoding="utf-8"))
    contract = load_event_contract(Path(frozen["config_path"]))
    if frozen["contract_hash"] != contract["contract_hash"]:
        raise ValueError("Frozen event contract changed")
    return frozen, contract


def freeze(output: Path, config_path: Path) -> None:
    if output.exists():
        raise FileExistsError(output)
    contract = load_event_contract(config_path)
    capsule = Path(contract["dataset"]["spot_capsule"])
    capsule = capsule.resolve() if capsule.is_absolute() else (ROOT / capsule).resolve()
    capsule_contract = json.loads((capsule / "capsule.json").read_text(encoding="utf-8"))
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    output.mkdir(parents=True)
    shutil.copy2(config_path, output / "contract_snapshot.json")
    frozen_contract = load_event_contract(output / "contract_snapshot.json")
    preregistration = {
        "registered_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scope": "DEV_ONLY_EXPOSED_RESEARCH",
        "execution_enabled": False,
        "admission_enabled": False,
        "git_head": head,
        "working_tree_note": "Existing tracked and untracked work preserved; this run is immutable",
        "python": sys.version,
        "executable": sys.executable,
        "config_path": str((output / "contract_snapshot.json").resolve()),
        "source_config_path": contract["config_path"],
        "source_config_sha256": contract["config_sha256"],
        "contract_hash": frozen_contract["contract_hash"],
        "spot_capsule": str(capsule),
        "spot_capsule_hash": capsule_contract["capsule_hash"],
        "spot_dataset_hash": capsule_contract["dataset_hash"],
        "candidate_ids": [item["id"] for item in frozen_contract["candidates"]],
        "restricted_tail_read": False,
        "claims": frozen_contract["claims"],
    }
    preregistration["preregistration_hash"] = canonical_hash(preregistration)
    _write_json(output / "preregistration.json", preregistration)


def build(output: Path) -> None:
    frozen, contract = _load_frozen(output)
    dataset = load_event_dataset(contract)
    if dataset.base.content_hash != frozen["spot_dataset_hash"]:
        raise ValueError("Frozen OHLCV dataset identity changed")
    rows, audit = build_event_observations(dataset, contract)
    panel_hash = _write_rows(output / "event_observations.jsonl.gz", rows)
    if panel_hash != audit["panel_hash"]:
        raise ValueError("Event panel hash mismatch")
    manifest = {
        "status": "DEV_ONLY_EXPOSED_EVENT_DATASET",
        "contract_hash": contract["contract_hash"],
        "event_dataset_hash": dataset.content_hash,
        "event_panel_hash": panel_hash,
        "event_panel_file_sha256": file_hash(output / "event_observations.jsonl.gz"),
        "audit": audit,
        "claims": contract["claims"],
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    _write_json(output / "dataset_manifest.json", manifest)


def analyze(output: Path) -> None:
    _, contract = _load_frozen(output)
    manifest = json.loads((output / "dataset_manifest.json").read_text(encoding="utf-8"))
    rows = _read_rows(output / "event_observations.jsonl.gz")
    if canonical_hash(rows) != manifest["event_panel_hash"]:
        raise ValueError("Stored event observations changed")
    study = summarize_event_study(rows, manifest["audit"], contract)
    _write_json(output / "event_study.json", study)
    exports = []
    for row in rows:
        for horizon in (1, 6, 24):
            outcome = row["fixed_horizon_base"][str(horizon)]
            exports.append(
                {
                    "sample_id": row["sample_id"],
                    "candidate_id": row["candidate_id"],
                    "sample_type": row["sample_type"],
                    "fold": row["fold"],
                    "symbol": row["symbol"],
                    "event_start": row["event_start"],
                    "event_end": row["event_end"],
                    "signal_time": row["signal_time"],
                    "horizon_hours": horizon,
                    "label_status": outcome["label_status"],
                    "net_return": outcome.get("net_return"),
                    "gross_return": outcome.get("gross_return"),
                    "maximum_favorable_excursion": outcome.get("maximum_favorable_excursion"),
                    "maximum_adverse_excursion": outcome.get("maximum_adverse_excursion"),
                    "threshold_hash": row["threshold_hash"],
                    "feature_snapshot_hash": row["feature_snapshot_hash"],
                }
            )
    _write_csv(output / "event_fixed_horizon_outcomes.csv", exports)


def fit(output: Path) -> None:
    study = json.loads((output / "event_study.json").read_text(encoding="utf-8"))
    qualified = study["qualified_candidates"]
    if qualified:
        status = "MODEL_PENDING_SEPARATE_FROZEN_STUDENT_T_ARTIFACT"
        reason = "Preliminary event gate passed; fitting requires a new immutable model artifact per qualified event"
    else:
        status = "SKIPPED_NO_PRELIMINARY_EVENT_GATE"
        reason = "No event definition passed the preregistered descriptive and control-increment checks"
    payload = {
        "status": status,
        "qualified_candidates": qualified,
        "reason": reason,
        "model_loaded_by_runtime": False,
        "candidate_selection_enabled": False,
        "claims": {
            "calibrated_probability": False,
            "performance_gate_passed": False,
            "runtime_admission": False,
        },
    }
    payload["artifact_gate_hash"] = canonical_hash(payload)
    _write_json(output / "model_gate.json", payload)


def replay(output: Path) -> None:
    _, contract = _load_frozen(output)
    manifest = json.loads((output / "dataset_manifest.json").read_text(encoding="utf-8"))
    study = json.loads((output / "event_study.json").read_text(encoding="utf-8"))
    rows = _read_rows(output / "event_observations.jsonl.gz")
    dataset = load_event_dataset(contract)
    if dataset.content_hash != manifest["event_dataset_hash"]:
        raise ValueError("Event source identity changed before replay")
    result = evaluate_qualified_replays(rows, dataset, manifest["audit"], study, contract)
    summaries = {}
    for candidate_id, value in result["candidate_results"].items():
        trades = value.pop("trades")
        curve = value.pop("equity_curve")
        slug = candidate_id.lower()
        _write_csv(output / f"replay_{slug}_trades.csv", trades)
        _write_csv(output / f"replay_{slug}_equity_curve.csv", curve)
        value["trades_file"] = f"replay_{slug}_trades.csv"
        value["trades_file_sha256"] = file_hash(output / value["trades_file"])
        value["equity_file"] = f"replay_{slug}_equity_curve.csv"
        value["equity_file_sha256"] = file_hash(output / value["equity_file"])
        summaries[candidate_id] = value
    result["candidate_results"] = summaries
    result["result_hash"] = canonical_hash(result)
    _write_json(output / "portfolio_replay.json", result)


def report(output: Path) -> None:
    frozen, contract = _load_frozen(output)
    manifest = json.loads((output / "dataset_manifest.json").read_text(encoding="utf-8"))
    study = json.loads((output / "event_study.json").read_text(encoding="utf-8"))
    model = json.loads((output / "model_gate.json").read_text(encoding="utf-8"))
    replay_state = json.loads((output / "portfolio_replay.json").read_text(encoding="utf-8"))
    qualified = study["qualified_candidates"]
    result = {
        "status": "DEV_ONLY_EXPOSED_RESEARCH_COMPLETE",
        "preregistration_hash": frozen["preregistration_hash"],
        "contract_hash": contract["contract_hash"],
        "dataset_manifest_hash": manifest["manifest_hash"],
        "event_study_hash": study["result_hash"],
        "model_gate_hash": model["artifact_gate_hash"],
        "portfolio_replay_hash": replay_state["result_hash"],
        "qualified_candidates": qualified,
        "event_definition_result": "AT_LEAST_ONE_PRELIMINARY_PASS" if qualified else "ALL_EVENT_DEFINITIONS_REJECTED",
        "model_status": model["status"],
        "engineering_status": "BUILD_PASS",
        "data_status": "ELIGIBLE_FOR_EXPOSED_DEV_EVENT_STUDY",
        "performance_status": "PERFORMANCE_UNPROVEN",
        "execution_enabled": False,
        "admission_enabled": False,
        "old_strategy_or_ab_modified": False,
        "limits": [
            "All history is exposed development evidence",
            "Historical entries are next-5m-open proxies, not exchange fills",
            "The event gate is a research filter, not an execution admission",
            "The unresolved legacy 10R contract prevents a performance PASS",
        ],
        "claims": contract["claims"],
    }
    result["report_hash"] = canonical_hash(result)
    _write_json(output / "report_final.json", result)


def run_all(output: Path, config_path: Path) -> None:
    freeze(output, config_path)
    build(output)
    analyze(output)
    fit(output)
    replay(output)
    report(output)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    commands = value.add_subparsers(dest="command", required=True)
    for name in ("freeze", "build", "analyze", "fit", "replay", "report", "all"):
        command = commands.add_parser(name)
        command.add_argument("--output", required=True)
        if name in {"freeze", "all"}:
            command.add_argument("--config", default=str(DEFAULT_CONFIG))
    return value


def main() -> int:
    args = parser().parse_args()
    output = _output(args.output)
    if args.command == "freeze":
        freeze(output, Path(args.config))
    elif args.command == "build":
        build(output)
    elif args.command == "analyze":
        analyze(output)
    elif args.command == "fit":
        fit(output)
    elif args.command == "replay":
        replay(output)
    elif args.command == "report":
        report(output)
    else:
        run_all(output, Path(args.config))
    print(json.dumps({"command": args.command, "output": str(output), "status": "COMPLETE"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
