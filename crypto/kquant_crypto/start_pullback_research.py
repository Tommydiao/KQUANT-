"""Two preregistered entries; shared legacy execution, no execution-service imports."""
from collections import Counter
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

from .low_frequency_research import DAY, STEP, SYMBOLS, Market, aggregate, digest
from .low_frequency_recovery import independent_segments

HOUR = 3600
FOUR = 4 * HOUR
CANDIDATES = ("START_V1", "PULLBACK_V1")
FLOW = ("quote_volume", "taker_buy_quote_volume", "trade_count")
EXECUTION_POLICY = "DELAYED_BAR_PROXY_1H_CLOSE_PLUS_300S_NOT_QUOTE_OR_EXCHANGE_FILL"


def complete_bars(frame, seconds):
    if not frame.index.is_unique or any(frame.index.to_numpy() % STEP):
        raise ValueError("Duplicate or unaligned source bars")
    if frame.empty:
        raise ValueError("Empty source")
    rules = {"open": ("open", "first"), "high": ("high", "max"),
             "low": ("low", "min"), "close": ("close", "last"),
             "count": ("close", "count")}
    for key in FLOW:
        rules[key] = (key, "sum")
    f = frame.copy()
    values = f[list(FLOW)].to_numpy(float)
    f["valid_flow"] = (np.isfinite(values).all(axis=1) & (values >= 0).all(axis=1)
                       & (values[:, 1] <= values[:, 0])
                       & (values[:, 2] == np.floor(values[:, 2])))
    rules["valid_flow"] = ("valid_flow", "sum")
    out = f.groupby(f.index.to_numpy() // seconds * seconds).agg(**rules)
    out = out.reindex(np.arange(f.index.min() // seconds * seconds,
                               f.index.max() // seconds * seconds + seconds, seconds))
    good = (out["count"] == seconds // STEP) & (out.valid_flow == seconds // STEP)
    out.loc[~good, ["open", "high", "low", "close", *FLOW]] = np.nan
    out["complete"] = good
    return out


def hourly_features(h, c):
    result = h.copy()
    logp = np.log(result.close)
    result["sigma"] = logp.diff().rolling(c["volatility_hours"]).std(ddof=0) * math.sqrt(24)
    result["return_48h"] = (logp - logp.shift(c["market_return_hours"])).where(
        logp.rolling(c["market_return_hours"] + 1).count() == c["market_return_hours"] + 1)
    result["volume_median"] = result.quote_volume.shift(1).rolling(c["volume_median_bars"]).median()
    result.index = result.index + HOUR
    return result


def structure_features(f, c):
    out = f.copy()
    previous_returns = np.log(out.close).diff().shift(1)
    out["upper"] = out.high.shift(1).rolling(c["box_bars"]).max()
    out["lower"] = out.low.shift(1).rolling(c["box_bars"]).min()
    out["short_std"] = previous_returns.rolling(c["compression_short"]).std(ddof=0)
    out["long_std"] = previous_returns.rolling(c["compression_long"]).std(ddof=0)
    out["volume_median"] = out.quote_volume.shift(1).rolling(c["volume_median_bars"]).median()
    return out


def finite(*values):
    return all(value is not None and math.isfinite(float(value)) for value in values)


def market_allowed(own, btc, c):
    if own is None or btc is None:
        return None
    if not finite(own.sigma, own.return_48h, btc.sigma, btc.return_48h):
        return None
    if own.sigma <= 0 or btc.sigma <= 0:
        return None
    return bool(own.return_48h >= -c["market_block_sigma"] * own.sigma
                and btc.return_48h >= -c["market_block_sigma"] * btc.sigma)


def raw_setup(row):
    return bool(finite(row.close, row.upper, row.lower, row.short_std, row.long_std,
                       row.quote_volume, row.volume_median)
                and row.short_std <= row.long_std
                and row.close > row.upper and row.quote_volume > row.volume_median)


def price_plan(symbol, at, row, c):
    reference, sigma = float(row.close), float(row.sigma)
    return {"symbol": symbol, "signal_time": int(at), "confirmation_time": int(at),
            "entry_time": int(at) + c["entry_delay_seconds"], "reference": reference,
            "stop": reference * math.exp(-c["stop_sigma_24h"] * sigma),
            "target": reference * math.exp(c["target_sigma_24h"] * sigma),
            "sigma": sigma, "rank": float(row.return_48h / sigma), "executable": False,
            "target_role": "entry_upper_bound_only_not_take_profit"}


@dataclass
class ResearchMarket:
    market: Market
    signals: dict
    opportunities: list
    episodes: list
    hourly: dict
    eligible_plans: dict
    audit: dict


def prepare(frames, c):
    hourly, structures = {}, {}
    for symbol in SYMBOLS:
        hourly[symbol] = hourly_features(complete_bars(frames[symbol], HOUR), c)
        structures[symbol] = structure_features(complete_bars(frames[symbol], FOUR), c)
    signals = {candidate: {} for candidate in CANDIDATES}
    opportunities, episodes, eligible, regimes = [], [], {}, {}
    counters = Counter()
    policy_hash = digest(c)
    hourly_rows = {s: {int(t): row for t, row in f.iterrows()} for s, f in hourly.items()}
    for symbol in SYMBOLS:
        for at, row in hourly_rows[symbol].items():
            ok = market_allowed(row, hourly_rows["BTCUSDT"].get(at), c)
            if at % FOUR == 0:
                regimes[(symbol, at + STEP)] = ok
            if ok is True and bool(row.complete) and finite(row.close, row.volume_median):
                p = price_plan(symbol, at, row, c)
                p["opportunity_id"] = digest({"symbol": symbol, "at": at, "kind": "random_grid", "policy": policy_hash})
                eligible[(symbol, p["entry_time"])] = p
        episode = None
        last_signal = {candidate: -10**15 for candidate in CANDIDATES}

        def confirm(candidate, setup_start, row, ep):
            at = int(setup_start) + FOUR + HOUR
            h = hourly_rows[symbol].get(at)
            btc = hourly_rows["BTCUSDT"].get(at)
            base = {"candidate_id": candidate, "symbol": symbol, "episode_id": ep["episode_id"],
                    "setup_time": int(setup_start) + FOUR, "confirmation_time": at,
                    "signal_time": at, "entry_time": at + STEP, "upper": ep["upper"], "lower": ep["lower"],
                    "policy_hash": policy_hash, "scope": "DEV_ONLY", "execution_policy": EXECUTION_POLICY,
                    "historical_available_at_proxy": at, "actual_received_at": None,
                    "actual_decision_committed_at": None, "fill_status": "NOT_ATTEMPTED",
                    "label_status": "NOT_APPLICABLE"}
            base["opportunity_id"] = digest({k: base[k] for k in ("candidate_id", "symbol", "episode_id", "confirmation_time", "policy_hash")})
            reasons = []
            if h is None or not bool(h.complete) or not finite(h.close, h.open, h.low, h.quote_volume,
                                                               h.taker_buy_quote_volume, h.volume_median):
                reasons.append("missing_first_confirmation_hour")
            else:
                if h.close <= ep["upper"]:
                    reasons.append("confirmation_not_above_upper")
                if candidate == "START_V1" and h.close <= h.open:
                    reasons.append("confirmation_not_green")
                if candidate == "PULLBACK_V1":
                    if h.close <= row.close:
                        reasons.append("confirmation_not_above_reclaim_close")
                    if h.low < row.low:
                        reasons.append("confirmation_broke_reclaim_low")
                if h.quote_volume <= h.volume_median:
                    reasons.append("confirmation_turnover_not_above_median")
                if h.quote_volume <= 0 or h.taker_buy_quote_volume <= h.quote_volume * .5:
                    reasons.append("confirmation_buy_share_not_above_half")
                ok = market_allowed(h, btc, c)
                if ok is None:
                    reasons.append("market_window_incomplete")
                elif not ok:
                    reasons.append("market_downside_block")
                if finite(h.sigma) and h.sigma > 0:
                    if math.log(h.close / ep["upper"]) > c["entry_extension_sigma"] * h.sigma:
                        reasons.append("overextended")
                    base.update(price_plan(symbol, at, h, c))
                    base["factor_snapshot"] = {"quote_volume": float(h.quote_volume),
                        "taker_buy_quote_volume": float(h.taker_buy_quote_volume),
                        "quote_median": float(h.volume_median), "sigma": float(h.sigma),
                        "return_48h": float(h.return_48h) if finite(h.return_48h) else None}
            base["technical_confirmed"] = not reasons
            if not reasons and at < last_signal[candidate] + c["signal_cooldown_hours"] * HOUR:
                reasons.append("signal_cooldown_24h")
            base["reasons"] = reasons
            base["signal_qualified"] = not reasons
            base["feature_snapshot_hash"] = digest(base.get("factor_snapshot", {"unavailable": True}))
            opportunities.append(base)
            if not reasons:
                last_signal[candidate] = at
                signals[candidate].setdefault(at + STEP, []).append(dict(base))
            counters.update(reasons or ["qualified_" + candidate])

        for start, row in structures[symbol].iterrows():
            start = int(start)
            if episode is not None:
                age = (start - episode["bar_start"]) // FOUR
                reason = None
                if not bool(row.complete):
                    reason = "critical_4h_data_gap"
                elif row.low < episode["lower"]:
                    reason = "structure_low_broken"
                elif age > c["episode_lifetime_bars"]:
                    reason = "episode_expired"
                if reason:
                    episode["ended_at"], episode["end_reason"] = start + FOUR, reason
                    episode = None
                    counters[reason] += 1
                    continue
                if (not episode["pullback_attempted"] and 1 <= age <= c["episode_lifetime_bars"]
                        and row.low <= episode["upper"] and row.close >= episode["upper"]
                        and row.low > episode["lower"]):
                    episode["pullback_attempted"] = True
                    confirm("PULLBACK_V1", start, row, episode)
                continue
            if not raw_setup(row):
                counters["no_qualified_4h_setup"] += 1
                continue
            episode = {"symbol": symbol, "bar_start": start, "setup_time": start + FOUR,
                       "upper": float(row.upper), "lower": float(row.lower),
                       "pullback_attempted": False, "ended_at": None, "end_reason": "observation_end"}
            episode["episode_id"] = digest({"symbol": symbol, "bar_start": start, "policy": policy_hash})
            episodes.append(episode)
            confirm("START_V1", start, row, episode)
    price_frames = {s: f[["open", "high", "low", "close", "volume"]].copy() for s, f in frames.items()}
    market = Market(price_frames, {s: aggregate(f, DAY) for s, f in price_frames.items()},
                    {s: aggregate(f, FOUR) for s, f in price_frames.items()}, {}, regimes, eligible)
    return ResearchMarket(market, signals, opportunities, episodes, hourly, eligible, dict(counters))


def run_segments(research, c, candidate, start, end, signals, halts, multiplier=1, excluded=()):
    if candidate not in CANDIDATES:
        raise ValueError("Unknown research entry")
    result = independent_segments(research.market, c, "LF_TRAIL_V1", start, end,
                                  signals, halts, multiplier, excluded)
    for seg in result:
        for row in seg["result"]["trades"]:
            row.update(candidate_id=candidate, protection_engine="LF_TRAIL_V1",
                       execution_policy=EXECUTION_POLICY, fill_status="FILLED_PROXY", scope="DEV_ONLY",
                       r_denominator_policy="BASE_INITIAL_NET_RISK" if multiplier == 1 else "SCENARIO_INITIAL_NET_RISK")
    return result


def random_frequency(research, c, training_end):
    result = {}
    for candidate in CANDIDATES:
        result[candidate] = {}
        for symbol in SYMBOLS:
            n = sum(p["symbol"] == symbol for t, ps in research.signals[candidate].items() if t < training_end for p in ps)
            d = sum(s == symbol and t < training_end for s, t in research.eligible_plans)
            result[candidate][symbol] = {"qualified_signals": n, "eligible_hours": d, "rate": n / d if d else 0.0}
    return result


def random_signals(research, c, candidate, rates):
    rng = np.random.default_rng(c["seed"] + CANDIDATES.index(candidate))
    result, last = {}, {s: -10**15 for s in SYMBOLS}
    for (s, t), p in sorted(research.eligible_plans.items(), key=lambda x: (x[0][1], SYMBOLS.index(x[0][0]))):
        chosen = rng.random() < rates[candidate][s]["rate"]
        if chosen and t >= last[s] + c["signal_cooldown_hours"] * HOUR:
            last[s] = t
            result.setdefault(t, []).append(dict(p, candidate_id=candidate, diagnostic_control=True))
    return result
