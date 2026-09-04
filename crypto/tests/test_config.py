from __future__ import annotations

from kquant_crypto.config import load_settings


def test_local_dotenv_is_loaded_without_overriding_process_environment(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(
        "KQUANT_CRYPTO_PORT=8123\nKQUANT_CRYPTO_LOGIN_EMAIL=owner@example.com\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("KQUANT_CRYPTO_PORT", raising=False)
    monkeypatch.delenv("KQUANT_CRYPTO_LOGIN_EMAIL", raising=False)
    settings = load_settings(tmp_path)
    assert settings.port == 8123
    assert settings.login_email == "owner@example.com"


def test_process_environment_wins_over_local_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("KQUANT_CRYPTO_PORT=8123\n", encoding="utf-8")
    monkeypatch.setenv("KQUANT_CRYPTO_PORT", "8124")
    assert load_settings(tmp_path).port == 8124


def test_candidate_spot_symbols_survive_stale_core_symbol_override(tmp_path, monkeypatch):
    monkeypatch.setenv("KQUANT_CRYPTO_CORE_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT")
    settings = load_settings(tmp_path)
    assert {"ZECUSDT", "ARBUSDT", "PUMPUSDT"}.issubset(settings.core_symbols)
    assert "HYPEUSDT" not in settings.core_symbols


def test_public_binance_endpoints_are_separate_from_execution(tmp_path, monkeypatch):
    monkeypatch.delenv("BINANCE_SPOT_MARKET_DATA_BASE_URL", raising=False)
    settings = load_settings(tmp_path)
    assert settings.binance_public_endpoints.spot_rest == "https://data-api.binance.vision"
    assert settings.execution.spot_live_base_url == "https://api.binance.com"
