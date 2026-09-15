import httpx
import pytest
from kquant_crypto.hybrid_loopback_transport import LoopbackHealthTransport


@pytest.mark.parametrize('url', ['https://127.0.0.1:8010/api/health',
    'http://example.com/api/health','http://127.0.0.1:8010/api/orders',
    'http://127.0.0.1:8010/api/health?secret=1'])
def test_only_fixed_endpoint_allowed(url):
    with pytest.raises(httpx.RequestError):
        LoopbackHealthTransport().handle_request(httpx.Request('GET',url))


def test_reads_close_and_no_forwarded_headers(monkeypatch):
    import kquant_crypto.hybrid_loopback_transport as module
    seen=[]
    class Connection:
        sock=None
        status=200
        def __init__(self,*args,**kwargs):
            seen.append((args,kwargs))
            self.chunks=iter([b'{"status":"ok"}',b''])
        def request(self,*args,**kwargs): seen.append((args,kwargs))
        def getresponse(self): return self
        def read1(self,n): return next(self.chunks)
        def close(self): seen.append('closed')
    monkeypatch.setattr(module.http.client,'HTTPConnection',Connection)
    response=LoopbackHealthTransport().handle_request(httpx.Request('GET',
        'http://127.0.0.1:8010/api/health',headers={'x-private':'do-not-forward'}))
    assert response.json()=={'status':'ok'}
    assert seen[-1]=='closed'
    assert 'do-not-forward' not in str(seen)
