"""Resumable fold training and predictions. Budgets never become full evidence."""
from pathlib import Path
import numpy as np

from .contracts import atomic_json, digest, file_hash, read_json, stamp, utc
from .sequences import Panel, partition, fit_transform, transform
from .retrieval import Retriever, ar_fit, ar_predict


def preprocessing(run, panel, fold):
    key = "fit_" + fold["id"]
    with run.phase(key) as out:
        if out is not None:
            rows = partition(run, panel, fold, "train")
            fitted = fit_transform(panel, rows)
            atomic_json(out / "transform.json", fitted)
            atomic_json(out / "ar.json", ar_fit(panel, rows))
            # Distributional baseline is train-only, not estimated from report outcomes.
            q = np.quantile(panel.outcomes(rows), [.1, .5, .9], axis=0).T
            q -= q[:, 1:2]
            atomic_json(out / "uncertainty.json", q.tolist())
            atomic_json(out / "identity.json", {"dataset_hash": panel.manifest["dataset_hash"],
                        "contract_hash": run.frozen["contract_hash"], "train_end": fold["train_end"],
                        "training_ids_hash": digest(panel.identities(rows))})
    return read_json(run.path / key / "transform.json")


def train(run, fold, seed, single=False):
    if seed not in run.config["tcn"]["seeds"]:
        raise ValueError("Unregistered seed")
    if single and seed != run.config["tcn"]["seeds"][0]:
        raise ValueError("Ablation is primary seed only")
    panel = Panel(run)
    fitted = preprocessing(run, panel, fold)
    name = f"train_{fold['id']}_{'tcn1h' if single else 'tcn'}_{seed}"
    with run.phase(name) as out:
        if out is None:
            return
        from .tcn import fit
        rows, validation = partition(run, panel, fold, "train"), partition(run, panel, fold, "validation")
        diagnostics = fit(panel, rows, validation, fitted, run.config["tcn"], seed, out, single)
        artifact = {"method": "tcn_1h" if single else "tcn", "scope": "DEV_ONLY",
                    "runtime_enabled": False, "execution_enabled": False,
                    "contract_hash": run.frozen["contract_hash"], "dataset_hash": panel.manifest["dataset_hash"],
                    "transform_hash": digest(fitted), "weights_hash": file_hash(out / "weights.pt"),
                    "feature_order": run.config["features"], "fold": fold, "diagnostics": diagnostics,
                    "actual_fit_finished_at": utc(), "historical_availability": "DEVELOPMENT_REPLAY_NOT_PIT_DEPLOYMENT"}
        artifact["artifact_hash"] = digest(artifact)
        atomic_json(out / "artifact.json", artifact)


def load_model(run, panel, fold, method, seed, fitted):
    import torch
    from .tcn import PathTCN
    directory = run.path / f"train_{fold['id']}_{'tcn1h' if method == 'tcn_1h' else 'tcn'}_{seed}"
    artifact = read_json(directory / "artifact.json")
    if (artifact.get("runtime_enabled") is not False or artifact.get("execution_enabled") is not False
            or artifact.get("scope") != "DEV_ONLY"
            or digest({k: v for k, v in artifact.items() if k != "artifact_hash"}) != artifact["artifact_hash"]
            or artifact["dataset_hash"] != panel.manifest["dataset_hash"]
            or artifact["contract_hash"] != run.frozen["contract_hash"]
            or artifact["transform_hash"] != digest(fitted)
            or artifact["feature_order"] != run.config["features"]
            or artifact["fold"] != fold
            or file_hash(directory / "weights.pt") != artifact["weights_hash"]):
        raise ValueError("Unsafe or incompatible model artifact")
    torch.set_num_threads(2)
    model = PathTCN(method == "tcn_1h")
    model.load_state_dict(torch.load(directory / "weights.pt", map_location="cpu", weights_only=True))
    model.eval()
    return model


def predict(run, fold, method, *, kind="report", seed=20260913, max_samples=0):
    if method not in ("constant", "ar1", "nearest", "dtw", "tcn", "tcn_1h"):
        raise ValueError("Unknown forecast method")
    if kind not in ("validation", "report", "appendix"):
        raise ValueError("Unknown inference partition")
    panel = Panel(run)
    fitted = preprocessing(run, panel, fold)
    rows = partition(run, panel, fold, kind)
    train_rows = partition(run, panel, fold, "train")
    trained_symbols = {s for s in range(len(panel.symbols)) if sum(ss == s for ss, _ in train_rows) >= 30}
    retriever = Retriever(panel, train_rows, fitted, method) if method in ("nearest", "dtw") else None
    model = load_model(run, panel, fold, method, seed, fitted) if method.startswith("tcn") else None
    ar = read_json(run.path / f"fit_{fold['id']}/ar.json")
    uncertainty = np.asarray(read_json(run.path / f"fit_{fold['id']}/uncertainty.json"))
    key = f"predict_{fold['id']}_{kind}_{method}_{seed}"
    completed = 0
    for offset in range(0, len(rows), 16):
        chunk = rows[offset:offset + 16]
        chunk_key = key + f"_{offset:07d}"
        exists = (run.path / chunk_key / "complete.json").exists()
        if not exists and max_samples and completed + len(chunk) > max_samples:
            break
        with run.phase(chunk_key) as out:
            if out is None:
                continue
            pred = None
            if model is not None:
                import torch
                with torch.no_grad():
                    pred = model([torch.from_numpy(x.astype(np.float32)) for x in transform(panel.batch(chunk), fitted)]).numpy()
            records = []
            for n, row in enumerate(chunk):
                matches = []
                if row[0] not in trained_symbols:
                    q = None
                elif pred is not None:
                    q = pred[n]
                elif retriever is not None:
                    q, matches = retriever.predict(row)
                    # Input sequences are reconstructed from immutable sample IDs for reports.
                    for match in matches:
                        match.pop("input", None)
                else:
                    point = np.zeros(24) if method == "constant" else ar_predict(panel, row, ar)
                    q = None if point is None else uncertainty + point[:, None]
                identity = panel.identities([row])[0]
                s, i = row
                truth = panel.symbols[s].labels[i]
                valid_outcome = np.isfinite(truth).all()
                if q is not None and (np.asarray(q).shape != (24, 3) or not np.isfinite(q).all() or np.any(np.diff(q, axis=1) < 0)):
                    raise ValueError("Invalid forecast quantiles")
                records.append({**identity, "method": method, "fold": fold["id"], "partition": kind,
                                "seed": seed, "dataset_hash": panel.manifest["dataset_hash"],
                                "contract_hash": run.frozen["contract_hash"], "scope": "DEV_ONLY",
                                "predicted_log_path": None if q is None else np.asarray(q).tolist(),
                                "actual_log_path": truth.tolist() if valid_outcome else None,
                                "neighbours": matches, "forecast_status": "ABSTAIN" if q is None else
                                ("LIMITED_EVIDENCE" if retriever and len(matches) < 20 else "AVAILABLE"),
                                "actual_generated_at": utc(), "source_time_basis": "HISTORICAL_CLOSE_PROXY",
                                "forecast_id": digest([key, identity["symbol"], identity["signal_time"]])})
                if q is None:
                    records[-1]["abstention_reason"] = "INSUFFICIENT_TRAINING_CONTEXT" if row[0] not in trained_symbols else "NO_ELIGIBLE_ANALOGUE_OR_BASELINE"
            atomic_json(out / "predictions.json", records)
            completed += len(chunk)
            print(key, offset + len(chunk), "/", len(rows), flush=True)
    expected = {digest([key, i["symbol"], i["signal_time"]]) for i in panel.identities(rows)}
    found = set()
    for directory in sorted(run.path.glob(key + "_*")):
        if (directory / "complete.json").exists():
            found.update(r["forecast_id"] for r in read_json(directory / "predictions.json"))
    atomic_json(run.path / (key + "_progress.json"), {"expected": len(expected), "completed": len(found),
                "complete": found == expected, "missing": len(expected - found), "scope": "DEV_ONLY",
                "budget_limited": bool(max_samples), "at": utc()})
