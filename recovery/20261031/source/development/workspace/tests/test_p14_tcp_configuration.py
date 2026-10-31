"""Real runner/CLI configuration checks; no production process, DB or SDK."""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / 'crypto'))

def test_gateway_loop_matches_existing_windows_backend(monkeypatch):
    import uvicorn
    from kquant_crypto.__main__ import main
    calls = []
    monkeypatch.setenv('KQUANT_GATEWAY_LAN_ADDRESS', '')
    monkeypatch.setattr(uvicorn, 'run', lambda *args, **kwargs: calls.append(kwargs))
    assert main(['gateway']) == 0
    assert calls[0]['loop'] == ('asyncio:SelectorEventLoop' if sys.platform == 'win32' else 'auto')

def test_actual_runner_honors_server_loop_factory(tmp_path):
    spec = importlib.util.spec_from_file_location('p14_loop_harness', CODE / 'scripts/check_r58_p10_topology.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    observed = []
    class Server:
        config = SimpleNamespace(get_loop_factory=lambda: asyncio.SelectorEventLoop)
        async def serve(self):
            observed.append(type(asyncio.get_running_loop()).__name__)
    module.observed_server(Server(), tmp_path, 'runner-test')
    expected = '_WindowsSelectorEventLoop' if sys.platform == 'win32' else '_UnixSelectorEventLoop'
    assert observed == [expected]
