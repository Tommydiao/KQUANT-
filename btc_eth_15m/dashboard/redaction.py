from __future__ import annotations

import re


def safe_error_detail(reason: str) -> str:
    redacted = re.sub(r"(https?://[^\s?]+)\?[^\s)]+", r"\1?<redacted>", reason)
    redacted = re.sub(
        r"(?i)\b(signature|timestamp|recvWindow|listenKey|api[_-]?key|secret)=([^&\s]+)",
        r"\1=<redacted>",
        redacted,
    )
    return redacted
