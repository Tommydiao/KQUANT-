from copy import deepcopy
import pytest

from kquant_crypto.hybrid_clock import POLICY,calibrate,native_ms


def samples():
    epoch=1_788_600_000
    return [{'monotonic_before':100+i,'monotonic_after':100.2+i,
             'local_before':epoch-320+i,'local_after':epoch-319.8+i,
             'serverTime':int((epoch+.1+i)*1000),'age_seconds':0} for i in range(5)]


def test_320_second_offset_maps_receiver_never_native_event():
    segment=calibrate(samples())
    receipt=segment.bounds(110,1_788_599_690)
    assert receipt['received_at_local_utc']==1_788_599_690
    assert receipt['received_at_lower']<1_788_600_010<receipt['received_at_upper']
    source=1_788_600_009.5
    assert segment.check_quote(source,receipt)=='qualified_time_interval'
    assert source==1_788_600_009.5


@pytest.mark.parametrize('value',[1788600000,1788600000000000,'1788600000000',True])
def test_no_second_microsecond_or_string_guessing(value):
    with pytest.raises(ValueError):native_ms(value)


def test_native_millisecond_conversion():
    assert native_ms(1788600000123)==1788600000.123


def test_uncertain_order_not_relaxed_as_fresh():
    s=calibrate(samples());r=s.bounds(110,1_788_599_690)
    assert s.check_quote((r['received_at_lower']+r['received_at_upper'])/2,r)=='quote_receipt_order_uncertain'
    assert s.check_quote(r['received_at_upper']-30.01,r)=='stale_quote'
    assert POLICY['quote_freshness_seconds']==30


@pytest.mark.parametrize('change',[{'age_seconds':10},{'serverTime':1788600400000}])
def test_cache_and_inconsistent_offset_rejected(change):
    p=samples();p[2].update(change)
    with pytest.raises(ValueError):calibrate(p)


def test_clock_step_or_expired_segment_requires_new_segment():
    s=calibrate(samples())
    with pytest.raises(ValueError):s.bounds(110,1_788_599_692)
    with pytest.raises(ValueError):s.bounds(1000,1_788_600_580)
    with pytest.raises(ValueError):s.bounds(100,1_788_599_680)


def test_repeated_server_response_not_anchor():
    p=samples();p[1]['serverTime']=p[0]['serverTime']
    with pytest.raises(ValueError):calibrate(p)


def test_probe_does_not_mutate_raw_evidence():
    p=samples();before=deepcopy(p);s=calibrate(p)
    assert p==before and s.probes_hash


@pytest.mark.parametrize('source',[float('nan'),float('inf'),float('-inf')])
def test_nonfinite_source_time_rejected(source):
    s=calibrate(samples());r=s.bounds(110,1_788_599_690)
    assert s.check_quote(source,r)=='invalid_source_event_time'


def test_wrong_segment_and_reversed_receipt_rejected():
    s=calibrate(samples());r=s.bounds(110,1_788_599_690)
    with pytest.raises(ValueError):s.check_quote(1788600000,r|{'clock_segment_id':'old'})
    with pytest.raises(ValueError):s.check_quote(1788600000,r|{'received_at_lower':r['received_at_upper']+1})
