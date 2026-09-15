"""Read-only diagnostics of one authorized, frozen DEV_ONLY posterior.

No model construction, sampling, production loading, registry, or market reads.
Numerical estimates below are exposed-design diagnostics, not usable signals.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "outputs/hybrid_regime_v1/dev_fit_20260905_03"
OUTPUT = ROOT / "outputs/hybrid_delivery/posterior_review_20260906"
MANIFEST_SHA = "dd58b6b9546d23665841be0d56b571c510e9d6035dec6c2a1a04032948c6e75e"
TARGET = "LEGACY_BAR_PROXY_BASE_10_5"
PARAMETERS = ["alpha", "beta", "tau", "sigma", "nu", "z", "u_symbolmode"]
PERMISSIONS = {"mean_inference_valid": False, "predictive_probability_valid": False,
               "predictive_tail_valid": False, "runtime_enabled": False}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_new(path, value):
    """Fail instead of replacing evidence from an earlier invocation."""
    with Path(path).open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def verify_frozen(path=FROZEN, *, purpose="DEV_ONLY"):
    if purpose != "DEV_ONLY":
        raise ValueError("non-DEV_ONLY use refused before artifact IO")
    path = Path(path).resolve()
    if path != FROZEN.resolve():
        raise ValueError("only dev_fit_20260905_03 is authorized")
    if sha(path / "delivery_manifest.json") != MANIFEST_SHA:
        raise ValueError("frozen delivery manifest hash mismatch")
    manifest = read_json(path / "delivery_manifest.json")
    hashes = {p.name: sha(p) for p in path.iterdir() if p.is_file()}
    # Select only this run's manifest entries; never follow adjacent clock/data paths.
    for name, actual in hashes.items():
        if name == "delivery_manifest.json":
            continue
        key = "outputs\\hybrid_regime_v1\\dev_fit_20260905_03\\" + name
        if manifest["output_hashes"].get(key) != actual:
            raise ValueError("frozen artifact hash mismatch: " + name)
    required = {"artifact.json", "preregistration.json", "row_provenance.json", "posterior.nc",
                "prior.nc", "baseline.json", "transform.json", "audit.json", "config_snapshot.json",
                "process_exit.json", "numerical_warning.json", "training_source_snapshot.py"}
    if not required <= hashes.keys():
        raise ValueError("missing frozen artifact")
    meta = read_json(path / "artifact.json")
    if (meta["scope"] != "DEV_ONLY" or meta["exposure"] != "EXPOSED_RESEARCH"
            or meta["runtime_enabled"] is not False or meta["admission"] != "ABSTAIN"):
        raise ValueError("unsafe frozen model identity")
    if meta["posterior_sha256"] != hashes["posterior.nc"] or meta["config_sha256"] != hashes["config_snapshot.json"]:
        raise ValueError("model/config binding mismatch")
    return hashes


def _finite(value):
    import numpy as np
    return float(value) if np.isfinite(value) else None


def estimate(draws, *, quantile=None):
    """Preserve chain/draw axes for ArviZ autocorrelation-aware MCSE.

    Constant indicator draws have unestimable mixing/error, not proven zero MCSE.
    Quantile MCSE is for that quantile, not the mean of the same draws.
    """
    import arviz as az
    import numpy as np
    values = np.asarray(draws, dtype=float)
    if values.ndim != 2 or values.shape[1] < 4 or not np.isfinite(values).all():
        raise ValueError("finite chain-by-draw values with at least four draws required")
    point = float(values.mean() if quantile is None else np.quantile(values, quantile))
    per_chain = (values.mean(axis=1) if quantile is None else np.quantile(values, quantile, axis=1)).tolist()
    result = {"estimate": point, "per_chain": per_chain, "mcse": None,
              "mcse_method": "ArviZ mean" if quantile is None else f"ArviZ quantile({quantile})",
              "status": "ESTIMATED", "ess": None}
    if np.any(np.std(values, axis=1) == 0):
        result["status"] = "UNESTIMABLE_CONSTANT_CHAIN"
        return result
    kwargs = {} if quantile is None else {"prob": quantile}
    result["mcse"] = _finite(az.mcse(values, method="mean" if quantile is None else "quantile", **kwargs))
    result["ess"] = _finite(az.ess(values, method="mean" if quantile is None else "quantile", **kwargs))
    if result["mcse"] is None or result["ess"] is None:
        result["status"] = "UNESTIMABLE"
    return result


def critical_outputs(mu, sigma, nu, predictive):
    import numpy as np
    from scipy.stats import t
    return {
        "mu": estimate(mu),
        "p_win": estimate(t.sf(0, df=nu, loc=mu, scale=sigma)),
        "p_win_saved_predictive_frequency": estimate(np.asarray(predictive) > 0),
        "p_edge": estimate(np.asarray(mu) > 0),
        "q05_mu": estimate(mu, quantile=.05),
        "q05_outcome": estimate(predictive, quantile=.05),
    }


def output_permission(coverage, symbol, mode, target, *, feature_in_range=True):
    reasons = ["EXPOSED_DEV_ONLY", "SUPPORT_AND_CALIBRATION_UNVALIDATED"]
    if coverage.get(symbol + ":" + mode, 0) == 0:
        reasons.append("UNSUPPORTED_GROUP")
    if target != TARGET:
        reasons.append("UNSUPPORTED_EXECUTION_TARGET")
    if not feature_in_range:
        reasons.append("OUTSIDE_OBSERVED_FEATURE_RANGE")
    return {"admission": "ABSTAIN", "reasons": reasons, "p_win": None, "p_edge": None,
            "q05_mu": None, "outcome_quantiles": None, **PERMISSIONS}


def _flatten(dataset):
    import numpy as np
    names, columns = [], []
    for name in PARAMETERS:
        value = dataset[name].transpose("chain", "draw", ...)
        dims = value.dims[2:]
        for indices in np.ndindex(value.shape[2:]):
            labels = [str(value.coords[dim].values[i]) for dim, i in zip(dims, indices)]
            names.append(name + ("[" + ",".join(labels) + "]" if labels else ""))
            columns.append(np.asarray(value)[(slice(None), slice(None)) + indices])
    return names, np.stack(columns, axis=-1)


def _corr(a, b):
    import numpy as np
    if np.std(a) == 0 or np.std(b) == 0:
        return None
    return _finite(np.corrcoef(a, b)[0, 1])


def chain_diagnostics(posterior, stats, cap):
    import numpy as np
    names, values = _flatten(posterior)
    result = []
    for chain in range(values.shape[0]):
        depth = np.asarray(stats.tree_depth)[chain]
        steps = np.asarray(stats.n_steps)[chain]
        saturated = steps >= 2 ** cap - 1
        pairs = []
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                pairs.append({"left": names[i], "right": names[j],
                              "pearson_r": _corr(values[chain, :, i], values[chain, :, j])})
        pairs.sort(key=lambda row: abs(row["pearson_r"] or 0), reverse=True)
        result.append({"chain": int(posterior.chain.values[chain]), "draws": len(depth),
            "tree_depth_histogram": dict(sorted(Counter(map(str, depth)).items())),
            "at_depth_cap": int((depth >= cap).sum()), "steps_at_cap": int(saturated.sum()),
            "steps_at_cap_fraction": float(saturated.mean()),
            "divergences": int(np.asarray(stats.diverging)[chain].sum()),
            "top_parameter_correlations": pairs[:10],
            "parameter_depth_correlations": [{"parameter": name,
                "tree_depth_r": _corr(values[chain, :, i], depth),
                "cap_indicator_r": _corr(values[chain, :, i], saturated)} for i, name in enumerate(names)]})
    return result


def _distribution(values):
    import numpy as np
    a = np.asarray(values)
    return {"mean": float(a.mean()), "sd": float(a.std()),
            "q05_q50_q95": np.quantile(a, [.05, .5, .95]).tolist()}


def _acceptance(tasks):
    statuses = {"T14": ["COVERED", "COVERED", "COVERED", "COVERED"],
                "T15": ["COVERED_BY_EXISTING_FIT", "PARTIAL", "COVERED", "COVERED"]}
    evidence = {"T14": ["No refit or treedepth changes; per-chain warning retained.",
        "Rhat/ESS recomputed as numerical diagnostics only, not prediction accuracy.",
        "Economic support, predictive tails/probabilities and mean permissions separately false.",
        "Only frozen 27 exposed fit rows read; no independent final evaluation accessed."],
        "T15": ["Existing completed 27-label fit reused; no 200-trade prerequisite or new fit.",
        "Per-row label times and raw artifact times retained; synchronized model availability is unverified.",
        "p_win integrates conditional Student-t probability; p_edge is Pr(mu>0); q05_mu is mean quantile.",
        "Unsupported cells, targets and feature extrapolation return ABSTAIN with null usable outputs."]}
    return {task["id"]: {"status": "PARTIAL_NO_G2_PASS", "acceptance": [
        {"requirement": text, "coverage": status, "evidence": note}
        for text, status, note in zip(task["acceptance"], statuses[task["id"]], evidence[task["id"]])],
        "deliverables": task["deliverables"],
        "remaining": ["Validate economic support and output-specific mean/probability/tail suitability.",
                      "No diagnostic repair attempted or validated; frozen tree-depth warning remains."]
        if task["id"] == "T14" else [
            "Verified model available-at/registration time with trustworthy clock evidence.",
            "Matched-target support and numerical-error acceptance validation before G2.",
            "Time-out calibration/group validation before G6; not performed on this exposed sample."]}
        for task in tasks if task["id"] in statuses}


def review_saved(*, purpose="DEV_ONLY"):
    before = verify_frozen(purpose=purpose)
    import arviz as az
    import numpy as np
    from scipy.stats import t
    trace, prior = az.from_netcdf(FROZEN / "posterior.nc"), az.from_netcdf(FROZEN / "prior.nc")
    try:
        trace.load()
        prior.load()
        posterior = trace.posterior
        rows = read_json(FROZEN / "row_provenance.json")
        audit = read_json(FROZEN / "audit.json")
        registration = read_json(FROZEN / "preregistration.json")
        config = registration["config"]
        transform = read_json(FROZEN / "transform.json")
        coverage = dict(Counter(r["label"]["symbol"] + ":" + r["label"]["mode"] for r in rows))
        if len(rows) != 27 or coverage != audit["coverage"] or posterior.sizes["chain"] != 4 or posterior.sizes["draw"] != 1500:
            raise ValueError("frozen population/draw shape mismatch")
        y = np.array([r["label"]["net_r"] for r in rows])
        np.testing.assert_allclose(trace.observed_data.R, y, rtol=0, atol=0)
        if len({r["label"]["economic_signal_id"] for r in rows}) != 27:
            raise ValueError("duplicate frozen label identity")
        outputs, support = [], []
        for i, row in enumerate(rows):
            label = row["label"]
            mode, symbol = label["mode"], label["symbol"]
            x = (np.array([row["feature"]["values"][f] for f in transform["features"]]) - transform["mean"]) / transform["scale"]
            expected = posterior.alpha.sel(mode=mode) + posterior.u_symbolmode.sel(cell=symbol + ":" + mode)
            expected = expected + (posterior.beta.sel(mode=mode) * x).sum("feature")
            mu = posterior.mu.isel(obs=i).values
            np.testing.assert_allclose(mu, expected, rtol=1e-12, atol=1e-12)
            sigma, nu = posterior.sigma.sel(mode=mode).values, posterior.nu.values
            pred = trace.posterior_predictive.R.isel(obs=i).values
            outputs.append({"economic_signal_id": label["economic_signal_id"], "symbol": symbol, "mode": mode,
                "label_available_at": label["available_at"], "information_end": label["information_end"],
                "feature_available_at": row["feature"]["available_at"],
                "diagnostic_estimates_not_usable_predictions": critical_outputs(mu, sigma, nu, pred),
                "usable_output": output_permission(coverage, symbol, mode, TARGET)})
            trade = label["executed_trade"]
            lower = -trade["entry_price"] * 1.001 / trade["unit_net_risk"]
            if not np.isclose(lower, row["lower_r"], rtol=1e-12):
                raise ValueError("economic support denominator mismatch")
            mass = t.cdf(lower, df=nu, loc=mu, scale=sigma)
            support.append({"economic_signal_id": label["economic_signal_id"], "economic_lower_r": lower,
                "analytic_posterior_impossible_mass": estimate(mass),
                "saved_predictive_impossible_fraction": float((pred < lower).mean())})
        summary = az.summary(trace, var_names=PARAMETERS, round_to="none")
        limits = config["diagnostics"]
        numerical = {"rhat_max": float(summary.r_hat.max()), "ess_bulk_min": float(summary.ess_bulk.min()),
                     "ess_tail_min": float(summary.ess_tail.min()), "bfmi": az.bfmi(trace).tolist(),
                     "divergences": int(trace.sample_stats.diverging.sum()), "frozen_thresholds": limits}
        numerical["frozen_sampler_checks_pass"] = bool(
            np.isfinite(summary[["r_hat", "ess_bulk", "ess_tail"]].values).all()
            and numerical["rhat_max"] <= limits["rhat_max"] and numerical["ess_bulk_min"] >= limits["ess_bulk_min"]
            and numerical["ess_tail_min"] >= limits["ess_tail_min"] and min(numerical["bfmi"]) >= limits["bfmi_min"]
            and numerical["divergences"] <= limits["divergences_max"])
        warning = read_json(FROZEN / "numerical_warning.json")
        numerical["chains"] = chain_diagnostics(posterior, trace.sample_stats, warning["library_default_max_tree_depth"])
        numerical["tree_depth_policy"] = {"cap": warning["library_default_max_tree_depth"],
            "source": "frozen numerical_warning.json library default; not a new gate",
            "definition": "depth>=10 and n_steps>=1023 reported separately; not equivalent",
            "new_threshold": None, "refit": False, "repair_candidates_attempted": 0}
        names, post_values = _flatten(posterior)
        prior_names, prior_values = _flatten(prior.prior)
        if names != prior_names:
            raise ValueError("prior/posterior coordinates differ")
        comparison = [{"parameter": name, "prior": _distribution(prior_values[..., i]),
                       "posterior": _distribution(post_values[..., i])} for i, name in enumerate(names)]
        predicted = trace.posterior_predictive.R.values
        prior_pred = prior.prior_predictive.R.values
        q = np.quantile(predicted, [.05, .95], axis=(0, 1))
        strata = {}
        for category in ("mode", "symbol", "reason"):
            for name in sorted({r["label"][category] for r in rows}):
                mask = np.array([r["label"][category] == name for r in rows])
                strata[category + ":" + name] = {"n": int(mask.sum()), "observed": _distribution(y[mask]),
                                               "posterior_predictive": _distribution(predicted[..., mask])}
        baseline = read_json(FROZEN / "baseline.json")
        baseline["posterior_mean_in_sample_rmse"] = float(np.sqrt(np.mean((posterior.mu.values.mean(axis=(0, 1)) - y) ** 2)))
        baseline["refit"] = False
        group_report = {}
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            for mode in ("RANGE", "UP_TREND"):
                cell = symbol + ":" + mode
                members = [r for r in rows if r["label"]["symbol"] == symbol and r["label"]["mode"] == mode]
                group_report[cell] = {"n": len(members), "dependency_days": len({r["label"]["dependence_group"] for r in members}),
                    "feature_ranges": {f: [min(r["feature"]["values"][f] for r in members),
                                            max(r["feature"]["values"][f] for r in members)]
                                       for f in config["features"]} if members else {},
                    "support": "OBSERVED_NOT_VALIDATED" if members else "UNSUPPORTED",
                    "proxy": output_permission(coverage, symbol, mode, TARGET),
                    "quote_aware": output_permission(coverage, symbol, mode, "QUOTE_AWARE")}
        tasks = read_json(ROOT / "plan/hybrid_to_live_tasks.v1_2.json")["tasks"]
        result = {"scope": "DEV_ONLY", "exposure": "EXPOSED_RESEARCH", "admission": "ABSTAIN",
            "G2": "NOT_PASSED_SUPPORT_UNVALIDATED", "G6": "NOT_EVALUATED", **PERMISSIONS,
            "frozen_run": str(FROZEN), "input_hashes": before, "no_refit": True,
            "market_labels": 27, "posterior_draws": 6000, "excluded_unfilled": len(audit["excluded_unavailable"]),
            "dependency_days": len(audit["groups"]), "overlap_pairs": len(audit["overlapping_pairs"]),
            "target": TARGET, "original_splits_all_exposed": audit["original_splits"],
            "model_version": config["version"], "features": config["features"],
            "numerical": numerical, "prior_posterior_parameters": comparison,
            "critical_outputs": outputs, "groups": group_report, "support": support,
            "predictive_checks": {"prior": _distribution(prior_pred), "posterior": _distribution(predicted),
                "observed": _distribution(y), "strata": strata,
                "in_sample_90pct_interval_coverage": float(((y >= q[0]) & (y <= q[1])).mean()),
                "coverage_is_calibration": False, "draws_clipped": False,
                "support_rule": "R >= -entry_price*(1+0.001)/frozen_BASE_unit_net_risk; -1R is not hard support",
                "support_validated": False},
            "baseline": baseline, "existing_fit_command": read_json(FROZEN / "process_exit.json"),
            "timing": {"fit_registered_raw_local_utc": registration["registered_at_utc"],
                "posterior_created_raw_local_utc": posterior.attrs.get("created_at"),
                "model_available_at_verified": None, "label_availability_basis": audit["availability_limit"],
                "clock_warning": "Raw original host timestamps; prior report identified clock offset. No corrected time invented."},
            "definitions": {"p_win": "E_posterior[Pr(R>0|theta,x)] via Student-t SF; not Pr(mu>0)",
                "p_edge": "Pr_posterior(mu(x)>0), estimated from mean draws; not trade win probability",
                "q05_mu": "5th percentile of posterior conditional mean mu(x); not outcome tail",
                "q05_outcome": "5th percentile of saved posterior predictive R; unvalidated outcome tail",
                "MCSE": "Autocorrelation-aware ArviZ mean/quantile MCSE, not market error or model uncertainty",
                "correlations": "Within-chain Pearson associations; descriptive, not causal diagnosis"},
            "acceptance": _acceptance(tasks),
            "limitations": ["All 27 portfolio-selected A proxy labels are EXPOSED; no OOS validation.",
                "RANGE has 2 labels, BTC trend 1; missing groups cannot borrow validated status from pooling.",
                "Student-t has unbounded support; finite draws with zero impossible outcomes do not prove support.",
                "No registered output-MCSE tolerances or support/mean/tail calibration validation supplied.",
                "Stop/target/timeout clustering and conditional independence remain unvalidated.",
                "Proxy prediction is not QUOTE_AWARE execution prediction; no target migration performed.",
                "Sampler ESS is not market sample size; in-sample coverage/RMSE is not accuracy evidence."],
            "review_time_raw_host_utc": datetime.now(timezone.utc).isoformat()}
        if before != verify_frozen():
            raise ValueError("frozen artifacts changed during review")
        result["frozen_artifacts_unchanged"] = True
        return result
    finally:
        trace.close()
        prior.close()


def markdown_report(result):
    n = result["numerical"]
    lines = ["# Frozen Posterior Review - 2026-09-06", "",
        "DEV_ONLY / EXPOSED_RESEARCH / ABSTAIN. G2 NOT PASSED; G6 not evaluated.", "",
        "Reused dev_fit_20260905_03: 27 A proxy labels, 23 unfilled excluded, 4 x 1500 saved draws.",
        "No refit, resampling, clipping, parameter changes, restricted interval reads, or production integration.", "",
        f"Rhat max {n['rhat_max']:.9f}; bulk ESS min {n['ess_bulk_min']:.3f}; tail ESS min {n['ess_tail_min']:.3f}; divergences {n['divergences']}.",
        "Frozen sampler checks pass, but this is not G2 or predictive validity.", "",
        "| Chain | Depth >= cap | Steps at cap | Step-cap fraction |", "|---|---:|---:|---:|"]
    for c in n["chains"]:
        lines.append(f"| {c['chain']} | {c['at_depth_cap']} | {c['steps_at_cap']} | {c['steps_at_cap_fraction']:.6f} |")
    lines += ["", "Per-chain parameter/depth correlations and row-specific output MCSE are in review.json.",
              "Correlations do not establish the cause of saturation. No numerical repair was attempted.", "", "## Output Definitions"]
    lines += [f"- {k}: {v}" for k, v in result["definitions"].items()]
    lines += ["", "## Coverage And Support"]
    lines += [f"- {cell}: n={group['n']}, dependency days={group['dependency_days']}, {group['support']}; ABSTAIN."
              for cell, group in result["groups"].items()]
    mass = max(s["analytic_posterior_impossible_mass"]["estimate"] for s in result["support"])
    lines += [f"- Maximum integrated Student-t probability below a row's economic bound: {mass:.12g}.",
              "- No support pass inferred from a low finite-draw count or this analytical probability alone.", ""]
    lines += ["- " + text for text in result["limitations"]]
    lines += ["", "## Existing Baseline And Timing", "```json",
              json.dumps({"baseline": result["baseline"], "timing": result["timing"],
                          "existing_fit_command": result["existing_fit_command"]}, indent=2), "```", "",
              "## Exact Acceptance Coverage"]
    for task, coverage in result["acceptance"].items():
        lines += [f"### {task}: {coverage['status']}"]
        for item in coverage["acceptance"]:
            lines.append(f"- {item['requirement']}: {item['coverage']}. {item['evidence']}")
        lines += ["Remaining: " + " ".join(coverage["remaining"]), ""]
    lines += ["Task state and gates are not modified. Parent owns acceptance and scheduling.",
              "commands.json, review.log, tests.log, tests_result.json and manifest.json record execution and hashes."]
    return "\n".join(lines) + "\n"
