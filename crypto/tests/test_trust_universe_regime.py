from __future__ import annotations

from kquant_crypto.data_trust import DataSnapshot, DataTrustStore, assess_trust
from kquant_crypto.market_regime import MarketRegimeInput, classify_regime
from kquant_crypto.market_regime_runtime import MarketRegimeRuntime
from kquant_crypto.universe import CanonicalAsset, UniverseRegistry


def test_data_trust_is_fail_closed_for_forming_or_stale_inputs(settings):
    assert assess_trust(provider_status="live", age_seconds=1, required_fields=["bid"], payload={"bid": 1}) == "live"
    assert assess_trust(provider_status="live", age_seconds=1, required_fields=["bid"], payload={"bid": 1, "forming_candle": True}) == "partial"
    assert assess_trust(provider_status="clock_skew", age_seconds=1, required_fields=[], payload={}) == "provider_unavailable"
    assert assess_trust(provider_status="live", age_seconds=99, required_fields=[], payload={}) == "stale"


def test_snapshot_hash_and_store_are_reproducible(settings):
    snapshot = DataSnapshot.create(snapshot_type="market", source="binance", payload={"last": 1}, trust_status="live", asset_id="asset:btc")
    assert snapshot.eval_eligible()
    store = DataTrustStore(settings.db_path)
    store.save(snapshot)
    stored = store.get(snapshot.snapshot_id)
    assert stored is not None
    assert stored["content_hash"] == snapshot.content_hash


def test_universe_uses_contract_identity_and_point_in_time_membership(settings):
    registry = UniverseRegistry(settings.db_path)
    btc = CanonicalAsset.cex("BTC")
    meme = CanonicalAsset.dex("solana", "ABC123", "MOON")
    snapshot = registry.create_snapshot([(btc, "CORE"), (meme, "MEME")], as_of_time="2026-08-22T00:00:00+00:00")
    assert btc.asset_id != meme.asset_id
    assert registry.member_at("asset:btc", "2026-08-22T01:00:00+00:00")
    assert snapshot["member_count"] == 2


def test_new_universe_snapshot_closes_prior_membership(settings):
    registry = UniverseRegistry(settings.db_path)
    btc = CanonicalAsset.cex("BTC")
    eth = CanonicalAsset.cex("ETH")
    registry.create_snapshot([(btc, "CORE")], as_of_time="2026-08-22T00:00:00+00:00")
    registry.create_snapshot([(eth, "CORE")], as_of_time="2026-08-23T00:00:00+00:00")

    assert registry.member_at("asset:btc", "2026-08-22T12:00:00+00:00")
    assert not registry.member_at("asset:btc", "2026-08-23T00:00:00+00:00")
    assert registry.member_at("asset:eth", "2026-08-23T00:00:00+00:00")


def test_market_regime_prioritizes_stress_and_missing_data():
    caution = classify_regime(MarketRegimeInput(None, None, None, None, None, None, None, None, False))
    assert caution["regime"] == "DATA_CAUTION"
    stress = classify_regime(MarketRegimeInput(-0.1, -0.1, -0.2, 0.2, 0.01, -0.2, 0.9, 0.0, True))
    assert stress["regime"] == "DELEVERAGING"
    alt = classify_regime(MarketRegimeInput(0.01, 0.02, 0.04, 0.7, 0.0, 0.03, 0.0, 0.0, True))
    assert alt["regime"] == "ALT_EXPANSION"


def test_market_regime_runtime_uses_closed_history_and_returns_audit_payload(settings):
    class FakeBuffer:
        def __init__(self):
            self._history = {}

        def instruments(self):
            return list(self._history)

        def closed_history(self, instrument_id, interval):
            return tuple(self._history.get(instrument_id, ())) if interval == "1H" else ()

        def snapshot(self, instrument_id):
            return {"provider_status": "live", "age_seconds": 1, "last_source_time": "2026-08-23T00:00:00+00:00", "last_received_at": "2026-08-23T00:00:01+00:00"}

    class FakeRuntime:
        def __init__(self):
            self.buffer = FakeBuffer()

        def snapshot(self, instrument_id):
            return self.buffer.snapshot(instrument_id)

    class Bar:
        def __init__(self, close):
            self.close = close

    runtime = FakeRuntime()
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "PEPEUSDT", "WIFUSDT", "BONKUSDT", "SUIUSDT"]
    for index, symbol in enumerate(symbols):
        base = 100.0 + index
        values = [Bar(base)] * 24 + [Bar(base * (1.02 if symbol != "BTCUSDT" else 1.01))]
        runtime.buffer._history[f"binance:spot:{symbol}"] = values
    regime = MarketRegimeRuntime(settings.db_path, runtime, symbols=symbols, universe_snapshot_id="universe_test")
    result = regime.compute(as_of_time="2026-08-23T00:00:00+00:00")
    assert result["regime"] in {"RISK_ON", "ALT_EXPANSION", "BTC_DOMINANT", "DATA_CAUTION"}
    assert result["data_snapshot"].snapshot_type == "crypto_market_regime_inputs"
    assert result["input"]["core_returns"]["BTCUSDT"] is not None
    assert result["input"]["alt_sample_count"] == 5
    persisted = regime._persist(result)
    restored = MarketRegimeRuntime(settings.db_path, runtime, symbols=symbols, universe_snapshot_id="universe_test")
    assert restored.latest() is not None
    assert restored.latest()["regime_snapshot_id"] == persisted["regime_snapshot_id"]
