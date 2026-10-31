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
