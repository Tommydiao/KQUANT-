from datetime import UTC, datetime, timedelta

from kquant_crypto.evidence_pipeline import build_research_model_evidence
from kquant_crypto.market_buffer import Candle
from kquant_crypto.model_evidence import get_model_evidence_packet, verify_model_evidence_packet


def _bars(count: int = 24 * 80) -> tuple[Candle, ...]:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    values = []
    price = 100.0
    for index in range(count):
        price *= 1.0 + (0.002 if index % 11 < 7 else -0.0015)
        values.append(Candle(
            instrument_id="binance:spot:BTCUSDT",
            interval="1H",
            start_time=(start + timedelta(hours=index)).isoformat(),
            open=price * 0.999,
            high=price * 1.004,
            low=price * 0.996,
            close=price,
            volume=1000.0 + index,
            closed=True,
            component_count=60,
            source="test",
        ))
    return tuple(values)


def test_research_evidence_is_persisted_but_cannot_fake_model_gate(settings):
    bars = _bars()
    signal_time = (datetime(2025, 3, 22, tzinfo=UTC)).isoformat()
    kwargs = dict(
        db_path=settings.db_path,
        asset_id="asset:btc",
        symbol="BTCUSDT",
        market_type="spot",
        strategy_version="crypto_spot_momentum_v2.1.0",
        signal_time=signal_time,
        available_at=signal_time,
        hourly_bars=bars,
        factor_values={
            "trend_ema_reclaim": 1.0,
            "trend_ema_slope": 0.01,
            "relative_strength_btc": 0.0,
            "relative_strength_eth": 0.03,
            "momentum_acceleration": 0.02,
            "volume_acceleration": 0.4,
            "volatility_compression": 0.8,
            "spread_bps": 3.0,
        },
        entry_zone=(99.5, 100.5),
        stop_zone=(94.0, 95.0),
        target_zone=(110.0, 112.0),
        source_snapshot_ids=("market:test", "factor:test", "regime:test"),
        source_status="live",
    )
    first = build_research_model_evidence(**kwargs)
    second = build_research_model_evidence(**kwargs)

    assert first.packet_id == second.packet_id
    assert first.bayesian_posterior["evidence_status"] == "complete"
    assert first.monte_carlo_result["status"] == "available"
    assert first.monte_carlo_result["config"]["paths"] == 5000
    assert first.promotion_status == "RESEARCH_ONLY"
    assert "logistic_evidence_unavailable" in first.blockers
    assert "calibration_gate_closed" in first.blockers
    stored = get_model_evidence_packet(settings.db_path, first.packet_id)
    assert stored is not None
    assert verify_model_evidence_packet(stored) == (True, ())


def test_research_evidence_rejects_invalid_plan_geometry(settings):
    bars = _bars()
    signal_time = datetime(2025, 3, 22, tzinfo=UTC).isoformat()
    try:
        build_research_model_evidence(
            db_path=settings.db_path,
            asset_id="asset:btc",
            symbol="BTCUSDT",
            market_type="spot",
            strategy_version="crypto_spot_momentum_v2.1.0",
            signal_time=signal_time,
            available_at=signal_time,
            hourly_bars=bars,
            factor_values={},
            entry_zone=(100.0,),
            stop_zone=(101.0,),
            target_zone=(110.0,),
            source_snapshot_ids=("market:test",),
            source_status="live",
        )
    except ValueError as exc:
        assert str(exc) == "invalid_trade_plan_geometry"
    else:
        raise AssertionError("invalid geometry must fail closed")
