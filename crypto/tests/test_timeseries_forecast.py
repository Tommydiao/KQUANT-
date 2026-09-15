import copy
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import numpy as np
import pandas as pd
import pytest

from kquant_crypto.timeseries_forecast.contracts import validate, stamp, digest, Run, atomic_json, recover_lock
from kquant_crypto.timeseries_forecast.data import aggregate, archive_requests, parse_archive, valid_rows
from kquant_crypto.timeseries_forecast.sequences import SymbolPanel, partition, fit_transform, transform
from kquant_crypto.timeseries_forecast.retrieval import dtw_distance, multi_distance, Retriever
from kquant_crypto.timeseries_forecast.evaluation import metrics, holm, bootstrap_difference

CONFIG = Path(__file__).resolve().parents[1] / "config/timeseries_forecast_v1.json"


@pytest.fixture
def config():
    return json.loads(CONFIG.read_text())


def prices(n=5200, start=1609459200):
    t = np.arange(n)
    close = 100 * np.exp(.00003 * t + .01 * np.sin(t / 9))
    return pd.DataFrame({"open": close * .999, "high": close * 1.002, "low": close * .997,
                         "close": close, "volume": 10 + t % 7, "quote_volume": close * (10 + t % 7),
                         "trade_count": 100 + t % 13, "taker_buy_quote_volume": close * (10 + t % 7) * (.5 + .1 * np.sin(t))},
                        index=start + t * 3600)


def test_boundary_and_claims(config):
    validate(config)
    for key, value in [("cutoff_exclusive", "2026-04-14"), ("runtime_enabled", True), ("execution_enabled", True)]:
        c = copy.deepcopy(config)
        c[key] = value
        with pytest.raises(ValueError):
            validate(c)


def test_requests_do_not_fetch_sealed_month(config):
    requests = list(archive_requests(config))
    assert all(end <= stamp("2026-04-13") for _, _, end, _, _ in requests)
    assert not any(name.endswith("2026-04.zip") for *_, name in requests)
    assert any(name.endswith("2026-04-12.zip") for *_, name in requests)
    assert not any(stamp("2021-01-01") <= start < stamp("2025-01-01") for _, start, *_ in requests)


def test_complete_aggregation_and_order():
    df = prices(48)
    a = aggregate(df, 14400)
    b = aggregate(df.sample(frac=1, random_state=1), 14400)
    pd.testing.assert_frame_equal(a, b)
    assert a.complete.all()
    assert a.index[0] == df.index[0] + 14400
    assert not aggregate(df.drop(df.index[1]), 14400).complete.iloc[0]


def test_duplicate_and_invalid_flow():
    df = prices(48)
    with pytest.raises(ValueError):
        aggregate(pd.concat([df, df.iloc[:1]]), 3600)
    df.loc[df.index[0], "taker_buy_quote_volume"] = 1e20
    assert not valid_rows(df).iloc[0]
    assert not aggregate(df, 86400).complete.iloc[0]


@pytest.mark.parametrize("unit", [1000, 1000000])
def test_archive_units_and_identity(tmp_path, unit):
    start = stamp("2020-01-01")
    row = [start * unit, 100, 102, 99, 101, 10, (start + 3600) * unit - 1, 1010, 5, 5, 505, 0]
    path = tmp_path / "x.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("BTCUSDT-1h-2020-01.csv", ",".join(map(str, row)))
    frame = parse_archive(path, "BTCUSDT", start, start + 3600, stamp("2026-04-13"))
    assert frame.index[0] == start
    with pytest.raises(ValueError):
        parse_archive(path, "SOLUSDT", start, start + 3600, stamp("2026-04-13"))
    with pytest.raises(ValueError):
        parse_archive(path, "BTCUSDT", start, stamp("2026-04-14"), stamp("2026-04-13"))


def test_native_time_conflicts_are_audited_not_repaired(tmp_path):
    start = stamp("2020-01-01")
    good = [start * 1000, 100, 102, 99, 101, 10, (start + 3600) * 1000 - 1, 1010, 5, 5, 505, 0]
    bad = list(good)
    bad[0] += 3600000
    bad[6] += 3600000 - 1500
    path = tmp_path / "native.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("BTCUSDT-1h-2020-01.csv", "\n".join(",".join(map(str, r)) for r in [good, bad]))
    with pytest.raises(ValueError, match="timestamp"):
        parse_archive(path, "BTCUSDT", start, start + 7200, stamp("2026-04-13"))
    audit = []
    result = parse_archive(path, "BTCUSDT", start, start + 7200, stamp("2026-04-13"), audit)
    assert list(result.index) == [start]
    assert len(audit) == 1 and audit[0]["raw_close_time"] == bad[6]
    assert audit[0]["action"] == "EXCLUDED_NOT_REPAIRED"


def test_future_perturbation(config):
    raw = prices()
    before = SymbolPanel("BTCUSDT", aggregate(raw, 3600), config["windows"])
    index = 4700
    altered = raw.copy()
    altered.loc[altered.index[index + 1:], ["open", "high", "low", "close", "quote_volume", "taker_buy_quote_volume"]] *= 4
    after = SymbolPanel("BTCUSDT", aggregate(altered, 3600), config["windows"])
    for a, b in zip(before.window(index), after.window(index)):
        np.testing.assert_array_equal(a, b)
    assert not np.array_equal(before.labels[index], after.labels[index])


def test_forming_daily_not_visible(config):
    raw = prices()
    p = SymbolPanel("BTCUSDT", aggregate(raw, 3600), config["windows"])
    i = 4700
    assert all(p.frames[s].index[p.positions[s][i]] <= p.times[i] for s in config["windows"])
    assert p.frames["1d"].index[p.positions["1d"][i]] % 86400 == 0


def test_missing_future_is_not_missing_input(config):
    p = SymbolPanel("BTCUSDT", aggregate(prices(), 3600), config["windows"])
    assert p.input_valid[-1] and not p.label_valid[-1]
    assert p.label_available[-1] > p.times[-1]
    assert np.isnan(p.labels[-1]).all()


def test_gap_invalidates_windows_not_filled(config):
    df = prices()
    df = df.drop(df.index[4600])
    p = SymbolPanel("BTCUSDT", aggregate(df, 3600), config["windows"])
    assert p.input_valid[4599]
    assert not p.label_valid[4599]
    assert not p.input_valid[4601]


def test_partition_uses_maturity_and_embargo(config):
    class Fake:
        def rows(self, start, end, training=False):
            return start, end, training
    run = SimpleNamespace(config=config)
    fold = config["folds"][0]
    start, end, training = partition(run, Fake(), fold, "validation")
    assert start == stamp(fold["train_end"]) + 86400
    assert end == stamp(fold["validation_end"]) - 86400 and training
    assert partition(run, Fake(), fold, "report")[2] is False


def test_dtw_identity_and_symmetry():
    rng = np.random.default_rng(1)
    a, b = rng.normal(size=(20, 5)), rng.normal(size=(20, 5))
    assert dtw_distance(a, a, 2) == 0
    assert dtw_distance(a, b, 2) == pytest.approx(dtw_distance(b, a, 2))
    assert multi_distance([a] * 3, [a] * 3, "nearest") == 0


def test_training_transform_ignores_other_rows():
    class Fake:
        symbols = [SimpleNamespace(label_available=np.arange(100))]
        def batch(self, rows):
            return [np.asarray([np.arange(30).reshape(6, 5) + i for _, i in rows], np.float32)] * 3
    fitted = fit_transform(Fake(), [(0, i) for i in range(10)])
    assert fitted["maximum_label_available_at"] == 9
    assert fitted == fit_transform(Fake(), [(0, i) for i in range(10)])


def test_retrieval_weekly_dedup_and_future_guard():
    class Fake:
        def __init__(self):
            self.symbols = [SimpleNamespace(times=np.arange(50) * 86400, label_available=(np.arange(50) + 1) * 86400,
                                           labels=np.tile(np.arange(24), (50, 1)))]
        def batch(self, rows):
            return [np.asarray([np.full((10, 5), i / 100) for _, i in rows])] * 3
    p = Fake()
    p.symbols[0].window = lambda i: [np.zeros((10, 5))] * 3
    fitted = {"mean": np.zeros((3, 5)).tolist(), "scale": np.ones((3, 5)).tolist()}
    engine = Retriever(p, [(0, i) for i in range(40)], fitted, "nearest")
    q, cases = engine.predict((0, 49))
    assert len(cases) == len({r["group_id"] for r in cases}) == 6
    assert q.shape == (24, 3)
    p.symbols[0].label_available[0] = 100 * 86400
    with pytest.raises(ValueError):
        engine.predict((0, 49))


def test_holm_monotonic_and_metrics():
    assert holm({"a": .01, "b": .04, "c": .2}) == pytest.approx({"a": .03, "b": .08, "c": .2})
    r = {"actual_log_path": [0.] * 24, "predicted_log_path": [[-.1, 0., .1]] * 24}
    assert metrics([r])["path_mae"] == 0
    assert metrics([r])["pointwise_80_coverage"] == 1


def test_atomic_phase_resume_and_integrity(tmp_path, config):
    atomic_json(tmp_path / "frozen.json", {"config": config, "contract_hash": digest(config), "source_hashes": {}})
    run = Run(tmp_path)
    with pytest.raises(RuntimeError):
        with run.phase("test") as p:
            atomic_json(p / "chunk.json", {"value": 1})
            raise RuntimeError("database-like write failure")
    assert not (tmp_path / "test/writer.lock").exists()
    with run.phase("test") as p:
        assert json.loads((p / "chunk.json").read_text())["value"] == 1
    with run.phase("test") as p:
        assert p is None
    (tmp_path / "test/chunk.json").write_text("{}")
    with pytest.raises(ValueError):
        with run.phase("test"):
            pass


def test_lock_does_not_steal_live_writer(tmp_path, config):
    atomic_json(tmp_path / "frozen.json", {"config": config, "contract_hash": digest(config), "source_hashes": {}})
    run = Run(tmp_path)
    atomic_json(tmp_path / "job/writer.lock", {"pid": 123})
    with pytest.raises(ValueError):
        recover_lock(run, "job", lambda _: True)
    archive = recover_lock(run, "job", lambda _: False)
    assert archive.exists() and not (tmp_path / "job/writer.lock").exists()


def test_tcn_causality_and_quantile_order():
    torch = pytest.importorskip("torch")
    from kquant_crypto.timeseries_forecast.tcn import CausalConv, PathTCN
    torch.set_num_threads(2)
    torch.manual_seed(42)
    conv = CausalConv(5, 32, 2).eval()
    x = torch.randn(1, 5, 40)
    y = x.clone()
    y[:, :, 20:] += 100
    assert torch.equal(conv(x)[:, :, :20], conv(y)[:, :, :20])
    model = PathTCN().eval()
    xs = [torch.randn(2, n, 5) for n in (168, 180, 180)]
    with torch.no_grad():
        a, b = model(xs), model(xs)
    assert a.shape == (2, 24, 3)
    assert torch.equal(a, b) and torch.all(torch.diff(a, dim=2) >= 0)


def test_no_execution_imports():
    root = Path(__file__).resolve().parents[1] / "kquant_crypto/timeseries_forecast"
    for p in root.glob("*.py"):
        text = p.read_text()
        assert "import execution" not in text and "import gateway" not in text
        assert "create_order(" not in text


def test_incomplete_evaluation_never_passes(tmp_path, config):
    from kquant_crypto.timeseries_forecast.evaluation import evaluate
    atomic_json(tmp_path / "frozen.json", {"config": config, "contract_hash": digest(config), "source_hashes": {}})
    path = evaluate(Run(tmp_path))
    result = json.loads((path / "results.json").read_text())
    assert all(d["status"] == "PREDICTION_UNPROVEN" for d in result["decisions"].values())
    assert result["profitability_pass"] is False


def test_checkpoint_resume_matches_uninterrupted(tmp_path, config):
    torch = pytest.importorskip("torch")
    from kquant_crypto.timeseries_forecast.tcn import fit
    class SmallPanel:
        def batch(self, rows):
            return [np.stack([np.sin(np.arange(n * 5).reshape(n, 5) / 100 + i).astype(np.float32) for _, i in rows]) for n in (168, 180, 180)]
        def outcomes(self, rows):
            return np.asarray([np.arange(24) * .0001 + i * .00001 for _, i in rows], np.float32)
    fitted = {"mean": np.zeros((3, 5)).tolist(), "scale": np.ones((3, 5)).tolist()}
    full, resumed = tmp_path / "full", tmp_path / "resumed"
    full.mkdir()
    resumed.mkdir()
    settings = dict(config["tcn"], epochs=2, batch_size=2)
    args = SmallPanel(), [(0, 0), (0, 1)], [(0, 2), (0, 3)], fitted
    fit(*args, settings, 42, full)
    fit(*args, dict(settings, epochs=1), 42, resumed)
    fit(*args, settings, 42, resumed)
    a = torch.load(full / "weights.pt", weights_only=True)
    b = torch.load(resumed / "weights.pt", weights_only=True)
    assert all(torch.equal(a[k], b[k]) for k in a)
    assert json.loads((full / "training_curve.json").read_text()) == json.loads((resumed / "training_curve.json").read_text())
