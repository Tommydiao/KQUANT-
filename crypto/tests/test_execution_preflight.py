from __future__ import annotations

from dataclasses import replace

from kquant_crypto.config import ExecutionMode, ExecutionSettings
from kquant_crypto.execution_service import ExecutionController


def test_preflight_is_no_go_and_side_effect_free_when_disabled(settings):
    controller = ExecutionController(settings.db_path, ExecutionSettings())
    result = controller.preflight()
    assert result["status"] == "NO_GO"
    assert result["side_effects"] is False
    assert result["armed"] is False
    assert "execution_mode_selected" in result["blockers"]


def test_preflight_does_not_create_client_without_credentials(settings):
    called = []
    execution = replace(ExecutionSettings(), mode=ExecutionMode.TESTNET, autotrade_enabled=True)
    controller = ExecutionController(
        settings.db_path,
        execution,
        client_factory=lambda: called.append(True),
    )
    result = controller.preflight()
    assert result["status"] == "NO_GO"
    assert "credentials_configured" in result["blockers"]
    assert called == []
