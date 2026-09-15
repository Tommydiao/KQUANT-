"""Hierarchical Student-t walk-forward model for the bounded trend hypotheses."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .math_action_contract import CORE_SYMBOLS, canonical_hash, file_hash
from .trend_evidence_research import HOUR


MODEL_VERSION = "trend_evidence_hierarchical_student_t_dev_v1.0.0"


def _training_rows(
    rows: list[dict[str, Any]], candidate: dict[str, Any], fold: dict[str, int]
) -> list[dict[str, Any]]:
    horizon = int(candidate["horizon_hours"])
    anchor = int(fold["training_start"])
    return [
        row
        for row in rows
        if row["candidate_id"] == candidate["id"]
        and fold["training_start"] <= row["signal_time"] < fold["training_end_exclusive"]
        and row["fill_status"] == "FILLED"
        and row["label_status"] == "MATURE"
        and ((row["signal_time"] - anchor) // HOUR) % horizon == 0
    ]


def fit_student_t_fold(
    rows: list[dict[str, Any]],
    candidate: dict[str, Any],
    fold: dict[str, int],
    contract: dict[str, Any],
    output: Path,
    *,
    sampler: str = "numpyro",
) -> dict[str, Any]:
    if sampler not in {"pymc", "numpyro"}:
        raise ValueError("Unsupported sampler")
    if output.exists():
        raise FileExistsError(output)
    features = list(candidate["features"])
    train = _training_rows(rows, candidate, fold)
    if len(train) < 30:
        raise ValueError("Insufficient horizon-spaced training rows")
    raw = np.asarray([[row["features"][name] for name in features] for row in train], dtype=float)
    outcome = np.asarray([row["net_r"] for row in train], dtype=float)
    mean, scale = raw.mean(axis=0), raw.std(axis=0)
    if not np.isfinite(raw).all() or not np.isfinite(outcome).all() or not np.all(scale > 0):
        raise ValueError("Invalid Bayesian model inputs")
    standardized = (raw - mean) / scale
    symbol_index = np.asarray([CORE_SYMBOLS.index(row["symbol"]) for row in train], dtype=int)

    import arviz as az
    import pymc as pm

    output.mkdir(parents=True)

    settings = contract["bayesian"]
    with pm.Model(
        coords={"symbol": list(CORE_SYMBOLS), "feature": features, "obs": np.arange(len(train))}
    ) as model:
        alpha = pm.Normal("alpha", 0.0, float(settings["alpha_sd"]))
        beta = pm.Normal("beta", 0.0, float(settings["beta_sd"]), dims="feature")
        symbol_tau = pm.HalfNormal("symbol_tau", float(settings["symbol_tau_sd"]))
        symbol_z = pm.Normal("symbol_z", 0.0, 1.0, dims="symbol")
        symbol_effect = pm.Deterministic("symbol_effect", symbol_z * symbol_tau, dims="symbol")
        sigma = pm.HalfNormal("sigma", float(settings["sigma_sd"]))
        nu = pm.Deterministic(
            "nu", 2.0 + pm.Exponential("nu_minus_two", float(settings["nu_minus_two_rate"]))
        )
        mu = pm.Deterministic(
            "mu", alpha + symbol_effect[symbol_index] + (beta * standardized).sum(axis=1), dims="obs"
        )
        pm.StudentT("net_r", nu=nu, mu=mu, sigma=sigma, observed=outcome, dims="obs")
        sampler_options: dict[str, Any] = {"nuts_sampler": sampler}
        if sampler == "numpyro":
            sampler_options["nuts_sampler_kwargs"] = {"chain_method": "sequential"}
        trace = pm.sample(
            draws=int(settings["draws"]),
            tune=int(settings["tune"]),
            chains=int(settings["chains"]),
            cores=1,
            target_accept=float(settings["target_accept"]),
            random_seed=int(settings["seed"]) + int(fold["fold"]),
            progressbar=False,
            idata_kwargs={"log_likelihood": True},
            **sampler_options,
        )

    posterior_path = output / "posterior.nc"
    trace.to_netcdf(posterior_path)
    summary = az.summary(
        trace,
        var_names=["alpha", "beta", "symbol_tau", "symbol_effect", "sigma", "nu"],
        round_to="none",
    )
    summary.to_csv(output / "parameter_summary.csv")
    diagnostics = {
        "rhat_max": float(summary.r_hat.max()),
        "ess_bulk_min": float(summary.ess_bulk.min()),
        "ess_tail_min": float(summary.ess_tail.min()),
        "divergences": int(trace.sample_stats.diverging.sum()),
        "bfmi": [float(value) for value in az.bfmi(trace)],
        "sampler": sampler,
    }
    diagnostics["sampler_pass"] = bool(
        diagnostics["rhat_max"] <= 1.01
        and diagnostics["ess_bulk_min"] >= 400
        and diagnostics["ess_tail_min"] >= 400
        and diagnostics["divergences"] == 0
        and min(diagnostics["bfmi"]) >= 0.3
    )
    transform = {"feature_names": features, "mean": mean.tolist(), "scale": scale.tolist()}
    transform_path = output / "transform.json"
    transform_path.write_text(
        json.dumps(transform, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8"
    )
    diagnostics_path = output / "diagnostics.json"
    diagnostics_path.write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8"
    )
    artifact = {
        "version": MODEL_VERSION,
        "scope": "DEV_ONLY_EXPOSED_RESEARCH",
        "runtime_enabled": False,
        "admission_enabled": False,
        "candidate_id": candidate["id"],
        "fold": fold,
        "contract_hash": contract["contract_hash"],
        "likelihood": "StudentT_net_R",
        "hierarchy": "partial_pooling_symbol_intercepts",
        "feature_names": features,
        "training_rows": len(train),
        "training_signal_times": len({row["signal_time"] for row in train}),
        "training_panel_hash": canonical_hash([row["sample_id"] for row in train]),
        "transform_sha256": file_hash(transform_path),
        "posterior_sha256": file_hash(posterior_path),
        "diagnostics_sha256": file_hash(diagnostics_path),
        "model_source_sha256": file_hash(Path(__file__)),
        "diagnostics": diagnostics,
        "action_gate": contract["bayesian"]["action_gate"],
        "claims": {
            "independent_oos": False,
            "calibrated_probability": False,
            "performance_gate_passed": False,
            "execution_admission": False,
        },
    }
    artifact["artifact_hash"] = canonical_hash(artifact)
    (output / "artifact.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8"
    )
    return artifact


def predict_student_t_fold(
    rows: list[dict[str, Any]], model_dir: Path
) -> list[dict[str, Any]]:
    import arviz as az

    artifact = json.loads((model_dir / "artifact.json").read_text(encoding="utf-8"))
    expected = canonical_hash({key: value for key, value in artifact.items() if key != "artifact_hash"})
    if artifact.get("artifact_hash") != expected or artifact.get("runtime_enabled") is not False:
        raise ValueError("Unsafe or corrupt Student-t artifact")
    posterior_path = model_dir / "posterior.nc"
    transform_path = model_dir / "transform.json"
    diagnostics_path = model_dir / "diagnostics.json"
    if file_hash(posterior_path) != artifact["posterior_sha256"]:
        raise ValueError("Posterior integrity mismatch")
    if file_hash(transform_path) != artifact["transform_sha256"]:
        raise ValueError("Transform integrity mismatch")
    if file_hash(diagnostics_path) != artifact["diagnostics_sha256"]:
        raise ValueError("Diagnostics integrity mismatch")
    transform = json.loads(transform_path.read_text(encoding="utf-8"))
    features = transform["feature_names"]
    mean = np.asarray(transform["mean"], dtype=float)
    scale = np.asarray(transform["scale"], dtype=float)
    trace = az.from_netcdf(posterior_path)
    alpha = np.asarray(trace.posterior.alpha).reshape(-1)
    beta = np.asarray(trace.posterior.beta).reshape(-1, len(features))
    symbol_effect = np.asarray(trace.posterior.symbol_effect).reshape(-1, len(CORE_SYMBOLS))
    fold = artifact["fold"]
    evaluation = [
        row
        for row in rows
        if row["candidate_id"] == artifact["candidate_id"]
        and fold["evaluation_start"] <= row["signal_time"] < fold["last_entry_time_exclusive"]
    ]
    predictions = []
    for start in range(0, len(evaluation), 512):
        chunk = evaluation[start : start + 512]
        values = np.asarray([[row["features"][name] for name in features] for row in chunk], dtype=float)
        values = (values - mean) / scale
        symbols = np.asarray([CORE_SYMBOLS.index(row["symbol"]) for row in chunk], dtype=int)
        conditional = alpha[:, None] + symbol_effect[:, symbols] + beta @ values.T
        posterior_mean = conditional.mean(axis=0)
        posterior_q05 = np.quantile(conditional, 0.05, axis=0)
        for index, row in enumerate(chunk):
            diagnostic_pass = bool(artifact["diagnostics"]["sampler_pass"])
            predictions.append(
                {
                    "sample_id": row["sample_id"],
                    "candidate_id": row["candidate_id"],
                    "fold": fold["fold"],
                    "signal_time": row["signal_time"],
                    "symbol": row["symbol"],
                    "predicted_net_r": float(posterior_mean[index]),
                    "posterior_q05_conditional_mean_net_r": float(posterior_q05[index]),
                    "posterior_probability_conditional_mean_positive": float(
                        np.mean(conditional[:, index] > 0)
                    ),
                    "passes_research_gate": bool(diagnostic_pass and posterior_q05[index] > 0.0),
                    "sampler_pass": diagnostic_pass,
                    "model_artifact_hash": artifact["artifact_hash"],
                    "decision_authority": "DEV_STUDENT_T_RESEARCH_ONLY",
                    "calibrated_probability": False,
                }
            )
    return predictions
