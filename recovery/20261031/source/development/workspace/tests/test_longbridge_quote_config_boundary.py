"""SDK constructor contract with fake credentials; never creates a real context."""
import sys
from types import SimpleNamespace

from kquant.longbridge_provider import LongbridgeReadOnlyRuntime


def test_quote_config_maps_credentials_and_explicitly_disables_paper(monkeypatch):
    values = ('TEST_ONLY_KEY', 'TEST_ONLY_SECRET', 'TEST_ONLY_TOKEN')
    for name, value in zip(('LONGBRIDGE_APP_KEY', 'LONGBRIDGE_APP_SECRET', 'LONGBRIDGE_ACCESS_TOKEN'), values):
        monkeypatch.setenv(name, value)
    monkeypatch.setenv('LONGBRIDGE_PAPERTRADING', 'true')
    monkeypatch.setenv('LONGPORT_PAPERTRADING', 'true')
    calls = []
    sentinel = object()

    def from_apikey(*args, **kwargs):
        calls.append((args, kwargs))
        return sentinel

    monkeypatch.setitem(sys.modules, 'longbridge.openapi', SimpleNamespace(
        Config=SimpleNamespace(from_apikey=from_apikey), QuoteContext=lambda config: config))
    # This constructor path needs no executor or runtime subscription setup.
    runtime = object.__new__(LongbridgeReadOnlyRuntime)
    assert runtime._build_context() is sentinel
    assert len(calls) == 1
    assert calls[0][0] == values
    assert calls[0][1]['enable_print_quote_packages'] is False
    assert calls[0][1].get('enable_papertrading') is False
