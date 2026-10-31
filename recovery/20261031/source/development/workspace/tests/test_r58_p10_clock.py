"""TEST_ONLY clock packet fixtures. No system-time mutation or real approval."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import struct
from types import SimpleNamespace

import pytest

from kquant import options_clock_measurement as clock
from kquant import options_one_minute as common
from kquant.options_opening_trend_sdk import candle_evidence
from kquant.options_minute_decisions import _local_candidate, LOCAL_METHOD

NOW = datetime(2026, 10, 6, 13, 35, 5, tzinfo=UTC)


def sample(server, *, shift=.01):
    t1 = NOW.timestamp() - .2
    # Quantize through native NTP encoding, matching actual query decoding.
    t2 = clock.decode(clock.stamp(t1 + .08 + shift))
    t3 = clock.decode(clock.stamp(t1 + .081 + shift))
    t4 = NOW.timestamp()
    packet = bytearray(48)
    packet[0], packet[1], packet[3] = 0x24, 2, 246
    packet[24:32], packet[32:40], packet[40:48] = clock.stamp(t1), clock.stamp(t2), clock.stamp(t3)
    radius = ((t4 - t1) - (t3 - t2)) / 2 + 2 ** -10 + .002
    row = dict(server=server, t1=t1, t2=t2, t3=t3, t4=t4, monotonic_elapsed_seconds=t4 - t1,
               offset_seconds=((t2-t1) + (t3-t4))/2, uncertainty_radius_seconds=radius,
               packet_hex=packet.hex(), checked_at=NOW.isoformat(), udp_authenticated=False)
    row["observation_hash"] = common.digest(row)
    return row


def acceptance(root):
    row = dict(status="ACCEPTED", accepted_by="OWNER", method=clock.METHOD,
               method_hash=common.digest(clock.METHOD), accepted_at=NOW.isoformat(),
               valid_until=(NOW + timedelta(hours=1)).isoformat(), test_only=True)
    raw = json.dumps(row).encode()
    (root / "TEST_ONLY_clock_acceptance.json").write_bytes(raw)
    return {"acceptance_path": "TEST_ONLY_clock_acceptance.json", "acceptance_sha256": sha256(raw).hexdigest()}


def test_real_format_clock_without_exact_source_method_stays_unverified(tmp_path):
    samples = [sample(host) for host in clock.METHOD["servers"]]
    value = clock.evaluate(samples, now=NOW, root=tmp_path)
    assert value["state"] == "MEASURED_UNVERIFIED"
    assert value["uncertainty_ms"] is None and not value["precision_verified"]


def test_accepted_isolated_bound_attaches_to_actual_sdk_capture_and_original_boundary(tmp_path,monkeypatch):
    # This historic packet test needs its explicit as-of clock; a real current
    # read must now correctly reject the week-old attachment.
    class TestAsOfClock(datetime):
        @classmethod
        def now(cls,tz=None):
            return NOW.astimezone(tz)
    monkeypatch.setattr(clock,'datetime',TestAsOfClock)
    monkeypatch.setattr(clock,'_attachment',deepcopy(clock._attachment))
    monkeypatch.setattr(clock,'_published_time',None)
    samples = [sample(host) for host in clock.METHOD["servers"]]
    value = clock.evaluate(samples, proof=acceptance(tmp_path), root=tmp_path, now=NOW)
    assert value["state"] == "VERIFIED_BOUND" and 0 < value["uncertainty_ms"] < 1000
    clock.publish(value)
    native = candle_evidence(SimpleNamespace(open=100, high=101, low=99, close=101),
        provider_symbol="TEST.US", interface="QuoteContext.candlesticks",
        received_at=(NOW + timedelta(seconds=1)).isoformat(), requested_at=NOW.isoformat())
    assert native["clock_evidence"] == value
    row = dict(available_at=(NOW - timedelta(seconds=1)).isoformat(), received_at=(NOW + timedelta(seconds=1)).isoformat(), sdk_evidence=native)
    assert _local_candidate(row, {"method": LOCAL_METHOD})
    row["available_at"] = NOW.isoformat()
    assert not _local_candidate(row, {"method": LOCAL_METHOD})


@pytest.mark.parametrize("defect", ["single_source", "source_changed", "packet_changed", "fake_radius", "wrong_nonce", "disagreement", "expiry", "method_changed", "missing_owner"])
def test_clock_negatives_do_not_supply_bound(tmp_path, defect):
    samples = [sample(host) for host in clock.METHOD["servers"]]
    proof = acceptance(tmp_path)
    now = NOW
    if defect == "single_source": samples.pop()
    if defect == "source_changed": samples[0]["observation_hash"] = "changed"
    if defect == "packet_changed": samples[0]["packet_hex"] = "00"
    if defect == "fake_radius": samples[0]["uncertainty_radius_seconds"] = 0
    if defect == "wrong_nonce":
        raw = bytearray.fromhex(samples[0]["packet_hex"])
        raw[24:32] = b"0" * 8
        samples[0]["packet_hex"] = raw.hex()
    if defect == "disagreement": samples[0] = sample(clock.METHOD["servers"][0], shift=3)
    if defect == "expiry": now += timedelta(seconds=901)
    if defect in {"method_changed", "missing_owner"}:
        path = tmp_path / proof["acceptance_path"]
        row = json.loads(path.read_text())
        if defect == "method_changed": row["method"]["max_uncertainty_ms"] = 5000
        else: row["accepted_by"] = "AUTOMATED"
        raw = json.dumps(row).encode()
        path.write_bytes(raw)
        proof["acceptance_sha256"] = sha256(raw).hexdigest()
    if defect in {"packet_changed", "fake_radius", "wrong_nonce"}:
        samples[0]["observation_hash"] = common.digest({k:v for k,v in samples[0].items() if k != "observation_hash"})
    value = clock.evaluate(samples, proof=proof, root=tmp_path, now=now)
    assert value["state"] != "VERIFIED_BOUND" and not value["precision_verified"]
