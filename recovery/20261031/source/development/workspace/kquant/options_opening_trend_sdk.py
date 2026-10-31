"""Small field-whitelisted SDK evidence, captured before float normalization."""
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version


@lru_cache(maxsize=1)
def sdk_version():
    try:
        return version("longbridge")
    except PackageNotFoundError:
        return "UNAVAILABLE"


def candle_evidence(candle, *, provider_symbol, interface, received_at, requested_at=None,
                    confirmed=None, clock_evidence=None):
    fields = {}
    for name in ("timestamp", "open", "high", "low", "close", "volume", "turnover", "trade_session"):
        value = getattr(candle, name, None)
        fields[name] = {"value": None if value is None else str(value),
                        "type": type(value).__module__ + "." + type(value).__qualname__}
    from .options_clock_measurement import snapshot
    clock = snapshot() if clock_evidence is None else clock_evidence
    return {"kind": "SDK_OBJECT_FIELDS_NOT_WIRE_RESPONSE", "provider_symbol": provider_symbol,
            "interface": interface, "sdk_package": "longbridge", "sdk_version": sdk_version(),
            "period": "Min_1", "adjustment": "NoAdjust" if interface in
            {"QuoteContext.candlesticks", "QuoteContext.history_candlesticks_by_offset"} else "NOT_PROVIDED",
            "request_started_at": requested_at, "received_at": received_at,
            "provider_confirmed": confirmed, "fields": fields, "clock_evidence": clock}
