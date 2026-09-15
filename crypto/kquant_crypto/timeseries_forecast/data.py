"""Official archives only; no sealed rows, interpolation, or fabricated receipts."""
import calendar
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import time
import urllib.error
import urllib.request
import zipfile

import numpy as np
import pandas as pd

from .contracts import SEALED, atomic_json, digest, file_hash, read_json, stamp, utc

FIELDS = ["open", "high", "low", "close", "volume", "quote_volume", "trade_count", "taker_buy_quote_volume"]
BASE = "https://data.binance.vision/data/spot"


def valid_rows(df):
    x = df[FIELDS].to_numpy(float)
    return (np.isfinite(x).all(axis=1) & (df[["open", "high", "low", "close"]].min(axis=1) > 0)
            & (df.high >= df[["open", "close", "low"]].max(axis=1))
            & (df.low <= df[["open", "close", "high"]].min(axis=1))
            & (df.volume >= 0) & (df.quote_volume > 0) & (df.trade_count > 0)
            & (df.trade_count == np.floor(df.trade_count))
            & (df.taker_buy_quote_volume >= 0) & (df.taker_buy_quote_volume <= df.quote_volume))


def aggregate(df, seconds, source_seconds=3600):
    if not df.index.is_unique or np.any(df.index.to_numpy() % source_seconds):
        raise ValueError("Duplicate/unaligned bars")
    df = df.sort_index().copy()
    df["valid"] = valid_rows(df).astype(int)
    groups = df.index.to_numpy() // seconds * seconds
    rules = {"open": ("open", "first"), "high": ("high", "max"), "low": ("low", "min"), "close": ("close", "last")}
    rules.update({k: (k, "sum") for k in FIELDS[4:]})
    rules["valid"] = ("valid", "sum")
    out = df.groupby(groups).agg(**rules)
    out = out.reindex(np.arange(df.index.min() // seconds * seconds, df.index.max() // seconds * seconds + seconds, seconds))
    out["complete"] = out.valid == seconds // source_seconds
    out.loc[~out.complete, FIELDS] = np.nan
    out.index = out.index + seconds  # Available-at close proxy, never real receipt.
    return out


def parse_archive(path, symbol, start, end, cutoff, rejected=None):
    if end > cutoff or cutoff > SEALED:
        raise ValueError("Archive intersects sealed boundary")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != 1 or not names[0].startswith(symbol + "-1h-") or not names[0].endswith(".csv"):
            raise ValueError("Archive identity mismatch")
        raw = pd.read_csv(io.BytesIO(archive.read(names[0])), header=None)
    if raw.shape[1] != 12:
        raise ValueError("Unexpected kline schema")
    starts = pd.to_numeric(raw[0], errors="raise").to_numpy(np.int64)
    ends = pd.to_numeric(raw[6], errors="raise").to_numpy(np.int64)
    unit = np.where(starts >= 100_000_000_000_000, 1_000_000, 1000)
    secs = starts // unit
    invalid_time = (starts % unit != 0) | (secs % 3600 != 0) | (ends != (secs + 3600) * unit - 1)
    if np.any(secs < start) or np.any(secs + 3600 > end) or np.any(secs + 3600 > cutoff):
        raise ValueError("Out-of-contract historical rows")
    if invalid_time.any():
        if rejected is None:
            raise ValueError("Invalid timestamp unit or close time")
        for i in np.flatnonzero(invalid_time):
            rejected.append({"archive": Path(path).name, "symbol": symbol, "row": int(i),
                             "raw_open_time": int(starts[i]), "raw_close_time": int(ends[i]),
                             "reason": "INVALID_NATIVE_HOURLY_TIME_CONTRACT", "action": "EXCLUDED_NOT_REPAIRED"})
        raw = raw.loc[~invalid_time]
        secs = secs[~invalid_time]
    df = pd.DataFrame({k: pd.to_numeric(raw[i], errors="raise").to_numpy() for k, i in zip(FIELDS, [1, 2, 3, 4, 5, 7, 8, 10])}, index=secs)
    if not df.index.is_unique:
        raise ValueError("Duplicate archive timestamps")
    return df.sort_index()


def archive_requests(c):
    cutoff = stamp(c["cutoff_exclusive"])
    first = datetime.fromisoformat(c["start"]).replace(tzinfo=timezone.utc)
    for symbol in c["symbols"]:
        current = first
        while int(current.timestamp()) < cutoff:
            next_month = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
            start, end = int(current.timestamp()), int(next_month.timestamp())
            if start >= stamp(c["reuse_start"]) and end <= stamp(c["reuse_end"]):
                current = next_month
                continue
            if end <= cutoff:
                name = f"{symbol}-1h-{current:%Y-%m}.zip"
                yield symbol, start, end, f"{BASE}/monthly/klines/{symbol}/1h/{name}", name
            else:
                day = current
                while int((day + timedelta(days=1)).timestamp()) <= cutoff:
                    name = f"{symbol}-1h-{day:%Y-%m-%d}.zip"
                    yield symbol, int(day.timestamp()), int((day + timedelta(days=1)).timestamp()), f"{BASE}/daily/klines/{symbol}/1h/{name}", name
                    day += timedelta(days=1)
            current = next_month


def download(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in (401, 403, 451):
                raise RuntimeError(f"Provider denied public request: HTTP {exc.code}") from exc
            if attempt == 2:
                raise
        except (TimeoutError, urllib.error.URLError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


def fetch(run):
    with run.phase("fetch") as out:
        if out is None:
            return
        archive_dir = out / "archives"
        archive_dir.mkdir(exist_ok=True)
        records = []
        for symbol, start, end, url, name in archive_requests(run.config):
            meta = archive_dir / (name + ".json")
            path = archive_dir / name
            if meta.exists():
                record = read_json(meta)
                if record["status"] == "AVAILABLE" and file_hash(path) != record["sha256"]:
                    raise ValueError("Archive changed after receipt")
            else:
                checksum = download(url + ".CHECKSUM")
                record = {"symbol": symbol, "start": start, "end": end, "url": url, "name": name, "received_at": utc()}
                if checksum is None:
                    record["status"] = "NOT_PUBLISHED_OR_NOT_LISTED"
                else:
                    expected = checksum.decode().split()[0].lower()
                    payload = download(url)
                    if payload is None:
                        raise ValueError("Checksum exists without archive")
                    import hashlib
                    if hashlib.sha256(payload).hexdigest() != expected:
                        raise ValueError("Official checksum mismatch")
                    if path.exists() and file_hash(path) != expected:
                        raise ValueError("Uncommitted archive conflict")
                    if not path.exists():
                        path.write_bytes(payload)
                    (archive_dir / (name + ".CHECKSUM")).write_bytes(checksum)
                    record.update(status="AVAILABLE", sha256=expected, bytes=len(payload))
                atomic_json(meta, record)
            records.append(record)
            print(name, record["status"], flush=True)
        atomic_json(out / "manifest.json", {"records": records, "scope": "DEV_ONLY", "cutoff": stamp(run.config["cutoff_exclusive"])})


def build(run):
    c = run.config
    with run.phase("build") as out:
        if out is None:
            return
        sources = read_json(run.path / "fetch/manifest.json")["records"]
        reuse = Path(run.frozen["crypto_root"]) / c["reuse"]
        old_audit = read_json(reuse / "manifest.json")
        confirmed = {(symbol, t // 3600 * 3600 + 3600) for symbol, t in old_audit.get("confirmed_halts", [])}
        report = {}
        rejected = []
        for symbol in c["symbols"]:
            old = reuse / f"{symbol}_5m.parquet"
            if file_hash(old) != run.frozen["baseline_hashes"][str(old)]:
                raise ValueError("Frozen reuse data changed")
            raw = pd.read_parquet(old)
            if raw.index.min() < stamp(c["reuse_start"]) or raw.index.max() + 300 > stamp(c["reuse_end"]):
                raise ValueError("Reuse date contract mismatch")
            old_hour = aggregate(raw, 3600, 300)
            old_hour.index -= 3600
            frames = [old_hour[FIELDS]]
            hashes = {str(old): file_hash(old)}
            for record in sources:
                if record["symbol"] != symbol or record["status"] != "AVAILABLE":
                    continue
                path = run.path / "fetch/archives" / record["name"]
                if file_hash(path) != record["sha256"]:
                    raise ValueError("Source hash mismatch")
                frames.append(parse_archive(path, symbol, record["start"], record["end"], stamp(c["cutoff_exclusive"]), rejected))
                hashes[str(path)] = record["sha256"]
            df = pd.concat(frames).sort_index()
            if not df.index.is_unique:
                raise ValueError("Overlapping sources must be resolved explicitly")
            hourly = aggregate(df, 3600)
            hourly.to_parquet(out / f"{symbol}.parquet")
            good = hourly.complete
            usable = hourly.index[good]
            gaps = [{"symbol": symbol, "close_time": int(t), "reason": "CONTAINS_CONFIRMED_HALT" if (symbol, int(t)) in confirmed else "INCOMPLETE_OR_INVALID_HOUR_UNKNOWN"} for t in hourly.index[~good]]
            atomic_json(out / f"{symbol}_gaps.json", gaps)
            report[symbol] = {"start": int(hourly.index.min()) - 3600, "end": int(hourly.index.max()),
                              "complete_hours": int(good.sum()), "expected_hours": len(hourly),
                              "coverage": float(good.mean()), "first_valid_close": int(usable.min()),
                              "calendar_years": float((hourly.index.max() - hourly.index.min() + 3600) / (365.25 * 86400)),
                              "source_hashes": hashes, "parquet_hash": file_hash(out / f"{symbol}.parquet")}
        atomic_json(out / "rejected_native_rows.json", rejected)
        atomic_json(out / "manifest.json", {"symbols": report, "dataset_hash": digest(report), "rejected_native_rows": len(rejected),
                    "availability": "HISTORICAL_CLOSE_PROXY_NOT_RECEIPT", "scope": "DEV_ONLY", "sealed_consumed": False})
