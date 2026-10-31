"""Offline, read-only source audit of one retained-watchlist quote series.

Partial snapshots are explicit. --final requires all 100 attempts and an
existing controller lock acquired without writing it. No SDK/env/API imports
or process launches occur; only new immutable audit outputs are written.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager, nullcontext
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys

import run_watchlist_quote_facts_series as controller

ROOT = Path(__file__).resolve().parent
DEFAULT_SERIES = ROOT / "evidence/watchlist-quote-series/watchlist-quote-20261007-v1"
OUTPUT = ROOT / "evidence/watchlist-quote-audits"
SHA_PATTERN = re.compile(r"[a-f0-9]{64}")
FALSE_GATES = ("trade_context_created", "orders_enabled", "system_clock_modified",
               "owner_acceptance_created", "production_admission_verified")
AUDIT_BOUNDARY = ["ABSOLUTE_CLOCK_NOT_ACCEPTED", "LIVE_CLOSED_MINUTE_INPUT_NOT_PROBED",
    "PRIOR_CLOSE_SCALE_NOT_BOUND", "RAW_VOLUME_AND_TURNOVER_UNITS_NOT_ACCEPTED",
    "CONTRACT_DELIVERABLE_NOT_ACCEPTED", "LIVE_BBO_EVENT_TIME_AND_FRESHNESS_NOT_PROVEN",
    "SOURCE_METHOD_OWNER_ACCEPTANCE_NOT_CREATED"]


class AuditError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def native(row, field):
    value = row.get(field, {}) if isinstance(row, dict) else {}
    return value.get("raw") if isinstance(value, dict) else None


def numeric(value):
    try:
        parsed = Decimal(str(value)) if value is not None and not isinstance(value, bool) else None
        return parsed if parsed is not None and parsed.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def aware_iso(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AuditError("AWARE_RECEIPT_TIME_REQUIRED")
    return parsed.astimezone(timezone.utc)


def verify_native_timestamp(captured, binding):
    if not isinstance(captured, dict) or captured.get("raw") is None:
        return False
    if captured.get("native_type") != "datetime.datetime":
        raise AuditError("NATIVE_TIMESTAMP_TYPE_CHANGED")
    raw = datetime.fromisoformat(captured["raw"])
    if raw.tzinfo is None or raw.utcoffset() is None:
        if captured.get("normalization_state") != "VERIFIED_SDK_NAIVE_ADAPTER" or not binding.get("timestamp_evidence_sha256"):
            raise AuditError("NAIVE_TIMESTAMP_UNVERIFIED")
        # The immutable empirically verified contract is fixed +08 for the
        # exact installed wheel; this audit independently checks each value.
        expected = raw.replace(tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)
    else:
        if captured.get("normalization_state") != "ORIGINAL_AWARE_TIMESTAMP":
            raise AuditError("AWARE_TIMESTAMP_PROFILE_CHANGED")
        expected = raw.astimezone(timezone.utc)
    if aware_iso(captured.get("utc", "")) != expected:
        raise AuditError("NATIVE_TIMESTAMP_UTC_ADAPTER_MISMATCH")
    return True


def checked_ref(ref, parent, source_bytes):
    if not isinstance(ref, dict) or not SHA_PATTERN.fullmatch(str(ref.get("sha256", ""))):
        raise AuditError("IMMUTABLE_REFERENCE_INVALID")
    path = Path(ref.get("path", "")).resolve()
    if path.parent != parent.resolve() or path.suffix != ".json" or not path.stem.endswith(ref["sha256"]):
        raise AuditError("IMMUTABLE_REFERENCE_SCOPE_INVALID")
    raw = path.read_bytes()
    if digest(raw) != ref["sha256"]:
        raise AuditError("IMMUTABLE_REFERENCE_HASH_MISMATCH")
    if path in source_bytes and source_bytes[path] != raw:
        raise AuditError("SOURCE_BYTES_CHANGED_DURING_READ")
    source_bytes[path] = raw
    return json.loads(raw), path


def inspect_report(report, asset, binding):
    """Independent checks against original probe fields, before projection."""
    if report.get("mode") != "quote-facts" or any(report.get(key) is not False for key in FALSE_GATES):
        raise AuditError("PROBE_GATE_OR_MODE_CHANGED")
    if any(report.get(key) not in (None, False) for key in ("production_started", "qualified_publication_enabled", "clock_precision_verified")):
        raise AuditError("PROBE_PROMOTED_TO_PRODUCTION")
    observations = report.get("observations", [])
    if not isinstance(observations, list) or len(observations) > 11:
        raise AuditError("PROBE_OBSERVATION_LIMIT_EXCEEDED")
    requests = report.get("requests")
    if requests is not None and (not isinstance(requests, int) or isinstance(requests, bool) or requests != len(observations) or not 0 <= requests <= 11):
        raise AuditError("PROBE_REQUEST_BOUND_CHANGED")
    if observations and report.get("scope") != {**asset, "manifest_sha256": binding["manifest_canonical_sha256"]}:
        raise AuditError("PROBE_MANIFEST_SCOPE_CHANGED")
    if observations and report.get("timestamp_profile") != {
        "name": "VERIFIED_SDK_NAIVE_ASIA_SHANGHAI", "naive_timezone": "Asia/Shanghai",
        "evidence_sha256": binding["timestamp_evidence_sha256"]}:
        raise AuditError("PROBE_TIMESTAMP_CONTRACT_CHANGED")
    app = report.get("provider_scope_sha256")
    if app is not None and (report.get("provider_scope_kind") != "APP_KEY_SHA256" or not SHA_PATTERN.fullmatch(str(app))):
        raise AuditError("PROBE_PROVIDER_IDENTITY_INVALID")
    discovery = report.get("contract_discovery", {})
    selected = discovery.get("selected_contracts", [])
    if not isinstance(selected, list) or len(selected) > 2:
        raise AuditError("NATIVE_CONTRACT_CAPTURE_BOUND_CHANGED")
    codes = [item.get("symbol") for item in selected]
    if len(codes) != len(set(codes)) or any(not isinstance(code, str) for code in codes):
        raise AuditError("NATIVE_SELECTED_CONTRACT_INVALID")
    try:
        market_date = date.fromisoformat(report["market_date"]) if observations else None
        expiry = date.fromisoformat(discovery["expiry_date"]) if selected else None
    except (KeyError, TypeError, ValueError) as exc:
        raise AuditError("PROBE_CALENDAR_DATE_INVALID") from exc
    if selected and not 3 <= (expiry - market_date).days <= 7:
        raise AuditError("NATIVE_CONTRACT_CALENDAR_DTE_INVALID")
    allowed_requests = {asset["provider_symbol"], *codes}
    covered, failures, stock_rows, option_rows, chain_rows, expiry_dates = [], [], [], [], [], []
    timestamp_count = 0
    quote_response_checks = []
    requested_times = []
    for ordinal, observation in enumerate(observations):
        interface = observation.get("interface")
        if interface not in controller.INTERFACES:
            raise AuditError("NON_QUOTE_INTERFACE_IN_SOURCE")
        scope = observation.get("request_symbols", [])
        if not isinstance(scope, list) or any(symbol not in allowed_requests for symbol in scope):
            raise AuditError("UNRETAINED_OR_UNBOUND_REQUEST_SYMBOL")
        if observation.get("source_kind") != "SDK_OBJECT_FIELDS_NOT_WIRE_RESPONSE":
            raise AuditError("SOURCE_NATIVE_LAYER_CHANGED")
        if observation.get("state") not in {"RETURNED", "PROVIDER_ERROR"}:
            raise AuditError("SOURCE_RETURN_STATE_INVALID")
        requested = aware_iso(observation["requested_at"])
        received = aware_iso(observation["received_at"])
        if received < requested:
            raise AuditError("SOURCE_WALL_ORDER_INVERTED")
        requested_times.append(requested)
        errors = controller.safe_error(observation["error"]) if observation.get("error") else None
        if errors:
            failures.append({"ordinal": ordinal, "interface": interface, **errors})
        covered.append({"ordinal": ordinal, "interface": interface, "state": observation["state"],
            "request_symbols": scope, "requested_at_untrusted_wall": observation["requested_at"],
            "received_at_untrusted_wall": observation["received_at"], "error": errors})
        rows = observation.get("rows", [])
        if not isinstance(rows, list):
            raise AuditError("SOURCE_ROWS_INVALID")
        for row in rows:
            if "timestamp" in row:
                timestamp_count += verify_native_timestamp(row["timestamp"], binding)
        if interface.endswith(".static_info") or interface.endswith(".quote"):
            if any(native(row, "symbol") != asset["provider_symbol"] for row in rows):
                raise AuditError("UNDERLYING_NATIVE_RESPONSE_SCOPE_CHANGED")
        if interface.endswith(".quote"):
            stock_rows += rows
            if observation["state"] == "RETURNED":
                quote_response_checks.append(len(rows) == 1)
        elif interface.endswith(".option_quote"):
            if any(native(row, "symbol") not in codes for row in rows):
                raise AuditError("OPTION_NATIVE_RESPONSE_OUTSIDE_SELECTED_CHAIN")
            option_rows += rows
        elif interface.endswith(".calc_indexes"):
            if any(native(row, "symbol") not in codes for row in rows):
                raise AuditError("CALC_NATIVE_RESPONSE_OUTSIDE_SELECTED_CHAIN")
        elif interface.endswith(".option_chain_expiry_date_list"):
            expiry_dates += observation.get("expiry_dates", [])
        elif interface.endswith(".option_chain_info_by_date"):
            chain_rows += observation.get("selected_native_chain_rows", [])
        elif interface.endswith(".depth"):
            if observation["state"] == "RETURNED" and (
                observation.get("contract_symbol") not in codes
                or observation.get("native_depth_event_timestamp_available") is not False
                or observation.get("raw_volume_not_assumed_contract_count") is not True):
                raise AuditError("DEPTH_SCOPE_OR_EVENT_TIME_POLICY_CHANGED")
    if selected:
        if expiry.isoformat() not in expiry_dates:
            raise AuditError("SELECTED_EXPIRY_ABSENT_FROM_NATIVE_RETURN")
        valid_dates = [date.fromisoformat(value) for value in expiry_dates
                       if 3 <= (date.fromisoformat(value) - market_date).days <= 7]
        if not valid_dates or expiry != min(valid_dates):
            raise AuditError("SELECTED_EXPIRY_IS_NOT_EARLIEST_RETURNED_MATCH")
    contracts = []
    for item in selected:
        code, right = item["symbol"], item.get("right")
        matches = [row for row in option_rows if native(row, "symbol") == code]
        matching_chain = [row for row in chain_rows if native(row, "call_symbol" if right == "CALL" else "put_symbol") == code]
        chain_verified = len(matching_chain) == 1 and native(matching_chain[0], "standard") is True and numeric(native(matching_chain[0], "price")) == numeric(item.get("strike"))
        if not chain_verified:
            raise AuditError("SELECTED_CONTRACT_NOT_BOUND_TO_NATIVE_STANDARD_CHAIN")
        quote = matches[0] if len(matches) == 1 else {}
        identity = bool(quote and native(quote, "underlying_symbol") == asset["provider_symbol"]
            and native(quote, "expiry_date") == expiry.isoformat()
            and numeric(native(quote, "strike_price")) == numeric(item.get("strike"))
            and right in {"CALL", "PUT"}
            and native(quote, "direction") == "OptionDirection." + {"CALL": "Call", "PUT": "Put"}[right])
        depths = [observation for observation in observations if observation["interface"] == "QuoteContext.depth"
                  and observation.get("contract_symbol") == code]
        contract_status = native(quote, "trade_status")
        contracts.append({"symbol": code, "right": right, "strike_raw": item.get("strike"),
            "expiry_date": expiry.isoformat(), "calendar_dte": (expiry - market_date).days,
            "native_standard_chain_flag_verified": True, "native_basic_identity_matches": identity,
            "trade_status_raw": contract_status, "native_trade_status_normal": contract_status == "TradeStatus.Normal",
            "contract_size_raw": native(quote, "contract_size"), "contract_multiplier_raw": native(quote, "contract_multiplier"),
            "option_quote_iv_raw": native(quote, "implied_volatility"),
            "native_last_price_time_utc": quote.get("timestamp", {}).get("utc"),
            "depth_returned": bool(depths),
            "depth_nonempty_both_sides": any(row.get("bids") and row.get("asks") for row in depths),
            "depth_native_event_time_available": False, "bbo_freshness_proven": False,
            "standard_deliverable_qualified": False})
    latest = stock_rows[-1] if stock_rows else {}
    status = native(latest, "trade_status")
    intervals = [(later - earlier).total_seconds() for earlier, later in zip(requested_times, requested_times[1:])]
    return {"source_observations": covered, "provider_errors": failures,
        "native_timestamp_values_revalidated": timestamp_count,
        "asset_specific_request_evidence": any(asset["provider_symbol"] in row["request_symbols"] for row in covered),
        "native_quote_scope_verified": bool(quote_response_checks and all(quote_response_checks)),
        "trade_status_raw": status, "native_trade_status_normal": status == "TradeStatus.Normal",
        "native_last_price_time_utc": latest.get("timestamp", {}).get("utc"),
        "last_done_raw": native(latest, "last_done"), "prev_close_raw": native(latest, "prev_close"),
        "volume_raw": native(latest, "volume"), "turnover_raw": native(latest, "turnover"),
        "minimum_untrusted_wall_request_interval_seconds": min(intervals) if intervals else None,
        "monotonic_request_cadence_directly_recorded": False,
        "monotonic_limit_enforced_by_bound_source": True,
        "provider_scope_sha256": app, "known_requests": requests,
        "market_date_from_untrusted_local_wall": report.get("market_date"),
        "local_market_phase_from_untrusted_local_wall": report.get("local_calendar", {}).get("phase"),
        "probe_status": controller.safe_status(report.get("status"), controller.REPORT_STATUSES, "UNKNOWN_PROBE_STATUS"),
        "discovery_state": discovery.get("state", "NOT_CAPTURED"), "contracts": contracts}


@contextmanager
def readonly_series_lock(directory):
    # The controller owns this byte; never create, append, or overwrite it.
    with (directory / "controller.lock").open("rb") as handle:
        if os.fstat(handle.fileno()).st_size != 1:
            raise AuditError("EXISTING_CONTROLLER_LOCK_INVALID")
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise AuditError("CONTROLLER_STILL_ACTIVE") from exc
        try:
            yield handle
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def source_inventory(source_bytes):
    return sorted(({"path": str(path), "sha256": digest(raw), "bytes": len(raw)}
                  for path, raw in source_bytes.items()), key=lambda row: row["path"])


def root_relative_ref(ref):
    path = Path(ref["path"]).resolve()
    if not path.is_relative_to(ROOT.resolve()):
        raise AuditError("EXPLICIT_SOURCE_REFERENCE_OUTSIDE_ROOT")
    return {"path": path.relative_to(ROOT.resolve()).as_posix(), "sha256": ref["sha256"]}


def audit_snapshot(directory, *, final=False, market_out=controller.MARKET_OUT,
                   binding_provider=controller.bindings):
    directory = directory.resolve()
    with (readonly_series_lock(directory) if final else nullcontext()) as lock_handle:
        binding, assets, skipped = binding_provider()
        source_bytes = {}
        checkpoint = directory / "checkpoint.json"
        state_bytes = checkpoint.read_bytes()
        source_bytes[checkpoint] = state_bytes
        state = json.loads(state_bytes)
        if state.get("schema") != "KQUANT_WATCHLIST_QUOTES_V1" or state.get("binding") != binding or state.get("assets") != assets:
            raise AuditError("SERIES_SCOPE_OR_SOURCE_BINDING_CHANGED")
        for name in binding["original_source_sha256"]:
            path = ROOT / name
            raw = path.read_bytes()
            if digest(raw) != binding["original_source_sha256"][name]:
                raise AuditError("BOUND_SOURCE_HASH_MISMATCH")
            source_bytes[path] = raw
        for path, expected in ((controller.MANIFEST, binding["manifest_bytes_sha256"]),
            (controller.TIMESTAMP, binding["timestamp_evidence_sha256"]),
            (ROOT / "environment/wheels/longbridge-4.4.1-cp312-cp312-win_amd64.whl", binding["sdk_wheel_sha256"])):
            raw = path.read_bytes()
            if expected and digest(raw) != expected:
                raise AuditError("BOUND_ARTIFACT_HASH_MISMATCH")
            source_bytes[path] = raw
        lock_path = directory / "controller.lock"
        if final:
            lock_handle.seek(0)
            source_bytes[lock_path] = lock_handle.read()
        if state.get("request_reservations") != (len(state.get("results", {})) + bool(state.get("in_flight"))) * 11 or state["request_reservations"] > 1100:
            raise AuditError("REQUEST_RESERVATION_LEDGER_INVALID")
        if final and (state.get("in_flight") or len(state.get("results", {})) != 100):
            raise AuditError("FINAL_REQUIRES_100_TERMINAL_ATTEMPTS")
        refs = state.get("results", {})
        if list(refs) != [row["symbol"] for row in assets[:len(refs)]]:
            raise AuditError("ATTEMPTS_ARE_NOT_EXACT_RETAINED_PREFIX")
        if state.get("in_flight") and state["in_flight"].get("asset") != assets[len(refs)]:
            raise AuditError("INFLIGHT_IS_NOT_NEXT_EXACT_RETAINED_ASSET")
        rows, actual_results, used_probes = [], {}, set()
        for asset in assets:
            symbol = asset["symbol"]
            if symbol not in refs:
                rows.append({**asset, "attempt_state": "IN_FLIGHT" if (state.get("in_flight") or {}).get("asset") == asset else "PENDING_NO_QUERY",
                             "eligible": False, "blocking_gates": ["SOURCE_FACTS_NOT_CAPTURED", *AUDIT_BOUNDARY]})
                continue
            result, result_path = checked_ref(refs[symbol], directory / "attempts", source_bytes)
            if result.get("asset") != asset or result.get("eligible") is not False or result.get("production_admission_verified") is not False or result.get("request_reservation") != 11:
                raise AuditError("ASSET_RESULT_SCOPE_OR_GATE_CHANGED")
            actual_results[symbol] = result
            row = {**asset, "attempt_state": "TERMINAL_RECORDED", "transport_status": result.get("transport_status"),
                "attempt_receipt": refs[symbol], "eligible": False, "blocking_gates": result.get("blocking_gates", [])}
            ref = result.get("probe_receipt")
            if ref:
                report, probe_path = checked_ref(ref, market_out, source_bytes)
                if probe_path in used_probes:
                    raise AuditError("ONE_PROBE_REUSED_FOR_MULTIPLE_ASSETS")
                used_probes.add(probe_path)
                inspected = inspect_report(report, asset, binding)
                projection = controller.summarize_report(report, asset, binding)
                if projection != result.get("facts") or projection["blocking_gates"] != row["blocking_gates"]:
                    raise AuditError("ASSET_PROJECTION_MISMATCH")
                row.update(inspected, probe_receipt=ref, projection_equal=True,
                    child_tree_cleanup_confirmed_by_bound_commit_gate=result.get("transport_status") == "CHILD_RETURNED",
                    per_asset_job_active_count_recorded=False)
            else:
                if result.get("facts") is not None:
                    raise AuditError("FACTS_WITHOUT_SOURCE_RECEIPT")
                row.update(known_requests=None, projection_equal=False,
                    child_tree_cleanup_confirmed_by_bound_commit_gate=result.get("transport_status") in {
                        "CHILD_TIMED_OUT", "CHILD_OUTPUT_NOT_STRUCTURED", "CHILD_FAILED", "CHILD_GUARD_OR_TRANSPORT_FAILED"},
                    per_asset_job_active_count_recorded=False)
            rows.append(row)
        for item in skipped:
            rows.append({**item, "attempt_state": "IDENTITY_UNCONFIRMED_NO_QUERY", "eligible": False,
                         "blocking_gates": ["PROVIDER_IDENTITY_NOT_VERIFIED", *AUDIT_BOUNDARY]})
        segments = []
        for path in sorted(directory.glob("*-segment-*.json")):
            report, _ = checked_ref({"path": str(path), "sha256": path.stem.rsplit("-", 1)[-1]}, directory, source_bytes)
            if report.get("binding") != binding or report.get("eligible_assets_proven") != 0 or any(report.get(key) is not False for key in (
                "production_admission_verified", "production_started", "qualified_publication_enabled", "clock_precision_verified", "owner_acceptance_created", "token_values_or_hashes_saved")):
                raise AuditError("SEGMENT_BINDING_OR_GATE_CHANGED")
            subset = report.get("asset_result_refs", {})
            if any(refs.get(symbol) != ref for symbol, ref in subset.items()) or list(subset) != [row["symbol"] for row in assets[:len(subset)]]:
                raise AuditError("SEGMENT_RESULTS_NOT_BOUND_PREFIX")
            if report.get("asset_attempts_terminal") != len(subset):
                raise AuditError("SEGMENT_ASSET_TOTAL_MISMATCH")
            known = sum((actual_results[symbol].get("facts") or {}).get("known_requests") or 0 for symbol in subset)
            if known != report.get("known_requests") or not known <= report.get("maximum_possible_requests_reserved", -1) <= 1100:
                raise AuditError("SEGMENT_REQUEST_TOTAL_MISMATCH")
            segments.append({"path": str(path), "sha256": digest(source_bytes[path]), "status": report.get("status"),
                "asset_attempts_terminal": len(subset), "known_requests": known,
                "maximum_possible_requests_reserved": report["maximum_possible_requests_reserved"],
                "matches_snapshot_terminal_refs": subset == refs})
        if final and not any(row["matches_snapshot_terminal_refs"] and row["status"] == "ALL_100_ASSET_ATTEMPTS_RECORDED" for row in segments):
            raise AuditError("FINAL_100_SEGMENT_RECEIPT_MISSING")
        if final:
            actual_attempt_files = {path.resolve() for path in (directory / "attempts").glob("*.json")}
            if actual_attempt_files != {Path(ref["path"]).resolve() for ref in refs.values()}:
                raise AuditError("FINAL_ATTEMPT_FILES_NOT_EXACT_LEDGER")
        before = source_inventory(source_bytes)
        after = []
        for item in before:
            path = Path(item["path"])
            if final and path == lock_path:
                lock_handle.seek(0); raw = lock_handle.read()
            else:
                raw = path.read_bytes()
            after.append({"path": item["path"], "sha256": digest(raw), "bytes": len(raw)})
        unchanged = before == after
        immutable_unchanged = all(row == after[index] for index, row in enumerate(before) if row["path"] != str(checkpoint))
        if not immutable_unchanged or final and not unchanged or binding_provider()[0] != binding:
            raise AuditError("SOURCE_CHANGED_DURING_AUDIT")
        terminal = [row for row in rows if row["attempt_state"] == "TERMINAL_RECORDED"]
        contract_assets = [row for row in terminal if row.get("contracts")]
        app_hashes = sorted({row["provider_scope_sha256"] for row in terminal if row.get("provider_scope_sha256")})
        if len(app_hashes) > 1 or app_hashes and state.get("provider_scope_sha256") != app_hashes[0]:
            raise AuditError("MULTIPLE_PROVIDER_IDENTITIES_IN_SERIES")
        known = sum(row.get("known_requests") or 0 for row in terminal)
        if known > state["request_reservations"]:
            raise AuditError("KNOWN_REQUESTS_EXCEED_RESERVATIONS")
        return {"record_kind": "INDEPENDENT_OFFLINE_WATCHLIST_QUOTE_SOURCE_AUDIT", "audit_mode": "FINAL" if final else "PARTIAL",
            "status": "FINAL_SOURCE_FACTS_AUDITED_NOT_ELIGIBILITY" if final else "PARTIAL_IMMUTABLE_SOURCE_SNAPSHOT",
            "series_directory": str(directory), "binding": binding, "audit_program_sha256": digest(Path(__file__).read_bytes()),
            "created_at_untrusted_local_wall": datetime.now(timezone.utc).isoformat(),
            "retained_identities": 111, "verified_mapped_identities": 100, "identity_unconfirmed_no_query_count": 11,
            "terminal_attempts": len(terminal), "provider_asset_request_evidence_count": sum(bool(row.get("asset_specific_request_evidence")) for row in terminal),
            "native_quote_scope_verified_count": sum(bool(row.get("native_quote_scope_verified")) for row in terminal),
            "native_underlying_trade_status_counts": dict(Counter(row.get("trade_status_raw") or "NOT_CAPTURED" for row in terminal)),
            "native_underlying_normal_count": sum(bool(row.get("native_trade_status_normal")) for row in terminal),
            "native_underlying_non_normal_assets": [row["symbol"] for row in terminal if row.get("trade_status_raw") and not row.get("native_trade_status_normal")],
            "assets_with_native_3_to_7_day_candidates": len(contract_assets),
            "native_candidate_contract_count": sum(len(row["contracts"]) for row in contract_assets),
            "native_basic_identity_matched_contract_count": sum(bool(item["native_basic_identity_matches"]) for row in contract_assets for item in row["contracts"]),
            "native_standard_chain_verified_contract_count": sum(bool(item["native_standard_chain_flag_verified"]) for row in contract_assets for item in row["contracts"]),
            "assets_without_native_3_to_7_day_candidates": [row["symbol"] for row in terminal if not row.get("contracts")],
            "probe_status_counts": dict(Counter(row.get("probe_status") or row.get("transport_status") for row in terminal)),
            "market_dates_from_untrusted_local_wall": dict(Counter(row.get("market_date_from_untrusted_local_wall") or "NOT_CAPTURED" for row in terminal)),
            "known_requests": known, "maximum_possible_requests_reserved": state["request_reservations"], "series_request_upper_bound": 1100,
            "unknown_outcome_assets": [row["symbol"] for row in terminal if row.get("known_requests") is None],
            "provider_app_identity_hash_count": len(app_hashes), "provider_app_identity_consistent": len(app_hashes) == 1,
            "provider_app_scope_sha256": app_hashes[0] if len(app_hashes) == 1 else None,
            "provider_app_identity_is_opaque_app_key_hash_not_token": True,
            "global_stop": state.get("global_stop"), "snapshot_in_flight_symbol": (state.get("in_flight") or {}).get("asset", {}).get("symbol"),
            "native_timestamp_values_revalidated": sum(row.get("native_timestamp_values_revalidated", 0) for row in terminal),
            "projection_consistency_verified_count": sum(bool(row.get("projection_equal")) for row in terminal),
            "per_asset_native_job_active_count_receipts_available": False,
            "child_tree_cleanup_bound_source_gate_count": sum(bool(row.get("child_tree_cleanup_confirmed_by_bound_commit_gate")) for row in terminal),
            "child_tree_cleanup_evidence_limit": "BOUND_COMMIT_SOURCE_GATE_ONLY_NOT_INDEPENDENT_PER_ASSET_JOB_COUNTER_OBSERVATION",
            "no_fresh_bbo_or_deliverable_eligibility_inferred": True, "eligible_assets_proven": 0,
            "clock_precision_verified": False, "owner_acceptance_created": False, "production_admission_verified": False,
            "market_data_requests_executed_by_audit": 0, "env_file_read_by_audit": False, "source_files_written_by_audit": False,
            "single_trusted_current_market_snapshot_proven": False,
            "source_pre_inventory_sha256": digest(canonical(before)), "source_post_inventory_sha256": digest(canonical(after)),
            "source_checkpoint_pre_sha256": digest(state_bytes), "source_checkpoint_post_sha256": digest(checkpoint.read_bytes()),
            "controller_lock_acquired_readonly": final, "controller_lock_bytes_in_inventory": final,
            "snapshot_all_source_hashes_unchanged": unchanged, "snapshot_immutable_source_hashes_unchanged": immutable_unchanged,
            "source_pre_inventory": before, "source_post_inventory": after, "segments": segments,
            "receipt_files": [root_relative_ref(row["probe_receipt"]) for row in terminal if row.get("probe_receipt")],
            "attempt_receipt_files": [root_relative_ref(row["attempt_receipt"]) for row in terminal],
            "segment_receipt_files": [root_relative_ref(row) for row in segments],
            "assets_without_original_probe_receipt": [row["symbol"] for row in terminal if not row.get("probe_receipt")],
            "assets": rows, "remaining_eligibility_gates": AUDIT_BOUNDARY}


def csv_bytes(audit):
    output = io.StringIO(newline="")
    names = ["symbol", "provider_symbol", "attempt_state", "probe_status", "known_requests", "native_quote_scope_verified",
        "trade_status_raw", "native_trade_status_normal", "native_last_price_time_utc", "last_done_raw", "prev_close_raw",
        "volume_raw", "turnover_raw", "market_date_from_untrusted_local_wall", "discovery_state", "candidate_count",
        "contract_symbols", "calendar_dtes", "native_basic_identity_matches", "native_standard_flags", "option_trade_statuses",
        "contract_sizes_raw", "contract_multipliers_raw", "provider_error_categories", "blocking_gates", "eligible", "probe_receipt_sha256"]
    writer = csv.DictWriter(output, fieldnames=names, lineterminator="\r\n")
    writer.writeheader()
    for row in audit["assets"]:
        record = {key: row.get(key, "") for key in names}
        contracts = row.get("contracts", [])
        record.update(candidate_count=len(contracts), contract_symbols="|".join(item["symbol"] for item in contracts),
            calendar_dtes="|".join(str(item["calendar_dte"]) for item in contracts),
            native_basic_identity_matches="|".join(str(item["native_basic_identity_matches"]) for item in contracts),
            native_standard_flags="|".join(str(item["native_standard_chain_flag_verified"]) for item in contracts),
            option_trade_statuses="|".join(item.get("trade_status_raw") or "NOT_CAPTURED" for item in contracts),
            contract_sizes_raw="|".join(item.get("contract_size_raw") or "NOT_CAPTURED" for item in contracts),
            contract_multipliers_raw="|".join(item.get("contract_multiplier_raw") or "NOT_CAPTURED" for item in contracts),
            provider_error_categories="|".join(sorted({item["error_category"] for item in row.get("provider_errors", [])})),
            blocking_gates="|".join(row["blocking_gates"]), eligible=False,
            probe_receipt_sha256=row.get("probe_receipt", {}).get("sha256", ""))
        writer.writerow(record)
    return output.getvalue().encode("utf-8-sig")


def markdown_bytes(audit, csv_ref):
    mode = "最终" if audit["audit_mode"] == "FINAL" else "进行中快照"
    lines = [f"# 自选行情事实只读审阅（{mode}）", "",
        f"100 个已核验映射中已记录 {audit['terminal_attempts']} 个终态，{audit['provider_asset_request_evidence_count']} 个有实际标的请求证据，{audit['native_quote_scope_verified_count']} 个原生报价身份通过核对。11 个身份未确认项明确未查询。",
        "", f"原生正常交易状态 {audit['native_underlying_normal_count']} 个；状态分布：{json.dumps(audit['native_underlying_trade_status_counts'], ensure_ascii=False)}。",
        "", f"{audit['assets_with_native_3_to_7_day_candidates']} 个标的返回 3–7 个日历日到期的候选，共 {audit['native_candidate_contract_count']} 个合约；{audit['native_standard_chain_verified_contract_count']} 个保留并核对原生 standard=true 链字段，{audit['native_basic_identity_matched_contract_count']} 个原生期权基本身份匹配。",
        "", f"已知请求 {audit['known_requests']} 次；预留上界 {audit['maximum_possible_requests_reserved']} 次，系列总上界 1100。AppKey 不可反推身份哈希种类数 {audit['provider_app_identity_hash_count']}；Token 未读取或保存。",
        "", f"全复验原生时间值 {audit['native_timestamp_values_revalidated']} 个、投影 {audit['projection_consistency_verified_count']} 个；原始不可变来源前后相同：{audit['snapshot_immutable_source_hashes_unchanged']}；包括 checkpoint 的快照前后相同：{audit['snapshot_all_source_hashes_unchanged']}。",
        "", "绑定 controller 源码要求清理 Job 子树成功才 commit；每资产收据没有独立记录 ActiveProcesses=0，所以本审阅只证明源码门禁与收据一致，不能声称逐资产直接观察到了零进程。请求限频同样绑定单调时钟源码，收据墙钟间隔只作为未验证观测。",
        "", "正常状态、standard 标志和 3–7 日候选均为原生事实。可交付合约、原生量单位、绝对时钟、实时 BBO 事件时间与新鲜度等资格仍未证明；股票和期权最新成交时间不能替代 BBO 时间。eligible=0，未创建 OWNER，未发布或启动生产。",
        "", f"CSV：`{csv_ref['path']}`（SHA256 `{csv_ref['sha256']}`）", "",
        f"来源清单 SHA256：前 `{audit['source_pre_inventory_sha256']}`；后 `{audit['source_post_inventory_sha256']}`。", ""]
    return "\n".join(lines).encode("utf-8")


def immutable_output(directory, stem, extension, raw):
    directory.mkdir(parents=True, exist_ok=True)
    value = digest(raw)
    path = directory / f"{stem}-{value}.{extension}"
    with path.open("xb") as handle:
        handle.write(raw); handle.flush(); os.fsync(handle.fileno())
    return {"path": str(path), "sha256": value}


def write_outputs(audit, directory):
    directory = directory.resolve()
    source = Path(audit["series_directory"]).resolve()
    if not directory.is_relative_to(OUTPUT.resolve()) or directory == source or directory.is_relative_to(source) or directory == controller.MARKET_OUT.resolve() or directory.is_relative_to(controller.MARKET_OUT.resolve()):
        raise AuditError("OUTPUT_WOULD_MUTATE_SOURCE_DIRECTORY")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    stem = stamp + "-" + audit["audit_mode"].lower()
    csv_ref = immutable_output(directory, stem + "-assets", "csv", csv_bytes(audit))
    md_ref = immutable_output(directory, stem + "-summary", "md", markdown_bytes(audit, csv_ref))
    audit.update(csv_receipt=csv_ref, markdown_receipt=md_ref)
    return immutable_output(directory, stem + "-audit", "json", canonical(audit))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series-dir", type=Path, default=DEFAULT_SERIES)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--final", action="store_true", help="Acquire existing lock read-only; require all100 terminal attempts")
    args = parser.parse_args()
    try:
        audit = audit_snapshot(args.series_dir, final=args.final)
        receipt = write_outputs(audit, args.output_dir)
        print(json.dumps({"status": audit["status"], "terminal_attempts": audit["terminal_attempts"],
            "known_requests": audit["known_requests"], "assets_with_native_3_to_7_day_candidates": audit["assets_with_native_3_to_7_day_candidates"],
            "receipt": receipt, "csv": audit["csv_receipt"], "markdown": audit["markdown_receipt"],
            "eligible_assets_proven": 0, "production_admission_verified": False}, ensure_ascii=False))
        return 0
    except (AuditError, controller.IntegrityError, OSError, ValueError, TypeError, KeyError):
        print(json.dumps({"status": "SOURCE_AUDIT_FAILED_SAFE_BOUNDARY", "market_data_requests_executed_by_audit": 0,
            "production_admission_verified": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
