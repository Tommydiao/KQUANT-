from datetime import UTC, datetime
import json

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from kquant_crypto.candidate_dataset import DAY, WARMUP, freeze_dataset, load_dataset
from kquant_crypto.strategy_dual_mode_v1 import Bar

END = int(datetime(2026, 9, 1, tzinfo=UTC).timestamp())


def _row(stamp, tf, symbol="BTCUSDT", **changes):
    return dict(source_time=datetime.fromtimestamp(stamp, UTC).isoformat(),
                instrument_id=f"binance:spot:{symbol}", venue="binance", market_type="spot",
                interval=tf, open=100., high=102., low=98., close=101., volume=1.,
                received_at="2026-09-02T00:00:00+00:00", provider_status="historical", **changes)


def _write(data, tf, rows):
    directory = data / "market" / "_compacted"
    directory.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), directory / f"closed_klines_spot_{tf}.parquet")


def _small(data, hours=24):
    for tf, step in (("5m", 300), ("1h", 3600)):
        _write(data, tf, [_row(t, tf) for t in range(END - hours * 3600, END, step)])


def test_freeze_roundtrip_provenance_stability_and_read_only(tmp_path):
    data = tmp_path / "data"
    _small(data)
    before = {p: p.read_bytes() for p in data.rglob("*.parquet")}
    one = freeze_dataset(data, tmp_path / "one", ["BTCUSDT"], as_of=END)
    two = freeze_dataset(data, tmp_path / "two", ["BTCUSDT"], as_of=END)
    assert one == two
    assert before == {p: p.read_bytes() for p in data.rglob("*.parquet")}
    bars = load_dataset(tmp_path / "one" / "data_manifest.json")
    assert len(bars["BTCUSDT"]["1h"]) == 24
    assert isinstance(bars["BTCUSDT"]["5m"][0], Bar)
    row = pq.read_table(tmp_path / "one" / "BTCUSDT_5m.parquet").to_pylist()[0]
    assert row["available_at"] == row["start"] + 300
    assert row["received_at"] == "2026-09-02T00:00:00+00:00"
    assert "assumed" in row["availability_basis"]
    assert one["exposure"]["independent_holdout"] is False
    assert one["original_historical_data_gate"]["modified"] is False
    assert not one["candidate_data_eligibility"]["BTCUSDT"]["historical"]["eligible"]
    with pytest.raises(FileExistsError):
        freeze_dataset(data, tmp_path / "one", ["BTCUSDT"], as_of=END)


def test_missing_conflicting_exact_invalid_and_mismatch_hours(tmp_path):
    data = tmp_path / "data"
    _small(data)
    path = data / "market/_compacted/closed_klines_spot_5m.parquet"
    rows = pq.read_table(path).to_pylist()
    rows.pop(0)
    rows.append(dict(rows[12]))
    rows.append(dict(rows[24], close=100.5))
    rows[36]["high"] = float("inf")
    _write(data, "5m", rows)
    hour_path = data / "market/_compacted/closed_klines_spot_1h.parquet"
    hours = pq.read_table(hour_path).to_pylist()
    hours[4]["high"] = 103.
    _write(data, "1h", hours)
    manifest = freeze_dataset(data, tmp_path / "out", ["BTCUSDT"], as_of=END)
    quality = manifest["quality"]["BTCUSDT"]
    assert quality["5m"]["exact_duplicate_rows"] == 1
    assert quality["5m"]["conflicting_duplicate_timestamps"] == 1
    assert any(x["reason"] == "invalid_ohlcv_or_timestamp" for x in quality["5m"]["excluded"])
    assert [x["reason"] for x in quality["1h"]["excluded"]].count("incomplete_12x5m") == 3
    assert any(x["reason"] == "hour_ohlc_mismatch" for x in quality["1h"]["excluded"])
    loaded = load_dataset(tmp_path / "out/data_manifest.json")["BTCUSDT"]
    assert len(loaded["1h"]) == 20
    assert len(loaded["5m"]) == 285
    assert quality["5m"]["coverage"]["gaps"]


def test_symbol_market_interval_filters_and_shared_future_cutoff(tmp_path):
    data = tmp_path / "data"
    for tf, step in (("5m", 300), ("1h", 3600)):
        rows = [_row(t, tf, s) for s in ("BTCUSDT", "ETHUSDT")
                for t in range(END - 2 * DAY, END + DAY, step)
                if s == "BTCUSDT" or t < END]
        rows += [dict(_row(END - DAY, tf), market_type="perpetual", close=999.)]
        rows += [dict(_row(END - DAY, tf), venue="other", close=999.)]
        rows += [dict(_row(END - DAY, tf), interval="1m", close=999.)]
        rows += [_row(END - DAY, tf, "AAAUSDT") for _ in range(1000)]
        _write(data, tf, rows)
    manifest = freeze_dataset(data, tmp_path / "out", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], as_of=END + DAY)
    assert manifest["window"]["end"] == END
    assert manifest["profile"]["raw_rows_read"]["5m"] == 4 * DAY // 300
    assert manifest["quality"]["BTCUSDT"]["5m"]["conflicting_duplicate_timestamps"] == 0
    assert not manifest["candidate_data_eligibility"]["SOLUSDT"]["historical"]["eligible"]
    original = load_dataset(tmp_path / "out/data_manifest.json")
    assert max(b.start + 300 for b in original["BTCUSDT"]["5m"]) == END
    for tf in ("5m", "1h"):
        path = data / f"market/_compacted/closed_klines_spot_{tf}.parquet"
        rows = pq.read_table(path).to_pylist()
        for row in rows:
            if datetime.fromisoformat(row["source_time"]).timestamp() >= END:
                row.update(open=1000., high=1002., low=998., close=1001.)
        _write(data, tf, rows)
    freeze_dataset(data, tmp_path / "again", ["BTCUSDT", "ETHUSDT", "SOLUSDT"], as_of=END + DAY)
    assert original == load_dataset(tmp_path / "again/data_manifest.json")


def test_hash_tampering(tmp_path):
    data = tmp_path / "data"
    _small(data)
    freeze_dataset(data, tmp_path / "out", ["BTCUSDT"], as_of=END)
    path = tmp_path / "out/data_manifest.json"
    original = path.read_bytes()
    manifest = json.loads(original)
    manifest["window"]["end"] += 300
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="manifest hash"):
        load_dataset(path)
    path.write_bytes(original)
    with (tmp_path / "out/BTCUSDT_5m.parquet").open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="file path/hash"):
        load_dataset(path)


@pytest.mark.parametrize("days", [180, 365])
def test_full_history_window_and_warmup(tmp_path, days):
    data = tmp_path / "data"
    directory = data / "market/_compacted"
    directory.mkdir(parents=True)
    with duckdb.connect(":memory:") as conn:
        for tf, step in (("5m", 300), ("1h", 3600)):
            table = conn.execute("""SELECT 'binance:spot:BTCUSDT' AS instrument_id,
                'binance' AS venue, 'spot' AS market_type, ? AS interval,
                CAST(to_timestamp(t) AS VARCHAR) AS source_time, 100.0 AS open,
                102.0 AS high, 98.0 AS low, 101.0 AS close, 1.0 AS volume,
                '2026-09-02' AS received_at, 'historical' AS provider_status
                FROM range(?, ?, ?) r(t)""", [tf, END - days * DAY - WARMUP, END, step]).to_arrow_table()
            pq.write_table(table, directory / f"closed_klines_spot_{tf}.parquet")
    manifest = freeze_dataset(data, tmp_path / "out", ["BTCUSDT"], as_of=END)
    assert manifest["window"]["days"] == days
    assert manifest["window"]["warmup_start"] == END - days * DAY - WARMUP
    assert manifest["candidate_data_eligibility"]["BTCUSDT"]["historical"]["eligible"]
    assert manifest["candidate_data_eligibility"]["BTCUSDT"]["historical"]["continuous"]
    assert manifest["candidate_data_eligibility"]["BTCUSDT"]["historical"]["formal_acceptance_eligible"]
    assert manifest["candidate_data_eligibility"]["BTCUSDT"]["freshness"]["eligible"]


def test_missing_inputs_do_not_create_source_directories(tmp_path):
    data = tmp_path / "missing"
    manifest = freeze_dataset(data, tmp_path / "out", as_of=END)
    assert not data.exists()
    assert all(not e["historical"]["eligible"] for e in manifest["candidate_data_eligibility"].values())


def test_reject_output_in_source(tmp_path):
    with pytest.raises(ValueError, match="read-only"):
        freeze_dataset(tmp_path, tmp_path / "out", as_of=END)


def test_malformed_timestamp_is_not_silently_dropped(tmp_path):
    data = tmp_path / "data"
    _small(data)
    _write(data, "5m", [dict(_row(END - 300, "5m"), source_time="not-a-time")])
    with pytest.raises(ValueError, match="invalid source timestamp"):
        freeze_dataset(data, tmp_path / "out", ["BTCUSDT"], as_of=END)
    assert not (tmp_path / "out").exists()


def test_alignment_tolerance_and_freshness_grace(tmp_path):
    data = tmp_path / "data"
    _small(data)
    path = data / "market/_compacted/closed_klines_spot_5m.parquet"
    rows = pq.read_table(path).to_pylist()
    rows[0]["source_time"] = datetime.fromtimestamp(END - DAY + 1, UTC).isoformat()
    _write(data, "5m", rows)
    hours = [_row(t, "1h") for t in range(END - DAY, END, 3600)]
    hours[1]["high"] += 1e-9
    _write(data, "1h", hours)
    grace = freeze_dataset(data, tmp_path / "grace", ["BTCUSDT"], as_of=END + 330)
    late = freeze_dataset(data, tmp_path / "late", ["BTCUSDT"], as_of=END + 331)
    assert grace["window"]["end"] == END
    assert grace["candidate_data_eligibility"]["BTCUSDT"]["freshness"]["eligible"]
    assert not late["candidate_data_eligibility"]["BTCUSDT"]["freshness"]["eligible"]
    assert len(load_dataset(tmp_path / "grace/data_manifest.json")["BTCUSDT"]["1h"]) == 23


@pytest.mark.parametrize("segment_hours, eligible", [(249, False), (250, True), (260, True)])
@pytest.mark.parametrize("missing_tf", ["1h", "5m"])
def test_research_eligibility_requires_contiguous_warmup_preserves_whole_window(tmp_path, segment_hours, eligible, missing_tf):
    data = tmp_path / "data"
    total_hours = 2 * segment_hours + 1
    _small(data, hours=total_hours)
    missing_start = END - (segment_hours + 1) * 3600
    path = data / f"market/_compacted/closed_klines_spot_{missing_tf}.parquet"
    hours = [row for row in pq.read_table(path).to_pylist()
             if datetime.fromisoformat(row["source_time"]).timestamp() != missing_start]
    _write(data, missing_tf, hours)
    manifest = freeze_dataset(data, tmp_path / "out", ["BTCUSDT"], as_of=END)
    historical = manifest["candidate_data_eligibility"]["BTCUSDT"]["historical"]
    assert historical["eligible"] is eligible
    assert historical["status"] == ("PARTIAL" if eligible else "BLOCKED")
    assert historical["continuous"] is False
    assert historical["formal_acceptance_eligible"] is False
    assert len(historical["usable_segments"]) == (2 if eligible else 0)
    for segment in historical["usable_segments"]:
        assert segment["bars_1h"] == segment_hours
        assert segment["bars_5m"] == segment_hours * 12
        assert segment["warmup_complete_at"] == segment["start"] + WARMUP
    assert manifest["window"]["start"] == END - 180 * DAY
    assert manifest["window"]["end"] == END
    loaded = load_dataset(tmp_path / "out/data_manifest.json")["BTCUSDT"]
    assert len(loaded["5m"]) == total_hours * 12 - (missing_tf == "5m")
    assert len(loaded["1h"]) == total_hours - 1
    assert loaded["5m"][0].start == END - total_hours * 3600
    assert loaded["5m"][-1].start == END - 300
    # The hourly hole remains visible to the adapter while 5m keeps advancing.
    assert missing_start not in {bar.start for bar in loaded["1h"]}
    assert missing_start + 3300 in {bar.start for bar in loaded["5m"]}
    assert missing_start + 3600 in {bar.start for bar in loaded["5m"]}
