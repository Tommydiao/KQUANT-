import asyncio

import httpx
import pytest

from kquant_crypto import hybrid_probe_recording as module


def test_partial_probe_failure_preserves_previous(monkeypatch):
    records = []
    class Client:
        calls = 0
        async def get(self, url, **kwargs):
            self.calls += 1
            if self.calls == 2:
                raise httpx.ConnectError('sensitive exception text must not be logged')
            return httpx.Response(200, json={'serverTime':1788690000000}, request=httpx.Request('GET', url))
    async def no_sleep(_):
        pass
    monkeypatch.setattr(module.asyncio, 'sleep', no_sleep)
    with pytest.raises(httpx.ConnectError):
        asyncio.run(module.probes(Client(), records.append))
    assert len(records) == 2
    assert records[0]['state'] == 'RECEIVED'
    assert records[1]['state'] == 'FAILED'
    assert records[1]['index'] == 1
    assert 'sensitive' not in str(records)


def test_record_failure_cannot_be_silently_ignored():
    class Client:
        async def get(self, url, **kwargs):
            return httpx.Response(200, json={'serverTime':1788690000000}, request=httpx.Request('GET', url))
    def bad_sink(_):
        raise OSError('disk unavailable')
    with pytest.raises(OSError):
        asyncio.run(module.probes(Client(), bad_sink))
