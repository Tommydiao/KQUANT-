from __future__ import annotations

"""Read-only Stocks/Crypto entry gateway.

The gateway provides one clear entry page and a health view. It does not
proxy data, merge databases, share session cookies, or expose execution APIs.
Each product keeps its own backend, database, and login boundary.
"""

import html
import os
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse


GATEWAY_VERSION = "kquant_gateway_v1.2.0"


GATEWAY_PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#071019">
  <title>KQUANT Research Gateway</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; color: #e8f1f8; background: #071019; }
    main { width: min(980px, 100%); margin: 0 auto; padding: 48px 20px; }
    .top { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 42px; }
    .brand { display: flex; align-items: center; gap: 14px; }
    .mark { display: grid; place-items: center; width: 52px; height: 52px; border: 1px solid #3e9dca; border-radius: 14px; color: #83dbff; background: #0c1c2a; font-weight: 800; letter-spacing: .04em; }
    h1, h2, p { margin: 0; }
    h1 { font-size: clamp(28px, 5vw, 46px); letter-spacing: -.02em; }
    h2 { font-size: 18px; }
    .eyebrow, .muted, .meta { color: #8ea5b8; }
    .eyebrow { font-size: 12px; text-transform: uppercase; letter-spacing: .14em; margin-bottom: 7px; }
    .lead { max-width: 690px; color: #a9bdcc; line-height: 1.65; font-size: 17px; }
    .version { white-space: nowrap; color: #8ea5b8; font: 12px ui-monospace, SFMono-Regular, Consolas, monospace; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
    .mode { display: grid; gap: 20px; min-height: 220px; padding: 24px; color: inherit; text-decoration: none; border: 1px solid #294258; border-radius: 16px; background: #0d1a27; transition: border-color .18s ease, transform .18s ease, background .18s ease; }
    .mode:hover, .mode:focus-visible { border-color: #67c9f4; background: #102333; transform: translateY(-2px); outline: none; }
    .mode-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .mode-copy { display: grid; gap: 8px; }
    .mode-copy p { color: #9fb3c1; line-height: 1.55; }
    .arrow { color: #72d2fb; font-size: 22px; }
    .pill { display: inline-flex; align-items: center; width: fit-content; padding: 6px 9px; border: 1px solid #31516a; border-radius: 999px; color: #a9bdcc; font-size: 12px; }
    .pill.ok { border-color: #278c70; color: #6ee7bd; }
    .pill.warn { border-color: #9a7935; color: #f4ca71; }
    .pill.bad { border-color: #9b4d5b; color: #ff9eae; }
    .foot { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px; margin-top: 22px; padding-top: 18px; border-top: 1px solid #203548; }
    .foot span { color: #8ea5b8; font-size: 12px; }
    @media (max-width: 680px) { main { padding: 28px 16px; } .top { display: grid; margin-bottom: 28px; } .grid { grid-template-columns: 1fr; } .mode { min-height: 180px; } }
  </style>
</head>
<body>
  <main>
    <header class="top">
      <div class="brand">
        <div class="mark" aria-label="KQ">KQ</div>
        <div><div class="eyebrow">Research terminal</div><h1>KQUANT</h1></div>
      </div>
      <div class="version">__VERSION__</div>
    </header>
    <p class="lead">Choose a research workspace. Stocks and Crypto remain separate applications with independent sessions, databases, data providers, and read-only boundaries.</p>
    <section class="grid" aria-label="Research workspaces">
      <a class="mode" href="__STOCKS_URL__">
        <div class="mode-head"><span class="pill" id="stocks-status">Checking</span><span class="arrow" aria-hidden="true">&#8594;</span></div>
        <div class="mode-copy"><h2>Stocks</h2><p>US equities, Longbridge market data, themes, Stock Quant, and research journals.</p><span class="muted">Independent stock backend</span></div>
      </a>
      <a class="mode" href="__CRYPTO_URL__">
        <div class="mode-head"><span class="pill" id="crypto-status">Checking</span><span class="arrow" aria-hidden="true">&#8594;</span></div>
        <div class="mode-copy"><h2>Crypto</h2><p>CEX, DEX/MEME, crypto roll research, Bayesian evidence, Monte Carlo, and EVAL.</p><span class="muted">Independent crypto backend</span></div>
      </a>
    </section>
    <footer class="foot"><span>Read-only research gateway</span><span id="health-note">Checking backend health...</span></footer>
  </main>
  <script>
    async function loadHealth() {
      const note = document.getElementById("health-note");
      try {
        const response = await fetch("/api/gateway/health", { cache: "no-store" });
        const payload = await response.json();
        for (const name of ["stocks", "crypto"]) {
          const item = payload[name] || {};
          const node = document.getElementById(name + "-status");
          node.textContent = item.status === "available" ? "Available" : (item.status || "Unavailable");
          node.className = "pill " + (item.status === "available" ? "ok" : "bad");
        }
        note.textContent = payload.data_mixing === false && payload.order_submission === false ? "Separate sessions · no account or order access" : "Review gateway boundary";
      } catch (error) {
        note.textContent = "Backend health unavailable";
        for (const name of ["stocks", "crypto"]) {
          const node = document.getElementById(name + "-status");
          node.textContent = "Unavailable";
          node.className = "pill bad";
        }
      }
    }
    loadHealth();
    window.setInterval(loadHealth, 15000);
  </script>
</body>
</html>"""


def _url(name: str, default: str) -> str:
    return os.getenv(name, default).strip().rstrip("/")


def _render_gateway_page(stocks: str, crypto: str) -> str:
    return (
        GATEWAY_PAGE_TEMPLATE
        .replace("__VERSION__", html.escape(GATEWAY_VERSION))
        .replace("__STOCKS_URL__", html.escape(stocks + "/", quote=True))
        .replace("__CRYPTO_URL__", html.escape(crypto + "/", quote=True))
    )


def create_gateway_app(*, stocks_url: str | None = None, crypto_url: str | None = None) -> FastAPI:
    stocks = (stocks_url or _url("KQUANT_GATEWAY_STOCKS_URL", "http://127.0.0.1:8001")).rstrip("/")
    crypto = (crypto_url or _url("KQUANT_GATEWAY_CRYPTO_URL", "http://127.0.0.1:8010")).rstrip("/")
    app = FastAPI(title="KQUANT Gateway", version=GATEWAY_VERSION)

    @app.get("/", response_class=HTMLResponse)
    async def landing() -> str:
        return _render_gateway_page(stocks, crypto)

    @app.get("/stocks")
    async def stocks_redirect() -> RedirectResponse:
        return RedirectResponse(stocks + "/", status_code=307)

    @app.get("/crypto")
    async def crypto_redirect() -> RedirectResponse:
        return RedirectResponse(crypto + "/", status_code=307)

    @app.get("/api/gateway/config")
    async def gateway_config() -> dict[str, Any]:
        """Expose navigation metadata without proxying sessions or data."""

        return {
            "gateway_version": GATEWAY_VERSION,
            "modes": [
                {"id": "stocks", "label": "Stocks", "url": stocks + "/", "session": "stock_backend"},
                {"id": "crypto", "label": "Crypto", "url": crypto + "/", "session": "crypto_backend"},
            ],
            "session_mode": "separate_backend_sessions",
            "data_mixing": False,
            "read_only": True,
            "research_only": True,
            "secrets_exposed": False,
        }

    async def probe(name: str, url: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=3.0, follow_redirects=False, trust_env=False) as client:
                response = await client.get(url + "/api/health")
            body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            runtime = body.get("runtime") if isinstance(body.get("runtime"), dict) else {}
            return {
                "name": name,
                "status": "available" if response.status_code == 200 else "unhealthy",
                "http_status": response.status_code,
                "app_version": body.get("app_version") or runtime.get("app_version") or runtime.get("strategy_version"),
                "api_contract_version": body.get("api_contract_version") or runtime.get("api_contract_version"),
                "read_only": body.get("read_only") if body.get("read_only") is not None else body.get("read_only_research", runtime.get("read_only")),
                "url_configured": True,
                "secrets_exposed": False,
            }
        except (httpx.HTTPError, ValueError, TypeError):
            return {"name": name, "status": "unavailable", "url_configured": True, "secrets_exposed": False}

    @app.get("/api/gateway/health")
    async def gateway_health() -> dict[str, Any]:
        return {
            "gateway_version": GATEWAY_VERSION,
            "stocks": await probe("stocks", stocks),
            "crypto": await probe("crypto", crypto),
            "session_mode": "separate_backend_sessions",
            "data_mixing": False,
            "account_access": False,
            "wallet_access": False,
            "order_submission": False,
            "research_only": True,
        }

    return app


app = create_gateway_app()


__all__ = ["GATEWAY_VERSION", "create_gateway_app", "app"]
