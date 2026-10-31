"""Only the one frozen helper can override the exact inherited test payload."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}


@pytest.fixture
def subject(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("null_time_test_bootstrap", HERE / "bootstrap.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "HERE", tmp_path)
    parent = dict(candidate_id="TEST_ONLY_PARENT",
        projection_followup="SELECT_BEFORE_COMPACT_AND_READ_ONLY_AI_BOUNDARY_V1",
        changes=[dict(target="kquant/options_minute_decisions.py", payload="OLD", sha256="OLD"),
                 dict(target="kquant/options_research_ai.py", payload="RETAINED", sha256="RETAINED")])
    proof = save(tmp_path / "release/parent/projection.json", parent)
    child = dict(candidate_id="TEST_ONLY_CHILD", base_candidate=parent["candidate_id"],
        recovery_input_boundary="REJECT_PUSH_BEFORE_PULL_TIME_PARSE_V1", inherited_projection=proof,
        changes=[dict(target="kquant/options_minute_decisions.py", payload="NEW", sha256="NEW")])
    path = tmp_path / "release/child/projection.json"
    save(path, child)
    monkeypatch.setenv("KQUANT_TEST_FROZEN_PROJECTION", str(path))
    return module, path, parent, child


def test_exact_inheritance_keeps_new_identity_and_one_override(subject):
    module, _, _, _ = subject
    projection = module.selected_projection()
    assert projection["candidate_id"] == "TEST_ONLY_CHILD"
    assert projection["projection_followup"] == "SELECT_BEFORE_COMPACT_AND_READ_ONLY_AI_BOUNDARY_V1"
    rows = {r["target"]: r for r in projection["changes"]}
    assert rows["kquant/options_minute_decisions.py"]["payload"] == "NEW"
    assert rows["kquant/options_research_ai.py"]["payload"] == "RETAINED"
    assert len(rows) == 2


def test_three_declared_repairs_keep_parent_and_distinct_source_targets(subject):
    module, path, _, child = subject
    child['current_card_materialization_boundary'] = 'VISIBLE_RESEARCH_SUBSET_SNAPSHOT_V1'
    child['live_fact_commit_boundary'] = 'PREPARE_THEN_ACCEPTED_CAS_COMMIT_V1'
    for target in ('kquant/options_opening_trend_store.py', 'kquant/options_one_minute_runtime.py'):
        child['changes'].append(dict(target=target, payload='TEST_ONLY_NEW', sha256='TEST_ONLY'))
    save(path, child)
    result = module.selected_projection()
    assert result['candidate_id'] == 'TEST_ONLY_CHILD'
    assert len(result['changes']) == 4


def test_actual_topology_copy_only_relocates_root_and_uses_live_preparation():
    import ast
    root = HERE.parents[5] / 'source/development/workspace'
    original = ast.parse((root/'scripts/check_r58_p10_topology.py').read_text(encoding='utf-8'))
    copied = ast.parse((HERE/'live_fact_topology.py').read_text(encoding='utf-8'))
    root_value = next(node.value for node in original.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == 'ROOT' for target in node.targets))
    old_samples = next(node.values[index] for node in ast.walk(original) if isinstance(node, ast.Dict)
        for index, key in enumerate(node.keys) if isinstance(key, ast.Constant) and key.value == 'source_fact_samples')
    changed = {'root': 0, 'live_prepare': 0, 'evidence_label': 0, 'preparation_label': 0}
    for node in ast.walk(copied):
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'ROOT' for target in node.targets):
            node.value = root_value
            changed['root'] += 1
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == '_price_fact_quotes':
            supplied = [value for value in node.keywords if value.arg == 'persist']
            assert len(supplied) == 1 and supplied[0].value.value is False
            node.keywords.remove(supplied[0])
            changed['live_prepare'] += 1
        if isinstance(node, ast.Dict):
            for index in reversed(range(len(node.keys))):
                if isinstance(node.keys[index], ast.Constant) and node.keys[index].value == 'source_fact_persistence':
                    assert node.values[index].value == 'PREPARED_INPUT_THEN_ACCEPTED_CAS_RESULT_COMMIT'
                    del node.keys[index]
                    del node.values[index]
                    changed['evidence_label'] += 1
                elif isinstance(node.keys[index], ast.Constant) and node.keys[index].value == 'source_fact_samples':
                    assert node.values[index].value == 'generator_advances_read_only_binding_preparation_not_per_asset_cost'
                    node.values[index] = old_samples
                    changed['preparation_label'] += 1
    assert changed == {'root': 1, 'live_prepare': 1, 'evidence_label': 1, 'preparation_label': 1}
    assert ast.dump(original, include_attributes=False) == ast.dump(copied, include_attributes=False)


@pytest.mark.parametrize("bad", ["hash", "parent_identity", "other_target", "two_targets", "outside_parent"])
def test_wrong_parent_or_expanded_delta_fails_closed(subject, bad, tmp_path):
    module, path, parent, child = subject
    if bad == "hash":
        child["inherited_projection"]["sha256"] = "0" * 64
    elif bad == "parent_identity":
        child["base_candidate"] = "TEST_ONLY_WRONG"
    elif bad == "other_target":
        child["changes"][0]["target"] = "kquant/options_opening_momentum.py"
    elif bad == "two_targets":
        child["changes"].append(dict(child["changes"][0]))
    else:
        child["inherited_projection"] = save(tmp_path / "not-release/parent.json", parent)
    save(path, child)
    with pytest.raises(ValueError):
        module.selected_projection()
