"""Bounded quote-only history probe. Credentials and raw SDK errors are never printed."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT / "development/workspace"
OUT = ROOT / "evidence/minute-history-probe"
PREFIX = "KQUANT_PROBE_REPORT="


def _safe_message(value):
    if not isinstance(value, str):
        return None
    # A huge opaque response is not useful diagnostic text. Never log its prefix.
    if len(value) > 16384:
        return '[OVERSIZE_MESSAGE_OMITTED]'
    for name in ('LONGBRIDGE_APP_KEY', 'LONGBRIDGE_APP_SECRET', 'LONGBRIDGE_ACCESS_TOKEN'):
        secret = os.environ.get(name)
        if secret:
            from urllib.parse import quote
            for form in {secret, quote(secret, safe='')}:
                value = value.replace(form, '[REDACTED]')
    value = re.sub(r'https?://\S+', '[URL_OMITTED]', value, flags=re.I)
    value = re.sub(r'(?im)(authorization|cookie|set-cookie)\s*[:=][^\r\n]*', r'\1=[REDACTED]', value)
    value = re.sub(r'(?i)\bbearer\s+\S+', 'Bearer [REDACTED]', value)
    value = re.sub(r'''(?ix)\b(?:app[_ -]?key|app[_ -]?secret|access[_ -]?token|refresh[_ -]?token|password|secret|token)\s*[:=]\s*(?:"[^"]*"|'[^']*'|[^\s,;]+)''', '[REDACTED_FIELD]', value)
    value = re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[REDACTED]', value)
    value = re.sub(r'[A-Za-z0-9_+/=-]{24,}', '[OPAQUE_VALUE_OMITTED]', value)
    value = ' '.join(value.split())
    return value[:512]


def safe_provider_error(exc, *, stage='UNSPECIFIED'):
    """Keep bounded structured diagnostics; never serialize arbitrary exception repr."""
    raw_code = getattr(exc, "code", None)
    code = int(raw_code) if isinstance(raw_code, int) and not isinstance(raw_code, bool) else None
    message = str(exc).lower()
    if code is None:
        match = re.search(r"\bcode\s*[=:]\s*(\d{3,9})\b", message)
        code = int(match.group(1)) if match else None
    kind = str(getattr(exc, "kind", ""))
    kind = next((x for x in ("Http", "OpenApi", "Other") if x.lower() in kind.lower()), "UNKNOWN")
    known = {301600: "INVALID_REQUEST", 301602: "SERVER_ERROR", 301603: "NO_QUOTES",
             301604: "NO_QUOTE_ACCESS", 301606: "RATE_LIMIT", 301607: "HISTORY_MONTHLY_SYMBOL_QUOTA",
             401: "AUTHENTICATION", 403: "ACCESS_DENIED", 429: "RATE_LIMIT",
             401003: "TOKEN_EXPIRED", 403201: "INVALID_SIGNATURE", 403203: "INVALID_APP_KEY",
             403205: "IP_NOT_ALLOWED", 429001: "RATE_LIMIT", 429002: "RATE_LIMIT"}
    category = known.get(code, "UNCLASSIFIED")
    if category == "UNCLASSIFIED":
        patterns = {"TIMEOUT": ("timeout", "timed out"),
                    "AUTHENTICATION": ("unauthorized", "invalid token", "token expired", "invalid app key", "invalid signature"),
                    "CONNECTION": ("connection", "dns", "tls", "network", "resolve host"),
                    "UNSUPPORTED": ("not supported", "unsupported"),
                    "ACCESS_DENIED": ("permission", "access denied", "not allowed")}
        category = next((name for name, values in patterns.items() if any(v in message for v in values)), category)
    structured = getattr(exc, 'message', None)
    identifiers = {}
    for field in ('request_id', 'trace_id'):
        value = getattr(exc, field, None)
        if value is None and isinstance(structured, str) and len(structured) <= 16384:
            match = re.search(r'\b' + field + r'\s*[:=]\s*([A-Za-z0-9-]{8,64})\b', structured)
            value = match.group(1) if match else None
        if (not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9-]{8,64}', value)
                or any(secret and secret in value for secret in
                       (os.environ.get(key) for key in ('LONGBRIDGE_APP_KEY', 'LONGBRIDGE_APP_SECRET', 'LONGBRIDGE_ACCESS_TOKEN')))):
            value = None
        identifiers[field] = value
    from importlib.metadata import version
    return {"error_type": type(exc).__name__, "provider_error_code": code,
            "provider_error_kind": kind, "error_category": category,
            "provider_message": _safe_message(structured),
            "provider_message_available": isinstance(structured, str),
            "provider_identifiers": identifiers, "sdk_version": version('longbridge'),
            "failure_stage": stage if re.fullmatch(r'[A-Za-z0-9_.]{1,80}', stage) else 'UNSPECIFIED'}


def run_worker(args):
    sys.path.insert(0, str(WORKSPACE))
    from kquant.local_env import load_market_data_env

    credentials = load_market_data_env(path=ROOT / ".env")
    result = {"observed_at":datetime.now(timezone.utc).isoformat(), "market_data_only":True,
              "production_started":False,"old_business_continuity":"UNKNOWN","results":[],"requests":0,
              "credentials_configured": bool(credentials["longbridge_credentials_configured"])}
    if not credentials["longbridge_credentials_configured"]:
        result["status"] = "BLOCKED_CREDENTIALS_MISSING"
        return result
    manifest = json.loads((ROOT / "evidence/retained-watchlist.json").read_text(encoding="utf-8"))
    item = next((x for x in manifest["items"] if x["symbol"] == args.symbol), None)
    if not item or item["identity_status"] != "verified" or not item.get("provider_symbol"):
        result["status"] = "BLOCKED_IDENTITY"
        return result
    if not re.fullmatch(r"[A-Z0-9.-]+\.US", item["provider_symbol"]):
        result["status"] = "BLOCKED_PROVIDER_SYMBOL"
        return result
    from kquant.market_clock import session_bounds_utc
    from longbridge.openapi import Config, QuoteContext, Period, AdjustType, TradeSessions

    context = None
    from minute_rebuild import timestamp_profile
    profile = timestamp_profile(getattr(args, "timestamp_contract", "aware-only"), getattr(args, "timestamp_evidence", None))
    OUT.mkdir(exist_ok=True, parents=True)
    try:
        for session in args.sessions.split(","):
            day = date.fromisoformat(session)
            opening, closing = session_bounds_utc(day)
            if closing > datetime.now(timezone.utc):
                result["status"] = "BLOCKED_SESSION_NOT_CLOSED"
                return result
            if context is None:
                config = Config.from_apikey(os.environ["LONGBRIDGE_APP_KEY"], os.environ["LONGBRIDGE_APP_SECRET"],
                    os.environ["LONGBRIDGE_ACCESS_TOKEN"], enable_print_quote_packages=False)
                context = QuoteContext(config)
            requested = datetime.now(timezone.utc)
            target = OUT / f"{args.symbol}-{session}-{requested.strftime('%Y%m%dT%H%M%S%fZ')}.json"
            result["requests"] += 1
            raw = context.history_candlesticks_by_date(item["provider_symbol"], Period.Min_1, AdjustType.NoAdjust,
                day, day, trade_sessions=TradeSessions.Intraday)
            received = datetime.now(timezone.utc)
            rows, accepted, rejected = [], set(), []
            for candle in raw:
                stamp = candle.timestamp
                raw_stamp = stamp.isoformat() if isinstance(stamp,datetime) else str(stamp)
                if isinstance(stamp,datetime) and stamp.tzinfo is None and profile.get("naive_timezone"):
                    stamp = stamp.replace(tzinfo=ZoneInfo(profile["naive_timezone"])).astimezone(timezone.utc)
                row={"open_at":stamp.isoformat() if isinstance(stamp,datetime) else str(stamp), "raw_timestamp":raw_stamp}
                for field in ("open","high","low","close","volume","turnover"):
                    value=getattr(candle,field,None)
                    row[field]=str(value) if value is not None else None
                rows.append(row)
                reason=None
                if not isinstance(stamp,datetime) or stamp.tzinfo is None: reason="TIMEZONE_MISSING"
                elif not opening <= stamp < closing or stamp.second or stamp.microsecond: reason="OUTSIDE_REGULAR_MINUTE_GRID"
                elif stamp+timedelta(minutes=1)>requested: reason="NOT_CLOSED_AT_REQUEST"
                else:
                    try:
                        prices=[float(row[k]) for k in ("open","high","low","close")]
                        amounts=[float(row[k]) for k in ("volume","turnover")]
                        if not all(math.isfinite(x) and x>0 for x in prices): reason="INVALID_PRICE"
                        elif prices[2]>min(prices[0],prices[3]) or prices[1]<max(prices[0],prices[3]) or prices[2]>prices[1]: reason="INVALID_OHLC"
                        elif not all(math.isfinite(x) and x>=0 for x in amounts): reason="INVALID_NATIVE_VOLUME_OR_TURNOVER"
                        elif stamp in accepted: reason="DUPLICATE_MINUTE"
                        else: accepted.add(stamp)
                    except (ValueError, TypeError, OverflowError):
                        reason="INVALID_NUMERIC_FIELD"
                if reason: rejected.append({"open_at":row["open_at"],"reason":reason})
            expected=int((closing-opening).total_seconds()/60)
            page={"record_kind":"HISTORICAL_REDOWNLOAD_NOT_OLD_BUSINESS_RECOVERY", "symbol":args.symbol,
                  "provider_symbol":item["provider_symbol"],"session":session,"period":"Min_1","adjustment":"NoAdjust",
                  "trade_sessions":"Intraday","requested_at":requested.isoformat(),"received_at":received.isoformat(),
                  "provider_rows":len(rows),"accepted_unique_minutes":len(accepted),"expected_regular_minutes":expected,
                  "missing_minutes":expected-len(accepted),"rejections":rejected,"rows":rows,
                  "native_turnover_preserved":True, "timestamp_contract":profile,
                  "historical_market_page_complete":len(accepted)==expected and not rejected and len(rows)<1000,
                  "production_admission_verified":False,"old_business_continuity":"UNKNOWN"}
            with target.open("x",encoding="utf-8") as f:
                json.dump(page,f,ensure_ascii=False,indent=2)
            result["results"].append({k:v for k,v in page.items() if k not in ("rows","rejections")})
            result["results"][-1]["path"]=str(target)
            result["results"][-1]["sha256"]=hashlib.sha256(target.read_bytes()).hexdigest()
        result["status"]="PROBE_PASSED" if result["results"] and all(
            page["historical_market_page_complete"] for page in result["results"]) else "PROBE_INCOMPLETE"
    except Exception as exc:
        # Classify without exposing arbitrary SDK text, URLs, tokens, or account data.
        result.update(status="PROVIDER_PROBE_FAILED", **safe_provider_error(exc))
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--symbol",default="NVDA")
    parser.add_argument("--sessions",default="2026-10-06,2026-09-09")
    parser.add_argument("--worker",action="store_true")
    parser.add_argument("--timestamp-contract", choices=("aware-only", "verified-naive-asia-shanghai"), default="aware-only")
    parser.add_argument("--timestamp-evidence", type=Path)
    args=parser.parse_args()
    if args.worker:
        print(PREFIX+json.dumps(run_worker(args),ensure_ascii=False))
        return
    OUT.mkdir(exist_ok=True,parents=True)
    try:
        command=[sys.executable,str(Path(__file__).resolve()),"--worker","--symbol",args.symbol,"--sessions",args.sessions,
                 "--timestamp-contract", args.timestamp_contract]
        if args.timestamp_evidence:
            command.extend(["--timestamp-evidence",str(args.timestamp_evidence)])
        completed=subprocess.run(command,
            capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=55)
        payloads=[line[len(PREFIX):] for line in completed.stdout.splitlines() if line.startswith(PREFIX)]
        report=json.loads(payloads[-1]) if payloads else {"status":"WORKER_FAILED","returncode":completed.returncode}
    except subprocess.TimeoutExpired:
        report={"status":"PROBE_TIMED_OUT","timeout_seconds":55,"child_terminated":True}
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    (OUT/f"probe-receipt-{stamp}.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
