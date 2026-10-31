"""Read-only research on observed evidence, never a candidate publisher."""
from datetime import timedelta

from . import options_one_minute as common
from . import options_opening_trend as trend


def observed_minutes(bars, *, symbol, as_of):
    latest = {}
    for row in bars:
        try:
            start = common.timestamp(row['open_at'])
            end = start + timedelta(minutes=1)
            received = common.timestamp(row['received_at'])
            valid = (row.get('symbol') == symbol and row.get('interval') == '1m'
                     and row.get('closed') is True and common.timestamp(row['available_at']) == end
                     and end <= received <= as_of
                     and all(common.finite(row.get(k)) for k in ('open', 'high', 'low', 'close', 'turnover', 'volume'))
                     and 0 < row['low'] <= min(row['open'], row['close'])
                     <= max(row['open'], row['close']) <= row['high']
                     and row['volume'] >= 0 and row['turnover'] >= 0
                     and row.get('turnover_source') == 'NATIVE' and row.get('currency') == 'USD')
            old = latest.get(start)
            if valid and (old is None or received > common.timestamp(old['received_at'])):
                latest[start] = row
        except (KeyError, ValueError, TypeError):
            pass
    return latest


def labels(evaluation, bars, *, report_as_of):
    """Underlying-only labels; OHLC cannot identify the order of intrabar touches."""
    if evaluation.get('state') != 'NUMERIC_PASS':
        return {'status': 'NO_NUMERIC_SETUP', 'option_returns': None}
    start = common.timestamp(evaluation['confirmation_at'])
    entered = evaluation['bar_evidence']['close']
    direction = 1 if evaluation['right'] == 'CALL' else -1
    risk = evaluation['initial_r']
    if not common.finite(risk) or risk <= 0 or not common.finite(entered) or entered <= 0:
        return {'status': 'INVALID_REFERENCE_R', 'option_returns': None}
    planned = common.timestamp(evaluation['planned_exit_at'])
    # The model's decision window and the position's maximum holding time are distinct.
    planned = min(planned, start + timedelta(minutes=evaluation['policy_snapshot']['holding_max_minutes']))
    rows = observed_minutes(bars, symbol=evaluation['symbol'], as_of=common.timestamp(report_as_of))
    results = {}
    for name, requested in [*( (f'{n}m', start + timedelta(minutes=n)) for n in (5, 15, 30, 60)), ('planned_exit', planned)]:
        end = min(requested, planned)
        if end <= start:
            results[name] = {'status': 'NO_FORWARD_WINDOW'}
            continue
        minutes = int((end - start).total_seconds() // 60)
        expected = [start + timedelta(minutes=i) for i in range(minutes)]
        missing = [s.isoformat() for s in expected if s not in rows]
        if missing or not minutes:
            results[name] = {'status': 'OUTCOME_MINUTES_MISSING', 'end_at': end.isoformat(),
                             'missing_minutes': missing, 'truncated': end != requested}
            continue
        future = [rows[s] for s in expected]
        extremes = [direction * (r[k] - entered) for r in future for k in ('high', 'low')]
        ambiguous = [r['open_at'] for r in future
                     if direction * ((r['low'] if direction == 1 else r['high']) - evaluation['structure_line']) <= 0
                     and direction * ((r['high'] if direction == 1 else r['low']) - entered) >= risk]
        five = trend.aggregate(future, 5)
        broken = next((r['available_at'] for r in five
                       if direction * (r['close'] - evaluation['structure_line']) < 0), None)
        results[name] = {'status': 'UNDERLYING_REFERENCE_ONLY', 'end_at': end.isoformat(),
            'truncated': end != requested, 'underlying_return': direction * (future[-1]['close'] - entered) / entered,
            'mfe_r': max(0, max(extremes)) / risk, 'mae_r': min(0, min(extremes)) / risk,
            'structure_break_5m_at': broken, 'intrabar_path_uncertain': ambiguous,
            'last_evidence_received_at': max(future, key=lambda r: common.timestamp(r['received_at']))['received_at'],
            'source_hashes': [common.digest(r) for r in future]}
    return {'status': 'REFERENCE_LABELS_NOT_TRADING_RETURNS', 'reference_price': entered,
            'labels': results, 'option_returns': None,
            'option_return_status': 'REAL_SAME_CONTRACT_HISTORY_AND_FEES_REQUIRED'}


def delay_checks(evaluation, quotes, bars=()):
    result = []
    if evaluation.get('state') != 'NUMERIC_PASS':
        return result
    formed = common.timestamp(evaluation['confirmation_at'])
    for delay in (30, 60, 120, 180, 300):
        stamp = formed + timedelta(seconds=delay)
        known = []
        for quote in quotes:
            try:
                received = common.timestamp(quote['received_at'])
                trade = common.timestamp(quote['quote_time'])
                if (quote.get('symbol') == evaluation['symbol'] and common.finite(quote.get('last'))
                        and quote['last'] > 0 and trade <= received <= stamp
                        and (stamp - received).total_seconds() <= 3):
                    known.append(quote)
            except (KeyError, ValueError, TypeError):
                pass
        if stamp >= common.timestamp(evaluation['deadline_at']):
            state = 'EXPIRED'
        elif not known:
            state = 'OBSERVED_QUOTE_MISSING'
        else:
            latest = max(known, key=lambda q: common.timestamp(q['received_at']))
            from .options_opening_trend_current import current
            context = current(evaluation, list(bars), now=stamp)
            check = trend.current_eligibility(evaluation, quote=latest, now=stamp,
                event_valid=False, contract_valid=False, policy_approved=False, trend_evidence=context)
            state = ('PRICE_INVALIDATED' if check['state'] == 'WITHDRAWN' else
                     'CURRENT_TREND_EVIDENCE_MISSING' if context['state'] == 'INCOMPLETE' else 'PRICE_ONLY_NOT_QUALIFIED')
        result.append({'delay_seconds': delay, 'as_of': stamp.isoformat(), 'state': state,
                       'qualified_signal': False})
    return result


def replay(*, symbol, right, bars, history, references, opening, closing, scope_hash, report_as_of,
           quotes=(), policy=None):
    """Re-evaluate at real observed arrivals without retiming bars or backfill."""
    p = policy or trend.load_policy()
    cutoff = opening + timedelta(minutes=p['entry_window_minutes'])
    stamps = {opening + timedelta(minutes=n, seconds=1) for n in (15, 20, 25)}
    for row in bars:
        try:
            received = common.timestamp(row['received_at'])
            if (opening + timedelta(minutes=15) <= received < cutoff
                    and common.timestamp(row['open_at']) + timedelta(minutes=1) <= received):
                stamps.add(received)
        except (KeyError, ValueError, TypeError):
            pass
    checkpoints, setups = [], {}
    for stamp in sorted(t for t in stamps if t <= common.timestamp(report_as_of)):
        usable_refs = []
        for ref in references:
            try:
                if common.timestamp(ref['received_at']) <= stamp:
                    usable_refs.append(ref)
            except (KeyError, TypeError, ValueError):
                pass
        reference = max(usable_refs, key=lambda r: common.timestamp(r['received_at'])) if usable_refs else {}
        decision = trend.evaluate(symbol=symbol, right=right, bars=bars, history=history, reference=reference,
            opening=opening, closing=closing, now=stamp, scope_hash=scope_hash, policy=p)
        seen = observed_minutes(bars, symbol=symbol, as_of=stamp)
        old_bar = seen.get(opening + timedelta(minutes=int((stamp-opening).total_seconds() // 60) - 1))
        old = None
        if old_bar:
            start = common.timestamp(old_bar['open_at'])
            required = min(5, int((start - opening).total_seconds() // 60))
            prior = [seen.get(start - timedelta(minutes=i)) for i in range(required, 0, -1)]
            old = common.evaluate(symbol=symbol, right=right, bar=old_bar,
                previous=[r for r in prior if r], history=history,
                schedule={'is_trading_day': True, 'regular_open_utc': opening.isoformat(), 'regular_close_utc': closing.isoformat()},
                scope_hash=scope_hash, now=stamp)
        checkpoints.append({'as_of': stamp.isoformat(), 'new_state': decision['state'],
            'new_reasons': decision['reasons'], 'evaluation_hash': common.digest(decision),
            'old_state': old['state'] if old else 'OBSERVED_MINUTE_UNAVAILABLE',
            'old_reasons': old['reasons'] if old else ['POST_CLOSE_MINUTE_EVIDENCE_REQUIRED']})
        if decision['state'] == 'NUMERIC_PASS' and decision['evaluation_id'] not in setups:
            setups[decision['evaluation_id']] = {'evaluation': decision,
                'outcomes': labels(decision, bars, report_as_of=report_as_of),
                'manual_delay': delay_checks(decision, quotes, bars)}
    return {'symbol': symbol, 'right': right, 'policy_hash': p['policy_hash'], 'scope_hash': scope_hash,
            'mode': 'OBSERVED_AS_OF_REPLAY', 'checkpoints': checkpoints, 'setups': list(setups.values()),
            'timestamps_rewritten': 0, 'qualified_signals_published': 0, 'database_writes': 0}
