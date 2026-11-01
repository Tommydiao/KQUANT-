"""Immutable native structure reuse; requested scope/time admission stays live."""
from datetime import timedelta
from pathlib import Path

from kquant import _first_hour_parent_admission as parent
POLICY, POLICY_HASH = parent.POLICY, parent.POLICY_HASH


def native_structure(row):
    """Use the original validator itself, not a second OHLC/basis rule set."""
    try:
        start = parent.common.timestamp(row['open_at'])
        available = parent.common.timestamp(row['available_at'])
        received = parent.common.timestamp(row['received_at'])
        checked = tuple(parent.classify(row, symbol=row.get('symbol'), opening=start,
            until=start+timedelta(minutes=1), now=received, price_only=price_only)[1]
            for price_only in (True, False))
        return (parent.classify, POLICY_HASH, start, available, received, checked)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def classify(row, *, symbol, opening, until, now, price_only=True):
    from prepared_minutes import PreparedMinute
    cached = row.native_structure if isinstance(row, PreparedMinute) else None
    if cached is not None and cached[:2] == (parent.classify, POLICY_HASH):
        _, _, start, available, received, reasons = cached
        try:
            if not opening <= start < until:
                return start, 'OUTSIDE_REQUESTED_MINUTES'
            if (row.get('symbol') != symbol or row.get('interval') != '1m'
                    or row.get('closed') is not True or (start-opening).total_seconds() % 60):
                return start, 'MINUTE_IDENTITY_INTERVAL_OR_CLOSURE_INVALID'
            if available != start+timedelta(minutes=1) or not available <= received <= now:
                return start, 'MINUTE_TIME_EVIDENCE_CONFLICT'
            return start, reasons[0 if price_only else 1]
        except (KeyError, TypeError, ValueError, AttributeError):
            pass
    return parent.classify(row, symbol=symbol, opening=opening, until=until,
                           now=now, price_only=price_only)


def partition(rows, *, symbol, opening, until, now):
    from prepared_minutes import partition as prepared_partition
    return prepared_partition(rows, symbol=symbol, opening=opening, until=until, now=now)
