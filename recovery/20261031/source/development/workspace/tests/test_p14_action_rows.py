"""Real P13 raw replay and TEST_ONLY contracts; never production approvals."""
from collections import Counter
from copy import deepcopy
from datetime import UTC, date, datetime
import json
import os
from pathlib import Path

import pytest

from kquant import options_one_minute as common
from kquant import options_price_action_rows as rows
from kquant import options_price_action_source as actions
from test_p13_snapshot_coverage import fixture as snapshot_fixture

NOW = datetime(2026, 10, 2, 13, 35, tzinfo=UTC)
RAW_DIR = Path(os.environ.get("P14_ACTION_ROWS_RAW_DIR",
    str(Path.home() / "Desktop/Codex coding/P13-actions-20261013")))
CN_CATEGORY = "\u5206\u914d\u65b9\u6848"
CN_ZONE = "\u7f8e\u4e1c\u65f6\u95f4"
CN_EX = "\u9664\u6743\u65e5"
CN_PAYMENT = "\u6d3e\u606f\u65e5"


def modern_contract():
    return {"version": rows.ROLE_CONTRACT, "type_field": "action",
        "date_zones": [CN_ZONE, "America/New_York", "EST"], "types": {
            "DividendExDate": {"price_changing": True, "native_categories": [CN_CATEGORY, "Distribution Plan"],
                "date_roles": {CN_EX: "EX_DATE", CN_PAYMENT: "PAYMENT_DATE",
                    "\u767b\u8bb0\u65e5": "RECORD_DATE", "\u516c\u544a\u65e5": "ANNOUNCEMENT_DATE",
                    "Payment Date": "PAYMENT_DATE", "Ex Date": "EX_DATE"}},
            "FinancialReport": {"price_changing": False, "native_categories": ["\u4e1a\u7ee9\u62ab\u9732"],
                "date_roles": {"": "REPORT_DATE"}},
            "ReportDate": {"price_changing": False, "native_categories": ["\u9884\u8ba1\u8d22\u62a5\u53d1\u5e03"],
                "date_roles": {"\u8d22\u62a5\u53d1\u5e03\u65e5": "REPORT_DATE"}},
            "StockSplit": {"price_changing": True, "native_categories": ["Split"],
                "date_roles": {"Effective Date": "EFFECTIVE_DATE"}},
            "ReverseSplit": {"price_changing": True, "native_categories": ["Consolidation"],
                "date_roles": {"Effective Date": "EFFECTIVE_DATE"}},
        }}


def native_row(code="DividendExDate", label=CN_EX, day="20261002", identity="TEST_ONLY_1"):
    categories = {"DividendExDate": CN_CATEGORY, "FinancialReport": "\u4e1a\u7ee9\u62ab\u9732",
                  "ReportDate": "\u9884\u8ba1\u8d22\u62a5\u53d1\u5e03",
                  "StockSplit": "Split", "ReverseSplit": "Consolidation"}
    return {"id": identity, "action": code, "act_type": categories.get(code, "Unknown"),
        "date": day, "date_type": label, "date_zone": CN_ZONE, "is_delay": False,
        "act_desc": "TEST_ONLY description is not a field mapping"}


def reviewed_fixture(tmp_path, items):
    proof, observation = snapshot_fixture(tmp_path, items)
    claim = proof["claim"]
    for key in ("known_action_types", "price_changing_action_types", "economic_date_type", "date_zone"):
        claim.pop(key)
    claim["action_date_role_contract"] = modern_contract()
    proof["claim_hash"] = common.digest(claim)
    return proof, observation


@pytest.mark.parametrize("symbol,count", [("FCX", 452), ("NVTS", 24)])
def test_actual_raw_rows_preserved_and_source_review_still_missing(tmp_path, symbol, count):
    path = RAW_DIR / (symbol + "-raw-observation.json")
    observation = json.loads(path.read_text(encoding="utf-8"))
    original = deepcopy(observation)
    parsed = rows.parse_action_rows(observation, source_locator=str(path))
    assert len(parsed) == count == len(observation["raw_response"]["items"])
    assert Counter(row["parse_status"] for row in parsed) == {"PARSED": count}
    required = {"raw_id", "query_symbol", "provider_schema", "action_code", "native_category",
        "date_role", "native_date", "timezone", "timezone_semantics", "economic_effective_date",
        "relevance", "relevance_to_price_scale", "parse_status", "source_locator"}
    assert len({row["source_locator"] for row in parsed}) == count
    for index, (native, parsed_row) in enumerate(zip(observation["raw_response"]["items"], parsed)):
        assert required <= parsed_row.keys()
        assert parsed_row["native_row"] == native
        assert parsed_row["raw_id"] == native["id"]
        assert parsed_row["query_symbol"] == symbol + ".US"
        assert parsed_row["date_type"] == native["date_type"]
        assert parsed_row["native_date"] == native["date"]
        assert parsed_row["timezone"] == native["date_zone"]
        assert parsed_row["source_locator"].endswith("/items/" + str(index))
    now = common.timestamp(observation["received_at"])
    fact = actions.coverage_fact(observation, method=None, now=now, root=tmp_path)
    assert not fact["complete"] and not fact["owner_approval"]
    assert fact["status"] == "INCOMPLETE" and fact["price_scale_state"] == "UNKNOWN"
    assert "COMPANY_ACTION_COVERAGE_METHOD_MISSING" in fact["reasons"]
    assert fact["action_date_role_contract_hash"] is None
    assert len(fact["action_rows"]) == count
    assert observation == original


def test_actual_476_role_distribution_and_same_id_multiple_dates():
    observations = [json.loads((RAW_DIR / (symbol + "-raw-observation.json")).read_text(encoding="utf-8"))
                    for symbol in ("FCX", "NVTS")]
    parsed = [row for observation in observations for row in rows.parse_action_rows(observation)]
    assert len(parsed) == 476
    assert Counter(row["date_role"] for row in parsed) == {
        "EX_DATE": 102, "PAYMENT_DATE": 102, "RECORD_DATE": 102,
        "ANNOUNCEMENT_DATE": 57, "REPORT_DATE": 113}
    assert Counter(row["relevance"] for row in parsed) == {
        "PRICE_SCALE_CHANGE": 102, "CONTEXT_ONLY": 261, "NON_PRICE_SCALE_EVENT": 113}
    dividend = [row for row in parsed if row["query_symbol"] == "FCX.US" and row["raw_id"] == "651398"]
    assert len(dividend) == 4
    assert {row["native_date"] for row in dividend} == {"20261102", "20261015", "20260923"}
    assert [row["economic_effective_date"] for row in dividend if row["date_role"] == "EX_DATE"] == ["2026-10-15"]
    assert all(row["economic_effective_date"] is None for row in dividend if row["date_role"] != "EX_DATE")
    assert all(row["date_type"] == "" and row["date_role"] == "REPORT_DATE"
               for row in parsed if row["action_code"] == "FinancialReport")


def test_observe_attaches_diagnostics_without_coverage_or_native_mutation():
    native = {"data": {"items": [native_row(), native_row()]}}
    original = deepcopy(native)
    observation = actions.observe(native, symbol="TEST", requested_at=NOW, received_at=NOW,
        target_session=date(2026, 10, 2), query={"symbol": "TEST.US"})
    assert native == original == observation["raw_response"]
    assert len(observation["action_rows"]) == 2
    assert observation["action_rows"][0]["source_locator"].endswith("/raw_response/data/items/0")
    assert not observation["complete"] and not observation["owner_approval"]


def test_explicit_mixed_contract_financial_reports_do_not_require_ex_dates(tmp_path):
    items = [native_row("FinancialReport", ""),
             native_row("ReportDate", "\u8d22\u62a5\u53d1\u5e03\u65e5")]
    proof, observation = reviewed_fixture(tmp_path, items)
    fact = actions.coverage_fact(observation, method=proof, now=NOW, root=tmp_path)
    assert fact["complete"] and fact["price_scale_state"] == "UNCHANGED"
    assert not fact["owner_approval"]
    assert fact["action_date_role_contract_hash"] == common.digest(rows.action_row_contract(proof["claim"]))
    assert all(row["date_role"] == "REPORT_DATE" and row["economic_effective_date"] is None
               for row in fact["action_rows"])
    assert actions.valid_fact(fact, symbol="TEST", previous="2026-10-01", session="2026-10-02", now=NOW, root=tmp_path)


@pytest.mark.parametrize("ex_day,expected", [("20260901", "UNCHANGED"), ("20261002", "CHANGED")])
def test_payment_record_and_announcement_are_not_economic_ex_dates(tmp_path, ex_day, expected):
    items = [native_row(label=CN_PAYMENT), native_row(day=ex_day),
        native_row(label="\u767b\u8bb0\u65e5"), native_row(label="\u516c\u544a\u65e5")]
    proof, observation = reviewed_fixture(tmp_path, items)
    original = deepcopy(observation)
    fact = actions.coverage_fact(observation, method=proof, now=NOW, root=tmp_path)
    assert fact["complete"] and fact["price_scale_state"] == expected
    assert len(fact["action_rows"]) == 4 and observation == original
    assert all(row["economic_effective_date"] is None for row in fact["action_rows"] if row["date_role"] != "EX_DATE")


@pytest.mark.parametrize("code", ["StockSplit", "ReverseSplit"])
def test_formally_mapped_split_roles_block_price_comparison(tmp_path, code):
    proof, observation = reviewed_fixture(tmp_path, [native_row(code, "Effective Date")])
    fact = actions.coverage_fact(observation, method=proof, now=NOW, root=tmp_path)
    assert fact["complete"] and fact["price_scale_state"] == "CHANGED"
    assert fact["action_rows"][0]["economic_effective_date"] == "2026-10-02"
    assert not actions.valid_fact(fact, symbol="TEST", previous="2026-10-01", session="2026-10-02", now=NOW, root=tmp_path)
    diagnostic = rows.parse_action_rows(observation)[0]
    assert diagnostic["parse_status"] == "UNRESOLVED"
    assert "ACTION_FIELD_MAPPING_REQUIRES_REVIEW" in diagnostic["parse_reasons"]


@pytest.mark.parametrize("defect", ["unknown_type", "unknown_role", "category", "timezone",
    "invalid_date", "missing_date", "missing_label", "delayed", "missing_delay", "delay_string",
    "nondict", "code_object", "zone_object"])
def test_unresolved_rows_are_retained_and_block_even_outside_snapshot_window(tmp_path, defect):
    native = native_row(day="20200101")
    if defect == "unknown_type": native["action"] = "UnmappedSpinOff"
    elif defect == "unknown_role": native["date_type"] = "unmapped_date"
    elif defect == "category": native["act_type"] = "Other"
    elif defect == "timezone": native["date_zone"] = "unknown"
    elif defect == "invalid_date": native["date"] = "20200230"
    elif defect == "missing_date": native.pop("date")
    elif defect == "missing_label": native.pop("date_type")
    elif defect == "delayed": native["is_delay"] = True
    elif defect == "missing_delay": native.pop("is_delay")
    elif defect == "delay_string": native["is_delay"] = "false"
    elif defect == "nondict": native = ["unrecognized", "row"]
    elif defect == "code_object": native["action"] = {"unexpected": "code"}
    else: native["date_zone"] = {"unexpected": "zone"}
    proof, observation = reviewed_fixture(tmp_path, [native])
    diagnostic = rows.parse_action_rows(observation)
    assert len(diagnostic) == 1 and diagnostic[0]["native_row"] == native
    fact = actions.coverage_fact(observation, method=proof, now=NOW, root=tmp_path)
    assert len(fact["action_rows"]) == 1 and fact["action_rows"][0]["native_row"] == native
    assert fact["action_rows"][0]["parse_status"] == "UNRESOLVED"
    assert not fact["complete"] and fact["price_scale_state"] == "UNKNOWN"


@pytest.mark.parametrize("defect", ["wrong_version", "wrong_type_field", "bad_zones", "unknown_role",
    "payment_as_ex", "report_as_ex", "missing_economic_role", "bad_price_flag", "known_mismatch",
    "changing_mismatch", "empty_contract"])
def test_invalid_explicit_contract_never_falls_back_to_valid_legacy_claim(tmp_path, defect):
    proof, observation = snapshot_fixture(tmp_path)
    contract = modern_contract()
    proof["claim"]["action_date_role_contract"] = contract
    if defect == "wrong_version": contract["version"] = "UNKNOWN"
    elif defect == "wrong_type_field": contract["type_field"] = []
    elif defect == "bad_zones": contract["date_zones"] = []
    elif defect == "unknown_role": contract["types"]["FinancialReport"]["date_roles"][""] = "UNKNOWN"
    elif defect == "payment_as_ex": contract["types"]["DividendExDate"]["date_roles"][CN_PAYMENT] = "EX_DATE"
    elif defect == "report_as_ex":
        contract["types"]["FinancialReport"].update(price_changing=True, date_roles={"": "EX_DATE"})
    elif defect == "missing_economic_role": contract["types"]["DividendExDate"]["date_roles"] = {CN_PAYMENT: "PAYMENT_DATE"}
    elif defect == "bad_price_flag": contract["types"]["StockSplit"]["price_changing"] = "true"
    elif defect == "known_mismatch": proof["claim"]["known_action_types"] = ["wrong"]
    elif defect == "changing_mismatch": proof["claim"]["price_changing_action_types"] = []
    else: proof["claim"]["action_date_role_contract"] = {}
    proof["claim_hash"] = common.digest(proof["claim"])
    assert rows.action_row_contract(proof["claim"]) is None
    fact = actions.coverage_fact(observation, method=proof, now=NOW, root=tmp_path)
    assert not fact["complete"]
    assert "COMPANY_ACTION_COVERAGE_METHOD_MISSING" in fact["reasons"]


def test_role_contract_hash_is_bound_to_fact_and_revalidation(tmp_path):
    proof, observation = reviewed_fixture(tmp_path, [native_row("FinancialReport", "")])
    fact = actions.coverage_fact(observation, method=proof, now=NOW, root=tmp_path)
    contract_hash = common.digest(rows.action_row_contract(proof["claim"]))
    assert fact["action_date_role_contract_hash"] == contract_hash
    fact["action_date_role_contract_hash"] = "forged"
    fact["fact_hash"] = common.digest({key: value for key, value in fact.items() if key != "fact_hash"})
    assert not actions.valid_fact(fact, symbol="TEST", previous="2026-10-01", session="2026-10-02", now=NOW, root=tmp_path)


@pytest.mark.parametrize("defect", ["no_source", "unreviewed_claim", "source_mutation", "claim_hash",
    "no_acceptance", "pagination", "count", "raw_mutation", "query_mutation"])
def test_parsing_does_not_bypass_current_source_and_coverage_gates(tmp_path, defect):
    proof, observation = reviewed_fixture(tmp_path, [native_row("FinancialReport", "")])
    if defect == "no_source": proof = None
    elif defect == "unreviewed_claim": proof = {"claim": proof["claim"]}
    elif defect == "source_mutation": (tmp_path / "action-reply.txt").write_bytes(b"TEST_ONLY changed source")
    elif defect == "claim_hash": proof["claim_hash"] = "wrong"
    elif defect == "no_acceptance": proof.pop("snapshot_method_acceptance")
    elif defect == "pagination":
        observation["raw_response"]["has_more"] = True
        observation["raw_response_sha256"] = common.digest(observation["raw_response"])
    elif defect == "count":
        observation["raw_response"]["total_count"] = 2
        observation["raw_response_sha256"] = common.digest(observation["raw_response"])
    elif defect == "raw_mutation": observation["raw_response"]["items"][0]["date"] = "20261001"
    else: observation["query"]["symbol"] = "WRONG.US"
    fact = actions.coverage_fact(observation, method=proof, now=NOW, root=tmp_path)
    assert len(fact["action_rows"]) == 1
    assert not fact["complete"] and fact["price_scale_state"] == "UNKNOWN"
    assert not fact["owner_approval"]


def test_legacy_claim_stays_compatible_and_payment_cannot_be_legacy_economic_date(tmp_path):
    native = {"act_type": "split", "date_type": "ex_date", "date_zone": "America/New_York", "date": "20261002"}
    proof, observation = snapshot_fixture(tmp_path, [native])
    fact = actions.coverage_fact(observation, method=proof, now=NOW, root=tmp_path)
    assert fact["complete"] and fact["price_scale_state"] == "CHANGED"
    assert rows.action_row_contract(proof["claim"])["legacy"]
    proof["claim"]["economic_date_type"] = "payment_date"
    assert rows.action_row_contract(proof["claim"]) is None


def test_description_does_not_classify_unknown_action_and_cached_rows_are_not_trusted(tmp_path):
    native = native_row("NewProviderType")
    native["act_desc"] = "2:1 stock split effective today"
    native["extra_native_field"] = {"preserved": [1, 2]}
    proof, observation = reviewed_fixture(tmp_path, [native])
    observation["action_rows"] = [{"parse_status": "PARSED", "relevance": "NON_PRICE_SCALE_EVENT"}]
    fact = actions.coverage_fact(observation, method=proof, now=NOW, root=tmp_path)
    assert fact["action_rows"][0]["native_row"] == native
    assert fact["action_rows"][0]["action_code"] == "NewProviderType"
    assert fact["action_rows"][0]["relevance"] == "UNRESOLVED"
    assert not fact["complete"]
