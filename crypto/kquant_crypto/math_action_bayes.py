"""Hierarchical Student-t net-R model for exposed development research only."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import numpy as np

from .math_action_contract import CORE_SYMBOLS, canonical_hash, file_hash


def _training_rows(rows: list[dict[str, Any]], contract: dict[str, Any]) -> list[dict[str, Any]]:
    stride = int(contract["dataset"]["training_stride_hours"])
    return [
        row
        for row in rows
        if row["partition"] == "DEVELOPMENT_TRAIN"
        and row["fill_status"] == "FILLED"
        and row["label_status"] == "MATURE"
        and (row["signal_time"] // 3600) % stride == 0
    ]


def fit_hierarchical_student_t(
    rows: list[dict[str, Any]],
    contract: dict[str, Any],
    output: Path,
    *,
    sampler: str = "numpyro",
) -> dict[str, Any]:
    """Fit once from the preregistered training rows and save immutable artifacts."""
    if sampler not in {"pymc", "numpyro"}:
        raise ValueError("Unsupported sampler")
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    features = list(contract["features"]["spot_long"])
    train = _training_rows(rows, contract)
    if len(train) < 100:
        raise ValueError("Insufficient non-overlapping development rows")
    raw = np.asarray([[row["features"][name] for name in features] for row in train], dtype=float)
    y = np.asarray([row["net_r"] for row in train], dtype=float)
    mean, scale = raw.mean(axis=0), raw.std(axis=0)
    if not np.isfinite(raw).all() or not np.isfinite(y).all() or not np.all(scale > 0):
        raise ValueError("Invalid model inputs")
    x = (raw - mean) / scale
    symbol_index = np.asarray([CORE_SYMBOLS.index(row["symbol"]) for row in train], dtype=int)

    import arviz as az
    import pymc as pm

    options = contract["bayesian"]
    with pm.Model(
        coords={"symbol": list(CORE_SYMBOLS), "feature": features, "obs": np.arange(len(train))}
    ) as model:
        alpha = pm.Normal("alpha", 0.0, float(options["alpha_sd"]))
        beta = pm.Normal("beta", 0.0, float(options["beta_sd"]), dims="feature")
        symbol_tau = pm.HalfNormal("symbol_tau", float(options["symbol_tau_sd"]))
        symbol_z = pm.Normal("symbol_z", 0.0, 1.0, dims="symbol")
        symbol_effect = pm.Deterministic("symbol_effect", symbol_z * symbol_tau, dims="symbol")
        sigma = pm.HalfNormal("sigma", float(options["sigma_sd"]))
        nu = pm.Deterministic(
            "nu",
            2.0 + pm.Exponential("nu_minus_two", float(options["nu_minus_two_rate"])),
        )
        mu = pm.Deterministic(
            "mu",
            alpha + symbol_effect[symbol_index] + (beta * x).sum(axis=1),
            dims="obs",
        )
        pm.StudentT("net_r", nu=nu, mu=mu, sigma=sigma, observed=y, dims="obs")
        sampler_options: dict[str, Any] = {"nuts_sampler": sampler}
        if sampler == "numpyro":
            sampler_options["nuts_sampler_kwargs"] = {"chain_method": "sequential"}
        trace = pm.sample(
            draws=int(options["draws"]),
            tune=int(options["tune"]),
            chains=int(options["chains"]),
            cores=1,
            target_accept=float(options["target_accept"]),
            random_seed=int(options["seed"]),
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
    (output / "diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8"
    )
    transform = {"feature_names": features, "mean": mean.tolist(), "scale": scale.tolist()}
    (output / "transform.json").write_text(
        json.dumps(transform, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8"
    )
    artifact = {
        "version": "math_action_hierarchical_student_t_dev_v1.0.0",
        "scope": "DEV_ONLY",
        "exposure": "EXPOSED_RESEARCH",
        "runtime_enabled": False,
        "admission_enabled": False,
        "contract_hash": contract["contract_hash"],
        "likelihood": "StudentT_net_R",
        "hierarchy": "partial_pooling_symbol_intercepts",
        "training_rows": len(train),
        "training_signal_times": len({row["signal_time"] for row in train}),
        "training_stride_hours": int(contract["dataset"]["training_stride_hours"]),
        "training_panel_hash": canonical_hash([row["sample_id"] for row in train]),
        "posterior_sha256": file_hash(posterior_path),
        "diagnostics": diagnostics,
        "action_gate": contract["bayesian"]["action_gate"],
        "claims": {
            "independent_oos": False,
            "calibrated_probability": False,
            "performance_gate_passed": False,
            "execution_admission": False,
        },
        "limits": [
            "Fit uses exposed development labels only",
            "Daily-stride training reduces temporal overlap but does not make cross-asset rows independent",
            "Posterior probabilities are not calibrated trading probabilities",
            "Artifact is prohibited from runtime admission and order execution",
        ],
    }
    artifact["artifact_hash"] = canonical_hash(artifact)
    (output / "artifact.json").write_text(
        json.dumps(artifact, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8"
    )
    return artifact


def predict_conditional_mean(
    rows: list[dict[str, Any]],
    model_dir: Path,
    *,
    output: Path | None = None,
) -> list[dict[str, Any]]:
    import arviz as az

    artifact = json.loads((model_dir / "artifact.json").read_text(encoding="utf-8"))
    if artifact["artifact_hash"] != canonical_hash({key: value for key, value in artifact.items() if key != "artifact_hash"}):
        raise ValueError("Bayesian artifact hash mismatch")
    if artifact.get("scope") != "DEV_ONLY" or artifact.get("runtime_enabled") is not False:
        raise ValueError("Unsafe Bayesian artifact")
    posterior_path = model_dir / "posterior.nc"
    if file_hash(posterior_path) != artifact["posterior_sha256"]:
        raise ValueError("Posterior integrity mismatch")
    transform = json.loads((model_dir / "transform.json").read_text(encoding="utf-8"))
    features = transform["feature_names"]
    mean = np.asarray(transform["mean"], dtype=float)
    scale = np.asarray(transform["scale"], dtype=float)
    trace = az.from_netcdf(posterior_path)
    alpha = np.asarray(trace.posterior.alpha).reshape(-1)
    beta = np.asarray(trace.posterior.beta).reshape(-1, len(features))
    symbol_effect = np.asarray(trace.posterior.symbol_effect).reshape(-1, len(CORE_SYMBOLS))
    predictions: list[dict[str, Any]] = []
    for start in range(0, len(rows), 512):
        chunk = rows[start : start + 512]
        x = np.asarray([[row["features"][name] for name in features] for row in chunk], dtype=float)
        x = (x - mean) / scale
        symbols = np.asarray([CORE_SYMBOLS.index(row["symbol"]) for row in chunk], dtype=int)
        conditional = alpha[:, None] + symbol_effect[:, symbols] + beta @ x.T
        means = conditional.mean(axis=0)
        q05 = np.quantile(conditional, 0.05, axis=0)
        positive = np.mean(conditional > 0, axis=0)
        for index, row in enumerate(chunk):
            predictions.append(
                {
                    "sample_id": row["sample_id"],
                    "signal_time": row["signal_time"],
                    "symbol": row["symbol"],
                    "action": row["action"],
                    "partition": row["partition"],
                    "posterior_mean_net_r": float(means[index]),
                    "posterior_q05_conditional_mean_net_r": float(q05[index]),
                    "posterior_probability_conditional_mean_positive": float(positive[index]),
                    "passes_action_gate": bool(q05[index] > 0.0),
                    "model_version": artifact["version"],
                    "model_artifact_hash": artifact["artifact_hash"],
                    "scope": "DEV_ONLY_EXPOSED_RESEARCH",
                    "calibrated_probability": False,
                }
            )
    if output is not None:
        if output.exists():
            raise FileExistsError(output)
        payload = "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in predictions)
        output.write_bytes(gzip.compress(payload.encode("utf-8"), mtime=0))
    return predictions
