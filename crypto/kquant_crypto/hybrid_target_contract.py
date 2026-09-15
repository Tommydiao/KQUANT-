"""Research target identities and consumer boundaries, not model admission."""
from enum import Enum


class ResearchTarget(str, Enum):
    POPULATION = 'POPULATION_GROSS_LOG_RETURN_24H'
    ENTRY = 'ENTRY_POLICY_NET_R'
    HOLDING = 'POSITION_STATE_INCREMENTAL_EXIT_VALUE'


CONTRACTS = {
    ResearchTarget.POPULATION: dict(unit='100*log(1+gross_return_24h)',
        probability_name='p_gross_positive', trading_probability=False),
    ResearchTarget.ENTRY: dict(unit='net_pnl/frozen_BASE_initial_risk',
        probability_name='p_policy_net_r_positive', trading_probability=False),
    ResearchTarget.HOLDING: dict(unit='(continue_value-next_legal_exit_value)/frozen_BASE_initial_risk',
        probability_name='p_incremental_exit_value_positive', trading_probability=False),
}


def require_research_target(actual, expected, consumer):
    actual, expected = ResearchTarget(actual), ResearchTarget(expected)
    if actual != expected:
        raise ValueError('Research target mismatch')
    if consumer not in ('offline_diagnostic', 'retrospective_abstention_audit'):
        raise ValueError('No runtime, sizing or execution consumer admission')
    return dict(CONTRACTS[actual], target_id=actual.value, scope='DEV_ONLY')


def holding_identity(row, trade):
    if row['trade_id'] != trade['trade_id'] or row['symbol'] != trade['symbol']:
        raise ValueError('Holding parent trade mismatch')
    if row['execution_policy_id'] != trade['policy_hash']:
        raise ValueError('Holding execution policy mismatch')
    if not trade['entry_time'] <= row['as_of'] < trade['exit_time'] <= row['label_available_at']:
        raise ValueError('Holding information chronology mismatch')
    if row['available_at'] > row['as_of']:
        raise ValueError('Features unavailable at snapshot')
    allowed = {'age_seconds','base_unit_net_risk','mark_to_entry_r'}
    if set(row['holding_features']) != allowed:
        raise ValueError('Unknown or future holding feature')
    if row['holding_features']['base_unit_net_risk'] != trade['base_unit_net_risk']:
        raise ValueError('BASE denominator mismatch')
    return dict(economic_key=[trade['symbol'],trade['mode'],trade['signal_time']],
        parent_trade_id=trade['trade_id'], policy_id=row['execution_policy_id'],
        snapshot_time=row['as_of'], information_start=trade['signal_time'],
        information_end=row['label_available_at'], target_id=ResearchTarget.HOLDING.value,
        source='COUNTERFACTUAL_EXIT_COMPARISON_ON_ACTUAL_VIRTUAL_HOLDING', training_enabled=False)


def interval_components(groups):
    """Conservative touching intervals share a component, not an OOS fold."""
    ordered=sorted(groups,key=lambda r:(r['information_start'],r['information_end'],r['economic_key']))
    components=[]
    for row in ordered:
        start,end=row['information_start'],row['information_end']
        if end < start:raise ValueError('Invalid group interval')
        if not components or start > components[-1]['information_end']:
            components.append(dict(information_start=start,information_end=end,economic_keys=[row['economic_key']]))
        else:
            component=components[-1]
            component['information_end']=max(component['information_end'],end)
            component['economic_keys'].append(row['economic_key'])
    return components
