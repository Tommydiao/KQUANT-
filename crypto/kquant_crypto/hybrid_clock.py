"""Receiver clock calibration only. Never manufactures an exchange event time."""
from dataclasses import asdict, dataclass
import hashlib
import json
import math

POLICY = {
    'version':'hybrid_receiver_clock_dev_v2', 'scope':'ISOLATED_RESEARCH_OBSERVER',
    'monotonic_clock':'perf_counter',
    'probes':5, 'timestamp_unit':'MILLISECOND', 'valid_for_seconds':600,
    'max_interval_width_seconds':1.0, 'drift_ppm':100,
    'local_clock_step_limit_seconds':1.0, 'quote_freshness_seconds':30,
    'changes_system_clock':False, 'fills_missing_source_time':False,
    'automatic_trading':False,
}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def native_ms(value):
    if type(value) is not int or not 1_000_000_000_000 <= value < 10_000_000_000_000:
        raise ValueError('Expected native millisecond Unix timestamp; no unit guessing')
    return value/1000


@dataclass(frozen=True)
class ClockSegment:
    offset_lower:float
    offset_upper:float
    mono_anchor:float
    local_anchor:float
    probes_hash:str
    policy_hash:str

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.offset_lower,self.offset_upper,self.mono_anchor,self.local_anchor)):
            raise ValueError('Finite clock anchors required')
        if not 0<=self.offset_upper-self.offset_lower<=POLICY['max_interval_width_seconds']:
            raise ValueError('Invalid clock interval')

    @property
    def segment_id(self):return digest(asdict(self))

    def bounds(self,monotonic_at,local_at):
        if self.policy_hash!=digest(POLICY):raise ValueError('Clock policy mismatch')
        age=monotonic_at-self.mono_anchor
        if not all(math.isfinite(x) for x in (monotonic_at,local_at,age)) or not 0<=age<=POLICY['valid_for_seconds']:
            raise ValueError('Clock segment expired or monotonic clock changed')
        if abs((local_at-self.local_anchor)-age)>POLICY['local_clock_step_limit_seconds']:
            raise ValueError('Local clock discontinuity: new segment required')
        drift=age*POLICY['drift_ppm']/1e6
        lower=monotonic_at+self.offset_lower-drift
        upper=monotonic_at+self.offset_upper+drift
        if upper-lower>POLICY['max_interval_width_seconds']:
            raise ValueError('Clock uncertainty exceeds observation contract')
        return {'clock_segment_id':self.segment_id,'received_at_local_utc':local_at,
                'received_at_monotonic':monotonic_at,'received_at_lower':lower,'received_at_upper':upper,
                'received_at':upper,'receiver_clock_basis':'SERVER_ALIGNED_MONOTONIC_INTERVAL',
                'source_event_time_modified':False}

    def check_quote(self,source_event_time,receipt):
        if receipt['clock_segment_id']!=self.segment_id:raise ValueError('Wrong observation clock segment')
        if not math.isfinite(source_event_time):return 'invalid_source_event_time'
        if not all(math.isfinite(receipt[k]) for k in ('received_at_lower','received_at_upper')):
            raise ValueError('Nonfinite receiver bounds')
        if receipt['received_at_lower']>receipt['received_at_upper']:
            raise ValueError('Reversed receiver bounds')
        if source_event_time>receipt['received_at_lower']:
            return 'quote_receipt_order_uncertain'
        if receipt['received_at_upper']-source_event_time>POLICY['quote_freshness_seconds']:
            return 'stale_quote'
        return 'qualified_time_interval'


def calibrate(probes):
    if len(probes)!=POLICY['probes']:raise ValueError('Require preregistered number of probes')
    lower=[];upper=[]
    for index,p in enumerate(probes):
        server=native_ms(p['serverTime'])
        m0,m1=p['monotonic_before'],p['monotonic_after']
        l0,l1=p['local_before'],p['local_after']
        if index and (m0<probes[index-1]['monotonic_after'] or p['serverTime']<=probes[index-1]['serverTime']):
            raise ValueError('Out-of-order or repeated cached clock sample')
        if not all(math.isfinite(v) for v in (m0,m1,l0,l1)) or not 0<m1-m0<=5:
            raise ValueError('Invalid clock probe duration')
        if abs((l1-l0)-(m1-m0))>.1:raise ValueError('Clock moved during probe')
        if p.get('age_seconds',0)>0:raise ValueError('Cached server time cannot anchor receiver clock')
        # Server timestamp was generated between send and receive, to 1ms.
        lower.append(server-m1-.001);upper.append(server-m0+.001)
    lo,hi=max(lower),min(upper)
    if not lo<=hi or hi-lo>POLICY['max_interval_width_seconds']:
        raise ValueError('Inconsistent clock probes or excessive uncertainty')
    last=probes[-1]
    return ClockSegment(lo,hi,last['monotonic_after'],last['local_after'],digest(probes),digest(POLICY))
