"""Raw synthetic protocol fixtures only; no account or exchange evidence."""
import json
import socket
from decimal import Decimal

import pytest

from kquant_crypto.hybrid_spot_stream_contract_v12 import (
    MockConnection, OfflineExecutionDecoder, OrderExpectation, ProtocolError,
    decode_execution_report, to_jsonable,
)

NOW = 1788580000000
CONNECTION = MockConnection("synthetic://unit", "attempt-1", 0)
EXPECTED = OrderExpectation("BTCUSDT", 101, "entry-1", "BUY", "1")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def report(**changes):
    event = dict(e="executionReport", E=NOW+1, T=NOW, O=NOW-1000,
                 s="BTCUSDT", S="BUY", i=101, I=1, c="entry-1", C="",
                 x="NEW", X="NEW", o="LIMIT", f="GTC", q="1", z="0",
                 Z="0", l="0", L="0", Y="0", t=-1, r="NONE", n="0", N=None)
    event.update(changes)
    return {"subscriptionId": 0, "event": event}


def trade(**changes):
    values = dict(x="TRADE", X="PARTIALLY_FILLED", I=2, t=20,
                  l="0.4", z="0.4", L="100", Y="40", Z="40", n="0.04", N="USDT")
    values.update(changes)
    return report(**values)


def decode(payload, **kwargs):
    return decode_execution_report(payload, CONNECTION, received_at_ms=NOW+10,
                                   expected=EXPECTED, **kwargs)


def test_ack_is_not_fill():
    result = decode(json.dumps(report()))
    assert result.fill is None
    assert not result.ledger_admission and not result.authenticated_transport
    assert result.order.received_at_ms == NOW+10


def test_partial_and_final_increment_not_cumulative():
    decoder = OfflineExecutionDecoder(CONNECTION)
    first = decoder.decode(trade(), received_at_ms=NOW+10, expected=EXPECTED)
    last = decoder.decode(trade(I=3, t=21, l="0.6", z="1", Y="60", Z="100", X="FILLED"),
                          received_at_ms=NOW+11, expected=EXPECTED)
    assert first.fill.quantity == Decimal("0.4")
    assert last.fill.quantity == Decimal("0.6")
    assert last.order.cumulative_quantity == Decimal("1")


def test_cancel_alias_no_retrospective_fill():
    result = decode(report(x="CANCELED", X="CANCELED", c="cancel-1", C="entry-1", z="0.4", Z="40"))
    assert result.fill is None
    assert result.order.client_order_id == "entry-1"
    assert "CUMULATIVE_TOTAL_IS_NOT_FILL_EVIDENCE" in result.reconciliation_reasons


def test_duplicate_report_and_fill_suppressed_separately():
    decoder = OfflineExecutionDecoder(CONNECTION)
    first = decoder.decode(trade(), received_at_ms=NOW+10)
    repeated = decoder.decode(trade(), received_at_ms=NOW+20)
    alias = decoder.decode(trade(I=3), received_at_ms=NOW+21)
    assert first.fill is not None
    assert repeated.duplicate_report and repeated.duplicate_fill and repeated.fill is None
    assert not alias.duplicate_report and alias.duplicate_fill and alias.fill is None


@pytest.mark.parametrize("changes,reason", [({"n": "0.05"}, "CONFLICTING_EXECUTION_ID"),
                                           ({"I": 3, "n": "0.05"}, "CONFLICTING_TRADE_ID")])
def test_conflicting_identifiers(changes, reason):
    decoder = OfflineExecutionDecoder(CONNECTION)
    decoder.decode(trade(), received_at_ms=NOW+10)
    with pytest.raises(ProtocolError, match=reason):
        decoder.decode(trade(**changes), received_at_ms=NOW+11)
    assert len(decoder.reports) == 1


def test_unseen_out_of_order_fill_preserved():
    decoder = OfflineExecutionDecoder(CONNECTION)
    decoder.decode(trade(I=3, t=21, l="0.6", z="1", Y="60", Z="100", X="FILLED"), received_at_ms=NOW+10)
    old = decoder.decode(trade(), received_at_ms=NOW+11)
    assert old.fill.quantity == Decimal("0.4")
    assert "OUT_OF_ORDER_CUMULATIVE_REQUIRES_RECONCILIATION" in old.reconciliation_reasons


@pytest.mark.parametrize("asset", ["USDT", "BTC", "BNB", "UNKNOWN_ASSET"])
def test_fee_currency_preserved_not_converted(asset):
    result = decode(trade(N=asset))
    assert result.fill.commission == Decimal("0.04")
    assert result.fill.commission_asset == asset
    assert result.fill.commission_quote_value is None
    assert "COMMISSION_UNCONVERTED:" + asset in result.reconciliation_reasons


def test_missing_fee_not_zero():
    payload = trade()
    del payload["event"]["n"]
    del payload["event"]["N"]
    result = decode(payload)
    assert result.fill.commission is None and result.fill.commission_asset is None
    assert "COMMISSION_AMOUNT_UNKNOWN" in result.reconciliation_reasons
    assert decode(trade(n="0", N=None)).fill.commission == Decimal(0)


def test_unknown_semantics_preserved():
    result = decode(report(x="FUTURE", X="FUTURE", r="NEW_REJECT", eR="NEW_EXPIRY", extra="retain"))
    assert result.fill is None
    assert "UNSUPPORTED_EXECUTION_TYPE:FUTURE" in result.reconciliation_reasons
    assert "UNSUPPORTED_ORDER_STATUS:FUTURE" in result.reconciliation_reasons
    assert "UNSUPPORTED_REJECT_REASON:NEW_REJECT" in result.reconciliation_reasons
    assert "UNSUPPORTED_EXPIRY_REASON:NEW_EXPIRY" in result.reconciliation_reasons
    assert json.loads(result.raw_json)["event"]["extra"] == "retain"


@pytest.mark.parametrize("field", ["E", "T", "O"])
@pytest.mark.parametrize("value", [None, True, 0, 1788580000, 1788580000000000, "1788580000000"])
def test_unknown_timestamp_rejected(field, value):
    with pytest.raises(ProtocolError, match="TIMESTAMP"):
        decode(report(**{field: value}))


@pytest.mark.parametrize("changes", [{"i": 102}, {"c": "other"}, {"s": "ETHUSDT"},
                                     {"S": "SELL"}, {"x": "CANCELED", "C": "other"}])
def test_identity_contradiction_rejected(changes):
    with pytest.raises(ProtocolError, match="IDENTITY"):
        decode(report(**changes))


@pytest.mark.parametrize("value", [0.4, "NaN", "Infinity", "1e-4", "-1", "0." + "1"*25])
def test_decimal_invalid_or_unsupported_precision(value):
    with pytest.raises(ProtocolError, match="DECIMAL"):
        decode(trade(l=value))


def test_precision_exact_without_float():
    value = "0.123456789012345678901234"
    result = decode(trade(l=value, z=value, L="1", Y=value, Z=value))
    assert result.fill.quantity == Decimal(value)
    assert to_jsonable(result)["fill"]["quantity"] == value


@pytest.mark.parametrize("changes", [{"Y": "39"}, {"z": "0.3"}, {"X": "FILLED"}, {"t": -1}])
def test_contradictory_trade_rejected(changes):
    with pytest.raises(ProtocolError):
        decode(trade(**changes))


def test_nontrade_increment_rejected():
    with pytest.raises(ProtocolError, match="NONTRADE"):
        decode(report(l="0.1", z="0.1", Z="10", Y="10", L="100"))


@pytest.mark.parametrize("namespace", ["production://unit", "testnet://unit", "wss://example", "mock://"])
def test_only_synthetic_namespace(namespace):
    with pytest.raises(ProtocolError):
        MockConnection(namespace, "epoch", 0)


def test_scope_epoch_changes_keys():
    first = decode(trade())
    second = decode_execution_report(trade(), MockConnection("mock://other", "epoch2", 0), received_at_ms=NOW+10)
    assert first.fill.fill_key != second.fill.fill_key


def test_envelope_subscription_and_event_rejected():
    payload = report()
    payload["subscriptionId"] = 1
    with pytest.raises(ProtocolError, match="SUBSCRIPTION"):
        decode(payload)
    with pytest.raises(ProtocolError, match="UNSUPPORTED_EVENT"):
        decode(report(e="outboundAccountPosition"))


def test_json_errors_and_missing_required():
    with pytest.raises(ProtocolError, match="MALFORMED_JSON"):
        decode("{")
    with pytest.raises(ProtocolError, match="DUPLICATE_JSON_KEY"):
        decode('{"subscriptionId":0,"subscriptionId":1}')
    payload = report()
    del payload["event"]["T"]
    with pytest.raises(ProtocolError, match="MISSING_REQUIRED_FIELD:T"):
        decode(payload)


def test_capacity_no_silent_eviction():
    decoder = OfflineExecutionDecoder(CONNECTION, max_records=1)
    decoder.decode(report(), received_at_ms=NOW+10)
    with pytest.raises(ProtocolError, match="CAPACITY"):
        decoder.decode(trade(), received_at_ms=NOW+10)
    assert decoder.decode(report(), received_at_ms=NOW+11).duplicate_report


def test_creation_and_receipt_clock():
    with pytest.raises(ProtocolError, match="CREATION_TIME"):
        decode(report(O=NOW+2))
    result = decode_execution_report(report(), CONNECTION, received_at_ms=NOW-2)
    assert "CLOCK_ORDER_REQUIRES_RECONCILIATION" in result.reconciliation_reasons


def test_state_identity_without_expectation():
    decoder = OfflineExecutionDecoder(CONNECTION)
    decoder.decode(report(), received_at_ms=NOW+10)
    with pytest.raises(ProtocolError, match="IDENTITY"):
        decoder.decode(trade(c="other"), received_at_ms=NOW+10)
