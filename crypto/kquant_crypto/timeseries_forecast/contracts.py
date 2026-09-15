"""Immutable contracts and atomic, resumable research artifacts."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import importlib.metadata

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
SEALED = 1776038400


def stamp(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    with tmp.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate(c):
    if c["scope"] != "DEV_ONLY_EXPOSED_RESEARCH" or c["execution_enabled"] is not False or c["runtime_enabled"] is not False:
        raise ValueError("Research-only contract required")
    if tuple(c["symbols"]) != SYMBOLS or c["horizon"] != 24:
        raise ValueError("Frozen universe/horizon changed")
    if c["windows"] != {"1h": 168, "4h": 180, "1d": 180}:
        raise ValueError("Frozen context changed")
    if stamp(c["cutoff_exclusive"]) > min(stamp(c["sealed_from"]), SEALED):
        raise ValueError("Sealed history access denied")
    if any(c["claims"].values()) or c["neighbours"] != 20:
        raise ValueError("Invalid claims or neighbour count")
    expected_features = ["anchored_log_close", "log_high_low", "log1p_quote_volume", "log1p_trade_count", "taker_buy_fraction"]
    if c["features"] != expected_features or c["embargo_hours"] != 24 or c["dtw_band_fraction"] != .1 or c["group_days"] != 7:
        raise ValueError("Unregistered feature or time contract")
    if any(c["tcn"][k] != v for k, v in {"channels": 32, "kernel": 3, "dilations": [1, 2, 4, 8, 16, 32, 64], "dropout": .1}.items()):
        raise ValueError("Unregistered TCN architecture")
    return c


@dataclass(frozen=True)
class SequenceSample:
    symbol: str
    signal_time: int
    input_start: int
    label_available_at: int
    label_status: str
    dataset_hash: str


@dataclass(frozen=True)
class AnalogueMatch:
    symbol: str
    signal_time: int
    distance: float
    group_id: int


@dataclass(frozen=True)
class PathForecast:
    symbol: str
    signal_time: int
    method: str
    quantiles: list
    evidence_scope: str = "DEV_ONLY_NOT_CALIBRATED"


@dataclass(frozen=True)
class ForecastArtifact:
    method: str
    contract_hash: str
    dataset_hash: str
    train_cutoff: int
    scope: str = "DEV_ONLY"
    runtime_enabled: bool = False


class Run:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.frozen = read_json(self.path / "frozen.json")
        self.config = validate(self.frozen["config"])
        if digest(self.config) != self.frozen["contract_hash"]:
            raise ValueError("Frozen contract corrupted")
        for source, expected in self.frozen["source_hashes"].items():
            if file_hash(source) != expected:
                raise ValueError(f"Source changed: new run required: {source}")

    def baseline_changes(self):
        return [p for p, h in self.frozen["baseline_hashes"].items() if not Path(p).exists() or file_hash(p) != h]

    @contextmanager
    def phase(self, key):
        if not key.replace("_", "").isalnum():
            raise ValueError("Invalid phase key")
        root = self.path / key
        root.mkdir(exist_ok=True)
        marker = root / "complete.json"
        if marker.exists():
            for name, expected in read_json(marker)["files"].items():
                if file_hash(root / name) != expected:
                    raise ValueError(f"Artifact changed: {name}")
            yield None
            return
        lock = root / "writer.lock"
        with lock.open("x", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "started_at": utc()}, handle)
        try:
            yield root
            for source, expected in self.frozen["source_hashes"].items():
                if file_hash(source) != expected:
                    raise ValueError("Source changed during phase")
            files = {str(p.relative_to(root)): file_hash(p) for p in root.rglob("*")
                     if p.is_file() and p.name not in {"writer.lock", "complete.json"} and not p.name.endswith(".tmp")}
            atomic_json(marker, {"finished_at": utc(), "files": files})
        except Exception as exc:
            error = root / f"failure_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}.json"
            atomic_json(error, {"error_type": type(exc).__name__, "message": str(exc), "at": utc()})
            raise
        finally:
            lock.unlink()


def freeze(path, config, crypto_root):
    path = Path(path)
    c = validate(read_json(config))
    path.mkdir(parents=True, exist_ok=False)
    sources = sorted(Path(__file__).parent.glob("*.py"))
    sources += [Path(config), Path(crypto_root) / "scripts/run_timeseries_forecast.py"]
    baseline = {}
    repo = Path(crypto_root).parent
    tracked = subprocess.run(["git", "ls-files"], cwd=repo, capture_output=True, text=True, check=True).stdout.splitlines()
    for name in tracked:
        p = repo / name
        if p.is_file():
            baseline[str(p)] = file_hash(p)
    prior = Path(crypto_root) / c["reuse"] / "manifest.json"
    if prior.exists():
        baseline[str(prior)] = file_hash(prior)
        for p in prior.parent.glob("*_5m.parquet"):
            baseline[str(p)] = file_hash(p)
    atomic_json(path / "frozen.json", {
        "at": utc(), "config": c, "contract_hash": digest(c),
        "source_hashes": {str(p.resolve()): file_hash(p) for p in sources},
        "baseline_hashes": baseline, "crypto_root": str(Path(crypto_root).resolve()),
        "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip(),
        "python": sys.executable, "python_version": sys.version, "platform": platform.platform(),
        "dependencies": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
        "scope": "DEV_ONLY", "sealed_from": SEALED,
    })
    return Run(path)


def recover_lock(run, key, alive=None):
    if not key.replace("_", "").isalnum():
        raise ValueError("Invalid phase")
    if alive is None:
        import psutil
        alive = psutil.pid_exists
    lock = run.path / key / "writer.lock"
    owner = read_json(lock)
    if alive(owner["pid"]):
        raise ValueError("Owner process still exists; never stop or steal a writer")
    archive = lock.with_name("abandoned_writer_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + ".json")
    lock.rename(archive)
    return archive
