"""Lossless company-action row diagnostics, independent of coverage authority."""
from copy import deepcopy
from datetime import datetime
import re

PARSER = "COMPANY_ACTION_ROWS_V1"
ROLE_CONTRACT = "ACTION_DATE_ROLE_CONTRACT_V1"
ROLES = {"EX_DATE", "PAYMENT_DATE", "RECORD_DATE", "ANNOUNCEMENT_DATE",
         "REPORT_DATE", "EFFECTIVE_DATE"}
ECONOMIC_ROLES = {"EX_DATE", "EFFECTIVE_DATE"}
DATE_LABELS = {
    "ex_date": "EX_DATE", "Ex Date": "EX_DATE", "Ex-Dividend Date": "EX_DATE",
    "\u9664\u6743\u65e5": "EX_DATE", "\u9664\u6b0a\u65e5": "EX_DATE",
    "Payment Date": "PAYMENT_DATE", "payment_date": "PAYMENT_DATE",
    "\u6d3e\u606f\u65e5": "PAYMENT_DATE",
    "Record Date": "RECORD_DATE", "record_date": "RECORD_DATE",
    "\u767b\u8bb0\u65e5": "RECORD_DATE", "\u767b\u8a18\u65e5": "RECORD_DATE",
    "Announcement Date": "ANNOUNCEMENT_DATE", "announcement_date": "ANNOUNCEMENT_DATE",
    "\u516c\u544a\u65e5": "ANNOUNCEMENT_DATE",
    "Report Date": "REPORT_DATE", "report_date": "REPORT_DATE",
    "\u8d22\u62a5\u53d1\u5e03\u65e5": "REPORT_DATE", "\u8ca1\u5831\u767c\u5e03\u65e5": "REPORT_DATE",
    "Effective": "EFFECTIVE_DATE", "Effective Date": "EFFECTIVE_DATE",
    "effective_date": "EFFECTIVE_DATE",
}
DIAGNOSTIC_TYPES = {
    "DividendExDate": True, "FinancialReport": False, "ReportDate": False,
    "Split": True, "StockSplit": True, "ReverseSplit": True,
}
DIAGNOSTIC_ZONES = {"\u7f8e\u4e1c\u65f6\u95f4", "\u7f8e\u6771\u6642\u9593",
                    "America/New_York", "EST", "ET"}


def action_row_contract(claim):
    """Validate an explicit per-type contract, or expand the legacy claim exactly.

    This validates structure and internal consistency, not source review. A bad
    explicit contract must never fall back to legacy or diagnostic assumptions.
    """
    if not isinstance(claim, dict):
        return None
    if "action_date_role_contract" in claim:
        value = claim["action_date_role_contract"]
        if (not isinstance(value, dict) or value.get("version") != ROLE_CONTRACT
                or not isinstance(value.get("type_field"), str)
                or value["type_field"] != "action"
                or not _strings(value.get("date_zones"))
                or not isinstance(value.get("types"), dict) or not value["types"]):
            return None
        for kind, spec in value["types"].items():
            if (not isinstance(kind, str) or not kind or not isinstance(spec, dict)
                    or type(spec.get("price_changing")) is not bool
                    or not _strings(spec.get("native_categories"))
                    or not isinstance(spec.get("date_roles"), dict) or not spec["date_roles"]):
                return None
            for label, role in spec["date_roles"].items():
                if (not isinstance(label, str) or not isinstance(role, str) or role not in ROLES
                        or (label in DATE_LABELS and DATE_LABELS[label] != role)
                        or (role in ECONOMIC_ROLES and not spec["price_changing"])):
                    return None
            if spec["price_changing"] and not ECONOMIC_ROLES.intersection(spec["date_roles"].values()):
                return None
            if value["type_field"] == "action":
                roles = set(spec["date_roles"].values())
                if (kind in {"FinancialReport", "ReportDate"}
                        and (spec["price_changing"] or roles != {"REPORT_DATE"})):
                    return None
                if (kind == "DividendExDate" and (not spec["price_changing"]
                        or not roles <= {"EX_DATE", "PAYMENT_DATE", "RECORD_DATE", "ANNOUNCEMENT_DATE"})):
                    return None
        known = claim.get("known_action_types")
        changing = claim.get("price_changing_action_types")
        if known is not None and (not _strings(known) or set(known) != set(value["types"])):
            return None
        expected = {kind for kind, spec in value["types"].items() if spec["price_changing"]}
        if changing is not None and (not _strings(changing, empty=True) or set(changing) != expected):
            return None
        return deepcopy(value)
    known, changing = claim.get("known_action_types"), claim.get("price_changing_action_types")
    label, zone = claim.get("economic_date_type"), claim.get("date_zone")
    if (not _strings(known) or not _strings(changing) or not set(changing) <= set(known)
            or not isinstance(label, str) or not label or not isinstance(zone, str) or not zone
            or DATE_LABELS.get(label) in {"PAYMENT_DATE", "RECORD_DATE", "ANNOUNCEMENT_DATE", "REPORT_DATE"}):
        return None
    return {"version": ROLE_CONTRACT, "type_field": "act_type", "date_zones": [zone],
            "legacy": True, "types": {kind: {"price_changing": kind in changing,
                "native_categories": [kind], "date_roles": {label: DATE_LABELS.get(label, "EFFECTIVE_DATE")}}
                for kind in known}}


def _strings(value, *, empty=False):
    return (isinstance(value, list) and (empty or bool(value))
            and all(isinstance(item, str) and item for item in value)
            and len(value) == len(set(value)))


def parse_action_rows(observation, *, claim=None, source_locator=None):
    """One output per input row; IDs are not keys and native dates stay native.

    Without a claim, known labels/codes provide diagnostics only. With a claim,
    every type, category, date role and zone must match that explicit contract.
    Neither path establishes completeness, source authority, or OWNER approval.
    """
    response = observation.get("raw_response")
    wrapped = isinstance(response, dict) and "data" in response
    body = response.get("data") if wrapped else response
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list):
        return []
    contract = action_row_contract(claim) if claim is not None else None
    query = observation.get("query")
    query_symbol = query.get("symbol") if isinstance(query, dict) else None
    prefix = source_locator or observation.get("source_locator") or (
        "sha256:" + str(observation.get("raw_response_sha256", "UNCONFIRMED")))
    pointer = "/raw_response/data/items/" if wrapped else "/raw_response/items/"
    result = []
    for index, native in enumerate(items):
        row = native if isinstance(native, dict) else {}
        issues, role, changing = [], "UNKNOWN", None
        label, code = row.get("date_type"), row.get("action")
        if not isinstance(native, dict):
            issues.append("ROW_SCHEMA_UNCONFIRMED")
        if claim is not None:
            if contract is None:
                issues.append("TYPE_DATE_ROLE_CONTRACT_UNCONFIRMED")
            else:
                kind = row.get(contract["type_field"])
                spec = contract["types"].get(kind) if isinstance(kind, str) else None
                if spec is None:
                    issues.append("UNKNOWN_ACTION_TYPE")
                else:
                    changing = spec["price_changing"]
                    if row.get("act_type") not in spec["native_categories"]:
                        issues.append("NATIVE_CATEGORY_UNCONFIRMED")
                    role = spec["date_roles"].get(label, "UNKNOWN") if isinstance(label, str) else "UNKNOWN"
                if row.get("date_zone") not in contract["date_zones"]:
                    issues.append("TIMEZONE_UNCONFIRMED")
        else:
            changing = DIAGNOSTIC_TYPES.get(code) if isinstance(code, str) else None
            if changing is None:
                issues.append("UNKNOWN_ACTION_TYPE")
            elif code in {"Split", "StockSplit", "ReverseSplit"}:
                issues.append("ACTION_FIELD_MAPPING_REQUIRES_REVIEW")
            role = DATE_LABELS.get(label, "UNKNOWN") if isinstance(label, str) else "UNKNOWN"
            if code == "FinancialReport" and label == "":
                role = "REPORT_DATE"
            if not isinstance(row.get("date_zone"), str) or row["date_zone"] not in DIAGNOSTIC_ZONES:
                issues.append("TIMEZONE_UNCONFIRMED")
            if (isinstance(code, str) and code in {"FinancialReport", "ReportDate"} and role != "REPORT_DATE"
                    or code == "DividendExDate" and role not in {
                        "EX_DATE", "PAYMENT_DATE", "RECORD_DATE", "ANNOUNCEMENT_DATE"}):
                issues.append("ACTION_DATE_ROLE_CONFLICT")
        if role == "UNKNOWN":
            issues.append("UNKNOWN_DATE_ROLE")
        day = None
        native_date = row.get("date")
        if isinstance(native_date, str) and re.fullmatch(r"[0-9]{8}", native_date):
            try:
                day = datetime.strptime(native_date, "%Y%m%d").date().isoformat()
            except ValueError:
                pass
        if day is None:
            issues.append("NATIVE_DATE_UNINTERPRETABLE")
        if row.get("is_delay") is not False:
            # Legacy rows historically allowed the optional delay field to be absent.
            if not (contract and contract.get("legacy") and "is_delay" not in row):
                issues.append("DELAY_STATUS_UNCONFIRMED")
        relevance = ("UNRESOLVED" if issues else "PRICE_SCALE_CHANGE"
                     if changing and role in ECONOMIC_ROLES else "CONTEXT_ONLY"
                     if changing else "NON_PRICE_SCALE_EVENT")
        result.append({"raw_id": deepcopy(row.get("id")), "query_symbol": query_symbol,
            "provider_schema": "LONGBRIDGE_COMPANY_ACT_ITEMS_V3",
            "action_code": deepcopy(code), "native_category": deepcopy(row.get("act_type")),
            "date_role": role, "native_date": deepcopy(native_date),
            "date_type": deepcopy(label), "timezone": deepcopy(row.get("date_zone")),
            "timezone_semantics": "NATIVE_LOCAL_DATE_NO_UTC_INSTANT",
            "economic_effective_date": day if relevance == "PRICE_SCALE_CHANGE" else None,
            "event_date": day, "relevance": relevance, "relevance_to_price_scale": relevance,
            "parse_status": "UNRESOLVED" if issues else "PARSED",
            "parse_reasons": sorted(set(issues)), "source_locator": str(prefix) + "#" + pointer + str(index),
            "semantic_basis": "EXPLICIT_CONTRACT" if contract else "LOCAL_DIAGNOSTIC_ONLY",
            "native_row": deepcopy(native)})
    return result
