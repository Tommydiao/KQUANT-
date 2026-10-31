"""Explain one immutable final audit using its already committed raw pages only.

No source index writes, SDK, network or credentials. Public event interpretations
below are conservative reviewed facts, and never change raw grid denominators.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

import minute_rebuild as rebuild

ROOT = Path(__file__).resolve().parent
QUOTE = ROOT / "evidence/market-readiness/20261007T080541100598Z-73464aaad1bbf1f4a0cf0defc4cf0071e706500a919d439e157a681df5d4658b.json"
NYSE_URL = "https://ir.theice.com/press/news-details/2026/NYSE-to-Commence-Delisting-Proceedings-Against-ESS-Tech-Inc--GWH-f6e4fead4/default.aspx"
SEC_URL = "https://www.sec.gov/Archives/edgar/data/1819438/000181943826000088/esstech-nyselistingstatusu.htm"


def hashed_json(path):
    path = Path(path)
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if not path.name.endswith(sha + ".json"):
        raise ValueError("IMMUTABLE_INPUT_HASH_NAME_CHANGED")
    return json.loads(raw), sha


def row_utc(row, profile):
    stamp = datetime.fromisoformat(row["raw_timestamp"])
    if stamp.tzinfo is None:
        if profile.get("name") != "VERIFIED_SDK_NAIVE_ASIA_SHANGHAI" or not profile.get("evidence_sha256"):
            raise ValueError("UNVERIFIED_RAW_TIMESTAMP")
        stamp = stamp.replace(tzinfo=rebuild.ZoneInfo("Asia/Shanghai"))
    return stamp.astimezone(rebuild.UTC).isoformat()


def expanded_ranges(ranges):
    result = []
    for row in ranges:
        begin = rebuild.aware(row["start_utc"])
        stop = rebuild.aware(row["end_exclusive_utc"])
        if begin + timedelta(minutes=row["minute_count"]) != stop:
            raise ValueError("GAP_RANGE_COUNT_CHANGED")
        result.extend((begin + timedelta(minutes=i)).isoformat() for i in range(row["minute_count"]))
    return result


def build_review(audit_path):
    audit, audit_sha = hashed_json(audit_path)
    if (audit["status"] != "AUDIT_VERIFIED_WITH_GAPS" or not audit["source_unchanged_verified"]
            or audit["projection_mismatches"] or audit["integrity_errors"]):
        raise ValueError("REVIEW_REQUIRES_VERIFIED_IMMUTABLE_RAW_AUDIT")
    source = Path(audit["source_cache"]).resolve()
    if not source.is_relative_to(ROOT.resolve() / "minute-rebuild"):
        raise ValueError("SOURCE_CACHE_OUTSIDE_ISOLATED_REBUILD")
    gaps = [row for row in audit["task_audits"] if row["state"] != "COMPLETE"]
    if not gaps or not all(row["successful_pages"] == 3 for row in gaps):
        raise ValueError("NOT_ALL_INCOMPLETE_TASKS_EXHAUSTED_THREE_SUCCESSFUL_PAGES")
    by_sha = {row["page_sha256"]: row for row in audit["page_audits"]}
    classifications, details, all_invalid_slots = Counter(), [], []
    for task in gaps:
        slots = expanded_ranges(task["missing_ranges"])
        if len(slots) != task["missing_minutes_count"]:
            raise ValueError("GAP_MINUTE_COUNT_CHANGED")
        pages = []
        for sha in task["page_sha256"]:
            page, actual_sha = hashed_json(source / "pages" / (sha + ".json"))
            if (actual_sha != sha or page["task"]["task_id"] != task["task_id"] or page["error"] is not None
                    or not by_sha[sha]["stored_validation_matches_recomputed"]):
                raise ValueError("ORIGINAL_PAGE_BINDING_CHANGED")
            indexed_rows = defaultdict(list)
            rejected = {row["ordinal"]: row["reasons"] for row in page["validation"]["rejected_rows"]}
            for ordinal, row in enumerate(page["rows"]):
                indexed_rows[row_utc(row, audit["timestamp_profile"])].append((ordinal, row, rejected.get(ordinal, [])))
            pages.append((sha, page, indexed_rows))
        record = {key: task[key] for key in ("task_id", "symbol", "provider_symbol", "session", "state",
                   "missing_minutes_count", "missing_ranges", "successful_pages", "page_sha256")}
        if all(not page["rows"] for _, page, _ in pages):
            record["observed_evidence_class"] = "ALL_THREE_SUCCESSFUL_REQUESTS_RETURNED_EMPTY_DAY"
            if task["symbol"] == "GWH" and task["session"] in {"2026-10-05", "2026-10-06"}:
                category = "GWH_POST_SUSPENSION_XNYS_ELIGIBILITY_CHANGE"
                record["interpretation"] = "Primary Oct2 suspension and Oct5 listing update support changed old-XNYS eligibility; no OTC substitution."
                record["interpretation_is_inference"] = True
                record["primary_source_urls"] = [NYSE_URL, SEC_URL]
            else:
                category = "EMPTY_DAY_UPSTREAM_ROOT_CAUSE_UNRESOLVED"
                record["interpretation"] = "Oct2 exact suspension start is not supplied by the primary text; cannot explain all 390 slots."
                record["interpretation_is_inference"] = False
            record["review_class"] = category
            classifications[category] += len(slots)
        else:
            slot_evidence = []
            for stamp in slots:
                present = [(sha, ordinal, raw, reasons) for sha, _, native in pages
                           for ordinal, raw, reasons in native.get(stamp, [])]
                if not present:
                    category = "NATIVE_SLOT_ABSENT_ALL_THREE_PAGES_UPSTREAM_CAUSE_UNKNOWN"
                    item = {"open_at_utc": stamp, "review_class": category, "returned_native_rows": 0,
                            "missing_in_page_sha256": [sha for sha, _, _ in pages]}
                elif all("INVALID_OHLC" in reasons for _, _, _, reasons in present):
                    category = "NATIVE_OHLC_INVALID_REJECTED"
                    occurrences = []
                    for sha, ordinal, raw, reasons in present:
                        values = {key: Decimal(raw[key]) for key in rebuild.FIELDS[:4]}
                        violations = [name for name, failed in (
                            ("OPEN_ABOVE_HIGH", values["open"] > values["high"]),
                            ("CLOSE_ABOVE_HIGH", values["close"] > values["high"]),
                            ("OPEN_BELOW_LOW", values["open"] < values["low"]),
                            ("CLOSE_BELOW_LOW", values["close"] < values["low"])) if failed]
                        occurrences.append({"page_sha256": sha, "ordinal": ordinal, "reasons": reasons,
                                            "ohlc_violations": violations,
                                            "original_native_fields": {key: raw[key] for key in ("raw_timestamp", *rebuild.FIELDS)}})
                    item = {"open_at_utc": stamp, "review_class": category, "upstream_error_cause": "UNKNOWN",
                            "native_occurrences": occurrences}
                    all_invalid_slots.append({"symbol": task["symbol"], "session": task["session"], **item})
                else:
                    raise ValueError("UNCLASSIFIED_GAP_NATIVE_ROWS_REQUIRE_REVIEW")
                classifications[category] += 1
                slot_evidence.append(item)
            record["slot_evidence"] = slot_evidence
            record["observed_evidence_classes"] = dict(Counter(row["review_class"] for row in slot_evidence))
        details.append(record)
    if sum(classifications.values()) != audit["coverage"]["missing_minutes"]:
        raise ValueError("GAP_CLASSIFICATION_TOTAL_DOES_NOT_MATCH_AUDIT")
    quote, quote_sha = hashed_json(QUOTE)
    if quote["diagnostic_scope"]["provider_symbol"] != "GWH.US" or quote["scope"]["manifest_sha256"] != audit["manifest_sha256"]:
        raise ValueError("GWH_QUOTE_SCOPE_NOT_BOUND")
    quote_checks = [{"interface": row["interface"], "received_at_local_wall_utc": row["received_at"],
                     "response_scope_verified": row["response_scope_verified"],
                     "fields": {key: value for key, value in row.get("fields", {}).items()
                                if key in {"symbol", "currency", "exchange", "trade_status", "timestamp", "last_done", "volume", "turnover"}}}
                    for row in quote["diagnostic_response_checks"]]
    return {"record_kind": "FINAL_MINUTE_GAP_REVIEW", "audit_path": str(Path(audit_path).resolve()),
        "audit_sha256": audit_sha, "source_modified": False, "index_modified": False,
        "requests": 0, "sdk_used": False, "credentials_read": False, "production_admission_verified": False,
        "raw_grid_denominator_preserved": audit["coverage"]["theoretical_slots"],
        "accepted_unique_minutes": audit["coverage"]["accepted_unique_minutes"],
        "missing_slots": audit["coverage"]["missing_minutes"], "classification_slot_counts": dict(classifications),
        "incomplete_task_count": len(gaps), "all_incomplete_tasks_three_successful_pages_verified": True,
        "distinct_invalid_ohlc_slots": len(all_invalid_slots),
        "repeated_invalid_ohlc_occurrences": sum(len(row["native_occurrences"]) for row in all_invalid_slots),
        "invalid_ohlc_unique_minutes": all_invalid_slots, "gap_tasks": details,
        "native_gwh_quote": {"receipt_path": str(QUOTE), "receipt_sha256": quote_sha, "checks": quote_checks},
        "reviewed_primary_sources": [
            {"url": NYSE_URL, "date": "2026-10-02", "retrieval": "PRIMARY_WEB_OPEN_AND_SEARCH",
             "supported_fact": "NYSE Regulation announced GWH common-stock immediate suspension and commencement of delisting proceedings.",
             "limitation": "No exact intraday suspension timestamp appears in the read primary announcement."},
            {"url": SEC_URL, "date": "2026-10-05", "retrieval": "PRIMARY_SEC_SEARCH_BODY_DIRECT_OPEN_UNAVAILABLE",
             "supported_fact": "Issuer update says shares may trade OTC as GWHT after the Oct2 immediate NYSE suspension.",
             "limitation": "May trade is not proof of actual OTC minute activity or of a Longbridge replacement identity."}],
        "interpretation_limits": ["Fixed grid remains unchanged; explained eligibility slots are not synthesized bars or complete days.",
            "No zero-volume interpolation, no OHLC repair, no guessed replacement code or OTC/NYSE mixing.",
            "The 41 invalid-OHLC slots prove validator rejection, not the upstream reason prices were inconsistent.",
            "The 18 native slot omissions and GWH Oct2 whole-day emptiness retain unknown upstream causes.",
            "All local receipt timestamps retain the original wall clock; absolute clock precision remains unverified."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    if args.audit.name.startswith(".env"):
        parser.error("Invalid audit path")
    report = build_review(args.audit)
    raw = rebuild.canonical(report)
    sha = hashlib.sha256(raw).hexdigest()
    out = ROOT / "evidence/minute-audits"
    out.mkdir(exist_ok=True)
    path = out / (datetime.now(rebuild.UTC).strftime("%Y%m%dT%H%M%S%fZ-gap-review-") + sha + ".json")
    with path.open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"receipt_path": str(path), "receipt_sha256": sha,
        "classification_slot_counts": report["classification_slot_counts"],
        "distinct_invalid_ohlc_slots": report["distinct_invalid_ohlc_slots"],
        "repeated_invalid_ohlc_occurrences": report["repeated_invalid_ohlc_occurrences"],
        "incomplete_task_count": report["incomplete_task_count"],
        "all_incomplete_tasks_three_successful_pages_verified": True}, ensure_ascii=False, indent=2))


def write_markdown(review_path):
    review, review_sha = hashed_json(review_path)
    audit, _ = hashed_json(review["audit_path"])
    invalid_by_date = defaultdict(list)
    for row in review["invalid_ohlc_unique_minutes"]:
        invalid_by_date[row["session"]].append(row["symbol"])
    omissions = [(task["symbol"], task["session"], row["open_at_utc"])
                 for task in review["gap_tasks"] for row in task.get("slot_evidence", [])
                 if row["review_class"] == "NATIVE_SLOT_ABSENT_ALL_THREE_PAGES_UPSTREAM_CAUSE_UNKNOWN"]
    coverage = audit["coverage"]
    lines = ["# 分钟重建最终独立审计（2026-10-07）", "",
        f"100 个已核验代码 × 20 个闭合 XNYS 交易日（2026-09-09 至 2026-10-06），理论网格 {coverage['theoretical_slots']:,} 个槽位。",
        f"全复验 {audit['source_page_count']:,} 个不可变原页、{sum(row['provider_rows'] for row in audit['page_audits']):,} 行；"
        f"保留 {coverage['accepted_unique_minutes']:,} 个有效唯一分钟，缺口 {coverage['missing_minutes']:,}。",
        "1,939 个标的日期完整，58 个部分、3 个空日；61 个未完整任务均已成功取回三页，当前重取上限已用尽。",
        "0 冲突、0 提供方截断、0 API 错误页、0 孤儿页；原页验证、覆盖投影、身份/额度/权限证明均一致。生产准入未验证，历史重建不等于旧持仓/业务状态恢复。", "",
        "## 缺口分类", "", "| 槽位数 | 已证明观察 / 解释 | 限制 |", "| ---: | --- | --- |",
        "| 41 | 原始 OHLC 违反价格边界，校验拒绝；三个独立返回页共 123 次重复错误 | 上游产生价格矛盾的根因未知 |",
        "| 18 | 三个成功返回页均没有该分钟 | 不能据此判定停牌、无成交或零成交量 |",
        "| 780 | GWH 的 10 月 5、6 日为空；官方停牌与发行人更新支持旧 XNYS 资格变化 | 这是保守事件解释，不是补回 780 根 K 线 |",
        "| 390 | GWH 的 10 月 2 日三次均为空 | 官方文本没有精确停牌时点，不能解释全天 390 个槽位 |", "",
        "原分母 780,000、原缺口 1,229 保留。没有填零、改 OHLC、合成分钟或混入 OTC 行情；11 个身份未确认的原始标签继续保留。", "",
        "## 41 个 OHLC 拒绝槽位", "", "以下均为原生日内首分钟 13:30 UTC（纽约 09:30）；原始价格和逐页 SHA 见缺口收据。", "",
        "| 交易日 | 标的 | 缺口数 |", "| --- | --- | ---: |"]
    if any(rebuild.aware(row["open_at_utc"]).strftime("%H:%M") != "13:30" for row in review["invalid_ohlc_unique_minutes"]):
        raise ValueError("INVALID_OHLC_TIME_SUMMARY_CHANGED")
    for day in sorted(invalid_by_date, reverse=True):
        names = sorted(invalid_by_date[day])
        lines.append(f"| {day} | {', '.join(names)} | {len(names)} |")
    lines.extend(["", "## 18 个原生返回缺席槽位", "", "| 交易日 | 标的 | UTC 分钟 | 纽约分钟 |",
                  "| --- | --- | --- | --- |"])
    for symbol, day, stamp in sorted(omissions, key=lambda item: (item[1], item[0], item[2]), reverse=True):
        utc = rebuild.aware(stamp)
        lines.append(f"| {day} | {symbol} | {utc:%H:%M} | {utc.astimezone(rebuild.ZoneInfo('America/New_York')):%H:%M} |")
    lines.extend(["", "## GWH 的三个空日", "",
        "10 月 2、5、6 日各返回三个成功空页，合计 1,170 个原网格槽位。独立股票快照返回 GWH.US、TradeStatus.CodeMoved，最后价格时间为 2026-10-01T20:00:00Z。",
        f"[NYSE 10 月 2 日官方公告]({NYSE_URL}) 说明立即暂停交易并启动退市程序；[发行人 10 月 5 日 SEC 附件]({SEC_URL}) 说明可能以 GWHT 在 OTC 报价/交易。",
        "这些事实支持后续两个交易日的旧 XNYS 资格变化。官方文字没有精确的 10 月 2 日停牌开始时间；GWHT 的长桥身份与实际 OTC 分钟覆盖也没有验证，不作替代。", "",
        "## 来源未变的证明", "",
        f"- 索引前/后 SHA256：`{audit['source_index_pre_sha256']}`",
        f"- 原页清单前/后 SHA256：`{audit['source_pages_pre_inventory_sha256']}`",
        f"- writer.lock 前/后 SHA256：`{audit['source_lock_pre_sha256']}`",
        "- 全部三项前后完全相同；审计未写缓存、源码或系统设置，没有 API 请求。",
        "- 本机壁钟约 266 秒偏差的独立证据继续适用；原请求/收据时间保留，绝对时钟精度未通过。", "",
        f"[最终全审计收据](<{review['audit_path']}>)，SHA256 `{review['audit_sha256']}`。",
        f"[逐槽缺口与原页 SHA 收据](<{Path(review_path).resolve()}>), SHA256 `{review_sha}`。",
        f"[GWH 原生行情事实](<{review['native_gwh_quote']['receipt_path']}>), SHA256 `{review['native_gwh_quote']['receipt_sha256']}`。", ""])
    raw = "\n".join(lines).encode("utf-8")
    sha = hashlib.sha256(raw).hexdigest()
    path = ROOT / "evidence/minute-audits" / ("MINUTE_DATA_FINAL_AUDIT_20261007-" + sha + ".md")
    with path.open("xb") as stream:
        stream.write(raw)
    return {"report_path": str(path), "report_sha256": sha}


if __name__ == "__main__":
    main()
