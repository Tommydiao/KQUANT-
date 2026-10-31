"""Freeze only the verified null-time fix above the accepted live candidate."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = ROOT / "source/development/workspace"
sys.path.insert(0, str(BASE))
from kquant.recovery_preflight import candidate_hash


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode()


def save(path, value):
    body = encoded(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != body:
            raise ValueError("FROZEN_CONTENT_CHANGED")
    else:
        with path.open("xb") as stream:
            stream.write(body)
    return dict(path=str(path), sha256=sha256(body).hexdigest())


def main():
    entry_path = BASE / "config/local_workspace_entry.json"
    entry = read(entry_path)
    if entry["candidate_id"] != "local-candidate-198444f784fb3ada":
        raise ValueError("REVIEWED_PARENT_REQUIRED")
    for key in ("runtime_manifest", "recovery_manifest"):
        if digest(entry[key]["path"]) != entry[key]["sha256"]:
            raise ValueError("PARENT_MANIFEST_CHANGED")
    parent_release_path = Path(entry["runtime_manifest"]["path"])
    parent_release = read(parent_release_path)
    recovery = read(entry["recovery_manifest"]["path"])
    for proof in recovery["required_source"] + recovery["frontend"]:
        path = Path(proof["path"])
        if not path.resolve().is_relative_to(ROOT.resolve()) or digest(path) != proof["sha256"]:
            raise ValueError("PARENT_SOURCE_CHANGED")
    target = "kquant/options_minute_decisions.py"
    payload = HERE / "recovery-null-time-followup/patches" / target
    original_hash = "983a730fc5b8f617cfb7a38d591bbc4c639ea50fa7611d25e2afb543d6ba07d1"
    expected_hash = "a206bd80cdc4339053dad96535e3df217be70d42ae26f3da13f0365d4f28923c"
    if digest(BASE / target) != original_hash or digest(payload) != expected_hash:
        raise ValueError("REVIEWED_ONE_FILE_DIFF_CHANGED")
    row = dict(target=target, payload=str(payload), sha256=expected_hash,
               previous_sha256=original_hash)
    projected = deepcopy(parent_release)
    projected["files"][target] = {"sha256": expected_hash}
    for section in ("retained_source_hashes", "frontend_files", "configuration_hashes", "source_fact_hashes"):
        if target in projected.get(section, {}):
            projected[section][target] = expected_hash
    projected.pop("candidate_id", None)
    projected["production_accepted"] = False
    candidate = "local-candidate-" + sha256(encoded(projected)).hexdigest()[:16]
    projected["candidate_id"] = candidate
    output = HERE / "release" / candidate
    release_proof = save(output / "release-manifest.json", projected)
    required = {p["path"]: p for p in recovery["required_source"]
                if Path(p["path"]) != parent_release_path}
    required[str(BASE / target)] = dict(path=str(BASE / target), sha256=expected_hash)
    required[release_proof["path"]] = release_proof
    recovery.update(candidate_id=candidate, required_source=list(required.values()),
        final_runtime_accepted=False, qualified_signal_authorized=False, can_launch=False)
    recovery.pop("acceptance_receipt", None)
    recovery_proof = save(output / "recovery-manifest.json", recovery)
    proposed = dict(entry, candidate_id=candidate, runtime_manifest=release_proof,
        recovery_manifest=recovery_proof, production_accepted=False, shadow_runtime_accepted=False)
    proposed_proof = save(output / "proposed-local-workspace-entry.json", proposed)
    parent_projection = HERE / "release" / entry["candidate_id"] / "deployment-projection.json"
    deployment = HERE / "apply_checked_delta.py"
    bundle = dict(schema="KQUANT_UNACCEPTED_RESEARCH_DELTA_V1", candidate_id=candidate,
        candidate_payload_sha256=candidate_hash(recovery), base_candidate=entry["candidate_id"],
        base_entry_sha256=digest(entry_path), base_release_manifest=entry["runtime_manifest"],
        base_recovery_manifest=entry["recovery_manifest"], release_manifest=release_proof,
        recovery_manifest=recovery_proof, changes=[row], proposed_entry=proposed_proof,
        inherited_projection=dict(path=str(parent_projection), sha256=digest(parent_projection)),
        deployment_tool=dict(path=str(deployment), sha256=digest(deployment)),
        approved=False, applied=False, production_accepted=False, qualified_signal_authorized=False,
        frontend_rebuilt=False, frontend_reuse="EXACT_ACCEPTED_PARENT_STOCK_AND_UNIFIED_BUILDS",
        data_epoch_reinitialized=False, live_writes=0,
        deadline_constraint=read(HERE.parent / "constraint.json"),
        preparation_tool_sha256=digest(Path(__file__)),
        recovery_input_boundary="REJECT_PUSH_BEFORE_PULL_TIME_PARSE_V1",
        harness_readiness="NEW_ONE_FILE_PROJECTION_ADAPTER_REQUIRED_BEFORE_MATCHED_HOUR",
        prior_parent_hour="SAFETY_RELIABILITY_PASS_PERFORMANCE_FAIL_NOT_THIS_CANDIDATE",
        deployment_requires=["actual affected constructor/recovery/short and matched-hour evidence",
            "one genuine exact O-LAUNCH after frozen validation", "original controlled entry and five-role gate",
            "no hot edits or business-data rollback", "ten-minute actual observer"])
    proof = save(output / "deployment-projection.json", bundle)
    print(json.dumps(dict(proof, candidate_id=candidate,
        candidate_payload_sha256=bundle["candidate_payload_sha256"], changes=1,
        production_writes=0, frontend_rebuilt=False, accepted=False)))


if __name__ == "__main__":
    main()
