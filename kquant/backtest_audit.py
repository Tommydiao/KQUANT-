from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


AUDIT_SCHEMA_VERSION = "backtest_audit_v1"


def stable_hash(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_backtest_audit(
    *,
    dataset_id: str,
    policy_version: str,
    strategy_versions: dict[str, str],
    strategy_config_hashes: dict[str, str],
    config: dict[str, Any],
    symbols: list[str],
    trades: list[dict[str, Any]],
) -> dict[str, Any]:
    """Describe the inputs required to reproduce a validation result.

    The fingerprint intentionally excludes timestamps, run IDs, and filesystem
    paths so repeating the same replay with the same inputs yields the same
    reproducibility identity.
    """

    snapshot = [
        {
            "symbol": item.get("symbol"),
            "signal_time": item.get("signal_time"),
            "entry_time": item.get("entry_time"),
            "exit_time": item.get("exit_time"),
            "entry_price": item.get("entry_price"),
            "exit_price": item.get("exit_price"),
            "stop_price": item.get("stop_price"),
            "target_price": item.get("target_price"),
            "profile": item.get("profile"),
            "action": item.get("action"),
            "data_source": item.get("data_source"),
        }
        for item in trades
    ]
    input_contract = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "dataset_id": dataset_id,
        "policy_version": policy_version,
        "strategy_versions": strategy_versions,
        "strategy_config_hashes": strategy_config_hashes,
        "config": config,
        "symbols": sorted(symbols),
        "data_snapshot_hash": stable_hash(snapshot),
        "trade_count": len(snapshot),
    }
    return {
        **input_contract,
        "reproducibility_fingerprint": stable_hash(input_contract),
        "runtime_environment": {
            "python": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "generated_at": datetime.now(UTC).isoformat(),
        "read_only_research": True,
        "no_order_submission": True,
    }


def write_backtest_audit(
    audit: dict[str, Any],
    summary: dict[str, Any],
    output_dir: Path,
    *,
    run_id: str,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {"audit": audit, "summary": summary}
    json_path = output_dir / f"strategy-validation-audit-{run_id}.json"
    latest_json_path = output_dir / "strategy-validation-audit-latest.json"
    markdown_path = output_dir / f"strategy-validation-audit-{run_id}.md"
    latest_markdown_path = output_dir / "strategy-validation-audit-latest.md"
    serialized = json.dumps(payload, indent=2, ensure_ascii=True)
    json_path.write_text(serialized, encoding="utf-8")
    latest_json_path.write_text(serialized, encoding="utf-8")
    lines = [
        "# KQUANT Strategy Validation Audit",
        "",
        f"- Run: `{run_id}`",
        f"- Dataset: `{audit['dataset_id']}`",
        f"- Policy: `{audit['policy_version']}`",
        f"- Reproducibility fingerprint: `{audit['reproducibility_fingerprint']}`",
        f"- Data snapshot hash: `{audit['data_snapshot_hash']}`",
        f"- Trade inputs: `{audit['trade_count']}`",
        f"- Generated at: `{audit['generated_at']}`",
        "",
        "## Aggregate Result",
        "",
        f"- Samples: {summary.get('sample_count', 0)}",
        f"- Win rate: {summary.get('win_rate', 0)}%",
        f"- Average R: {summary.get('average_r', 0)}",
        f"- Profit factor: {summary.get('profit_factor', 0)}",
        f"- Max drawdown (R): {summary.get('max_drawdown_r', 0)}",
        "",
        "This is a deterministic research replay audit. It neither reads a broker account nor submits an order.",
        "",
    ]
    markdown = "\n".join(lines)
    markdown_path.write_text(markdown, encoding="utf-8")
    latest_markdown_path.write_text(markdown, encoding="utf-8")
    return {
        "json": str(json_path),
        "markdown": str(markdown_path),
        "latest_json": str(latest_json_path),
        "latest_markdown": str(latest_markdown_path),
    }
