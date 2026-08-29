from __future__ import annotations

from kquant_crypto.security import SessionAuth, generate_session_secret, hash_password, verify_password


def test_scrypt_password_hash_round_trip():
    encoded = hash_password("secret")
    assert verify_password("secret", encoded)
    assert not verify_password("wrong", encoded)


def test_session_login_logout_and_rate_limit(settings):
    auth = SessionAuth(settings.db_path, settings.login_email, settings.login_password_hash, settings.session_secret)
    assert auth.login(settings.login_email, "wrong", "client") is None
    token = auth.login(settings.login_email, "correct horse battery staple", "client")
    assert token
    assert auth.authenticate(token) == settings.login_email
    auth.logout(token)
    assert auth.authenticate(token) is None


def test_unconfigured_session_never_authenticates(settings):
    auth = SessionAuth(settings.db_path, "", "", generate_session_secret())
    assert auth.login("owner@example.com", "secret", "client") is None
