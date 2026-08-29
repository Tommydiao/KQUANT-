from __future__ import annotations

import os

from kquant.local_env import load_market_data_env


def test_market_data_env_loads_only_missing_allowlisted_values(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "LONGBRIDGE_APP_KEY=file-key\n"
        "LONGBRIDGE_APP_SECRET='file-secret'\n"
        "LONGBRIDGE_ACCESS_TOKEN=file-token\n"
        "KQUANT_MARKET_DATA_PROVIDER=longbridge\n"
        "OPENAI_API_KEY=must-not-load\n",
        encoding="utf-8",
    )
    managed_names = (
        "LONGBRIDGE_APP_KEY",
        "LONGBRIDGE_APP_SECRET",
        "LONGBRIDGE_ACCESS_TOKEN",
        "KQUANT_MARKET_DATA_PROVIDER",
        "OPENAI_API_KEY",
    )
    original = {name: os.environ.get(name) for name in managed_names}
    try:
        for name in managed_names:
            os.environ.pop(name, None)
        os.environ["LONGBRIDGE_APP_KEY"] = "process-key"

        report = load_market_data_env(path=env_file)

        assert os.environ["LONGBRIDGE_APP_KEY"] == "process-key"
        assert os.environ["LONGBRIDGE_APP_SECRET"] == "file-secret"
        assert os.environ["LONGBRIDGE_ACCESS_TOKEN"] == "file-token"
        assert os.environ["KQUANT_MARKET_DATA_PROVIDER"] == "longbridge"
        assert "OPENAI_API_KEY" not in os.environ
        assert report["loaded_key_count"] == 3
        assert report["longbridge_credentials_configured"] is True
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
