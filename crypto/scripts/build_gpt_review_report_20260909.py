"""Package the dated review from frozen evidence; never writes research stores."""
from pathlib import Path
import datetime as dt
import hashlib
import json
import re
import subprocess

import duckdb


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/hybrid_delivery/gpt_review_20260909_01"
DOC = ROOT / "docs/HYBRID_GPT_REVIEW_REPORT_20260909.md"
OUT.mkdir(parents=True, exist_ok=True)

EVIDENCE = [
    "outputs/dual_regime_v1/frozen/data_manifest.json",
    "config/hybrid_exit_research_v1.json",
    "outputs/hybrid_delivery/multifactor_portfolio_audit_20260907_01/report.json",
    "outputs/hybrid_delivery/multifactor_portfolio_capsule_20260909_01/report.json",
    "outputs/hybrid_delivery/multifactor_portfolio_clean_verify_20260909_01/verification.json",
    "outputs/hybrid_delivery/multifactor_portable_clean_verify_20260909_02/verification.json",
    "outputs/hybrid_delivery/multifactor_population_fit_20260908_01/artifact.json",
    "outputs/hybrid_delivery/multifactor_population_prediction_20260908_01/report.json",
    "outputs/hybrid_delivery/multifactor_population_sidecar_20260909_01/report.json",
    "outputs/hybrid_delivery/multifactor_block_sensitivity_20260909_01/report.json",
    "outputs/hybrid_delivery/multifactor_portable_replay_20260909_01/authorized_dev_dataset_replay.zip",
    "outputs/hybrid_delivery/multifactor_portfolio_portable_20260909_02/authorized_dev_portfolio_replay.zip",
]
index = []
for name in EVIDENCE:
    path = ROOT / name
    raw = path.read_bytes()
    index.append({"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})

# SQL is preserved as the actual source transformation used by the chart.
query = """SELECT key AS scenario,
    json_extract(value, '$.profit_factor')::DOUBLE AS net_pf,
    json_extract(value, '$.mean_net_r')::DOUBLE AS average_net_r,
    json_extract(value, '$.trades')::INTEGER AS completed_trades,
    json_extract(value, '$.net_pnl')::DOUBLE AS net_pnl
FROM read_json_auto('outputs/hybrid_delivery/multifactor_portfolio_capsule_20260909_01/report.json'),
     json_each(to_json(scenarios))
WHERE key IN ('ORIGINAL_1', 'FIXED_2_5R_1', 'FIXED_3R_1', 'T1_1', 'T2_1')
ORDER BY net_pf DESC"""
import os
os.chdir(ROOT)
connection = duckdb.connect()
cursor = connection.execute(query)
fields = [item[0] for item in cursor.description]
rows = [dict(zip(fields, row)) for row in cursor.fetchall()]
connection.close()
replay = json.loads((ROOT / EVIDENCE[3]).read_text(encoding="utf-8"))
assert len(replay["reference_parity"]) == 10
assert all(all(value.values()) for value in replay["reference_parity"].values())
assert all(row["net_pf"] < 1 and row["average_net_r"] < 0 for row in rows)
now = dt.datetime.now(dt.timezone.utc).isoformat()
head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
text = DOC.read_text(encoding="utf-8")
sections = re.split(r"(?m)(?=^## )", text)
title = text.splitlines()[0][2:]
source = {
    "id": "portfolio_replay",
    "label": "Authorized DEV portfolio replay, BASE costs",
    "path": EVIDENCE[3],
    "query": {
        "sql": query, "engine": "DuckDB", "language": "sql", "executed_at": now,
        "description": "Five BASE-cost research scenarios from the hash-matched portfolio replay, not OOS or live trades.",
        "tables_used": [EVIDENCE[3]],
        "filters": ["Authorized exposed DEV history only", "BASE cost multiplier 1", "No REFERENCE or doubled-cost rows"],
        "metric_definitions": {"net_pf": "Sum positive simulated net cash PnL divided by absolute sum negative simulated net cash PnL, per scenario, after fees and slippage."},
    },
}
blocks = []
def reader_tables(body):
    lines = body.splitlines()
    result = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("|") and i + 1 < len(lines) and re.match(r"^\|[-:| ]+\|$", lines[i+1]):
            headers = [cell.strip() for cell in lines[i].strip("|").split("|")]
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                cells = [cell.strip() for cell in lines[i].strip("|").split("|")]
                result.append("- " + "; ".join(f"{header}: {cell}" for header, cell in zip(headers, cells)))
                i += 1
            result.append("")
        else:
            result.append(lines[i])
            i += 1
    return "\n".join(result)

for i, section in enumerate(sections):
    # Reader-only wrap opportunities; Markdown and evidence hashes remain exact.
    body = re.sub(r"[A-Za-z0-9_./-]{32,}", lambda match: "\u200b".join(match.group()[j:j+16] for j in range(0, len(match.group()), 16)), reader_tables(section.strip()))
    blocks.append({"id": f"section_{i}", "type": "markdown", "body": body})
    if section.startswith("## 5."):
        blocks.append({"id": "pf_plot", "type": "chart", "chartId": "pf"})
sources = [source] + [{"id": f"evidence_{i}", "label": Path(item["path"]).parent.name, "path": item["path"]} for i, item in enumerate(index) if not item["path"].endswith(".zip")]
artifact = {
    "surface": "report",
    "manifest": {"version": 1, "title": title, "generatedAt": now, "blocks": blocks, "sources": sources,
                 "charts": [{"id": "pf", "type": "bar", "title": "BASE 成本下各候选的净 Profit Factor",
                             "dataset": "strategy_metrics", "encodings": {"x": {"field": "scenario", "type": "nominal"}, "y": {"field": "net_pf", "type": "quantitative"}}, "source": source}]},
    "snapshot": {"version": 1, "status": "ready", "generatedAt": now, "datasets": {"strategy_metrics": rows}},
    "sources": sources,
}
for filename, payload in [("artifact.json", artifact), ("evidence_index.json", {"generated_at": now, "head": head, "scope": "Report-only snapshot; no trading activation", "sources": index, "chart_rows": rows, "replay_hash_parity": replay["reference_parity"]})]:
    (OUT / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / DOC.name).write_text(text, encoding="utf-8")
print(json.dumps({"output": str(OUT), "verified_sources": len(index), "all_ten_replay_scenarios_match": True, "chart_rows": rows}, ensure_ascii=False))
