from __future__ import annotations

import json
import html as html_lib
import os
import random
import re
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from .stock_signals import api_stock_candles, average_true_range_pct, ema_last, iso_now, pct
from .stock_store import default_db_path

MSTR_SYMBOL = "MSTR"
BTC_SYMBOL = "BTC-USD"
USER_AGENT = "kquant-local-research/0.2"
MSTR_JOURNAL_STATUSES = {"reviewed", "wait", "staged-watch", "invalidated"}
MSTR_SCHEMA = """
CREATE TABLE IF NOT EXISTS mstr_cycle_runs (
    run_id TEXT PRIMARY KEY,
    completed_at TEXT NOT NULL,
    level TEXT NOT NULL,
    bottom_score REAL NOT NULL,
    distribution_risk_score REAL NOT NULL,
    bayesian_bottom_probability REAL NOT NULL,
    bayesian_confidence REAL NOT NULL,
    premium_to_btc_nav REAL,
    ev_to_btc_nav REAL,
    mstr_btc_momentum_4w_pct REAL,
    mc_24m_probability_2x REAL,
    mc_24m_probability_5x REAL,
    mc_24m_probability_10x REAL,
    provider_status TEXT NOT NULL,
    blocker_count INTEGER NOT NULL,
    blockers_json TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mstr_cycle_runs_completed_at
ON mstr_cycle_runs(completed_at DESC);

CREATE TABLE IF NOT EXISTS mstr_cycle_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL DEFAULT '',
    reviewed_at TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT '',
    bottom_score REAL NOT NULL DEFAULT 0,
    bayesian_bottom_probability REAL NOT NULL DEFAULT 0,
    manual_checklist_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_mstr_cycle_journal_reviewed_at
ON mstr_cycle_journal(reviewed_at DESC);
"""


def api_mstr_cycle_radar(
    db_path: Path | None = None,
    outputs_dir: Path | None = None,
    source: str = "live",
) -> dict[str, Any]:
    if source != "live":
        raise ValueError("MSTR Cycle Radar is live-only; fixture data is not exposed.")
    db = db_path or default_db_path()
    outputs = outputs_dir or Path("outputs")
    started = iso_now()

    mstr_daily = api_stock_candles(MSTR_SYMBOL, "1y", "1d", "live", db)
    mstr_weekly = api_stock_candles(MSTR_SYMBOL, "5y", "1wk", "live", db)
    mstr_monthly = api_stock_candles(MSTR_SYMBOL, "10y", "1mo", "live", db)
    btc_daily = api_stock_candles(BTC_SYMBOL, "1y", "1d", "live", db)
    btc_weekly = api_stock_candles(BTC_SYMBOL, "5y", "1wk", "live", db)
    btc_monthly = api_stock_candles(BTC_SYMBOL, "10y", "1mo", "live", db)
    relative_weekly = ratio_payload(MSTR_SYMBOL, BTC_SYMBOL, mstr_weekly, btc_weekly)

    quote = yahoo_quote_snapshot(MSTR_SYMBOL)
    holdings = strategy_btc_holdings_snapshot()
    quote = enrich_quote_from_chart(quote, mstr_daily)
    btc_close = latest_close(btc_daily) or latest_close(btc_weekly)
    premium = premium_proxy(quote, holdings, btc_close)

    btc_cycle = btc_cycle_component(btc_weekly, btc_monthly)
    mstr_bottom = mstr_bottom_component(mstr_weekly, mstr_daily)
    relative = relative_btc_component(relative_weekly)
    financing = financing_component(quote, holdings, premium)
    strategy_tracker_metrics = strategy_tracker_metrics_component(
        quote=quote,
        holdings=holdings,
        btc_daily=btc_daily,
        mstr_daily=mstr_daily,
        premium=premium,
        financing=financing,
    )
    distribution = distribution_risk_component(btc_cycle, mstr_bottom, relative, premium)
    monte_carlo = monte_carlo_component(mstr_weekly, btc_weekly, relative_weekly, premium)
    bayesian_bottom = bayesian_bottom_component(btc_cycle, mstr_bottom, relative, premium, financing, distribution)

    provider_errors = collect_provider_errors(
        {
            "mstr_daily": mstr_daily,
            "mstr_weekly": mstr_weekly,
            "mstr_monthly": mstr_monthly,
            "btc_daily": btc_daily,
            "btc_weekly": btc_weekly,
            "btc_monthly": btc_monthly,
        }
    )
    provider_clean = not provider_errors
    bottom_score = round(
        btc_cycle["score"] * 0.3
        + mstr_bottom["score"] * 0.35
        + relative["score"] * 0.2
        + premium["score"] * 0.1
        + financing["score"] * 0.05,
        1,
    )
    distribution_score = distribution["score"]
    level = cycle_level(
        bottom_score=bottom_score,
        distribution_score=distribution_score,
        provider_clean=provider_clean,
        premium_available=premium["status"] == "available",
        financing_available=financing["status"] == "available",
        btc_candles=bool(btc_weekly.get("candles")),
        mstr_candles=bool(mstr_weekly.get("candles")),
    )
    reasons = level_reasons(level, btc_cycle, mstr_bottom, relative, premium, financing, distribution)
    blockers = level_blockers(level, provider_errors, premium, financing, distribution)
    cycle_dashboard = cycle_dashboard_component(
        level=level,
        bottom_score=bottom_score,
        distribution_score=distribution_score,
        provider_clean=provider_clean,
        btc_cycle=btc_cycle,
        mstr_bottom=mstr_bottom,
        relative=relative,
        premium=premium,
        financing=financing,
        monte_carlo=monte_carlo,
        bayesian_bottom=bayesian_bottom,
    )
    trigger_monitor = trigger_monitor_component(
        level=level,
        bottom_score=bottom_score,
        distribution_score=distribution_score,
        provider_clean=provider_clean,
        btc_cycle=btc_cycle,
        mstr_bottom=mstr_bottom,
        relative=relative,
        premium=premium,
        financing=financing,
    )
    path_stress_test = path_stress_test_component(cycle_dashboard.get("ten_x_path", {}), premium)
    completed = iso_now()
    payload = {
        "run_id": f"mstr-cycle-{int(time.time() * 1000)}",
        "product": "KQUANT MSTR Cycle Bottom Radar",
        "source": "live",
        "started_at": started,
        "completed_at": completed,
        "symbol": MSTR_SYMBOL,
        "btc_reference_symbol": BTC_SYMBOL,
        "level": level,
        "bottom_score": bottom_score,
        "distribution_risk_score": distribution_score,
        "provider_status": "available" if provider_clean else "degraded",
        "provider_error_count": len(provider_errors),
        "provider_errors": provider_errors[:30],
        "live_only_policy": "MSTR and BTC reference data use live Yahoo public chart or stale real cache only",
        "btc_reference_only": True,
        "fixture_user_visible": False,
        "llm_signal_core_enabled": False,
        "broker_order_wiring_enabled": False,
        "levels": ["CYCLE ACCUMULATION", "BOTTOM WATCH", "WAIT", "DISTRIBUTION RISK"],
        "positioning_note": "Research reminder only. No full-position buy signal; use staged review such as 20-30% left-side watch and add only after confirmation.",
        "components": {
            "btc_cycle": btc_cycle,
            "mstr_bottom": mstr_bottom,
            "relative_btc": relative,
            "premium_proxy": premium,
            "financing_risk": financing,
            "distribution_risk": distribution,
        },
        "strategy_tracker_metrics": strategy_tracker_metrics,
        "treasury_snapshot": strategy_tracker_metrics["treasury_snapshot"],
        "premium_nav_metrics": strategy_tracker_metrics["premium_nav_metrics"],
        "cost_basis_metrics": strategy_tracker_metrics["cost_basis_metrics"],
        "btc_yield_metrics": strategy_tracker_metrics["btc_yield_metrics"],
        "share_metrics": strategy_tracker_metrics["share_metrics"],
        "debt_financing_metrics": strategy_tracker_metrics["debt_financing_metrics"],
        "liquidity_metrics": strategy_tracker_metrics["liquidity_metrics"],
        "benchmark_metrics": strategy_tracker_metrics["benchmark_metrics"],
        "tracker_provider_status": strategy_tracker_metrics["tracker_provider_status"],
        "monte_carlo": monte_carlo,
        "bayesian_bottom": bayesian_bottom,
        "cycle_dashboard": cycle_dashboard,
        "trigger_monitor": trigger_monitor,
        "path_stress_test": path_stress_test,
        "scenario_horizon": ["6m", "12m", "24m"],
        "model_limitations": [
            "Monte Carlo is a deterministic historical bootstrap, not a price forecast.",
            "Bayesian probability is an interpretable evidence score, not a trained model.",
            "10x probability is a scenario statistic, not a promise or recommendation.",
            "Missing premium, financing, BTC, or MSTR data disables high-confidence interpretation.",
        ],
        "reasons": reasons,
        "blockers": blockers,
        "manual_checklist": [
            "Confirm BTC weekly/monthly trend is no longer in uncontrolled breakdown.",
            "Confirm MSTR weekly structure is stabilizing instead of only bouncing intraday.",
            "Compare MSTR/BTC relative strength; prefer recovery from extreme underperformance.",
            "Review premium proxy and financing/issuance risk before any staged accumulation.",
            "Plan partial profit review when distribution risk rises; this is not a hold-forever signal.",
        ],
        "charts": {
            "mstr_daily": mstr_daily,
            "mstr_weekly": mstr_weekly,
            "mstr_monthly": mstr_monthly,
            "btc_daily": btc_daily,
            "btc_weekly": btc_weekly,
            "btc_monthly": btc_monthly,
            "mstr_btc_weekly": relative_weekly,
        },
    }
    record_mstr_cycle_run(db, payload)
    payload["cycle_history_summary"] = api_mstr_cycle_history(limit=30, db_path=db)["summary"]
    payload["manual_journal"] = api_mstr_cycle_journal(db_path=db, limit=12)
    write_mstr_cycle_report(outputs, payload)
    return payload


def btc_cycle_component(weekly: dict[str, Any], monthly: dict[str, Any]) -> dict[str, Any]:
    candles = weekly.get("candles", [])
    monthly_candles = monthly.get("candles", [])
    metrics = cycle_metrics(candles)
    score = 0.0
    reasons: list[str] = []
    if not candles:
        return empty_component("btc_cycle", "BTC weekly candles are unavailable.")
    if metrics["drawdown_from_ath_pct"] <= -65:
        score += 28
        reasons.append("BTC is in a deep cycle drawdown zone.")
    elif metrics["drawdown_from_ath_pct"] <= -50:
        score += 20
        reasons.append("BTC drawdown is materially bearish enough for bottom research.")
    elif metrics["drawdown_from_ath_pct"] <= -35:
        score += 10
        reasons.append("BTC has corrected, but not yet a deep-cycle washout.")
    if -20 <= metrics["distance_to_ema200_pct"] <= 25:
        score += 22
        reasons.append("BTC is near its weekly EMA200 zone.")
    elif metrics["distance_to_ema200_pct"] < -20 and metrics["momentum_4w_pct"] > 0:
        score += 14
        reasons.append("BTC is below EMA200 but showing a recovery attempt.")
    if 32 <= metrics["rsi14"] <= 55:
        score += 14
        reasons.append("BTC weekly RSI is in a repairable bottoming range.")
    elif metrics["rsi14"] < 32:
        score += 8
        reasons.append("BTC weekly RSI is washed out, but confirmation is still needed.")
    if metrics["momentum_4w_pct"] > 0:
        score += 12
        reasons.append("BTC 4-week momentum is improving.")
    if monthly_candles and latest_close(monthly) > ema_last([c["close"] for c in monthly_candles], 20):
        score += 8
        reasons.append("BTC monthly close is above monthly EMA20.")
    return {
        "status": "available",
        "score": round(min(score, 100), 1),
        "metrics": metrics,
        "reasons": reasons or ["BTC cycle metrics are available but not in a bottoming zone."],
    }


def mstr_bottom_component(weekly: dict[str, Any], daily: dict[str, Any]) -> dict[str, Any]:
    candles = weekly.get("candles", [])
    daily_candles = daily.get("candles", [])
    metrics = cycle_metrics(candles)
    score = 0.0
    reasons: list[str] = []
    if not candles:
        return empty_component("mstr_bottom", "MSTR weekly candles are unavailable.")
    if metrics["drawdown_from_ath_pct"] <= -75:
        score += 26
        reasons.append("MSTR is in an extreme drawdown zone.")
    elif metrics["drawdown_from_ath_pct"] <= -60:
        score += 18
        reasons.append("MSTR drawdown is deep enough for staged bottom research.")
    if metrics["distance_to_ema200_pct"] <= 20:
        score += 18
        reasons.append("MSTR is near or below weekly EMA200.")
    if 30 <= metrics["rsi14"] <= 55:
        score += 14
        reasons.append("MSTR weekly RSI is no longer extremely hot.")
    if metrics["momentum_4w_pct"] > 0:
        score += 12
        reasons.append("MSTR 4-week momentum is turning positive.")
    if daily_candles:
        daily_close = [bar["close"] for bar in daily_candles]
        close = daily_close[-1]
        daily_ema20 = ema_last(daily_close, 20)
        daily_ema50 = ema_last(daily_close, 50)
        if close > daily_ema20:
            score += 8
            reasons.append("MSTR daily close is back above EMA20.")
        if close > daily_ema50:
            score += 8
            reasons.append("MSTR daily close is back above EMA50.")
    return {
        "status": "available",
        "score": round(min(score, 100), 1),
        "metrics": metrics,
        "reasons": reasons or ["MSTR is not yet showing a cycle-bottom structure."],
    }


def relative_btc_component(relative: dict[str, Any]) -> dict[str, Any]:
    candles = relative.get("candles", [])
    metrics = cycle_metrics(candles)
    score = 0.0
    reasons: list[str] = []
    if not candles:
        return empty_component("relative_btc", "MSTR/BTC relative candles are unavailable.")
    if metrics["drawdown_from_ath_pct"] <= -55:
        score += 24
        reasons.append("MSTR has heavily underperformed BTC, which can mark relative-value washout.")
    elif metrics["drawdown_from_ath_pct"] <= -35:
        score += 14
        reasons.append("MSTR/BTC relative ratio is meaningfully discounted from prior highs.")
    if metrics["momentum_4w_pct"] > 0:
        score += 20
        reasons.append("MSTR/BTC relative momentum is improving.")
    if metrics["close"] > metrics["ema20"]:
        score += 14
        reasons.append("MSTR/BTC ratio has reclaimed weekly EMA20.")
    if 35 <= metrics["rsi14"] <= 58:
        score += 10
        reasons.append("MSTR/BTC RSI is in a constructive repair range.")
    return {
        "status": "available",
        "score": round(min(score, 100), 1),
        "metrics": metrics,
        "reasons": reasons or ["MSTR/BTC relative strength is not yet confirming accumulation."],
    }


def premium_proxy(quote: dict[str, Any], holdings: dict[str, Any], btc_price: float) -> dict[str, Any]:
    quote_price = float(quote.get("regular_market_price") or 0.0)
    basic_shares = float(holdings.get("basic_shares_outstanding") or quote.get("shares_outstanding") or 0.0)
    diluted_shares = float(holdings.get("assumed_diluted_shares_outstanding") or holdings.get("ibit_shares") or 0.0)
    market_cap = float(quote.get("market_cap") or 0.0)
    if market_cap <= 0 and quote_price > 0 and basic_shares > 0:
        market_cap = quote_price * basic_shares
    btc_holdings = float(holdings.get("btc_holdings") or 0.0)
    debt = float(holdings.get("debt") or 0.0)
    preferred = float(holdings.get("preferred_stock") or holdings.get("pref") or 0.0)
    cash = float(holdings.get("cash") or 0.0)
    if market_cap <= 0 or btc_holdings <= 0 or btc_price <= 0:
        return {
            "status": "missing",
            "score": 0.0,
            "premium_to_btc_nav": None,
            "market_cap": market_cap or None,
            "btc_holdings": btc_holdings or None,
            "btc_price": btc_price or None,
            "source": {"quote": quote.get("source"), "holdings": holdings.get("source")},
            "reason": "Missing market cap, BTC holdings, or BTC price; highest accumulation level is disabled.",
        }
    nav = btc_holdings * btc_price
    premium = market_cap / nav if nav else 0.0
    enterprise_value = market_cap + debt + preferred - cash
    enterprise_value_to_btc_nav = enterprise_value / nav if nav else 0.0
    btc_per_basic_share = btc_holdings / basic_shares if basic_shares else 0.0
    btc_per_diluted_share = btc_holdings / diluted_shares if diluted_shares else 0.0
    if premium <= 1.25:
        score = 22
        reason = "MSTR premium proxy is close to BTC NAV."
    elif premium <= 1.8:
        score = 15
        reason = "MSTR premium proxy is moderate."
    elif premium <= 2.5:
        score = 7
        reason = "MSTR premium proxy is elevated; require stronger technical confirmation."
    else:
        score = 0
        reason = "MSTR premium proxy is high; cycle accumulation is downgraded."
    return {
        "status": "available",
        "score": score,
        "premium_to_btc_nav": round(premium, 3),
        "enterprise_value_to_btc_nav": round(enterprise_value_to_btc_nav, 3) if enterprise_value_to_btc_nav else None,
        "market_cap": round(market_cap, 2),
        "btc_holdings": round(btc_holdings, 4),
        "btc_holdings_value": round(nav, 2),
        "btc_price": round(btc_price, 2),
        "basic_shares_outstanding": round(basic_shares, 2) if basic_shares else None,
        "assumed_diluted_shares_outstanding": round(diluted_shares, 2) if diluted_shares else None,
        "btc_per_basic_share": round(btc_per_basic_share, 8) if btc_per_basic_share else None,
        "btc_per_diluted_share": round(btc_per_diluted_share, 8) if btc_per_diluted_share else None,
        "as_of_date": holdings.get("as_of_date"),
        "freshness": holdings.get("freshness", "live"),
        "source": {"quote": quote.get("source"), "holdings": holdings.get("source")},
        "metrics": {
            "premium_to_btc_nav": round(premium, 3),
            "ev_to_btc_nav": round(enterprise_value_to_btc_nav, 3) if enterprise_value_to_btc_nav else 0.0,
            "btc_per_basic_share": round(btc_per_basic_share, 8) if btc_per_basic_share else 0.0,
            "btc_per_diluted_share": round(btc_per_diluted_share, 8) if btc_per_diluted_share else 0.0,
        },
        "reason": reason,
    }


def financing_component(quote: dict[str, Any], holdings: dict[str, Any], premium: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    risk_warnings: list[str] = []
    score = 0.0
    shares = holdings.get("basic_shares_outstanding") or quote.get("shares_outstanding")
    diluted_shares = holdings.get("assumed_diluted_shares_outstanding") or holdings.get("ibit_shares")
    btc_nav = float(premium.get("btc_holdings_value") or 0.0)
    debt = float(holdings.get("debt") or 0.0)
    preferred = float(holdings.get("preferred_stock") or holdings.get("pref") or 0.0)
    cash = float(holdings.get("cash") or 0.0)
    annual_dividends = float(holdings.get("annual_dividends") or 0.0)
    debt_to_btc_nav = debt / btc_nav if btc_nav else 0.0
    preferred_to_btc_nav = preferred / btc_nav if btc_nav else 0.0
    net_obligations_to_btc_nav = max(debt + preferred - cash, 0.0) / btc_nav if btc_nav else 0.0
    dividend_to_btc_nav = annual_dividends / btc_nav if btc_nav else 0.0
    if shares:
        score += 8
        reasons.append("Basic shares outstanding are available for dilution monitoring.")
    if diluted_shares:
        score += 5
        reasons.append("Diluted share proxy is available.")
    if holdings.get("btc_holdings"):
        score += 8
        reasons.append("Official BTC holdings proxy is available.")
    if premium.get("status") == "available" and float(premium.get("premium_to_btc_nav") or 0) <= 2.5:
        score += 6
        reasons.append("Premium proxy is not in the highest risk bucket.")
    if btc_nav and debt_to_btc_nav <= 0.12:
        score += 3
        reasons.append("Debt-to-BTC NAV proxy is not extreme.")
    elif debt_to_btc_nav > 0.2:
        risk_warnings.append("Debt-to-BTC NAV proxy is elevated.")
    if btc_nav and preferred_to_btc_nav <= 0.25:
        score += 3
        reasons.append("Preferred stock burden is visible and not extreme versus BTC NAV.")
    elif preferred_to_btc_nav > 0.35:
        risk_warnings.append("Preferred stock burden is elevated versus BTC NAV.")
    if dividend_to_btc_nav > 0.03:
        risk_warnings.append("Annual dividend burden is elevated versus BTC NAV.")
    status = "available" if score >= 20 else "data_caution"
    return {
        "status": status,
        "score": round(min(score, 33), 1),
        "shares_outstanding": shares,
        "assumed_diluted_shares_outstanding": diluted_shares,
        "debt": debt or None,
        "preferred_stock": preferred or None,
        "cash": cash or None,
        "annual_dividends": annual_dividends or None,
        "as_of_date": holdings.get("as_of_date"),
        "freshness": holdings.get("freshness", "live"),
        "metrics": {
            "debt_to_btc_nav": round(debt_to_btc_nav, 4),
            "preferred_to_btc_nav": round(preferred_to_btc_nav, 4),
            "net_obligations_to_btc_nav": round(net_obligations_to_btc_nav, 4),
            "dividend_to_btc_nav": round(dividend_to_btc_nav, 4),
        },
        "risk_warnings": (reasons + risk_warnings)
        or ["Financing/issuance fields are incomplete; treat the signal as Data Caution and do not upgrade to highest level."],
    }


def strategy_tracker_metrics_component(
    *,
    quote: dict[str, Any],
    holdings: dict[str, Any],
    btc_daily: dict[str, Any],
    mstr_daily: dict[str, Any],
    premium: dict[str, Any],
    financing: dict[str, Any],
) -> dict[str, Any]:
    """SaylorTracker-style MSTR treasury metrics, calculated locally when possible."""
    btc_holdings = float(premium.get("btc_holdings") or holdings.get("btc_holdings") or 0.0)
    btc_price = float(premium.get("btc_price") or latest_close(btc_daily) or 0.0)
    share_price = float(quote.get("regular_market_price") or latest_close(mstr_daily) or 0.0)
    market_cap = float(premium.get("market_cap") or quote.get("market_cap") or 0.0)
    basic_shares = float(
        premium.get("basic_shares_outstanding")
        or holdings.get("basic_shares_outstanding")
        or quote.get("shares_outstanding")
        or 0.0
    )
    diluted_shares = float(
        premium.get("assumed_diluted_shares_outstanding")
        or holdings.get("assumed_diluted_shares_outstanding")
        or holdings.get("ibit_shares")
        or 0.0
    )
    if market_cap <= 0 and share_price > 0 and basic_shares > 0:
        market_cap = share_price * basic_shares
    btc_nav = btc_holdings * btc_price if btc_holdings and btc_price else 0.0
    debt = float(financing.get("debt") or holdings.get("debt") or 0.0)
    preferred = float(financing.get("preferred_stock") or holdings.get("preferred_stock") or 0.0)
    cash = float(financing.get("cash") or holdings.get("cash") or 0.0)
    enterprise_value = market_cap + debt + preferred - cash if market_cap else 0.0
    avg_cost_per_btc = as_float(
        holdings.get("avg_cost_per_btc")
        or holdings.get("average_cost_per_btc")
        or holdings.get("cost_basis_per_btc")
    )
    total_cost_basis = as_float(holdings.get("total_cost_basis"))
    if not total_cost_basis and avg_cost_per_btc and btc_holdings:
        total_cost_basis = avg_cost_per_btc * btc_holdings
    unrealized_pl = btc_nav - total_cost_basis if btc_nav and total_cost_basis else None
    unrealized_pl_pct = pct(btc_nav, total_cost_basis) if btc_nav and total_cost_basis else None
    nav_per_basic_share = btc_nav / basic_shares if btc_nav and basic_shares else 0.0
    nav_per_diluted_share = btc_nav / diluted_shares if btc_nav and diluted_shares else 0.0
    basic_mnav = market_cap / btc_nav if market_cap and btc_nav else 0.0
    diluted_market_cap = share_price * diluted_shares if share_price and diluted_shares else 0.0
    diluted_mnav = diluted_market_cap / btc_nav if diluted_market_cap and btc_nav else 0.0
    ev_mnav = enterprise_value / btc_nav if enterprise_value and btc_nav else 0.0
    btc_per_basic_share = btc_holdings / basic_shares if btc_holdings and basic_shares else 0.0
    btc_per_diluted_share = btc_holdings / diluted_shares if btc_holdings and diluted_shares else 0.0
    sats_per_basic_share = btc_per_basic_share * 100_000_000 if btc_per_basic_share else 0.0
    sats_per_diluted_share = btc_per_diluted_share * 100_000_000 if btc_per_diluted_share else 0.0
    share_dilution_pct = pct(diluted_shares, basic_shares) if diluted_shares and basic_shares else None
    debt_to_btc_nav = debt / btc_nav if debt and btc_nav else 0.0
    preferred_to_btc_nav = preferred / btc_nav if preferred and btc_nav else 0.0
    net_obligations_to_btc_nav = max(debt + preferred - cash, 0.0) / btc_nav if btc_nav else 0.0
    annual_dividends = as_float(holdings.get("annual_dividends"))
    dividend_to_btc_nav = annual_dividends / btc_nav if annual_dividends and btc_nav else 0.0
    mstr_candles = mstr_daily.get("candles", [])
    btc_candles = btc_daily.get("candles", [])
    latest_volume = float(mstr_candles[-1].get("volume") or 0.0) if mstr_candles else 0.0
    avg_volume_20d = average_volume(mstr_candles[-20:])
    dollar_volume = latest_volume * share_price if latest_volume and share_price else 0.0
    premium_dollars = max(market_cap - btc_nav, 0.0) if market_cap and btc_nav else 0.0
    days_to_cover_mnav = premium_dollars / dollar_volume if premium_dollars and dollar_volume else None
    mstr_return_3m = period_return(mstr_candles, 63)
    mstr_return_1y = period_return(mstr_candles, 252)
    btc_return_3m = period_return(btc_candles, 63)
    btc_return_1y = period_return(btc_candles, 252)
    tracker_status = tracker_provider_status(holdings)
    availability = {
        "treasury": bool(btc_holdings and btc_price and share_price),
        "premium_nav": bool(btc_nav and market_cap),
        "shares": bool(basic_shares or diluted_shares),
        "cost_basis": bool(avg_cost_per_btc or total_cost_basis),
        "yield": bool(holdings.get("btc_yield_ytd") or holdings.get("btc_gain_ytd")),
        "debt": bool(debt or preferred or annual_dividends),
        "liquidity": bool(latest_volume and avg_volume_20d),
        "benchmarks": bool(mstr_return_1y is not None and btc_return_1y is not None),
    }
    return {
        "status": "available" if any(availability.values()) else "data_caution",
        "source_type": "derived_locally_with_best_effort_tracker",
        "tracker_provider_status": tracker_status,
        "tracker_source": holdings.get("source"),
        "freshness": holdings.get("freshness", "unknown"),
        "as_of_date": holdings.get("as_of_date"),
        "calculation_policy": "SaylorTracker-style metrics calculated from live MSTR/BTC market data and official Strategy tracker fields when available.",
        "availability": availability,
        "missing_tracker_fields": missing_tracker_fields(holdings),
        "treasury_snapshot": {
            "status": "available" if availability["treasury"] else "data_caution",
            "source_type": "derived_locally",
            "calculation_method": "BTC holdings x BTC price, plus MSTR quote/chart price.",
            "btc_holdings": round_or_none(btc_holdings, 4),
            "btc_price": round_or_none(btc_price, 2),
            "share_price": round_or_none(share_price, 2),
            "btc_holdings_value": round_or_none(btc_nav, 2),
            "market_cap": round_or_none(market_cap, 2),
            "enterprise_value": round_or_none(enterprise_value, 2),
            "bitcoin_nav": round_or_none(btc_nav, 2),
        },
        "premium_nav_metrics": {
            "status": "available" if availability["premium_nav"] else "data_caution",
            "source_type": "derived_locally",
            "calculation_method": "Market cap and enterprise value divided by BTC NAV.",
            "nav_premium": round_or_none((basic_mnav - 1) * 100 if basic_mnav else None, 2),
            "market_cap_to_btc_nav": round_or_none(basic_mnav, 3),
            "ev_to_btc_nav": round_or_none(ev_mnav, 3),
            "basic_mnav": round_or_none(basic_mnav, 3),
            "diluted_mnav": round_or_none(diluted_mnav, 3),
            "ev_mnav": round_or_none(ev_mnav, 3),
            "nav_per_basic_share": round_or_none(nav_per_basic_share, 4),
            "nav_per_diluted_share": round_or_none(nav_per_diluted_share, 4),
        },
        "cost_basis_metrics": {
            "status": "available" if availability["cost_basis"] else "unavailable",
            "source_type": "official_tracker_or_unavailable",
            "calculation_method": "Average cost and total cost basis require tracker/filing data.",
            "avg_cost_per_btc": round_or_none(avg_cost_per_btc, 2),
            "total_cost_basis": round_or_none(total_cost_basis, 2),
            "unrealized_pl": round_or_none(unrealized_pl, 2),
            "percentage_return": round_or_none(unrealized_pl_pct, 2),
        },
        "btc_yield_metrics": {
            "status": "available" if availability["yield"] else "unavailable",
            "source_type": "official_tracker_or_unavailable",
            "calculation_method": "BTC Yield/Gain fields are consumed from official tracker data when present.",
            "btc_yield_ytd": round_or_none(as_float(holdings.get("btc_yield_ytd")), 3),
            "btc_yield_qtd": round_or_none(as_float(holdings.get("btc_yield_qtd")), 3),
            "btc_gain_ytd": round_or_none(as_float(holdings.get("btc_gain_ytd")), 4),
            "btc_gain_qtd": round_or_none(as_float(holdings.get("btc_gain_qtd")), 4),
            "btc_dollar_gain_ytd": round_or_none((as_float(holdings.get("btc_gain_ytd")) or 0) * btc_price if btc_price else None, 2),
        },
        "share_metrics": {
            "status": "available" if availability["shares"] else "data_caution",
            "source_type": "official_tracker_or_quote",
            "calculation_method": "BTC holdings divided by basic/effective diluted share counts.",
            "basic_shares_outstanding": round_or_none(basic_shares, 2),
            "assumed_diluted_shares_outstanding": round_or_none(diluted_shares, 2),
            "btc_per_basic_share": round_or_none(btc_per_basic_share, 8),
            "btc_per_diluted_share": round_or_none(btc_per_diluted_share, 8),
            "sats_per_basic_share": round_or_none(sats_per_basic_share, 2),
            "sats_per_diluted_share": round_or_none(sats_per_diluted_share, 2),
            "share_dilution_pct": round_or_none(share_dilution_pct, 2),
        },
        "debt_financing_metrics": {
            "status": "available" if availability["debt"] else "data_caution",
            "source_type": "official_tracker_or_unavailable",
            "calculation_method": "Debt, preferred stock, cash, and dividends compared with BTC NAV.",
            "total_debt": round_or_none(debt, 2),
            "preferred_stock": round_or_none(preferred, 2),
            "cash": round_or_none(cash, 2),
            "annual_dividends": round_or_none(annual_dividends, 2),
            "debt_to_btc_nav": round_or_none(debt_to_btc_nav, 4),
            "preferred_to_btc_nav": round_or_none(preferred_to_btc_nav, 4),
            "net_obligations_to_btc_nav": round_or_none(net_obligations_to_btc_nav, 4),
            "dividend_to_btc_nav": round_or_none(dividend_to_btc_nav, 4),
            "common_equity_raises_atm": holding_or_none(holdings, "common_equity_raises_atm"),
        },
        "liquidity_metrics": {
            "status": "available" if availability["liquidity"] else "data_caution",
            "source_type": "live_yahoo_chart",
            "calculation_method": "MSTR daily volume, 20D average volume, dollar volume, and premium-dollar cover days.",
            "latest_volume": round_or_none(latest_volume, 2),
            "avg_volume_20d": round_or_none(avg_volume_20d, 2),
            "relative_volume": round_or_none(latest_volume / avg_volume_20d if latest_volume and avg_volume_20d else None, 3),
            "dollar_volume": round_or_none(dollar_volume, 2),
            "days_to_cover_mnav": round_or_none(days_to_cover_mnav, 2),
            "atr14_pct": round_or_none(average_true_range_pct(mstr_candles[-14:]) if len(mstr_candles) >= 14 else None, 2),
        },
        "benchmark_metrics": {
            "status": "available" if availability["benchmarks"] else "data_caution",
            "source_type": "live_yahoo_chart",
            "calculation_method": "MSTR and BTC returns over comparable windows; index benchmarks can be added later.",
            "mstr_return_3m_pct": round_or_none(mstr_return_3m, 2),
            "mstr_return_1y_pct": round_or_none(mstr_return_1y, 2),
            "btc_return_3m_pct": round_or_none(btc_return_3m, 2),
            "btc_return_1y_pct": round_or_none(btc_return_1y, 2),
            "mstr_minus_btc_3m_pct": round_or_none(mstr_return_3m - btc_return_3m if mstr_return_3m is not None and btc_return_3m is not None else None, 2),
            "mstr_minus_btc_1y_pct": round_or_none(mstr_return_1y - btc_return_1y if mstr_return_1y is not None and btc_return_1y is not None else None, 2),
            "bse_return": round_or_none(holding_or_none(holdings, "bse_return"), 2),
        },
    }


def distribution_risk_component(
    btc_cycle: dict[str, Any],
    mstr_bottom: dict[str, Any],
    relative: dict[str, Any],
    premium: dict[str, Any],
) -> dict[str, Any]:
    score = 0.0
    reasons: list[str] = []
    btc = btc_cycle.get("metrics", {})
    mstr = mstr_bottom.get("metrics", {})
    rel = relative.get("metrics", {})
    if btc.get("drawdown_from_ath_pct", -100) > -18 and btc.get("distance_to_ema200_pct", 0) > 80:
        score += 30
        reasons.append("BTC is close to prior highs and far above weekly EMA200.")
    if mstr.get("drawdown_from_ath_pct", -100) > -20 and mstr.get("distance_to_ema200_pct", 0) > 120:
        score += 30
        reasons.append("MSTR is near highs and very extended above weekly EMA200.")
    if float(premium.get("premium_to_btc_nav") or 0) > 2.8:
        score += 25
        reasons.append("MSTR premium proxy is very high.")
    if rel.get("rsi14", 0) > 72:
        score += 15
        reasons.append("MSTR/BTC relative RSI is overheated.")
    return {
        "status": "elevated" if score >= 55 else "normal",
        "score": round(min(score, 100), 1),
        "reasons": reasons or ["No major cycle-top distribution trigger from current proxy metrics."],
    }


def monte_carlo_component(
    mstr_weekly: dict[str, Any],
    btc_weekly: dict[str, Any],
    relative_weekly: dict[str, Any],
    premium: dict[str, Any],
    *,
    paths: int = 800,
) -> dict[str, Any]:
    mstr_candles = mstr_weekly.get("candles", [])
    btc_candles = btc_weekly.get("candles", [])
    if not mstr_candles or not btc_candles:
        return unavailable_monte_carlo("MSTR or BTC weekly candles are unavailable.")
    if premium.get("status") != "available":
        return unavailable_monte_carlo("Premium proxy is missing; scenario simulation is disabled to avoid false precision.")
    mstr_returns = weekly_returns(mstr_candles)
    btc_returns = weekly_returns(btc_candles)
    if len(mstr_returns) < 40 or len(btc_returns) < 40:
        return unavailable_monte_carlo("Not enough weekly history for a stable bootstrap simulation.")
    beta = beta_to_btc(mstr_returns, btc_returns)
    mstr_metrics = cycle_metrics(mstr_candles)
    btc_metrics = cycle_metrics(btc_candles)
    premium_ratio = float(premium.get("premium_to_btc_nav") or 0.0)
    regime_drift = 0.0
    if btc_metrics["drawdown_from_ath_pct"] <= -50 and mstr_metrics["drawdown_from_ath_pct"] <= -60:
        regime_drift += 0.004
    if btc_metrics["momentum_4w_pct"] < -10:
        regime_drift -= 0.0025
    if premium_ratio > 2.5:
        regime_drift -= 0.003
    elif premium_ratio <= 1.5:
        regime_drift += 0.001
    seed = int((mstr_metrics["close"] * 100) + (btc_metrics["close"] % 10_000))
    rng = random.Random(42_017 + seed)
    horizons = {"6m": 26, "12m": 52, "24m": 104}
    return {
        "status": "available",
        "method": "deterministic historical weekly bootstrap",
        "paths": paths,
        "beta_to_btc": round(beta, 3),
        "regime_adjustment_weekly_pct": round(regime_drift * 100, 3),
        "horizons": {
            key: simulate_horizon(mstr_returns, weeks, paths, rng, regime_drift)
            for key, weeks in horizons.items()
        },
        "inputs": {
            "mstr_weekly_returns": len(mstr_returns),
            "btc_weekly_returns": len(btc_returns),
            "premium_to_btc_nav": premium_ratio,
            "mstr_drawdown_from_ath_pct": mstr_metrics["drawdown_from_ath_pct"],
            "btc_drawdown_from_ath_pct": btc_metrics["drawdown_from_ath_pct"],
            "relative_weekly_candles": len(relative_weekly.get("candles", [])),
        },
        "limitations": [
            "Bootstrap samples historical weekly returns and does not know future macro/liquidity regimes.",
            "Large MSTR financing, dilution, or premium regime changes can invalidate the distribution.",
            "Path probabilities are research context only and must not be read as trade instructions.",
        ],
    }


def bayesian_bottom_component(
    btc_cycle: dict[str, Any],
    mstr_bottom: dict[str, Any],
    relative: dict[str, Any],
    premium: dict[str, Any],
    financing: dict[str, Any],
    distribution: dict[str, Any],
) -> dict[str, Any]:
    prior = 0.18
    odds = prior / (1 - prior)
    confidence = 0.78
    positive: list[dict[str, Any]] = []
    negative: list[dict[str, Any]] = []

    def add(target: list[dict[str, Any]], name: str, lr: float, reason: str) -> None:
        target.append({"name": name, "likelihood_ratio": lr, "reason": reason})

    btc = btc_cycle.get("metrics", {})
    mstr = mstr_bottom.get("metrics", {})
    rel = relative.get("metrics", {})
    premium_status = premium.get("status")
    financing_status = financing.get("status")

    if btc.get("drawdown_from_ath_pct", 0) <= -50:
        add(positive, "BTC deep drawdown", 1.65, "BTC has corrected enough to resemble late-bear-cycle environments.")
    if -25 <= btc.get("distance_to_ema200_pct", 999) <= 25:
        add(positive, "BTC near 200W zone", 1.5, "BTC is near its weekly EMA200 reference zone.")
    if 32 <= btc.get("rsi14", 0) <= 55:
        add(positive, "BTC RSI repair", 1.22, "BTC weekly RSI is washed out but repairable.")
    if btc.get("momentum_4w_pct", 0) < -10:
        add(negative, "BTC momentum still falling", 0.72, "BTC 4-week momentum remains sharply negative.")
    if mstr.get("drawdown_from_ath_pct", 0) <= -70:
        add(positive, "MSTR extreme drawdown", 1.55, "MSTR is deeply below prior highs.")
    if mstr.get("momentum_4w_pct", 0) < -20:
        add(negative, "MSTR momentum not stabilized", 0.7, "MSTR 4-week momentum is still deteriorating.")
    if rel.get("drawdown_from_ath_pct", 0) <= -50:
        add(positive, "MSTR/BTC relative washout", 1.25, "MSTR has underperformed BTC enough for relative-value research.")
    if rel.get("momentum_4w_pct", 0) > 0:
        add(positive, "MSTR/BTC relative repair", 1.18, "MSTR/BTC relative momentum has turned positive.")
    if premium_status == "available":
        premium_ratio = float(premium.get("premium_to_btc_nav") or 0)
        if premium_ratio <= 1.8:
            add(positive, "Premium not stretched", 1.22, "Premium proxy is not in a stretched zone.")
        elif premium_ratio > 2.5:
            add(negative, "Premium stretched", 0.65, "MSTR premium proxy is too high for clean accumulation.")
    else:
        confidence -= 0.18
        add(negative, "Premium missing", 0.78, "Missing premium proxy reduces confidence and disables highest interpretation.")
    if financing_status != "available":
        confidence -= 0.14
        add(negative, "Financing incomplete", 0.82, "Financing/issuance data is incomplete.")
    if distribution.get("score", 0) >= 55:
        add(negative, "Distribution risk elevated", 0.35, "Cycle-top risk is elevated, so bottom probability is capped.")

    for item in positive + negative:
        odds *= float(item["likelihood_ratio"])
    probability = odds / (1 + odds)
    if distribution.get("score", 0) >= 55:
        probability = min(probability, 0.35)
    confidence = max(0.25, min(confidence, 0.9))
    band_width = 0.18 + (1 - confidence) * 0.32
    low = max(0.0, probability - band_width / 2)
    high = min(1.0, probability + band_width / 2)
    return {
        "status": "available" if confidence >= 0.55 else "data_caution",
        "method": "interpretable likelihood-ratio update",
        "prior_probability": round(prior * 100, 1),
        "bottom_probability": round(probability * 100, 1),
        "confidence": round(confidence * 100, 1),
        "confidence_band": {"low": round(low * 100, 1), "high": round(high * 100, 1)},
        "positive_evidence": positive,
        "negative_evidence": negative,
        "does_not_override_level": True,
        "limitations": [
            "Likelihood ratios are hand-calibrated for explainability, not trained on a labeled cycle dataset.",
            "Missing premium or financing data lowers confidence rather than being ignored.",
            "High distribution risk caps bottom probability even if drawdown evidence is strong.",
        ],
    }


def cycle_level(
    *,
    bottom_score: float,
    distribution_score: float,
    provider_clean: bool,
    premium_available: bool,
    financing_available: bool,
    btc_candles: bool,
    mstr_candles: bool,
) -> str:
    if distribution_score >= 70:
        return "DISTRIBUTION RISK"
    if not btc_candles or not mstr_candles:
        return "WAIT"
    if bottom_score >= 72 and provider_clean and premium_available and financing_available:
        return "CYCLE ACCUMULATION"
    if bottom_score >= 48:
        return "BOTTOM WATCH"
    return "WAIT"


def level_reasons(
    level: str,
    btc_cycle: dict[str, Any],
    mstr_bottom: dict[str, Any],
    relative: dict[str, Any],
    premium: dict[str, Any],
    financing: dict[str, Any],
    distribution: dict[str, Any],
) -> list[str]:
    if level == "DISTRIBUTION RISK":
        return distribution.get("reasons", [])
    reasons = []
    for component in (btc_cycle, mstr_bottom, relative):
        reasons.extend(component.get("reasons", [])[:2])
    if premium.get("reason"):
        reasons.append(str(premium["reason"]))
    reasons.extend(financing.get("risk_warnings", [])[:1])
    return reasons[:8]


def level_blockers(level: str, provider_errors: list[str], premium: dict[str, Any], financing: dict[str, Any], distribution: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if provider_errors:
        blockers.append("Provider degraded; highest accumulation level is disabled.")
    if premium.get("status") != "available":
        blockers.append("Premium proxy is missing; highest accumulation level is disabled.")
    if financing.get("status") != "available":
        blockers.append("Financing/issuance proxy is incomplete.")
    if distribution.get("score", 0) >= 55:
        blockers.append("Distribution risk is elevated; bottom-buy logic should not dominate.")
    if level == "WAIT" and not blockers:
        blockers.append("Cycle, MSTR, or relative BTC scores are below bottom-watch thresholds.")
    return blockers


def cycle_dashboard_component(
    *,
    level: str,
    bottom_score: float,
    distribution_score: float,
    provider_clean: bool,
    btc_cycle: dict[str, Any],
    mstr_bottom: dict[str, Any],
    relative: dict[str, Any],
    premium: dict[str, Any],
    financing: dict[str, Any],
    monte_carlo: dict[str, Any],
    bayesian_bottom: dict[str, Any],
) -> dict[str, Any]:
    btc = btc_cycle.get("metrics", {})
    mstr = mstr_bottom.get("metrics", {})
    rel = relative.get("metrics", {})
    bottom_gap = round(max(0.0, 48.0 - bottom_score), 1)
    accumulation_gap = round(max(0.0, 72.0 - bottom_score), 1)
    wait_reasons: list[dict[str, Any]] = []
    if bottom_gap > 0:
        wait_reasons.append(
            {
                "label": "Bottom score below BOTTOM WATCH threshold",
                "current": bottom_score,
                "target": 48.0,
                "status": "blocking",
                "why": "The radar remains WAIT until BTC/MSTR/relative/premium evidence clears the first cycle-watch threshold.",
            }
        )
    if mstr.get("momentum_4w_pct", 0) < 0:
        wait_reasons.append(
            {
                "label": "MSTR weekly momentum not stabilized",
                "current": mstr.get("momentum_4w_pct", 0),
                "target": 0.0,
                "status": "blocking",
                "why": "A cycle bottom needs MSTR to stop making lower weekly momentum before staged accumulation improves.",
            }
        )
    if btc.get("momentum_4w_pct", 0) < 0:
        wait_reasons.append(
            {
                "label": "BTC reference momentum still negative",
                "current": btc.get("momentum_4w_pct", 0),
                "target": 0.0,
                "status": "watch",
                "why": "BTC is reference-only, but MSTR bottom quality is weaker while BTC weekly momentum is still falling.",
            }
        )
    if rel.get("momentum_4w_pct", 0) < 0:
        wait_reasons.append(
            {
                "label": "MSTR/BTC relative strength still deteriorating",
                "current": rel.get("momentum_4w_pct", 0),
                "target": 0.0,
                "status": "blocking",
                "why": "For MSTR-specific upside, MSTR should stop underperforming BTC before the highest cycle signal can appear.",
            }
        )
    if not provider_clean:
        wait_reasons.append(
            {
                "label": "Provider health not clean",
                "current": "degraded",
                "target": "available",
                "status": "data_caution",
                "why": "Live/stale data caution prevents high-confidence interpretation.",
            }
        )
    if premium.get("status") != "available":
        wait_reasons.append(
            {
                "label": "Premium proxy unavailable",
                "current": premium.get("status"),
                "target": "available",
                "status": "data_caution",
                "why": "Premium is required before Monte Carlo and cycle accumulation can be trusted.",
            }
        )
    if not wait_reasons:
        wait_reasons.append(
            {
                "label": "WAIT is driven by aggregate evidence quality",
                "current": bottom_score,
                "target": 72.0,
                "status": "watch",
                "why": "The radar has some bottom evidence, but not enough for a cycle accumulation label.",
            }
        )

    upgrade_triggers = [
        {
            "level": "BOTTOM WATCH",
            "status": "met" if level in {"BOTTOM WATCH", "CYCLE ACCUMULATION"} else "pending",
            "requirements": [
                f"Bottom score >= 48; current {bottom_score}",
                "MSTR weekly momentum improves toward 0% or turns positive.",
                "MSTR/BTC relative momentum stops deteriorating.",
                "Distribution risk remains below 55.",
            ],
        },
        {
            "level": "CYCLE ACCUMULATION",
            "status": "met" if level == "CYCLE ACCUMULATION" else "pending",
            "requirements": [
                f"Bottom score >= 72; current {bottom_score}; gap {accumulation_gap}",
                "Provider clean, premium available, and financing proxy available.",
                "BTC weekly/monthly structure no longer in uncontrolled breakdown.",
                "MSTR weekly structure confirms stabilization, not only a short bounce.",
                "Distribution risk stays below 70.",
            ],
        },
        {
            "level": "DISTRIBUTION RISK",
            "status": "active" if level == "DISTRIBUTION RISK" else "inactive",
            "requirements": [
                "BTC approaches prior highs while far above weekly EMA200.",
                "MSTR is near highs and very extended above weekly EMA200.",
                "Premium proxy stretches above 2.8x or MSTR/BTC RSI overheats.",
            ],
        },
    ]
    return {
        "summary": cycle_dashboard_summary(level, bottom_score, bottom_gap, bayesian_bottom),
        "wait_reasons": wait_reasons[:6],
        "upgrade_triggers": upgrade_triggers,
        "ten_x_path": ten_x_path_component(mstr, btc, premium, monte_carlo),
        "review_bias": "observe" if level == "WAIT" else "review",
        "read_only": True,
        "does_not_issue_trade_instruction": True,
        "score_gaps": {
            "bottom_watch_gap": bottom_gap,
            "cycle_accumulation_gap": accumulation_gap,
            "distribution_risk_score": distribution_score,
        },
    }


def cycle_dashboard_summary(level: str, bottom_score: float, bottom_gap: float, bayesian_bottom: dict[str, Any]) -> str:
    probability = bayesian_bottom.get("bottom_probability")
    if level == "WAIT" and bottom_gap > 0:
        return f"WAIT because bottom score is {bottom_gap} points below BOTTOM WATCH; Bayesian bottom probability is {probability}%."
    if level == "WAIT":
        return f"WAIT because evidence has not cleared cycle accumulation quality; Bayesian bottom probability is {probability}%."
    if level == "BOTTOM WATCH":
        return "BOTTOM WATCH: bottom evidence is visible, but staged confirmation is still required."
    if level == "CYCLE ACCUMULATION":
        return "CYCLE ACCUMULATION: long-cycle evidence is aligned enough for staged manual review."
    return "DISTRIBUTION RISK: cycle-top risk is elevated; bottom-buy logic should stand down."


def ten_x_path_component(mstr: dict[str, Any], btc: dict[str, Any], premium: dict[str, Any], monte_carlo: dict[str, Any]) -> dict[str, Any]:
    current_mstr = float(mstr.get("close") or 0.0)
    current_btc = float(btc.get("close") or premium.get("btc_price") or 0.0)
    btc_holdings = float(premium.get("btc_holdings") or 0.0)
    premium_ratio = float(premium.get("premium_to_btc_nav") or 0.0)
    market_cap = float(premium.get("market_cap") or 0.0)
    target_mstr = current_mstr * 10 if current_mstr else 0.0
    target_market_cap = market_cap * 10 if market_cap else 0.0
    scenario_premiums = [1.0, 1.5, 2.0, 2.5]
    required_btc_prices = []
    for ratio in scenario_premiums:
        required = target_market_cap / max(btc_holdings * ratio, 1.0) if target_market_cap and btc_holdings else 0.0
        required_btc_prices.append(
            {
                "premium_to_nav": ratio,
                "required_btc_price": round(required, 2) if required else None,
                "btc_multiple_from_current": round(required / current_btc, 2) if required and current_btc else None,
            }
        )
    horizon_24m = (monte_carlo.get("horizons") or {}).get("24m", {})
    return {
        "status": "available" if current_mstr and target_market_cap and btc_holdings else "data_caution",
        "current_mstr_price": round(current_mstr, 2) if current_mstr else None,
        "target_mstr_price_10x": round(target_mstr, 2) if target_mstr else None,
        "current_btc_price": round(current_btc, 2) if current_btc else None,
        "current_premium_to_nav": round(premium_ratio, 3) if premium_ratio else None,
        "target_market_cap": round(target_market_cap, 2) if target_market_cap else None,
        "required_btc_prices": required_btc_prices,
        "monte_carlo_24m_probability_10x_pct": horizon_24m.get("probability_10x_pct"),
        "monte_carlo_24m_p90_return_pct": horizon_24m.get("p90_return_pct"),
        "assumptions": [
            "10x path assumes no major share-count expansion beyond current proxies.",
            "Required BTC price estimates hold BTC holdings constant.",
            "Premium-to-NAV can expand or contract; the table is a scenario map, not a forecast.",
            "Financing, dilution, and BTC accumulation changes can materially alter this path.",
        ],
    }


def trigger_monitor_component(
    *,
    level: str,
    bottom_score: float,
    distribution_score: float,
    provider_clean: bool,
    btc_cycle: dict[str, Any],
    mstr_bottom: dict[str, Any],
    relative: dict[str, Any],
    premium: dict[str, Any],
    financing: dict[str, Any],
) -> dict[str, Any]:
    btc = btc_cycle.get("metrics", {})
    mstr = mstr_bottom.get("metrics", {})
    rel = relative.get("metrics", {})
    conditions = [
        monitor_condition("BOTTOM WATCH", "Bottom score clears first watch threshold", bottom_score, 48.0, bottom_score >= 48.0),
        monitor_condition("BOTTOM WATCH", "Distribution risk remains controlled", distribution_score, 55.0, distribution_score < 55.0, comparator="<"),
        monitor_condition("BOTTOM WATCH", "MSTR weekly momentum stabilizes", mstr.get("momentum_4w_pct", 0.0), 0.0, mstr.get("momentum_4w_pct", 0.0) >= 0),
        monitor_condition("BOTTOM WATCH", "MSTR/BTC relative momentum stops falling", rel.get("momentum_4w_pct", 0.0), 0.0, rel.get("momentum_4w_pct", 0.0) >= 0),
        monitor_condition("CYCLE ACCUMULATION", "Bottom score clears accumulation threshold", bottom_score, 72.0, bottom_score >= 72.0),
        monitor_condition("CYCLE ACCUMULATION", "Provider health is clean", 1 if provider_clean else 0, 1, provider_clean),
        monitor_condition("CYCLE ACCUMULATION", "Premium proxy is available", 1 if premium.get("status") == "available" else 0, 1, premium.get("status") == "available"),
        monitor_condition("CYCLE ACCUMULATION", "Financing proxy is available", 1 if financing.get("status") == "available" else 0, 1, financing.get("status") == "available"),
        monitor_condition("CYCLE ACCUMULATION", "BTC reference momentum is not breaking down", btc.get("momentum_4w_pct", 0.0), 0.0, btc.get("momentum_4w_pct", 0.0) >= 0),
        monitor_condition("DISTRIBUTION RISK", "Distribution score enters top-risk zone", distribution_score, 70.0, distribution_score >= 70.0),
    ]
    bottom_watch_met = all(item["met"] for item in conditions if item["level"] == "BOTTOM WATCH")
    accumulation_met = all(item["met"] for item in conditions if item["level"] == "CYCLE ACCUMULATION")
    distribution_met = any(item["met"] for item in conditions if item["level"] == "DISTRIBUTION RISK")
    if distribution_met:
        next_state = "DISTRIBUTION RISK active"
    elif accumulation_met:
        next_state = "CYCLE ACCUMULATION conditions met"
    elif bottom_watch_met:
        next_state = "BOTTOM WATCH conditions met; accumulation still pending"
    else:
        next_state = "WAIT; bottom-watch conditions still pending"
    return {
        "status": "active",
        "level": level,
        "next_state": next_state,
        "gaps": {
            "bottom_watch_score_gap": round(max(0.0, 48.0 - bottom_score), 1),
            "cycle_accumulation_score_gap": round(max(0.0, 72.0 - bottom_score), 1),
            "distribution_risk_score_gap": round(max(0.0, 70.0 - distribution_score), 1),
        },
        "conditions": conditions,
        "read_only": True,
    }


def monitor_condition(
    level: str,
    name: str,
    current: Any,
    target: Any,
    met: bool,
    *,
    comparator: str = ">=",
) -> dict[str, Any]:
    return {
        "level": level,
        "name": name,
        "current": round(current, 2) if isinstance(current, (float, int)) else current,
        "target": round(target, 2) if isinstance(target, (float, int)) else target,
        "comparator": comparator,
        "met": bool(met),
    }


def path_stress_test_component(ten_x_path: dict[str, Any], premium: dict[str, Any]) -> dict[str, Any]:
    target_market_cap = float(ten_x_path.get("target_market_cap") or 0.0)
    btc_holdings = float(premium.get("btc_holdings") or 0.0)
    current_btc = float(ten_x_path.get("current_btc_price") or premium.get("btc_price") or 0.0)
    if target_market_cap <= 0 or btc_holdings <= 0:
        return {
            "status": "data_caution",
            "rows": [],
            "reason": "Target market cap or BTC holdings proxy is unavailable; 10x stress test is disabled.",
            "read_only": True,
        }
    rows: list[dict[str, Any]] = []
    for dilution_rate in (0.0, 0.10, 0.25, 0.50):
        for premium_ratio in (1.0, 1.5, 2.0):
            adjusted_target_market_cap = target_market_cap * (1 + dilution_rate)
            required_btc = adjusted_target_market_cap / max(btc_holdings * premium_ratio, 1.0)
            rows.append(
                {
                    "dilution_rate_pct": round(dilution_rate * 100, 1),
                    "premium_to_nav": premium_ratio,
                    "required_btc_price": round(required_btc, 2),
                    "btc_multiple_from_current": round(required_btc / current_btc, 2) if current_btc else None,
                    "adjusted_target_market_cap": round(adjusted_target_market_cap, 2),
                }
            )
    return {
        "status": "available",
        "question": "If shares expand and premium compresses, what BTC price is needed for a 10x MSTR path?",
        "rows": rows,
        "assumptions": [
            "Stress test keeps current BTC holdings constant unless future tracker data changes it.",
            "Dilution scenarios approximate share expansion and financing drag.",
            "Premium scenarios show expansion/contraction risk and are not forecasts.",
        ],
        "read_only": True,
    }


def connect_mstr_db(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(MSTR_SCHEMA)
    connection.commit()
    return connection


def record_mstr_cycle_run(db_path: Path, payload: dict[str, Any]) -> None:
    bayes = payload.get("bayesian_bottom", {})
    mc_24m = (payload.get("monte_carlo", {}).get("horizons") or {}).get("24m", {})
    premium = payload.get("components", {}).get("premium_proxy", {})
    relative = payload.get("components", {}).get("relative_btc", {})
    compact = compact_mstr_cycle_payload(payload)
    with connect_mstr_db(db_path) as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO mstr_cycle_runs (
                run_id, completed_at, level, bottom_score, distribution_risk_score,
                bayesian_bottom_probability, bayesian_confidence, premium_to_btc_nav,
                ev_to_btc_nav, mstr_btc_momentum_4w_pct, mc_24m_probability_2x,
                mc_24m_probability_5x, mc_24m_probability_10x, provider_status,
                blocker_count, blockers_json, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["run_id"],
                payload["completed_at"],
                payload["level"],
                payload["bottom_score"],
                payload["distribution_risk_score"],
                bayes.get("bottom_probability") or 0,
                bayes.get("confidence") or 0,
                premium.get("premium_to_btc_nav"),
                premium.get("enterprise_value_to_btc_nav"),
                (relative.get("metrics") or {}).get("momentum_4w_pct"),
                mc_24m.get("probability_2x_pct"),
                mc_24m.get("probability_5x_pct"),
                mc_24m.get("probability_10x_pct"),
                payload["provider_status"],
                len(payload.get("blockers", [])),
                json.dumps(payload.get("blockers", []), ensure_ascii=True),
                json.dumps(compact, ensure_ascii=True),
            ),
        )
        connection.commit()


def compact_mstr_cycle_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": payload.get("run_id"),
        "completed_at": payload.get("completed_at"),
        "level": payload.get("level"),
        "bottom_score": payload.get("bottom_score"),
        "distribution_risk_score": payload.get("distribution_risk_score"),
        "provider_status": payload.get("provider_status"),
        "provider_error_count": payload.get("provider_error_count"),
        "components": {
            name: {
                "status": component.get("status"),
                "score": component.get("score"),
                "metrics": component.get("metrics", {}),
            }
            for name, component in (payload.get("components") or {}).items()
        },
        "monte_carlo_24m": (payload.get("monte_carlo", {}).get("horizons") or {}).get("24m", {}),
        "bayesian_bottom": payload.get("bayesian_bottom", {}),
        "trigger_monitor": payload.get("trigger_monitor", {}),
        "path_stress_test": {
            "status": (payload.get("path_stress_test") or {}).get("status"),
            "row_count": len((payload.get("path_stress_test") or {}).get("rows") or []),
        },
    }


def api_mstr_cycle_history(limit: int = 30, db_path: Path | None = None) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or 30), 200))
    with connect_mstr_db(db_path) as connection:
        rows = connection.execute(
            """
            SELECT run_id, completed_at, level, bottom_score, distribution_risk_score,
                   bayesian_bottom_probability, bayesian_confidence, premium_to_btc_nav,
                   ev_to_btc_nav, mstr_btc_momentum_4w_pct, mc_24m_probability_2x,
                   mc_24m_probability_5x, mc_24m_probability_10x, provider_status,
                   blocker_count, blockers_json
            FROM mstr_cycle_runs
            ORDER BY completed_at DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    records = [mstr_history_row(row) for row in rows]
    return {
        "status": "available" if records else "not_scanned",
        "limit": safe_limit,
        "records": records,
        "summary": mstr_cycle_history_summary(records),
        "read_only": True,
    }


def mstr_history_row(row: sqlite3.Row) -> dict[str, Any]:
    try:
        blockers = json.loads(row["blockers_json"] or "[]")
    except json.JSONDecodeError:
        blockers = []
    return {
        "run_id": row["run_id"],
        "completed_at": row["completed_at"],
        "level": row["level"],
        "bottom_score": row["bottom_score"],
        "distribution_risk_score": row["distribution_risk_score"],
        "bayesian_bottom_probability": row["bayesian_bottom_probability"],
        "bayesian_confidence": row["bayesian_confidence"],
        "premium_to_btc_nav": row["premium_to_btc_nav"],
        "ev_to_btc_nav": row["ev_to_btc_nav"],
        "mstr_btc_momentum_4w_pct": row["mstr_btc_momentum_4w_pct"],
        "mc_24m_probability_2x": row["mc_24m_probability_2x"],
        "mc_24m_probability_5x": row["mc_24m_probability_5x"],
        "mc_24m_probability_10x": row["mc_24m_probability_10x"],
        "provider_status": row["provider_status"],
        "blocker_count": row["blocker_count"],
        "blockers": blockers,
    }


def mstr_cycle_history_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {
            "run_count": 0,
            "latest_level": "not_scanned",
            "latest_completed_at": None,
            "score_change": 0,
            "probability_change": 0,
            "trend": "not_scanned",
        }
    latest = records[0]
    previous = records[1] if len(records) > 1 else latest
    score_change = float(latest.get("bottom_score") or 0) - float(previous.get("bottom_score") or 0)
    probability_change = float(latest.get("bayesian_bottom_probability") or 0) - float(previous.get("bayesian_bottom_probability") or 0)
    if score_change > 1 or probability_change > 2:
        trend = "improving"
    elif score_change < -1 or probability_change < -2:
        trend = "weakening"
    else:
        trend = "stable"
    return {
        "run_count": len(records),
        "latest_level": latest.get("level"),
        "previous_level": previous.get("level"),
        "latest_completed_at": latest.get("completed_at"),
        "first_completed_at": records[-1].get("completed_at"),
        "latest_bottom_score": latest.get("bottom_score"),
        "score_change": round(score_change, 2),
        "latest_bottom_probability": latest.get("bayesian_bottom_probability"),
        "probability_change": round(probability_change, 2),
        "latest_premium_to_nav": latest.get("premium_to_btc_nav"),
        "latest_mc_24m_probability_10x": latest.get("mc_24m_probability_10x"),
        "trend": trend,
    }


def api_mstr_cycle_journal(db_path: Path | None = None, limit: int = 50) -> dict[str, Any]:
    safe_limit = max(1, min(int(limit or 50), 200))
    with connect_mstr_db(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, run_id, status, notes, outcome, reviewed_at, level,
                   bottom_score, bayesian_bottom_probability, manual_checklist_json
            FROM mstr_cycle_journal
            ORDER BY reviewed_at DESC, id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    entries = [mstr_journal_row(row) for row in rows]
    counts = {status: 0 for status in sorted(MSTR_JOURNAL_STATUSES)}
    for entry in entries:
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
    return {
        "status": "available",
        "limit": safe_limit,
        "entries": entries,
        "counts": counts,
        "read_only_research": True,
    }


def api_mstr_cycle_journal_entry(payload: dict[str, Any], db_path: Path | None = None) -> dict[str, Any]:
    status = str(payload.get("status") or "reviewed").strip()
    if status not in MSTR_JOURNAL_STATUSES:
        raise ValueError("Invalid MSTR journal status.")
    notes = str(payload.get("notes") or "").strip()[:4000]
    outcome = str(payload.get("outcome") or "").strip()[:4000]
    run_id = str(payload.get("run_id") or "").strip()
    reviewed_at = iso_now()
    with connect_mstr_db(db_path) as connection:
        run = None
        if run_id:
            run = connection.execute(
                "SELECT run_id, level, bottom_score, bayesian_bottom_probability, payload_json FROM mstr_cycle_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if run is None:
            run = connection.execute(
                "SELECT run_id, level, bottom_score, bayesian_bottom_probability, payload_json FROM mstr_cycle_runs ORDER BY completed_at DESC LIMIT 1"
            ).fetchone()
        if run is None:
            raise ValueError("Run MSTR Cycle Radar before saving a journal entry.")
        checklist = []
        try:
            compact = json.loads(run["payload_json"] or "{}")
            checklist = compact.get("trigger_monitor", {}).get("conditions", [])[:8]
        except json.JSONDecodeError:
            checklist = []
        cursor = connection.execute(
            """
            INSERT INTO mstr_cycle_journal (
                run_id, status, notes, outcome, reviewed_at, level, bottom_score,
                bayesian_bottom_probability, manual_checklist_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run["run_id"],
                status,
                notes,
                outcome,
                reviewed_at,
                run["level"],
                run["bottom_score"],
                run["bayesian_bottom_probability"],
                json.dumps(checklist, ensure_ascii=True),
            ),
        )
        connection.commit()
        entry = connection.execute(
            """
            SELECT id, run_id, status, notes, outcome, reviewed_at, level,
                   bottom_score, bayesian_bottom_probability, manual_checklist_json
            FROM mstr_cycle_journal
            WHERE id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()
    return {
        "status": "saved",
        "entry": mstr_journal_row(entry),
        "journal": api_mstr_cycle_journal(db_path=db_path, limit=50),
        "read_only_research": True,
    }


def mstr_journal_row(row: sqlite3.Row) -> dict[str, Any]:
    try:
        checklist = json.loads(row["manual_checklist_json"] or "[]")
    except json.JSONDecodeError:
        checklist = []
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "status": row["status"],
        "notes": row["notes"],
        "outcome": row["outcome"],
        "reviewed_at": row["reviewed_at"],
        "level": row["level"],
        "bottom_score": row["bottom_score"],
        "bayesian_bottom_probability": row["bayesian_bottom_probability"],
        "manual_checklist": checklist,
    }


def cycle_metrics(candles: list[dict[str, Any]]) -> dict[str, float]:
    if not candles:
        return {
            "close": 0.0,
            "ath": 0.0,
            "drawdown_from_ath_pct": 0.0,
            "ema20": 0.0,
            "ema50": 0.0,
            "ema100": 0.0,
            "ema200": 0.0,
            "distance_to_ema200_pct": 0.0,
            "rsi14": 0.0,
            "momentum_4w_pct": 0.0,
            "atr14_pct": 0.0,
        }
    closes = [float(bar["close"]) for bar in candles]
    close = closes[-1]
    ath = max(closes)
    ema20 = ema_last(closes, 20)
    ema50 = ema_last(closes, 50)
    ema100 = ema_last(closes, 100)
    ema200 = ema_last(closes, 200)
    return {
        "close": round(close, 4),
        "ath": round(ath, 4),
        "drawdown_from_ath_pct": round(pct(close, ath), 2),
        "ema20": round(ema20, 4),
        "ema50": round(ema50, 4),
        "ema100": round(ema100, 4),
        "ema200": round(ema200, 4),
        "distance_to_ema200_pct": round(pct(close, ema200), 2) if ema200 else 0.0,
        "rsi14": round(rsi(closes, 14), 1),
        "momentum_4w_pct": round(pct(close, closes[-5]) if len(closes) > 5 else 0.0, 2),
        "atr14_pct": round(average_true_range_pct(candles[-14:]), 2),
    }


def unavailable_monte_carlo(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "method": "deterministic historical weekly bootstrap",
        "paths": 0,
        "horizons": {},
        "reason": reason,
        "limitations": [
            "Simulation is disabled unless MSTR, BTC, and premium proxy are available.",
            "Unavailable simulation is safer than fabricating probability from incomplete data.",
        ],
    }


def weekly_returns(candles: list[dict[str, Any]]) -> list[float]:
    closes = [float(item["close"]) for item in candles if float(item.get("close") or 0) > 0]
    returns: list[float] = []
    for previous, current in zip(closes[:-1], closes[1:]):
        returns.append(max(-0.6, min((current / previous) - 1, 0.8)))
    return returns


def beta_to_btc(mstr_returns: list[float], btc_returns: list[float]) -> float:
    count = min(len(mstr_returns), len(btc_returns))
    if count < 3:
        return 0.0
    left = mstr_returns[-count:]
    right = btc_returns[-count:]
    avg_left = sum(left) / count
    avg_right = sum(right) / count
    covariance = sum((a - avg_left) * (b - avg_right) for a, b in zip(left, right)) / count
    variance = sum((b - avg_right) ** 2 for b in right) / count
    return covariance / variance if variance else 0.0


def simulate_horizon(
    returns: list[float],
    weeks: int,
    paths: int,
    rng: random.Random,
    regime_drift: float,
) -> dict[str, Any]:
    final_returns: list[float] = []
    max_drawdowns: list[float] = []
    for _ in range(paths):
        value = 1.0
        peak = 1.0
        worst_drawdown = 0.0
        for _week in range(weeks):
            sampled = rng.choice(returns)
            weekly_return = max(-0.65, min(sampled + regime_drift, 0.85))
            value *= 1 + weekly_return
            peak = max(peak, value)
            worst_drawdown = min(worst_drawdown, (value / peak) - 1)
        final_returns.append((value - 1) * 100)
        max_drawdowns.append(worst_drawdown * 100)
    return {
        "weeks": weeks,
        "p10_return_pct": round(percentile(final_returns, 10), 2),
        "p50_return_pct": round(percentile(final_returns, 50), 2),
        "p90_return_pct": round(percentile(final_returns, 90), 2),
        "median_return_pct": round(percentile(final_returns, 50), 2),
        "p10_max_drawdown_pct": round(percentile(max_drawdowns, 10), 2),
        "median_max_drawdown_pct": round(percentile(max_drawdowns, 50), 2),
        "probability_2x_pct": round(probability_at_least(final_returns, 100), 2),
        "probability_5x_pct": round(probability_at_least(final_returns, 400), 2),
        "probability_10x_pct": round(probability_at_least(final_returns, 900), 2),
    }


def percentile(values: list[float], pct_value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * pct_value / 100
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def probability_at_least(values: list[float], threshold_pct: float) -> float:
    if not values:
        return 0.0
    return sum(1 for value in values if value >= threshold_pct) / len(values) * 100


def ratio_payload(left_symbol: str, right_symbol: str, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_candles = left.get("candles", [])
    right_candles = right.get("candles", [])
    count = min(len(left_candles), len(right_candles))
    candles: list[dict[str, Any]] = []
    for left_bar, right_bar in zip(left_candles[-count:], right_candles[-count:]):
        scale = 100000.0
        if not right_bar.get("close"):
            continue
        candles.append(
            {
                "open_time": left_bar["open_time"],
                "time": left_bar["time"],
                "open": round(float(left_bar["open"]) / max(float(right_bar["open"]), 0.0001) * scale, 4),
                "high": round(float(left_bar["high"]) / max(float(right_bar["low"]), 0.0001) * scale, 4),
                "low": round(float(left_bar["low"]) / max(float(right_bar["high"]), 0.0001) * scale, 4),
                "close": round(float(left_bar["close"]) / max(float(right_bar["close"]), 0.0001) * scale, 4),
                "volume": float(left_bar.get("volume", 0)),
                "source": "derived_live_ratio",
            }
        )
    provider_errors = []
    for payload in (left, right):
        provider_errors.extend(payload.get("provider_errors", []))
    return {
        "instrument_type": "derived_ratio",
        "symbol": f"{left_symbol}/{right_symbol}",
        "range": left.get("range", "5y"),
        "interval": left.get("interval", "1wk"),
        "source_type": "derived_live_ratio",
        "provider_status": "available" if candles and not provider_errors else "unavailable",
        "provider_errors": provider_errors[:5],
        "freshness": "live" if candles and not provider_errors else "missing",
        "candles": candles,
    }


def yahoo_quote_snapshot(symbol: str) -> dict[str, Any]:
    params = urlencode({"symbols": symbol})
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?{params}"
    try:
        response = requests.get(url, timeout=5, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        result = ((response.json().get("quoteResponse") or {}).get("result") or [{}])[0]
        return {
            "source": "yahoo_quote",
            "status": "available",
            "market_cap": result.get("marketCap"),
            "shares_outstanding": result.get("sharesOutstanding"),
            "regular_market_price": result.get("regularMarketPrice"),
        }
    except Exception as exc:  # pragma: no cover - depends on public provider/network
        return {"source": "yahoo_quote", "status": "unavailable", "error": str(exc)}


def enrich_quote_from_chart(quote: dict[str, Any], mstr_daily: dict[str, Any]) -> dict[str, Any]:
    if quote.get("regular_market_price"):
        return quote
    chart_close = latest_close(mstr_daily)
    if chart_close <= 0:
        return quote
    enriched = dict(quote)
    enriched["regular_market_price"] = chart_close
    enriched["price_source"] = "live_yahoo_chart_last_close"
    enriched["source"] = f"{quote.get('source', 'yahoo_quote')}+chart_close"
    if enriched.get("status") != "available":
        enriched["status"] = "partial"
    return enriched


def strategy_btc_holdings_snapshot() -> dict[str, Any]:
    env_value = os.getenv("KQUANT_MSTR_BTC_HOLDINGS") or os.getenv("MSTR_BTC_HOLDINGS")
    if env_value:
        try:
            return {"source": "env", "status": "available", "btc_holdings": float(env_value.replace(",", ""))}
        except ValueError:
            pass
    for url in ("https://www.strategy.com/btc", "https://www.strategy.com/"):
        try:
            response = requests.get(url, timeout=5, headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            matches = [float(match.replace(",", "")) for match in re.findall(r"₿\s*([0-9][0-9,]{4,})", response.text)]
            candidates = [value for value in matches if 10_000 <= value <= 5_000_000]
            if candidates:
                return {"source": url, "status": "available", "btc_holdings": max(candidates)}
        except Exception:
            continue
    return {"source": "strategy_public_page", "status": "missing", "btc_holdings": None}


def strategy_btc_holdings_snapshot() -> dict[str, Any]:
    env_value = os.getenv("KQUANT_MSTR_BTC_HOLDINGS") or os.getenv("MSTR_BTC_HOLDINGS")
    if env_value:
        try:
            return {
                "source": "env",
                "status": "available",
                "freshness": "manual_override",
                "btc_holdings": float(env_value.replace(",", "")),
            }
        except ValueError:
            pass
    try:
        response = requests.get("https://www.strategy.com/", timeout=8, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        parsed = parse_strategy_tracker_snapshot(response.text)
        if parsed:
            write_mstr_reference_cache(parsed)
            return parsed
    except Exception:
        pass
    cached = read_mstr_reference_cache()
    if cached:
        return cached
    return {"source": "strategy_public_tracker", "status": "missing", "freshness": "missing", "btc_holdings": None}


def parse_strategy_tracker_snapshot(page_html: str) -> dict[str, Any] | None:
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', page_html, re.DOTALL)
    if not match:
        return None
    try:
        next_data = json.loads(html_lib.unescape(match.group(1)))
    except json.JSONDecodeError:
        return None
    rows = (((next_data.get("props") or {}).get("pageProps") or {}).get("btcTrackerData") or [])
    if not isinstance(rows, list):
        return None
    latest_rows = [row for row in rows if isinstance(row, dict) and row.get("latest")]
    row = latest_rows[0] if latest_rows else (rows[0] if rows and isinstance(rows[0], dict) else None)
    if not row:
        return None
    btc_holdings = as_float(row.get("btc_holdings"))
    if not btc_holdings:
        return None
    return {
        "source": "strategy_public_tracker",
        "source_url": "https://www.strategy.com/",
        "status": "available",
        "freshness": "live",
        "retrieved_at": iso_now(),
        "as_of_date": row.get("as_of_date"),
        "btc_holdings": btc_holdings,
        "basic_shares_outstanding": as_float(row.get("basic_shares_outstanding")),
        "assumed_diluted_shares_outstanding": as_float(row.get("assumed_diluted_shares_outstanding") or row.get("ibit_shares")),
        "ibit_shares": as_float(row.get("ibit_shares")),
        "debt": as_float(row.get("debt")),
        "preferred_stock": as_float(row.get("pref")),
        "cash": as_float(row.get("cash")),
        "annual_dividends": as_float(row.get("annual_dividends")),
        "debt_years": as_float(row.get("debt_years")),
        "btc_yield_ytd": as_float(row.get("btc_yield_ytd")),
        "btc_yield_qtd": as_float(row.get("btc_yield_qtd") or row.get("btc_yield_quarterly")),
        "btc_gain_ytd": as_float(row.get("btc_gain_ytd")),
        "btc_gain_qtd": as_float(row.get("btc_gain_qtd")),
        "avg_cost_per_btc": as_float(row.get("avg_cost_per_btc") or row.get("average_cost_per_btc") or row.get("cost_basis_per_btc")),
        "total_cost_basis": as_float(row.get("total_cost_basis") or row.get("cost_basis")),
        "bse_return": as_float(row.get("bse_return")),
        "common_equity_raises_atm": as_float(row.get("common_equity_raises_atm") or row.get("atm_raises")),
        "preferred_series": {
            key.replace("_metrics", ""): {
                "shares": as_float(value.get("shares")),
                "dividend": as_float(value.get("dividend")),
                "cumulative_notional": as_float(value.get("cumulative_notional")),
                "next_payout_date": value.get("next_payout_date"),
                "next_record_date": value.get("next_record_date"),
            }
            for key, value in row.items()
            if key.startswith("str") and key.endswith("_metrics") and isinstance(value, dict)
        },
    }


def mstr_reference_cache_path() -> Path:
    return default_db_path().parent / "mstr_reference_cache.json"


def write_mstr_reference_cache(snapshot: dict[str, Any]) -> None:
    path = mstr_reference_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")


def read_mstr_reference_cache() -> dict[str, Any] | None:
    path = mstr_reference_cache_path()
    if not path.exists():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    retrieved_at = str(cached.get("retrieved_at") or "")
    stale_age = 0
    try:
        from datetime import datetime

        retrieved = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
        stale_age = max(0, int(time.time() - retrieved.timestamp()))
    except Exception:
        pass
    cached["status"] = "stale_cache"
    cached["freshness"] = "stale_real_cache"
    cached["source"] = "strategy_public_tracker_cache"
    cached["stale_age_seconds"] = stale_age
    return cached


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def round_or_none(value: Any, digits: int = 2) -> float | None:
    numeric = as_float(value)
    if numeric is None:
        return None
    return round(numeric, digits)


def holding_or_none(holdings: dict[str, Any], key: str) -> float | None:
    return as_float(holdings.get(key))


def tracker_provider_status(holdings: dict[str, Any]) -> str:
    status = str(holdings.get("status") or "missing")
    source = str(holdings.get("source") or "")
    if status == "available":
        return "available"
    if status == "stale_cache" or "cache" in source:
        return "stale_cache"
    return "unavailable"


def missing_tracker_fields(holdings: dict[str, Any]) -> list[str]:
    required = {
        "btc_holdings": "BTC Holdings",
        "basic_shares_outstanding": "Basic Shares Outstanding",
        "assumed_diluted_shares_outstanding": "Assumed Diluted Shares Outstanding",
        "debt": "Total Debt",
        "preferred_stock": "Preferred Stock",
        "cash": "Cash",
        "annual_dividends": "Annual Dividends",
        "avg_cost_per_btc": "Average Cost per BTC",
        "total_cost_basis": "Total Cost Basis",
        "btc_yield_ytd": "BTC Yield YTD",
        "btc_gain_ytd": "BTC Gain YTD",
        "common_equity_raises_atm": "Common Equity Raises ATM",
    }
    missing = [label for key, label in required.items() if holdings.get(key) in (None, "", 0)]
    return missing


def average_volume(candles: list[dict[str, Any]]) -> float:
    volumes = [float(item.get("volume") or 0.0) for item in candles if float(item.get("volume") or 0.0) > 0]
    return sum(volumes) / len(volumes) if volumes else 0.0


def period_return(candles: list[dict[str, Any]], periods: int) -> float | None:
    if len(candles) <= periods:
        return None
    start = float(candles[-periods - 1].get("close") or 0.0)
    end = float(candles[-1].get("close") or 0.0)
    if start <= 0 or end <= 0:
        return None
    return pct(end, start)


def latest_close(payload: dict[str, Any]) -> float:
    candles = payload.get("candles", [])
    return float(candles[-1]["close"]) if candles else 0.0


def collect_provider_errors(payloads: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for name, payload in payloads.items():
        status = payload.get("provider_status")
        if status != "available":
            details = "; ".join(str(item) for item in payload.get("provider_errors", [])[:2])
            errors.append(f"{name}: {status}{' - ' + details if details else ''}")
    return errors


def rsi(values: list[float], period: int = 14) -> float:
    if len(values) <= period:
        return 50.0
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values[-period - 1 : -1], values[-period:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(abs(min(change, 0.0)))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def empty_component(name: str, reason: str) -> dict[str, Any]:
    return {"status": "missing", "score": 0.0, "metrics": {}, "reasons": [reason], "component": name}


def write_mstr_cycle_report(outputs_dir: Path, payload: dict[str, Any]) -> None:
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "mstr-cycle-radar-report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# KQUANT MSTR Cycle Bottom Radar",
        "",
        f"- Run: `{payload['run_id']}`",
        f"- Level: `{payload['level']}`",
        f"- Bottom score: `{payload['bottom_score']}`",
        f"- Distribution risk score: `{payload['distribution_risk_score']}`",
        f"- Provider: `{payload['provider_status']}` / errors `{payload['provider_error_count']}`",
        f"- BTC reference only: `{payload['btc_reference_only']}`",
        f"- Live-only policy: `{payload['live_only_policy']}`",
        "",
        "## Components",
        "",
    ]
    for name, component in payload["components"].items():
        component_reasons = component.get("reasons", component.get("risk_warnings", []))
        if component.get("reason"):
            component_reasons = [component["reason"], *component_reasons]
        lines.extend(
            [
                f"### {name}",
                "",
                f"- Status: `{component.get('status')}`",
                f"- Score: `{component.get('score')}`",
                f"- Metrics: `{component.get('metrics', {})}`",
                f"- Reasons: {'; '.join(str(item) for item in component_reasons)}",
                "",
            ]
        )
    tracker_metrics = payload.get("strategy_tracker_metrics", {})
    lines.extend(
        [
            "## StrategyTracker Metrics",
            "",
            f"- Status: `{tracker_metrics.get('status')}`",
            f"- Tracker provider: `{tracker_metrics.get('tracker_provider_status')}`",
            f"- Source: `{tracker_metrics.get('tracker_source')}`",
            f"- As of: `{tracker_metrics.get('as_of_date')}`",
            f"- Policy: {tracker_metrics.get('calculation_policy')}",
            f"- Missing tracker fields: `{tracker_metrics.get('missing_tracker_fields', [])}`",
            "",
            "### Premium / NAV",
            "",
            f"- Metrics: `{payload.get('premium_nav_metrics', {})}`",
            "",
            "### BTC Per Share / Yield",
            "",
            f"- Share metrics: `{payload.get('share_metrics', {})}`",
            f"- BTC yield metrics: `{payload.get('btc_yield_metrics', {})}`",
            "",
            "### Debt and Dilution",
            "",
            f"- Debt/financing metrics: `{payload.get('debt_financing_metrics', {})}`",
            "",
            "### Liquidity and Benchmark",
            "",
            f"- Liquidity metrics: `{payload.get('liquidity_metrics', {})}`",
            f"- Benchmark metrics: `{payload.get('benchmark_metrics', {})}`",
            "",
        ]
    )
    monte_carlo = payload.get("monte_carlo", {})
    dashboard = payload.get("cycle_dashboard", {})
    lines.extend(
        [
            "## Cycle Dashboard",
            "",
            f"- Summary: {dashboard.get('summary')}",
            f"- Review bias: `{dashboard.get('review_bias')}`",
            f"- Read-only: `{dashboard.get('read_only')}`",
            "",
            "### Why Not Yet",
            "",
            *(
                f"- {item.get('label')}: current `{item.get('current')}` / target `{item.get('target')}` - {item.get('why')}"
                for item in dashboard.get("wait_reasons", [])
            ),
            "",
            "### Upgrade Triggers",
            "",
        ]
    )
    for trigger in dashboard.get("upgrade_triggers", []):
        lines.extend([f"- {trigger.get('level')}: `{trigger.get('status')}`"])
        lines.extend(f"  - {requirement}" for requirement in trigger.get("requirements", []))
    trigger_monitor = payload.get("trigger_monitor", {})
    lines.extend(
        [
            "",
            "## Trigger Monitor",
            "",
            f"- Next state: {trigger_monitor.get('next_state')}",
            f"- Score gaps: `{trigger_monitor.get('gaps', {})}`",
            "",
            "| Level | Condition | Current | Target | Met |",
            "| --- | --- | ---: | ---: | --- |",
        ]
    )
    for condition in trigger_monitor.get("conditions", []):
        lines.append(
            f"| {condition.get('level')} | {condition.get('name')} | "
            f"{condition.get('current')} | {condition.get('comparator')} {condition.get('target')} | {condition.get('met')} |"
        )
    history = payload.get("cycle_history_summary", {})
    lines.extend(
        [
            "",
            "## Historical Trend",
            "",
            f"- Stored runs in view: `{history.get('run_count')}`",
            f"- Latest level: `{history.get('latest_level')}`",
            f"- Trend: `{history.get('trend')}`",
            f"- Bottom score change: `{history.get('score_change')}`",
            f"- Bottom probability change: `{history.get('probability_change')}`",
            "",
        ]
    )
    ten_x_path = dashboard.get("ten_x_path", {})
    lines.extend(
        [
            "",
            "### 10x Path Map",
            "",
            f"- Current MSTR: `{ten_x_path.get('current_mstr_price')}`",
            f"- Target MSTR 10x: `{ten_x_path.get('target_mstr_price_10x')}`",
            f"- Current BTC: `{ten_x_path.get('current_btc_price')}`",
            f"- Current premium to NAV: `{ten_x_path.get('current_premium_to_nav')}`",
            f"- 24m Monte Carlo P(10x): `{ten_x_path.get('monte_carlo_24m_probability_10x_pct')}%`",
            "",
            "| Premium to NAV | Required BTC Price | BTC Multiple |",
            "| ---: | ---: | ---: |",
        ]
    )
    for row in ten_x_path.get("required_btc_prices", []):
        lines.append(f"| {row.get('premium_to_nav')}x | {row.get('required_btc_price')} | {row.get('btc_multiple_from_current')}x |")
    lines.extend(
        [
            "",
            "### 10x Assumptions",
            "",
            *(f"- {item}" for item in ten_x_path.get("assumptions", [])),
            "",
        ]
    )
    stress = payload.get("path_stress_test", {})
    lines.extend(
        [
            "## 10x Stress Test",
            "",
            f"- Status: `{stress.get('status')}`",
            f"- Question: {stress.get('question', stress.get('reason', 'N/A'))}",
            "",
            "| Dilution | Premium | Required BTC | BTC Multiple |",
            "| ---: | ---: | ---: | ---: |",
        ]
    )
    for row in stress.get("rows", [])[:12]:
        lines.append(
            f"| {row.get('dilution_rate_pct')}% | {row.get('premium_to_nav')}x | "
            f"{row.get('required_btc_price')} | {row.get('btc_multiple_from_current')}x |"
        )
    lines.append("")
    lines.extend(["## Monte Carlo Distribution", ""])
    if monte_carlo.get("status") == "available":
        lines.extend(
            [
                f"- Method: `{monte_carlo.get('method')}`",
                f"- Paths: `{monte_carlo.get('paths')}`",
                f"- Beta to BTC: `{monte_carlo.get('beta_to_btc')}`",
                f"- Weekly regime adjustment: `{monte_carlo.get('regime_adjustment_weekly_pct')}%`",
                "",
                "| Horizon | P10 Return | Median Return | P90 Return | Median Max DD | P(2x) | P(5x) | P(10x) |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for horizon, stats in monte_carlo.get("horizons", {}).items():
            lines.append(
                f"| {horizon} | {stats.get('p10_return_pct')}% | {stats.get('median_return_pct')}% | "
                f"{stats.get('p90_return_pct')}% | {stats.get('median_max_drawdown_pct')}% | "
                f"{stats.get('probability_2x_pct')}% | {stats.get('probability_5x_pct')}% | {stats.get('probability_10x_pct')}% |"
            )
    else:
        lines.append(f"- Unavailable: {monte_carlo.get('reason')}")
    bayes = payload.get("bayesian_bottom", {})
    lines.extend(
        [
            "",
            "## Bayesian Bottom Probability",
            "",
            f"- Prior: `{bayes.get('prior_probability')}%`",
            f"- Bottom probability: `{bayes.get('bottom_probability')}%`",
            f"- Confidence: `{bayes.get('confidence')}%`",
            f"- Confidence band: `{(bayes.get('confidence_band') or {}).get('low')}%` to `{(bayes.get('confidence_band') or {}).get('high')}%`",
            f"- Does not override level: `{bayes.get('does_not_override_level')}`",
            "",
            "### Positive Evidence",
            "",
            *(f"- {item.get('name')}: LR {item.get('likelihood_ratio')} - {item.get('reason')}" for item in bayes.get("positive_evidence", [])),
            "",
            "### Negative Evidence",
            "",
            *(f"- {item.get('name')}: LR {item.get('likelihood_ratio')} - {item.get('reason')}" for item in bayes.get("negative_evidence", [])),
            "",
        ]
    )
    lines.extend(
        [
            "## Blockers",
            "",
            *(f"- {item}" for item in payload["blockers"]),
            "",
            "## Manual Checklist",
            "",
            *(f"- {item}" for item in payload["manual_checklist"]),
            "",
        ]
    )
    journal = payload.get("manual_journal", {})
    lines.extend(
        [
            "## Manual Journal",
            "",
            f"- Entries loaded: `{len(journal.get('entries', []))}`",
            f"- Counts: `{journal.get('counts', {})}`",
            "",
        ]
    )
    for entry in journal.get("entries", [])[:5]:
        lines.append(
            f"- `{entry.get('reviewed_at')}` / `{entry.get('status')}` / `{entry.get('level')}`: {entry.get('notes') or entry.get('outcome') or 'No note'}"
        )
    lines.append("")
    (outputs_dir / "mstr-cycle-radar-report.md").write_text("\n".join(lines), encoding="utf-8")
