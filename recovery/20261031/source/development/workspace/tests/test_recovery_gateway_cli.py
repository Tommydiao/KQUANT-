"""The web gateway must not load the inactive Crypto business stack."""
import builtins
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import sys


def test_gateway_entry_does_not_import_crypto_database_or_settings(monkeypatch):
    source = Path(__file__).parents[1] / "crypto/kquant_crypto/__main__.py"
    real_import = builtins.__import__
    imports = []

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        imports.append(name)
        if name in {"config", "db.migrations", "staging", "security"} and level:
            raise AssertionError("Inactive Crypto dependency imported")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    server = Mock()
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(run=server))
    monkeypatch.setenv("KQUANT_GATEWAY_LAN_ADDRESS", "")
    monkeypatch.setenv("KQUANT_GATEWAY_PORT", "28020")
    spec = importlib.util.spec_from_file_location("isolated_gateway_cli", source)
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    assert entry.main(["gateway"]) == 0
    server.assert_called_once_with("kquant_crypto.gateway:app", host="127.0.0.1", port=28020, reload=False)
    assert not {"config", "db.migrations", "staging"}.intersection(imports)
