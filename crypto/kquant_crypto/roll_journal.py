from __future__ import annotations

import re
from dataclasses import dataclass
from math import isfinite
from typing import Any

from .evaluation_models import stable_hash


ROLL_JOURNAL_PREVIEW_VERSION = "crypto_roll_journal_preview_v1.0.0"
_NUMBER = r"([-+]?(?:\d+(?:\.\d+)?|\.\d+))"


def _value(text: str, labels: tuple[str, ...]) -> float | None:
    label = "|".join(re.escape(item) for item in labels)
    match = re.search(rf"(?:{label})\s*[:=：]?\s*\$?\s*{_NUMBER}", text, re.IGNORECASE)
    if not match:
        return None
    parsed = float(match.group(1))
    return parsed if isfinite(parsed) else None


@dataclass(frozen=True)
class RollJournalPreview:
    preview_id: str
    preview_version: str
    symbol: str | None
    realized_profit: float | None
    rolled_capital: float | None
    remaining_risk: float | None
    user_note: str
    missing_fields: tuple[str, ...]
    status: str
    write_allowed: bool
    content_hash: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "preview_id": self.preview_id,
            "preview_version": self.preview_version,
            "symbol": self.symbol,
            "realized_profit": self.realized_profit,
            "rolled_capital": self.rolled_capital,
            "remaining_risk": self.remaining_risk,
            "user_note": self.user_note,
            "missing_fields": list(self.missing_fields),
            "status": self.status,
            "write_allowed": self.write_allowed,
            "content_hash": self.content_hash,
            "research_only": True,
        }


def preview_roll_journal_text(text: str) -> RollJournalPreview:
    source = str(text or "").strip()
    symbol_match = re.search(r"(?:symbol|ticker|标的|币种)\s*[:=：]?\s*\$?([A-Za-z][A-Za-z0-9_-]{1,15})", source, re.IGNORECASE)
    symbol = symbol_match.group(1).upper() if symbol_match else None
    realized_profit = _value(source, ("realized_profit", "realized profit", "已实现利润", "已实现盈利"))
    rolled_capital = _value(source, ("rolled_capital", "roll capital", "滚入资本", "滚仓资本"))
    remaining_risk = _value(source, ("remaining_risk", "remaining risk", "剩余风险"))
    note_match = re.search(r"(?:note|备注)\s*[:=：]?\s*(.+)$", source, re.IGNORECASE | re.MULTILINE)
    note = note_match.group(1).strip() if note_match else ""
    required = {
        "symbol": symbol,
        "realized_profit": realized_profit,
        "rolled_capital": rolled_capital,
        "remaining_risk": remaining_risk,
    }
    missing = tuple(key for key, value in required.items() if value is None)
    payload = {
        "preview_version": ROLL_JOURNAL_PREVIEW_VERSION,
        "symbol": symbol,
        "realized_profit": realized_profit,
        "rolled_capital": rolled_capital,
        "remaining_risk": remaining_risk,
        "user_note": note,
        "missing_fields": list(missing),
        "source_text_hash": stable_hash(source),
    }
    content_hash = stable_hash(payload)
    return RollJournalPreview(
        preview_id=f"roll_journal_preview_{content_hash[:20]}",
        preview_version=ROLL_JOURNAL_PREVIEW_VERSION,
        symbol=symbol,
        realized_profit=realized_profit,
        rolled_capital=rolled_capital,
        remaining_risk=remaining_risk,
        user_note=note,
        missing_fields=missing,
        status="preview_ready" if not missing else "preview_incomplete",
        write_allowed=False,
        content_hash=content_hash,
    )


__all__ = ["ROLL_JOURNAL_PREVIEW_VERSION", "RollJournalPreview", "preview_roll_journal_text"]
