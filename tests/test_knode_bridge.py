from __future__ import annotations

import json
from pathlib import Path

from kquant.knode_bridge import (
    api_research_company_dossier,
    api_research_evidence,
    api_research_evidence_save,
    api_research_reports,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_research_dossier_uses_local_knode_data(monkeypatch, tmp_path):
    monkeypatch.setenv("KNODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KNODE_API_BASE_URL", "http://127.0.0.1:9")
    _write_json(
        tmp_path / "data" / "project_spaces.json",
        [
            {
                "symbol": "NVDA",
                "company_name": "NVIDIA",
                "thesis": "AI factory leader",
                "bull_case": ["accelerator demand"],
                "bear_risks": ["supply chain"],
                "tags": ["ai_compute"],
            }
        ],
    )
    _write_jsonl(
        tmp_path / "data" / "highlights.jsonl",
        [
            {"symbol": "NVDA", "title": "Data center evidence", "summary": "Demand remains high"},
            {"symbol": "TSLA", "title": "Other evidence", "summary": "Not NVDA"},
        ],
    )
    _write_json(
        tmp_path / "data" / "exports" / "nvda-report.json",
        {"symbol": "NVDA", "title": "NVDA Report", "summary": "Report summary"},
    )

    payload = api_research_company_dossier("NVDA")

    assert payload["status"] == "available"
    assert payload["dossier"]["company_name"] == "NVIDIA"
    assert payload["summary"]["evidence_count"] == 1
    assert payload["summary"]["report_count"] == 1
    assert payload["read_only_research"] is True


def test_research_evidence_filters_by_symbol(monkeypatch, tmp_path):
    monkeypatch.setenv("KNODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KNODE_API_BASE_URL", "http://127.0.0.1:9")
    _write_jsonl(
        tmp_path / "data" / "highlights.jsonl",
        [
            {"symbol": "RKLB", "title": "Launch cadence", "summary": "More launches"},
            {"symbol": "NVDA", "title": "GPU cycle", "summary": "Different symbol"},
        ],
    )

    payload = api_research_evidence("RKLB")

    assert payload["status"] == "available"
    assert payload["count"] == 1
    assert payload["items"][0]["title"] == "Launch cadence"


def test_research_reports_return_open_links(monkeypatch, tmp_path):
    monkeypatch.setenv("KNODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KNODE_API_BASE_URL", "http://127.0.0.1:9")
    _write_json(tmp_path / "data" / "exports" / "mstr-cycle.json", {"symbol": "MSTR", "title": "MSTR Cycle"})

    payload = api_research_reports("MSTR")

    assert payload["status"] == "available"
    assert payload["count"] == 1
    assert "mstr-cycle.json" in payload["reports"][0]["open_url"]


def test_research_evidence_save_appends_local_knode_jsonl(monkeypatch, tmp_path):
    monkeypatch.setenv("KNODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("KNODE_API_BASE_URL", "http://127.0.0.1:9")

    payload = api_research_evidence_save(
        {
            "symbol": "RKLB",
            "company_name": "Rocket Lab",
            "title": "New contract",
            "summary": "Backlog improves",
            "type": "news",
            "tags": ["space", "backlog"],
        }
    )

    assert payload["status"] == "saved"
    assert payload["evidence"]["count"] == 1
    assert (tmp_path / "data" / "highlights.jsonl").exists()
    saved = api_research_evidence("RKLB")
    assert saved["items"][0]["title"] == "New contract"
