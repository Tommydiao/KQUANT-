"""Bounded offline P14 sidecar. Never constructs an SDK or sends requests.

Writes only CWD P14_CAPACITY_* evidence. Production sources are read-only.
"""
import argparse
import ast
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile


CODE = Path(__file__).resolve().parents[1]
CWD = Path(r"C:\Users\Administrator\Desktop\Codex coding")
PRICE_CONFIG = "config/review_acceptances/options_opening_trend_reference_sources.json"
EXPIRY = "2026-10-14T10:11:42.484792+00:00"
SCENARIOS = ("healthy", "transient_failures", "slow_1_5s", "slow_10s",
             "graceful_restart", "lost_reservation_restart", "lease_overrun")


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def write(name, value):
    assert name.startswith("P14_CAPACITY_") and "/" not in name and "\\" not in name
    path = CWD / name
    text = json.dumps(value, indent=2, ensure_ascii=True) if not isinstance(value, str) else value
    path.write_text(text, encoding="utf-8")
    return path


def walk(value, pointer=""):
    if isinstance(value, dict):
        if "valid_until" in value:
            yield pointer, value
        for key, child in value.items():
            yield from walk(child, pointer + "/" + key.replace("~", "~0").replace("/", "~1"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, pointer + "/" + str(index))


def pointer_value(value, pointer):
    for key in pointer.split("/")[1:]:
        key = key.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def definition(file, name):
    tree = ast.parse((CODE / file).read_text(encoding="utf-8-sig"))
    node = next(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == name)
    return dict(path=str(CODE / file), function=name, line=node.lineno)


def source_inventory():
    sys.path.insert(0, str(CODE))
    from kquant.options_opening_trend_reference import source_review
    now = datetime.now(UTC)
    archive = CWD / "KQUANT_R58P13_REAL_S0_REVIEW_20261013_v2.zip"
    with zipfile.ZipFile(archive) as bundle:
        original_raw = bundle.read("identity/price-sources.json")
    original = json.loads(original_raw)
    raw = (CODE / PRICE_CONFIG).read_bytes()
    current = json.loads(raw)
    receipt = CODE / "outputs/r58/p14-source-revalidation-20261013/receipt.json"
    receipt_value = json.loads(receipt.read_bytes()) if receipt.is_file() else {}
    renewal = {row["pointer"]: row for row in receipt_value.get("rows", [])}
    consumers = {
        "loader": definition("kquant/options_opening_trend_reference.py", "load_reviews"),
        "validator": definition("kquant/options_opening_trend_reference.py", "source_review"),
        "contract_binding": definition("kquant/options_opening_trend_reference.py", "contract_proofs"),
        "contract_validation": definition("kquant/options_opening_trend_reference.py", "_provider_standard"),
        "instrument_classification": definition("kquant/options_price_facts.py", "instrument"),
        "session_price_binding": definition("kquant/options_price_facts.py", "bind"),
        "price_reference": definition("kquant/options_price_reference.py", "build"),
    }
    expiring = [(pointer, row) for pointer, row in walk(original) if row.get("valid_until") == EXPIRY]
    assert len(expiring) == 16, "P13 archive's original expiring cohort changed"
    rows = []
    for pointer, original_row in expiring:
        live = pointer_value(current, pointer)
        source = (CODE / live["source_path"]).resolve()
        assert source.is_relative_to(CODE.resolve())
        actual = sha256(source.read_bytes()).hexdigest() if source.is_file() else None
        roles = ["loader", "validator", "contract_binding", "contract_validation"]
        if pointer.startswith("/instrument_facts/"):
            roles += ["instrument_classification", "session_price_binding", "price_reference"]
        rows.append(dict(pointer=pointer, original_valid_until=original_row["valid_until"],
                         current_valid_until=live.get("valid_until"), source_url=live.get("source_url"),
                         original_source_url=original_row["source_url"],
                         original_source_path=str(CODE / original_row["source_path"]), source_path=str(source),
                         expected_sha256=live.get("source_sha256"), actual_sha256=actual,
                         unchanged_hash=actual == live.get("source_sha256"),
                         source_review_passes_now=source_review(live, root=CODE, now=now) is not None,
                         parent_revalidation_status=renewal.get(pointer, {}).get("status"),
                         changed_since_P13=live != original_row, consumers=[consumers[role] for role in roles]))
    revalidation = ["tests/test_r58_p7_inputs.py", "tests/test_r58_positive_chain.py",
                    "tests/test_r58_p10_fresh_binding.py", "tests/test_r58_signal_recovery.py",
                    "tests/test_p13_snapshot_coverage.py", "scripts/collect_r58_p9_readiness.py"]
    return dict(schema="P14_CAPACITY_PRICE_SOURCE_READONLY_V1", observed_at=now.isoformat(),
                alias="identity/price-sources.json", alias_is_zip_member_not_filesystem_path=True,
                archive_path=str(archive), archive_member_sha256=sha256(original_raw).hexdigest(),
                consuming_config_path=str(CODE / PRICE_CONFIG), current_config_sha256=sha256(raw).hexdigest(),
                merged_contract_config=str(CODE / "config/review_acceptances/options_contract_units_sources.json"),
                original_expiring_cohort_count=len(rows), records=rows,
                current_source_review_pass_count=sum(row["source_review_passes_now"] for row in rows),
                parent_revalidated_count=sum(row["parent_revalidation_status"] == "REVALIDATED" for row in rows),
                parent_retained_unavailable_pointers=[row["pointer"] for row in rows
                    if row["parent_revalidation_status"] == "REVALIDATION_UNAVAILABLE_OLD_RECORD_RETAINED"],
                parent_revalidation_receipt_path=str(receipt),
                parent_revalidation_receipt_sha256=sha256(receipt.read_bytes()).hexdigest() if receipt.is_file() else None,
                recommended_revalidation_files=[str(CODE / file) for file in revalidation],
                source_review_checks_hash_excerpt_authority_and_time_not_live_truth=True,
                production_edits=False, refetches=0, renewal_owner="PARENT")


def proposal():
    return dict(schema="P14_CAPACITY_PROPOSAL_V2", status="PROPOSED_NOT_ACCEPTED", owner_confirmation=None,
                supersedes_proposal_sha256="e7c095b5667063cb7dfd9fe7f08a78ba95cc56a5c212ff460c3d720924e562d8",
                budget_status="NEW_LOCAL_BUDGET_PENDING_OWNER_NOT_VERIFIED_PROVIDER_LIMIT",
                provider_limit_verified=False,
                production_apply_authorized=False, production_cap_changed=False,
                comparison=dict(default_cap=12, proposed_cap=120, budget_window_seconds=840,
                                budget_semantics="PERSISTENT_ANCHORED_FIXED_WINDOW_NOT_ROLLING",
                                minimum_request_start_interval_seconds=1, maximum_concurrent_requests=1,
                                calendar_reserved_requests=6, action_batch_size=3, fact_ttl_seconds=900,
                                object_count=100, simulated_seconds=2700),
                proposed_control_location=dict(cap="CalendarSourceRunner.shared_source_window_cap",
                                               interval="NOT_IMPLEMENTED_IN_PRODUCTION_REQUIRES_SEPARATE_OWNER_REVIEW",
                                               gate="SourceCallGate"),
                real_probe=dict(status="NOT_RUN_REQUIRES_LATER_EXPLICIT_OWNER_CONFIRMATION",
                                symbols=["FCX.US", "NVTS.US", "NVDA.US", "AMD.US", "AAPL.US", "MSFT.US"],
                                scope_objects=6, maximum_elapsed_seconds=2700, maximum_total_requests=48,
                                maximum_requests_per_840_second_window=12,
                                minimum_request_start_interval_seconds=1, maximum_concurrent_requests=1,
                                calendar_maximum_requests_per_batch=6,
                                allowed_methods=["GET"],
                                allowed_endpoints=["/v1/quote/company-act", "/v1/quote/finance_calendar"],
                                company_action_query=dict(req_type="1", version="3", symbol="ALLOWLIST_ONLY"),
                                company_action_semantics="RAW_UNDATED_NATIVE_OBSERVATION_NO_COMPLETENESS_INFERENCE",
                                snapshot_completeness_required_for_raw_probe=False,
                                calendar_scope=dict(market="US", categories="EXISTING_SIX_CATEGORIES",
                                                    date_end="SESSION_PLUS_7_DAYS", pagination="NO_EXTRA_REQUESTS"),
                                isolated_store_required=True, no_production_fact_promotion=True,
                                no_extra_workers=True, automatic_restart=False, automatic_retry_after_timeout=False,
                                abort_on=["FIRST_PROVIDER_RATE_LIMIT", "UNKNOWN_ACCOUNTING", "TIMEOUT_OR_STUCK_CALL",
                                          "IDENTITY_OR_RAW_RESPONSE_SCHEMA_INVALID", "HARD_LIMIT_REACHED",
                                          "PACING_OR_CONCURRENCY_VIOLATION"],
                                prerequisites=["OWNER confirmation of this exact proposal hash and probe scope",
                                               "Parent confirms allowlisted identities and isolated raw observation store",
                                               "Separate bounded limiter reviewed before any real probe"],
                                provider_quota_status="UNKNOWN_NOT_VERIFIED_BY_THIS_PROPOSAL",
                                limitation="Six-object probe cannot establish 100-object sustained production capacity"),
                exclusions=["NO_SDK_OR_HTTP_REQUESTS_IN_THIS_SIDECAR", "NO_PRODUCTION_MODULE_OR_CONFIG_EDITS",
                            "NO_FORGED_FACTS_OR_OWNER_ACCEPTANCE", "NO_PRODUCTION_CAP_CHANGE",
                            "NO_MARKET_OR_SIGNAL_QUALIFICATION", "PARENT_OWNS_FACT_RENEWAL_AND_FREEZE"])


def protected_hashes():
    result = {}
    for directory in ("kquant", "config", "scripts", "tests"):
        for file in (CODE / directory).rglob("*"):
            if file.is_file() and file.suffix in (".py", ".json", ".toml", ".yaml", ".yml") and "__pycache__" not in file.parts:
                relative = file.relative_to(CODE).as_posix()
                if relative not in ("tests/test_p14_capacity.py", "scripts/check_p14_capacity.py"):
                    result[relative] = sha256(file.read_bytes()).hexdigest()
    return result


def comparison(results):
    rows = []
    for scenario in SCENARIOS:
        for cap in (12, 120):
            result = results[f"{scenario}_{cap}"]
            rows.append(dict(scenario=scenario, cap=cap, action_requests=result["action_requests"],
                             calendar_requests=result["calendar_requests"], failures=result["failures"],
                             unknown_charge=result["unknown_reservation_charge"],
                             first_all_100_fresh_seconds=result["first_all_100_fresh_seconds"],
                             uninterrupted_all_100_after_warmup=result["uninterrupted_all_100_after_warmup"],
                             fresh_at_900=result["cycles"][0]["end"]["fresh"],
                             fresh_at_1800=result["cycles"][1]["end"]["fresh"],
                             fresh_at_2700=result["final"]["fresh"],
                             expired_at_2700=result["final"]["expired"], never_at_2700=result["final"]["never"],
                             last_two_cycles_min_fresh=[cycle["min_fresh"] for cycle in result["cycles"][1:]],
                             budget_accounted_requests=result["budget_accounted_requests"],
                             failed_commits=result["failed_commits"]))
    return rows


def finalize_results():
    """Re-render evidence after the tests without rerunning or changing them."""
    path = CWD / "P14_CAPACITY_COMPARISON_20261013.json"
    report = json.loads(path.read_bytes())
    inventory = source_inventory()
    write("P14_CAPACITY_SOURCE_REVALIDATION_20261013.json", inventory)
    plan = proposal()
    plan_hash = digest(plan)
    proposal_path = write("P14_CAPACITY_PROPOSAL_20261013_v2.json", dict(proposal=plan, proposal_sha256=plan_hash,
        hash_encoding="SHA256 of UTF-8 JSON sorted keys, compact separators, ensure_ascii=true"))
    report.update(proposal_path=str(proposal_path), proposal_sha256=plan_hash,
                  evidence_finalized_at=datetime.now(UTC).isoformat(),
                  parent_revalidated_count=inventory["parent_revalidated_count"],
                  parent_retained_unavailable_pointers=inventory["parent_retained_unavailable_pointers"])
    report["owned_file_hashes"] = {name: sha256((CODE / name).read_bytes()).hexdigest() for name in (
        "tests/test_p14_capacity.py", "scripts/check_p14_capacity.py")}
    results = json.loads(Path(report["test_results_path"]).read_bytes())["results"]
    exact = {}
    for key, result in results.items():
        if "objects" not in result:
            continue
        warmup = result["first_all_100_fresh_seconds"]
        gaps = {}
        for symbol, row in result["objects"].items():
            intervals = [(commit["at_seconds"], commit["valid_until_seconds"])
                         for commit in row["commits"] if commit["valid_until_seconds"] is not None]
            missing, covered_until = [], 0
            for start, end in intervals:
                if start > covered_until:
                    missing.append([covered_until, min(start, 2700)])
                covered_until = max(covered_until, end)
            if covered_until < 2700:
                missing.append([covered_until, 2700])
            gaps[symbol] = [[max(start, warmup), end] for start, end in missing
                           if warmup is not None and end > max(start, warmup)]
        exact[key] = dict(warmup_seconds=warmup,
                          uninterrupted_after_warmup=warmup is not None and not any(gaps.values()),
                          gaps_seconds=gaps)
    report["exact_continuous_interval_proof"] = exact
    for row in report["comparison"]:
        row["exact_uninterrupted_after_warmup"] = exact[f"{row['scenario']}_{row['cap']}"]["uninterrupted_after_warmup"]
    write(path.name, report)
    summary_path = CWD / "P14_CAPACITY_FINDINGS_20261013.md"
    summary = summary_path.read_text(encoding="utf-8")
    old_hash = json.loads((CWD / "P14_CAPACITY_PROPOSAL_20261013.json").read_bytes())["proposal_sha256"]
    summary = summary.replace(old_hash, plan_hash)
    summary += ("\n## Final Proposal Revision\n\n"
                "Original proposal retained unchanged. Authoritative proposal: `" + str(proposal_path) + "`.\n"
                "Raw probe: RAW_UNDATED_NATIVE_OBSERVATION_NO_COMPLETENESS_INFERENCE. No completeness prerequisite or fact promotion.\n"
                "120 is a new local budget pending OWNER, not a verified provider limit; no cap activated.\n"
                f"Parent renewal receipt: {inventory['parent_revalidated_count']}/16 renewed; five retained/unavailable: "
                + ", ".join(inventory["parent_retained_unavailable_pointers"]) + ".\n"
                "Stored archive validation passing is not fresh refetch success.\n"
                "Exact continuous freshness intervals (including fractional seconds) are in the comparison JSON.\n")
    write(summary_path.name, summary)
    print(json.dumps(dict(test_status=report["test_status"], comparison=report["comparison"],
                          proposal_sha256=plan_hash, proposal_path=str(proposal_path)), indent=2))
    return 0 if report["test_status"] == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect-only", action="store_true")
    parser.add_argument("--finalize-results", action="store_true")
    args = parser.parse_args()
    assert CODE == Path(r"E:\kquant 1007\KQUANT-Resume-Latest\source\development\workspace")
    assert Path.cwd().resolve() == CWD.resolve(), "Run from the authorized evidence CWD"
    if args.finalize_results:
        return finalize_results()
    inventory = source_inventory()
    source_path = write("P14_CAPACITY_SOURCE_REVALIDATION_20261013.json", inventory)
    plan = proposal()
    plan_hash = digest(plan)
    proposal_path = write("P14_CAPACITY_PROPOSAL_20261013_v2.json", dict(proposal=plan, proposal_sha256=plan_hash,
        hash_encoding="SHA256 of UTF-8 JSON sorted keys, compact separators, ensure_ascii=true"))
    if args.inspect_only:
        print(json.dumps(dict(source_inventory=str(source_path), proposal=str(proposal_path), proposal_sha256=plan_hash,
                              current_source_review_pass_count=inventory["current_source_review_pass_count"])))
        return 0
    before = protected_hashes()
    output = CWD / "P14_CAPACITY_TEST_RESULTS_20261013.json"
    base = CWD / ("P14_CAPACITY_TEST_TMP_" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"))
    assert base.parent.resolve() == CWD.resolve() and not base.exists()
    command = [sys.executable, "-B", "-m", "pytest", "tests/test_p14_capacity.py",
               "tests/test_p11_budget_concurrency.py", "tests/test_p11_calendar_accounting.py",
               "tests/test_p11_source_call.py", "tests/test_p11_source_process_recovery.py",
               "tests/test_p11_action_leases.py", "-q", "-p", "no:cacheprovider", "--basetemp", str(base)]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", P14_CAPACITY_TEST_RESULTS=str(output))
    env.pop("KQUANT_RUNTIME_DATA_ROOT", None)
    started = time.monotonic()
    run = subprocess.run(command, cwd=CODE, env=env, capture_output=True, text=True, timeout=600)
    elapsed = time.monotonic() - started
    log_path = write("P14_CAPACITY_PYTEST_20261013.txt", run.stdout + run.stderr)
    after = protected_hashes()
    changed = [path for path in sorted(set(before) | set(after)) if before.get(path) != after.get(path)]
    valid_output = output.is_file() and output.stat().st_mtime >= time.time() - elapsed - 5
    results = json.loads(output.read_text())["results"] if valid_output else {}
    complete = all(f"{scenario}_{cap}" in results for scenario in SCENARIOS for cap in (12, 120))
    rows = comparison(results) if complete else []
    report = dict(schema="P14_CAPACITY_COMPARISON_SIDECAR_V1", observed_at=datetime.now(UTC).isoformat(),
                  test_status="PASS" if run.returncode == 0 and complete else "FAIL",
                  test_returncode=run.returncode, test_command=command, elapsed_seconds=round(elapsed, 3),
                  test_results_current_run=valid_output, comparison=rows,
                  proposal_path=str(proposal_path), proposal_sha256=plan_hash,
                  test_results_path=str(output), pytest_log_path=str(log_path),
                  source_inventory_path=str(source_path), protected_files_before=before,
                  protected_files_after=after, protected_files_changed_during_run=changed,
                  change_attribution="Hash drift alone is not attributed to this sidecar; parent owns concurrent renewal",
                  owned_changed_files=[str(CODE / "tests/test_p14_capacity.py"), str(CODE / "scripts/check_p14_capacity.py")],
                  owned_file_hashes={name: sha256((CODE / name).read_bytes()).hexdigest() for name in (
                      "tests/test_p14_capacity.py", "scripts/check_p14_capacity.py")},
                  provider_requests=0, production_cap_changed=False, owner_confirmation=None,
                  assessment="CONDITIONAL_OFFLINE_CAPACITY_NOT_PRODUCTION_APPROVAL" if run.returncode == 0 else "TEST_FAILURE",
                  limitations=["Fictional complete method; not evidence for installed provider capability",
                               "One-second spacing is test-boundary enforcement absent in the production gate",
                               "Simulated latency does not measure wall-clock SDK timeout or provider p95",
                               "Fixed 840-second windows do not enforce a rolling-window provider rate limit",
                               "Calendar reserve6 assumes one page per category; pagination can leave gaps",
                               "Cold start is not immediately fresh; failures and slow calls can invalidate a cap-only conclusion",
                               "Parent owns renewed facts and freeze; no production facts promoted"])
    report_path = write("P14_CAPACITY_COMPARISON_20261013.json", report)
    lines = ["# P14 Capacity Comparison", "", "TEST_ONLY; no provider request, production edit, or OWNER acceptance.",
             "", "Proposal SHA256: `" + plan_hash + "`", "", "| Scenario | Cap | Action/calendar | Fresh 900/1800/2700 | Expired/never 2700 | Continuous after warmup |", "|---|---:|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['scenario']} | {row['cap']} | {row['action_requests']}/{row['calendar_requests']} | "
                     f"{row['fresh_at_900']}/{row['fresh_at_1800']}/{row['fresh_at_2700']} | "
                     f"{row['expired_at_2700']}/{row['never_at_2700']} | {row['uninterrupted_all_100_after_warmup']} |")
    lines += ["", "## Decision", "", "12/840 cannot sustain 100 objects. 120/840 is a conditional offline capacity candidate, not a production go-ahead.",
              "The paired slow/failure/restart cases and per-object cycle histories define its limits. Preserve strict 900-second expiry.",
              "OWNER confirmation must cite the exact proposal hash; the later six-object, 48-request maximum probe cannot validate 100-object scale.",
              "Production pacing and independently verified provider limits remain separate prerequisites.", "", "## Source Revalidation", "",
              f"Original ZIP cohort: 16 pointers. Current read-only source_review passes: {inventory['current_source_review_pass_count']}/16.",
              f"Parent receipt: {inventory['parent_revalidated_count']}/16 freshly revalidated; retained/unavailable pointers: "
                  + ", ".join(inventory["parent_retained_unavailable_pointers"]) + ".",
              "source_review can still accept an unchanged, unexpired retained archive; that does not mean its refetch succeeded.",
              "Actual config: `" + str(CODE / PRICE_CONFIG) + "`.", "All 16 exact pointers, URLs, original/current archived paths and consuming function paths are in `" + str(source_path) + "`.",
              "Parent owns renewal/freeze. The sidecar neither renews nor asserts the truth of source contents.", "", "## Verification", "",
              f"pytest return code {run.returncode}; elapsed {elapsed:.3f}s. Log: `{log_path}`.",
              "Protected source/config hash drift during run: " + (", ".join(changed) if changed else "none") + ".",
              "Changed code files: `tests/test_p14_capacity.py`, `scripts/check_p14_capacity.py` only."]
    write("P14_CAPACITY_FINDINGS_20261013.md", "\n".join(lines) + "\n")
    print(json.dumps(dict(report=str(report_path), test_status=report["test_status"], comparison=rows,
                          proposal_sha256=plan_hash, protected_files_changed=changed), indent=2))
    return 0 if report["test_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
