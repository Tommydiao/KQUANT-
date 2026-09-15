"""Isolated OHLC risk-path adapter reusing the unchanged candidate portfolio."""
from copy import deepcopy
import math

from .candidate_policy import digest
from .candidate_simulation import CandidatePortfolio
from .strategy_dual_mode_v1 import Bar
from .hybrid_mc_numerics_v12 import path_risk


class ExistingExposurePortfolio(CandidatePortfolio):
    def _clock(self, time, *, force=False):
        previous = self.day_start
        previous_day = self.day
        super()._clock(time, force=force)
        if previous_day is not None and previous_day != self.day:
            if not hasattr(self, '_mc_day_resets'):
                self._mc_day_resets = []
            self._mc_day_resets.append(dict(time=time, previous_day=previous_day,
                new_day=self.day, previous_baseline=previous, new_baseline=self.day_start,
                source='CandidatePortfolio._clock(day_change)'))
        if force:
            if not hasattr(self, '_mc_opening_resets'):
                self._mc_opening_resets = []
            self._mc_opening_resets.append(dict(time=time, previous_baseline=previous,
                new_baseline=self.day_start, source='CandidatePortfolio._clock(force=True)'))

    def _reserve(self, symbol, signal, time):
        # Keep admitted pending from the restored snapshot; reject only NEW proposals.
        self.event('MC_NEW_PROPOSAL_SUPPRESSED', time, symbol)


def risk_budget_audit(portfolio, as_of, historical_high_watermark):
    """Describe the original reserve budget; never authorize or resize exposure."""
    equity = portfolio.value()
    groups = {}
    for name in ('positions', 'pending'):
        exposures = getattr(portfolio, name).values()
        groups[name] = {
            'base_r_amount': sum(e['risk_amount'] for e in exposures),
            'sizing_risk_amount': sum(e.get('estimated_risk_amount', e['risk_amount'])
                                      for e in getattr(portfolio, name).values()),
        }
    used = sum(g['sizing_risk_amount'] for g in groups.values())
    cap = equity * portfolio.policy['max_open_risk']
    reserved = sum(e['reserved_cash'] for e in portfolio.pending.values())
    daily_line = portfolio.day_start * (1 - portfolio.policy['daily_loss_limit'])
    return {
        'scope': 'DEV_ONLY_ORIGINAL_BUDGET_AUDIT', 'equity': equity,
        'cash': portfolio.cash, 'pending_cash_reserved': reserved,
        'cash_unreserved': portfolio.cash - reserved, 'exposure': groups,
        'open_risk_cap': cap, 'sizing_risk_used': used,
        'open_risk_remaining_signed': cap - used,
        'single_trade_risk_cap': equity * portfolio.policy['risk_per_trade'],
        'day_start_equity': portfolio.day_start, 'day_id': portfolio.day,
        'daily_loss_line': daily_line, 'daily_headroom_signed': equity - daily_line,
        'historical_high_watermark': historical_high_watermark,
        'day_paused': portfolio.day_paused,
        'streak_pause_active': as_of < portfolio.pause_until,
        'remaining_position_slots': max(0, portfolio.policy['max_positions']
                                        - len(portfolio.positions) - len(portfolio.pending)),
        'entry_permission': False,
        'limitation': 'Budget headroom is not executable quantity or maximum possible loss; gaps can exceed BASE R',
    }


def evaluate_path(policy, rules, state, batches, *, as_of, historical_high_watermark,
                  hour_prefix=None, future_cost_multiplier=None, include_terminal_state=True):
    """No network/storage, no live consumer and no terminal liquidation invention.

    All admission, entry, BASE risk, gap/stop/target, expiry, regime exit and day
    handling is inherited. Costed closing marks are not simultaneous intra-bar
    liquidation quotes. Volume=0 is only an unused field in the frozen price-only
    regime contract, not order-flow evidence. No future entry is admitted.
    """
    if type(as_of) is not int or as_of % 300 or not batches:
        raise ValueError('Closed five-minute boundary and nonempty path required')
    if state['execution'] != 'ohlcv':
        raise ValueError('OHLC paths cannot impersonate quote execution')
    symbols = tuple(policy['symbols'])
    def finite(value, positive=True):
        return type(value) in (int, float) and math.isfinite(value) and (value > 0 if positive else value >= 0)
    if set(state['marks']) != set(symbols) or set(state['kernels']) != set(symbols):
        raise ValueError('Complete mark and kernel coverage required')
    if not all(finite(v) for v in state['marks'].values()) or not finite(state['cash'], False):
        raise ValueError('No missing mark fallback or invalid cash allowed')
    if set(state['positions']) & set(state['pending']) or not (set(state['positions']) | set(state['pending'])) <= set(symbols):
        raise ValueError('Invalid exposure identity')
    ids = set()
    for kind in ('positions', 'pending'):
        for symbol, exposure in state[kind].items():
            if exposure['symbol'] != symbol or exposure['trade_id'] in ids:
                raise ValueError('Duplicate or mismatched exposure identity')
            ids.add(exposure['trade_id'])
            for key in ('quantity', 'unit_net_risk', 'risk_amount', 'stop', 'target', 'sizing_unit_risk', 'estimated_risk_amount'):
                if not finite(exposure[key]):
                    raise ValueError('Invalid exposure amount or protection')
            if exposure['stop'] >= exposure['target'] or not math.isclose(
                    exposure['risk_amount'], exposure['quantity'] * exposure['unit_net_risk'], rel_tol=1e-12, abs_tol=1e-8):
                raise ValueError('Frozen BASE risk or protection mismatch')
            if kind == 'pending':
                if (not finite(exposure['signal_time'], False) or not finite(exposure['available_at'], False)
                        or not exposure['signal_time'] <= exposure['available_at'] <= as_of):
                    raise ValueError('Future or invalid pending availability')
                if not finite(exposure['reserved_cash']):
                    raise ValueError('Invalid pending reservation')
            elif (not finite(exposure['entry_time'], False) or exposure['entry_time'] > as_of
                  or not finite(exposure['entry_price']) or not finite(exposure['entry_fee'], False)):
                raise ValueError('Invalid existing fill')
    if sum(e['reserved_cash'] for e in state['pending'].values()) > state['cash'] + 1e-8:
        raise ValueError('Pending reservations exceed current cash')
    if any(state['last_bars'].get(s) != as_of - 300 for s in symbols):
        raise ValueError('Frozen portfolio and path must share one closed boundary')
    if state['day'] != as_of // 86400:
        raise ValueError('Original risk-day state required; no budget reset')
    p = ExistingExposurePortfolio(deepcopy(policy), deepcopy(rules),
                                 cost_multiplier=state['cost_multiplier'], only_mode=state['only_mode'])
    if set(state) != set(p.snapshot()):
        raise ValueError('Only the original candidate snapshot schema is allowed')
    # from_dict already detaches each kernel; restore aliases other fields.
    detached = {k: (v if k == 'kernels' else deepcopy(v)) for k, v in state.items()}
    p.restore(detached)
    initial = p.value()
    initial_budget = risk_budget_audit(p, as_of, historical_high_watermark)
    future_cost = state['cost_multiplier'] if future_cost_multiplier is None else future_cost_multiplier
    if type(future_cost) is not int or future_cost not in (1, 2) or future_cost < state['cost_multiplier']:
        raise ValueError('Future stress cannot lower costs or exceed the registered double-cost scenario')
    # Paid costs stay in restored positions; only subsequent entry/exit charges change.
    p.cost_multiplier = future_cost
    identity = digest(state)
    prefix = deepcopy(hour_prefix or {s: [] for s in symbols})
    count = (as_of % 3600) // 300
    if set(prefix) != set(symbols):
        raise ValueError('Explicit synchronized hourly prefix required')
    for symbol, parts in prefix.items():
        if len(parts) != count or any(b.start != as_of - count * 300 + i * 300 for i, b in enumerate(parts)):
            raise ValueError('Missing or future hourly prefix; cannot fabricate confirmation')
        if parts and parts[-1].close != p.marks[symbol]:
            raise ValueError('Hourly prefix and current mark conflict')
    curve = [dict(time=as_of, equity=initial, risk_day_id=p.day,
                  day_start_equity=p.day_start, daily_loss_limit=policy['daily_loss_limit'])]
    for index, batch in enumerate(batches):
        start = as_of + index * 300
        if batch['start'] != start or set(batch['bars']) != set(symbols):
            raise ValueError('Incomplete, duplicated or out-of-order joint path')
        bars = {s: Bar(start, **{k: float(batch['bars'][s][k]) for k in ('open', 'high', 'low', 'close')})
                for s in symbols}
        hourly = {}
        for s, b in bars.items():
            prefix[s].append(b)
            if (start + 300) % 3600 == 0:
                parts = prefix[s]
                if len(parts) != 12:
                    raise ValueError('Incomplete hour in simulated path')
                hourly[s] = Bar(parts[0].start, parts[0].open, max(x.high for x in parts),
                                min(x.low for x in parts), parts[-1].close)
                prefix[s] = []
        # False would cancel existing pending: suppression is only at _reserve.
        p.on_closed_batch(bars, hourly, start + 300, allow_entries=True)
        curve.append(dict(time=start + 300, equity=p.value(), risk_day_id=p.day,
                          day_start_equity=p.day_start, daily_loss_limit=policy['daily_loss_limit']))
    if digest(state) != identity:
        raise ValueError('Original portfolio snapshot mutated')
    resets = getattr(p, '_mc_opening_resets', [])
    risk = path_risk(curve, initial_equity=initial, historical_high_watermark=historical_high_watermark,
                     opening_resets=resets, day_resets=getattr(p, '_mc_day_resets', []))
    # Closing marks alone can miss an original intra-bar/previous-day loss pause.
    risk['daily_loss_line_breached'] |= bool(state['day_paused']) or any(
        e['kind'] == 'DAILY_LOSS_PAUSE' for e in p.events)
    return {'scope': 'DEV_ONLY_OHLC_RISK_PATH', 'initial_snapshot_hash': identity,
            'curve': curve, 'risk': risk, 'original_opening_resets': resets,
            'original_day_resets': getattr(p, '_mc_day_resets', []),
            'trades': p.trades, 'events': p.events,
            'terminal_state': p.snapshot() if include_terminal_state else None,
            'terminal_state_included': include_terminal_state,
            'remaining_positions': len(p.positions), 'remaining_pending': len(p.pending),
            'initial_reference_equity': initial, 'prior_cost_multiplier': state['cost_multiplier'],
            'initial_risk_budget': initial_budget,
            'future_cost_multiplier': future_cost, 'paid_entry_costs_rewritten': False,
            'cost_scope': 'FUTURE_ONLY_FROM_FROZEN_SNAPSHOT',
            'terminal_liquidation_forced': False, 'sizing_enabled': False, 'G4_passed': False,
            'admission': 'ABSTAIN', 'source_type': 'BOOTSTRAP_OHLC_PROXY',
            'limitations': ['No intra-bar simultaneous portfolio valuation',
                            'No executable bid/ask or size evidence',
                            'No new proposal sizing selection or market calibration']}
