from datetime import UTC,date,datetime
from types import SimpleNamespace
from urllib.parse import parse_qs,urlparse

from kquant import options_price_action_source as actions


def test_documented_http_snapshot_preserves_actual_arguments_without_fake_dates(monkeypatch):
    import longbridge.openapi as sdk
    sent=[]
    class Http:
        def request(self,method,path):
            sent.append((method,path))
            return {'items':[]}
    monkeypatch.setattr(sdk,'HttpClient',Http)
    raw,interface,query=actions.request_actions(SimpleNamespace(_context=lambda:Http()),'FCX','2026-10-12','2026-10-13')
    method,path=sent[0]
    assert method=='get' and urlparse(path).path=='/v1/quote/company-act'
    assert parse_qs(urlparse(path).query)=={'symbol':['FCX.US'],'req_type':['1'],'version':['3']}
    assert 'start_date' not in query and 'end_date' not in query
    now=datetime(2026,10,13,12,tzinfo=UTC)
    row=actions.observe(raw,symbol='FCX',requested_at=now,received_at=now,
        target_session=date(2026,10,13),interface=interface,query=query)
    assert not row['complete']
    assert 'COMPANY_ACTION_WINDOW_AND_COMPLETENESS_UNCONFIRMED' in row['reasons']


def test_same_interface_success_does_not_fabricate_coverage(monkeypatch,tmp_path):
    test_documented_http_snapshot_preserves_actual_arguments_without_fake_dates(monkeypatch)
    now=datetime(2026,10,13,12,tzinfo=UTC)
    row=actions.observe({'items':[]},symbol='FCX',requested_at=now,received_at=now,
        target_session=date(2026,10,13),query={'symbol':'FCX.US','req_type':'1','version':'3'})
    fact=actions.coverage_fact(row,method=None,now=now,root=tmp_path)
    assert fact['status']=='INCOMPLETE' and fact['price_scale_state']=='UNKNOWN'
    assert not fact['complete'] and not fact['owner_approval']
