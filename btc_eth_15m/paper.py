from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from btc_eth_15m.config import AppConfig
from btc_eth_15m.data import load_klines
from btc_eth_15m.strategy import generate_signals


def run_paper_once(config: AppConfig) -> Path:
    signals = []
    for symbol in config.symbols:
        raw = load_klines(config.db_path, symbol, config.interval)
        if raw.empty:
            signals.append({"symbol": symbol, "status": "missing_data"})
            continue
        frame = generate_signals(raw, config.strategy)
        latest = frame.iloc[-1]
        signal = int(latest["signal"])
        side = "long" if signal == 1 else "short" if signal == -1 else "flat"
        signals.append(
            {
                "symbol": symbol,
                "status": "ok",
                "bar_time": str(latest["open_datetime"]),
                "side": side,
                "close": float(latest["close"]),
                "atr": float(latest["signal_atr"]) if latest["signal_atr"] == latest["signal_atr"] else None,
                "rsi": float(latest["rsi"]) if latest["rsi"] == latest["rsi"] else None,
                "note": "Signal is for the next 15m candle open; no live order is sent.",
            }
        )
    config.outputs_dir.mkdir(parents=True, exist_ok=True)
    out_path = config.outputs_dir / "paper-signal.json"
    out_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(tz=UTC).isoformat(),
                "signals": signals,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return out_path

