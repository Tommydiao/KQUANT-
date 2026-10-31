"""One bounded AI lane. It never changes a deterministic event or quote expiry."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock

from . import options_one_minute as common
from .options_research_ai import evidence_packet


def review_delivery(result, captured, current, *, now):
    """Discard stale conclusions rather than attaching them to a revised event."""
    now=common.timestamp(now)
    view={**result,'qualified_signal':False,'current_opportunity':False}
    if result.get('state')!='COMPLETED':
        return {**view,'delivery_state':'MODEL_UNAVAILABLE'}
    if not current or current.get('event_id')!=captured.get('event_id'):
        return {**view,'delivery_state':'EVENT_UNAVAILABLE'}
    if common.digest(evidence_packet(current))!=common.digest(evidence_packet(captured)):
        return {**view,'delivery_state':'INPUT_REVISED'}
    try:
        if now>=common.timestamp(captured['deadline_at']):
            return {**view,'delivery_state':'EXPIRED'}
    except (KeyError,ValueError,TypeError):
        return {**view,'delivery_state':'DEADLINE_UNVERIFIED'}
    if current.get('state')!='NUMERIC_PASS' or current.get('withdrawn'):
        return {**view,'delivery_state':'WITHDRAWN'}
    reference=current.get('reference_contract') or {}
    received=(reference.get('snapshot') or {}).get('bbo_received_at')
    try:
        age=(now-common.timestamp(received)).total_seconds()
        if not 0<=age<=3:
            return {**view,'delivery_state':'QUOTE_STALE','quote_receive_age_seconds':age}
    except (ValueError,TypeError,KeyError):
        return {**view,'delivery_state':'QUOTE_UNVERIFIED'}
    # Existing deterministic qualification owns price/structure checking. A missing
    # fresh check means the AI section is historical only, not a current opportunity.
    check=current.get('live_price_check') or {}
    try:
        age=(now-common.timestamp(check['checked_at'])).total_seconds()
        verified=check.get('state')=='PASS' and 0<=age<=3
    except (KeyError,ValueError,TypeError):
        verified=False
    if not verified:
        return {**view,'delivery_state':'PRICE_RECHECK_REQUIRED'}
    return {**view,'delivery_state':'CURRENT_RESEARCH_REVIEW','current_opportunity':True,
        'quote_receive_age_seconds':(now-common.timestamp(received)).total_seconds()}


class ResearchAILane:
    """Caller supplies committed evidence and persists results in the existing ledger."""
    def __init__(self, client, *, on_result, current_event, clock):
        self.client,self.on_result,self.current_event,self.clock=client,on_result,current_event,clock
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='opening-research-ai')
        self.lock=Lock()
        self.active=None
        self.closed=False
        self.delivering=False
        self.last_error=None

    def submit(self, event, *, role='SOL'):
        captured=deepcopy(event)
        with self.lock:
            if self.closed:
                return 'CLOSED'
            if self.active is not None:
                return 'INFLIGHT' if self.active[0]['event_id']==event['event_id'] else 'DEFERRED_BUSY'
            future=self.executor.submit(self.client.assess,captured,role=role)
            self.active=captured,future
            return 'QUEUED'

    def poll(self):
        with self.lock:
            active=self.active
            if active is None or self.delivering or not active[1].done():
                return None
            self.delivering=True
            # Keep single-inflight ownership through validation and persistence.
        captured,future=active
        try:
            try:
                result=future.result()
            except Exception as exc:
                result={'state':'FAILED','error_code':type(exc).__name__,'qualified_signal':False}
            current=self.current_event(captured['event_id'])
            result=review_delivery(result,captured,current,now=self.clock())
            self.on_result(captured,result)
            self.last_error=None
            return result
        except Exception as exc:
            self.last_error=type(exc).__name__
            return {'state':'DELIVERY_FAILED','error_code':self.last_error,'qualified_signal':False}
        finally:
            with self.lock:
                if self.active is active:
                    self.active=None
                self.delivering=False

    def close(self):
        with self.lock:
            self.closed=True
        self.executor.shutdown(wait=True,cancel_futures=True)
