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
