"""Export retained minute observations and measure reference coverage, without promotion."""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import csv
import hashlib
import json
import math
import sqlite3

import exchange_calendars as xcals

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "evidence"
DAY = date(2026, 10, 7)


def main():
    manifest = json.loads((OUT / "retained-watchlist.json").read_text(encoding="utf-8"))
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(DAY - timedelta(days=60), DAY - timedelta(days=1))[-20:]
    expected = {}
    for session in sessions:
        start, end = calendar.session_open(session).to_pydatetime(), calendar.session_close(session).to_pydatetime()
        expected[session.date().isoformat()] = {start + timedelta(minutes=i) for i in range(int((end-start).total_seconds()/60))}
    source = ROOT / "inspection-data/work/kquant_us.sqlite3"
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = [dict(r) for r in db.execute("SELECT * FROM market_candles WHERE interval='1m' ORDER BY symbol,open_time")]
    retained = OUT / "retained-minute-observations.jsonl"
    exported = "".join(json.dumps({"record_kind":"RETAINED_REFERENCE_NOT_LIVE_ADMISSION", "origin_table":"market_candles", **row}, ensure_ascii=False) + "\n" for row in rows)
    if retained.exists():
        if retained.read_text(encoding="utf-8") != exported:
            raise ValueError("Retained export differs; preserve prior evidence")
    else:
        with retained.open("x", encoding="utf-8") as stream:
            stream.write(exported)
    coverage, rejected = defaultdict(set), Counter()
    for row in rows:
        reason = None
        try:
            opened = datetime.fromisoformat(row["open_time"])
            fetched = datetime.fromisoformat(row["fetched_at"])
            if opened.tzinfo is None or fetched.tzinfo is None:
                raise ValueError("Timezone required")
            opened, fetched = opened.astimezone(timezone.utc), fetched.astimezone(timezone.utc)
            prices = [float(row[k]) for k in ("open", "high", "low", "close")]
            if row["bar_state"] != "closed_candle": reason = "FORMING_CANDLE"
            elif row["adjustment_mode"] != "unadjusted": reason = "ADJUSTMENT_MISMATCH"
            elif row["primary_source"] != "longbridge_candles": reason = "SOURCE_MISMATCH"
            elif not all(math.isfinite(x) and x > 0 for x in prices): reason = "INVALID_PRICE"
            elif prices[2] > min(prices[0], prices[3]) or prices[1] < max(prices[0], prices[3]) or prices[2] > prices[1]: reason = "INVALID_OHLC"
            elif fetched < opened + timedelta(minutes=1): reason = "RECEIVED_BEFORE_CLOSE"
            else:
                matched = next((d for d, slots in expected.items() if opened in slots), None)
                if matched: coverage[row["symbol"], matched].add(opened)
                else: reason = "OUTSIDE_TARGET_REGULAR_SESSIONS"
        except (TypeError, ValueError, KeyError):
            reason = "MALFORMED_RECORD"
        if reason: rejected[reason] += 1
    matrix = []
    for item in manifest["items"]:
        for day, slots in expected.items():
            mapped = item["identity_status"] == "verified" and bool(item.get("provider_symbol"))
            count = len(coverage[item["symbol"], day])
            matrix.append({"symbol":item["symbol"], "provider_symbol":item.get("provider_symbol"), "identity_status":item["identity_status"], "session":day,
                "expected_regular_minutes":len(slots) if mapped else None, "retained_reference_minutes":count,
                "missing_reference_minutes":len(slots)-count if mapped else None, "live_admission_verified":False})
    with (OUT / "minute-reference-gap-matrix.csv").open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(matrix[0]));writer.writeheader();writer.writerows(matrix)
    summary={"as_of_session":DAY.isoformat(), "watchlist_source_session":"2026-10-02", "watchlist_requires_current_recheck":True,
        "watchlist_symbols":len(manifest["items"]), "identity_counts":dict(Counter(x["identity_status"] for x in manifest["items"])),
        "target_sessions":list(expected), "retained_raw_rows":len(rows), "retained_symbols":dict(Counter(x["symbol"] for x in rows)),
        "raw_bar_states":dict(Counter(x["bar_state"] for x in rows)), "reference_exclusions":dict(rejected),
        "retained_regular_reference_slots_all_symbols":sum(len(v) for v in coverage.values()),
        "retained_regular_reference_slots_in_verified_watchlist":sum(x["retained_reference_minutes"] for x in matrix if x["expected_regular_minutes"] is not None),
        "expected_verified_symbol_slots":sum(x["expected_regular_minutes"] or 0 for x in matrix),
        "missing_reference_slots":sum(x["missing_reference_minutes"] or 0 for x in matrix),
        "export_sha256":hashlib.sha256(retained.read_bytes()).hexdigest(), "full_old_minute_database_recovered":False,
        "live_admission_verified":False, "business_records_reconstructed":False,
        "notes":["References retain original fetched/first-seen timestamps; they are not newly observed live bars.",
                 "5-minute bars are not decomposed into fabricated 1-minute bars.",
                 "Market history cannot reconstruct old positions, events, tasks, or historical option quotes."]}
    (OUT / "minute-recovery-inventory.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
