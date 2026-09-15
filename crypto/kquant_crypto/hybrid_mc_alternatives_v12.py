"""Prepare the registered research size alternatives; never select or execute one."""
from copy import deepcopy
import math

from .candidate_policy import digest
from .candidate_simulation import CandidatePortfolio
from .strategy_dual_mode_v1 import expected_net_values

MULTIPLIERS = (0, .25, .5, 1)


def prepare_alternatives(policy, rules, state, symbol, *, as_of):
    if symbol not in policy['symbols'] or state['execution'] != 'ohlcv':
        raise ValueError('Registered Spot OHLC research proposal required')
    decision = state['decisions'].get(symbol, {})
    signal = decision.get('signal')
    if (not signal or signal['signal_time'] != as_of or decision['available_at'] != as_of
            or decision['bar_close'] != as_of or state['last_bars'].get(symbol) != as_of - 300):
        raise ValueError('Proposal must be the frozen currently available technical decision')
    profit, risk = expected_net_values(signal['entry_reference'], signal['stop'], signal['target'])
    if (not 0 < signal['stop'] < signal['entry_reference'] < signal['target'] or risk <= 0
            or not math.isclose(signal['unit_net_risk'], risk, rel_tol=1e-12)
            or not math.isclose(signal['expected_net_rr'], profit / risk, rel_tol=1e-12)):
        raise ValueError('Proposal BASE calculation mismatch')
    p = CandidatePortfolio(deepcopy(policy), deepcopy(rules), cost_multiplier=state['cost_multiplier'],
                           only_mode=state['only_mode'])
    p.restore(deepcopy(state))
    original = digest(state)
    already = symbol in p.positions or symbol in p.pending
    p._reserve(symbol, deepcopy(signal), as_of)
    admitted = None if already else p.pending.get(symbol)
    alternatives = []
    for multiplier in MULTIPLIERS:
        trial = deepcopy(state)
        quantity = 0.0
        status = 'EXISTING_RISK_ONLY' if multiplier == 0 else 'SKIP_ORIGINAL_HARD_RULE'
        if multiplier and admitted:
            quantity = p._round_quantity(symbol, admitted['quantity'] * multiplier)
            rule = rules[symbol]
            if quantity < rule['min_qty'] or quantity * signal['entry_reference'] < rule['min_notional']:
                status = 'SKIP_MINIMUM_ORDER'
                quantity = 0.0
            else:
                pending = deepcopy(admitted)
                ratio = quantity / admitted['quantity']
                pending.update(quantity=quantity, risk_amount=quantity * pending['unit_net_risk'],
                               estimated_risk_amount=quantity * pending['sizing_unit_risk'],
                               reserved_cash=admitted['reserved_cash'] * ratio)
                trial['pending'][symbol] = pending
                status = 'DEV_ALTERNATIVE_NOT_ADMITTED'
        alternatives.append({'multiplier': multiplier, 'status': status, 'quantity': quantity,
                             'state': trial, 'state_hash': digest(trial), 'selected': False})
    if digest(state) != original:
        raise ValueError('Original snapshot changed')
    return {'scope': 'DEV_ONLY_SIZE_INPUTS', 'proposal_hash': digest(signal),
            'original_state_hash': original, 'alternatives': alternatives,
            'original_rule_events': p.events, 'selected': None, 'sizing_enabled': False,
            'execution_enabled': False, 'G4_passed': False,
            'warning': 'm=0 retains all existing risk and is not new-entry permission'}
