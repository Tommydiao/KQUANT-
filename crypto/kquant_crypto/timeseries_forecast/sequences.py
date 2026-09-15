"""Lazy multi-resolution windows with independent input and outcome eligibility."""
from collections import Counter
import numpy as np
import pandas as pd

from .contracts import atomic_json, file_hash, read_json, stamp
from .data import aggregate, FIELDS

SCALES = ("1h", "4h", "1d")
SECONDS = {"1h": 3600, "4h": 14400, "1d": 86400}


def feature_rows(frame):
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.column_stack([np.log(frame.close), np.log(frame.high / frame.low),
                                np.log1p(frame.quote_volume), np.log1p(frame.trade_count),
                                frame.taker_buy_quote_volume / frame.quote_volume]).astype(np.float64)


class SymbolPanel:
    def __init__(self, symbol, hourly, windows):
        self.symbol, self.windows = symbol, windows
        raw = hourly[FIELDS].copy()
        raw.index -= 3600
        self.frames = {"1h": hourly, "4h": aggregate(raw, 14400), "1d": aggregate(raw, 86400)}
        self.arrays = {key: feature_rows(frame) for key, frame in self.frames.items()}
        times = hourly.index.to_numpy(np.int64)
        self.times = times
        self.positions = {}
        valid = np.ones(len(times), dtype=bool)
        for scale in SCALES:
            frame = self.frames[scale]
            pos = np.searchsorted(frame.index, times, side="right") - 1
            self.positions[scale] = pos
            bad = (~np.isfinite(self.arrays[scale]).all(axis=1)).astype(int)
            count = np.concatenate([[0], np.cumsum(bad)])
            starts = pos + 1 - windows[scale]
            good = starts >= 0
            good &= count[np.maximum(pos + 1, 0)] - count[np.maximum(starts, 0)] == 0
            valid &= good
        self.input_valid = valid
        close = hourly.close.to_numpy(float)
        self.labels = np.full((len(times), 24), np.nan)
        for h in range(1, 25):
            with np.errstate(divide="ignore", invalid="ignore"):
                self.labels[:-h, h - 1] = np.log(close[h:] / close[:-h])
        self.label_valid = np.isfinite(self.labels).all(axis=1)
        self.label_available = times + 24 * 3600

    def window(self, i):
        if not self.input_valid[i]:
            raise ValueError("Invalid input window")
        result = []
        for scale in SCALES:
            end = self.positions[scale][i] + 1
            block = self.arrays[scale][end - self.windows[scale]:end].copy()
            block[:, 0] -= block[0, 0]
            result.append(block)
        return result


class Panel:
    def __init__(self, run):
        self.run = run
        self.manifest = read_json(run.path / "build/manifest.json")
        self.symbols = []
        for symbol in run.config["symbols"]:
            path = run.path / "build" / f"{symbol}.parquet"
            if file_hash(path) != self.manifest["symbols"][symbol]["parquet_hash"]:
                raise ValueError("Dataset integrity mismatch")
            self.symbols.append(SymbolPanel(symbol, pd.read_parquet(path), run.config["windows"]))

    def rows(self, start, end, *, training=False):
        result = []
        for s, panel in enumerate(self.symbols):
            mask = panel.input_valid & (panel.times >= start) & (panel.times < end)
            if training:
                mask &= panel.label_valid & (panel.label_available <= end)
            result.extend((s, int(i)) for i in np.flatnonzero(mask))
        return sorted(result, key=lambda pair: (self.symbols[pair[0]].times[pair[1]], pair[0]))

    def batch(self, rows):
        blocks = [[] for _ in SCALES]
        for s, i in rows:
            for j, block in enumerate(self.symbols[s].window(i)):
                blocks[j].append(block)
        return [np.asarray(block, dtype=np.float32) for block in blocks]

    def outcomes(self, rows):
        return np.asarray([self.symbols[s].labels[i] for s, i in rows], dtype=np.float32)

    def identities(self, rows):
        return [{"symbol": self.symbols[s].symbol, "signal_time": int(self.symbols[s].times[i]),
                 "label_available_at": int(self.symbols[s].label_available[i]),
                 "label_status": "MATURE" if self.symbols[s].label_valid[i] else "UNAVAILABLE",
                 "input_start": int(self.symbols[s].frames["1d"].index[self.symbols[s].positions["1d"][i] - 179]) - 86400}
                for s, i in rows]


def partition(run, panel, fold, kind):
    embargo = run.config["embargo_hours"] * 3600
    if kind == "train":
        return panel.rows(stamp(run.config["start"]), stamp(fold["train_end"]), training=True)
    if kind == "validation":
        return panel.rows(stamp(fold["train_end"]) + embargo, stamp(fold["validation_end"]) - embargo, training=True)
    if kind == "report":
        return panel.rows(stamp(fold["validation_end"]) + embargo, stamp(fold["report_end"]) - embargo)
    if kind == "appendix":
        if fold["id"] != run.config["appendix"]["uses_fold"]:
            raise ValueError("Appendix must use frozen last-fold model")
        return panel.rows(stamp(run.config["appendix"]["start"]) + embargo,
                          stamp(run.config["cutoff_exclusive"]) - 24 * 3600)
    raise ValueError(kind)


def fit_transform(panel, rows):
    if not rows:
        raise ValueError("No eligible training samples")
    count = np.zeros(3)
    total = np.zeros((3, 5))
    squared = np.zeros((3, 5))
    for offset in range(0, len(rows), 256):
        for j, x in enumerate(panel.batch(rows[offset:offset + 256])):
            a = x.astype(np.float64).reshape(-1, 5)
            count[j] += len(a)
            total[j] += a.sum(axis=0)
            squared[j] += (a * a).sum(axis=0)
    mean = total / count[:, None]
    scale = np.sqrt(np.maximum(squared / count[:, None] - mean * mean, 0))
    if not np.isfinite(mean).all() or np.any(scale < 1e-12):
        raise ValueError("Degenerate training transform")
    return {"mean": mean.tolist(), "scale": scale.tolist(), "training_rows": len(rows),
            "maximum_label_available_at": max(panel.symbols[s].label_available[i].item() for s, i in rows)}


def transform(blocks, fitted):
    return [(block - np.asarray(fitted["mean"][j], np.float32)) / np.asarray(fitted["scale"][j], np.float32)
            for j, block in enumerate(blocks)]


def audit_sequences(run):
    panel = Panel(run)
    report = {}
    for p in panel.symbols:
        report[p.symbol] = {"hours": len(p.times), "eligible_inputs": int(p.input_valid.sum()),
                            "mature_inputs": int((p.input_valid & p.label_valid).sum()),
                            "valid_input_unavailable_future": int((p.input_valid & ~p.label_valid).sum())}
    folds = {fold["id"]: {kind: len(partition(run, panel, fold, kind)) for kind in ("train", "validation", "report")}
             for fold in run.config["folds"]}
    atomic_json(run.path / "sequence_audit.json", {"symbols": report, "folds": folds,
                "independence": "Hourly windows overlap; counts are not independent observations"})
    return panel
