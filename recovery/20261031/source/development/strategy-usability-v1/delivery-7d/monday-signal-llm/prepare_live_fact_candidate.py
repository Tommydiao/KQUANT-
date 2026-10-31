"""Freeze three reviewed repairs without editing the accepted running payload."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import sys

from prepare_null_time_candidate import BASE, HERE, ROOT, digest, encoded, read, save
from kquant.recovery_preflight import candidate_hash


def main():
    entry_path = BASE / "config/local_workspace_entry.json"
    entry = read(entry_path)
    baseline = read(HERE / "release/local-candidate-b8742253742df53c/deployment-projection.json")
    if entry["candidate_id"] != baseline["base_candidate"]:
        raise ValueError("REVIEWED_LIVE_PARENT_CHANGED")
    for key in ("runtime_manifest", "recovery_manifest"):
        if entry[key] != baseline["base_"+key.replace("runtime", "release")]:
            raise ValueError("PARENT_PROOF_CHANGED")
        if digest(entry[key]["path"]) != entry[key]["sha256"]:
            raise ValueError("PARENT_MANIFEST_CHANGED")
    parent_release_path = Path(entry["runtime_manifest"]["path"])
    parent_release = read(parent_release_path)
    recovery = read(entry["recovery_manifest"]["path"])
    for proof in recovery["required_source"] + recovery["frontend"]:
        if not Path(proof["path"]).resolve().is_relative_to(ROOT.resolve()) or digest(proof["path"]) != proof["sha256"]:
            raise ValueError("PARENT_SOURCE_OR_BUILD_CHANGED")
    rows = deepcopy(baseline["changes"])
    for row in rows:
        if digest(BASE / row["target"]) != row["previous_sha256"] or digest(row["payload"]) != row["sha256"]:
            raise ValueError("NULL_TIME_REPAIR_CHANGED")
    target = "kquant/options_opening_trend_store.py"
    proof = read(HERE / "evidence/current-card-equivalence-final-20261020.json")
    payload = HERE / "current-card-followup/patches" / target
    if digest(BASE / target) != proof["original_sha256"] or digest(payload) != proof["followup_sha256"]:
        raise ValueError("EQUIVALENCE_SOURCE_CHANGED")
    if not all(row["equivalent"] for row in proof["attempts"]):
        raise ValueError("EQUIVALENCE_FAILED")
    rows.append(dict(target=target, payload=str(payload), sha256=digest(payload),
        previous_sha256=digest(BASE / target)))
    target = "kquant/options_one_minute_runtime.py"
    payload = HERE / "fact-commit-followup/patches" / target
    if digest(BASE / target) != digest(HERE / "patches" / target):
        raise ValueError("REVIEWED_RUNTIME_PARENT_CHANGED")
    from xml.etree import ElementTree
    tests = ElementTree.parse(HERE / "evidence/live-fact-commit-20261020.xml").getroot()
    if any(int(node.get("errors", "0")) or int(node.get("failures", "0")) for node in tests.iter("testsuite")):
        raise ValueError("LIVE_FACT_COMMIT_TESTS_FAILED")
    rows.append(dict(target=target, payload=str(payload), sha256=digest(payload),
        previous_sha256=digest(BASE / target)))
    release = deepcopy(parent_release)
    for row in rows:
        release["files"][row["target"]] = dict(sha256=row["sha256"])
        for section in ("retained_source_hashes", "frontend_files", "configuration_hashes", "source_fact_hashes"):
            if row["target"] in release.get(section, {}):
                release[section][row["target"]] = row["sha256"]
    release.pop("candidate_id", None)
    release["production_accepted"] = False
    candidate = "local-candidate-"+sha256(encoded(release)).hexdigest()[:16]
    release["candidate_id"] = candidate
    out = HERE / "release" / candidate
    release_proof = save(out / "release-manifest.json", release)
    required = {p["path"]: p for p in recovery["required_source"] if Path(p["path"]) != parent_release_path}
    for row in rows:
        required[str(BASE / row["target"])] = dict(path=str(BASE / row["target"]), sha256=row["sha256"])
    required[release_proof["path"]] = release_proof
    recovery.update(candidate_id=candidate, required_source=list(required.values()),
        final_runtime_accepted=False, qualified_signal_authorized=False, can_launch=False)
    recovery.pop("acceptance_receipt", None)
    recovery_proof = save(out / "recovery-manifest.json", recovery)
    proposed = dict(entry, candidate_id=candidate, runtime_manifest=release_proof,
        recovery_manifest=recovery_proof, production_accepted=False, shadow_runtime_accepted=False)
    proposed_proof = save(out / "proposed-local-workspace-entry.json", proposed)
    parent_projection = HERE / "release" / entry["candidate_id"] / "deployment-projection.json"
    tool = HERE / "apply_checked_delta.py"
    projection = dict(schema="KQUANT_UNACCEPTED_RESEARCH_DELTA_V1", candidate_id=candidate,
        candidate_payload_sha256=candidate_hash(recovery), base_candidate=entry["candidate_id"],
        base_entry_sha256=digest(entry_path), base_release_manifest=entry["runtime_manifest"],
        base_recovery_manifest=entry["recovery_manifest"], release_manifest=release_proof,
        recovery_manifest=recovery_proof, proposed_entry=proposed_proof, changes=rows,
        inherited_projection=dict(path=str(parent_projection), sha256=digest(parent_projection)),
        deployment_tool=dict(path=str(tool), sha256=digest(tool)),
        recovery_input_boundary="REJECT_PUSH_BEFORE_PULL_TIME_PARSE_V1",
        current_card_materialization_boundary="VISIBLE_RESEARCH_SUBSET_SNAPSHOT_V1",
        live_fact_commit_boundary="PREPARE_THEN_ACCEPTED_CAS_COMMIT_V1",
        approved=False, applied=False, production_accepted=False, qualified_signal_authorized=False,
        frontend_rebuilt=False, frontend_reuse="EXACT_ACCEPTED_PARENT_STOCK_AND_UNIFIED_BUILDS",
        data_epoch_reinitialized=False, live_writes=0,
        deadline_constraint=read(HERE.parent / "constraint.json"),
        preparation_tool_sha256=digest(Path(__file__)),
        source_equivalence_evidence=dict(path=str(HERE / "evidence/current-card-equivalence-final-20261020.json"),
            sha256=digest(HERE / "evidence/current-card-equivalence-final-20261020.json")),
        harness_readiness="EXACT_THREE_REPAIR_ADAPTER_REQUIRED_BEFORE_SHORT_AND_MATCHED_HOUR",
        prior_b874_hour="SEPARATE_ONE_REPAIR_HOUR_PRESERVE_CURRENT_CARDS_FAILURE_NOT_THIS_CANDIDATE",
        deployment_requires=baseline["deployment_requires"])
    saved = save(out / "deployment-projection.json", projection)
    print(json.dumps(dict(saved, candidate_id=candidate, candidate_payload_sha256=projection["candidate_payload_sha256"],
        changes=len(rows), production_writes=0, accepted=False)))


if __name__ == "__main__":
    main()
