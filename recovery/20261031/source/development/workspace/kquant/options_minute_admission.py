"""Shared, non-mutating admission for whole native minute versions."""
from datetime import timedelta

from . import options_one_minute as common

POLICY = {"version": "MINUTE_ADMISSION_V1", "whole_version": True,
          "closed_boundary": "available_at=end<=received_at<=as_of",
          "basis": "NoAdjust_when_declared", "session": "regular_when_declared"}
POLICY_HASH = common.digest(POLICY)


def classify(row, *, symbol, opening, until, now, price_only=True):
    try:
        start = common.timestamp(row["open_at"])
        if not opening <= start < until:
            return start, "OUTSIDE_REQUESTED_MINUTES"
        end = start + timedelta(minutes=1)
        if (row.get("symbol") != symbol or row.get("interval") != "1m"
                or row.get("closed") is not True or (start - opening).total_seconds() % 60):
            return start, "MINUTE_IDENTITY_INTERVAL_OR_CLOSURE_INVALID"
        if common.timestamp(row["available_at"]) != end or not end <= common.timestamp(row["received_at"]) <= now:
            return start, "MINUTE_TIME_EVIDENCE_CONFLICT"
        native = row.get("sdk_evidence", {})
        if native.get("adjustment") not in (None, "NOT_PROVIDED", "NoAdjust"):
            return start, "MINUTE_PRICE_BASIS_INVALID"
        if native.get("trade_session") not in (None, "Intraday", "Regular", "regular", 0):
            return start, "MINUTE_SESSION_INVALID"
        fields = ("open", "high", "low", "close") if price_only else ("open", "high", "low", "close", "turnover", "volume")
        if not all(common.finite(row.get(k)) for k in fields):
            return start, "MINUTE_NUMERIC_FIELDS_MISSING"
        if not 0 < row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"]:
            return start, "MINUTE_OHLC_INVALID"
        if not price_only and (row["turnover"] < 0 or row["volume"] < 0
                or row.get("turnover_source") != "NATIVE" or row.get("currency") != "USD"):
            return start, "MINUTE_NATIVE_AMOUNT_OR_VOLUME_INVALID"
        return start, None
    except (KeyError, TypeError, ValueError, AttributeError):
        try:
            return common.timestamp(row["open_at"]), "MINUTE_TIME_FIELDS_INVALID"
        except (KeyError, TypeError, ValueError, AttributeError):
            return None, "MINUTE_TIME_FIELDS_INVALID"


def partition(rows, *, symbol, opening, until, now):
    raw, eligible, rejected = {}, {}, {}
    for row in rows:
        try:
            if common.timestamp(row["received_at"]) > now:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        start, reason = classify(row, symbol=symbol, opening=opening, until=until, now=now)
        if start is None or not opening <= start < until:
            continue
        identity = common.digest(row)
        raw[identity] = row
        if reason:
            rejected[identity] = reason
        else:
            eligible[identity] = row
    return {"raw": raw, "eligible": eligible, "rejected": rejected,
            "eligibility_policy_hash": POLICY_HASH}
