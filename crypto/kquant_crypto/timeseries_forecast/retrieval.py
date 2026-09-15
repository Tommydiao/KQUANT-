"""Exact same-symbol retrieval, weekly diversity and frozen training baselines."""
import numpy as np

try:
    from numba import njit
except ImportError:
    def njit(*args, **kwargs):
        return lambda f: f

from .sequences import transform


@njit(cache=True)
def dtw_distance(a, b, radius):
    n, d = a.shape
    previous = np.full(n + 1, np.inf)
    previous[0] = 0.
    for i in range(1, n + 1):
        current = np.full(n + 1, np.inf)
        for j in range(max(1, i - radius), min(n, i + radius) + 1):
            delta = 0.
            for f in range(d):
                delta += (a[i - 1, f] - b[j - 1, f]) ** 2
            current[j] = delta + min(previous[j], current[j - 1], previous[j - 1])
        previous = current
    return np.sqrt(previous[n] / (n * d))


def multi_distance(query, example, method):
    if method == "nearest":
        return float(np.mean([np.sqrt(np.mean((a - b) ** 2)) for a, b in zip(query, example)]))
    if method == "dtw":
        return float(np.mean([dtw_distance(a, b, int(np.ceil(len(a) * .1))) for a, b in zip(query, example)]))
    raise ValueError(method)


class Retriever:
    def __init__(self, panel, train, fitted, method):
        self.panel, self.train, self.fitted, self.method = panel, train, fitted, method
        self.by_symbol = {s: [(ss, i) for ss, i in train if ss == s] for s in range(len(panel.symbols))}

    def predict(self, row):
        s, i = row
        p = self.panel.symbols[s]
        query = [x[0] for x in transform(self.panel.batch([row]), self.fitted)]
        best = {}
        for offset in range(0, len(self.by_symbol[s]), 128):
            rows = self.by_symbol[s][offset:offset + 128]
            blocks = transform(self.panel.batch(rows), self.fitted)
            for j, (_, index) in enumerate(rows):
                if p.label_available[index] > p.times[i]:
                    raise ValueError("Future reference outcome in library")
                distance = multi_distance(query, [x[j] for x in blocks], self.method)
                group = int(p.times[index] // (7 * 86400))
                item = (distance, int(p.times[index]), index)
                if group not in best or item[:2] < best[group][:2]:
                    best[group] = item
        selected = sorted(best.values())[:20]
        if not selected:
            return None, []
        outcomes = np.asarray([p.labels[index] for _, _, index in selected])
        if not np.isfinite(outcomes).all():
            raise ValueError("Reference outcome unavailable")
        q = np.quantile(outcomes, [.1, .5, .9], axis=0).T
        matches = [{"distance": float(d), "signal_time": t, "group_id": int(t // (7 * 86400)),
                    "future_log_returns": p.labels[index].tolist(),
                    "input": [a.tolist() for a in p.window(index)]} for d, t, index in selected]
        return q, matches


def ar_fit(panel, train):
    parameters = {}
    for s, p in enumerate(panel.symbols):
        indices = [i for ss, i in train if ss == s]
        # Return pairs are unique market times, not duplicated overlapping windows.
        logs = np.log(p.frames["1h"].close.to_numpy())
        ret = np.diff(logs, prepend=np.nan)
        ii = np.asarray(indices, int)
        ii = ii[(ii > 0) & np.isfinite(ret[ii]) & np.isfinite(ret[ii - 1])]
        if len(ii) < 30:
            parameters[str(s)] = None
            continue
        design = np.column_stack([np.ones(len(ii)), ret[ii - 1]])
        intercept, slope = np.linalg.lstsq(design, ret[ii], rcond=None)[0]
        parameters[str(s)] = {"intercept": float(intercept), "slope": float(slope)}
    return parameters


def ar_predict(panel, row, params):
    s, i = row
    if params[str(s)] is None:
        return None
    close = panel.symbols[s].frames["1h"].close.to_numpy()
    r = np.log(close[i] / close[i - 1])
    total, result = 0., []
    for _ in range(24):
        r = params[str(s)]["intercept"] + params[str(s)]["slope"] * r
        total += r
        result.append(total)
    if not np.isfinite(result).all():
        raise ValueError("Unstable AR forecast")
    return np.asarray(result)
