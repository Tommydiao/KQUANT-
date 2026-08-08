from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


DEFAULT_LOCAL_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8001",
    "http://127.0.0.1:8001",
)
SESSION_COOKIE_NAME = "kquant_session"
_PASSWORD_HASH_SCHEME = "scrypt"


def _enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_email(value: str) -> bool:
    """Small local-login validation without adding a mail-validation dependency."""

    candidate = value.strip()
    if len(candidate) > 320 or candidate.count("@") != 1 or any(char.isspace() for char in candidate):
        return False
    local, domain = candidate.rsplit("@", 1)
    return bool(local and domain and "." in domain and not domain.startswith(".") and not domain.endswith("."))


def allowed_origins() -> list[str]:
    configured = os.getenv("KQUANT_CORS_ORIGINS", "").strip()
    if not configured:
        return list(DEFAULT_LOCAL_ORIGINS)
    return [item.strip() for item in configured.split(",") if item.strip()]


def _bounded_integer(name: str, default: int, *, lower: int, upper: int) -> int:
    """Read an operational setting without allowing a malformed env value to break startup."""

    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(lower, min(upper, value))


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(f"{value}{'=' * (-len(value) % 4)}")


def generate_password_hash(password: str) -> str:
    """Create a self-describing scrypt hash suitable for the local .env file."""

    if len(password) < 12:
        raise ValueError("Choose a password with at least 12 characters.")
    salt = secrets.token_bytes(16)
    n, r, p = 16_384, 8, 1
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
    return "$".join((_PASSWORD_HASH_SCHEME, str(n), str(r), str(p), _b64encode(salt), _b64encode(digest)))


def verify_password(password: str, encoded: str) -> bool:
    """Verify an scrypt password hash without exposing malformed configuration."""

    try:
        scheme, raw_n, raw_r, raw_p, raw_salt, raw_digest = encoded.split("$", 5)
        if scheme != _PASSWORD_HASH_SCHEME:
            return False
        expected = _b64decode(raw_digest)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_b64decode(raw_salt),
            n=int(raw_n),
            r=int(raw_r),
            p=int(raw_p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (TypeError, ValueError, UnicodeError):
        return False


@dataclass(frozen=True)
class SecuritySettings:
    require_api_auth: bool
    api_token_configured: bool
    rate_limit_per_minute: int
    external_access_enabled: bool
    cors_origins: tuple[str, ...]
    local_login_enabled: bool
    login_email_configured: bool
    login_password_hash_configured: bool
    session_secret_configured: bool
    session_idle_seconds: int
    session_max_seconds: int
    login_attempt_limit: int
    login_attempt_window_seconds: int

    @classmethod
    def from_environment(cls) -> "SecuritySettings":
        login_email = os.getenv("KQUANT_LOGIN_EMAIL", "").strip()
        password_hash = os.getenv("KQUANT_LOGIN_PASSWORD_HASH", "").strip()
        session_secret = os.getenv("KQUANT_SESSION_SECRET", "").strip()
        return cls(
            require_api_auth=_enabled("KQUANT_REQUIRE_API_AUTH"),
            api_token_configured=bool(os.getenv("KQUANT_API_AUTH_TOKEN", "").strip()),
            rate_limit_per_minute=_bounded_integer(
                "KQUANT_API_RATE_LIMIT_PER_MINUTE", 240, lower=10, upper=10_000
            ),
            external_access_enabled=_enabled("KQUANT_EXTERNAL_ACCESS"),
            cors_origins=tuple(allowed_origins()),
            local_login_enabled=_enabled("KQUANT_LOGIN_ENABLED", default=bool(login_email or password_hash)),
            login_email_configured=_is_email(login_email),
            login_password_hash_configured=bool(password_hash),
            session_secret_configured=len(session_secret) >= 32,
            session_idle_seconds=_bounded_integer("KQUANT_LOGIN_IDLE_MINUTES", 30, lower=5, upper=720) * 60,
            session_max_seconds=_bounded_integer("KQUANT_LOGIN_MAX_HOURS", 8, lower=1, upper=168) * 3600,
            login_attempt_limit=_bounded_integer("KQUANT_LOGIN_ATTEMPT_LIMIT", 5, lower=3, upper=20),
            login_attempt_window_seconds=_bounded_integer("KQUANT_LOGIN_ATTEMPT_WINDOW_MINUTES", 15, lower=1, upper=120) * 60,
        )

    @property
    def local_login_ready(self) -> bool:
        return (
            self.local_login_enabled
            and self.login_email_configured
            and self.login_password_hash_configured
            and self.session_secret_configured
        )

    def report(self) -> dict[str, object]:
        return {
            "api_auth_required": self.require_api_auth,
            "api_token_configured": self.api_token_configured,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "external_access_enabled": self.external_access_enabled,
            "cors_origin_count": len(self.cors_origins),
            "local_login_enabled": self.local_login_enabled,
            "local_login_ready": self.local_login_ready,
            "login_email_configured": self.login_email_configured,
            "session_idle_minutes": self.session_idle_seconds // 60,
            "session_max_hours": self.session_max_seconds // 3600,
            "secrets_exposed": False,
        }


class LocalSessionAuth:
    """Signed, local-only browser sessions. Passwords and session secrets stay in env."""

    def __init__(self, settings: SecuritySettings) -> None:
        self.settings = settings
        self._failed_logins: dict[str, Deque[float]] = defaultdict(deque)

    def session_from_request(self, request: Request) -> dict[str, int] | None:
        if not self.settings.local_login_ready:
            return None
        raw = request.cookies.get(SESSION_COOKIE_NAME, "")
        if not raw:
            return None
        try:
            encoded_payload, supplied_signature = raw.split(".", 1)
            secret = os.getenv("KQUANT_SESSION_SECRET", "").encode("utf-8")
            expected_signature = _b64encode(hmac.new(secret, encoded_payload.encode("ascii"), hashlib.sha256).digest())
            if not hmac.compare_digest(supplied_signature, expected_signature):
                return None
            payload = json.loads(_b64decode(encoded_payload).decode("utf-8"))
            now = int(time.time())
            issued_at = int(payload["iat"])
            last_seen = int(payload["last"])
            expires_at = int(payload["exp"])
            if issued_at > now + 60 or expires_at <= now or last_seen + self.settings.session_idle_seconds <= now:
                return None
            return {"iat": issued_at, "exp": expires_at}
        except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
            return None

    def issue_session(self, *, issued_at: int | None = None, expires_at: int | None = None) -> str:
        now = int(time.time())
        issued = issued_at or now
        expires = expires_at or (issued + self.settings.session_max_seconds)
        payload = _b64encode(json.dumps({"iat": issued, "last": now, "exp": expires}, separators=(",", ":")).encode("utf-8"))
        secret = os.getenv("KQUANT_SESSION_SECRET", "").encode("utf-8")
        signature = _b64encode(hmac.new(secret, payload.encode("ascii"), hashlib.sha256).digest())
        return f"{payload}.{signature}"

    def login_allowed(self, client: str) -> bool:
        now = time.monotonic()
        attempts = self._failed_logins[client]
        while attempts and attempts[0] <= now - self.settings.login_attempt_window_seconds:
            attempts.popleft()
        return len(attempts) < self.settings.login_attempt_limit

    def record_login_failure(self, client: str) -> None:
        self._failed_logins[client].append(time.monotonic())

    def clear_login_failures(self, client: str) -> None:
        self._failed_logins.pop(client, None)

    def verify_login(self, email: str, password: str) -> bool:
        configured_email = os.getenv("KQUANT_LOGIN_EMAIL", "").strip().lower()
        email_matches = hmac.compare_digest(email.strip().lower(), configured_email)
        return (
            self.settings.local_login_ready
            and email_matches
            and verify_password(password, os.getenv("KQUANT_LOGIN_PASSWORD_HASH", ""))
        )

    def set_session_cookie(self, response: Response, token: str) -> None:
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=token,
            max_age=self.settings.session_max_seconds,
            httponly=True,
            secure=self.settings.external_access_enabled,
            samesite="strict",
            path="/",
        )

    def clear_session_cookie(self, response: Response) -> None:
        response.delete_cookie(key=SESSION_COOKIE_NAME, path="/", httponly=True, secure=self.settings.external_access_enabled, samesite="strict")


class ApiSecurityMiddleware(BaseHTTPMiddleware):
    """Local-first request guard with optional token auth and bounded API rate."""

    def __init__(self, app, *, settings: SecuritySettings, session_auth: LocalSessionAuth) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.settings = settings
        self.session_auth = session_auth
        self._requests: dict[str, Deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        path = request.url.path
        is_api = path.startswith("/api/")
        is_auth_endpoint = path.startswith("/api/auth/")
        session = self.session_auth.session_from_request(request)
        if is_api:
            if self.settings.local_login_enabled and not self.settings.local_login_ready and not is_auth_endpoint:
                return self._response(503, {"detail": "Local login is enabled but not configured."})
            expected = os.getenv("KQUANT_API_AUTH_TOKEN", "")
            supplied = request.headers.get("X-KQUANT-API-TOKEN", "")
            token_authenticated = bool(expected and hmac.compare_digest(supplied, expected))
            if self.settings.require_api_auth and not expected:
                return self._response(503, {"detail": "API authentication is enabled but not configured."})
            if not is_auth_endpoint and self.settings.local_login_ready and not session and not token_authenticated:
                return self._response(401, {"detail": "Local login is required."})
            if self.settings.require_api_auth and not token_authenticated and not session:
                return self._response(401, {"detail": "API authentication is required."})
            client = request.client.host if request.client else "unknown"
            now = time.monotonic()
            attempts = self._requests[client]
            while attempts and attempts[0] <= now - 60:
                attempts.popleft()
            if len(attempts) >= self.settings.rate_limit_per_minute:
                return self._response(429, {"detail": "API rate limit reached. Retry later."})
            attempts.append(now)
        response = await call_next(request)
        if is_api and not is_auth_endpoint and session and self.settings.local_login_ready:
            self.session_auth.set_session_cookie(response, self.session_auth.issue_session(issued_at=session["iat"], expires_at=session["exp"]))
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store" if path.startswith("/api/") else "public, max-age=300"
        return response

    @staticmethod
    def _response(status_code: int, payload: dict[str, object]) -> JSONResponse:
        response = JSONResponse(payload, status_code=status_code)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        return response
