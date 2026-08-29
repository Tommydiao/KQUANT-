from __future__ import annotations

from kquant_crypto.meme_factors import MemeObservation, compute_meme_factors


def _history(security: str = "passed") -> tuple[MemeObservation, ...]:
    return (
        MemeObservation("solana:token", "2026-08-22T00:00:00+00:00", 0.10, 100_000, 10_000, 40, 35, 1000, security_status=security),
        MemeObservation("solana:token", "2026-08-22T00:05:00+00:00", 0.12, 130_000, 25_000, 120, 20, 1300, security_status=security),
    )


def test_meme_factors_expose_transparent_early_state():
    result = compute_meme_factors(_history())
    assert result.factor_version == "crypto_meme_factor_v1.0.0"
    assert result.values["meme_volume_acceleration"] == 1.5
    assert result.values["meme_buy_pressure"] > 0
    assert result.setup_score > 60
    assert result.stage in {"ARMED", "PAPER_BUY_REVIEW"}
    assert result.content_hash


def test_meme_security_unknown_is_not_an_action_state():
    result = compute_meme_factors(_history("unknown"))
    assert result.stage == "SAFETY_PENDING"
    assert {item["code"] for item in result.blockers} == {"security_pending"}


def test_future_observation_does_not_change_past_snapshot():
    history = _history()
    past = compute_meme_factors(history, as_of="2026-08-22T00:05:00+00:00")
    future = history + (MemeObservation("solana:token", "2026-08-22T00:10:00+00:00", 0.20, 180_000, 50_000, 180, 20, 1800, security_status="passed"),)
    repeated = compute_meme_factors(future, as_of="2026-08-22T00:05:00+00:00")
    assert repeated.as_dict() == past.as_dict()


def test_liquidity_withdrawal_is_a_risk_state():
    history = _history() + (MemeObservation("solana:token", "2026-08-22T00:10:00+00:00", 0.11, 40_000, 5_000, 10, 80, 900, security_status="passed"),)
    result = compute_meme_factors(history)
    assert result.stage == "LIQUIDITY_RISK"
    assert any(item["code"] == "liquidity_withdrawal" for item in result.blockers)
