from __future__ import annotations

"""Unified read-only Stocks/Crypto workspace gateway.

The gateway is the only browser-facing entry point for the combined UI.  It
owns one local session and proxies an explicit allow-list of research routes
to the two independent runtimes.  The stock and crypto databases, strategy
versions, and provider contracts remain separate by design.
"""

import asyncio
import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import ssl
import time
from http.cookiejar import CookieJar, DefaultCookiePolicy
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any, Deque, Iterable

import httpx
import certifi
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from starlette.requests import ClientDisconnect
from pydantic import BaseModel, Field


GATEWAY_VERSION = "kquant_gateway_v2.1.0"


class NoUpstreamCookies(DefaultCookiePolicy):
    """A shared transport must never share one browser's backend session."""

    def set_ok(self, cookie, request):
        return False

    def return_ok(self, cookie, request):
        return False


def alert_stream_event_name(payload: str) -> str:
    try:
        event = json.loads(payload)
        if isinstance(event, dict) and event.get("type") == "options_two_hour_progress":
            return "operations"
    except (TypeError, ValueError):
        pass
    return "alert"


API_CONTRACT_VERSION = "kquant-workspace-api-2026-09-14"
FRONTEND_CONTRACT_VERSION = "kquant-workspace-web-graphite-signal-v2"
SESSION_COOKIE_NAME = "kquant_workspace_session"
LOCAL_WORKSPACE_IDENTITY = "local@kquant.local"


class WorkspaceLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=512)


def _enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(f"{value}{'=' * (-len(value) % 4)}")


def _verify_password(password: str, encoded: str) -> bool:
    """Accept the scrypt encodings already used by both runtimes."""

    try:
        parts = encoded.split("$")
        if len(parts) != 6 or parts[0] != "scrypt":
            return False
        _, raw_n, raw_r, raw_p, raw_salt, raw_digest = parts
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
class WorkspaceSecurity:
    enabled: bool
    email: str
    password_hash: str
    session_secret: str
    idle_seconds: int
    max_seconds: int

    @classmethod
    def from_environment(cls) -> "WorkspaceSecurity":
        email = os.getenv("KQUANT_WORKSPACE_LOGIN_EMAIL", "").strip().lower()
        password_hash = os.getenv("KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH", "").strip()
        session_secret = os.getenv("KQUANT_WORKSPACE_SESSION_SECRET", "").strip()
        enabled = _enabled("KQUANT_WORKSPACE_LOGIN_ENABLED", default=bool(email or password_hash or session_secret))
        return cls(
            enabled=enabled,
            email=email,
            password_hash=password_hash,
            session_secret=session_secret,
            idle_seconds=max(300, int(os.getenv("KQUANT_WORKSPACE_LOGIN_IDLE_MINUTES", "30")) * 60),
            max_seconds=max(3600, int(os.getenv("KQUANT_WORKSPACE_LOGIN_MAX_HOURS", "8")) * 3600),
        )

    @property
    def configured(self) -> bool:
        return bool(self.email and self.password_hash and len(self.session_secret) >= 32)

    def report(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "configured": self.configured,
            "email_configured": bool(self.email),
            "password_configured": bool(self.password_hash),
            "session_secret_configured": len(self.session_secret) >= 32,
            "session_idle_minutes": self.idle_seconds // 60,
            "session_max_hours": self.max_seconds // 3600,
            "secrets_exposed": False,
        }


class WorkspaceSessionAuth:
    def __init__(self, security: WorkspaceSecurity) -> None:
        self.security = security
        self._failed: dict[str, Deque[float]] = defaultdict(deque)

    def _sign(self, encoded: str) -> str:
        return _b64encode(hmac.new(self.security.session_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest())

    def issue(self, *, email: str | None = None, issued_at: int | None = None, expires_at: int | None = None) -> str:
        now = int(time.time())
        issued = issued_at or now
        expires = expires_at or issued + self.security.max_seconds
        payload = {"email": email or self.security.email, "iat": issued, "last": now, "exp": expires}
        encoded = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        return f"{encoded}.{self._sign(encoded)}"

    def read(self, request: Request) -> dict[str, Any] | None:
        if not self.security.configured:
            return None
        raw = request.cookies.get(SESSION_COOKIE_NAME, "")
        try:
            encoded, supplied = raw.split(".", 1)
            if not hmac.compare_digest(supplied, self._sign(encoded)):
                return None
            payload = json.loads(_b64decode(encoded).decode("utf-8"))
            now = int(time.time())
            if int(payload["iat"]) > now + 60 or int(payload["exp"]) <= now or int(payload["last"]) + self.security.idle_seconds <= now:
                return None
            return payload
        except (AttributeError, KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
            return None

    def set_cookie(self, response: Response, token: str) -> None:
        response.set_cookie(
            SESSION_COOKIE_NAME,
            token,
            max_age=self.security.max_seconds,
            httponly=True,
            secure=_enabled("KQUANT_WORKSPACE_SECURE_COOKIE"),
            samesite="strict",
            path="/",
        )

    def clear_cookie(self, response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE_NAME, path="/")

    def allowed(self, client: str) -> bool:
        now = time.monotonic()
        attempts = self._failed[client]
        while attempts and attempts[0] <= now - 900:
            attempts.popleft()
        return len(attempts) < 8

    def failed(self, client: str) -> None:
        self._failed[client].append(time.monotonic())

    def clear_failures(self, client: str) -> None:
        self._failed.pop(client, None)

    def verify(self, email: str, password: str) -> bool:
        return bool(
            self.security.configured
            and hmac.compare_digest(email.strip().lower(), self.security.email)
            and _verify_password(password, self.security.password_hash)
        )


@dataclass(frozen=True)
class Backend:
    name: str
    base_url: str
    token: str
    header_name: str


FORBIDDEN_ROUTE_PARTS = {
    "account",
    "wallet",
    "order",
    "orders",
    "position",
    "positions",
    "broker",
    "trade",
    "swap",
    "private-key",
    "private_key",
}


STOCK_ALIAS_PREFIXES = {
    "health": "/api/health",
    "alerts": "/api/alerts",
    "notifications": "/api/notifications",
    "runtime": "/api/runtime",
    "instructions": "/api/instructions",
    "quant": "/api/quant",
    "themes": "/api/themes",
    "leadership": "/api/leadership",
    "models": "/api/models",
    "data": "/api/data",
    "shadow": "/api/shadow",
    "options": "/api/options",
}

CRYPTO_ALIAS_PREFIXES = {
    "health": "/api/health",
    "notifications": "/api/notifications",
}

STOCK_DIRECT_PREFIXES = (
    "depth",
    "candles",
    "daily-candidates",
    "search",
    "signals",
    "universe",
    "provider-health",
    "quote",
    "realtime-snapshot",
    "market-data/",
    "market-regime",
    "analyze",
    "factor-snapshot",
    "early-trend",
    "signal-journal",
    "weekly-review",
    "production-readiness",
    "production-launch-report",
    "today-workbench",
    "live-data-health",
    "ai-review",
    "research-chat",
    "watchlist",
)
CRYPTO_DIRECT_PREFIXES = (
    "trade-plans",
    "instructions",
    "runtime/",
    "roll/",
    "roll-journal",
    "research/",
    "validation/",
    "shadow/",
    "evaluations/",
    "alerts",
    "evidence",
    "dex/",
    "providers/",
    "assets/",
    "factors/",
    "security/",
    "universe/",
    "market-regime/",
    "paper-observations",
    "data/",
    "models",
    "operations/",
)
STOCK_SYMBOL_SUFFIXES = (
    "/factor-snapshot",
    "/early-trend",
)

STOCK_WRITE_PREFIXES = {
    "alerts/",
    "notifications/",
    "options/paper-observations",
    "options/radar/runs",
    "options/watchlist",
    "options/manual-outcomes",
    "options/simulations",
    "options/copilot/paper/confirm",
    "options/full-watch/scan",
    "options/full-watch/options/",
    "options/full-watch/observations",
    "options/event-sources/reviews",
    "options/one-minute/manual/entries",
    "options/one-minute/manual/exits",
    "quant/stocks/validation/runs",
    "decision-ledger",
    "forward-pilot",
    "manual-position-plan",
    "manual-trade-journal",
    "paper-simulation",
    "signal-journal/entry",
    "ai-review",
    "ai-decision",
    "research-chat",
    "ai-daily-agent",
    "strategy-validation/runs",
    "watchlist",
}
CRYPTO_WRITE_PREFIXES = {
    "alerts/",
    "trade-plans",
    "roll/",
    "roll-journal/",
    "research/",
    "evidence",
    "shadow/",
    "paper-observations",
    "validation/",
    "notifications/",
}


def _starts_with(value: str, prefixes: Iterable[str]) -> bool:
    return any(value == prefix.rstrip("/") or value.startswith(prefix) for prefix in prefixes)


def _safe_path(path: str) -> bool:
    parts = {part.lower() for part in path.strip("/").split("/") if part}
    return not parts.intersection(FORBIDDEN_ROUTE_PARTS)


def _resolve_backend_path(domain: str, path: str, method: str) -> str | None:
    normalized = path.strip("/")
    if not normalized or not _safe_path(normalized):
        return None
    if domain == "stocks" and normalized.startswith("options/full-watch/observations"):
        return "/api/options/full-watch/observations" if normalized == "options/full-watch/observations" and method.upper() == "POST" else None
    if domain == 'stocks' and normalized.startswith('options/opening-trend/ai-review'):
        return '/api/options/opening-trend/ai-review' if normalized=='options/opening-trend/ai-review' and method.upper()=='POST' else None
    if domain == "crypto" and normalized.startswith("candidate-simulation"):
        allowed = {"candidate-simulation/status", "candidate-simulation/trades", "candidate-simulation/report"}
        return "/api/crypto/" + normalized if method.upper() == "GET" and normalized in allowed else None
    aliases = STOCK_ALIAS_PREFIXES if domain == "stocks" else CRYPTO_ALIAS_PREFIXES
    direct_prefixes = STOCK_DIRECT_PREFIXES if domain == "stocks" else CRYPTO_DIRECT_PREFIXES
    writes = STOCK_WRITE_PREFIXES if domain == "stocks" else CRYPTO_WRITE_PREFIXES
    target: str | None = None
    for prefix, backend_prefix in aliases.items():
        if normalized == prefix or normalized.startswith(prefix + "/"):
            suffix = normalized[len(prefix):].lstrip("/")
            target = backend_prefix + (f"/{suffix}" if suffix else "")
            break
    if target is None and domain == "stocks" and any(normalized.endswith(suffix) for suffix in STOCK_SYMBOL_SUFFIXES):
        target = "/api/stocks/" + normalized
    if target is None and _starts_with(normalized, direct_prefixes):
        target = "/api/stocks/" + normalized if domain == "stocks" else "/api/crypto/" + normalized
    if target is None:
        return None
    if method.upper() != "GET" and not _starts_with(normalized, writes):
        return None
    return target


FALLBACK_PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KQUANT 统一工作台</title></head>
<body style="margin:0;background:#111518;color:#e7edf2;font:16px system-ui;padding:32px"><main><strong>KQ</strong><h1>统一工作台尚未构建</h1><p>股票 Stocks 与 Crypto 共用入口。请先运行统一前端的 production build。</p><code>/api/gateway/health</code></main></body></html>"""


def _url(name: str, default: str) -> str:
    return os.getenv(name, default).strip().rstrip("/")


class LoginFingerprintReader:
    """Rehash on file generation changes; never cache failed filesystem checks."""

    def __init__(self, path):
        self.path = path
        self.lock = RLock()
        self.signature = None
        self.fingerprint = None
        self.has_value = False
        self.hashed_at = 0.0
        self.hash_reads = 0

    def ticket(self, stat):
        change_time = stat.st_ctime_ns
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class BasicInfo(ctypes.Structure):
                _fields_ = [(name, ctypes.c_longlong) for name in
                            ("creation", "access", "write", "change")] + [("attributes", wintypes.DWORD)]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            create = kernel.CreateFileW
            create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                               wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            create.restype = wintypes.HANDLE
            info = kernel.GetFileInformationByHandleEx
            info.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            info.restype = wintypes.BOOL
            close = kernel.CloseHandle
            close.argtypes, close.restype = [wintypes.HANDLE], wintypes.BOOL
            handle = create(str(self.path), 0x80, 7, None, 3, 0, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                value = BasicInfo()
                if not info(handle, 0, ctypes.byref(value), ctypes.sizeof(value)):
                    raise ctypes.WinError(ctypes.get_last_error())
                change_time = value.change
            finally:
                close(handle)
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, change_time)

    def __call__(self):
        with self.lock:
            try:
                signature = self.ticket(self.path.stat())
                if self.has_value and signature == self.signature and time.monotonic() - self.hashed_at < 1:
                    return self.fingerprint
                raw = self.path.read_bytes()
                self.hash_reads += 1
                if self.ticket(self.path.stat()) != signature:
                    raise OSError("LOGIN_FILE_CHANGED_DURING_READ")
                value = hashlib.sha256(raw).hexdigest()
            except FileNotFoundError:
                signature, value = None, None
            self.signature, self.fingerprint, self.has_value = signature, value, True
            self.hashed_at = time.monotonic()
            return value


class LoginFingerprintCheck:
    """One in-flight file check; a stalled read fails closed without blocking HTTP."""

    def __init__(self, reader, original):
        self.reader, self.original = reader, original
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="login-fingerprint")
        self.future = self.pool.submit(self._read)
        self.consumed = None
        self.revoked = False
        self.diagnostics = {"state": "PREPARING", "reason": "INITIAL_CHECK_PENDING", "checks": 0,
                            "timeouts": 0, "checked_at": None, "read_ms": None}

    def _read(self):
        started = time.monotonic()
        try:
            return self.reader(), None, (time.monotonic() - started) * 1000
        except OSError as exc:
            return None, getattr(exc, "winerror", None) or type(exc).__name__, (time.monotonic() - started) * 1000

    async def state(self, *, enabled):
        if self.revoked:
            return "CHANGED"
        # Consume a read which finished after an earlier timeout before scheduling
        # another one. Concurrent waiters always share the same generation.
        if self.future is None or self.future is self.consumed:
            self.future = self.pool.submit(self._read)
        future = self.future
        try:
            if future.done():
                current, error, read_ms = future.result()
            else:
                current, error, read_ms = await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(future)), timeout=.05)
        except TimeoutError:
            # Scheduling can delay delivery of a read that already completed.
            # Use its real result; a genuinely pending read still fails closed.
            if future.done():
                current, error, read_ms = future.result()
            else:
                self.diagnostics.update(state="UNAVAILABLE", reason="FILE_CHECK_PENDING",
                                        timeouts=self.diagnostics["timeouts"] + 1,
                                        reader_running=future.running())
                return "UNAVAILABLE"
        if self.consumed is not future:
            self.diagnostics["checks"] += 1
        self.consumed = future
        self.diagnostics.update(checked_at=datetime.now(UTC).isoformat(), read_ms=read_ms, reader_running=False)
        if error is not None or current == "UNREADABLE":
            self.diagnostics.update(state="UNAVAILABLE", reason="FILE_READ_FAILED", error_code=error)
            return "UNAVAILABLE"
        self.revoked = self.revoked or current != self.original or (current is not None and not enabled)
        state = "CHANGED" if self.revoked else "UNCHANGED"
        self.diagnostics.update(state=state, reason="CONFIGURATION_GENERATION_CHANGED" if self.revoked else None, error_code=None)
        return state

    def close(self):
        # Cancelling a waiter does not mean a blocked file read has ended.
        self.pool.shutdown(wait=False, cancel_futures=True)


def _frontend_dir(default_root: Path) -> Path:
    raw = os.getenv("KQUANT_GATEWAY_WEB_DIST", "").strip()
    if not raw:
        return (default_root / "web" / "dist-unified").resolve()
    configured = Path(raw)
    return (configured if configured.is_absolute() else default_root / configured).resolve()


async def _probe_backend(backend: Backend, *, transport: httpx.AsyncBaseTransport | None = None,
                         tls_context: ssl.SSLContext | bool = True) -> dict[str, Any]:
    headers = {backend.header_name: backend.token} if backend.token else {}
    try:
        async with httpx.AsyncClient(transport=transport, verify=tls_context, timeout=3.0, follow_redirects=False, trust_env=False) as client:
            path = "/api/health/live" if backend.name == "stocks" else "/api/health"
            response = await client.get(backend.base_url + path, headers=headers)
            if response.status_code == 404 and path != "/api/health":
                response = await client.get(backend.base_url + "/api/health", headers=headers)
        content_type = response.headers.get("content-type", "")
        body = response.json() if content_type.startswith("application/json") else {}
        if not isinstance(body, dict):
            body = {}
        return {
            "name": backend.name,
            "status": "available" if response.status_code == 200 and body.get("status") in {"online", "ok", "healthy", "available"} else "unhealthy",
            "http_status": response.status_code,
            "market_data_checked": body.get("market_data_checked", False),
            "app_version": body.get("app_version") or body.get("runtime", {}).get("app_version"),
            "api_contract_version": body.get("api_contract_version"),
            "frontend_contract_version": body.get("frontend_contract_version"),
            "read_only": body.get("read_only", True),
            "strategy": (body.get("version_matrix") or {}).get("strategy") or body.get("strategy"),
            "gateway_auth_probe": (body.get("internal_gateway_auth") or {}).get("health_probe"),
            "secrets_exposed": False,
        }
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        return {"name": backend.name, "status": "unavailable", "error_type": type(exc).__name__,
                "url_configured": True, "market_data_checked": False, "secrets_exposed": False}


def _filtered_headers(response: httpx.Response) -> dict[str, str]:
    headers: dict[str, str] = {}
    content_type = response.headers.get("content-type")
    if content_type:
        headers["content-type"] = content_type
    if response.headers.get("cache-control"):
        headers["cache-control"] = response.headers["cache-control"]
    if response.headers.get("retry-after"):
        headers["retry-after"] = response.headers["retry-after"]
    request_id = response.headers.get("x-request-id", "")
    if request_id and len(request_id) <= 128 and all(
        char.isascii() and (char.isalnum() or char in "-_.:") for char in request_id
    ):
        headers["x-request-id"] = request_id
    # Preserve explicit test provenance without classifying ordinary upstream failures.
    if (response.status_code == 503 and
            response.headers.get("x-kquant-test-isolation") == "legacy-not-mounted"):
        headers["x-kquant-test-isolation"] = "legacy-not-mounted"
    return headers


def create_gateway_app(
    *,
    stocks_url: str | None = None,
    crypto_url: str | None = None,
    web_dist_dir: str | Path | None = None,
    stocks_api_token: str | None = None,
    crypto_api_token: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    root = Path(__file__).resolve().parents[2]
    stocks = (stocks_url or _url("KQUANT_GATEWAY_STOCKS_URL", "http://127.0.0.1:8001")).rstrip("/")
    crypto = (crypto_url or _url("KQUANT_GATEWAY_CRYPTO_URL", "http://127.0.0.1:8010")).rstrip("/")
    security = WorkspaceSecurity.from_environment()
    auth = WorkspaceSessionAuth(security)
    login_file = Path(os.getenv("LOCALAPPDATA", "")) / "KQUANT" / "workspace_login.dpapi"

    login_fingerprint = LoginFingerprintReader(login_file)
    try:
        startup_login_fingerprint = login_fingerprint()
    except OSError:
        startup_login_fingerprint = "UNREADABLE"
    login_check = LoginFingerprintCheck(login_fingerprint, startup_login_fingerprint)
    backends = {
        "stocks": Backend("stocks", stocks, stocks_api_token if stocks_api_token is not None else os.getenv("KQUANT_GATEWAY_STOCKS_API_TOKEN", ""), "X-KQUANT-API-TOKEN"),
        "crypto": Backend("crypto", crypto, crypto_api_token if crypto_api_token is not None else os.getenv("KQUANT_GATEWAY_CRYPTO_API_TOKEN", ""), "X-KQUANT-CRYPTO-INTERNAL-TOKEN"),
    }
    frontend_dir = Path(web_dist_dir).resolve() if web_dist_dir else _frontend_dir(root)
    # HTTPX otherwise reloads CA files synchronously on every proxy request,
    # including loopback HTTP. Keep verification enabled without blocking the loop.
    upstream_tls = ssl.create_default_context(cafile=certifi.where())
    @asynccontextmanager
    async def lifespan(application):
        try:
            await login_check.state(enabled=security.enabled)
            yield
        finally:
            pending = list(application.state.snapshot_requests.values())
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if application.state.snapshot_client is not None:
                await application.state.snapshot_client.aclose()
                application.state.snapshot_client = None
            login_check.close()

    app = FastAPI(title="KQUANT Unified Workspace", version=GATEWAY_VERSION, lifespan=lifespan)
    app.state.security = security
    app.state.workspace_auth = auth
    app.state.backends = backends
    app.state.frontend_dir = frontend_dir
    app.state.transport = transport
    app.state.last_backend_health = None
    app.state.login_fingerprint_check = login_check
    app.state.snapshot_requests = {}
    app.state.snapshot_client = None

    def snapshot_client():
        # Created on the serving event loop, owned and closed by its lifespan.
        # Only connections are reused: no response cache, retries or cookies.
        if app.state.snapshot_client is None:
            app.state.snapshot_client = httpx.AsyncClient(transport=transport,
                verify=upstream_tls, timeout=.75, follow_redirects=False, trust_env=False,
                cookies=CookieJar(policy=NoUpstreamCookies()),
                limits=httpx.Limits(max_connections=16, max_keepalive_connections=8,
                                    keepalive_expiry=2))
        return app.state.snapshot_client

    @app.get("/api/health/live")
    async def gateway_live():
        # This only proves this HTTP process is responsive, not research readiness.
        return {"status": "online", "gateway_version": GATEWAY_VERSION,
            "started_at": app.state.started_at, "market_data_checked": False,
            "order_submission": False, "backend_health": app.state.last_backend_health}

    @app.middleware("http")
    async def workspace_session_guard(request: Request, call_next):
        path = request.url.path
        public = {
            "/api/auth/login",
            "/api/auth/logout",
            "/api/auth/session",
            "/api/workspace/health",
            "/api/workspace/version",
            "/api/gateway/config",
            "/api/gateway/health",
            "/api/health/live",
        }
        session = auth.read(request)
        request.state.workspace_configuration_verified = False
        if path.startswith("/api/") and path not in public:
            configuration = await login_check.state(enabled=security.enabled)
            if configuration != "UNCHANGED":
                reason = "LOGIN_CONFIGURATION_CHECK_UNAVAILABLE" if configuration == "UNAVAILABLE" else "LOGIN_CONFIGURATION_RESTART_REQUIRED"
                return JSONResponse({"detail": reason, "configuration_check": dict(login_check.diagnostics)},
                                    status_code=503, headers={"Retry-After": "1"})
            request.state.workspace_configuration_verified = True
        if path.startswith("/api/") and path not in public and security.enabled:
            if not security.configured:
                return JSONResponse({"detail": "统一登录尚未配置。"}, status_code=503)
            if not session:
                return JSONResponse({"detail": "请先登录 KQUANT 统一工作台。"}, status_code=401)
            request.state.workspace_email = str(session.get("email") or security.email)
        elif path.startswith("/api/") and not security.enabled:
            # Development mode still needs an audit identity for the crypto
            # runtime, which intentionally requires X-KQUANT-WORKSPACE-USER.
            request.state.workspace_email = LOCAL_WORKSPACE_IDENTITY
        response = await call_next(request)
        # Failed checks and public health polling must not extend a session.
        if (session and security.configured and response.status_code < 400
                and request.state.workspace_configuration_verified
                and path not in {"/api/auth/login", "/api/auth/logout"}):
            auth.set_cookie(response, auth.issue(email=str(session.get("email") or security.email), issued_at=int(session["iat"]), expires_at=int(session["exp"])))
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store" if path.startswith("/api/") else "no-cache"
        return response

    @app.get("/api/auth/session")
    async def auth_session(request: Request) -> Any:
        session = auth.read(request)
        configuration = await login_check.state(enabled=security.enabled)
        request.state.workspace_configuration_verified = configuration == "UNCHANGED"
        restart_required = configuration == "CHANGED"
        unavailable = configuration == "UNAVAILABLE"
        payload = {
            "authentication_required": security.enabled or restart_required or unavailable,
            "authenticated": False if restart_required or unavailable else (bool(session) if security.enabled else True),
            "configured": security.configured,
            "restart_required": restart_required,
            "configuration_check_unavailable": unavailable,
            "configuration_check": dict(login_check.diagnostics),
            "mode": "configuration_unavailable" if unavailable else ("restart_required" if restart_required else ("workspace_email_password" if security.enabled else "not_required")),
            "email": session.get("email") if session else None,
            "expires_at": session.get("exp") if session else None,
        }
        if unavailable:
            return JSONResponse({**payload, "detail": "LOGIN_CONFIGURATION_CHECK_UNAVAILABLE"},
                                status_code=503, headers={"Retry-After": "1"})
        return payload

    @app.post("/api/auth/login")
    async def auth_login(payload: WorkspaceLoginRequest, request: Request, response: Response) -> dict[str, Any]:
        configuration = await login_check.state(enabled=security.enabled)
        if configuration != "UNCHANGED":
            reason = "LOGIN_CONFIGURATION_CHECK_UNAVAILABLE" if configuration == "UNAVAILABLE" else "LOGIN_CONFIGURATION_RESTART_REQUIRED"
            raise HTTPException(status_code=503, detail=reason, headers={"Retry-After": "1"})
        if not security.enabled:
            raise HTTPException(status_code=409, detail="统一登录未启用。")
        if not security.configured:
            raise HTTPException(status_code=503, detail="统一登录尚未配置。")
        client = request.client.host if request.client else "unknown"
        if not auth.allowed(client):
            raise HTTPException(status_code=429, detail="登录尝试过于频繁，请稍后再试。")
        if not auth.verify(payload.email, payload.password):
            auth.failed(client)
            raise HTTPException(status_code=401, detail="邮箱或密码不正确。")
        auth.clear_failures(client)
        auth.set_cookie(response, auth.issue(email=security.email))
        return {"authenticated": True, "email": security.email, "expires_in_seconds": security.max_seconds}

    @app.post("/api/auth/logout")
    async def auth_logout(response: Response) -> dict[str, Any]:
        auth.clear_cookie(response)
        return {"authenticated": False}

    async def workspace_health() -> dict[str, Any]:
        stocks_health, crypto_health = await asyncio.gather(
            _probe_backend(backends["stocks"], transport=transport, tls_context=upstream_tls),
            _probe_backend(backends["crypto"], transport=transport, tls_context=upstream_tls),
        )
        app.state.last_backend_health = {"observed_at": datetime.now(UTC).isoformat(),
            "stocks": stocks_health, "crypto": crypto_health}
        return {
            "status": "ok",
            "gateway_version": GATEWAY_VERSION,
            "api_contract_version": API_CONTRACT_VERSION,
            "frontend_contract_version": FRONTEND_CONTRACT_VERSION,
            "started_at": app.state.started_at,
            "session_mode": "unified_gateway_session",
            "stocks": stocks_health,
            "crypto": crypto_health,
            "backend_transport_auth": {
                "stocks_configured": bool(backends["stocks"].token),
                "crypto_configured": bool(backends["crypto"].token),
            },
            "read_only": True,
            "account_access": False,
            "wallet_access": False,
            "order_submission": False,
            "data_mixing": False,
            "secrets_exposed": False,
        }

    app.state.started_at = datetime.now(UTC).isoformat()
    app.state.transport_failures = __import__('collections').deque(maxlen=256)
    app.state.transport_failure_count = 0
    build_files = sorted(path for path in frontend_dir.rglob("*") if path.is_file()) if frontend_dir.exists() else []
    build_hash = hashlib.sha256("".join(f"{path.relative_to(frontend_dir).as_posix()}:{hashlib.sha256(path.read_bytes()).hexdigest()}\n" for path in build_files).encode()).hexdigest()

    @app.get("/api/workspace/health")
    async def workspace_health_route() -> dict[str, Any]:
        return await workspace_health()

    @app.get("/api/workspace/version")
    async def workspace_version() -> dict[str, Any]:
        return {
            "gateway": GATEWAY_VERSION,
            "api": API_CONTRACT_VERSION,
            "frontend": FRONTEND_CONTRACT_VERSION,
            "session": "unified_gateway_session",
            "release_id": f"options-desktop-{build_hash[:12]}",
            "build_sha256": build_hash,
            "started_at": app.state.started_at,
            "read_only": True,
        }

    @app.get("/api/gateway/config")
    async def gateway_config() -> dict[str, Any]:
        return {
            "gateway_version": GATEWAY_VERSION,
            "api_contract_version": API_CONTRACT_VERSION,
            "frontend_contract_version": FRONTEND_CONTRACT_VERSION,
            "modes": [
                {"id": "stocks", "label": "Stocks", "backend": "stocks", "session": "gateway"},
                {"id": "options", "label": "Options", "backend": "stocks", "session": "gateway"},
                {"id": "crypto", "label": "Crypto", "backend": "crypto", "session": "gateway"},
            ],
            "session_mode": "unified_gateway_session",
            "data_mixing": False,
            "read_only": True,
            "research_only": True,
            "secrets_exposed": False,
        }

    @app.get("/api/gateway/health")
    async def gateway_health() -> dict[str, Any]:
        return await workspace_health()

    async def proxy_request(domain: str, path: str, request: Request) -> Response:
        request_started = __import__('time').monotonic()
        backend_path = _resolve_backend_path(domain, path, request.method)
        if backend_path is None:
            raise HTTPException(status_code=404, detail="该研究接口未开放。")
        backend = backends[domain]
        headers = {"accept": request.headers.get("accept", "application/json")}
        if request.headers.get("content-type"):
            headers["content-type"] = request.headers["content-type"]
        if request.headers.get("user-agent"):
            headers["user-agent"] = request.headers["user-agent"][:500]
        if backend.token:
            headers[backend.header_name] = backend.token
        if getattr(request.state, "workspace_email", None):
            headers["X-KQUANT-WORKSPACE-USER"] = str(request.state.workspace_email)
        try:
            content = await request.body() if request.method not in {"GET", "HEAD"} else b""
        except ClientDisconnect:
            # No completed body means no write may be forwarded upstream.
            return Response(status_code=499)
        upstream_progress = {"stage": "NOT_STARTED", "request_id": __import__('uuid').uuid4().hex}
        headers['X-Request-Id'] = upstream_progress['request_id']
        try:
            memory_snapshot = backend_path in {"/api/health/live", "/api/options/opening-trend/current", "/api/options/one-minute/status"}
            bounded_read = request.method == "GET" and (memory_snapshot or backend_path == "/api/options/one-minute/manual")
            parameters = list(request.query_params.multi_items())

            async def fetch():
                async def trace(event, info):
                    if event.endswith('connect_tcp.started'):
                        upstream_progress['stage'] = 'CONNECT'
                    elif event.endswith('connect_tcp.complete'):
                        upstream_progress['stage'] = 'CONNECTED'
                    elif event.endswith('send_request_headers.started'):
                        upstream_progress['stage'] = 'SEND'
                    elif event.endswith('receive_response_headers.started'):
                        upstream_progress['stage'] = 'RECEIVE'
                if bounded_read:
                    return await snapshot_client().request(request.method, backend.base_url + backend_path,
                        params=parameters, headers=headers, content=content or None, extensions={'trace': trace})
                async with httpx.AsyncClient(transport=transport, verify=upstream_tls, timeout=20.0, follow_redirects=False, trust_env=False) as client:
                    return await client.request(request.method, backend.base_url + backend_path,
                        params=parameters, headers=headers, content=content or None, extensions={'trace': trace})

            if bounded_read:
                # Share only an in-flight read. Completed data and qualification
                # timestamps are never retained or renewed by the Gateway.
                key = (domain, backend_path, tuple(parameters),
                       headers.get("accept"), headers.get("X-KQUANT-WORKSPACE-USER"))
                pending = app.state.snapshot_requests
                task = pending.get(key)
                if task is None:
                    if len(pending) >= 16:
                        return JSONResponse({"detail": "SNAPSHOT_READ_CAPACITY"},
                                            status_code=503, headers={"Retry-After": "1"})
                    task = asyncio.create_task(asyncio.wait_for(fetch(), timeout=.75))
                    task._kquant_upstream_progress = upstream_progress
                    pending[key] = task

                    def release(completed):
                        if pending.get(key) is completed:
                            pending.pop(key, None)
                        if not completed.cancelled():
                            completed.exception()

                    task.add_done_callback(release)
                else:
                    upstream_progress = getattr(task, '_kquant_upstream_progress', {'stage': 'UNKNOWN'})
                upstream = await asyncio.shield(task)
            else:
                upstream = await fetch()
        except (httpx.HTTPError, TimeoutError) as exc:
            code = ("UPSTREAM_CONNECTION_FAILED" if isinstance(exc, httpx.ConnectError)
                    else "UPSTREAM_TIMEOUT" if isinstance(exc, (httpx.TimeoutException, TimeoutError))
                    else "UPSTREAM_TRANSPORT_FAILED")
            request_id = upstream_progress['request_id']
            app.state.transport_failure_count += 1
            # No query strings, headers, bodies, credentials or exception text.
            app.state.transport_failures.append({
                'request_id': request_id, 'path': backend_path, 'domain': domain,
                'started_monotonic': request_started,
                'ended_monotonic': __import__('time').monotonic(),
                'error_code': code, 'error_type': type(exc).__name__,
                'failure_stage': upstream_progress['stage'], 'status': 503})
            return JSONResponse({"detail": f"{domain} 研究服务暂时不可用。",
                                 "error_code": code, "error_origin": "GATEWAY_UPSTREAM",
                                 "error_type": type(exc).__name__,
                                 "failure_stage": upstream_progress['stage']},
                                status_code=503, headers={"Retry-After": "1",
                                    "X-Kquant-Error-Code": code,
                                    "X-Kquant-Error-Origin": "GATEWAY_UPSTREAM",
                                    "X-Kquant-Failure-Stage": upstream_progress["stage"],
                                    "X-Request-Id": request_id})
        response_headers = _filtered_headers(upstream)
        response_headers['X-Request-Id'] = upstream_progress['request_id']
        if upstream.status_code == 429:
            response_headers['X-Kquant-Error-Origin'] = 'UPSTREAM_HTTP'
        return Response(upstream.content, status_code=upstream.status_code, headers=response_headers)

    @app.get("/api/options/contracts/stream")
    @app.get("/api/stocks/chart/stream")
    async def stock_chart_stream(request: Request) -> StreamingResponse:
        backend = backends["stocks"]
        headers = {"accept": "text/event-stream"}
        if backend.token:
            headers[backend.header_name] = backend.token
        async def stream():
            try:
                async with httpx.AsyncClient(transport=transport, verify=upstream_tls, timeout=httpx.Timeout(20, read=None), trust_env=False) as client:
                    async with client.stream("GET", backend.base_url + request.url.path, params=list(request.query_params.multi_items()), headers=headers) as upstream:
                        if upstream.status_code != 200:
                            yield 'event: failure\ndata: {"error_code":"UPSTREAM_UNAVAILABLE"}\n\n'
                            return
                        async for chunk in upstream.aiter_bytes():
                            if await request.is_disconnected():
                                break
                            yield chunk
            except httpx.HTTPError:
                yield 'event: failure\ndata: {"error_code":"NETWORK_ERROR"}\n\n'
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.api_route("/api/stocks/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def stock_proxy(path: str, request: Request) -> Response:
        return await proxy_request("stocks", path, request)

    @app.api_route("/api/crypto/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def crypto_proxy(path: str, request: Request) -> Response:
        return await proxy_request("crypto", path, request)

    @app.api_route("/api/options/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def options_proxy(path: str, request: Request) -> Response:
        return await proxy_request("stocks", f"options/{path}", request)

    @app.get("/api/alerts/stream")
    async def merged_alert_stream(request: Request) -> StreamingResponse:
        async def stream():
            queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
            tasks: list[asyncio.Task[None]] = []

            async def consume(domain: str) -> None:
                backend = backends[domain]
                headers = {backend.header_name: backend.token} if backend.token else {}
                if getattr(request.state, "workspace_email", None):
                    headers["X-KQUANT-WORKSPACE-USER"] = str(request.state.workspace_email)
                try:
                    async with httpx.AsyncClient(transport=transport, verify=upstream_tls,
                            timeout=httpx.Timeout(3, read=20), follow_redirects=False, trust_env=False) as client:
                        async with client.stream("GET", backend.base_url + ("/api/alerts/stream" if domain == "stocks" else "/api/crypto/alerts/stream"), headers=headers) as upstream:
                            content_type = upstream.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                            if upstream.status_code != 200 or content_type != "text/event-stream":
                                if domain == "stocks":
                                    try:
                                        default_retry = 60 if upstream.status_code == 429 else 5
                                        retry_ms = max(5000, int(upstream.headers.get("retry-after", str(default_retry))) * 1000)
                                    except ValueError:
                                        retry_ms = 60000 if upstream.status_code == 429 else 5000
                                    await queue.put(("stocks_error", json.dumps({
                                        "code": "STOCKS_EVENT_STREAM_UNAVAILABLE" if upstream.status_code != 200 else "STOCKS_EVENT_STREAM_CONTENT_TYPE",
                                        "status": upstream.status_code, "retry_ms": retry_ms})))
                                return
                            if domain == "stocks":
                                await queue.put(("stocks_ready", ""))
                            async for line in upstream.aiter_lines():
                                if line.startswith("data:"):
                                    await queue.put((domain, line[5:].strip()))
                except asyncio.CancelledError:
                    raise
                except httpx.HTTPError as exc:
                    if domain == "stocks":
                        await queue.put(("stocks_error", json.dumps({"code": "STOCKS_EVENT_STREAM_TRANSPORT",
                            "error_type": type(exc).__name__, "retry_ms": 5000})))
                else:
                    if domain == "stocks":
                        await queue.put(("stocks_error", json.dumps({"code": "STOCKS_EVENT_STREAM_ENDED", "retry_ms": 5000})))

            tasks = [asyncio.create_task(consume("stocks")), asyncio.create_task(consume("crypto"))]
            try:
                while True:
                    try:
                        domain, payload = await asyncio.wait_for(queue.get(), timeout=15)
                        if domain == "stocks_ready":
                            yield 'retry: 5000\nevent: ready\ndata: {"source":"unified_gateway","read_only":true,"stocks_connected": true}\n\n'
                            continue
                        if domain == "stocks_error":
                            detail = json.loads(payload)
                            yield f"retry: {detail['retry_ms']}\nevent: error\ndata: {payload}\n\n"
                            break
                        event_name = alert_stream_event_name(payload)
                        yield f"event: {event_name}\ndata: {json.dumps({'domain': domain, 'payload': payload}, ensure_ascii=False)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/stocks")
    async def stocks_redirect() -> RedirectResponse:
        return RedirectResponse("/?market=stocks", status_code=307)

    @app.get("/crypto")
    async def crypto_redirect() -> RedirectResponse:
        return RedirectResponse("/?market=crypto", status_code=307)

    @app.get("/options")
    async def options_redirect() -> RedirectResponse:
        return RedirectResponse("/?workspace=options", status_code=307)

    def frontend_file(name: str) -> Path | None:
        candidate = frontend_dir / name
        return candidate if candidate.exists() and candidate.is_file() else None

    def frontend_index_file() -> Path | None:
        # Keep the unified HTML entry separate from the legacy stock build.
        return frontend_file("index.html") or frontend_file("unified.html")

    assets_dir = frontend_dir / "assets"
    if assets_dir.exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/assets", StaticFiles(directory=assets_dir), name="workspace-assets")

    @app.get("/manifest.webmanifest")
    async def manifest() -> Response:
        path = frontend_file("manifest.webmanifest")
        return FileResponse(path, media_type="application/manifest+json") if path else JSONResponse({"name": "KQUANT Unified Workspace", "display": "standalone"})

    @app.get("/service-worker.js")
    async def service_worker() -> Response:
        path = frontend_file("service-worker.js")
        return FileResponse(path, media_type="application/javascript") if path else Response("self.addEventListener('fetch',()=>{});", media_type="application/javascript")

    @app.get("/kq-mark.svg")
    @app.get("/favicon.svg")
    async def mark() -> Response:
        path = frontend_file("kq-mark.svg") or frontend_file("favicon.svg")
        if path:
            return FileResponse(path, media_type="image/svg+xml")
        return Response("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='10' fill='#151a1e'/><text x='10' y='42' fill='#5ea8ff' font-size='26' font-family='Arial' font-weight='700'>KQ</text></svg>", media_type="image/svg+xml")

    @app.get("/", response_class=HTMLResponse)
    async def index() -> Response:
        path = frontend_index_file()
        return FileResponse(path) if path else HTMLResponse(FALLBACK_PAGE)

    @app.get("/{asset_path:path}")
    async def frontend_fallback(asset_path: str) -> Response:
        if asset_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        path = frontend_file(asset_path)
        if path:
            return FileResponse(path)
        index_path = frontend_index_file()
        return FileResponse(index_path) if index_path else HTMLResponse(FALLBACK_PAGE)

    return app


app = create_gateway_app()


__all__ = ["API_CONTRACT_VERSION", "FRONTEND_CONTRACT_VERSION", "GATEWAY_VERSION", "create_gateway_app", "app"]


