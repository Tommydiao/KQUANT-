from __future__ import annotations

"""Explicit, non-overriding local environment loading for operational jobs."""

import os
from pathlib import Path
from typing import Iterable


MARKET_DATA_ENV_KEYS = frozenset(
    {
        "KQUANT_MARKET_DATA_PROVIDER",
        "KQUANT_LONGBRIDGE_TIMEOUT_SECONDS",
        "LONGBRIDGE_APP_KEY",
        "LONGBRIDGE_APP_SECRET",
        "LONGBRIDGE_ACCESS_TOKEN",
    }
)


def default_local_env_path() -> Path:
    configured = str(os.getenv("KQUANT_ENV_FILE") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1] / ".env"


def _parse_assignment(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text or text.startswith("#") or "=" not in text:
        return None
    name, value = text.split("=", 1)
    name = name.strip()
    if name.startswith("export "):
        name = name.removeprefix("export ").strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    if not name or not value:
        return None
    return name, value


def load_market_data_env(
    *,
    path: Path | None = None,
    keys: Iterable[str] = MARKET_DATA_ENV_KEYS,
) -> dict[str, object]:
    """Load only missing market-data settings from a local `.env` file.

    Callers opt in explicitly, so importing research modules cannot silently
    switch tests or request handlers to a developer's local credentials. The
    returned audit payload deliberately contains no configuration values.
    """

    source = path or default_local_env_path()
    requested = frozenset(str(key) for key in keys)
    if not source.exists():
        return {
            "status": "env_file_missing",
            "path_configured": bool(path or os.getenv("KQUANT_ENV_FILE")),
            "loaded_key_count": 0,
            "longbridge_credentials_configured": all(bool(os.getenv(key)) for key in _longbridge_keys()),
        }

    loaded: list[str] = []
    for raw_line in source.read_text(encoding="utf-8").splitlines():
        assignment = _parse_assignment(raw_line)
        if assignment is None:
            continue
        name, value = assignment
        if name not in requested or os.getenv(name):
            continue
        os.environ[name] = value
        loaded.append(name)
    return {
        "status": "loaded" if loaded else "already_configured_or_no_matching_values",
        "path_configured": bool(path or os.getenv("KQUANT_ENV_FILE")),
        "loaded_key_count": len(loaded),
        "longbridge_credentials_configured": all(bool(os.getenv(key)) for key in _longbridge_keys()),
    }


def _longbridge_keys() -> tuple[str, str, str]:
    return ("LONGBRIDGE_APP_KEY", "LONGBRIDGE_APP_SECRET", "LONGBRIDGE_ACCESS_TOKEN")


__all__ = ["MARKET_DATA_ENV_KEYS", "default_local_env_path", "load_market_data_env"]
