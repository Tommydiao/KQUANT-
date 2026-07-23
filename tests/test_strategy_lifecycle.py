from __future__ import annotations

from pathlib import Path

from kquant.stock_signals import (
    CANONICAL_STRATEGY_PROFILE,
    api_stock_analyze,
    strategy_lifecycle,
    visible_strategy_profile_keys,
)


def test_only_canonical_strategy_is_visible() -> None:
    assert visible_strategy_profile_keys() == [CANONICAL_STRATEGY_PROFILE]
    assert strategy_lifecycle("swing_long_v1")["mode"] == "canonical"
    assert strategy_lifecycle("high_beta_growth_v1")["mode"] == "legacy_comparison_only"


def test_analysis_marks_legacy_profile_as_comparison_only(tmp_path: Path) -> None:
    payload = api_stock_analyze("NVDA", source="fixture", profile="high_beta_growth_v1", db_path=tmp_path / "kquant.sqlite3", include_realtime=False)

    assert payload["strategy_lifecycle"]["canonical"] is False
    assert payload["signal"]["strategy_lifecycle"]["mode"] == "legacy_comparison_only"
