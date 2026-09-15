"""Isolated, deterministic spot research. No account or execution dependencies."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

DAY = 86400
STEP = 300
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
CANDIDATES = ("LF_FIXED_V1", "LF_TRAIL_V1")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def stamp(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())


def load_contract(path):
    c = json.loads(Path(path).read_text(encoding="utf-8"))
    if c["scope"] != "DEV_ONLY" or c["execution_enabled"] or tuple(c["symbols"]) != SYMBOLS:
        raise ValueError("Invalid research boundary")
    if tuple(c["candidates"]) != CANDIDATES:
        raise ValueError("Only the two registered exits are allowed")
    if stamp(c["data_end_exclusive"]) > c["protected_tail_start"]:
        raise ValueError("Requested history intersects restricted tail")
    return c


def aggregate(frame, seconds):
    """Return complete, aligned groups only. A gap cannot become a daily close."""
    group = frame.index.to_numpy() // seconds * seconds
    out = frame.groupby(group).agg(open=("open", "first"), high=("high", "max"),
                                   low=("low", "min"), close=("close", "last"),
                                   count=("close", "count"))
    return out[out["count"] == seconds // STEP]


@dataclass
class Market:
    frames: dict
    daily: dict
    four: dict
    signals: dict
    regimes: dict
    plan_rows: dict


def prepare_market(frames, c):
    daily, four, features = {}, {}, {}
    for symbol in SYMBOLS:
        f = frames[symbol].sort_index()
        if not f.index.is_unique or any(f.index.to_numpy() % STEP):
            raise ValueError("Duplicate or unaligned bars")
        daily[symbol] = aggregate(f, DAY)
        four[symbol] = aggregate(f, 4 * 3600)
        d = daily[symbol].reindex(np.arange(f.index.min() // DAY * DAY, f.index.max() // DAY * DAY + DAY, DAY))
        logp = np.log(d.close)
        ret = logp.diff()
        prior_max = d.close.shift(1).rolling(c["breakout_days"]).max()
        complete = d.close.rolling(c["momentum_days"] + 1).count() == c["momentum_days"] + 1
        h = aggregate(f, 3600).reindex(np.arange(f.index.min() // 3600 * 3600, f.index.max() // 3600 * 3600 + 3600, 3600))
        sigma = np.log(h.close).diff().rolling(c["volatility_hours"]).std(ddof=0) * math.sqrt(24)
        feature = pd.DataFrame(index=d.index)
        feature["reference"] = d.close
        feature["momentum"] = (logp - logp.shift(c["momentum_days"])).where(complete)
        feature["breakout"] = d.close > prior_max
        feature["rank"] = (logp - logp.shift(c["breakout_days"])) / (ret.rolling(c["breakout_days"]).std(ddof=0) * math.sqrt(c["breakout_days"]))
        feature["sigma"] = sigma.reindex(d.index + DAY - 3600).to_numpy()
        features[symbol] = feature
    signals, regimes, plans = {}, {}, {}
    for symbol in SYMBOLS:
        for day, row in features[symbol].iterrows():
            time = int(day) + DAY + c["entry_delay_seconds"]
            btc = features["BTCUSDT"].momentum.get(day, math.nan)
            valid = all(math.isfinite(float(x)) for x in (row.momentum, btc, row.sigma, row["rank"])) and row.sigma > 0
            regime = bool(valid and row.momentum > 0 and btc > 0)
            regimes[(symbol, time)] = regime if valid else None
            if not valid:
                continue
            reference = float(row.reference)
            plan = {"symbol": symbol, "signal_time": time - c["entry_delay_seconds"],
                    "entry_time": time, "reference": reference,
                    "stop": reference * math.exp(-c["stop_sigma_24h"] * row.sigma),
                    "target": reference * math.exp(c["target_sigma_24h"] * row.sigma),
                    "rank": float(row["rank"]), "sigma": float(row.sigma)}
            plan["opportunity_id"] = digest(plan)
            plans[(symbol, time)] = plan
            if regime and row.breakout:
                signals.setdefault(time, []).append(plan)
    return Market(frames, daily, four, signals, regimes, plans)


def protection(position, bar, candidate):
    o, h, low, _ = bar
    if o <= position["stop"]:
        return float(o), "gap_stop", True
    if candidate == "LF_FIXED_V1" and o >= position["target"]:
        return float(o), "gap_target", True
    if low <= position["stop"]:
        return position["stop"], "stop", False
    if candidate == "LF_FIXED_V1" and h >= position["target"]:
        return position["target"], "target", False
    return None


def next_trailing_stop(position, close):
    return max(position["stop"], close - position["initial_distance"])


def metrics(trades, curve):
    good = [t for t in trades if t["label_status"] == "MATURE"]
    pnl = np.asarray([t["net_pnl"] for t in good], float)
    rs = np.asarray([t["net_r"] for t in good], float)
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    eq = np.asarray([p["equity"] for p in curve], float)
    return {"trades": len(good), "wins": len(wins), "win_rate": float(np.mean(pnl > 0)) if len(pnl) else None,
            "pf": float(wins.sum() / -losses.sum()) if len(losses) else None,
            "payoff": float(wins.mean() / -losses.mean()) if len(wins) and len(losses) else None,
            "net_pnl": float(pnl.sum()), "mean_r": float(rs.mean()) if len(rs) else None,
            "pf_r": float(rs[rs > 0].sum() / -rs[rs < 0].sum()) if any(rs < 0) else None,
            "max_drawdown": float(np.max(1 - eq / np.maximum.accumulate(eq))) if len(eq) else None,
            "capital_return": float(eq[-1] / eq[0] - 1) if len(eq) else None,
            "fees": sum(t["fees"] for t in good),
            "mean_holding_days": float(np.mean([(t["exit_time"] - t["entry_time"]) / DAY for t in good])) if good else None,
            "censored": sum(t["label_status"] != "MATURE" for t in trades)}


def replay(market, c, candidate, start, end, multiplier=1, signals=None, excluded=(), independent=False, confirmed_halts=frozenset()):
    """Shared replay/decision kernel. Never admits entries using outcome labels."""
    if candidate not in CANDIDATES:
        raise ValueError(candidate)
    signals = market.signals if signals is None else signals
    timeline = np.arange(start, end, STEP, dtype=np.int64)
    arrays = {s: market.frames[s].reindex(timeline)[["open", "high", "low", "close"]].to_numpy() for s in SYMBOLS}
    for s, at in confirmed_halts:
        if s not in SYMBOLS or at % STEP:
            raise ValueError("Invalid halt identity/time")
        if at in market.frames[s].index:
            raise ValueError("Halt conflicts with observed bar")
    four = {s: {int(t) + 14400: float(row.close) for t, row in market.four[s].iterrows()} for s in SYMBOLS}
    fee, slip = c["fee_bps_side"] * multiplier / 10000, c["slippage_bps_side"] * multiplier / 10000
    cash = c["capital"]
    positions, marks, last_exit = {}, {}, {}
    trades, events = [], []
    curve = [{"time": start, "equity": cash, "uncertain": False}]
    day, daily_base, daily_pause, streak, paused_until = None, cash, False, 0, 0
    uncertain = False

    def equity():
        return cash + sum(p["quantity"] * marks.get(s, p["entry_price"]) * (1 - slip) * (1 - fee) for s, p in positions.items())

    def close(s, reference, at, reason):
        nonlocal cash, streak, paused_until
        p = positions.pop(s)
        price = reference * (1 - slip)
        exit_fee = p["quantity"] * price * fee
        cash += p["quantity"] * price - exit_fee
        pnl = p["quantity"] * (price - p["entry_price"]) - p["entry_fee"] - exit_fee
        trades.append({**p, "candidate_id": candidate, "label_status": "MATURE", "exit_time": at,
                       "exit_reference": reference, "exit_price": price, "exit_reason": reason,
                       "fees": p["entry_fee"] + exit_fee, "net_pnl": pnl, "net_r": pnl / p["risk_amount"],
                       "execution_policy": "closed_daily_signal_next_0005_5m_open_proxy"})
        last_exit[s] = at
        streak = streak + 1 if pnl < 0 else 0
        if streak >= c["loss_streak"]:
            paused_until, streak = at + c["pause_hours"] * 3600, 0

    for i, t0 in enumerate(timeline):
        t = int(t0)
        current = {s: arrays[s][i] for s in SYMBOLS}
        if day != t // DAY:
            day, daily_base, daily_pause = t // DAY, equity(), False
        for s, b in current.items():
            if math.isfinite(b[0]):
                marks[s] = float(b[0])
        for s in list(positions):
            p, b = positions[s], current[s]
            if (s, t) in confirmed_halts:
                events.append({"time": t, "symbol": s, "reason": "confirmed_venue_halt_no_execution"})
                continue
            if p.get("path_unknown"):
                continue
            if not math.isfinite(b[0]):
                p["path_unknown"], uncertain = True, True
                events.append({"time": t, "symbol": s, "reason": "unresolved_holding_gap"})
                continue
            # Opening protection precedes scheduled exits and all new entries.
            if b[0] <= p["stop"]:
                close(s, float(b[0]), t, "gap_stop")
            elif candidate == "LF_FIXED_V1" and b[0] >= p["target"]:
                close(s, float(b[0]), t, "gap_target")
            elif t >= p["expires_at"]:
                close(s, float(b[0]), t, "time_exit")
            elif (s, t) in market.regimes and market.regimes[(s, t)] is False:
                close(s, float(b[0]), t, "regime_exit")
        if equity() <= daily_base * (1 - c["daily_loss_limit"]):
            daily_pause = True
        for plan in sorted(signals.get(t, []), key=lambda p: (-p["rank"], SYMBOLS.index(p["symbol"]))):
            s, reason = plan["symbol"], None
            b = current[s]
            if s in excluded:
                continue
            if (s, t) in confirmed_halts: reason = "confirmed_venue_halt_no_entry"
            elif uncertain: reason = "equity_uncertain"
            elif not independent and daily_pause: reason = "daily_loss_pause"
            elif not independent and t < paused_until: reason = "loss_streak_pause"
            elif s in positions: reason = "symbol_occupied"
            elif not independent and s in last_exit and t < last_exit[s] + c["cooldown_hours"] * 3600: reason = "cooldown"
            elif not independent and len(positions) >= c["max_positions"]: reason = "position_limit"
            elif not math.isfinite(b[0]): reason = "missing_entry_bar"
            elif b[0] <= plan["stop"] or b[0] >= plan["target"]: reason = "entry_outside_frozen_plan"
            if reason:
                events.append({"time": t, "symbol": s, "opportunity_id": plan["opportunity_id"], "reason": reason})
                continue
            entry = float(b[0]) * (1 + slip)
            stop_fill = plan["stop"] * (1 - slip)
            unit_risk = entry - stop_fill + fee * (entry + stop_fill)
            eq = equity()
            budget = min(eq * c["risk_per_trade"], eq * c["max_open_risk"] - sum(p["risk_amount"] for p in positions.values()))
            q = min(max(0, budget) / unit_risk, eq * c["max_symbol_notional"] / entry, cash / (entry * (1 + fee)))
            if q <= 0:
                events.append({"time": t, "symbol": s, "reason": "risk_or_cash"})
                continue
            entry_fee = q * entry * fee
            cash -= q * entry + entry_fee
            positions[s] = {**plan, "entry_reference": float(b[0]), "entry_price": entry,
                            "quantity": q, "entry_fee": entry_fee, "base_r_per_unit": unit_risk,
                            "risk_amount": q * unit_risk, "initial_stop": plan["stop"],
                            "initial_distance": plan["reference"] - plan["stop"],
                            "expires_at": t + c["max_holding_days"] * DAY}
        for s in list(positions):
            p, b = positions[s], current[s]
            if p.get("path_unknown") or (s, t) in confirmed_halts:
                continue
            hit = protection(p, b, candidate)
            if hit:
                reference, reason, opening = hit
                close(s, reference, t if opening else t + STEP, reason)
            elif candidate == "LF_TRAIL_V1" and t + STEP in four[s] and t + STEP - 14400 >= p["entry_time"]:
                # Update after testing the entire old bar; never act retrospectively.
                p["stop"] = next_trailing_stop(p, four[s][t + STEP])
        for s, b in current.items():
            if math.isfinite(b[3]): marks[s] = float(b[3])
        value = equity()
        if value <= daily_base * (1 - c["daily_loss_limit"]): daily_pause = True
        curve.append({"time": t + STEP, "equity": value, "uncertain": uncertain})
    for s, p in positions.items():
        trades.append({**p, "candidate_id": candidate, "label_status": "CENSORED", "exit_time": end,
                       "exit_reason": "data_gap" if p.get("path_unknown") else "observation_end",
                       "net_pnl": None, "net_r": None, "fees": p["entry_fee"]})
    return {"trades": trades, "equity": curve, "events": events, "metrics": metrics(trades, curve), "uncertain": uncertain or bool(positions)}


def recost(trades, c, multiplier):
    out = []
    fee, slip = c["fee_bps_side"] * multiplier / 10000, c["slippage_bps_side"] * multiplier / 10000
    for t in trades:
        if t["label_status"] != "MATURE": continue
        en, ex = t["entry_reference"] * (1 + slip), t["exit_reference"] * (1 - slip)
        fees = t["quantity"] * fee * (en + ex)
        pnl = t["quantity"] * (ex - en) - fees
        out.append({**t, "net_pnl": pnl, "net_r": pnl / t["risk_amount"], "fees": fees,
                    "base_r_denominator_unchanged": True})
    return out


def centered_block_test(trades, start, end, c):
    """Synchronized calendar blocks; null-centered statistic, not raw posterior mass."""
    count = (end - start) // DAY
    sums, counts = np.zeros(count), np.zeros(count)
    for t in trades:
        if t["label_status"] != "MATURE": continue
        i = min(count - 1, (t["exit_time"] - start) // DAY)
        if i >= 0: sums[i] += t["net_r"]; counts[i] += 1
    if counts.sum() == 0:
        return {"p_value": None, "mean_r_lower": None, "status": "NO_TRADES"}
    observed = sums.sum() / counts.sum()
    length = c["block_days"]
    rng = np.random.default_rng(c["seed"])
    samples, nulls = [], []
    for _ in range(c["bootstrap_paths"]):
        starts = rng.integers(0, count - length + 1, size=math.ceil(count / length))
        idx = np.concatenate([np.arange(s, s + length) for s in starts])[:count]
        n = counts[idx].sum()
        if n:
            samples.append(sums[idx].sum() / n)
            nulls.append((sums[idx] - observed * counts[idx]).sum() / n)
    return {"p_value": float((1 + sum(x >= observed for x in nulls)) / (1 + len(nulls))),
            "mean_r_lower": float(np.quantile(samples, .025)), "mean_r_upper": float(np.quantile(samples, .975)),
            "mean_r": float(observed), "valid_paths": len(samples),
            "status": "DEV_ONLY_CENTERED_MOVING_BLOCK_APPROXIMATE_TEST",
            "independence_claim": False}
