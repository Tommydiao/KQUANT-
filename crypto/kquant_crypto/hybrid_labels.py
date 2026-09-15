"""Labels from unchanged virtual ledger; never invent counterfactual trades."""

import math

from .candidate_policy import digest
from .hybrid_label_contract import LabelRecord

LABEL_SCHEMA={
    'version':'hybrid_labels_v1.0-m2','source_policy':'actual_executed_virtual_only',
    'reference_quantity_policy':'actual_filled_quantity_from_frozen_baseline_ledger',
    'execution_policy':'LEGACY_BAR_PROXY_BASE_10_5',
    'net_r':'net_pnl/(actual_filled_quantity*signal_time_BASE_unit_net_risk)',
    'selection_bias':'portfolio cash, original cooldown, risk and quantity filters condition this population',
    'mature_population_not_all_candidates':True,
    'training_enabled':False,
}


def from_opportunity(opportunity, trade, *, cutoff):
    status='unavailable'; net_r=None; reason='not_executed_in_baseline'; source='executed_virtual'
    available=cutoff
    if trade:
        if trade['exit_time']>cutoff:
            status='censored'; reason='exit_after_cutoff'
        elif trade.get('path_unverifiable') or trade['exit_reason']=='data_gap':
            status='censored'; reason='missing_path'
        elif trade['exit_reason']=='terminal_liquidation':
            status='terminated'; source='termination_liquidation'; net_r=trade['net_r']; reason='end_of_run_liquidation'
        else:
            status='mature'; net_r=trade['net_r']; reason=trade['exit_reason']
            denominator=trade['quantity']*trade['unit_net_risk']
            if not math.isfinite(denominator) or denominator<=0 or not math.isfinite(net_r):
                raise ValueError('Invalid frozen BASE risk denominator')
            if not math.isclose(net_r,trade['net_pnl']/denominator,rel_tol=1e-12,abs_tol=1e-12):
                raise ValueError('Label net R does not match original BASE denominator')
        available=min(cutoff,trade['exit_time'])
    value=LabelRecord(opportunity['economic_signal_id'],digest(LABEL_SCHEMA),'executed_virtual' if source=='executed_virtual' else source,
                      status,net_r,opportunity['signal_time'],available,'historical_ohlcv_proxy',
                      'utc_day:'+str(opportunity['signal_time']//86400))
    row={**vars(value),'reason':reason,'symbol':opportunity['symbol'],'mode':opportunity['mode'],
         'feature_snapshot_hash':opportunity['snapshot_hash'],'label_schema_hash':digest(LABEL_SCHEMA),
         'information_start':opportunity['signal_time'],'information_end':available,
         'training_enabled':False}
    if trade and trade['exit_time']<=cutoff:
        row['executed_trade']={k:trade[k] for k in ('trade_id','entry_time','exit_time','quantity','entry_price',
             'exit_price','fees','net_pnl','risk_amount','unit_net_risk','exit_reason')}
    row['label_hash']=digest(row)
    return row


def delayed_open_assessment(signal_time, *, completed_at, expires_at, next_open):
    """No price access: availability decision cannot inspect next-bar returns."""
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x<0
           for x in (signal_time,completed_at,expires_at,next_open)):
        raise ValueError('Finite logical clock required')
    if completed_at<signal_time or expires_at<=signal_time or next_open<signal_time:
        raise ValueError('Invalid logical clock')
    if completed_at>=expires_at:
        return {'status':'unavailable','reason':'decision_expired','net_r':None}
    if not completed_at<next_open<=expires_at:
        return {'status':'unavailable','reason':'no_post_commit_open_before_expiry','net_r':None}
    return {'status':'timing_only','reason':'needs_shared_protection_and_fill_validation','net_r':None}
