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
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Deque, Iterable

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, Field


GATEWAY_VERSION = "kquant_gateway_v2.0.0"
API_CONTRACT_VERSION = "kquant-workspace-api-2026-08-30"
FRONTEND_CONTRACT_VERSION = "kquant-workspace-web-graphite-signal-v1"
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


def _frontend_dir(default_root: Path) -> Path:
    raw = os.getenv("KQUANT_GATEWAY_WEB_DIST", "").strip()
    if not raw:
        return (default_root / "web" / "dist-unified").resolve()
    configured = Path(raw)
    return (configured if configured.is_absolute() else default_root / configured).resolve()


async def _probe_backend(backend: Backend, *, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    headers = {backend.header_name: backend.token} if backend.token else {}
    try:
        async with httpx.AsyncClient(transport=transport, timeout=3.0, follow_redirects=False, trust_env=False) as client:
            response = await client.get(backend.base_url + "/api/health", headers=headers)
        content_type = response.headers.get("content-type", "")
        body = response.json() if content_type.startswith("application/json") else {}
        return {
            "name": backend.name,
            "status": "available" if response.status_code == 200 else "unhealthy",
            "http_status": response.status_code,
            "app_version": body.get("app_version") or body.get("runtime", {}).get("app_version"),
            "api_contract_version": body.get("api_contract_version"),
            "frontend_contract_version": body.get("frontend_contract_version"),
            "read_only": body.get("read_only", True),
            "strategy": (body.get("version_matrix") or {}).get("strategy") or body.get("strategy"),
            "gateway_auth_probe": (body.get("internal_gateway_auth") or {}).get("health_probe"),
            "secrets_exposed": False,
        }
    except (httpx.HTTPError, ValueError, TypeError):
        return {"name": backend.name, "status": "unavailable", "url_configured": True, "secrets_exposed": False}


def _filtered_headers(response: httpx.Response) -> dict[str, str]:
    headers: dict[str, str] = {}
    content_type = response.headers.get("content-type")
    if content_type:
        headers["content-type"] = content_type
    if response.headers.get("cache-control"):
        headers["cache-control"] = response.headers["cache-control"]
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
    backends = {
        "stocks": Backend("stocks", stocks, stocks_api_token if stocks_api_token is not None else os.getenv("KQUANT_GATEWAY_STOCKS_API_TOKEN", ""), "X-KQUANT-API-TOKEN"),
        "crypto": Backend("crypto", crypto, crypto_api_token if crypto_api_token is not None else os.getenv("KQUANT_GATEWAY_CRYPTO_API_TOKEN", ""), "X-KQUANT-CRYPTO-INTERNAL-TOKEN"),
    }
    frontend_dir = Path(web_dist_dir).resolve() if web_dist_dir else _frontend_dir(root)
    app = FastAPI(title="KQUANT Unified Workspace", version=GATEWAY_VERSION)
    app.state.security = security
    app.state.workspace_auth = auth
    app.state.backends = backends
    app.state.frontend_dir = frontend_dir
    app.state.transport = transport

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
        }
        session = auth.read(request)
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
        if session and security.configured and path not in {"/api/auth/login", "/api/auth/logout"}:
            auth.set_cookie(response, auth.issue(email=str(session.get("email") or security.email), issued_at=int(session["iat"]), expires_at=int(session["exp"])))
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store" if path.startswith("/api/") else "no-cache"
        return response

    @app.get("/api/auth/session")
    async def auth_session(request: Request) -> dict[str, Any]:
        session = auth.read(request)
        return {
            "authentication_required": security.enabled,
            "authenticated": bool(session) if security.enabled else True,
            "configured": security.configured,
            "mode": "workspace_email_password" if security.enabled else "not_required",
            "email": session.get("email") if session else None,
            "expires_at": session.get("exp") if session else None,
        }

    @app.post("/api/auth/login")
    async def auth_login(payload: WorkspaceLoginRequest, request: Request, response: Response) -> dict[str, Any]:
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
            _probe_backend(backends["stocks"], transport=transport),
            _probe_backend(backends["crypto"], transport=transport),
        )
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
        backend_path = _resolve_backend_path(domain, path, request.method)
        if backend_path is None:
            raise HTTPException(status_code=404, detail="该研究接口未开放。")
        backend = backends[domain]
        headers = {"accept": request.headers.get("accept", "application/json")}
        if backend.token:
            headers[backend.header_name] = backend.token
        if getattr(request.state, "workspace_email", None):
            headers["X-KQUANT-WORKSPACE-USER"] = str(request.state.workspace_email)
        content = await request.body()
        try:
            async with httpx.AsyncClient(transport=transport, timeout=20.0, follow_redirects=False, trust_env=False) as client:
                upstream = await client.request(
                    request.method,
                    backend.base_url + backend_path,
                    params=list(request.query_params.multi_items()),
                    headers=headers,
                    content=content or None,
                )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail=f"{domain} 研究服务暂时不可用。") from exc
        return Response(upstream.content, status_code=upstream.status_code, headers=_filtered_headers(upstream))

    @app.api_route("/api/stocks/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def stock_proxy(path: str, request: Request) -> Response:
        return await proxy_request("stocks", path, request)

    @app.api_route("/api/crypto/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def crypto_proxy(path: str, request: Request) -> Response:
        return await proxy_request("crypto", path, request)

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
                    async with httpx.AsyncClient(transport=transport, timeout=None, follow_redirects=False, trust_env=False) as client:
                        async with client.stream("GET", backend.base_url + ("/api/alerts/stream" if domain == "stocks" else "/api/crypto/alerts/stream"), headers=headers) as upstream:
                            async for line in upstream.aiter_lines():
                                if line.startswith("data:"):
                                    await queue.put((domain, line[5:].strip()))
                except (asyncio.CancelledError, httpx.HTTPError):
                    return

            tasks = [asyncio.create_task(consume("stocks")), asyncio.create_task(consume("crypto"))]
            yield "event: ready\ndata: {\"source\":\"unified_gateway\",\"read_only\":true}\n\n"
            try:
                while True:
                    try:
                        domain, payload = await asyncio.wait_for(queue.get(), timeout=15)
                        yield f"event: alert\ndata: {json.dumps({'domain': domain, 'payload': payload}, ensure_ascii=False)}\n\n"
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
