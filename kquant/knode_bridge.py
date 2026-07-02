"""Bridge KQUANT stock signals to the local KNODE research layer.

The first integration phase is deliberately light: KQUANT remains the trading
signal shell while KNODE remains the research/evidence/report store.  The
bridge tries KNODE's local HTTP API first, then falls back to reading KNODE's
portable local JSON files when the KNODE app is offline or protected by auth.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_KNODE_RELATIVE = Path("Desktop") / "2026-04-26" / "prd-ai-mvp-overview-1-1"


def normalize_symbol(value: Any) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum() or ch in ".-")[:16]


def iso_now() -> str:
    return datetime.now(UTC).isoformat()


def knode_api_base_url() -> str:
    return os.environ.get("KNODE_API_BASE_URL", "http://127.0.0.1:8787").rstrip("/")


def knode_project_root() -> Path:
    configured = os.environ.get("KNODE_PROJECT_ROOT", "").strip()
    if configured:
        return Path(configured)
    candidates = []
    home = Path.home()
    candidates.append(home / DEFAULT_KNODE_RELATIVE)
    candidates.append(Path("C:/Users/Administrator/Desktop/2026-04-26/prd-ai-mvp-overview-1-1"))
    for candidate in candidates:
        if (candidate / "data").exists():
            return candidate
    return candidates[0]


def bridge_status(api_status: str = "not_checked", api_error: str = "") -> dict[str, Any]:
    root = knode_project_root()
    return {
        "api_base_url": knode_api_base_url(),
        "api_status": api_status,
        "api_error": api_error[:240],
        "project_root": str(root),
        "local_data_status": "available" if (root / "data").exists() else "missing",
        "integration_mode": "api_then_local_json_fallback",
        "database_migrated": False,
        "read_only_research": True,
    }


def _read_json_array(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_jsonl(path: Path, limit: int = 2000) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
                if len(rows) >= limit:
                    break
    except OSError:
        return []
    return rows


def _try_knode_get(path: str, params: dict[str, Any] | None = None) -> tuple[str, dict[str, Any] | None, str]:
    query = urlencode({key: value for key, value in (params or {}).items() if value is not None})
    url = f"{knode_api_base_url()}{path}"
    if query:
        url = f"{url}?{query}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "kquant-knode-bridge/0.1"})
    try:
        with urlopen(request, timeout=float(os.environ.get("KNODE_BRIDGE_TIMEOUT", "3.0"))) as response:  # noqa: S310 - local user-configured endpoint
            payload = json.loads(response.read().decode("utf-8"))
        return "available", payload if isinstance(payload, dict) else {}, ""
    except HTTPError as exc:
        if exc.code in {401, 403}:
            return "auth_required", None, f"HTTP {exc.code}"
        return "api_error", None, f"HTTP {exc.code}"
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return "offline", None, type(exc).__name__


def _haystack(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "symbol",
        "ticker",
        "name",
        "title",
        "company_name",
        "project_name",
        "selected_project_name",
        "recommended_project_name",
        "suggestedProjectName",
        "description",
        "summary",
        "text",
        "evidence_fact",
        "evidence_visible_info",
        "filename",
        "content",
    ):
        value = item.get(key)
        if value:
            parts.append(str(value))
    tags = item.get("tags")
    if isinstance(tags, list):
        parts.extend(str(tag) for tag in tags)
    return " ".join(parts).upper()


def _matches_symbol(item: dict[str, Any], symbol: str) -> bool:
    needle = normalize_symbol(symbol)
    if not needle:
        return False
    has_explicit_symbol = False
    for key in ("symbol", "ticker"):
        normalized = normalize_symbol(item.get(key))
        if normalized:
            has_explicit_symbol = True
        if normalized == needle:
            return True
    if has_explicit_symbol:
        return False
    return needle in _haystack(item)


def _clean_text(value: Any, limit: int = 600) -> str:
    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
    return text[:limit]


def _file_url(path_value: Any) -> str:
    normalized = str(path_value or "").replace("\\", "/")
    return f"file:///{normalized}" if normalized else ""


def _normalize_dossier(item: dict[str, Any], symbol: str) -> dict[str, Any]:
    company_name = item.get("company_name") or item.get("name") or item.get("project_name") or symbol
    bull_case = item.get("bull_case")
    bear_risks = item.get("bear_risks") or item.get("bear_case") or item.get("risk_signal") or item.get("financial_warning")
    return {
        "id": item.get("id") or "",
        "symbol": symbol,
        "name": company_name,
        "company_name": company_name,
        "description": _clean_text(item.get("description") or item.get("summary") or "", 700),
        "ticker": item.get("ticker") or symbol,
        "company_type": item.get("company_type") or "",
        "financial_source": item.get("financial_source") or "",
        "financial_updated_at": item.get("financial_updated_at") or "",
        "updated_at": item.get("updated_at") or item.get("updatedAt") or item.get("created_at") or "",
        "thesis": _clean_text(item.get("thesis") or item.get("description") or item.get("summary") or "", 800),
        "bull_case": bull_case if isinstance(bull_case, list) else [_clean_text(bull_case or "", 500)] if bull_case else [],
        "bear_risks": bear_risks if isinstance(bear_risks, list) else [_clean_text(bear_risks or "", 500)] if bear_risks else [],
        "tags": item.get("tags") if isinstance(item.get("tags"), list) else [],
        "source": "knode_project_spaces",
    }


def _normalize_evidence(item: dict[str, Any], symbol: str) -> dict[str, Any]:
    return {
        "id": item.get("highlight_id") or item.get("id") or "",
        "symbol": symbol,
        "title": _clean_text(item.get("ai_title") or item.get("title") or item.get("evidence_fact") or "Untitled evidence", 220),
        "type": item.get("type") or item.get("source_channel") or item.get("kind") or "Research Item",
        "summary": _clean_text(item.get("summary") or item.get("aiSummary") or item.get("evidence_visible_info") or item.get("text"), 700),
        "fact": _clean_text(item.get("evidence_fact") or item.get("text") or item.get("title"), 700),
        "interpretation": _clean_text(item.get("evidence_interpretation") or item.get("evidence_hypothesis") or item.get("why_it_matters"), 700),
        "risks": _clean_text(item.get("evidence_risks") or item.get("risk_signal"), 500),
        "impact_direction": item.get("impact_direction") or "",
        "thesis_impact": item.get("thesis_impact") or "",
        "confidence": item.get("evidence_confidence") or item.get("confidence") or item.get("value_score") or 0,
        "url": item.get("url") or "",
        "source_domain": item.get("source_domain") or "",
        "created_at": item.get("created_at") or item.get("createdAt") or item.get("timestamp") or "",
        "tags": item.get("tags") if isinstance(item.get("tags"), list) else [],
        "source": "knode_highlights_jsonl",
    }


def _normalize_report(item: dict[str, Any], symbol: str) -> dict[str, Any]:
    export_id = item.get("id") or ""
    local_path = item.get("local_path") or ""
    return {
        "id": export_id,
        "symbol": symbol,
        "title": _clean_text(item.get("title") or item.get("filename") or "Research report", 220),
        "type": item.get("type") or item.get("content_format") or item.get("mimeType") or "report",
        "filename": item.get("filename") or "",
        "mime_type": item.get("mimeType") or item.get("mime_type") or "",
        "created_at": item.get("createdAt") or item.get("created_at") or item.get("exported_at") or "",
        "summary": _clean_text(item.get("summary") or item.get("content") or "", 800),
        "open_url": _file_url(local_path) if local_path else f"{knode_api_base_url()}/export/open/{export_id}" if export_id else "",
        "download_url": _file_url(local_path) if local_path else f"{knode_api_base_url()}/export/download/{export_id}" if export_id else "",
        "source": "knode_exports_json",
    }


def _local_project_spaces(symbol: str) -> list[dict[str, Any]]:
    data_dir = knode_project_root() / "data"
    rows = _read_json_array(data_dir / "project_spaces.json")
    return [_normalize_dossier(row, symbol) for row in rows if _matches_symbol(row, symbol)]


def _local_evidence(symbol: str, limit: int) -> list[dict[str, Any]]:
    rows = _read_jsonl(knode_project_root() / "data" / "highlights.jsonl")
    matches = [_normalize_evidence(row, symbol) for row in rows if _matches_symbol(row, symbol)]
    matches.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return matches[:limit]


def _local_reports(symbol: str, limit: int) -> list[dict[str, Any]]:
    exports_dir = knode_project_root() / "data" / "exports"
    if not exports_dir.exists():
        return []
    matches: list[dict[str, Any]] = []
    for path in exports_dir.glob("*.json"):
        item = _read_json_object(path)
        if item and _matches_symbol(item, symbol):
            item.setdefault("id", path.stem)
            item.setdefault("filename", path.name)
            item.setdefault("local_path", str(path))
            matches.append(_normalize_report(item, symbol))
    matches.sort(key=lambda item: str(item.get("created_at") or item.get("id") or ""), reverse=True)
    return matches[:limit]


def api_research_company_dossier(symbol: str) -> dict[str, Any]:
    normalized = normalize_symbol(symbol) or "NVDA"
    api_status, api_payload, api_error = _try_knode_get("/research/company-dossiers", {"symbol": normalized})
    api_dossiers: list[dict[str, Any]] = []
    if api_payload:
        raw = api_payload.get("company_dossiers") or api_payload.get("project_spaces") or []
        if isinstance(raw, list):
            api_dossiers = [_normalize_dossier(row, normalized) for row in raw if isinstance(row, dict) and _matches_symbol(row, normalized)]
    local_dossiers = _local_project_spaces(normalized)
    dossier = (api_dossiers or local_dossiers or [None])[0]
    evidence_count = len(_local_evidence(normalized, 200))
    report_count = len(_local_reports(normalized, 200))
    return {
        "product": "KQUANT x KNODE Research Bridge",
        "symbol": normalized,
        "status": "available" if dossier else "no_dossier",
        "bridge_status": bridge_status(api_status, api_error),
        "dossier": dossier,
        "summary": {
            "dossier_source": "knode_api" if api_dossiers else "local_json" if local_dossiers else "none",
            "evidence_count": evidence_count,
            "report_count": report_count,
            "knode_authenticated": api_status == "available",
        },
        "read_only_research": True,
    }


def api_research_evidence(symbol: str, limit: int = 20) -> dict[str, Any]:
    normalized = normalize_symbol(symbol) or "NVDA"
    api_status, api_payload, api_error = _try_knode_get("/research/items", {"symbol": normalized, "limit": limit})
    api_items: list[dict[str, Any]] = []
    if api_payload:
        raw = api_payload.get("research_items") or api_payload.get("items") or api_payload.get("highlights") or []
        if isinstance(raw, list):
            api_items = [_normalize_evidence(row, normalized) for row in raw if isinstance(row, dict) and _matches_symbol(row, normalized)]
    local_items = _local_evidence(normalized, max(1, min(limit, 100)))
    items = (api_items or local_items)[: max(1, min(limit, 100))]
    return {
        "product": "KQUANT x KNODE Evidence Bridge",
        "symbol": normalized,
        "status": "available" if items else "empty",
        "bridge_status": bridge_status(api_status, api_error),
        "items": items,
        "count": len(items),
        "source": "knode_api" if api_items else "local_json",
        "read_only_research": True,
    }


def api_research_reports(symbol: str, limit: int = 10) -> dict[str, Any]:
    normalized = normalize_symbol(symbol) or "NVDA"
    api_status, api_payload, api_error = _try_knode_get("/research/reports", {"symbol": normalized, "limit": limit})
    api_reports: list[dict[str, Any]] = []
    if api_payload:
        raw = api_payload.get("reports") or api_payload.get("research_items") or []
        if isinstance(raw, list):
            api_reports = [_normalize_report(row, normalized) for row in raw if isinstance(row, dict) and _matches_symbol(row, normalized)]
    local_reports = _local_reports(normalized, max(1, min(limit, 100)))
    reports = (api_reports or local_reports)[: max(1, min(limit, 100))]
    return {
        "product": "KQUANT x KNODE Reports Bridge",
        "symbol": normalized,
        "status": "available" if reports else "empty",
        "bridge_status": bridge_status(api_status, api_error),
        "reports": reports,
        "count": len(reports),
        "source": "knode_api" if api_reports else "local_json",
        "read_only_research": True,
    }


def api_research_evidence_save(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_symbol(payload.get("symbol") or "NVDA") or "NVDA"
    data_dir = knode_project_root() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "highlights.jsonl"
    now = iso_now()
    item = {
        "highlight_id": f"kquant-{uuid.uuid4()}",
        "id": f"kquant-{uuid.uuid4()}",
        "kind": "kquant_bridge",
        "source_channel": "kquant_bridge",
        "company_name": payload.get("company_name") or normalized,
        "ticker": normalized,
        "title": _clean_text(payload.get("title") or f"KQUANT evidence for {normalized}", 220),
        "summary": _clean_text(payload.get("summary") or payload.get("note") or "", 900),
        "text": _clean_text(payload.get("text") or payload.get("summary") or payload.get("note") or "", 1200),
        "note": _clean_text(payload.get("note") or "", 800),
        "url": _clean_text(payload.get("url") or "", 500),
        "source_domain": _clean_text(payload.get("source_domain") or "", 160),
        "type": payload.get("type") or "KQUANT Evidence",
        "tags": payload.get("tags") if isinstance(payload.get("tags"), list) else ["KQUANT Bridge", normalized],
        "evidence_fact": _clean_text(payload.get("evidence_fact") or payload.get("summary") or payload.get("note") or "", 900),
        "evidence_interpretation": _clean_text(payload.get("evidence_interpretation") or "Saved from KQUANT Stock Detail research bridge.", 700),
        "evidence_risks": _clean_text(payload.get("evidence_risks") or "Manually saved research evidence; verify before using in AI trading command.", 700),
        "evidence_confidence": int(payload.get("evidence_confidence") or 55),
        "created_at": now,
        "createdAt": now,
        "updated_at": now,
        "updatedAt": now,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    time.sleep(0.01)
    return {
        "product": "KQUANT x KNODE Evidence Bridge",
        "status": "saved",
        "symbol": normalized,
        "item": _normalize_evidence(item, normalized),
        "evidence": api_research_evidence(normalized, limit=20),
        "dossier": api_research_company_dossier(normalized),
        "read_only_research": True,
        "broker_order_wiring_enabled": False,
        "order_submission_enabled": False,
    }
