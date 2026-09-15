"""Forecast accuracy only. No trading or profitability gate is emitted."""
from collections import defaultdict
import html
import numpy as np

from .contracts import atomic_json, file_hash, read_json


def metrics(records):
    good = [r for r in records if r["actual_log_path"] is not None and r["predicted_log_path"] is not None]
    if not good:
        return {"scored": 0}
    y = np.asarray([r["actual_log_path"] for r in good])
    q = np.asarray([r["predicted_log_path"] for r in good])
    error = y[:, :, None] - q
    pinball = np.maximum(error * np.array([.1, .5, .9]), error * np.array([-.9, -.5, -.1]))
    return {"scored": len(good), "path_mae": float(np.abs(y - q[:, :, 1]).mean()),
            "terminal_mae": float(np.abs(y[:, -1] - q[:, -1, 1]).mean()),
            "direction_accuracy": float((np.sign(y[:, -1]) == np.sign(q[:, -1, 1])).mean()),
            "pinball": float(pinball.mean()), "pointwise_80_coverage": float(((y >= q[:, :, 0]) & (y <= q[:, :, 2])).mean()),
            "mean_interval_width": float((q[:, :, 2] - q[:, :, 0]).mean()),
            "coverage_by_hour": ((y >= q[:, :, 0]) & (y <= q[:, :, 2])).mean(axis=0).tolist(),
            "mae_by_hour": np.abs(y - q[:, :, 1]).mean(axis=0).tolist(),
            "scope": "DEV_ONLY_NOT_CALIBRATED"}


def bootstrap_difference(candidate, baseline, settings):
    def keyed(records):
        return {(r["symbol"], r["signal_time"]): r for r in records
                if r["actual_log_path"] is not None and r["predicted_log_path"] is not None}
    a, b = keyed(candidate), keyed(baseline)
    keys = sorted(a.keys() & b.keys())
    grouped = defaultdict(list)
    for key in keys:
        y = np.asarray(a[key]["actual_log_path"])
        if not np.array_equal(y, b[key]["actual_log_path"]):
            raise ValueError("Mismatched outcomes")
        da = np.abs(y - np.asarray(a[key]["predicted_log_path"])[:, 1]).mean()
        db = np.abs(y - np.asarray(b[key]["predicted_log_path"])[:, 1]).mean()
        grouped[key[1] // (settings["block_days"] * 86400)].append(float(da - db))
    if len(grouped) < settings["minimum_blocks"]:
        return {"status": "INSUFFICIENT_BLOCKS", "blocks": len(grouped), "paired_samples": len(keys), "p": 1.0}
    totals = np.array([sum(grouped[k]) for k in sorted(grouped)])
    counts = np.array([len(grouped[k]) for k in sorted(grouped)])
    observed = totals.sum() / counts.sum()
    rng = np.random.default_rng(settings["seed"])
    idx = rng.integers(0, len(totals), size=(settings["replicates"], len(totals)))
    draws = totals[idx].sum(axis=1) / counts[idx].sum(axis=1)
    centered = (totals - observed * counts)[idx].sum(axis=1) / counts[idx].sum(axis=1)
    p = (1 + np.count_nonzero(centered <= observed)) / (1 + len(draws))
    return {"status": "DEV_BLOCK_BOOTSTRAP", "blocks": len(grouped), "paired_samples": len(keys),
            "mean_difference": float(observed), "ci95": np.quantile(draws, [.025, .975]).tolist(), "p": float(p)}


def holm(ps):
    out, previous = {}, 0.
    ordered = sorted(ps, key=lambda name: ps[name])
    for i, name in enumerate(ordered):
        previous = max(previous, min(1., (len(ps) - i) * ps[name]))
        out[name] = previous
    return out


def load_predictions(run):
    records, ids = [], set()
    for directory in sorted(run.path.glob("predict_*")):
        if not directory.is_dir() or not (directory / "complete.json").exists():
            continue
        manifest = read_json(directory / "complete.json")
        if file_hash(directory / "predictions.json") != manifest["files"]["predictions.json"]:
            raise ValueError("Prediction artifact altered")
        for r in read_json(directory / "predictions.json"):
            if r["forecast_id"] in ids:
                raise ValueError("Duplicate forecast ID")
            ids.add(r["forecast_id"])
            records.append(r)
    return records


def evaluate(run):
    # Versioned evaluations can grow as immutable prediction chunks arrive.
    directories = sorted(run.path.glob("evaluation_*"))
    key = f"evaluation_{len(directories) + 1:03d}"
    with run.phase(key) as out:
        records = load_predictions(run)
        grouped = defaultdict(list)
        for r in records:
            grouped[(r["method"], r["seed"], r["partition"])].append(r)
        summaries = {str(k): metrics(v) for k, v in grouped.items()}
        primary = run.config["tcn"]["seeds"][0]
        progress = {p.stem: read_json(p) for p in run.path.glob("predict_*_progress.json")}
        decisions, tests = {}, {}
        for method in ("nearest", "dtw", "tcn"):
            cand = grouped[(method, primary, "report")]
            complete = all(progress.get(f"predict_{f['id']}_report_{m}_{primary}_progress", {}).get("complete", False)
                           for f in run.config["folds"] for m in (method, "constant", "ar1"))
            decision = {"complete": complete, "status": "PREDICTION_UNPROVEN", "profitability_pass": False}
            available = bool(cand) and all(r["forecast_status"] == "AVAILABLE" for r in cand)
            decision["all_inputs_forecast_available"] = available
            if complete and available:
                skills, paired = {}, {}
                for base in ("constant", "ar1"):
                    reference = grouped[(base, primary, "report")]
                    eligible = {(r["symbol"], r["signal_time"]) for r in cand if r["forecast_status"] == "AVAILABLE" and r["actual_log_path"] is not None}
                    cc = [r for r in cand if (r["symbol"], r["signal_time"]) in eligible]
                    bb = [r for r in reference if (r["symbol"], r["signal_time"]) in eligible]
                    cm, bm = metrics(cc), metrics(bb)
                    skills[base] = 1 - cm.get("path_mae", float("inf")) / max(bm.get("path_mae", 0), 1e-12)
                    paired[base] = bootstrap_difference(cc, bb, run.config["statistics"])
                    tests[method + "_" + base] = paired[base]["p"]
                years = {}
                for fold in run.config["folds"]:
                    cc = [r for r in cand if r["fold"] == fold["id"] and r["forecast_status"] == "AVAILABLE" and r["actual_log_path"] is not None]
                    keys = {(r["symbol"], r["signal_time"]) for r in cc}
                    years[fold["id"]] = bool(cc) and all(metrics(cc)["path_mae"] < metrics([r for r in grouped[(b, primary, "report")] if (r["symbol"], r["signal_time"]) in keys])["path_mae"] for b in ("constant", "ar1"))
                decision.update(skill=skills, tests=paired, positive_years=years,
                                preliminary=all(v >= .05 for v in skills.values()) and sum(years.values()) >= 2
                                and all(t.get("ci95", [0, 0])[1] < 0 for t in paired.values()))
            decisions[method] = decision
        adjusted = holm(tests)
        for method, d in decisions.items():
            if d["complete"] and d["all_inputs_forecast_available"]:
                d["status"] = "DEV_ACCURACY_CANDIDATE" if d.get("preliminary") and all(adjusted.get(method + "_" + b, 1) < .05 for b in ("constant", "ar1")) else "TARGET_NOT_MET"
            if method == "tcn" and d["status"] == "DEV_ACCURACY_CANDIDATE":
                stability = all(progress.get(f"predict_{f['id']}_report_tcn_{s}_progress", {}).get("complete", False)
                                for f in run.config["folds"] for s in run.config["tcn"]["seeds"])
                d["seed_stability_complete"] = stability
                if not stability:
                    d["status"] = "STABILITY_UNPROVEN"
                else:
                    seed_metrics = {str(s): metrics(grouped[("tcn", s, "report")]) for s in run.config["tcn"]["seeds"]}
                    baseline_mae = min(metrics(grouped[(b, primary, "report")])["path_mae"] for b in ("constant", "ar1"))
                    d["seed_stability"] = seed_metrics
                    if not all(v.get("path_mae", float("inf")) < baseline_mae for v in seed_metrics.values()):
                        d["status"] = "STABILITY_NOT_MET"
        by_symbol_year = {str((m, s, part, f["id"], sym)): metrics([r for r in rr if r["fold"] == f["id"] and r["symbol"] == sym])
                          for (m, s, part), rr in grouped.items() for f in run.config["folds"] for sym in run.config["symbols"] if rr}
        result = {"scope": "DEV_ONLY", "summaries": summaries, "by_symbol_year": by_symbol_year,
                  "decisions": decisions, "holm": adjusted, "progress": progress,
                  "model": "TRAINED" if list(run.path.glob("train_*/complete.json")) else "NOT_TRAINED",
                  "independent_oos": False, "profitability_pass": False, "execution_enabled": False}
        bounds = run.config["gate"]
        result["pointwise_interval_diagnostics"] = {str(k): {
            "nominal": .8, "observed_by_hour": metrics(rr).get("coverage_by_hour", []),
            "within_registered_band": all(bounds["pointwise_coverage_lower"] <= v <= bounds["pointwise_coverage_upper"]
                                          for v in metrics(rr).get("coverage_by_hour", [])) if metrics(rr)["scored"] else False,
            "simultaneous_path_coverage_claim": False} for k, rr in grouped.items() if rr}
        ready = [m for m in ("nearest", "dtw", "tcn") if decisions[m]["status"] == "DEV_ACCURACY_CANDIDATE"]
        result["recommended_method"] = min(ready, key=lambda m: (metrics(grouped[(m, primary, "report")])["path_mae"],
                                                   ("nearest", "dtw", "tcn").index(m))) if ready else None
        if "tcn" in ready:
            ablation_complete = all(progress.get(f"predict_{f['id']}_report_tcn_1h_{primary}_progress", {}).get("complete", False) for f in run.config["folds"])
            result["multiscale_ablation"] = {"complete": ablation_complete, "status": "UNPROVEN"}
            if ablation_complete:
                result["multiscale_ablation"].update(bootstrap_difference(grouped[("tcn", primary, "report")], grouped[("tcn_1h", primary, "report")], run.config["statistics"]))
        atomic_json(out / "results.json", result)
    return run.path / key


def _render_report(run, path, result):
    data = read_json(run.path / "build/manifest.json") if (run.path / "build/manifest.json").exists() else {"symbols": {}}
    lines = ["# Multi-scale time-series forecast research", "", "Scope: DEV_ONLY. No independent OOS, calibrated probability or profitability claim.", "",
             f"Contract: {run.frozen['contract_hash']}", "", "## Data"]
    for symbol, d in data["symbols"].items():
        lines.append(f"- {symbol}: {d['calendar_years']:.2f} calendar years; {d['complete_hours']}/{d['expected_hours']} complete hours; coverage {d['coverage']:.4%}.")
    lines += ["", "## Forecast evidence", ""]
    for name, m in result["summaries"].items():
        if m["scored"]:
            lines.append(f"- {name}: n={m['scored']}, path MAE={m['path_mae']:.8f}, pointwise coverage={m['pointwise_80_coverage']:.3f}.")
    for method, decision in result["decisions"].items():
        lines.append(f"- {method}: {decision['status']} (complete={decision['complete']}).")
    lines += ["", "Unfinished chunks and budget-limited runs cannot pass. Correlated hourly rows are not independent samples.",
              "Intervals are pointwise, not simultaneous path coverage. No order, wallet, account or runtime admission."]
    (path / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    # All numeric forecasts are preserved; examples are selected chronologically, never by success.
    examples = {}
    for r in load_predictions(run):
        if r["predicted_log_path"] is not None:
            examples.setdefault((r["method"], r["fold"], r["symbol"]), r)
    charts = []
    panel = None
    for identity, r in examples.items():
        q = np.asarray(r["predicted_log_path"])
        y = np.asarray(r["actual_log_path"]) if r["actual_log_path"] is not None else np.full(24, np.nan)
        values = np.concatenate([q.reshape(-1), y[np.isfinite(y)]])
        lo, hi = values.min(), values.max()
        def points(a):
            return " ".join(f"{20 + i * 22:.1f},{200 - (v - lo) / max(hi - lo, 1e-9) * 170:.1f}" for i, v in enumerate(a))
        traces = "".join(f'<polyline points="{points(q[:, j])}" fill="none" stroke="{color}"/>' for j, color in [(0, "#8091a3"), (1, "#1765bd"), (2, "#8091a3")])
        if np.isfinite(y).all():
            traces += f'<polyline points="{points(y)}" fill="none" stroke="#167347"/>'
        charts.append(f'<h3>{html.escape(str(identity))}</h3><p>First chronological example. Blue: median; gray: pointwise P10/P90; green: observed.</p><svg viewBox="0 0 560 220" role="img" aria-label="Forecast and observed log-return paths">{traces}</svg>')
        if r.get("neighbours"):
            from .sequences import Panel, SCALES
            if panel is None:
                panel = Panel(run)
            source = next(p for p in panel.symbols if p.symbol == r["symbol"])
            query_index = int(np.searchsorted(source.times, r["signal_time"]))
            query = source.window(query_index)
            inputs = [source.window(int(np.searchsorted(source.times, m["signal_time"]))) for m in r["neighbours"]]
            for j, scale in enumerate(SCALES):
                paths = [x[j][:, 0] for x in inputs] + [query[j][:, 0]]
                lo, hi = min(x.min() for x in paths), max(x.max() for x in paths)
                polylines = []
                for k, a in enumerate(paths):
                    xy = " ".join(f"{20 + i * 510 / max(len(a)-1,1):.1f},{200 - (v-lo)/max(hi-lo,1e-9)*170:.1f}" for i,v in enumerate(a))
                    color = "#1765bd" if k == len(paths)-1 else "#adb5bd"
                    polylines.append(f'<polyline points="{xy}" fill="none" stroke="{color}"/>')
                charts.append(f'<h4>{scale}: query (blue), past input analogues (gray)</h4><svg viewBox="0 0 560 220">{"".join(polylines)}</svg>')
            charts.append('<details><summary>All matched dates, distances and actual next-hour paths</summary><pre>' + html.escape(str(r["neighbours"])) + '</pre></details>')
    body = "<pre>" + html.escape("\n".join(lines)) + "</pre>" + "".join(charts)
    (path / "REPORT.html").write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Time-series research</title><style>body{font:15px system-ui;max-width:1000px;margin:24px auto;padding:16px;color:#18212a}pre{white-space:pre-wrap;overflow-wrap:anywhere}svg{max-width:700px;width:100%;border:1px solid #ddd}</style>' + body, encoding="utf-8")
    return path


def report(run):
    evaluated = evaluate(run)
    key = "report_" + evaluated.name.split("_")[-1]
    with run.phase(key) as path:
        result = read_json(evaluated / "results.json")
        atomic_json(path / "evaluation_reference.json", {"path": str(evaluated), "sha256": file_hash(evaluated / "results.json")})
        _render_report(run, path, result)
    return run.path / key
