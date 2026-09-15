#!/usr/bin/env python
"""Run immutable negative-control and block-bootstrap audits for a frozen research run."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kquant_crypto.math_action_contract import canonical_hash, file_hash  # noqa: E402
from kquant_crypto.trend_evidence_controls import (  # noqa: E402
    block_bootstrap_trade_uncertainty,
    lead_time_vs_positive_price_momentum,
    load_controls_contract,
    run_equal_weight_buy_hold,
    run_matched_random_control,
    run_price_momentum_control,
)
from kquant_crypto.trend_evidence_research import (  # noqa: E402
    load_enriched_dataset,
    read_rows,
)


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl_gzip(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _normalize_trades(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows:
        result.append(
            {
                **row,
                "fold": int(row["fold"]),
                "signal_time": int(row["signal_time"]),
                "net_r": float(row["net_r"]),
                "net_pnl": float(row["net_pnl"]),
            }
        )
    return result


def _write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _summary_metrics(path: Path) -> dict:
    payload = _read_json(path)
    return {
        candidate_id: item["base"]
        for candidate_id, item in payload["candidate_results"].items()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--audit-id", required=True)
    args = parser.parse_args()

    source = ROOT / "outputs" / "trend_evidence_research" / args.source_run_id
    output = ROOT / "outputs" / "trend_evidence_controls" / args.audit_id
    if not source.is_dir():
        raise SystemExit(f"Missing source run: {source}")
    if output.exists():
        raise SystemExit(f"Audit output already exists: {output}")

    research_contract = _read_json(source / "contract_snapshot.json")
    research_contract["contract_hash"] = canonical_hash(research_contract)
    controls_contract = load_controls_contract()
    if controls_contract["source_contract_hash"] != research_contract["contract_hash"]:
        raise SystemExit("Control contract does not match the frozen source research contract")
    output.mkdir(parents=True)
    dataset = load_enriched_dataset(research_contract)
    base_rows = read_rows(source / "candidate_panel_base.jsonl.gz")
    stress_rows = read_rows(source / "candidate_panel_double_cost.jsonl.gz")
    ridge = _read_json(source / "ridge_walk_forward.json")
    ridge_predictions = _read_jsonl_gzip(source / "ridge_predictions.jsonl.gz")
    folds = ridge["folds"]

    price_momentum, _ = run_price_momentum_control(
        base_rows,
        stress_rows,
        folds,
        dataset,
        research_contract,
    )
    random_control = run_matched_random_control(
        base_rows,
        folds,
        dataset,
        research_contract,
        ridge_predictions,
        controls_contract,
    )
    buy_hold = {
        "cash": {"net_return": 0.0, "maximum_drawdown_fraction": 0.0},
        "base": run_equal_weight_buy_hold(dataset, folds, research_contract, cost_multiplier=1.0),
        "double_cost": run_equal_weight_buy_hold(dataset, folds, research_contract, cost_multiplier=2.0),
    }

    ridge_uncertainty = {}
    bayesian_uncertainty = {}
    lead_time = {"ridge": {}, "bayesian": {}}
    for candidate in research_contract["candidates"]:
        slug = candidate["id"].lower()
        ridge_trades = _normalize_trades(_read_csv(source / f"{slug}_trades.csv"))
        bayes_trades = _normalize_trades(_read_csv(source / f"bayesian_{slug}_trades.csv"))
        ridge_uncertainty[candidate["id"]] = block_bootstrap_trade_uncertainty(
            ridge_trades, folds, controls_contract
        )
        bayesian_uncertainty[candidate["id"]] = block_bootstrap_trade_uncertainty(
            bayes_trades, folds, controls_contract
        )
        lead_time["ridge"][candidate["id"]] = lead_time_vs_positive_price_momentum(
            ridge_trades, dataset
        )
        lead_time["bayesian"][candidate["id"]] = lead_time_vs_positive_price_momentum(
            bayes_trades, dataset
        )

    payload = {
        "status": "DEV_ONLY_EXPOSED_RESEARCH_CONTROLS_COMPLETE",
        "source_run_id": args.source_run_id,
        "source_report_sha256": file_hash(source / "report_final.json"),
        "research_contract_hash": research_contract["contract_hash"],
        "controls_contract": controls_contract,
        "dataset_hash": dataset.content_hash,
        "cash_and_buy_hold": buy_hold,
        "price_momentum": price_momentum,
        "matched_random": random_control,
        "flow_ablation": _summary_metrics(source / "ridge_ablation_evaluation.json"),
        "ridge_reference": _summary_metrics(source / "ridge_candidate_evaluation.json"),
        "ridge_block_bootstrap": ridge_uncertainty,
        "bayesian_block_bootstrap": bayesian_uncertainty,
        "lead_time_vs_price_momentum": lead_time,
        "claims": controls_contract["claims"],
        "admission_enabled": False,
        "execution_enabled": False,
    }
    payload["result_hash"] = canonical_hash(payload)
    _write_json(output / "controls_audit.json", payload)
    manifest = {
        "audit_id": args.audit_id,
        "source_run_id": args.source_run_id,
        "controls_audit_sha256": file_hash(output / "controls_audit.json"),
        "result_hash": payload["result_hash"],
        "files": ["controls_audit.json"],
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    _write_json(output / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
