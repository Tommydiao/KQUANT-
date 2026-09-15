import json
import httpx
import pytest
from kquant_crypto.hybrid_local_health_probe import probe, URL


@pytest.mark.parametrize('code,body,state', [(200,b'{"status":"ok","secret":"DO_NOT_COPY"}','OK'),
    (302,b'','FAILED'), (401,b'','FAILED'), (200,b'{','UNKNOWN'),
    (200,b'x'*65537,'UNKNOWN'), (200,b'[]','UNKNOWN')],
    ids=['ok','redirect','unauthorized','invalid-json','oversize','wrong-shape'])
def test_bounded_probe(code,body,state):
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(code,content=body,headers={'location':'https://example.com'})
    result=probe(transport=httpx.MockTransport(handler))
    assert len(requests)==1 and str(requests[0].url)==URL
    assert 'authorization' not in requests[0].headers
    assert result['observations']['process']['state']==state
    assert 'DO_NOT_COPY' not in json.dumps(result)
    assert set(result['observations'])=={'process'}
    assert not result['execution_authorized']


def test_error_is_redacted():
    def handler(request):
        raise httpx.ConnectError('PRIVATE_DETAIL',request=request)
    result=probe(transport=httpx.MockTransport(handler))
    assert result['reason']=='LOCAL_HEALTH_UNREACHABLE'
    assert 'PRIVATE_DETAIL' not in json.dumps(result)


@pytest.mark.parametrize('enabled,status,expected', [(False,'disabled','WAITING'),
    (True,'clock_skew','FAILED'), (True,'live',None)])
def test_provider_status_never_asserts_market_freshness(enabled,status,expected):
    def handler(request):
        return httpx.Response(200,json={'status':'ok','providers':{'binance':{
            'enabled':enabled,'status':status,'last_error':'DO_NOT_COPY'}}})
    result=probe(transport=httpx.MockTransport(handler))
    assert result['observations'].get('data',{}).get('state')==expected
    assert 'DO_NOT_COPY' not in json.dumps(result)
    assert result['provider_scope']=='API_RUNTIME_ONLY_NOT_INDEPENDENT_COLLECTORS'


def test_budget_excess_has_distinct_diagnostic(monkeypatch):
    from types import SimpleNamespace
    import kquant_crypto.hybrid_local_health_probe as module
    clock=iter([0.,1.,2.,4.,5.])
    monkeypatch.setattr(module,'time',SimpleNamespace(monotonic=lambda:next(clock),time=lambda:100))
    result=module.probe(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'status':'ok'})))
    assert result['reason']=='LOCAL_PROBE_BUDGET_EXCEEDED'
    assert result['phase_timings']=={'client_ready_seconds':1.,'headers_seconds':2.}
    assert result['observations']['process']['state']=='UNKNOWN'


def test_slow_initialization_does_not_send_request(monkeypatch):
    from types import SimpleNamespace
    import kquant_crypto.hybrid_local_health_probe as module
    clock=iter([0.,4.,4.1])
    monkeypatch.setattr(module,'time',SimpleNamespace(monotonic=lambda:next(clock),time=lambda:100))
    def forbidden(request):
        pytest.fail('Budget already exhausted')
    result=module.probe(transport=httpx.MockTransport(forbidden))
    assert result['http_status'] is None
    assert result['reason']=='LOCAL_PROBE_BUDGET_EXCEEDED'
