from __future__ import annotations

from kquant.__main__ import load_local_environment


def test_cli_loads_local_environment_without_overwriting_process_values(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("KQUANT_TEST_LOCAL=from_file\nKQUANT_TEST_EXISTING=from_file\n# ignored\n", encoding="utf-8")
    monkeypatch.delenv("KQUANT_TEST_LOCAL", raising=False)
    monkeypatch.setenv("KQUANT_TEST_EXISTING", "from_process")
    load_local_environment(env_file)
    assert __import__("os").environ["KQUANT_TEST_LOCAL"] == "from_file"
    assert __import__("os").environ["KQUANT_TEST_EXISTING"] == "from_process"
