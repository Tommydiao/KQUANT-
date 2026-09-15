"""CLI for the isolated flow-persistence and residual-trend research study."""

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
from kquant_crypto.trend_evidence_bayes import fit_student_t_fold, predict_student_t_fold
from kquant_crypto.trend_evidence_research import (
    DEFAULT_CONFIG,
    ROOT,
    build_candidate_panel,
    evaluate_ridge_candidates,
    load_enriched_dataset,
    load_trend_contract,
    read_rows,
    run_ridge_walk_forward,
    write_rows,
)


ALLOWED_OUTPUT_ROOT = (ROOT / "outputs" / "trend_evidence_research").resolve()


def _output(value: str) -> Path:
    path = Path(value)
    path = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    if not path.is_relative_to(ALLOWED_OUTPUT_ROOT):
        raise ValueError(f"Output must stay below {ALLOWED_OUTPUT_ROOT}")
    return path


def _json(path: Path, value) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")


def _jsonl_gzip(path: Path, rows: list[dict]) -> None:
    if path.exists():
        raise FileExistsError(path)
    payload = "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in rows)
    path.write_bytes(gzip.compress(payload.encode("utf-8"), mtime=0))


def _load_preregistration(output: Path) -> tuple[dict, dict]:
    preregistration = json.loads((output / "preregistration.json").read_text(encoding="utf-8"))
    contract = load_trend_contract(Path(preregistration["config_path"]))
    if preregistration["contract_hash"] != contract["contract_hash"]:
        raise ValueError("Frozen trend contract no longer matches")
    return preregistration, contract


def freeze(args) -> None:
    output = _output(args.output)
    if output.exists():
        raise FileExistsError(output)
    contract = load_trend_contract(Path(args.config))
    capsule = Path(contract["dataset"]["spot_capsule"])
    capsule = capsule.resolve() if capsule.is_absolute() else (ROOT / capsule).resolve()
    capsule_contract = json.loads((capsule / "capsule.json").read_text(encoding="utf-8"))
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    output.mkdir(parents=True)
    shutil.copy2(Path(args.config), output / "contract_snapshot.json")
    preregistration = {
        "registered_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scope": "DEV_ONLY_EXPOSED_RESEARCH",
        "execution_enabled": False,
        "admission_enabled": False,
        "git_head": head,
        "working_tree_note": "Existing unrelated tracked and untracked work preserved; this run is immutable",
        "python": sys.version,
        "executable": sys.executable,
        "command": sys.argv,
        "config_path": str((output / "contract_snapshot.json").resolve()),
        "source_config_path": contract["config_path"],
        "source_config_sha256": contract["config_sha256"],
        "contract_hash": contract["contract_hash"],
        "spot_capsule": str(capsule),
        "spot_capsule_hash": capsule_contract["capsule_hash"],
        "spot_dataset_hash": capsule_contract["dataset_hash"],
        "candidate_ids": [item["id"] for item in contract["candidates"]],
        "restricted_tail_read": False,
        "claims": contract["claims"],
    }
    preregistration["preregistration_hash"] = canonical_hash(preregistration)
    _json(output / "preregistration.json", preregistration)
    print(json.dumps({"status": "FROZEN", "output": str(output), "contract_hash": contract["contract_hash"]}))


def build(args) -> None:
    output = _output(args.output)
    preregistration, contract = _load_preregistration(output)
    dataset = load_enriched_dataset(contract)
    if dataset.base.content_hash != preregistration["spot_dataset_hash"]:
        raise ValueError("Frozen OHLCV dataset identity changed")
    base_rows, base_audit = build_candidate_panel(dataset, contract, cost_multiplier=1.0)
    stress_rows, stress_audit = build_candidate_panel(
        dataset, contract, cost_multiplier=float(contract["costs"]["stress_multiplier"])
    )
    base_hash = write_rows(output / "candidate_panel_base.jsonl.gz", base_rows)
    stress_hash = write_rows(output / "candidate_panel_double_cost.jsonl.gz", stress_rows)
    manifest = {
        "status": "DEV_ONLY_EXPOSED_RESEARCH",
        "contract_hash": contract["contract_hash"],
        "enriched_dataset_hash": dataset.content_hash,
        "base_panel_hash": base_hash,
        "base_panel_file_sha256": file_hash(output / "candidate_panel_base.jsonl.gz"),
        "double_cost_panel_hash": stress_hash,
        "double_cost_panel_file_sha256": file_hash(output / "candidate_panel_double_cost.jsonl.gz"),
        "base_audit": base_audit,
        "double_cost_audit": stress_audit,
        "claims": contract["claims"],
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    _json(output / "dataset_manifest.json", manifest)
    print(json.dumps({"rows": len(base_rows), "enriched_dataset_hash": dataset.content_hash, "status": "BUILT"}))


def _write_candidate_exports(output: Path, candidate_id: str, result: dict, *, prefix: str) -> dict:
    trades_path = output / f"{prefix}_{candidate_id.lower()}_trades.csv"
    equity_path = output / f"{prefix}_{candidate_id.lower()}_equity_curve.csv"
    if trades_path.exists() or equity_path.exists():
        raise FileExistsError(candidate_id)
    trades = result.pop("trades")
    equity = result.pop("equity_curve")
    trade_fields = sorted({key for row in trades for key in row})
    with trades_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=trade_fields)
        writer.writeheader()
        writer.writerows(trades)
    with equity_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["time", "equity"])
        writer.writeheader()
        writer.writerows(equity)
    result["trade_file"] = trades_path.name
    result["trade_file_sha256"] = file_hash(trades_path)
    result["equity_file"] = equity_path.name
    result["equity_file_sha256"] = file_hash(equity_path)
    return result


def ridge(args) -> None:
    output = _output(args.output)
    _, contract = _load_preregistration(output)
    manifest = json.loads((output / "dataset_manifest.json").read_text(encoding="utf-8"))
    base_rows = read_rows(output / "candidate_panel_base.jsonl.gz")
    stress_rows = read_rows(output / "candidate_panel_double_cost.jsonl.gz")
    if canonical_hash(base_rows) != manifest["base_panel_hash"]:
        raise ValueError("Base panel hash mismatch")
    if canonical_hash(stress_rows) != manifest["double_cost_panel_hash"]:
        raise ValueError("Double-cost panel hash mismatch")
    dataset = load_enriched_dataset(contract)
    if dataset.content_hash != manifest["enriched_dataset_hash"]:
        raise ValueError("Enriched dataset identity changed")
    result = run_ridge_walk_forward(base_rows, contract)
    predictions = result.pop("predictions")
    ablation_predictions = result.pop("ablation_predictions")
    _jsonl_gzip(output / "ridge_predictions.jsonl.gz", predictions)
    _jsonl_gzip(output / "ridge_ablation_predictions.jsonl.gz", ablation_predictions)
    result["predictions_file"] = "ridge_predictions.jsonl.gz"
    result["predictions_file_sha256"] = file_hash(output / result["predictions_file"])
    result["ablation_predictions_file"] = "ridge_ablation_predictions.jsonl.gz"
    result["ablation_predictions_file_sha256"] = file_hash(output / result["ablation_predictions_file"])
    _json(output / "ridge_walk_forward.json", result)

    replay_input = {**result, "predictions": predictions}
    evaluation = evaluate_ridge_candidates(base_rows, stress_rows, replay_input, dataset, contract)
    summaries = {}
    for candidate_id, candidate_result in evaluation["candidate_results"].items():
        summaries[candidate_id] = _write_candidate_exports(
            output, candidate_id, candidate_result, prefix="ridge"
        )
    evaluation["candidate_results"] = summaries
    evaluation["result_hash"] = canonical_hash(evaluation)
    _json(output / "ridge_candidate_evaluation.json", evaluation)

    ablation_input = {**result, "predictions": ablation_predictions}
    ablation_evaluation = evaluate_ridge_candidates(base_rows, stress_rows, ablation_input, dataset, contract)
    ablation_summary = {
        candidate_id: {key: value for key, value in item.items() if key not in {"trades", "equity_curve"}}
        for candidate_id, item in ablation_evaluation["candidate_results"].items()
    }
    ablation_payload = {
        "status": "DEV_ONLY_PRICE_OR_FLOW_ABLATION",
        "candidate_results": ablation_summary,
        "claims": ablation_evaluation["claims"],
    }
    ablation_payload["result_hash"] = canonical_hash(ablation_payload)
    _json(output / "ridge_ablation_evaluation.json", ablation_payload)
    print(json.dumps({candidate_id: item["base"] for candidate_id, item in summaries.items()}))


def bayes(args) -> None:
    from kquant_crypto.hybrid_dataset_capsule import load_capsule
    from kquant_crypto.trend_evidence_research import EnrichedDataset

    output = _output(args.output)
    preregistration, contract = _load_preregistration(output)
    manifest = json.loads((output / "dataset_manifest.json").read_text(encoding="utf-8"))
    base_rows = read_rows(output / "candidate_panel_base.jsonl.gz")
    stress_rows = read_rows(output / "candidate_panel_double_cost.jsonl.gz")
    ridge_state = json.loads((output / "ridge_walk_forward.json").read_text(encoding="utf-8"))
    base_dataset = load_capsule(Path(preregistration["spot_capsule"]))
    dataset = EnrichedDataset(
        base=base_dataset,
        microstructure={},
        content_hash=manifest["enriched_dataset_hash"],
        audit={},
    )
    selected_ids = (
        [item["id"] for item in contract["candidates"]]
        if args.candidate == "all"
        else [args.candidate]
    )
    if not set(selected_ids).issubset({item["id"] for item in contract["candidates"]}):
        raise ValueError("Unknown candidate")
    model_root = output / "bayesian_walk_forward"
    model_root.mkdir(exist_ok=True)
    artifacts = []
    predictions = []
    for candidate in contract["candidates"]:
        if candidate["id"] not in selected_ids:
            continue
        for fold in ridge_state["folds"]:
            model_dir = model_root / candidate["id"].lower() / f"fold_{fold['fold']}"
            artifact = fit_student_t_fold(
                base_rows, candidate, fold, contract, model_dir, sampler=args.sampler
            )
            artifacts.append(artifact)
            predictions.extend(predict_student_t_fold(base_rows, model_dir))
    _jsonl_gzip(output / "bayesian_predictions.jsonl.gz", predictions)
    state = {
        "status": "DEV_ONLY_EXPOSED_RESEARCH",
        "contract_hash": contract["contract_hash"],
        "artifacts": artifacts,
        "predictions_file": "bayesian_predictions.jsonl.gz",
        "predictions_file_sha256": file_hash(output / "bayesian_predictions.jsonl.gz"),
        "all_sampler_diagnostics_pass": all(item["diagnostics"]["sampler_pass"] for item in artifacts),
        "claims": {"independent_oos": False, "calibrated_probability": False},
    }
    state["state_hash"] = canonical_hash(state)
    _json(output / "bayesian_walk_forward.json", state)
    evaluation_input = {"folds": ridge_state["folds"], "predictions": predictions}
    evaluation = evaluate_ridge_candidates(base_rows, stress_rows, evaluation_input, dataset, contract)
    summaries = {}
    for candidate_id, candidate_result in evaluation["candidate_results"].items():
        if candidate_id not in selected_ids:
            continue
        summaries[candidate_id] = _write_candidate_exports(
            output, candidate_id, candidate_result, prefix="bayesian"
        )
    evaluation["candidate_results"] = summaries
    evaluation["model_role"] = "hierarchical_student_t_posterior_q05_gate"
    evaluation["all_sampler_diagnostics_pass"] = state["all_sampler_diagnostics_pass"]
    evaluation["result_hash"] = canonical_hash(evaluation)
    _json(output / "bayesian_candidate_evaluation.json", evaluation)
    print(json.dumps({
        "models": len(artifacts),
        "sampler_pass": state["all_sampler_diagnostics_pass"],
        "actions": {item: value["base"]["trades"] for item, value in summaries.items()},
    }))


def report(args) -> None:
    output = _output(args.output)
    preregistration, contract = _load_preregistration(output)
    dataset = json.loads((output / "dataset_manifest.json").read_text(encoding="utf-8"))
    ridge_result = json.loads((output / "ridge_candidate_evaluation.json").read_text(encoding="utf-8"))
    bayesian_path = output / "bayesian_candidate_evaluation.json"
    bayesian_result = json.loads(bayesian_path.read_text(encoding="utf-8")) if bayesian_path.exists() else None
    bayesian_state_path = output / "bayesian_walk_forward.json"
    bayesian_state = json.loads(bayesian_state_path.read_text(encoding="utf-8")) if bayesian_state_path.exists() else None
    targets = contract["targets"]
    candidates = {}
    for candidate_id, result in ridge_result["candidate_results"].items():
        metrics = result["base"]
        stress = result["fixed_sequence_double_cost"]
        descriptive_targets = {
            "net_payoff": metrics["payoff_r"] is not None and metrics["payoff_r"] >= targets["net_payoff_min"],
            "base_profit_factor": metrics["profit_factor_r"] is not None and metrics["profit_factor_r"] >= targets["base_profit_factor_min"],
            "mean_net_r": metrics["mean_net_r"] is not None and metrics["mean_net_r"] > targets["mean_net_r_min"],
            "double_cost_profit_factor": stress["profit_factor_r"] is not None and stress["profit_factor_r"] >= targets["double_cost_profit_factor_min"],
            "maximum_drawdown": metrics["maximum_drawdown_fraction"] is not None and metrics["maximum_drawdown_fraction"] <= targets["maximum_drawdown_fraction_max"],
            "sample_count": metrics["trades"] >= targets["independent_trades_min"],
            "legacy_10r": False,
        }
        candidates[candidate_id] = {
            "metrics": metrics,
            "fixed_sequence_double_cost": stress,
            "descriptive_target_checks": descriptive_targets,
            "all_descriptive_targets_met": all(descriptive_targets.values()),
            "research_decision": "CONTINUE_TO_BAYESIAN_REVIEW" if all(
                value for key, value in descriptive_targets.items() if key not in {"sample_count", "legacy_10r"}
            ) else "REJECT_AFTER_RIDGE_BASELINE",
        }
        if bayesian_result is not None:
            bayesian_metrics = bayesian_result["candidate_results"][candidate_id]["base"]
            bayesian_stress = bayesian_result["candidate_results"][candidate_id]["fixed_sequence_double_cost"]
            diagnostics = [
                artifact["diagnostics"]
                for artifact in bayesian_state["artifacts"]
                if artifact["candidate_id"] == candidate_id
            ]
            all_sampler_pass = len(diagnostics) == int(contract["walk_forward"]["folds"]) and all(
                item["sampler_pass"] for item in diagnostics
            )
            bayesian_checks = {
                "sampler_diagnostics": all_sampler_pass,
                "net_payoff": bayesian_metrics["payoff_r"] is not None and bayesian_metrics["payoff_r"] >= targets["net_payoff_min"],
                "base_profit_factor": bayesian_metrics["profit_factor_r"] is not None and bayesian_metrics["profit_factor_r"] >= targets["base_profit_factor_min"],
                "mean_net_r": bayesian_metrics["mean_net_r"] is not None and bayesian_metrics["mean_net_r"] > targets["mean_net_r_min"],
                "double_cost_profit_factor": bayesian_stress["profit_factor_r"] is not None and bayesian_stress["profit_factor_r"] >= targets["double_cost_profit_factor_min"],
                "maximum_drawdown": bayesian_metrics["maximum_drawdown_fraction"] is not None and bayesian_metrics["maximum_drawdown_fraction"] <= targets["maximum_drawdown_fraction_max"],
                "sample_count": bayesian_metrics["trades"] >= targets["independent_trades_min"],
                "legacy_10r": False,
            }
            candidates[candidate_id]["bayesian"] = {
                "metrics": bayesian_metrics,
                "fixed_sequence_double_cost": bayesian_stress,
                "diagnostics": diagnostics,
                "checks": bayesian_checks,
                "decision": "REJECTED" if not all(bayesian_checks.values()) else "ELIGIBLE_FOR_LOCKED_FORWARD",
            }
    bayesian_candidates = [
        candidate_id
        for candidate_id, item in candidates.items()
        if item.get("bayesian", {}).get("decision") == "ELIGIBLE_FOR_LOCKED_FORWARD"
    ]
    result = {
        "status": "DEV_ONLY_EXPOSED_RESEARCH",
        "preregistration_hash": preregistration["preregistration_hash"],
        "contract_hash": contract["contract_hash"],
        "dataset_manifest_hash": dataset["manifest_hash"],
        "candidates": candidates,
        "bayesian_candidate_evaluation": bayesian_result,
        "candidate_selection": (
            bayesian_candidates[0]
            if len(bayesian_candidates) == 1
            else "NONE_ALL_CANDIDATES_REJECTED"
            if bayesian_result is not None and not bayesian_candidates
            else "NONE_PENDING_REGISTERED_GATES"
        ),
        "model_status": (
            "BAYESIAN_COMPLETE"
            if bayesian_result is not None
            else "RIDGE_BASELINE_COMPLETE_BAYESIAN_PENDING"
        ),
        "performance_status": "PERFORMANCE_UNPROVEN",
        "descriptive_performance_status": (
            "TARGET_NOT_MET" if bayesian_result is not None and not bayesian_candidates else "PENDING"
        ),
        "execution_enabled": False,
        "admission_enabled": False,
        "old_strategy_or_ab_modified": False,
        "limits": [
            "All history is exposed development evidence",
            "Ridge is a falsification baseline, not the preregistered posterior-q05 action model",
            "The unresolved legacy 10R contract prevents a performance PASS",
            "No result can enable EVAL, Testnet, Live, or exchange orders",
        ],
    }
    result["report_hash"] = canonical_hash(result)
    _json(output / args.filename, result)
    print(json.dumps({"report": str(output / args.filename), "performance": result["performance_status"]}))


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    commands = value.add_subparsers(dest="command", required=True)
    for name, function in (
        ("freeze", freeze),
        ("build", build),
        ("ridge", ridge),
        ("bayes", bayes),
        ("report", report),
    ):
        command = commands.add_parser(name)
        command.add_argument("--output", required=True)
        if name == "freeze":
            command.add_argument("--config", default=str(DEFAULT_CONFIG))
        if name == "report":
            command.add_argument("--filename", default="report.json")
        if name == "bayes":
            command.add_argument(
                "--candidate",
                default="all",
                choices=("all", "H1_FLOW_24H", "H1_FLOW_72H", "H2_RESIDUAL_24H", "H2_RESIDUAL_72H"),
            )
            command.add_argument("--sampler", default="numpyro", choices=("numpyro", "pymc"))
        command.set_defaults(function=function)
    return value


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.function(arguments)
