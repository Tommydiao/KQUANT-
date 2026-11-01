"""Pure shared packet identity; read projections do not import paid execution."""
from . import options_one_minute as common

MODELS={'SOL':'gpt-6.1-sol','ASTRA':'gpt-6-astra'}


def economic_identity(event):
    return event.get('economic_opportunity_id') or event['event_id']


def technical_identity(event):
    """Native research identity excludes later quotes, contracts and cost refreshes."""
    return common.digest([event.get('evaluation_id'), event.get('runtime_inputs'),
        event.get('input_revision'), event.get('bar_evidence'), event.get('policy_hash')])


def fields(value,names):
    if not isinstance(value,dict):
        return None
    result={}
    for name in names:
        v=value.get(name)
        if v is None or type(v) is bool or common.finite(v):
            result[name]=v
        elif isinstance(v,str) and len(v)<=160 and not any(x in v.lower() for x in ('bearer ','sk-proj-','sk-svcacct-')):
            result[name]=v
    return result


def _asof_snapshot(value, *, asof, names, time_names, horizon=None):
    if not isinstance(value, dict) or asof is None:
        return {'state': 'UNAVAILABLE', 'reason': 'ASOF_OR_SNAPSHOT_MISSING'}
    try:
        known = next(value[name] for name in time_names if value.get(name))
        if common.timestamp(known) > common.timestamp(asof):
            return {'state': 'UNAVAILABLE', 'reason': 'FUTURE_EVIDENCE_EXCLUDED'}
        if horizon and (not value.get(horizon) or common.timestamp(value[horizon]) > common.timestamp(asof)):
            return {'state': 'UNAVAILABLE', 'reason': 'FOLLOWUP_NOT_YET_AVAILABLE'}
    except (StopIteration, KeyError, ValueError, TypeError):
        return {'state': 'UNAVAILABLE', 'reason': 'EVIDENCE_TIME_UNVERIFIED'}
    return {'state': 'ASOF_SNAPSHOT', 'known_at': known, 'asof': asof,
            'metrics': fields(value, names)}


def evidence_packet(event, *, extended=False):
    packet=fields(event,('event_id','evaluation_id','symbol','right','session','calculation_bar_end',
        'deadline_at','state','structure_line','input_revision','variant','policy_id','policy_hash'))
    packet['bar_evidence']=fields(event.get('bar_evidence'),('open','high','low','close','volume',
        'start','end','bar_start','bar_end','source_hash','open_at','available_at'))
    hashes=(event.get('bar_evidence') or {}).get('source_hashes')
    if isinstance(hashes,list) and len(hashes)<=60 and all(isinstance(v,str) and
            len(v)==64 and all(c in '0123456789abcdef' for c in v.lower()) for v in hashes):
        packet['bar_evidence']['source_hashes']=list(hashes)
    factors=event.get('factor_evidence') or {}
    packet['factor_evidence']=fields(factors,('state','momentum','close_position','day_open',
        'previous_close','price','prior_boundary'))
    packet['factor_evidence']['checks']=fields(factors.get('checks'),('momentum','close_position',
        'session_direction','previous_close_direction','prior_breakout'))
    packet['runtime_inputs']=fields(event.get('runtime_inputs'),('input_generation','data_generation',
        'source_version','method_hash','clock_epoch'))
    contract=event.get('reference_contract') or {}
    packet['reference_contract']=fields(contract,('contract_id','symbol','underlying','right',
        'expiry_date','strike','strike_price','dte','delta','bid','ask','quote_currency',
        'contract_multiplier','standard','deliverable','asset_type','state'))
    packet['reference_contract']['snapshot']=fields(contract.get('snapshot'),('bbo_received_at',
        'calc_received_at','source_timestamp','underlying_price','bbo_source_time'))
    packet['option_cost']=fields(event.get('option_cost'),('state','cost','currency','multiplier',
        'premium_per_unit','premium_per_contract','round_trip_cost_per_unit','round_trip_cost_per_contract',
        'spread_pct','spread','fees','slippage','basis','reference_price','premium_cash_reference',
        'spread_cash_reference','spread_equivalent_underlying_move','cost_equivalent_underlying_move',
        'spread_pct_ask','spread_pct_mid','quote_received_at','source_freshness','interpretation'))
    packet['amplitude']=fields(event.get('amplitude'),('range','range_pct','body','body_pct','M','Q',
        'distance_to_breakout','distance_to_structure','range_bps','body_bps',
        'same_slot_support','atr_support','range_vs_prior_atr','range_vs_same_slot_median'))
    packet['event_coverage']=fields(event.get('event_coverage'),('decision','state','observed_at',
        'valid_until','source_hash','coverage_hash'))
    entry=event.get('entry_range')
    if isinstance(entry,(list,tuple)) and len(entry)==2 and all(common.finite(v) for v in entry):
        packet['entry_range']=list(entry)
    packet['source_refs']={name:common.digest(packet[name]) for name in
        ('bar_evidence','factor_evidence','amplitude','reference_contract','option_cost','event_coverage') if name in packet}
    if extended:
        asof = event.get('_evidence_asof') or event.get('evaluated_at')
        try:
            asof = common.timestamp(asof).isoformat() if asof else None
        except (ValueError, TypeError):
            asof = None
        packet['evidence_asof'] = asof
        packet['local_event_materials'] = _asof_snapshot(event.get('event_coverage'), asof=asof,
            names=('decision', 'state', 'observed_at', 'valid_until', 'source_hash', 'coverage_hash'),
            time_names=('observed_at',))
        if packet['local_event_materials']['state'] == 'UNAVAILABLE':
            packet['event_coverage'] = dict(packet['local_event_materials'])
            packet['source_refs']['event_coverage'] = common.digest(packet['event_coverage'])
        packet['saved_followup_path'] = _asof_snapshot(event.get('outcome'), asof=asof,
            names=('state', 'known_at', 'measured_at', 'reaction_at', 'horizon_end_at',
                   'y60_pct', 'source_hash', 'basis'),
            time_names=('known_at', 'measured_at'), horizon='horizon_end_at')
        for name in ('local_event_materials', 'saved_followup_path'):
            packet['source_refs'][name] = common.digest(packet[name])
    packet['research_only']=True
    packet['qualified_signal']=False
    return packet


def evidence_catalog(event, *, extended=False):
    packet=evidence_packet(event, extended=extended)
    catalog=[]
    for name,identity in packet['source_refs'].items():
        value=packet.get(name) or {}
        metric_source = value.get('metrics', value)
        metrics={k:v for k,v in metric_source.items() if v is None or isinstance(v,(str,int,float,bool))}
        catalog.append(dict(name=name,hash=identity,
            observed_at=value.get('known_at') or value.get('observed_at') or value.get('available_at') or
                value.get('quote_received_at') or packet.get('calculation_bar_end'),
            timestamp_basis='FIELD_TIME_OR_CALCULATION_CHECKPOINT_NOT_NEW_RECEIPT',
            metrics=dict(list(metrics.items())[:10])))
    return catalog
