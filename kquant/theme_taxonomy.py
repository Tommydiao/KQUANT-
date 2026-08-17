from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .stock_store import connect
from .universe_registry import current_universe_members, ensure_current_universe_registry


DEFAULT_TAXONOMY_PATH = Path("config/theme_taxonomy_v1.yml")
TAXONOMY_CONTRACT_VERSION = "theme_taxonomy_contract_v1"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def load_taxonomy(path: Path = DEFAULT_TAXONOMY_PATH) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - project dependency guard
        raise RuntimeError("PyYAML is required to load the versioned theme taxonomy.") from exc
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict) or not payload.get("taxonomy_version"):
        raise ValueError("Theme taxonomy must define taxonomy_version.")
    definitions = payload.get("definitions")
    if not isinstance(definitions, list) or not definitions:
        raise ValueError("Theme taxonomy must define at least one definition.")
    required = {"id", "dimension_type", "slug", "display_name", "rule", "status"}
    seen: set[str] = set()
    for definition in definitions:
        if not isinstance(definition, dict) or not required <= set(definition):
            raise ValueError("Each theme definition requires id, dimension_type, slug, display_name, rule, and status.")
        definition_id = str(definition["id"])
        if definition_id in seen:
            raise ValueError(f"Duplicate theme definition: {definition_id}")
        seen.add(definition_id)
    return payload


def taxonomy_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _tokens(member: dict[str, Any]) -> dict[str, set[str]]:
    return {
        "tags": {str(item).strip().lower() for item in member.get("tags", [])},
        "layers": {str(member.get("layer") or "").strip().lower()},
        "sectors": {str(member.get("sector") or "").strip().lower()},
    }


def _rule_match(member: dict[str, Any], rule: dict[str, Any]) -> tuple[bool, float, dict[str, Any]]:
    if rule.get("match") == "never":
        return False, 0.0, {"rule": "never"}
    tokens = _tokens(member)
    evidence: dict[str, Any] = {}
    matched = False
    exact = False
    for key, token_key in (("tags_any", "tags"), ("layers_any", "layers"), ("sectors_any", "sectors")):
        candidates = {str(item).strip().lower() for item in rule.get(key, [])}
        hits = sorted(tokens[token_key] & candidates)
        if hits:
            matched = True
            exact = exact or key == "tags_any"
            evidence[key] = hits
    if not matched:
        return False, 0.0, evidence
    confidence = 0.95 if exact else 0.80
    return True, confidence, evidence


def _definition_hash(definition: dict[str, Any], taxonomy_version: str) -> str:
    payload = {"taxonomy_version": taxonomy_version, **definition}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_theme_taxonomy(
    *,
    db_path: Path,
    config_path: Path = DEFAULT_TAXONOMY_PATH,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Materialize a point-in-time taxonomy mapping from registry metadata."""

    taxonomy = load_taxonomy(config_path)
    version = str(taxonomy["taxonomy_version"])
    taxonomy_digest = taxonomy_hash(taxonomy)
    registry = ensure_current_universe_registry(db_path)
    members = current_universe_members(db_path)
    effective_date = as_of_date or datetime.now(UTC).date().isoformat()
    content_input = {"taxonomy_hash": taxonomy_digest, "registry": registry["content_hash"], "as_of_date": effective_date, "members": members}
    content_hash = hashlib.sha256(json.dumps(content_input, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    run_id = f"ttr_{content_hash[:20]}"
    created_at = _now()
    definitions = list(taxonomy["definitions"])
    by_id = {str(item["id"]): item for item in definitions}
    fallback_id = "theme.unmapped"
    if fallback_id not in by_id:
        raise ValueError("Taxonomy must include theme.unmapped fallback definition.")
    membership_rows: list[tuple[Any, ...]] = []
    audit_rows: list[tuple[Any, ...]] = []
    mapped_symbols: set[str] = set()
    dimension_counts: dict[str, int] = {}
    for member in members:
        symbol = str(member["symbol"])
        symbol_matches: list[tuple[dict[str, Any], float, dict[str, Any]]] = []
        for definition in definitions:
            matched, confidence, evidence = _rule_match(member, dict(definition.get("rule") or {}))
            if matched:
                symbol_matches.append((definition, confidence, evidence))
        theme_matches = [item for item in symbol_matches if item[0]["dimension_type"] == "theme"]
        if not theme_matches:
            symbol_matches.append((by_id[fallback_id], 0.0, {"reason": "no_theme_rule_match", "legacy_tags": member.get("tags", [])}))
            audit_rows.append((run_id, symbol, fallback_id, "unmapped", "No active theme rule matched the point-in-time metadata.", created_at))
        else:
            mapped_symbols.add(symbol)
        for definition, confidence, evidence in symbol_matches:
            definition_id = str(definition["id"])
            dimension_type = str(definition["dimension_type"])
            review_status = "needs_review" if definition_id == fallback_id else "auto_mapped"
            weight = 1.0 if dimension_type == "theme" else 0.5
            membership_rows.append((run_id, version, registry["registry_id"], definition_id, symbol, dimension_type, weight, confidence, json.dumps({"rule_evidence": evidence, "legacy_tags": member.get("tags", []), "layer": member.get("layer"), "sector": member.get("sector")}, ensure_ascii=True, sort_keys=True), review_status, effective_date, None, created_at))
            dimension_counts[dimension_type] = dimension_counts.get(dimension_type, 0) + 1
    summary = {
        "contract_version": TAXONOMY_CONTRACT_VERSION,
        "taxonomy_version": version,
        "taxonomy_hash": taxonomy_digest,
        "registry_id": registry["registry_id"],
        "registry_symbol_count": len(members),
        "mapped_theme_symbols": len(mapped_symbols),
        "unmapped_theme_symbols": len(members) - len(mapped_symbols),
        "mapped_coverage_pct": round(len(mapped_symbols) / len(members) * 100, 2) if members else 0.0,
        "target_pct": 95.0,
        "target_met": len(mapped_symbols) / len(members) >= 0.95 if members else False,
        "dimension_membership_counts": dimension_counts,
        "unmapped_is_explicit": True,
        "point_in_time": True,
    }
    with connect(db_path) as conn:
        existing_run = conn.execute("SELECT 1 FROM theme_taxonomy_runs WHERE run_id = ?", (run_id,)).fetchone()
        conn.execute(
            """
            INSERT OR IGNORE INTO theme_taxonomy_runs(
              run_id, taxonomy_version, taxonomy_hash, registry_id, as_of_date,
              content_hash, status, summary_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'materialized', ?, ?)
            """,
            (run_id, version, taxonomy_digest, registry["registry_id"], effective_date, content_hash, json.dumps(summary, ensure_ascii=True, sort_keys=True), created_at),
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO theme_definitions(
              taxonomy_version, definition_id, dimension_type, parent_id, slug, display_name,
              aliases_json, rule_json, status, effective_from, effective_to, content_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (version, str(item["id"]), str(item["dimension_type"]), item.get("parent_id"), str(item["slug"]), str(item["display_name"]), json.dumps(item.get("aliases") or [], ensure_ascii=True, sort_keys=True), json.dumps(item.get("rule") or {}, ensure_ascii=True, sort_keys=True), str(item["status"]), str(taxonomy.get("effective_from") or effective_date), taxonomy.get("effective_to"), _definition_hash(item, version), created_at)
                for item in definitions
            ],
        )
        conn.executemany(
            """
            INSERT OR IGNORE INTO theme_memberships(
              run_id, taxonomy_version, registry_id, definition_id, symbol, dimension_type,
              weight, confidence, evidence_json, review_status, valid_from, valid_to, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            membership_rows,
        )
        if existing_run is None:
            conn.executemany(
                """
                INSERT INTO theme_membership_audit(run_id, symbol, definition_id, action, reason, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                audit_rows,
            )
        conn.commit()
    return {"run_id": run_id, "content_hash": content_hash, "summary": summary}


def latest_theme_taxonomy(db_path: Path) -> dict[str, Any]:
    with connect(db_path) as conn:
        run = conn.execute("SELECT * FROM theme_taxonomy_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        if run is None:
            return {"status": "not_materialized", "taxonomy_version": None, "definitions": [], "summary": {}}
        definitions = [dict(row) for row in conn.execute("SELECT * FROM theme_definitions WHERE taxonomy_version=? ORDER BY dimension_type, definition_id", (run["taxonomy_version"],)).fetchall()]
        for definition in definitions:
            definition["aliases"] = json.loads(definition.pop("aliases_json"))
            definition["rule"] = json.loads(definition.pop("rule_json"))
            definition["membership_count"] = int(conn.execute("SELECT COUNT(*) FROM theme_memberships WHERE run_id=? AND definition_id=?", (run["run_id"], definition["definition_id"])).fetchone()[0])
    return {"status": run["status"], "run_id": run["run_id"], "taxonomy_version": run["taxonomy_version"], "taxonomy_hash": run["taxonomy_hash"], "registry_id": run["registry_id"], "as_of_date": run["as_of_date"], "summary": json.loads(run["summary_json"]), "definitions": definitions}


def theme_detail(db_path: Path, definition_id: str) -> dict[str, Any]:
    payload = latest_theme_taxonomy(db_path)
    definition = next((item for item in payload.get("definitions", []) if item["definition_id"] == definition_id), None)
    if definition is None:
        raise ValueError(f"Unknown theme definition: {definition_id}")
    with connect(db_path) as conn:
        members = [dict(row) for row in conn.execute("SELECT symbol, weight, confidence, review_status, valid_from, valid_to, evidence_json FROM theme_memberships WHERE run_id=? AND definition_id=? ORDER BY symbol", (payload["run_id"], definition_id)).fetchall()]
    for member in members:
        member["evidence"] = json.loads(member.pop("evidence_json"))
    return {"definition": definition, "run_id": payload["run_id"], "members": members, "point_in_time": True}
