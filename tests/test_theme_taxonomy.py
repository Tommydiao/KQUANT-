from __future__ import annotations

from pathlib import Path

from kquant.stock_store import connect
from kquant.theme_taxonomy import build_theme_taxonomy, latest_theme_taxonomy, taxonomy_audit, theme_detail


def _seed(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executemany(
            "INSERT INTO stock_universe(symbol, name, sector, layer, tags_json, rank, active, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, '2026-01-01T00:00:00+00:00')",
            [
                ("NVDA", "NVIDIA", "Technology", "Chips", '["ai", "ai_semis", "liquid"]', 1),
                ("RKLB", "Rocket Lab", "Industrials", "Space", '["space", "high_beta"]', 2),
                ("MYST", "Mystery", "Unknown", "Unknown", '[]', 3),
            ],
        )
        conn.commit()


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "taxonomy.yml"
    path.write_text(
        "taxonomy_version: theme_taxonomy_test_v1\n"
        "effective_from: '2026-01-01'\n"
        "definitions:\n"
        "  - id: theme.unmapped\n"
        "    dimension_type: theme\n"
        "    slug: unmapped\n"
        "    display_name: Unmapped\n"
        "    aliases: []\n"
        "    status: fallback\n"
        "    rule: {match: never}\n"
        "  - id: theme.ai\n"
        "    dimension_type: theme\n"
        "    slug: ai\n"
        "    display_name: AI\n"
        "    aliases: [ai]\n"
        "    status: active\n"
        "    rule: {tags_any: [ai]}\n"
        "  - id: theme.space\n"
        "    dimension_type: theme\n"
        "    slug: space\n"
        "    display_name: Space\n"
        "    aliases: [space]\n"
        "    status: active\n"
        "    rule: {tags_any: [space]}\n"
        "  - id: style.high_beta\n"
        "    dimension_type: risk_style\n"
        "    slug: high-beta\n"
        "    display_name: High Beta\n"
        "    aliases: [high_beta]\n"
        "    status: active\n"
        "    rule: {tags_any: [high_beta]}\n",
        encoding="utf-8",
    )
    return path


def test_taxonomy_materialization_is_versioned_and_explicitly_marks_unmapped(tmp_path: Path) -> None:
    db_path = tmp_path / "taxonomy.sqlite3"
    _seed(db_path)
    config = _config(tmp_path)
    first = build_theme_taxonomy(db_path=db_path, config_path=config, as_of_date="2026-08-17")
    second = build_theme_taxonomy(db_path=db_path, config_path=config, as_of_date="2026-08-17")
    assert first["run_id"] == second["run_id"]
    assert first["summary"]["registry_symbol_count"] == 3
    assert first["summary"]["mapped_theme_symbols"] == 2
    assert first["summary"]["unmapped_theme_symbols"] == 1
    latest = latest_theme_taxonomy(db_path)
    assert latest["taxonomy_version"] == "theme_taxonomy_test_v1"
    assert any(item["definition_id"] == "theme.unmapped" for item in latest["definitions"])
    detail = theme_detail(db_path, "theme.ai")
    assert [item["symbol"] for item in detail["members"]] == ["NVDA"]

    with connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM theme_taxonomy_runs").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM theme_membership_audit").fetchone()[0] == 1
    audit = taxonomy_audit(db_path)
    assert audit["status"] == "review"
    assert audit["registry_alignment"]["aligned"] is True
    assert audit["checks"]["unmapped_is_explicit"] is True


def test_taxonomy_latest_is_marked_stale_when_the_canonical_registry_changes(tmp_path: Path) -> None:
    db_path = tmp_path / "stale-taxonomy.sqlite3"
    _seed(db_path)
    config = _config(tmp_path)
    first = build_theme_taxonomy(db_path=db_path, config_path=config, as_of_date="2026-08-17")
    with connect(db_path) as conn:
        conn.execute("UPDATE stock_universe SET name='Changed after taxonomy' WHERE symbol='NVDA'")
        conn.commit()

    latest = latest_theme_taxonomy(db_path)

    assert latest["run_id"] == first["run_id"]
    assert latest["status"] == "stale_registry"
    assert latest["registry_alignment"]["aligned"] is False
    assert taxonomy_audit(db_path)["status"] == "review"
