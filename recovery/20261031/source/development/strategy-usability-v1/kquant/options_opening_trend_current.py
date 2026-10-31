"""Current, as-of minute trend evidence; never reuse the trigger's frozen VWAP."""
from contextlib import closing
from datetime import date, timedelta
import json
import sqlite3
from time import monotonic

from . import options_one_minute as common
from . import options_opening_trend as trend
from .market_clock import session_bounds_utc


def current(evaluation, bars, *, now, source_decisions=None):
    now = common.timestamp(now)
    opening, closing = session_bounds_utc(date.fromisoformat(evaluation['session']))
    until = min(opening + timedelta(minutes=int((now-opening).total_seconds()//60)), closing)
    result = {'symbol': evaluation['symbol'], 'session': evaluation['session'],
              'policy_hash': evaluation['policy_hash'], 'scope_hash': evaluation['scope_hash'],
              'checked_at': now.isoformat(), 'bar_end': until.isoformat(),
              'valid_until': (until+timedelta(minutes=1)).isoformat(), 'state': 'INCOMPLETE'}
    from .options_opening_momentum import POLICY_ID as MOMENTUM_ID
    s1 = evaluation.get('policy_id') == 'STRAT-INTRADAY-MOMENTUM-S1-RESEARCH-V1'
    momentum = evaluation.get('policy_id') == MOMENTUM_ID or s1
    rows, missing = trend.complete_minutes(bars, symbol=evaluation['symbol'], opening=opening,
                                          until=until, now=now, price_only=momentum, source_decisions=source_decisions)
    if missing or len(rows) < (5 if momentum else 15):
        return {**result, 'reasons': ['CURRENT_TREND_MINUTES_MISSING'], 'missing_minutes': missing}
    ref = evaluation['factor_evidence']['reference']
    if momentum:
        from .options_opening_momentum import price_reference_valid, price_aggregate
        from .options_intraday_comparison import intraday_contract
        reference_ok = (intraday_contract(ref, rows, symbol=evaluation['symbol'], session=evaluation['session'], now=now)['state'] == 'VERIFIED'
                        if s1 else price_reference_valid(ref, evaluation['symbol'], evaluation['session'], now))
        if not reference_ok:
            return {**result, 'reasons': ['CURRENT_TREND_REFERENCE_UNVERIFIED']}
        latest = price_aggregate(rows)[-1]
        d = 1 if evaluation['right'] == 'CALL' else -1
        factors = {'day_open': rows[0]['open'], 'previous_close': ref.get('previous_close'), 'trend_bar': latest}
        conflict = d * (latest['close'] - latest['open']) <= 0 or any(
            d * (rows[-1]['close'] - factors[k]) <= 0 for k in (('day_open',) if s1 else ('day_open', 'previous_close')))
        return {**result, 'state': 'TREND_CONFLICT' if conflict else 'VALID', 'factors': factors,
                'minute_evidence_hashes': [common.digest(b) for b in rows],
                'reasons': ['CURRENT_DAILY_TREND_CONFLICT'] if conflict else []}
    if (ref.get('volume_unit') != 'SHARES' or not ref.get('volume_unit_evidence_hash')
            or ref.get('price_comparable') is not True or not ref.get('price_basis_evidence_hash')
            or ref.get('symbol') != evaluation['symbol'] or ref.get('session') != evaluation['session']
            or not common.finite(ref.get('previous_close')) or ref['previous_close'] <= 0):
        return {**result, 'reasons': ['CURRENT_TREND_REFERENCE_UNVERIFIED']}
    from .options_opening_trend_reference import normalize_minutes
    try:
        rows, _ = normalize_minutes(rows, ref)
    except ValueError as exc:
        return {**result, 'reasons': [str(exc)]}
    volume = sum(b['volume'] for b in rows)
    if volume <= 0:
        return {**result, 'reasons': ['ZERO_VWAP_DENOMINATOR']}
    latest = trend.aggregate(rows, 15)[-1]
    factors = {'day_open': rows[0]['open'], 'previous_close': ref['previous_close'],
               'vwap': sum(b['turnover'] for b in rows)/volume, 'trend_bar': latest}
    direction = 1 if evaluation['right'] == 'CALL' else -1
    conflict = direction*(latest['close']-latest['open']) <= 0
    return {**result, 'state': 'TREND_CONFLICT' if conflict else 'VALID', 'factors': factors,
            'minute_evidence_hashes': [common.digest(b) for b in rows],
            'reasons': ['CURRENT_DAILY_TREND_CONFLICT'] if conflict else []}


def snapshot(evaluation, *, now, path=common.STORE):
    from .options_opening_trend_reference import load_reviews, source_review
    from .options_opening_momentum import POLICY_ID as MOMENTUM_ID
    momentum = evaluation.get('policy_id') in {MOMENTUM_ID, 'STRAT-INTRADAY-MOMENTUM-S1-RESEARCH-V1'}
    proof = source_review(load_reviews().get('candlestick_units', {}), now=now)
    expected = evaluation['factor_evidence']['reference'].get('volume_unit_evidence_hash')
    conversion = evaluation['factor_evidence']['reference'].get('unit_conversion') or {}
    if not momentum and (not proof or proof.get('source_sha256') != expected or proof.get('volume_unit') != 'SHARES'
            or proof.get('turnover_currency') != 'USD' or proof.get('interface') != 'US_EQUITY_CANDLESTICK_1M'
            or proof.get('shares_per_raw_volume', 1) != conversion.get('shares_per_raw_volume', 1)
            or proof.get('currency_units_per_raw_turnover', 1) != conversion.get('currency_units_per_raw_turnover', 1)):
        return {'state': 'INCOMPLETE', 'reasons': ['CURRENT_TREND_UNIT_SOURCE_CHANGED_OR_EXPIRED']}
    deadline = monotonic() + .2
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=.05)) as db:
            db.execute('PRAGMA query_only=ON')
            db.set_progress_handler(lambda: int(monotonic() >= deadline), 1000)
            # At most the opening half hour, not all historical versions or sessions.
            opening, _ = session_bounds_utc(date.fromisoformat(evaluation['session']))
            rows = db.execute('''SELECT payload_json FROM one_minute_bars
                WHERE session=? AND symbol=? AND open_at>=? AND open_at<?
                ORDER BY received_at LIMIT 2001''', (evaluation['session'], evaluation['symbol'],
                opening.isoformat(), (opening+timedelta(minutes=30)).isoformat())).fetchall()
        if len(rows) > 2000:
            return {'state': 'INCOMPLETE', 'reasons': ['CURRENT_TREND_READ_BOUND_EXCEEDED']}
        from .options_minute_decisions import read as read_decisions
        from .options_data_paths import resolve_stores
        decision_path = resolve_stores(common.ROOT)["opening_research"]
        decisions = read_decisions(decision_path, symbol=evaluation['symbol'], session=evaluation['session'], now=now) if momentum and decision_path.is_file() else None
        result = current(evaluation, [json.loads(r[0]) for r in rows], now=now, source_decisions=decisions)
        if not momentum:
            result['unit_source_check'] = {'sha256': proof['source_sha256'], 'valid_until': proof['valid_until']}
            result['valid_until'] = min(common.timestamp(result['valid_until']), common.timestamp(proof['valid_until'])).isoformat()
        return result
    except (sqlite3.Error, OSError, ValueError):
        return {'state': 'INCOMPLETE', 'reasons': ['CURRENT_TREND_READ_UNAVAILABLE']}
