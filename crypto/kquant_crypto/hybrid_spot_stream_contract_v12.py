"""Offline Spot executionReport JSON contract; synthetic connection scopes only.

No authenticated transport, OMS writes, account evidence, or gate admission.
Fields follow official binance-spot-api-docs/user-data-stream.md and enums.md,
read 2026-09-06. Missing fees remain unknown; cumulative totals never create fills.
Deduplication is bounded, in-memory, and must not be mistaken for a durable ledger.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from decimal import Decimal, localcontext
import hashlib
import json
import re

VERSION = "spot_execution_report_offline_v12"
EXECUTIONS = {"NEW", "CANCELED", "REPLACED", "REJECTED", "TRADE", "EXPIRED", "TRADE_PREVENTION"}
STATUSES = {"NEW", "PENDING_NEW", "PARTIALLY_FILLED", "FILLED", "CANCELED", "PENDING_CANCEL",
            "REJECTED", "EXPIRED", "EXPIRED_IN_MATCH"}
REJECTIONS = {"NONE", "INSUFFICIENT_BALANCES", "STOP_PRICE_WOULD_TRIGGER_IMMEDIATELY",
              "WOULD_MATCH_IMMEDIATELY", "OCO_BAD_PRICES"}
EXPIRIES = {"REJECTED", "EXCHANGE_CANCELED", "OCO_TRIGGER", "OTO_PHASE_ONE_EXPIRED",
            "UNFILLED_IOC_QUANTITY_EXPIRED", "UNFILLED_FOK_ORDER_EXPIRED", "INSUFFICIENT_LIQUIDITY",
            "EXECUTION_RULE_PRICE_RANGE_EXCEEDED"}


class ProtocolError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def _json(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ProtocolError("NON_JSON_PAYLOAD") from exc


def _key(kind, value):
    return kind + "_" + hashlib.sha256(_json(value).encode()).hexdigest()


def _integer(value, name, minimum=0):
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise ProtocolError("INVALID_INTEGER:" + name)
    return value


def _stamp(value, name):
    # This bounded offline contract explicitly supports contemporary ms epochs,
    # not seconds, microseconds, negative sentinels, or inferred time units.
    if type(value) is not int or not 1_000_000_000_000 <= value <= 9_999_999_999_999:
        raise ProtocolError("UNKNOWN_OR_UNSUPPORTED_TIMESTAMP:" + name)
    return value


def _text(value, name):
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ProtocolError("INVALID_TEXT:" + name)
    return value


def _decimal(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value) or len(value) > 80:
        raise ProtocolError("INVALID_DECIMAL_STRING:" + name)
    result = Decimal(value)
    if len(result.as_tuple().digits) > 40 or -result.as_tuple().exponent > 24:
        raise ProtocolError("UNSUPPORTED_DECIMAL_PRECISION:" + name)
    return result


@dataclass(frozen=True)
class MockConnection:
    namespace: str
    epoch: str
    subscription_id: int
    time_unit: str = "MILLISECOND"

    def __post_init__(self):
        if not isinstance(self.namespace, str) or not re.fullmatch(r"(?:mock|synthetic)://[A-Za-z0-9_-]{1,80}", self.namespace):
            raise ProtocolError("SYNTHETIC_CONNECTION_REQUIRED")
        _text(self.epoch, "epoch")
        _integer(self.subscription_id, "subscription_id")
        if self.time_unit != "MILLISECOND":
            raise ProtocolError("UNSUPPORTED_TIMESTAMP_UNIT")


@dataclass(frozen=True)
class OrderExpectation:
    symbol: str
    order_id: int
    client_order_id: str
    side: str
    quantity: str

    def __post_init__(self):
        _text(self.symbol, "symbol")
        _integer(self.order_id, "order_id")
        _text(self.client_order_id, "client_order_id")
        if self.side not in {"BUY", "SELL"} or _decimal(self.quantity, "quantity") <= 0:
            raise ProtocolError("INVALID_ORDER_EXPECTATION")


@dataclass(frozen=True)
class OrderUpdate:
    order_key: str
    report_key: str
    symbol: str
    order_id: int
    client_order_id: str
    report_client_order_id: str
    original_client_order_id: str
    side: str
    execution_type: str
    order_status: str
    order_type: str
    time_in_force: str
    quantity: Decimal
    cumulative_quantity: Decimal
    cumulative_quote: Decimal
    last_quantity: Decimal
    last_price: Decimal
    last_quote: Decimal
    commission: Decimal | None
    commission_asset: str | None
    reject_reason: str
    expiry_reason: str | None
    event_time_ms: int
    transaction_time_ms: int
    order_creation_time_ms: int
    received_at_ms: int


@dataclass(frozen=True)
class FillFact:
    fill_key: str
    order_key: str
    symbol: str
    order_id: int
    trade_id: int
    side: str
    quantity: Decimal
    price: Decimal
    quote_quantity: Decimal
    commission: Decimal | None
    commission_asset: str | None
    transaction_time_ms: int
    commission_quote_value: None = None


@dataclass(frozen=True)
class NormalizedExecution:
    connection: MockConnection
    order: OrderUpdate
    fill: FillFact | None
    reconciliation_reasons: tuple[str, ...]
    raw_json: str
    duplicate_report: bool = False
    duplicate_fill: bool = False
    ledger_admission: bool = False
    authenticated_transport: bool = False
    evidence_scope: str = "SYNTHETIC_PROTOCOL_FIXTURE_ONLY"


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ProtocolError("DUPLICATE_JSON_KEY:" + key)
        result[key] = value
    return result


def decode_execution_report(payload, connection, *, received_at_ms, expected=None):
    if not isinstance(connection, MockConnection):
        raise ProtocolError("SYNTHETIC_CONNECTION_REQUIRED")
    received = _stamp(received_at_ms, "received_at_ms")
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload, object_pairs_hook=_pairs)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise ProtocolError("MALFORMED_JSON") from exc
    if not isinstance(payload, dict):
        raise ProtocolError("INVALID_ENVELOPE")
    raw = _json(payload)
    if set(payload) != {"subscriptionId", "event"} or payload["subscriptionId"] != connection.subscription_id:
        raise ProtocolError("SUBSCRIPTION_ENVELOPE_MISMATCH")
    _integer(payload["subscriptionId"], "subscriptionId")
    event = payload["event"]
    if not isinstance(event, dict) or event.get("e") != "executionReport":
        raise ProtocolError("UNSUPPORTED_EVENT_TYPE")
    try:
        symbol, side = _text(event["s"], "s"), _text(event["S"], "S")
        if side not in {"BUY", "SELL"}:
            raise ProtocolError("UNSUPPORTED_SIDE")
        oid, eid = _integer(event["i"], "i"), _integer(event["I"], "I")
        client = _text(event["c"], "c")
        original = event.get("C", "")
        if not isinstance(original, str):
            raise ProtocolError("INVALID_ORIGINAL_CLIENT_ID")
        execution, status = _text(event["x"], "x"), _text(event["X"], "X")
        order_type, tif = _text(event["o"], "o"), _text(event["f"], "f")
        qty, cumulative, quote_total, last, price, last_quote = [_decimal(event[k], k) for k in ("q", "z", "Z", "l", "L", "Y")]
        event_time, transaction_time, creation = [_stamp(event[k], k) for k in ("E", "T", "O")]
        trade_id = _integer(event["t"], "t", -1)
        reject = _text(event["r"], "r")
    except KeyError as exc:
        raise ProtocolError("MISSING_REQUIRED_FIELD:" + str(exc.args[0])) from exc
    if creation > min(event_time, transaction_time):
        raise ProtocolError("CONTRADICTORY_ORDER_CREATION_TIME")
    if qty <= 0 or not 0 <= last <= cumulative <= qty or quote_total < last_quote:
        raise ProtocolError("CONTRADICTORY_EXECUTED_QUANTITIES")
    if cumulative == 0 and quote_total != 0:
        raise ProtocolError("QUOTE_TOTAL_WITHOUT_EXECUTED_QUANTITY")
    if status == "FILLED" and cumulative != qty or status == "PARTIALLY_FILLED" and not 0 < cumulative < qty:
        raise ProtocolError("CONTRADICTORY_ORDER_STATUS")
    reasons = []
    if execution not in EXECUTIONS:
        reasons.append("UNSUPPORTED_EXECUTION_TYPE:" + execution)
    if status not in STATUSES:
        reasons.append("UNSUPPORTED_ORDER_STATUS:" + status)
    if order_type not in {"LIMIT", "LIMIT_MAKER"} or tif not in {"GTC", "IOC", "FOK"}:
        reasons.append("ORDER_POLICY_NOT_INTEGRATED:" + order_type + ":" + tif)
    if execution in {"REPLACED", "TRADE_PREVENTION"}:
        reasons.append("AMENDMENT_OR_STP_RECONCILIATION_REQUIRED")
    canonical_client = original if original and execution == "CANCELED" else client
    if original and execution != "CANCELED":
        reasons.append("ORIGINAL_CLIENT_ALIAS_REQUIRES_RECONCILIATION")
    if expected is None:
        reasons.append("ORDER_NOT_BOUND_TO_LOCAL_INTENT")
    else:
        if not isinstance(expected, OrderExpectation) or (symbol, oid, side, canonical_client) != (
            expected.symbol, expected.order_id, expected.side, expected.client_order_id):
            raise ProtocolError("CONTRADICTORY_ORDER_IDENTITY")
        if qty != _decimal(expected.quantity, "expected.quantity"):
            if execution == "REPLACED":
                reasons.append("AMENDED_QUANTITY_REQUIRES_RECONCILIATION")
            else:
                raise ProtocolError("CONTRADICTORY_ORIGINAL_QUANTITY")
    fee = None if event.get("n") is None else _decimal(event["n"], "n")
    asset = event.get("N")
    if asset is not None:
        asset = _text(asset, "N")
    if fee is None:
        reasons.append("COMMISSION_AMOUNT_UNKNOWN")
    if asset is None and (fee is None or fee > 0):
        reasons.append("COMMISSION_ASSET_UNKNOWN")
    if asset is not None:
        reasons.append("COMMISSION_UNCONVERTED:" + asset)
    if reject != "NONE":
        reasons.append(("REJECT_REASON:" if reject in REJECTIONS else "UNSUPPORTED_REJECT_REASON:") + reject)
    expiry = event.get("eR")
    if expiry is not None:
        expiry = _text(expiry, "eR")
        reasons.append(("EXPIRY_REASON:" if expiry in EXPIRIES else "UNSUPPORTED_EXPIRY_REASON:") + expiry)
    if event.get("g", -1) != -1:
        reasons.append("ORDER_LIST_RECONCILIATION_UNIMPLEMENTED")
    if received < event_time or event_time < transaction_time:
        reasons.append("CLOCK_ORDER_REQUIRES_RECONCILIATION")
    scope = [connection.namespace, connection.epoch, symbol, oid]
    order_key, report_key = _key("order", scope), _key("report", scope + [eid])
    fill = None
    if execution == "TRADE":
        if last <= 0 or price <= 0 or trade_id < 0:
            raise ProtocolError("TRADE_WITHOUT_INCREMENTAL_FILL_FACTS")
        with localcontext() as context:
            context.prec = 128
            if last_quote != last * price:
                raise ProtocolError("CONTRADICTORY_LAST_QUOTE_QUANTITY")
        if status not in {"PARTIALLY_FILLED", "FILLED"}:
            reasons.append("TRADE_STATUS_REQUIRES_RECONCILIATION")
        fill = FillFact(_key("fill", scope + [trade_id]), order_key, symbol, oid, trade_id, side,
                        last, price, last_quote, fee, asset, transaction_time)
    elif execution in EXECUTIONS and last != 0:
        raise ProtocolError("NONTRADE_EXECUTION_HAS_INCREMENTAL_QUANTITY")
    if execution != "TRADE" and cumulative > 0:
        reasons.append("CUMULATIVE_TOTAL_IS_NOT_FILL_EVIDENCE")
    if execution != "TRADE" and fee is not None and fee > 0:
        reasons.append("COMMISSION_WITHOUT_TRADE_REQUIRES_RECONCILIATION")
    order = OrderUpdate(order_key, report_key, symbol, oid, canonical_client, client, original, side,
                        execution, status, order_type, tif, qty, cumulative, quote_total, last, price,
                        last_quote, fee, asset, reject, expiry, event_time, transaction_time, creation, received)
    return NormalizedExecution(connection, order, fill, tuple(reasons), raw)


class OfflineExecutionDecoder:
    """In-memory duplicate classification; unseen old fills are not discarded."""
    def __init__(self, connection, *, max_records=10000):
        if not isinstance(connection, MockConnection) or type(max_records) is not int or max_records < 1:
            raise ProtocolError("INVALID_DECODER_CONFIGURATION")
        self.connection, self.max_records = connection, max_records
        self.reports, self.fills, self.orders = {}, {}, {}

    def decode(self, payload, *, received_at_ms, expected=None):
        result = decode_execution_report(payload, self.connection, received_at_ms=received_at_ms, expected=expected)
        order, fill = result.order, result.fill
        old_report = self.reports.get(order.report_key)
        if old_report is not None:
            if old_report != result.raw_json:
                raise ProtocolError("CONFLICTING_EXECUTION_ID")
            return replace(result, fill=None, duplicate_report=True, duplicate_fill=fill is not None)
        old = self.orders.get(order.order_key)
        identity_fields = (order.symbol, order.order_id, order.client_order_id, order.side, order.order_creation_time_ms)
        if old and old[0] != identity_fields:
            raise ProtocolError("CONTRADICTORY_ORDER_IDENTITY")
        reasons = result.reconciliation_reasons
        if old and order.cumulative_quantity < old[1]:
            reasons += ("OUT_OF_ORDER_CUMULATIVE_REQUIRES_RECONCILIATION",)
        duplicate = False
        if fill and fill.fill_key in self.fills:
            if self.fills[fill.fill_key] != fill:
                raise ProtocolError("CONFLICTING_TRADE_ID")
            duplicate = True
        if len(self.reports) >= self.max_records or fill and not duplicate and len(self.fills) >= self.max_records:
            raise ProtocolError("DEDUP_CAPACITY_REQUIRES_DURABLE_RECONCILIATION")
        self.reports[order.report_key] = result.raw_json
        self.orders[order.order_key] = (identity_fields, max(order.cumulative_quantity, old[1] if old else Decimal(0)))
        if fill and not duplicate:
            self.fills[fill.fill_key] = fill
        return replace(result, fill=None if duplicate else fill, duplicate_fill=duplicate, reconciliation_reasons=reasons)


def to_jsonable(result):
    """Serialize Decimal facts without converting to binary float."""
    def convert(value):
        if isinstance(value, Decimal):
            return format(value, "f")
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [convert(item) for item in value]
        return value
    return convert(asdict(result))
