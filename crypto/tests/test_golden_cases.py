from __future__ import annotations

from kquant_crypto.golden_cases import GOLDEN_CASE_VERSION, crypto_golden_cases, golden_case_catalog, stock_golden_cases
from kquant_crypto.roll_engine import RollInput, evaluate_roll


def test_golden_catalog_has_separate_frozen_contracts():
    catalog = golden_case_catalog()
    assert catalog["version"] == GOLDEN_CASE_VERSION
    assert len(stock_golden_cases()) == 20
    assert len(crypto_golden_cases()) == 20
    assert {item["strategy_version"] for item in catalog["stock"]} == {"swing_long_v1.1.0"}


def test_crypto_golden_cases_are_deterministic_and_match_expected_actions():
    for case in crypto_golden_cases():
        payload = {key: value for key, value in case.items() if key not in {"case_id", "expected_action"}}
        first = evaluate_roll(RollInput.from_mapping(payload))
        second = evaluate_roll(RollInput.from_mapping(payload))
        assert first.roll_id == second.roll_id
        assert first.action == case["expected_action"]
