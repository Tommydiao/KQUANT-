"""CLI for the isolated 24-hour mathematical action research study."""

from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kquant_crypto.math_action_baseline import (
    action_diagnostics,
    fit_ridge_baseline,
    predict_ridge,
    replay_action_policy,
)
from kquant_crypto.math_action_bayes import fit_hierarchical_student_t, predict_conditional_mean
from kquant_crypto.math_action_contract import (
    DEFAULT_CONFIG,
    ROOT,
    canonical_hash,
    file_hash,
    load_math_action_contract,
    resolve_contract_path,
)
from kquant_crypto.math_action_dataset import build_spot_long_panel, read_panel, write_panel
from kquant_crypto.math_action_mc import run_regime_block_bootstrap


def _json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")


def _output(value: str) -> Path:
    path = Path(value)
    path = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
    allowed = (ROOT / "outputs" / "math_action_24h").resolve()
    if not path.is_relative_to(allowed):
        raise ValueError(f"Output must stay below {allowed}")
    return path


def _load_preregistration(output: Path) -> tuple[dict, dict]:
    prereg = json.loads((output / "preregistration.json").read_text(encoding="utf-8"))
    contract = load_math_action_contract(Path(prereg["config_path"]))
    if prereg["contract_hash"] != contract["contract_hash"]:
        raise ValueError("Frozen contract no longer matches")
    return prereg, contract


def freeze(args) -> None:
    output = _output(args.output)
    if output.exists():
        raise FileExistsError(output)
    contract = load_math_action_contract(Path(args.config))
    capsule = resolve_contract_path(contract, contract["dataset"]["spot_capsule"])
    capsule_contract = json.loads((capsule / "capsule.json").read_text(encoding="utf-8"))
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    output.mkdir(parents=True)
    shutil.copy2(Path(args.config), output / "contract_snapshot.json")
    prereg = {
        "registered_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scope": contract["scope"],
        "exposure": contract["exposure"],
        "execution_enabled": False,
        "admission_enabled": False,
        "git_head": head,
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
        "perpetual_short_status": "DATA_BLOCKED",
        "perpetual_short_reason": "No registered frozen Futures OHLCV, mark-price and actual funding dataset",
        "claims": contract["claims"],
    }
    prereg["preregistration_hash"] = canonical_hash(prereg)
    _json(output / "preregistration.json", prereg)
    print(json.dumps({"output": str(output), "contract_hash": contract["contract_hash"], "status": "FROZEN"}))


def build_labels(args) -> None:
    from kquant_crypto.hybrid_dataset_capsule import load_capsule

    output = _output(args.output)
    prereg, contract = _load_preregistration(output)
    capsule = Path(prereg["spot_capsule"])
    if json.loads((capsule / "capsule.json").read_text(encoding="utf-8"))["capsule_hash"] != prereg["spot_capsule_hash"]:
        raise ValueError("Frozen capsule identity changed")
    dataset = load_capsule(capsule)
    if dataset.content_hash != prereg["spot_dataset_hash"]:
        raise ValueError("Frozen dataset hash changed")
    rows, audit = build_spot_long_panel(dataset, contract)
    panel_path = output / "spot_long_panel.jsonl.gz"
    panel_hash = write_panel(panel_path, rows)
    audit["panel_file_sha256"] = file_hash(panel_path)
    if panel_hash != audit["panel_hash"]:
        raise ValueError("Panel hash mismatch")
    _json(output / "dataset_audit.json", audit)
    print(json.dumps({"rows": len(rows), "panel_hash": panel_hash, "perpetual_short": "DATA_BLOCKED"}))


def baseline(args) -> None:
    output = _output(args.output)
    _, contract = _load_preregistration(output)
    rows = read_panel(output / "spot_long_panel.jsonl.gz")
    artifact = fit_ridge_baseline(rows, contract)
    path = output / "ridge_artifact.json"
    if path.exists():
        raise FileExistsError(path)
    _json(path, artifact)
    predictions = predict_ridge(rows, artifact)
    report = action_diagnostics(
        rows,
        predictions,
        minimum_predicted_net_r=float(contract["ridge_baseline"]["minimum_predicted_net_r"]),
    )
    _json(output / "ridge_action_diagnostics.json", report)
    print(json.dumps({"artifact_hash": artifact["artifact_hash"], "metrics": report["metrics"]}))


def fit(args) -> None:
    output = _output(args.output)
    _, contract = _load_preregistration(output)
    rows = read_panel(output / "spot_long_panel.jsonl.gz")
    model_dir = output / "bayesian_spot_long"
    artifact = fit_hierarchical_student_t(rows, contract, model_dir, sampler=args.sampler)
    print(json.dumps({"model_dir": str(model_dir), "artifact": artifact}))


def predict(args) -> None:
    output = _output(args.output)
    _load_preregistration(output)
    rows = read_panel(output / "spot_long_panel.jsonl.gz")
    predictions = predict_conditional_mean(
        rows,
        output / "bayesian_spot_long",
        output=output / "bayesian_predictions.jsonl.gz",
    )
    print(json.dumps({"predictions": len(predictions), "passed_action_gate": sum(row["passes_action_gate"] for row in predictions)}))


def replay(args) -> None:
    output = _output(args.output)
    _, contract = _load_preregistration(output)
    rows = read_panel(output / "spot_long_panel.jsonl.gz")
    ridge_artifact = json.loads((output / "ridge_artifact.json").read_text(encoding="utf-8"))
    ridge_predictions = predict_ridge(rows, ridge_artifact)
    ridge_replay = replay_action_policy(
        rows,
        ridge_predictions,
        contract,
        score_field="predicted_net_r",
    )
    ridge_path = output / "ridge_portfolio_replay.json"
    if ridge_path.exists():
        raise FileExistsError(ridge_path)
    _json(ridge_path, ridge_replay)

    bayesian_artifact = json.loads((output / "bayesian_spot_long" / "artifact.json").read_text(encoding="utf-8"))
    with gzip.open(output / "bayesian_predictions.jsonl.gz", "rt", encoding="utf-8") as stream:
        bayesian_predictions = [json.loads(line) for line in stream if line.strip()]
    force_wait = None if bayesian_artifact["diagnostics"]["sampler_pass"] else "sampler_diagnostics_failed"
    bayesian_replay = replay_action_policy(
        rows,
        bayesian_predictions,
        contract,
        score_field="posterior_mean_net_r",
        eligibility_field="passes_action_gate",
        force_wait_reason=force_wait,
    )
    bayesian_path = output / "bayesian_portfolio_replay.json"
    if bayesian_path.exists():
        raise FileExistsError(bayesian_path)
    _json(bayesian_path, bayesian_replay)
    print(json.dumps({
        "ridge": {"trades": len(ridge_replay["trades"]), "net_pnl": ridge_replay["net_pnl"]},
        "bayesian": {"trades": len(bayesian_replay["trades"]), "net_pnl": bayesian_replay["net_pnl"], "forced_wait": force_wait},
    }))


def monte_carlo(args) -> None:
    from kquant_crypto.hybrid_dataset_capsule import load_capsule

    output = _output(args.output)
    prereg, contract = _load_preregistration(output)
    rows = {row["sample_id"]: row for row in read_panel(output / "spot_long_panel.jsonl.gz")}
    with gzip.open(output / "bayesian_predictions.jsonl.gz", "rt", encoding="utf-8") as stream:
        predictions = [json.loads(line) for line in stream if line.strip()]
    candidates = [prediction for prediction in predictions if prediction["passes_action_gate"]]
    dataset = load_capsule(Path(prereg["spot_capsule"]))
    results = [run_regime_block_bootstrap(dataset, rows[prediction["sample_id"]], contract) for prediction in candidates]
    payload = {
        "status": "DEV_ONLY_RISK_EVIDENCE",
        "contract_hash": contract["contract_hash"],
        "candidate_source": "raw_bayesian_q05_pass_before_sampler_diagnostic_block",
        "upstream_sampler_pass": False,
        "upstream_effective_action": "WAIT",
        "runtime_admission": False,
        "results": results,
    }
    payload["result_hash"] = canonical_hash(payload)
    path = output / "monte_carlo_risk_evidence.json"
    if path.exists():
        raise FileExistsError(path)
    _json(path, payload)
    print(json.dumps({
        "candidates": len(candidates),
        "completed": sum(result["status"] == "DEV_RISK_EVIDENCE" for result in results),
        "unavailable": sum(result["status"] != "DEV_RISK_EVIDENCE" for result in results),
        "effective_action": "WAIT",
    }))


def compare(args) -> None:
    output = _output(args.output)
    prereg, contract = _load_preregistration(output)
    old_path = ROOT / "outputs" / "hybrid_delivery" / "multifactor_portfolio_20260907_02" / "report.json"
    old = json.loads(old_path.read_text(encoding="utf-8"))
    if old["dataset_hash"] != prereg["spot_dataset_hash"]:
        raise ValueError("Old and mathematical studies do not share the same dataset hash")
    ridge = json.loads((output / "ridge_portfolio_replay.json").read_text(encoding="utf-8"))
    bayesian = json.loads((output / "bayesian_portfolio_replay.json").read_text(encoding="utf-8"))
    comparison = {
        "status": "DESCRIPTIVE_EXPOSED_DEVELOPMENT_COMPARISON",
        "dataset_hash": prereg["spot_dataset_hash"],
        "contract_hash": contract["contract_hash"],
        "technical_reference": {
            "strategy": "ORIGINAL_1",
            "trades": old["scenarios"]["ORIGINAL_1"]["trades"],
            "mean_net_r": old["scenarios"]["ORIGINAL_1"]["mean_net_r"],
            "profit_factor": old["scenarios"]["ORIGINAL_1"]["profit_factor"],
            "net_pnl": old["scenarios"]["ORIGINAL_1"]["net_pnl"],
        },
        "ridge_math_reference": {
            "trades": len(ridge["trades"]),
            "net_pnl": ridge["net_pnl"],
            "metrics": ridge["metrics"],
        },
        "bayesian_math_decision": {
            "trades": len(bayesian["trades"]),
            "net_pnl": bayesian["net_pnl"],
            "effective_action": "WAIT" if not bayesian["trades"] else "RESEARCH_ACTIONS",
        },
        "comparison_limit": "Policies and opportunity populations differ; this is not a paired performance test",
        "admission": "ABSTAIN",
        "performance": "PERFORMANCE_UNPROVEN",
    }
    comparison["comparison_hash"] = canonical_hash(comparison)
    path = output / "comparison.json"
    if path.exists():
        raise FileExistsError(path)
    _json(path, comparison)
    print(json.dumps({"comparison": str(path), "hash": comparison["comparison_hash"]}))


def report(args) -> None:
    output = _output(args.output)
    prereg, contract = _load_preregistration(output)
    audit = json.loads((output / "dataset_audit.json").read_text(encoding="utf-8")) if (output / "dataset_audit.json").exists() else None
    ridge = json.loads((output / "ridge_action_diagnostics.json").read_text(encoding="utf-8")) if (output / "ridge_action_diagnostics.json").exists() else None
    bayesian = json.loads((output / "bayesian_spot_long" / "artifact.json").read_text(encoding="utf-8")) if (output / "bayesian_spot_long" / "artifact.json").exists() else None
    ridge_portfolio = json.loads((output / "ridge_portfolio_replay.json").read_text(encoding="utf-8")) if (output / "ridge_portfolio_replay.json").exists() else None
    bayesian_portfolio = json.loads((output / "bayesian_portfolio_replay.json").read_text(encoding="utf-8")) if (output / "bayesian_portfolio_replay.json").exists() else None
    comparison = json.loads((output / "comparison.json").read_text(encoding="utf-8")) if (output / "comparison.json").exists() else None
    monte_carlo = json.loads((output / "monte_carlo_risk_evidence.json").read_text(encoding="utf-8")) if (output / "monte_carlo_risk_evidence.json").exists() else None
    bayesian_action = None
    prediction_path = output / "bayesian_predictions.jsonl.gz"
    if bayesian and prediction_path.exists():
        with gzip.open(prediction_path, "rt", encoding="utf-8") as stream:
            predictions = [json.loads(line) for line in stream if line.strip()]
        rows = {row["sample_id"]: row for row in read_panel(output / "spot_long_panel.jsonl.gz")}
        passing = [prediction for prediction in predictions if prediction["passes_action_gate"]]
        counts = Counter(
            f"{prediction['partition']}:{prediction['symbol']}" for prediction in passing
        )
        selected = []
        for prediction in passing:
            row = rows[prediction["sample_id"]]
            if row["partition"] != "PURGED" and row["label_status"] == "MATURE":
                selected.append(row["net_r"])
        bayesian_action = {
            "raw_rows_passing_q05_gate": len(passing),
            "raw_gate_counts": dict(counts),
            "raw_gate_mean_realized_net_r": sum(selected) / len(selected) if selected else None,
            "sampler_pass": bayesian["diagnostics"]["sampler_pass"],
            "effective_action": "WAIT" if not bayesian["diagnostics"]["sampler_pass"] else "Q05_GATED_RESEARCH_ACTIONS",
            "effective_authorized_action_count": len(passing) if bayesian["diagnostics"]["sampler_pass"] else 0,
            "reason": "sampler_diagnostics_failed" if not bayesian["diagnostics"]["sampler_pass"] else None,
            "independent_oos": False,
            "calibrated_probability": False,
        }
    result = {
        "status": "DEV_ONLY_RESEARCH",
        "contract_version": contract["version"],
        "contract_hash": contract["contract_hash"],
        "preregistration_hash": prereg["preregistration_hash"],
        "data": audit,
        "ridge_baseline": ridge,
        "ridge_portfolio_replay": ridge_portfolio,
        "bayesian_artifact": bayesian,
        "bayesian_action_audit": bayesian_action,
        "bayesian_portfolio_replay": bayesian_portfolio,
        "monte_carlo_risk_evidence": monte_carlo,
        "old_strategy_comparison": comparison,
        "perpetual_short": "DATA_BLOCKED",
        "admission": "ABSTAIN",
        "execution_enabled": False,
        "performance_conclusion": "PERFORMANCE_UNPROVEN",
    }
    result["report_hash"] = canonical_hash(result)
    if Path(args.filename).name != args.filename or not args.filename.endswith(".json"):
        raise ValueError("Report filename must be a local JSON filename")
    path = output / args.filename
    if path.exists():
        raise FileExistsError(path)
    _json(path, result)
    print(json.dumps({"report": str(path), "report_hash": result["report_hash"]}))


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    commands = value.add_subparsers(dest="command", required=True)
    for name, function in (
        ("freeze", freeze),
        ("build-labels", build_labels),
        ("baseline", baseline),
        ("fit", fit),
        ("predict", predict),
        ("monte-carlo", monte_carlo),
        ("replay", replay),
        ("compare", compare),
        ("report", report),
    ):
        command = commands.add_parser(name)
        command.add_argument("--output", required=True)
        if name == "freeze":
            command.add_argument("--config", default=str(DEFAULT_CONFIG))
        if name == "fit":
            command.add_argument("--sampler", choices=("pymc", "numpyro"), default="numpyro")
        if name == "report":
            command.add_argument("--filename", default="report.json")
        command.set_defaults(function=function)
    return value


if __name__ == "__main__":
    args = parser().parse_args()
    args.function(args)
