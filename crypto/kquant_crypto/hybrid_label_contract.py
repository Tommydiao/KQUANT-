"""Offline M1 label semantics. No data access, training or trade admission."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class LabelRecord:
    economic_signal_id: str
    execution_policy_hash: str
    source: str
    status: str
    net_r: float | None
    signal_time: float
    available_at: float
    execution_quality: str
    dependence_group: str

    def __post_init__(self):
        if not all((self.economic_signal_id, self.execution_policy_hash, self.dependence_group)):
            raise ValueError('Identity, execution policy and dependence group required')
        if self.source not in {'executed_virtual', 'counterfactual', 'termination_liquidation'}:
            raise ValueError('Unknown label population')
        if self.status not in {'mature', 'censored', 'unavailable', 'terminated'}:
            raise ValueError('Unknown label status')
        if self.execution_quality not in {'historical_ohlcv_proxy', 'observed_bbo_virtual', 'synthetic_fixture'}:
            raise ValueError('Explicit execution evidence required')
        times=(self.signal_time,self.available_at)
        if any(isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t) or t<0 for t in times):
            raise ValueError('Finite times required')
        if self.available_at<self.signal_time:
            raise ValueError('Label unavailable at signal creation')
        if self.status in {'censored','unavailable'}:
            if self.net_r is not None:
                raise ValueError('Censored or unavailable outcomes cannot be zero-filled')
        elif isinstance(self.net_r,bool) or not isinstance(self.net_r,(int,float)) or not math.isfinite(self.net_r):
            raise ValueError('Observed net R required')
        if (self.source=='termination_liquidation') != (self.status=='terminated'):
            raise ValueError('Termination is not a mature strategy exit')


def eligible_training_labels(records, *, cutoff, source, execution_policy_hash):
    if isinstance(cutoff,bool) or not isinstance(cutoff,(int,float)) or not math.isfinite(cutoff) or cutoff<0:
        raise ValueError('Finite cutoff required')
    if source not in {'executed_virtual','counterfactual'}:
        raise ValueError('One explicit training population required')
    selected=[r for r in records if r.available_at<=cutoff and r.status=='mature'
              and r.source==source and r.execution_policy_hash==execution_policy_hash
              and r.execution_quality!='synthetic_fixture']
    ids=[r.economic_signal_id for r in selected]
    if len(set(ids))!=len(ids):
        raise ValueError('Duplicate economic opportunity in training population')
    return selected
