from __future__ import annotations

from pathlib import Path

import pytest

from kquant_crypto.config import ProviderFlags, RuntimeMode, Settings
from kquant_crypto.db.migrations import migrate
from kquant_crypto.security import generate_session_secret, hash_password


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    db_path = tmp_path / "work" / "test.sqlite3"
    value = Settings(
        root_dir=tmp_path,
        mode=RuntimeMode.TEST,
        host="127.0.0.1",
        port=8010,
        db_path=db_path,
        data_dir=tmp_path / "data",
        outputs_dir=tmp_path / "outputs",
        web_dist_dir=tmp_path / "web" / "dist",
        login_email="owner@example.com",
        login_password_hash=hash_password("correct horse battery staple"),
        session_secret=generate_session_secret(),
        session_idle_minutes=30,
        session_max_hours=8,
        notifications_enabled=False,
        telegram_enabled=False,
        providers=ProviderFlags(),
        web_push_public_key="",
        web_push_private_key="",
        web_push_subject="",
        telegram_bot_token="",
        telegram_chat_id="",
    )
    value.data_dir.mkdir(parents=True, exist_ok=True)
    value.outputs_dir.mkdir(parents=True, exist_ok=True)
    migrate(db_path)
    return value
