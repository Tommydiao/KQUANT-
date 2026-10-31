from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .db.migrations import connect, migrate


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    if not password:
        raise ValueError("Password cannot be empty.")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = encoded.split("$", 5)
        if scheme != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(_unb64(digest)),
        )
        return hmac.compare_digest(actual, _unb64(digest))
    except (ValueError, TypeError):
        return False


def generate_session_secret() -> str:
    return _b64(secrets.token_bytes(32))


class SessionAuth:
    cookie_name = "kquant_crypto_session"

    def __init__(self, db_path: Path, email: str, password_hash: str, secret: str, idle_minutes: int = 30, max_hours: int = 8):
        self.db_path = db_path
        self.email = email.strip().lower()
        self.password_hash = password_hash
        self.secret = secret
        self.idle_minutes = idle_minutes
        self.max_hours = max_hours

    @property
    def configured(self) -> bool:
        return bool(self.email and self.password_hash and self.secret)

    def _token_hash(self, token: str) -> str:
        return hmac.new(self.secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()

    def _record_attempt(self, client_key: str, success: bool) -> None:
        migrate(self.db_path)
        with connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO auth_login_attempts(client_key,success,attempted_at) VALUES(?,?,?)",
                (client_key[:160], int(success), datetime.now(UTC).isoformat()),
            )

    def _too_many_attempts(self, client_key: str) -> bool:
        migrate(self.db_path)
        cutoff = (datetime.now(UTC) - timedelta(minutes=15)).isoformat()
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM auth_login_attempts WHERE client_key=? AND success=0 AND attempted_at>=?",
                (client_key[:160], cutoff),
            ).fetchone()
            return int(row["count"]) >= 8

    def login(self, email: str, password: str, client_key: str) -> str | None:
        normalized = email.strip().lower()
        if self._too_many_attempts(client_key):
            self._record_attempt(client_key, False)
            return None
        valid = bool(self.configured and hmac.compare_digest(normalized, self.email) and verify_password(password, self.password_hash))
        self._record_attempt(client_key, valid)
        if not valid:
            return None
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO auth_sessions(token_hash,email,created_at,last_seen_at,idle_expires_at,max_expires_at)
                VALUES(?,?,?,?,?,?)
                """,
                (
                    self._token_hash(token),
                    self.email,
                    now.isoformat(),
                    now.isoformat(),
                    (now + timedelta(minutes=self.idle_minutes)).isoformat(),
                    (now + timedelta(hours=self.max_hours)).isoformat(),
                ),
            )
        return token

    def authenticate(self, token: str | None) -> str | None:
        if not token or not self.configured:
            return None
        now = datetime.now(UTC)
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM auth_sessions WHERE token_hash=? AND revoked_at IS NULL",
                (self._token_hash(token),),
            ).fetchone()
            if row is None:
                return None
            idle = datetime.fromisoformat(row["idle_expires_at"])
            maximum = datetime.fromisoformat(row["max_expires_at"])
            if now >= idle or now >= maximum:
                conn.execute("UPDATE auth_sessions SET revoked_at=? WHERE token_hash=?", (now.isoformat(), row["token_hash"]))
                return None
            conn.execute(
                "UPDATE auth_sessions SET last_seen_at=?, idle_expires_at=? WHERE token_hash=?",
                (now.isoformat(), (now + timedelta(minutes=self.idle_minutes)).isoformat(), row["token_hash"]),
            )
            return row["email"]

    def logout(self, token: str | None) -> None:
        if not token or not self.secret:
            return
        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE auth_sessions SET revoked_at=? WHERE token_hash=?",
                (datetime.now(UTC).isoformat(), self._token_hash(token)),
            )
