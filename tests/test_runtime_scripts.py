from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_script(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_daily_launcher_requires_longbridge() -> None:
    launcher = read_script("KQUANT_START.cmd")
    startup = read_script("start_kquant_stock_terminal.ps1")

    assert "-RequireLongbridge" in launcher
    assert "[switch]$RequireLongbridge" in startup
    assert "KQUANT_SETUP_LONGBRIDGE.cmd" in startup
    assert "Import-UserEnv" in startup


def test_longbridge_setup_persists_only_backend_environment() -> None:
    setup = read_script("setup_kquant_longbridge.ps1")

    assert 'SetEnvironmentVariable($item.Key, $item.Value, "User")' in setup
    assert "LONGBRIDGE_APP_KEY" in setup
    assert "LONGBRIDGE_APP_SECRET" in setup
    assert "LONGBRIDGE_ACCESS_TOKEN" in setup
    assert "VITE_" not in setup
    assert "trade_context" not in setup.lower()
    assert "order_submission" not in setup.lower()


def test_realtime_check_uses_read_only_market_data_endpoints() -> None:
    realtime_check = read_script("check_kquant_realtime.ps1")
    preflight = read_script("run_kquant_monday_preflight.ps1")

    assert "/api/stocks/market-data/status" in realtime_check
    assert "/api/stocks/market-data/self-check" in realtime_check
    assert "/api/stocks/realtime-snapshot" in realtime_check
    assert "longbridge_account_enabled" in realtime_check
    assert "longbridge_trade_enabled" in realtime_check
    assert "-RequireLongbridge" in preflight


def test_reproducible_verification_can_skip_runtime_readiness() -> None:
    verifier = read_script("verify_kquant_local.ps1")

    assert "[switch]$SkipReadiness" in verifier
    assert 'Skipped by -SkipReadiness.' in verifier
