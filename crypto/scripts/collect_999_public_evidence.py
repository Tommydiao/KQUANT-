from __future__ import annotations

"""Collect the public evidence set required by the 999 research plan.

This is deliberately a batch *research* collector.  It only calls the
registered public Binance, OKX and DefiLlama adapters, writes source-timed
snapshots, and keeps a failure for one asset/provider isolated from the rest
of the batch.  No account, wallet, order or execution endpoint is reachable
from this script.
"""

import argparse
import json
import time
from pathlib import Path
import sys
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kquant_crypto.config import load_settings  # noqa: E402
from kquant_crypto.db.migrations import migrate  # noqa: E402
from kquant_crypto.external_evidence import save_evidence_snapshot  # noqa: E402
from kquant_crypto.market_structure_evidence import fetch_binance_market_structure_evidence  # noqa: E402
from kquant_crypto.providers.defillama import DefiLlamaPublicAdapter  # noqa: E402
from kquant_crypto.public_evidence import (  # noqa: E402
    fetch_binance_derivatives_evidence,
    fetch_okx_derivatives_evidence,
)


DEFAULT_SYMBOLS = ("BTC", "ETH", "SOL", "AAVE", "ENA", "ZEC", "PUMP")
CORE_SYMBOLS = ("BTC", "ETH", "SOL")


def _asset_id(symbol: str) -> str:
    normalized = str(symbol).strip().upper().replace("/", "").replace("-", "")
    for quote in ("USDT", "USDC", "USD"):
        if normalized.endswith(quote):
            normalized = normalized[: -len(quote)]
            break
    return f"asset:{normalized.lower()}"


def _quote_symbol(symbol: str) -> str:
    normalized = str(symbol).strip().upper().replace("/", "").replace("-", "")
    return normalized if normalized.endswith(("USDT", "USDC", "USD")) else f"{normalized}USDT"


def _save_result(
    *,
    db_path: Path,
    provider: str,
    category: str,
    symbol: str,
    collect: Callable[[], Any],
) -> dict[str, Any]:
    """Save one provider result and turn exceptions into an audit row."""

    normalized = str(symbol).strip().upper()
    try:
        result = collect()
        snapshot = result.snapshot
        saved = save_evidence_snapshot(db_path, snapshot)
        return {
            "provider": provider,
            "category": category,
            "symbol": normalized,
            "status": result.status,
            "trust_status": saved.get("trust_status"),
            "field_count": len(saved.get("values") or {}),
            "missing_fields": list(saved.get("missing_fields") or []),
            "evidence_id": saved.get("evidence_id"),
        }
    except Exception as exc:  # Keep a public provider failure fail-closed and local.
        return {
            "provider": provider,
            "category": category,
            "symbol": normalized,
            "status": "collector_error",
            "trust_status": "data_caution",
            "field_count": 0,
            "missing_fields": ["provider_response"],
            "error_type": type(exc).__name__,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect source-timed public evidence for the KQUANT 999 plan."
    )
    parser.add_argument("--symbol", action="append", dest="symbols", help="repeat an asset symbol")
    parser.add_argument("--skip-okx", action="store_true", help="skip the OKX core-asset cross-check")
    parser.add_argument("--skip-defillama", action="store_true", help="skip public DefiLlama context")
    parser.add_argument("--sleep-seconds", type=float, default=0.15)
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--report-path", type=Path)
    args = parser.parse_args()

    settings = load_settings(ROOT)
    db_path = (args.db_path or settings.db_path).resolve()
    report_path = (args.report_path or settings.outputs_dir / "crypto_999_public_evidence_latest.json").resolve()
    migrate(db_path)

    symbols = tuple(dict.fromkeys(
        str(value).strip().upper().replace("USDT", "")
        for value in (args.symbols or DEFAULT_SYMBOLS)
        if str(value).strip()
    ))
    results: list[dict[str, Any]] = []

    for symbol in symbols:
        results.append(_save_result(
            db_path=db_path,
            provider="binance_public_derivatives",
            category="exchange_derivatives",
            symbol=symbol,
            collect=lambda symbol=symbol: fetch_binance_derivatives_evidence(
                asset_id=_asset_id(symbol), symbol=symbol,
            ),
        ))
        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    if not args.skip_okx:
        for symbol in CORE_SYMBOLS:
            if symbol not in symbols:
                continue
            results.append(_save_result(
                db_path=db_path,
                provider="okx_public_derivatives",
                category="exchange_derivatives",
                symbol=symbol,
                collect=lambda symbol=symbol: fetch_okx_derivatives_evidence(
                    asset_id=_asset_id(symbol), symbol=symbol,
                ),
            ))
            if args.sleep_seconds > 0:
                time.sleep(args.sleep_seconds)

    # The breadth response is one point-in-time market snapshot.  Saving it
    # for BTC and ETH makes the category coverage explicit without pretending
    # that the same snapshot is an asset-specific on-chain metric.
    for symbol in ("BTC", "ETH"):
        if symbol not in symbols:
            continue
        results.append(_save_result(
            db_path=db_path,
            provider="binance_public_market_structure",
            category="market_structure",
            symbol=symbol,
            collect=lambda symbol=symbol: fetch_binance_market_structure_evidence(
                asset_id=_asset_id(symbol),
                symbol=symbol,
                universe_symbols=tuple(_quote_symbol(value) for value in settings.core_symbols),
            ),
        ))
        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    if not args.skip_defillama:
        adapter = DefiLlamaPublicAdapter()
        for symbol in ("BTC", "ETH"):
            if symbol not in symbols:
                continue
            results.append(_save_result(
                db_path=db_path,
                provider="defillama_public",
                category="onchain",
                symbol=symbol,
                collect=lambda symbol=symbol: adapter.fetch(
                    asset_id=_asset_id(symbol), symbol=symbol, category="onchain", enabled=True,
                ),
            ))
            if args.sleep_seconds > 0:
                time.sleep(args.sleep_seconds)
        for symbol in ("AAVE", "ENA"):
            if symbol not in symbols:
                continue
            results.append(_save_result(
                db_path=db_path,
                provider="defillama_public",
                category="protocol_metric",
                symbol=symbol,
                collect=lambda symbol=symbol: adapter.fetch(
                    asset_id=_asset_id(symbol), symbol=symbol, category="protocol_metric", enabled=True,
                ),
            ))
            if args.sleep_seconds > 0:
                time.sleep(args.sleep_seconds)

    status = "complete" if results and all(item["status"] == "complete" for item in results) else "partial"
    report = {
        "status": status,
        "collector_version": "crypto_999_public_evidence_batch_v1.0.0",
        "symbols": list(symbols),
        "results": results,
        "missing_is_na": True,
        "unknown_values_are_blocked": True,
        "research_only": True,
        "account_access": False,
        "wallet_access": False,
        "order_submission": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if status == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
