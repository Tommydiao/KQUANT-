"""Bounded read-only P3 observations; never activation, publication, or orders.

Credentials must be loaded explicitly by the caller and inherited by the child.
This script does not read .env, construct a TradeContext, or change system time.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time as datetime_time, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

from minute_rebuild import ROOT, WORKSPACE, aware, canonical, clock_functions, timestamp_profile
from probe_minute_history import safe_provider_error

UTC = timezone.utc
PREFIX = "KQUANT_MARKET_READINESS_REPORT="
OUT = ROOT / "evidence/market-readiness"
QUOTE_FIELDS = ("symbol", "last_done", "prev_close", "open", "high", "low", "timestamp",
                "volume", "turnover", "trade_status")
STATIC_FIELDS = ("symbol", "name_en", "exchange", "currency", "lot_size", "stock_derivatives")
OPTION_FIELDS = (*QUOTE_FIELDS, "expiry_date", "strike_price", "contract_multiplier", "contract_type",
                 "contract_size", "direction", "underlying_symbol", "implied_volatility", "open_interest")
CALC_FIELDS = ("symbol", "delta", "gamma", "theta", "vega", "implied_volatility", "expiry_date", "strike_price")
CHAIN_FIELDS = ("price", "call_symbol", "put_symbol", "standard")
DEPTH_FIELDS = ("position", "price", "volume", "order_num")
GLOBAL_ERRORS = {"AUTHENTICATION", "TOKEN_EXPIRED", "INVALID_SIGNATURE", "INVALID_APP_KEY", "IP_NOT_ALLOWED", "ACCESS_DENIED"}


class ProbeStopped(RuntimeError):
    pass


def native_value(value, profile):
    captured = {"native_type": type(value).__module__ + "." + type(value).__name__}
    if value is None:
        captured["raw"] = None
    elif isinstance(value, datetime):
        captured["raw"] = value.isoformat()
        if value.tzinfo is None or value.utcoffset() is None:
            if (profile.get("name") != "VERIFIED_SDK_NAIVE_ASIA_SHANGHAI"
                    or profile.get("naive_timezone") != "Asia/Shanghai"
                    or not profile.get("evidence_sha256")):
                captured["normalization_state"] = "UNVERIFIED_NAIVE_TIMESTAMP"
                return captured
            normalized = value.replace(tzinfo=ZoneInfo("Asia/Shanghai")).astimezone(UTC)
            captured["normalization_state"] = "VERIFIED_SDK_NAIVE_ADAPTER"
        else:
            normalized = value.astimezone(UTC)
            captured["normalization_state"] = "ORIGINAL_AWARE_TIMESTAMP"
        captured["utc"] = normalized.isoformat()
    elif isinstance(value, (date, datetime_time)):
        captured["raw"] = value.isoformat()
    elif isinstance(value, Decimal):
        captured["raw"] = str(value)
        captured["finite"] = value.is_finite()
    elif isinstance(value, bool):
        captured["raw"] = value
    elif isinstance(value, int):
        captured["raw"] = str(value)
    elif isinstance(value, float):
        captured["raw"] = repr(value)
        captured["finite"] = math.isfinite(value)
    elif isinstance(value, str):
        captured["raw"] = value[:256]
        captured["truncated"] = len(value) > 256
    elif isinstance(value, (list, tuple)):
        captured["raw"] = [native_value(item, profile) for item in value[:32]]
        captured["truncated"] = len(value) > 32
    else:
        # Native SDK enum objects only. Arbitrary object repr is never captured.
        module = str(getattr(value, "__module__", type(value).__module__))
        label = str(value) if module.startswith("longbridge") or module == "builtins" else ""
        captured["raw"] = label if re.fullmatch(r"[A-Za-z0-9_ .<>:'()-]{1,128}", label) else None
        captured["unsupported_native_type"] = not bool(captured["raw"])
    return captured


def fields(obj, names, profile):
    return {name: native_value(obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None), profile)
            for name in names}


def attr(obj, name, default=None):
    return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)


def decimal_value(value):
    try:
        result = Decimal(str(value)) if value is not None and not isinstance(value, bool) else None
        return result if result is not None and result.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def select_scope(manifest, symbol):
    matches = [item for item in manifest.get("items", []) if item.get("symbol") == symbol]
    if len(matches) != 1:
        raise ValueError("SYMBOL_NOT_UNIQUE_IN_RETAINED_SCOPE")
    item = matches[0]
    if (item.get("identity_status") != "verified" or not isinstance(item.get("provider_symbol"), str)
            or not re.fullmatch(r"[A-Z0-9.-]+\.US", item["provider_symbol"])):
        raise ValueError("SCOPE_IDENTITY_UNVERIFIED")
    return {"symbol": symbol, "provider_symbol": item["provider_symbol"],
            "manifest_sha256": hashlib.sha256(canonical(manifest)).hexdigest()}


def choose_expiry(expiries, market_day):
    valid = sorted({value for value in expiries if isinstance(value, date) and not isinstance(value, datetime)
                    and 3 <= (value - market_day).days <= 7})
    return valid[0] if valid else None


def choose_chain_contracts(chain, provider_symbol, expiry, spot):
    spot = decimal_value(spot)
    if spot is None or spot <= 0:
        return []
    root = re.escape(provider_symbol.removesuffix(".US"))
    candidates = []
    for index, row in enumerate(chain):
        strike = decimal_value(attr(row, "price"))
        if attr(row, "standard") is not True or strike is None or strike <= 0:
            continue
        contracts = []
        for side, name in (("CALL", "call_symbol"), ("PUT", "put_symbol")):
            native_symbol = attr(row, name)
            pattern = root + expiry.strftime("%y%m%d") + ("C" if side == "CALL" else "P") + r"\d{4,12}\.US"
            if isinstance(native_symbol, str) and re.fullmatch(pattern, native_symbol):
                contracts.append({"symbol": native_symbol, "right": side, "strike": str(strike),
                                  "source_chain_ordinal": index})
        if contracts:
            candidates.append((abs(strike - spot), strike, contracts))
    if not candidates:
        return []
    candidates.sort(key=lambda row: (row[0], row[1]))
    return candidates[0][2][:2]


def native_time_check(captured, received_at, checked_at):
    received, checked = aware(received_at), aware(checked_at)
    if not captured.get("utc"):
        return {"state": captured.get("normalization_state", "TIMESTAMP_MISSING"),
                "timestamp_semantics": "LATEST_PRICE_TIME_NOT_BBO_CONFIRMATION", "fresh_bbo_proven": False}
    provided = aware(captured["utc"])
    return {"state": "PROVIDER_TIME_AFTER_RECEIPT" if provided > received else "ORDERED",
            "native_timestamp_utc": provided.isoformat(),
            "native_last_price_age_seconds": (checked - provided).total_seconds(),
            "local_receipt_age_seconds": (checked - received).total_seconds(),
            "timestamp_semantics": "LATEST_PRICE_TIME_NOT_BBO_CONFIRMATION", "fresh_bbo_proven": False}


def execute_quote_probe(fetch, manifest, symbol, profile, *, diagnostic_symbol=None,
                        include_minute=False,
                        now=lambda: datetime.now(UTC),
                        sleeper=time.sleep, monotonic=time.monotonic, max_requests=12,
                        run_seconds=45):
    if not 1 <= max_requests <= 12 or not 1 <= run_seconds <= 48:
        raise ValueError("PROBE_BUDGET_OUT_OF_BOUNDS")
    scope = select_scope(manifest, symbol)
    diagnostic_scope = select_scope(manifest, diagnostic_symbol) if diagnostic_symbol is not None else None
    if diagnostic_scope and diagnostic_scope["provider_symbol"] == scope["provider_symbol"]:
        raise ValueError("DIAGNOSTIC_SYMBOL_DUPLICATES_PRIMARY")
    stock_symbols = [scope["provider_symbol"]] + ([diagnostic_scope["provider_symbol"]] if diagnostic_scope else [])
    started = monotonic()
    report = {"record_kind": "ISOLATED_READ_ONLY_MARKET_FACTS", "status": "FACTS_CAPTURED",
              "scope": scope, "timestamp_profile": profile, "requests": 0, "observations": [],
              "market_data_only": True, "trade_context_created": False, "orders_enabled": False,
              "production_started": False, "qualified_publication_enabled": False,
              "owner_acceptance_created": False, "system_clock_modified": False,
              "production_admission_verified": False, "clock_precision_verified": False}
    if diagnostic_scope:
        report["diagnostic_scope"] = diagnostic_scope
        report["diagnostic_gap_cause"] = "NOT_DETERMINED_BY_QUOTE_SNAPSHOT"
        report["diagnostic_response_checks"] = []
    last_started = None
    def request(method, *args):
        nonlocal last_started
        if report["requests"] >= max_requests:
            report["status"] = "REQUEST_BUDGET_REACHED"
            raise ProbeStopped()
        delay = max(0.0, 1.0 - (monotonic() - last_started)) if last_started is not None else 0.0
        if monotonic() + delay - started >= run_seconds:
            report["status"] = "RUN_TIME_BUDGET_REACHED"
            raise ProbeStopped()
        if delay:
            sleeper(delay)
        last_started = monotonic()
        requested = aware(now())
        report["requests"] += 1
        observation = {"interface": "QuoteContext." + method, "requested_at": requested.isoformat(),
                       "request_symbols": [value for arg in args for value in
                                           ([arg] if isinstance(arg, str) else arg if isinstance(arg, (list, tuple)) else [])
                                           if isinstance(value, str)],
                       "source_kind": "SDK_OBJECT_FIELDS_NOT_WIRE_RESPONSE"}
        try:
            value = fetch(method, *args)
            observation["received_at"] = aware(now()).isoformat()
            observation["state"] = "RETURNED"
        except Exception as exc:
            observation.update(received_at=aware(now()).isoformat(), state="PROVIDER_ERROR",
                               error=safe_provider_error(exc, stage="QuoteContext." + method))
            report["observations"].append(observation)
            code = observation["error"].get("provider_error_code")
            access_family = isinstance(code, int) and code // 1000 in {401, 403}
            if observation["error"]["error_category"] in GLOBAL_ERRORS or access_family:
                category = observation["error"]["error_category"]
                report["status"] = "BLOCKED_" + ("ACCESS_RESPONSE_UNCLASSIFIED" if category == "UNCLASSIFIED" else category)
                report["contract_discovery"] = {"state": "NOT_EXECUTED_ACCESS_BLOCKED", "selected_contracts": []}
                raise ProbeStopped()
            report["status"] = "STOPPED_PROVIDER_ERROR"
            report["failed_interface"] = observation["interface"]
            report["contract_discovery"] = {
                **report.get("contract_discovery", {}),
                "state": {
                    "option_chain_expiry_date_list": "EXPIRY_QUERY_UNAVAILABLE",
                    "option_chain_info_by_date": "CHAIN_QUERY_UNAVAILABLE",
                }.get(method, "STOPPED_PROVIDER_ERROR"),
                "qualification_verified": False,
            }
            raise ProbeStopped()
        report["observations"].append(observation)
        return value, observation
    def diagnostic_check(rows, observation, *, static=False):
        if not diagnostic_scope:
            return
        matching = [row for row in rows if attr(row, "symbol") == diagnostic_scope["provider_symbol"]]
        check = {"interface": observation["interface"], "requested_at": observation["requested_at"],
                 "received_at": observation["received_at"],
                 "requested_provider_symbol": diagnostic_scope["provider_symbol"],
                 "matching_native_rows": len(matching), "response_scope_verified": len(matching) == 1,
                 "source_observation_ordinal": len(report["observations"]) - 1}
        if len(matching) == 1:
            row = matching[0]
            check["fields"] = fields(row, STATIC_FIELDS if static else QUOTE_FIELDS, profile)
            if not static:
                check["native_time_check"] = native_time_check(native_value(attr(row, "timestamp"), profile),
                                                                observation["received_at"], now())
        report["diagnostic_response_checks"].append(check)
    market_day = aware(now()).astimezone(ZoneInfo("America/New_York")).date()
    report["market_date"] = market_day.isoformat()
    report["calendar_dte_scope"] = [3, 4, 5, 6, 7]
    try:
        is_session, bounds = clock_functions()
        from kquant.market_clock import market_clock
        local_phase = market_clock(aware(now())).session.upper()
        if is_session(market_day):
            opening, closing = bounds(market_day)
            current = aware(now())
            report["local_calendar"] = {"source": "exchange_calendars:XNYS", "opening_utc": opening.isoformat(),
                                         "closing_utc": closing.isoformat(),
                                         "phase": local_phase}
        else:
            report["local_calendar"] = {"source": "exchange_calendars:XNYS", "phase": "NON_SESSION"}
        sessions, observation = request("trading_session")
        if sessions is not None:
            observation["rows"] = [{"market": native_value(attr(row, "market"), profile),
                "trade_sessions": [fields(session, ("begin_time", "end_time", "trade_session"), profile)
                                   for session in attr(row, "trade_sessions", [])[:12]]}
                for row in list(sessions)[:8]]
            observation["native_clock_semantics"] = "CAPTURED_NOT_ASSUMED_EXCHANGE_TIMEZONE"
        days, observation = request("trading_days", market_day, market_day)
        if days is not None:
            observation["fields"] = fields(days, ("trading_days", "half_trading_days"), profile)
        static, observation = request("static_info", stock_symbols)
        if static is not None:
            static = list(static)
            observation["rows"] = [fields(row, STATIC_FIELDS, profile) for row in static[:2]]
            diagnostic_check(static, observation, static=True)
        quotes, observation = request("quote", stock_symbols)
        quote = None
        if quotes is not None:
            quotes = list(quotes)
            observation["rows"] = [fields(row, QUOTE_FIELDS, profile) for row in quotes[:2]]
            diagnostic_check(quotes, observation)
            matching = [row for row in quotes if attr(row, "symbol") == scope["provider_symbol"]]
            quote = matching[0] if len(matching) == 1 else None
            report["underlying_response_scope_verified"] = quote is not None
            if quote is not None:
                report["underlying_time_check"] = native_time_check(native_value(attr(quote, "timestamp"), profile),
                                                                   observation["received_at"], now())
                report["underlying_prices"] = {"last_done": native_value(attr(quote, "last_done"), profile),
                                                "prev_close": native_value(attr(quote, "prev_close"), profile),
                                                "prior_close_price_basis_verified": False}
        if quote is None:
            report["contract_discovery"] = {"state": "UNDERLYING_QUOTE_UNAVAILABLE_OR_SCOPE_MISMATCH",
                                            "selected_contracts": []}
            return report
        if include_minute:
            bars, observation = request('candlesticks', scope['provider_symbol'])
            if bars is None:
                report['contract_discovery'] = {'state': 'MINUTE_QUERY_UNAVAILABLE', 'selected_contracts': []}
                return report
            bars = list(bars)
            observation['rows'] = [fields(row, ('timestamp', 'open', 'high', 'low', 'close',
                'volume', 'turnover', 'trade_session'), profile) for row in bars[:5]]
            observation['requested_period'] = 'Min_1'
            observation['requested_adjustment'] = 'NoAdjust'
            observation['requested_count'] = 5
            observation['closed_bar_verified'] = False
            if not bars:
                report['contract_discovery'] = {'state': 'MINUTE_RESPONSE_EMPTY', 'selected_contracts': []}
                return report
        expiries, observation = request("option_chain_expiry_date_list", scope["provider_symbol"])
        if expiries is None:
            report["contract_discovery"] = {"state": "EXPIRY_QUERY_UNAVAILABLE", "selected_contracts": []}
            return report
        if expiries is not None:
            observation["expiry_dates"] = [value.isoformat() for value in list(expiries)[:128] if isinstance(value, date)]
        expiry = choose_expiry(expiries or [], market_day)
        if expiry is None:
            report["contract_discovery"] = {"state": "NO_MATCHING_RETURNED_CALENDAR_DTE", "selected_contracts": []}
            return report
        chain, observation = request("option_chain_info_by_date", scope["provider_symbol"], expiry)
        if chain is None:
            report["contract_discovery"] = {"state": "CHAIN_QUERY_UNAVAILABLE", "selected_contracts": []}
            return report
        candidates = choose_chain_contracts(chain or [], scope["provider_symbol"], expiry, attr(quote, "last_done"))
        if chain is not None:
            observation["expiry_date"] = expiry.isoformat()
            observation["provider_rows"] = len(chain)
            ordinals = {candidate["source_chain_ordinal"] for candidate in candidates}
            observation["selected_native_chain_rows"] = [fields(chain[index], CHAIN_FIELDS, profile) for index in sorted(ordinals)]
            observation["chain_capture_scope"] = "SELECTED_ROWS_ONLY_NATIVE_RETURNED_CODES"
        report["contract_discovery"] = {"state": "NATIVE_STANDARD_CHAIN_CANDIDATES" if candidates else "NO_BOUND_CHAIN_CANDIDATE",
                                         "expiry_date": expiry.isoformat(), "selected_contracts": candidates,
                                         "standard_deliverable_source_review_verified": False}
        if not candidates:
            return report
        codes = [candidate["symbol"] for candidate in candidates]
        calculations, observation = request("calc_indexes", codes)
        if calculations is not None:
            observation["rows"] = [fields(row, CALC_FIELDS, profile) for row in list(calculations)[:2]]
            report["greeks_local_received_at"] = observation["received_at"]
        option_quotes, observation = request("option_quote", codes)
        if option_quotes is not None:
            observation["rows"] = [fields(row, OPTION_FIELDS, profile) for row in list(option_quotes)[:2]]
            report["option_time_checks"] = [{"symbol": attr(row, "symbol"),
                **native_time_check(native_value(attr(row, "timestamp"), profile), observation["received_at"], now())}
                for row in list(option_quotes)[:2]]
            report["native_option_identity_checks"] = [{"symbol": attr(row, "symbol"),
                "returned_code_was_requested": attr(row, "symbol") in codes,
                "underlying_matches_scope": attr(row, "underlying_symbol") == scope["provider_symbol"],
                "expiry_matches_selected_chain": attr(row, "expiry_date") == expiry,
                "production_admission_verified": False} for row in list(option_quotes)[:2]]
        for candidate in candidates:
            depth, observation = request("depth", candidate["symbol"])
            if depth is not None:
                observation["bids"] = [fields(row, DEPTH_FIELDS, profile) for row in attr(depth, "bids", [])[:3]]
                observation["asks"] = [fields(row, DEPTH_FIELDS, profile) for row in attr(depth, "asks", [])[:3]]
                observation["contract_symbol"] = candidate["symbol"]
                observation["native_depth_event_timestamp_available"] = False
                observation["raw_volume_not_assumed_contract_count"] = True
        # One final underlying quote gives independent end-of-probe receipt age;
        # this does not promote native last-price timestamps into BBO time.
        latest, observation = request("quote", stock_symbols)
        if latest is not None:
            latest = list(latest)
            observation["rows"] = [fields(row, QUOTE_FIELDS, profile) for row in latest[:2]]
            diagnostic_check(latest, observation)
    except ProbeStopped:
        pass
    finally:
        report["completed_at"] = aware(now()).isoformat()
        report["elapsed_seconds"] = round(monotonic() - started, 3)
        if report["status"] == "FACTS_CAPTURED" and any(row.get("error") for row in report["observations"]):
            report["status"] = "FACTS_CAPTURED_WITH_PROVIDER_ERRORS"
        report["remaining_readiness_gates"] = ["ABSOLUTE_CLOCK_BOUND_NOT_ACCEPTED",
            "LIVE_CLOSED_MINUTE_INPUT_NOT_PROBED", "PRIOR_CLOSE_SCALE_NOT_BOUND",
            "CANDLESTICK_AND_DEPTH_UNITS_REQUIRE_REVIEWED_INTERFACE_FACTS",
            "STANDARD_DELIVERABLE_AND_MULTIPLIER_REQUIRE_SOURCE_BOUND_REVIEW",
            "LIVE_BBO_FRESHNESS_NOT_ESTABLISHED", "FINAL_VERSION_HOUR_RUNTIME_NOT_VERIFIED"]
    return report


def run_clock_worker():
    if str(WORKSPACE) not in sys.path:
        sys.path.insert(0, str(WORKSPACE))
    from kquant import options_clock_measurement as clock
    samples = []
    for host in clock.METHOD["servers"]:
        try:
            samples.append(clock.query(host))
        except (OSError, ValueError) as exc:
            samples.append({"server": host, "error_type": type(exc).__name__})
    evaluated = clock.evaluate(samples, proof=None, root=None, now=datetime.now(UTC))
    return {"record_kind": "READ_ONLY_CLOCK_OBSERVATION", "status": evaluated["state"],
            "measurement": evaluated, "clock_precision_verified": False,
            "method_acceptance_supplied": False, "owner_acceptance_created": False,
            "system_clock_modified": False, "production_attachment_published": False,
            "requests": 0, "sdk_connections": 0}


def run_quote_worker(args, manifest, profile):
    # This boundary may be called directly, so validate both scope identities
    # before even importing SDK classes or checking inherited credentials.
    select_scope(manifest, args.symbol)
    diagnostic_symbol = getattr(args, "diagnostic_symbol", None)
    if diagnostic_symbol is not None:
        diagnostic_scope = select_scope(manifest, diagnostic_symbol)
        if diagnostic_scope["provider_symbol"] == select_scope(manifest, args.symbol)["provider_symbol"]:
            raise ValueError("DIAGNOSTIC_SYMBOL_DUPLICATES_PRIMARY")
    keys = ("LONGBRIDGE_APP_KEY", "LONGBRIDGE_APP_SECRET", "LONGBRIDGE_ACCESS_TOKEN")
    if not all(os.environ.get(key) for key in keys):
        return {"status": "BLOCKED_INHERITED_CREDENTIALS_MISSING", "requests": 0}
    from longbridge.openapi import Config, QuoteContext, Market, CalcIndex, Period, AdjustType, TradeSessions
    context = None
    def fetch(method, *arguments):
        nonlocal context
        if context is None:
            context = QuoteContext(Config.from_apikey(*(os.environ[key] for key in keys),
                enable_print_quote_packages=False, enable_papertrading=False))
        if method == "trading_days":
            return context.trading_days(Market.US, *arguments)
        if method == 'candlesticks':
            return context.candlesticks(arguments[0], Period.Min_1, 5, AdjustType.NoAdjust,
                                        TradeSessions.Intraday)
        if method == "calc_indexes":
            indexes = [getattr(CalcIndex, name) for name in ("Delta", "Gamma", "Theta", "Vega", "ImpliedVolatility")]
            return context.calc_indexes(arguments[0], indexes)
        allowed = {"trading_session", "static_info", "quote", "option_chain_expiry_date_list",
                   "option_chain_info_by_date", "option_quote", "depth"}
        if method not in allowed:
            raise ValueError("NON_QUOTE_INTERFACE_REJECTED")
        return getattr(context, method)(*arguments)
    report = execute_quote_probe(fetch, manifest, args.symbol, profile, max_requests=args.max_requests,
                                 run_seconds=args.run_seconds, diagnostic_symbol=diagnostic_symbol,
                                 include_minute=getattr(args, 'include_minute', False))
    report["provider_scope_kind"] = "APP_KEY_SHA256"
    report["provider_scope_sha256"] = hashlib.sha256(os.environ["LONGBRIDGE_APP_KEY"].encode("utf-8")).hexdigest()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("clock-only", "quote-facts"))
    parser.add_argument("--symbol", default="NVDA")
    parser.add_argument("--diagnostic-symbol", help="One additional exact retained identity for native stock facts only")
    parser.add_argument('--include-minute', action='store_true', help='Check five native 1m bars after quote before chain discovery')
    parser.add_argument("--manifest", type=Path, default=ROOT / "evidence/retained-watchlist.json")
    parser.add_argument("--timestamp-contract", choices=("aware-only", "verified-naive-asia-shanghai"), default="aware-only")
    parser.add_argument("--timestamp-evidence", type=Path)
    parser.add_argument("--max-requests", type=int, default=12)
    parser.add_argument("--run-seconds", type=float, default=45)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.max_requests <= 12 or not 1 <= args.run_seconds <= 48:
        parser.error("Quote probe permits <=12 requests and <=48 seconds of work")
    if args.manifest.name.startswith(".env"):
        parser.error("Invalid manifest path")
    if args.diagnostic_symbol is not None and args.mode != "quote-facts":
        parser.error("A diagnostic symbol requires quote-facts mode")
    if args.include_minute and args.mode != 'quote-facts':
        parser.error('Minute check requires quote-facts mode')
    profile, manifest = timestamp_profile(), None
    if args.mode == "quote-facts":
        profile = timestamp_profile(args.timestamp_contract, args.timestamp_evidence)
        manifest = json.loads(args.manifest.read_bytes())
        select_scope(manifest, args.symbol)
        if args.diagnostic_symbol is not None:
            diagnostic_scope = select_scope(manifest, args.diagnostic_symbol)
            if diagnostic_scope["provider_symbol"] == select_scope(manifest, args.symbol)["provider_symbol"]:
                parser.error("Diagnostic symbol must differ from primary symbol")
    if args.worker:
        try:
            report = run_clock_worker() if args.mode == "clock-only" else run_quote_worker(args, manifest, profile)
        except Exception as exc:
            report = {"status": "PROBE_WORKER_FAILED", **safe_provider_error(exc, stage="WORKER_SETUP"), "requests": None}
        print(PREFIX + json.dumps(report, ensure_ascii=False))
        return
    timeout = 6 if args.mode == "clock-only" else 55
    arguments = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--worker"]
    try:
        child = subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        payloads = [line[len(PREFIX):] for line in child.stdout.splitlines() if line.startswith(PREFIX)]
        report = json.loads(payloads[-1]) if payloads else {"status": "PROBE_WORKER_FAILED", "returncode": child.returncode, "requests": None}
    except subprocess.TimeoutExpired:
        report = {"status": "CLOCK_MEASUREMENT_TIMED_OUT" if args.mode == "clock-only" else "QUOTE_PROBE_TIMED_OUT",
                  "timeout_seconds": timeout, "child_terminated": True, "requests": None}
    report.update(observed_at=datetime.now(UTC).isoformat(), mode=args.mode,
                  trade_context_created=False, orders_enabled=False, system_clock_modified=False,
                  owner_acceptance_created=False, production_admission_verified=False)
    expected = ROOT.resolve() / "evidence/market-readiness"
    if OUT.resolve() != expected:
        raise ValueError("OUTPUT_ALIAS_OUTSIDE_ISOLATED_EVIDENCE")
    OUT.mkdir(parents=True, exist_ok=True)
    raw = canonical(report)
    sha = hashlib.sha256(raw).hexdigest()
    target = OUT / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + sha + ".json")
    with target.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"status": report["status"], "requests": report.get("requests"),
                      "receipt_path": str(target), "receipt_sha256": sha,
                      "market_phase": report.get("local_calendar", {}).get("phase"),
                      "contract_discovery": report.get("contract_discovery"),
                      "clock_precision_verified": False, "production_admission_verified": False},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
