"""Small, source-bearing incident review bundle. Never copy business databases."""
import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).absolute().parents[1]
BASE = ROOT / "outputs/one-minute-shadow/runtime-20261004-r58-p8-v3"
CHANGED = (
    "kquant/status_snapshot.py", "kquant/research_http_snapshots.py", "kquant/dashboard/app.py",
    "kquant/options_radar_supervisor.py", "kquant/options_opening_momentum.py",
    "kquant/options_price_reference.py", "kquant/status_worker.py", "kquant/research_runtime_health.py",
    "kquant/options_opening_trend_runtime.py", "kquant/options_opening_trend_coverage.py",
    "crypto/kquant_crypto/gateway.py", "scripts/FoundationLifecycle.ps1", "start_kquant_workspace.ps1",
    "web/src/unified/OptionsOperations.tsx", "web/src/unified/OptionsOperations.test.tsx",
    "tests/test_r58_p9_incident.py", "tests/test_foundation_lifecycle.py", "crypto/tests/test_operations.py")
DEPENDENCIES = (
    "kquant/bounded_sqlite.py", "kquant/options_one_minute.py", "kquant/options_two_hour.py",
    "kquant/options_two_hour_data.py", "kquant/market_clock.py", "kquant/options_opening_trend.py",
    "kquant/options_opening_momentum_journal.py", "kquant/options_opening_trend_store.py",
    "kquant/options_opening_trend_history.py", "kquant/options_opening_trend_prewarm.py",
    "kquant/options_opening_trend_reference.py", "kquant/options_price_facts.py",
    "kquant/options_price_action_source.py", "kquant/options_minute_admission.py",
    "kquant/options_minute_decisions.py", "kquant/options_opening_trend_current.py",
    "kquant/options_opening_trend_pipeline.py", "kquant/options_opening_trend_approval.py",
    "kquant/options_release_acceptance.py", "kquant/options_service_observation.py",
    "kquant/options_opening_trend_events.py", "kquant/options_opening_trend_contracts.py",
    "kquant/options_opening_trend_jobs.py", "kquant/options_opening_trend_sdk.py",
    "kquant/options_opening_trend_risk.py", "kquant/options_opening_trend_summary.py",
    "kquant/options_opening_trend_projection.py", "kquant/options_opening_trend_clock.py",
    "kquant/options_opening_trend_publication.py", "kquant/options_one_minute_manual.py",
    "kquant/options_reported_risk_quotes.py", "kquant/options_source_updates.py",
    "crypto/kquant_crypto/security.py", "kquant/security.py", "web/src/unified/currentEligibility.ts",
    "web/src/unified/useOperationalResource.ts", "web/src/unified/operationsStream.ts",
    "web/src/unified/operationalData.ts", "web/src/unified/openingTrendText.ts",
    "tests/test_r58_positive_chain.py", "tests/test_r58_signal_recovery.py",
    "tests/test_r58_p7_inputs.py", "tests/test_r58_p8_closeout.py",
    "tests/test_r58_authenticated_manual_chain.py", "tests/test_options_opening_momentum.py",
    "tests/test_options_opening_trend_reference.py", "tests/test_status_snapshot.py",
    "scripts/capture_r58_p9_incident.py", "scripts/replay_r58_p9_inputs.py",
    "scripts/reconcile_r58_p9_incident.py", "scripts/check_r58_p9_mixed.py",
    "scripts/check_r58_p9_browser.cjs", "scripts/probe_r58_p9_live.py",
    "scripts/collect_r58_p9_readiness.py", "scripts/profile_r58_p9_calculation.py",
    "scripts/finalize_r58_p9_acceptance.py",
    "scripts/package_r58_p9_review.py", "scripts/Launch-FoundationDetached.ps1",
    "scripts/Invoke-FoundationDetached.ps1")
CONFIG = (
    "config/options_opening_momentum_v1.json", "config/options_opening_momentum_event_coverage_v1.json",
    "config/options_opening_momentum_web_policy_v1.json",
    "config/review_acceptances/options_opening_trend_reference_sources.json",
    "config/review_acceptances/options_contract_units_sources.json")
SECRET = re.compile(rb"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{24,}|Bearer\s+[A-Za-z0-9_.-]{24,}")


def raw(path):
    if path.is_symlink() or path.is_junction() or not path.is_file() or path.stat().st_size > 12 * 1024 * 1024:
        raise ValueError("BOUNDED_REGULAR_FILE_REQUIRED: " + str(path))
    value = path.read_bytes()
    if SECRET.search(value):
        raise ValueError("POSSIBLE_CREDENTIAL_EXCLUDED_PATH_ONLY: " + str(path))
    return value


def digest(value):
    return sha256(value).hexdigest()


def snapshot(out):
    base_raw = raw(BASE / "manifest.json")
    base = json.loads(base_raw)
    inventory = {}
    for name in dict.fromkeys(CHANGED + DEPENDENCIES):
        file = ROOT / name
        value = raw(file)
        archived = BASE / "source" / name
        expected = base.get("files", {}).get(name, {}).get("sha256") or base.get("retained_source_hashes", {}).get(name)
        if not archived.is_file():
            archived = Path(base["base_release"]) / "source" / name
        original_hash = digest(raw(archived)) if archived.is_file() else None
        if expected and original_hash != expected:
            raise ValueError("PREVIOUS_SOURCE_RECOVERY_HASH_MISMATCH: " + name)
        inventory[name] = {"sha256": digest(value), "bytes": len(value),
            "role": "PATCH" if name in CHANGED else "REVIEW_DEPENDENCY",
            "previous_source_sha256": original_hash,
            "previous_source_path": str(archived) if original_hash else None,
            "different_from_previous": original_hash != digest(value)}
    configs = {name: digest(raw(ROOT / name)) for name in CONFIG}
    builds = {}
    for label in ("candidate-dist-unified", "candidate-dist-stock"):
        directory = out / label
        builds[label] = {p.relative_to(directory).as_posix(): digest(raw(p))
            for p in sorted(directory.rglob("*")) if p.is_file()}
    scope = json.loads((out / "production-readonly-indexed/watch.json").read_text())["scope_hash"]
    identity = {"source": {k: v["sha256"] for k, v in inventory.items()},
                "config": configs, "builds": builds, "scope_hash": scope}
    bundle_hash = digest(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode())
    result = {"candidate_id": "runtime-20261006-r58-p9-incident-" + bundle_hash[:12],
        "created_at": datetime.now(UTC).isoformat(), "bundle_sha256": bundle_hash,
        "deployed": False, "owner_accepted": False, "production_entry_changed": False,
        "base_runtime": BASE.name, "base_manifest_sha256": digest(base_raw),
        "rollback": "Retain base source/build references. Never restore business databases from this bundle.",
        "inventory": inventory, **identity, "database_copies": 0,
        "build_acceptance": "ISOLATED_ONLY_NOT_PRODUCTION_8020",
        "permissions": {"llm": False, "paper": False, "real_orders": False, "system_notifications": False}}
    (out / "candidate_identity.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"candidate_id": result["candidate_id"], "bundle_sha256": bundle_hash,
        "source_files": len(inventory), "deployed": False}))
    return result


def package(out, target):
    frozen = json.loads((out / "candidate_identity.json").read_text())
    for name, expected in frozen["source"].items():
        if digest(raw(ROOT / name)) != expected:
            raise ValueError("SOURCE_CHANGED_AFTER_CANDIDATE_FREEZE: " + name)
    for name, expected in frozen["config"].items():
        if digest(raw(ROOT / name)) != expected:
            raise ValueError("CONFIG_CHANGED_AFTER_CANDIDATE_FREEZE: " + name)
    pressure = json.loads((out / "mixed-60min-v5-complete-window/mixed_load_report.json").read_text())
    if not pressure["continuous_60_minutes"] or not pressure["five_minute_cadence"] or not pressure["wall_clock_advances_through_full_entry_window"]:
        raise ValueError("ACTUAL_MIXED_HOUR_REQUIRED_BEFORE_FINAL_REVIEW_PACKAGE")
    for name, expected in pressure["executed_source_hashes"].items():
        if digest(raw(ROOT / name)) != expected:
            raise ValueError("RUNTIME_CHANGED_AFTER_MEASURED_MIXED_HOUR: " + name)
    if target.exists() or target.absolute().drive.upper() != "C:":
        raise ValueError("NEW_C_DRIVE_BUNDLE_REQUIRED")
    files = {}
    for name in frozen["source"]:
        files["source/" + name] = ROOT / name
    for name in CONFIG:
        files["source/" + name] = ROOT / name
    for name in ("INCIDENT_CLOSEOUT_REVIEW_20261006.md", "OWNER_PREOPEN_CHECKLIST.md"):
        files[name] = out / name
    files["base/manifest.json"] = BASE / "manifest.json"
    for label in ("candidate-dist-unified",):
        for name, expected in frozen["builds"][label].items():
            file = out / label / name
            if digest(raw(file)) != expected:
                raise ValueError("FRONTEND_CHANGED_AFTER_FREEZE")
            files["frontend/" + name] = file
    # The official source originals referenced by configs accompany their hashes.
    def originals(value):
        if isinstance(value, dict):
            name, expected = value.get("source_path"), value.get("source_sha256")
            if name and expected:
                file = (ROOT / name).resolve()
                if not file.is_relative_to(ROOT.resolve()) or digest(raw(file)) != expected:
                    raise ValueError("SOURCE_ORIGINAL_HASH_MISMATCH: " + str(name))
                files["source/" + name.replace("\\", "/")] = file
            for child in value.values():
                originals(child)
        elif isinstance(value, list):
            for child in value:
                originals(child)
    for name in CONFIG[-2:]:
        originals(json.loads(raw(ROOT / name)))
    allowed = {".json", ".jsonl", ".md", ".log", ".txt", ".png", ".py"}
    include_dirs = {"production-readonly-indexed", "actual-replay-v3-symbol-asof", "mixed-60min-v3-frozen",
                    "mixed-60min-v4-cadenced", "mixed-60min-v5-complete-window", "mixed-batch-smoke-v5",
                    "mixed-manual-path-smoke", "mixed-manual-path-smoke-v2", "mixed-final-instrumentation-smoke",
                    "mixed-coldstart-frozen",
                    "v4-executed-source", "calculation-profile-v2"}
    for file in out.rglob("*"):
        if not file.is_file() or file.suffix.lower() not in allowed:
            continue
        relative = file.relative_to(out)
        if len(relative.parts) == 1 or relative.parts[0] in include_dirs:
            files["evidence/" + relative.as_posix()] = file
    entries = {}
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=4) as archive:
        for name, file in sorted(files.items()):
            value = raw(file)
            archive.writestr(name, value)
            entries[name] = {"sha256": digest(value), "bytes": len(value)}
        archive.writestr("bundle_manifest.json", json.dumps({"created_at": datetime.now(UTC).isoformat(),
            "candidate": frozen["candidate_id"], "not_a_standalone_rebuilt_project": True,
            "base_required": BASE.name, "database_copies": 0, "entries": entries}, indent=2))
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise ValueError("BUNDLE_CRC_TEST_FAILED")
        for name, expected in entries.items():
            if digest(archive.read(name)) != expected["sha256"]:
                raise ValueError("BUNDLE_ENTRY_HASH_MISMATCH")
    checksum = sha256()
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    result = {"path": str(target), "sha256": checksum.hexdigest(), "bytes": target.stat().st_size,
              "files": len(entries), "crc_and_entry_hashes_verified": True, "production_deployed": False}
    (out / "review_bundle.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--zip", type=Path)
    arguments = parser.parse_args()
    if arguments.zip:
        package(arguments.out, arguments.zip)
    else:
        snapshot(arguments.out)
