"""Bind a read-only source review to already captured SDK observations.

This script is entirely offline. It imports neither the SDK nor any project
service; only the new evidence directory receives files.
"""
from __future__ import annotations

import ast
import base64
import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "evidence/quote-source-review"
COMMIT = "bc33287274d69a4617ab7a78167625e44ad83eb2"
QUOTE_SHA = "73464aaad1bbf1f4a0cf0defc4cf0071e706500a919d439e157a681df5d4658b"
AUDIT_SHA = "2bf68ba161b03909b830e0417d5aea1e0557e8e72c81ce9bc5c545437f81d627"
PAGE_SHA = "7593c980be521667f8f4c053d81849ae0694b09350590abfe61fbfc3269be778"
WHEEL_SHA = "ddde921d9c6a7b90567218bd666fccb59530904fd2381559e6be8440fdf384de"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def input_file(path: Path, expected: str | None = None) -> tuple[dict, bytes]:
    data = path.read_bytes()
    digest = sha(data)
    if expected and digest != expected:
        raise ValueError(f"Input hash mismatch: {path.name}")
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest}, data


def immutable(stem: str, suffix: str, data: bytes) -> dict:
    digest = sha(data)
    path = OUT / f"{stem}-{digest}{suffix}"
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Immutable evidence collision")
    else:
        with path.open("xb") as handle:
            handle.write(data)
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": digest}


def raw(row: dict, field: str):
    return row[field]["raw"]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    quote_ref, quote_bytes = input_file(
        ROOT / "evidence/market-readiness" / f"20261007T080541100598Z-{QUOTE_SHA}.json", QUOTE_SHA
    )
    quote = json.loads(quote_bytes)
    audit_ref, audit_bytes = input_file(
        ROOT / "evidence/minute-audits" / f"20261007T081016463042Z-{AUDIT_SHA}.json", AUDIT_SHA
    )
    audit = json.loads(audit_bytes)
    page_ref, page_bytes = input_file(
        ROOT / "minute-rebuild/native-20261007-v1/pages" / f"{PAGE_SHA}.json", PAGE_SHA
    )
    page = json.loads(page_bytes)
    if page["task"]["provider_symbol"] != "NVDA.US" or page["task"]["session"] != "2026-10-06":
        raise ValueError("Minute example is outside the selected verified scope")
    if not any(p["page_sha256"] == PAGE_SHA for p in audit["page_audits"]):
        raise ValueError("Minute example is not bound by the final independent audit")
    timestamp_path = ROOT / "evidence/sdk-timestamp-contract-20261007T071652086437Z.json"
    timestamp_ref, _ = input_file(timestamp_path, quote["timestamp_profile"]["evidence_sha256"])
    wheel = ROOT / "environment/wheels/longbridge-4.4.1-cp312-cp312-win_amd64.whl"
    wheel_ref, wheel_bytes = input_file(wheel, WHEEL_SHA)
    installed = ROOT / ".venv/Lib/site-packages"
    matches = []
    with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as archive:
        record = list(csv.reader(io.StringIO(archive.read("longbridge-4.4.1.dist-info/RECORD").decode())))
        expected_record = {r[0]: r[1:] for r in record}
        for entry in ["longbridge/__init__.py", "longbridge/openapi.pyi", "longbridge/openapi.py",
                      "longbridge/longbridge.cp312-win_amd64.pyd", "longbridge-4.4.1.dist-info/METADATA"]:
            wheel_entry = archive.read(entry)
            actual = (installed / entry).read_bytes()
            if actual != wheel_entry:
                raise ValueError(f"Installed wheel entry differs: {entry}")
            encoded = base64.urlsafe_b64encode(hashlib.sha256(wheel_entry).digest()).rstrip(b"=").decode()
            encoded_expected, size_expected = expected_record[entry]
            if encoded_expected != "sha256=" + encoded or int(size_expected) != len(wheel_entry):
                raise ValueError("Wheel RECORD check failed")
            matches.append({"entry": entry, "sha256": sha(actual), "bytes": len(actual),
                            "installed_matches_preserved_wheel": True, "wheel_record_verified": True})

    stub_ref, stub_bytes = input_file(installed / "longbridge/openapi.pyi")
    tree = ast.parse(stub_bytes.decode("utf-8"))
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    shapes = {}
    for name in ["SecurityQuote", "OptionQuote", "SecurityDepth", "PushDepth", "Depth", "Candlestick",
                 "StrikePriceInfo", "SecurityCalcIndex"]:
        cls = classes[name]
        shapes[name] = {"stub_start_line": cls.lineno, "fields": {
            field.target.id: {"annotation": ast.unparse(field.annotation), "stub_line": field.lineno}
            for field in cls.body if isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name)}}
    signatures = {}
    for node in classes["QuoteContext"].body:
        if isinstance(node, ast.FunctionDef) and node.name in {
            "quote", "option_quote", "depth", "calc_indexes", "option_chain_info_by_date",
            "history_candlesticks_by_date"}:
            signatures[node.name] = {"stub_line": node.lineno,
                                      "signature": ast.unparse(node).split(":\n", 1)[0]}
    for name in ["SecurityDepth", "PushDepth", "SecurityCalcIndex"]:
        if "timestamp" in shapes[name]["fields"]:
            raise ValueError("Review premise changed: timestamp field exists")

    sources = []
    source_text = {}
    for name in ["Cargo.toml", "python/Cargo.toml", "python/src/time.rs", "python/src/decimal.rs",
                 "python/src/quote/types.rs", "python/src/quote/context.rs", "rust/src/quote/types.rs"]:
        suffix = Path(name).suffix
        stem = name.replace("/", "_").removesuffix(suffix)
        candidates = list(OUT.glob(stem + "-*" + suffix))
        if len(candidates) != 1:
            raise ValueError(f"Source snapshot not unique: {name}")
        ref, data = input_file(candidates[0])
        if not candidates[0].stem.endswith(ref["sha256"]):
            raise ValueError("Source snapshot name/hash mismatch")
        sources.append({**ref, "source_path": name,
                        "url": f"https://github.com/longbridge/openapi/blob/{COMMIT}/{name}"})
        source_text[name] = data.decode("utf-8")
    if 'version = "4.4.1"' not in source_text["Cargo.toml"]:
        raise ValueError("Tagged source version mismatch")
    expected_markers = {
        "python/src/time.rs": ["PyDateTime::from_timestamp(py, self.0.unix_timestamp() as f64, None)"],
        "python/src/decimal.rs": [".call1(py, (self.0.to_string(),))"],
        "rust/src/quote/types.rs": ["volume: depth.volume,", "volume: quote.volume,",
                                   "volume: value.volume,", "standard: value.standard,",
                                   "implied_volatility: option_extend.implied_volatility.parse().unwrap_or_default(),",
                                   "output.implied_volatility = resp.implied_volatility.parse().ok()"],
    }
    anchors = {}
    for name, markers in expected_markers.items():
        lines = source_text[name].splitlines()
        anchors[name] = {}
        for marker in markers:
            locations = [i + 1 for i, line in enumerate(lines) if marker in line]
            if not locations:
                raise ValueError("Source interpretation marker missing")
            anchors[name][marker] = locations

    obs = quote["observations"]
    if len(obs) != 11 or quote["mode"] != "quote-facts":
        raise ValueError("Quote receipt scope changed")
    static = {raw(row, "symbol"): row for row in obs[2]["rows"]}
    spot = {raw(row, "symbol"): row for row in obs[3]["rows"]}
    options = {raw(row, "symbol"): row for row in obs[7]["rows"]}
    indexes = {raw(row, "symbol"): row for row in obs[6]["rows"]}
    chain = obs[5]["selected_native_chain_rows"]
    if len(chain) != 1 or raw(chain[0], "standard") is not True:
        raise ValueError("Selected chain standard flag mismatch")
    symbols = [item["symbol"] for item in quote["contract_discovery"]["selected_contracts"]]
    if set(options) != set(symbols) or set(indexes) != set(symbols):
        raise ValueError("Option/index native scope mismatch")
    if {raw(chain[0], "call_symbol"), raw(chain[0], "put_symbol")} != set(symbols):
        raise ValueError("Selected chain codes mismatch")

    native_options = []
    for symbol in symbols:
        row, calc = options[symbol], indexes[symbol]
        if raw(row, "underlying_symbol") != "NVDA.US" or raw(row, "contract_multiplier") != "100":
            raise ValueError("Option identity or multiplier mismatch")
        if raw(row, "contract_size") != "100" or raw(row, "expiry_date") != "2026-10-12":
            raise ValueError("Option size or expiry mismatch")
        unit_price_mean = Decimal(raw(row, "turnover")) / Decimal(raw(row, "volume")) / Decimal("100")
        within_range = Decimal(raw(row, "low")) <= unit_price_mean <= Decimal(raw(row, "high"))
        native_options.append({"symbol": symbol, "native_option_fields": row,
                               "native_calc_fields": calc,
                               "calc_iv_percent_points_documented": raw(calc, "implied_volatility"),
                               "calc_iv_ratio_if_using_documented_unit": str(Decimal(raw(calc, "implied_volatility")) / 100),
                               "option_quote_iv_raw_unscaled": raw(row, "implied_volatility"),
                               "separate_requests_not_same_snapshot": True,
                               "numerical_consistency_only": {
                                   "turnover_div_volume_div_100": str(unit_price_mean),
                                   "inside_native_daily_low_high": within_range,
                                   "proves_volume_unit": False, "proves_currency_unit": False}})

    docs = [
        {"id": "quote", "url": "https://open.longbridge.com/zh-CN/docs/quote/pull/quote",
         "reviewed_section": "Response Properties",
         "finding": "timestamp describes latest execution time; volume/turnover named but units unspecified."},
        {"id": "historical", "url": "https://open.longbridge.com/docs/quote/pull/history-candlestick",
         "reviewed_section": "Response Properties; date query range",
         "finding": "volume int64 and turnover string; numeric units unspecified; date request cap 1000."},
        {"id": "option_quote", "url": "https://open.longbridge.com/docs/quote/pull/option-quote",
         "reviewed_section": "Response Properties; example",
         "finding": "Distinct contract size/multiplier fields; IV examples are fractional, without explicit unit contract."},
        {"id": "chain", "url": "https://open.longbridge.com/docs/quote/pull/optionchain-date-strike",
         "reviewed_section": "Response Properties",
         "finding": "standard is a bool; detailed deliverable and corporate action semantics not supplied."},
        {"id": "calc", "url": "https://open.longbridge.com/zh-CN/docs/quote/pull/calc-index",
         "reviewed_section": "Response Properties",
         "finding": "IV is percentage data without percent sign; Vega raw is per 1.0 IV change; /100 yields per percentage point."},
        {"id": "depth_pull", "url": "https://open.longbridge.com/docs/quote/pull/depth",
         "reviewed_section": "Response Properties; protobuf",
         "finding": "Volume and order count differ; snapshot schema has no event timestamp and no specific volume unit."},
        {"id": "depth_push", "url": "https://open.longbridge.com/docs/quote/push/depth",
         "reviewed_section": "Data Format; protobuf",
         "finding": "Wire sequence is a sequence number, not documented event time; no timestamp in schema."},
    ]
    facts = [
        {"id": "stock_and_candlestick_units", "verified": ["Native SDK volume is int; turnover is Decimal.",
            "Pinned source passes volume and parses turnover without lot/currency scaling.",
            "NVDA static currency USD and lot_size 1 were captured."],
         "not_verified": ["Explicit provider field-specific shares-versus-lots unit contract.",
            "Explicit turnover currency/subunit/coverage convention.",
            "Actual wire strings before SDK parsing; numeric parser can default malformed strings to zero."],
         "admission_state": "UNITS_REMAIN_UNVERIFIED", "docs": ["quote", "historical"],
         "allowed_use": "Preserve raw int/Decimal strings with interface and symbol; no guessed conversion."},
        {"id": "option_contract_identity", "verified": ["Selected actual chain standard=True, size=100, multiplier=100.",
            "Two returned codes match selected native CALL/PUT, NVDA underlying, strike240 and expiry2026-10-12."],
         "not_verified": ["Exact deliverable/corporate-action and settlement eligibility for these two contracts.",
            "Equivalence of contract_size and contract_multiplier meanings for other option classes."],
         "admission_state": "NATIVE_STANDARD_CANDIDATES_ONLY", "docs": ["option_quote", "chain"]},
        {"id": "iv_interface_scale", "verified": ["Current Chinese calc-index documentation specifies percentage points.",
            "Receipt raw calc IV22.77/23.61; ratio conversion is0.2277/0.2361.",
            "SDK source preserves both IV fields without division; raw option IV0.228/0.236."],
         "not_verified": ["Explicit option_quote fractional-unit contract beyond examples and numerical agreement.",
            "Simultaneous or event-timestamped option quote/calc snapshots."],
         "admission_state": "CALC_PERCENT_UNIT_DOCUMENTED_OPTION_RATIO_INFERRED", "docs": ["calc", "option_quote"],
         "allowed_use": "Keep interface-tagged raw IV. Apply /100 only to calc IV after accepted adapter contract."},
        {"id": "depth_volume_and_time", "verified": ["Native volume int, order_num separate int, price Optional Decimal.",
            "Installed SecurityDepth/PushDepth shapes lack event time; quote timestamp is latest execution time.",
            "Two observed top prices/volumes exist; receipt local time records capture only."],
         "not_verified": ["Volume unit as contracts versus underlying shares/lots.",
            "Exchange/source event time, dissemination latency or 3-second BBO freshness."],
         "admission_state": "BBO_FRESHNESS_AND_SIZE_UNIT_UNVERIFIED", "docs": ["depth_pull", "depth_push", "quote"],
         "forbidden_inferences": ["Use last trade time as BBO time.", "Treat wire sequence as epoch time.",
                                  "Convert depth volume using option multiplier by analogy."]},
        {"id": "time_and_current_market_eligibility", "verified": ["Bound390-row installed SDK timestamp contract remains independent empirical evidence.",
            "v4.4.1 Python output conversion corroborates host-local naive datetime behavior."],
         "not_verified": ["Precision clock gate; host remained approximately266 seconds fast.",
            "Current session main quote freshness; extended-session quote fields were not captured.",
            "OWNER source/method acceptance and qualified market eligibility."],
         "admission_state": "NOT_PRODUCTION_ADMITTED", "docs": ["quote"]},
    ]
    source_scope = {
        "tag": "v4.4.1", "resolved_ref_commit": COMMIT,
        "ref_resolution_method": "Read-only git ls-remote https://github.com/longbridge/openapi.git refs/tags/v4.4.1*",
        "manifest_version": "4.4.1", "snapshots": sources, "interpretation_anchors": anchors,
        "source_to_preserved_wheel_reproducible_build_verified": False,
        "source_to_binary_attestation_verified": False,
        "older_timestamp_review_commit": "f6e9f7d04ca58c09e64957b12ddc6aaf184afa8b",
        "older_commit_manifest_version": "5.2.0",
        "older_source_corroboration_is_not_wheel_4_4_1_proof": True,
        "line_number_scope": "Anchors use unmodified UTF-8 source snapshot line numbers; browser-rendered text can collapse blank lines.",
    }
    spot_mean = Decimal(raw(spot["NVDA.US"], "turnover")) / Decimal(raw(spot["NVDA.US"], "volume"))
    minute_sample = page["rows"][0]
    review = {
        "record_kind": "QUOTE_BOUND_OFFLINE_OFFICIAL_SOURCE_REVIEW",
        "review_date_local_wall": datetime.now(timezone.utc).isoformat(),
        "wall_clock_precision_verified": False,
        "clock_skew_diagnostic_unchanged": "Existing read-only diagnosis found host approx266sec fast; this review performed no new measurement or adjustment.",
        "quote_receipt": quote_ref, "final_minute_audit": audit_ref,
        "historical_example_page": page_ref, "empirical_timestamp_contract": timestamp_ref,
        "sdk": {"name": "longbridge", "version": "4.4.1", "preserved_wheel": wheel_ref,
                "exact_installed_file_matches": matches, "installed_stub": stub_ref,
                "field_shapes": shapes, "function_signatures": signatures,
                "imported_by_reviewer": False, "release_binary_signature_verified": False},
        "official_source": source_scope, "official_docs": docs,
        "documentation_scope": "Current main documentation reviewed2026-10-07; it is not an old-wheel exact-build proof.",
        "native_scope": {"primary": quote["scope"], "diagnostic": quote["diagnostic_scope"],
                         "manifest_sha256": quote["scope"]["manifest_sha256"],
                         "capture_kind": "SDK_OBJECT_FIELDS_NOT_WIRE_RESPONSE"},
        "native_stock": {"static": static["NVDA.US"], "quote": spot["NVDA.US"],
                         "consistency_only_turnover_div_volume": str(spot_mean), "units_proven_by_arithmetic": False},
        "native_historical_example": {"task": page["task"], "first_row": minute_sample,
                                      "raw_int_decimal_strings_unscaled": True,
                                      "unit_proof_available": False},
        "native_selected_chain": chain, "native_options": native_options,
        "native_depth": [obs[8], obs[9]], "facts": facts,
        "remaining_gate_dependencies": [
            "Field-specific provider volume/turnover units and conversion rules accepted in SOURCE_METHOD evidence.",
            "Explicit IV adapters per interface, preserving raw values and non-simultaneous snapshot provenance.",
            "Contract-specific deliverable/settlement eligibility with native symbols and dated authoritative evidence.",
            "Trusted clock measurement under already fixed METHOD and accepted OWNER evidence.",
            "A source method able to establish native BBO event time or an explicitly accepted substitute freshness contract.",
            "A later bounded quote-only current-session check with extended-hours/native context and no production publication.",
        ],
        "network_used_for_source_docs_only": True, "market_api_requests_by_reviewer": 0,
        "env_file_read": False, "sdk_imported": False, "system_settings_modified": False,
        "workspace_frozen_candidate_modified": False, "original_cache_modified": False,
        "owner_acceptance_created": False, "production_admission_verified": False,
        "production_started": False, "qualified_publication_enabled": False,
    }
    # The review does not touch index/pages. Check all read evidence again before committing.
    for path, original in [(ROOT / quote_ref["path"], quote_bytes), (ROOT / audit_ref["path"], audit_bytes),
                           (ROOT / page_ref["path"], page_bytes)]:
        if path.read_bytes() != original:
            raise ValueError("Input changed while reviewing")
    json_bytes = (json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    result = immutable(stamp + "-source-review", ".json", json_bytes)
    print(json.dumps({"review": result, "status": "READ_ONLY_SOURCE_REVIEW_COMPLETE",
                      "production_admission_verified": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
