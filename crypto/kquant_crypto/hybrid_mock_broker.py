"""Credential-free synthetic Spot venue. No transport or production adapters.

LIMIT GTC/IOC only; liquidity is explicitly injected, never inferred from bars.
Local identity reuse is stricter than exchange client-ID reuse. This fixture is
not an exchange emulator, native protection implementation, or G8 acceptance.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_DOWN, localcontext
from functools import wraps
import hashlib
import json

VERSION = "hybrid_mock_spot_v1"
TERMINAL = frozenset({"FILLED", "CANCELED", "EXPIRED", "REJECTED"})


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identity(kind, payload):
    return kind + "_" + hashlib.sha256(encode(payload).encode()).hexdigest()


def decimal(value):
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("decimal strings/Decimal/integers only; binary float forbidden")
    result = Decimal(value)
    if not result.is_finite() or result < 0 or len(result.as_tuple().digits) > 28 or abs(result.as_tuple().exponent) > 18:
        raise ValueError("nonnegative finite bounded decimal required")
    return result


def number(value):
    with localcontext() as ctx:
        ctx.prec = 80
        return format(decimal(value).normalize(), "f")


def exact_decimal(function):
    """Insulate fixture arithmetic from a caller's ambient Decimal context."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        with localcontext() as ctx:
            ctx.prec = 80
            return function(*args, **kwargs)
    return wrapped


class BrokerRejected(ValueError):
    """Definitive local mock rejection, never a network timeout."""


class UnknownExecution(RuntimeError):
    """Injected ambiguous submit/cancel outcome. Query, never blindly resubmit."""


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    base: str
    quote: str
    tick_size: str
    step_size: str
    min_qty: str
    max_qty: str
    min_notional: str
    max_notional: str
    min_price: str
    max_price: str
    valid_until: int
    max_orders: int = 10
    trading: bool = True

    def __post_init__(self):
        if self.symbol not in {"BTCUSDT", "ETHUSDT", "SOLUSDT"} or self.symbol != self.base + self.quote or self.quote != "USDT":
            raise ValueError("fixed Spot research universe only")
        for field in ("tick_size", "step_size", "min_qty", "max_qty", "min_notional", "max_notional", "min_price", "max_price"):
            if decimal(getattr(self, field)) <= 0:
                raise ValueError("explicit positive mock filter required")
            object.__setattr__(self, field, number(getattr(self, field)))
        if (type(self.valid_until) is not int or self.valid_until < 0 or type(self.max_orders) is not int
                or self.max_orders < 1 or type(self.trading) is not bool):
            raise ValueError("invalid mock rule expiry/order limit/status")
        if any(decimal(getattr(self, lo)) > decimal(getattr(self, hi)) for lo, hi in (
            ("min_qty", "max_qty"), ("min_notional", "max_notional"), ("min_price", "max_price"))):
            raise ValueError("inverted filter bounds")

    @property
    def rule_hash(self):
        return identity("rules", asdict(self))

    def round_quantity(self, quantity):
        with localcontext() as ctx:
            ctx.prec = 80
            step = decimal(self.step_size)
            return number((decimal(quantity) / step).to_integral_value(rounding=ROUND_DOWN) * step)

    def validate(self, intent, now):
        if type(now) is not int or now < 0 or now > self.valid_until or not self.trading:
            raise BrokerRejected("rules stale or trading disabled")
        if intent.symbol != self.symbol or intent.rules_hash != self.rule_hash:
            raise BrokerRejected("rules/symbol mismatch")
        q, p = decimal(intent.quantity), decimal(intent.limit_price)
        with localcontext() as ctx:
            ctx.prec = 80
            if (not decimal(self.min_qty) <= q <= decimal(self.max_qty) or q % decimal(self.step_size)
                    or not decimal(self.min_price) <= p <= decimal(self.max_price) or p % decimal(self.tick_size)
                    or not decimal(self.min_notional) <= q * p <= decimal(self.max_notional)):
                raise BrokerRejected("quantity/price/notional filter; SKIP, never round risk upward")


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    symbol: str
    side: str
    quantity: str
    limit_price: str
    rules_hash: str
    time_in_force: str = "GTC"
    execution_version: str = VERSION

    def __post_init__(self):
        if (not isinstance(self.intent_id, str) or not self.intent_id or self.side not in {"BUY", "SELL"}
                or self.time_in_force not in {"GTC", "IOC"} or self.execution_version != VERSION):
            raise BrokerRejected("unsupported intent or execution policy")
        for key in ("quantity", "limit_price"):
            object.__setattr__(self, key, number(getattr(self, key)))


def reservation(intent, remaining, rules, fee_rate, fee_asset):
    q, rate = decimal(remaining), decimal(fee_rate)
    with localcontext() as ctx:
        ctx.prec = 80
        if intent.side == "BUY":
            return rules.quote, q * decimal(intent.limit_price) * (1 + rate if fee_asset == "quote" else 1)
        return rules.base, q * (1 + rate if fee_asset == "base" else 1)


def fill_deltas(fill, rules):
    q, p, fee = decimal(fill["quantity"]), decimal(fill["price"]), decimal(fill["commission"])
    with localcontext() as ctx:
        ctx.prec = 80
        sign = 1 if fill["side"] == "BUY" else -1
        changes = {rules.base: sign * q, rules.quote: -sign * q * p}
        changes[fill["commission_asset"]] -= fee
        return changes


class MockBroker:
    def __init__(self, rules, balances, *, namespace="fixture", epoch="epoch-1", fee_rate="0.001", fee_asset="quote"):
        if not namespace or not epoch or fee_asset not in {"base", "quote"} or decimal(fee_rate) > Decimal("0.01"):
            raise ValueError("explicit fixture namespace/epoch/fee required")
        if not rules or any(not isinstance(r, SymbolRules) or s != r.symbol for s, r in rules.items()):
            raise ValueError("explicit symbol rules required")
        self.rules = dict(rules)
        self.namespace, self.epoch = namespace, epoch
        self.fee_rate, self.fee_asset = number(fee_rate), fee_asset
        self.balances = {a: decimal(v) for a, v in balances.items()}
        for r in rules.values():
            self.balances.setdefault(r.base, Decimal(0))
            self.balances.setdefault(r.quote, Decimal(0))
        self.orders, self.fills, self.events = {}, [], []
        self.submit_calls = self.query_calls = 0
        self.submit_fault = self.cancel_fault = None
        self.online = True

    @property
    def binding(self):
        return {"version": VERSION, "namespace": self.namespace, "epoch": self.epoch,
                "rules": {s: r.rule_hash for s, r in sorted(self.rules.items())},
                "fee_rate": self.fee_rate, "fee_asset": self.fee_asset}

    def client_id(self, intent_id):
        return identity("hm", [self.namespace, self.epoch, intent_id])[:36]

    def get_capabilities(self):
        return {"venue": "ISOLATED_SYNTHETIC_SPOT", "network": "DENY_NO_TRANSPORT",
                "account_status": "UNKNOWN_NOT_ACCESSED", "credentials": False,
                "order_types": ["LIMIT"], "time_in_force": ["GTC", "IOC"],
                "native_protection": False, "withdrawal": False, "leverage": False,
                "testnet_verified": False, "G8": "NOT_PASSED"}

    def get_symbol_rules(self, symbol):
        return asdict(self.rules[symbol])

    def health(self):
        return {"online": self.online, "epoch": self.epoch, "synthetic_only": True}

    def _online(self):
        if not self.online:
            raise UnknownExecution("mock disconnect")

    @exact_decimal
    def _reserved(self, exclude=None):
        values = {}
        for cid, order in self.orders.items():
            if cid == exclude or order["status"] in TERMINAL:
                continue
            intent = OrderIntent(**order["intent"])
            asset, amount = reservation(intent, decimal(intent.quantity) - decimal(order["executed_quantity"]),
                                        self.rules[intent.symbol], self.fee_rate, self.fee_asset)
            values[asset] = values.get(asset, Decimal(0)) + amount
        return values

    @exact_decimal
    def get_account_snapshot(self):
        self._online()
        reserved = self._reserved()
        return {"epoch": self.epoch, "synthetic_only": True,
                "balances": {a: {"total": number(v), "reserved": number(reserved.get(a, 0)),
                                  "free": number(v - reserved.get(a, 0))} for a, v in sorted(self.balances.items())}}

    def get_open_orders(self, symbol=None):
        self._online()
        return deepcopy([o for o in self.orders.values() if o["status"] not in TERMINAL
                         and (symbol is None or o["intent"]["symbol"] == symbol)])

    def get_order(self, client_order_id=None, *, exchange_order_id=None):
        self._online()
        self.query_calls += 1
        if (client_order_id is None) == (exchange_order_id is None):
            raise ValueError("exactly one order identity required")
        if exchange_order_id is not None:
            return deepcopy(next((o for o in self.orders.values() if o["exchange_order_id"] == exchange_order_id), None))
        return deepcopy(self.orders.get(client_order_id))

    def get_fills(self, cursor=0):
        self._online()
        if type(cursor) is not int or not 0 <= cursor <= len(self.fills):
            raise ValueError("invalid epoch-scoped fill cursor")
        return {"epoch": self.epoch, "cursor": len(self.fills), "fills": deepcopy(self.fills[cursor:])}

    def subscribe_execution_events(self, cursor=0):
        self._online()
        if type(cursor) is not int or not 0 <= cursor <= len(self.events):
            raise ValueError("invalid mock event cursor")
        return iter(deepcopy(self.events[cursor:]))

    @exact_decimal
    def submit_order(self, intent, *, now):
        self._online()
        self.submit_calls += 1
        cid = self.client_id(intent.intent_id)
        if cid in self.orders:
            if self.orders[cid]["intent"] != asdict(intent):
                raise BrokerRejected("client ID conflicts with immutable intent")
            return deepcopy(self.orders[cid])
        fault, self.submit_fault = self.submit_fault, None
        if fault == "before_accept":
            raise UnknownExecution("injected timeout before acceptance; caller cannot know")
        rules = self.rules.get(intent.symbol)
        if rules is None:
            raise BrokerRejected("unsupported symbol")
        rules.validate(intent, now)
        if len(self.get_open_orders(intent.symbol)) >= rules.max_orders:
            raise BrokerRejected("open order limit")
        asset, amount = reservation(intent, intent.quantity, rules, self.fee_rate, self.fee_asset)
        if amount > self.balances.get(asset, 0) - self._reserved().get(asset, 0):
            raise BrokerRejected("insufficient free Spot balance")
        order = {"client_order_id": cid, "exchange_order_id": identity("mockorder", [self.epoch, cid]),
                 "intent": asdict(intent), "status": "ACKNOWLEDGED", "executed_quantity": "0", "revision": 1}
        self.orders[cid] = order
        self.events.append({"kind": "ACK", **deepcopy(order)})
        if fault in {"after_accept", "5xx_after_accept"}:
            raise UnknownExecution("injected ambiguous ACK loss/5xx after acceptance")
        return deepcopy(order)

    @exact_decimal
    def fill_order(self, client_order_id, *, quantity, price, fill_key):
        """Explicit fixture liquidity; no assertion of live price reachability."""
        self._online()
        order = self.orders[client_order_id]
        intent = OrderIntent(**order["intent"])
        rules = self.rules[intent.symbol]
        q, p = decimal(quantity), decimal(price)
        if not isinstance(fill_key, str) or not fill_key or q <= 0 or p <= 0:
            raise BrokerRejected("positive fill and stable fixture key required")
        with localcontext() as ctx:
            ctx.prec = 80
            fee = q * (p if self.fee_asset == "quote" else 1) * decimal(self.fee_rate)
        fill = {"exchange_trade_id": identity("mocktrade", [self.epoch, client_order_id, fill_key]),
                "client_order_id": client_order_id, "exchange_order_id": order["exchange_order_id"],
                "symbol": intent.symbol, "side": intent.side, "quantity": number(q), "price": number(p),
                "commission": number(fee), "commission_asset": getattr(rules, self.fee_asset), "epoch": self.epoch}
        old = next((f for f in self.fills if f["exchange_trade_id"] == fill["exchange_trade_id"]), None)
        if old:
            if old != fill:
                raise BrokerRejected("conflicting fill ID")
            return deepcopy(old)
        if (order["status"] in TERMINAL or q > decimal(intent.quantity) - decimal(order["executed_quantity"])
                or (intent.side == "BUY" and p > decimal(intent.limit_price))
                or (intent.side == "SELL" and p < decimal(intent.limit_price))):
            raise BrokerRejected("invalid fill quantity/limit/terminal state")
        updated = dict(self.balances)
        for asset, change in fill_deltas(fill, rules).items():
            updated[asset] = updated.get(asset, Decimal(0)) + change
            if updated[asset] < self._reserved(exclude=client_order_id).get(asset, 0):
                raise BrokerRejected("fill consumes another order's reserved balance")
        self.balances = updated
        self.fills.append(fill)
        order["executed_quantity"] = number(decimal(order["executed_quantity"]) + q)
        order["status"] = "FILLED" if decimal(order["executed_quantity"]) == decimal(intent.quantity) else "PARTIALLY_FILLED"
        order["revision"] += 1
        self.events.append({"kind": "FILL", "fill": deepcopy(fill), "order": deepcopy(order)})
        return deepcopy(fill)

    def finish_ioc(self, client_order_id):
        self._online()
        order = self.orders[client_order_id]
        if order["intent"]["time_in_force"] != "IOC":
            raise BrokerRejected("not an IOC fixture")
        if order["status"] not in TERMINAL:
            order["status"] = "EXPIRED"
            order["revision"] += 1
        return deepcopy(order)

    def cancel_order(self, client_order_id):
        self._online()
        order = self.orders.get(client_order_id)
        if order is None:
            raise UnknownExecution("order not found; not proof of nonacceptance")
        fault, self.cancel_fault = self.cancel_fault, None
        if fault == "before_cancel":
            raise UnknownExecution("ambiguous cancel timeout")
        if order["status"] not in TERMINAL:
            order["status"] = "CANCELED"
            order["revision"] += 1
        self.events.append({"kind": "CANCEL_ACK", **deepcopy(order)})
        if fault == "after_cancel":
            raise UnknownExecution("cancel ACK lost")
        return deepcopy(order)
