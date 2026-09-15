"""Immutable, isolated development research CLI. No database or network writes."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd

from kquant_crypto.low_frequency_research import DAY, STEP, SYMBOLS, digest, metrics, recost, stamp, centered_block_test
from kquant_crypto.low_frequency_recovery import write, csv_write, safe_metrics
from kquant_crypto.start_pullback_research import (CANDIDATES, HOUR, FOUR, FLOW, prepare,
    run_segments, random_frequency, random_signals, EXECUTION_POLICY)

CONFIG = ROOT / "config/start_pullback_research_v1.json"
CODE = [Path(__file__), ROOT / "kquant_crypto/start_pullback_research.py",
        ROOT / "kquant_crypto/low_frequency_research.py", ROOT / "kquant_crypto/low_frequency_recovery.py",
        ROOT / "scripts/verify_start_pullback_research.py", ROOT / "tests/test_start_pullback_research.py"]


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sources(c):
    return (ROOT / "outputs/low_frequency_research" / c["source_run"],
            ROOT / "outputs/low_frequency_recovery" / c["recovery_run"])


def check_contract(c):
    if (c["scope"] != "DEV_ONLY" or c["execution_enabled"] or tuple(c["symbols"]) != SYMBOLS
            or tuple(c["candidates"]) != CANDIDATES or c["data_start"] != "2021-01-01"
            or c["data_end_exclusive"] != "2025-01-01"
            or stamp(c["data_end_exclusive"]) > c["protected_tail_start"]):
        raise ValueError("Research boundary violated")
    old = read(sources(c)[0] / "contract.json")
    for key in ("capital", "risk_per_trade", "max_open_risk", "max_positions", "max_symbol_notional",
                "daily_loss_limit", "loss_streak", "pause_hours", "cooldown_hours", "volatility_hours",
                "stop_sigma_24h", "target_sigma_24h", "max_holding_days", "purge_days", "embargo_days",
                "fee_bps_side", "slippage_bps_side", "entry_delay_seconds"):
        if c[key] != old[key]:
            raise ValueError("Frozen protection/risk/cost changed: " + key)


def freeze(out):
    c = read(CONFIG)
    check_contract(c)
    source, recovery = sources(c)
    out.mkdir(parents=True, exist_ok=False)
    write(out / "contract.json", c)
    protected = []
    for folder in (source, recovery):
        protected += [p for p in folder.iterdir() if p.is_file()]
    protected += [ROOT / "config/low_frequency_research_v1.json", *CODE[2:4],
                  ROOT / "kquant_crypto/dashboard/app.py", ROOT / "kquant_crypto/gateway.py",
                  ROOT / "kquant_crypto/strategy_manifest.py", ROOT.parent / "web/src/unified/App.tsx"]
    manifest = {str(p): sha(p) for p in sorted(set(protected))}
    write(out / "protected_manifest.json", manifest)
    copy = out / "source_snapshot"
    copy.mkdir()
    for p in CODE:
        shutil.copy2(p, copy / p.name)
    inventory = subprocess.check_output(["powershell", "-NoProfile", "-Command",
        "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python|node' } | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CreationDate | ConvertTo-Json"], text=True)
    write(out / "process_inventory.json", json.loads(inventory))
    write(out / "preregistration.json", {
        "registered_at": datetime.now(timezone.utc).isoformat(), "policy_hash": digest(c),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "preexisting_git_status": subprocess.check_output(["git", "status", "--short"], cwd=ROOT, text=True),
        "python": sys.executable, "module_root": str(ROOT), "source": str(source), "recovery": str(recovery),
        "file_ownership": [str(CONFIG), str(CODE[0]), str(CODE[1]), str(ROOT / "tests/test_start_pullback_research.py")],
        "policy_seed_is_fixed_not_a_tuning_dimension": True,
        "source_hashes": {str(p): sha(p) for p in CODE}, "models_trained": False,
        "exposure": c["exposure"], "restricted_history_consumed": False,
        "existing_processes_modified": False, "old_database_writes": False,
        "contracts": c["contracts"]})


def baseline_check(out):
    errors = [name for name, expected in read(out / "protected_manifest.json").items()
              if not Path(name).exists() or sha(Path(name)) != expected]
    if errors:
        raise ValueError("Protected baseline changed: " + repr(errors))
    return {"checked_files": len(read(out / "protected_manifest.json")), "changed": errors}


def phase_path(out, name):
    index = read(out / (name + "_index.json"))
    folder = out / index["directory"]
    for filename, expected in index["hashes"].items():
        if sha(folder / filename) != expected:
            raise ValueError("Completed phase artifact drift: " + filename)
    return folder


def archive_frame(path, expected, verify_checksum=True):
    if sha(path) != expected:
        raise ValueError("Archive checksum mismatch: " + str(path))
    if verify_checksum and path.with_name(path.name + ".CHECKSUM").read_text().split()[0] != expected:
        raise ValueError("Official checksum mismatch")
    with zipfile.ZipFile(path) as z:
        if len(z.namelist()) != 1:
            raise ValueError("Unexpected archive members")
        with z.open(z.namelist()[0]) as stream:
            frame = pd.read_csv(stream, header=None)
    return frame


def native_flow(raw, step=STEP):
    times = raw[0].astype("int64")
    if (times >= 10**14).any() or (times % (step * 1000)).any():
        raise ValueError("Unexpected time unit/alignment in authorized 2021-2024 archive")
    valid = raw[6].astype("int64") == times + step * 1000 - 1
    result = pd.DataFrame({"quote_volume": raw[7].astype(float).to_numpy(),
        "taker_buy_quote_volume": raw[10].astype(float).to_numpy(),
        "trade_count": raw[8].astype(float).to_numpy()}, index=times.to_numpy() // 1000)
    result = result.loc[valid.to_numpy()]
    if not result.index.is_unique:
        raise ValueError("Duplicate native times")
    return result


def build(out, stage, c):
    baseline_check(out)
    source, recovery = sources(c)
    original = read(source / "archive_manifest.json")
    recovered = read(recovery / "data_changes.json")
    supplements = read(recovery / "supplemental_sources.json")
    manifest, input_sources = {}, []
    for symbol in SYMBOLS:
        path = recovery / (symbol + "_5m.parquet")
        if sha(path) != recovered["manifest"][symbol]:
            raise ValueError("Recovered price source changed")
        price = pd.read_parquet(path)
        parts = []
        selected = [item for item in original if item["symbol"] == symbol]
        if len(selected) != 48 or {(x["year"], x["month"]) for x in selected} != {(y, m) for y in range(2021, 2025) for m in range(1, 13)}:
            raise ValueError("Incomplete/unauthorized monthly manifest")
        for item in selected:
            raw = archive_frame(source / "archives" / item["file"], item["sha256"])
            parts.append(native_flow(raw))
            input_sources.append(dict(item, source_kind="native_monthly_5m"))
        native = pd.concat(parts).sort_index()
        if not native.index.is_unique:
            raise ValueError("Duplicate archive timestamps")
        for change in recovered["changes"]:
            if change["symbol"] != symbol or change["kind"] != "reconstructed_five_complete_native_minutes":
                continue
            t = change["time"]
            date = datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
            info = next(s for s in supplements if s["symbol"] == symbol and s["date"] == date and s["kind"] == "1m" and s["status"] == "VERIFIED")
            minute = native_flow(archive_frame(recovery / "archives" / info["file"], info["sha256"]), 60)
            sub = minute.reindex(np.arange(t, t + STEP, 60))
            if sub.isna().any().any():
                raise ValueError("Missing native reconstructed flow minutes")
            native.loc[t] = sub.sum()
            input_sources.append(dict(info, source_kind="sum_five_native_minutes"))
        frame = price.join(native, how="left")
        vals = frame[list(FLOW)].to_numpy()
        valid = (np.isfinite(vals).all(axis=1) & (vals >= 0).all(axis=1)
                 & (vals[:, 1] <= vals[:, 0]) & (vals[:, 2] == np.floor(vals[:, 2])))
        invalid_times = frame.index[~valid].tolist()
        frame.loc[~valid, list(FLOW)] = np.nan
        if frame.index.min() < stamp(c["data_start"]) or frame.index.max() >= stamp(c["data_end_exclusive"]):
            raise ValueError("Data outside authorized dates")
        dest = stage / (symbol + "_5m.parquet")
        with dest.open("xb") as handle:
            frame.to_parquet(handle)
        manifest[symbol] = {"rows": len(frame), "valid_flow_rows": int(valid.sum()),
            "invalid_flow_times": invalid_times, "missing_5m": int((stamp(c["data_end_exclusive"]) - stamp(c["data_start"])) // STEP - len(frame)),
            "start": int(frame.index.min()), "end_exclusive": int(frame.index.max()) + STEP,
            "sha256": sha(dest), "recovered_ohlcv_hash": sha(path)}
        print("built", symbol, manifest[symbol]["rows"], "invalid native flow", len(invalid_times), flush=True)
    write(stage / "manifest.json", {"symbols": manifest, "data_hash": digest(manifest),
        "source_hashes": input_sources, "confirmed_halts": recovered["confirmed_halts"],
        "scope": "DEV_ONLY", "independent_oos": False, "synthetic_flow": False,
        "historical_available_at": "candle_close_proxy_not_historical_receipt",
        "actual_archive_receipt": "source_manifests_verified_at_not_backdated",
        "policy_hash": digest(c), "baseline_guard": baseline_check(out)})


def load_research(out, c):
    folder = phase_path(out, "build")
    m = read(folder / "manifest.json")
    if m["policy_hash"] != digest(c):
        raise ValueError("Dataset policy mismatch")
    frames = {s: pd.read_parquet(folder / (s + "_5m.parquet")) for s in SYMBOLS}
    research = prepare(frames, c)
    return research, frozenset(tuple(x) for x in m["confirmed_halts"]), m


def entry_windows(c):
    return [(stamp(f"{y}-01-01") + c["embargo_days"] * DAY,
             stamp(f"{y+1}-01-01") - c["max_holding_days"] * DAY - STEP,
             stamp(f"{y+1}-01-01")) for y in c["evaluation_years"]]


def mask_signals(signals, windows):
    return {t: ps for t, ps in signals.items() if any(start <= t < entry_end for start, entry_end, _ in windows)}


def persist_segments(stage, prefix, segments):
    trades, summaries = [], []
    for number, seg in enumerate(segments):
        r = seg["result"]
        csv_write(stage / f"{prefix}_{number:02d}_trades.csv.gz", r["trades"])
        csv_write(stage / f"{prefix}_{number:02d}_equity.csv.gz", r["equity"])
        csv_write(stage / f"{prefix}_{number:02d}_events.csv.gz", r["events"])
        trades += r["trades"]
        summaries.append({k: v for k, v in seg.items() if k != "result"} | {
            "metrics": safe_metrics(r), "uncertain": r["uncertain"],
            "events": dict(Counter(e["reason"] for e in r["events"]))})
    result = metrics(trades, segments[0]["result"]["equity"] if len(segments) == 1 else [])
    if len(segments) != 1 or any(seg["result"]["uncertain"] for seg in segments):
        result["max_drawdown"] = result["capital_return"] = None
    return {"metrics": result, "segments": summaries,
            "by_symbol": {s: metrics([t for t in trades if t["symbol"] == s], []) for s in SYMBOLS}}, trades


def attach_outcomes(research, candidate, segments, windows):
    fills = {t["opportunity_id"]: t for seg in segments for t in seg["result"]["trades"]}
    denials = {e["opportunity_id"]: e["reason"] for seg in segments for e in seg["result"]["events"] if "opportunity_id" in e}
    rows = []
    for p in research.opportunities:
        if p["candidate_id"] != candidate:
            continue
        q = dict(p)
        allowed = any(start <= p["entry_time"] < entry_end for start, entry_end, _ in windows)
        q["partition"] = "DEV_EVALUATION" if allowed else ("DEVELOPMENT" if p["entry_time"] < stamp("2022-01-01") else "PURGED_OR_EMBARGOED")
        t = fills.get(p["opportunity_id"])
        if t:
            q.update(fill_status="FILLED_PROXY", label_status=t["label_status"],
                     exit_time=t["exit_time"], exit_reason=t["exit_reason"], net_pnl=t["net_pnl"], net_r=t["net_r"])
        else:
            q.update(fill_status="NOT_FILLED", label_status="NOT_APPLICABLE", net_pnl=None, net_r=None,
                     no_fill_reason=";".join(p["reasons"]) if p["reasons"] else
                     ("outside_entry_partition" if not allowed else denials.get(p["opportunity_id"], "account_path_unavailable")))
        q.pop("factor_snapshot", None)
        rows.append(q)
    return rows


def replay_phase(out, stage, c):
    research, halts, manifest = load_research(out, c)
    windows = entry_windows(c)
    start, end = windows[0][0], windows[-1][2]
    csv_write(stage / "opportunities.csv.gz", research.opportunities)
    write(stage / "episodes.json", research.episodes)
    rates = random_frequency(research, c, stamp("2022-01-01") - c["purge_days"] * DAY)
    write(stage / "random_frequency_freeze.json", {"rates": rates, "seed": c["seed"],
          "training_end_exclusive": stamp("2022-01-01") - c["purge_days"] * DAY})
    result = {}
    for candidate in CANDIDATES:
        signals = mask_signals(research.signals[candidate], windows)
        candidate_result, base = {}, None
        for scenario, multiplier in (("base", 1), ("stress", 2)):
            segments = run_segments(research, c, candidate, start, end, signals, halts, multiplier)
            info, trades = persist_segments(stage, candidate + "_continuous_" + scenario, segments)
            candidate_result[scenario] = info
            if scenario == "base":
                base = trades
                rows = attach_outcomes(research, candidate, segments, windows)
                csv_write(stage / (candidate + "_opportunity_outcomes.csv.gz"), rows)
                candidate_result["opportunity_counts"] = dict(Counter(
                    f"{p['partition']}|{p['fill_status']}|{p['label_status']}" for p in rows))
                candidate_result["no_fill_reasons"] = dict(Counter(p.get("no_fill_reason") for p in rows
                    if p["partition"] == "DEV_EVALUATION" and p["fill_status"] == "NOT_FILLED"))
            print(candidate, "continuous", scenario, info["metrics"], flush=True)
        fixed = recost(base, c, 2)
        csv_write(stage / (candidate + "_fixed_double_cost.csv.gz"), fixed)
        candidate_result["fixed_double_cost"] = metrics(fixed, [])
        candidate_result["zero_cost_fixed_sequence"] = metrics(recost(base, c, 0), [])
        candidate_result["uncertainty"] = centered_block_test(base, start, end, c)
        annual = []
        for year, window in zip(c["evaluation_years"], windows):
            sig = mask_signals(signals, [window])
            segments = run_segments(research, c, candidate, window[0], window[2], sig, halts)
            info, _ = persist_segments(stage, candidate + f"_{year}_base_reset", segments)
            annual.append({"year": year, **info})
            print(candidate, "annual diagnostic", year, info["metrics"]["trades"], flush=True)
        candidate_result["annual_reset_diagnostics"] = annual
        result[candidate] = candidate_result
    write(stage / "results.json", {"candidates": result, "policy_hash": digest(c), "data_hash": manifest["data_hash"],
        "setup_audit": research.audit, "entry_windows": windows, "scope": "DEV_ONLY", "execution_enabled": False,
        "primary_account": "continuous_no_annual_capital_resets", "annual_resets_not_pooled_for_gate": True,
        "r_units": {"base": "BASE_INITIAL_NET_RISK", "fixed_double_cost": "BASE_INITIAL_NET_RISK",
                    "full_stress": "SCENARIO_INITIAL_NET_RISK_NOT_BASE_R"}, "baseline_guard": baseline_check(out)})


def load_primary_trades(folder, candidate):
    rows = []
    for p in sorted(folder.glob(candidate + "_continuous_base_*_trades.csv.gz")):
        try:
            f = pd.read_csv(p)
        except pd.errors.EmptyDataError:
            continue
        for row in f.to_dict("records"):
            for key in ("net_pnl", "net_r", "exit_reference"):
                if key in row and pd.isna(row[key]): row[key] = None
            rows.append(row)
    return rows


def buy_hold(research, c, start, end, halts):
    timeline = np.arange(start, end, STEP)
    curve = np.zeros(len(timeline))
    fee, slip = c["fee_bps_side"] / 10000, c["slippage_bps_side"] / 10000
    unknown = 0
    for symbol in SYMBOLS:
        f = research.market.frames[symbol].reindex(timeline)
        if not np.isfinite(f.open.iloc[0]):
            return {"status": "MISSING_ENTRY", "capital_return": None, "max_drawdown": None}
        unknown += sum((symbol, int(t)) not in halts for t in f.index[f.close.isna()])
        q = c["capital"] / 3 / (f.open.iloc[0] * (1 + slip) * (1 + fee))
        curve += q * f.close.ffill().to_numpy() * (1 - slip) * (1 - fee)
    eq = np.r_[c["capital"], curve]
    return {"status": "UNKNOWN_MARKS" if unknown else "KNOWN_PROXY_MARKS", "unknown_bars": unknown,
        "capital_return": float(eq[-1] / eq[0] - 1) if not unknown else None,
        "max_drawdown": float(np.max(1 - eq / np.maximum.accumulate(eq))) if not unknown else None,
        "risk_matched": False, "halt_marks": "last_observable_price_not_executable_quote", "cash_return": 0.0}


def controls(out, stage, c):
    research, halts, _ = load_research(out, c)
    replays = phase_path(out, "replay")
    rates = read(replays / "random_frequency_freeze.json")["rates"]
    windows = entry_windows(c)
    start, end = windows[0][0], windows[-1][2]
    results = {}
    for candidate in CANDIDATES:
        trades = load_primary_trades(replays, candidate)
        mature = [t for t in trades if t["label_status"] == "MATURE"]
        sums = {s: sum(t["net_pnl"] for t in mature if t["symbol"] == s) for s in SYMBOLS}
        best = max(SYMBOLS, key=lambda s: sums[s])
        sig = mask_signals(research.signals[candidate], windows)
        segments = run_segments(research, c, candidate, start, end, sig, halts, excluded=(best,))
        leave, _ = persist_segments(stage, candidate + "_leave_best", segments)
        random = mask_signals(random_signals(research, c, candidate, rates), windows)
        random_runs = run_segments(research, c, candidate, start, end, random, halts)
        random_info, _ = persist_segments(stage, candidate + "_random", random_runs)
        largest = max(mature, key=lambda t: t["net_pnl"], default=None)
        remaining = [t for t in mature if largest is None or t["opportunity_id"] != largest["opportunity_id"]]
        results[candidate] = {"leave_best_asset": {"excluded": best, **leave}, "random": random_info,
            "remove_largest_trade": metrics(remaining, []), "by_symbol_profit": sums,
            "removed_winner_id": largest["opportunity_id"] if largest else None,
            "diagnostic_not_an_asset_selection_rule": True}
        print(candidate, "controls", results[candidate]["random"]["metrics"], flush=True)
    pairs = {}
    false_breakouts = []
    for p in research.opportunities:
        if not p["technical_confirmed"] or not any(a <= p["entry_time"] < b for a, b, _ in windows):
            continue
        pairs.setdefault(p["episode_id"], {})[p["candidate_id"]] = p
        at = p["confirmation_time"]
        expected = np.arange(((at // FOUR) + 1) * FOUR, at + DAY + 1, FOUR)
        closes = research.market.four[p["symbol"]].close.reindex(expected - FOUR)
        # Unknown high-frequency paths remain unknown even when endpoint closes exist.
        path = research.market.frames[p["symbol"]].reindex(np.arange(at, at + DAY, STEP))
        unknown = closes.isna().any() or path.close.isna().any()
        false_breakouts.append({"opportunity_id": p["opportunity_id"], "candidate_id": p["candidate_id"],
            "label_scope": "DIAGNOSTIC_NOT_TRADE", "available_at": at + DAY,
            "label_status": "CENSORED" if unknown else "MATURE", "closed_below_upper_within_24h": None if unknown else bool((closes < p["upper"]).any())})
    lead = [{"episode_id": e, "symbol": next(iter(p.values()))["symbol"],
             "start_confirmation": p["START_V1"]["confirmation_time"] if "START_V1" in p else None,
             "pullback_confirmation": p["PULLBACK_V1"]["confirmation_time"] if "PULLBACK_V1" in p else None,
             "lead_hours": (p["PULLBACK_V1"]["confirmation_time"] - p["START_V1"]["confirmation_time"]) / HOUR if len(p) == 2 else None}
            for e, p in pairs.items()]
    csv_write(stage / "paired_signal_lead_time.csv.gz", lead)
    csv_write(stage / "false_breakout_proxy.csv.gz", false_breakouts)
    write(stage / "controls.json", {"candidates": results, "cash": {"return": 0.0},
        "buy_hold": buy_hold(research, c, start, end, halts),
        "paired_signals": sum(p["lead_hours"] is not None for p in lead),
        "paired_lead_hours_mean": float(np.mean([p["lead_hours"] for p in lead if p["lead_hours"] is not None])) if any(p["lead_hours"] is not None for p in lead) else None,
        "false_breakout_proxy_counts": {candidate: {
            "mature": sum(p["candidate_id"] == candidate and p["label_status"] == "MATURE" for p in false_breakouts),
            "censored": sum(p["candidate_id"] == candidate and p["label_status"] == "CENSORED" for p in false_breakouts),
            "closed_below_upper": sum(p["candidate_id"] == candidate and p["closed_below_upper_within_24h"] is True for p in false_breakouts)
        } for candidate in CANDIDATES},
        "missing_pair_not_zero": sum(p["lead_hours"] is None for p in lead),
        "baseline_guard": baseline_check(out)})


def report(out, stage, c):
    rdir, cdir = phase_path(out, "replay"), phase_path(out, "controls")
    replay_results, diagnostic = read(rdir / "results.json"), read(cdir / "controls.json")
    candidates = replay_results["candidates"]
    running = 0.0
    for rank, candidate in enumerate(sorted(CANDIDATES, key=lambda k: candidates[k]["uncertainty"]["p_value"] if candidates[k]["uncertainty"]["p_value"] is not None else 1)):
        p = candidates[candidate]["uncertainty"]["p_value"]
        running = max(running, min(1.0, (2-rank) * (p if p is not None else 1.0)))
        candidates[candidate]["holm_p"] = running
    verification = {"trades_checked": 0, "errors": []}
    for candidate in CANDIDATES:
        info, checks = candidates[candidate], {}
        base = info["base"]["metrics"]
        def ge(value, threshold): return value is not None and value >= threshold
        checks.update(pf=ge(base["pf"], c["targets"]["pf"]), payoff=ge(base["payoff"], c["targets"]["payoff"]),
            positive_mean_r=ge(base["mean_r"], 1e-15), fixed_stress_pf=ge(info["fixed_double_cost"]["pf"], c["targets"]["stress_pf"]),
            full_stress_positive=ge(info["stress"]["metrics"]["mean_r"], 1e-15),
            drawdown=base["max_drawdown"] is not None and base["max_drawdown"] <= c["targets"]["max_drawdown"],
            samples=base["trades"] >= c["targets"]["trades"],
            per_symbol=all(info["base"]["by_symbol"][s]["trades"] >= c["targets"]["per_symbol"] for s in SYMBOLS),
            no_unresolved_paths=not any(s["uncertain"] for s in info["base"]["segments"]),
            leave_best_positive=ge(diagnostic["candidates"][candidate]["leave_best_asset"]["metrics"]["mean_r"], 1e-15),
            remove_largest_positive=ge(diagnostic["candidates"][candidate]["remove_largest_trade"]["mean_r"], 1e-15),
            all_years_positive=all(ge(y["metrics"]["mean_r"], 1e-15) for y in info["annual_reset_diagnostics"]),
            interval_lower_positive=ge(info["uncertainty"]["mean_r_lower"], 1e-15),
            holm_significance=info["holm_p"] <= c["targets"]["alpha"], legacy_10r_resolved=c["legacy_10r_resolved"])
        info["checks"] = checks
        numeric = ("pf", "payoff", "positive_mean_r", "fixed_stress_pf", "full_stress_positive", "drawdown")
        info["decision"] = "LIMITED_DEV_EVIDENCE_ONLY" if all(checks[k] for k in numeric) else "REJECT_CURRENT_DEFINITION"
        info["formal_performance_pass"] = False
        trades = load_primary_trades(rdir, candidate)
        info["exit_reasons"] = dict(Counter(t["exit_reason"] for t in trades))
        seen = set()
        for t in trades:
            verification["trades_checked"] += 1
            errors = []
            if t["opportunity_id"] in seen: errors.append("duplicate_fill")
            seen.add(t["opportunity_id"])
            if t["entry_time"] != t["confirmation_time"] + STEP: errors.append("entry_clock")
            if t["execution_policy"] != EXECUTION_POLICY: errors.append("policy")
            fee, slip = c["fee_bps_side"] / 10000, c["slippage_bps_side"] / 10000
            initial_risk = t["quantity"] * (t["entry_price"] - t["initial_stop"] * (1-slip)
                + fee * (t["entry_price"] + t["initial_stop"] * (1-slip)))
            if not np.isclose(initial_risk, t["risk_amount"], rtol=1e-10): errors.append("base_r")
            if t["label_status"] == "MATURE":
                pnl = t["quantity"] * (t["exit_reference"]*(1-slip)-t["entry_reference"]*(1+slip)) - t["fees"]
                if not np.isclose(pnl, t["net_pnl"], atol=1e-8): errors.append("cash_identity")
                if not np.isclose(t["net_r"], pnl / t["risk_amount"], atol=1e-8): errors.append("net_r_identity")
            if errors: verification["errors"].append({"id": t["opportunity_id"], "errors": errors})
    verification["baseline_guard"] = baseline_check(out)
    write(stage / "business_verification.json", verification)
    if verification["errors"]:
        raise ValueError("Business verification failed")
    final = {"scope": "DEV_ONLY", "model": "NOT_TRAINED", "performance": "NO_GO",
        "engineering": "REPLAY_AND_ACCOUNTING_VERIFIED_TESTS_RECORDED_SEPARATELY", "data": "PARTIAL",
        "policy_hash": digest(c), "data_hash": replay_results["data_hash"], "candidates": candidates,
        "controls": diagnostic, "execution_enabled": False, "independent_oos": False,
        "no_automatic_forward_or_testnet": True}
    write(stage / "final_report.json", final)
    lines = ["# START / PULLBACK development research", "", "DEV_ONLY; proxy fills; not independent OOS; execution disabled.", "",
             "Primary results use a continuous account. Annual reset diagnostics are never pooled into its equity or samples.", "",
             "| Candidate | Trades | Win rate | Payoff | PF | Mean BASE R | Fixed stress PF | Full stress PF | Drawdown | Decision |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"]
    def fmt(v): return "N/A" if v is None else f"{v:.4f}"
    for candidate in CANDIDATES:
        x = candidates[candidate]; b = x["base"]["metrics"]
        lines.append(f"| {candidate} | {b['trades']} | {fmt(b['win_rate'])} | {fmt(b['payoff'])} | {fmt(b['pf'])} | {fmt(b['mean_r'])} | {fmt(x['fixed_double_cost']['pf'])} | {fmt(x['stress']['metrics']['pf'])} | {fmt(b['max_drawdown'])} | {x['decision']} |")
        lines += ["", candidate + " failed checks: " + ", ".join(k for k,v in x["checks"].items() if not v)]
    lines += ["", "Full stress R uses scenario initial risk, not BASE R. Fixed-fill stress retains the BASE denominator.",
              "Both historical model fitting and execution are disabled. Old 10R conflict remains unresolved.",
              "Unknown paths and unmatched lead-time pairs are not replaced with zero.",
              "", "Policy hash: " + digest(c), "Data hash: " + replay_results["data_hash"]]
    with (stage / "REPORT.md").open("x", encoding="utf-8") as f: f.write("\n".join(lines) + "\n")


def execute_stage(out, name, c):
    if (out / (name + "_index.json")).exists():
        phase_path(out, name)
        print(name, "already complete; verified, not overwritten", flush=True)
        return
    stage = out / f"{name}_attempt_{len(list(out.glob(name + '_attempt_*'))) + 1:03d}"
    stage.mkdir()
    snapshot = stage / "source_snapshot"
    snapshot.mkdir()
    for p in CODE: shutil.copy2(p, snapshot / p.name)
    began = time.monotonic()
    write(stage / "stage_start.json", {"started_at": datetime.now(timezone.utc).isoformat(),
        "policy_hash": digest(c), "source_hashes": {str(p): sha(p) for p in CODE}, "python": sys.executable})
    try:
        {"build": build, "replay": replay_phase, "controls": controls, "report": report}[name](out, stage, c)
        if any(sha(Path(p)) != expected for p, expected in read(stage / "stage_start.json")["source_hashes"].items()):
            raise ValueError("Source code changed while phase was running")
    except Exception:
        write(stage / "failure.json", {"elapsed_seconds": time.monotonic()-began, "traceback": traceback.format_exc()})
        raise
    write(stage / "completion.json", {"exit_code": 0, "elapsed_seconds": time.monotonic()-began})
    hashes = {str(p.relative_to(stage)): sha(p) for p in stage.rglob("*") if p.is_file()}
    write(out / (name + "_index.json"), {"directory": stage.name, "hashes": hashes})
    print(name, "completed", round(time.monotonic()-began, 2), "seconds", flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=["freeze", "build", "replay", "controls", "report", "all", "status"])
    p.add_argument("--run-id", required=True)
    a = p.parse_args()
    if Path(a.run_id).name != a.run_id or a.run_id in (".", ".."):
        raise ValueError("Invalid run identity")
    out = ROOT / "outputs/start_pullback_research" / a.run_id
    if a.command == "freeze" or (a.command == "all" and not out.exists()):
        freeze(out)
    c = read(out / "contract.json")
    check_contract(c)
    if digest(c) != read(out / "preregistration.json")["policy_hash"]:
        raise ValueError("Frozen policy drift")
    if a.command == "status":
        print(json.dumps({"run": str(out), "policy_hash": digest(c), "execution_enabled": False,
            "completed": [n for n in ("build", "replay", "controls", "report") if (out / (n + "_index.json")).exists()]}, indent=2))
    for name in ("build", "replay", "controls", "report"):
        if a.command in (name, "all"): execute_stage(out, name, c)
    print(out, flush=True)


if __name__ == "__main__":
    main()
