import json

import pytest

from kquant_crypto.math_action_contract import load_math_action_contract


def test_contract_is_fail_closed():
    contract = load_math_action_contract()
    assert contract["scope"] == "DEV_ONLY"
    assert contract["execution_enabled"] is False
    assert contract["admission_enabled"] is False
    assert contract["claims"]["live_trading"] is False
    assert contract["bayesian"]["action_gate"] == "posterior_q05_conditional_mean_gt_zero"


def test_contract_rejects_execution_enablement(tmp_path):
    source = load_math_action_contract()
    source.pop("config_path")
    source.pop("config_sha256")
    source.pop("contract_hash")
    source["execution_enabled"] = True
    path = tmp_path / "unsafe.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="execution"):
        load_math_action_contract(path)
