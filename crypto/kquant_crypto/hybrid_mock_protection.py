"""Runnable synthetic protection, not a native exchange protection adapter.

Stop gates hold ordinary mock SELL reservations and become fill-eligible only
after an explicitly injected bid trigger. Triggering never manufactures fills.
The fixture venue must survive OMS restarts. No production transport, credential,
clock/quote validation, native OCO, or emergency market liquidation is provided.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_DOWN
import json

from .hybrid_mock_broker import (BrokerRejected, MockBroker, OrderIntent, TERMINAL,
                                 UnknownExecution, decimal, encode, exact_decimal, identity, number, reservation)
from .hybrid_mock_oms import MockOMS

PROTECTION_VERSION = "synthetic_stop_gate_v1"


@dataclass(frozen=True)
class MockEmergencyPolicy:
    policy_id: str
    action: str

    def __post_init__(self):
        if not self.policy_id or self.action not in {"HOLD_AND_ALERT", "CANCEL_ENTRY_REMAINDERS_AND_ALERT"}:
            raise ValueError("explicit mock emergency policy required; automatic liquidation unsupported")


class ProtectiveMockBroker(MockBroker):
    """Mock-only stop eligibility gate backed by normal Spot inventory locks."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.protection_gates = {}
        self.protection_fault = False

    def get_capabilities(self):
        return {**super().get_capabilities(), "mock_stop_gate": True,
                "native_protection_status": "UNKNOWN_UNVERIFIED", "trigger_fill_guarantee": False}

    def register_protection(self, intent, stop_price):
        stop = decimal(stop_price)
        rule = self.rules[intent.symbol]
        if (intent.side != "SELL" or intent.time_in_force != "GTC" or stop < decimal(intent.limit_price)
                or stop % decimal(rule.tick_size) or stop <= 0):
            raise BrokerRejected("invalid synthetic stop-limit protection")
        cid = self.client_id(intent.intent_id)
        configuration = {"intent": asdict(intent), "stop_price": number(stop)}
        old = self.protection_gates.get(cid)
        if old:
            if old["configuration"] != configuration:
                raise BrokerRejected("immutable protection identity conflict")
            return
        if cid in self.orders:
            raise BrokerRejected("cannot retroactively label an ordinary order protected")
        self.protection_gates[cid] = {"configuration": configuration, "triggered": False, "observations": {}}

    def submit_order(self, intent, *, now):
        if self.client_id(intent.intent_id) in self.protection_gates and self.protection_fault:
            self.protection_fault = False
            raise BrokerRejected("injected mock protection rejection")
        return super().submit_order(intent, now=now)

    def trigger_protection(self, client_order_id, *, bid, observation_id):
        self._online()
        if not isinstance(observation_id, str) or not observation_id or decimal(bid) <= 0:
            raise ValueError("explicit synthetic bid observation required")
        gate = self.protection_gates[client_order_id]
        value = number(bid)
        old = gate["observations"].get(observation_id)
        if old is not None and old != value:
            raise ValueError("conflicting synthetic observation identity")
        gate["observations"][observation_id] = value
        if self.orders[client_order_id]["status"] not in TERMINAL and decimal(bid) <= decimal(gate["configuration"]["stop_price"]):
            gate["triggered"] = True
        return {"client_order_id": client_order_id, "triggered": gate["triggered"],
                "fill_guaranteed": False, "scope": PROTECTION_VERSION}

    def fill_order(self, client_order_id, **kwargs):
        gate = self.protection_gates.get(client_order_id)
        if gate and not gate["triggered"]:
            raise BrokerRejected("mock protection is not triggered")
        return super().fill_order(client_order_id, **kwargs)


class MockProtection:
    def __init__(self, oms, prices, *, admission_until, emergency_policy):
        if not isinstance(oms, MockOMS) or not isinstance(oms.broker, ProtectiveMockBroker):
            raise TypeError("isolated protective mock broker and OMS required")
        if not isinstance(emergency_policy, MockEmergencyPolicy):
            raise ValueError("explicit mock emergency policy required")
        if type(admission_until) is not int or admission_until < 0 or not prices or set(prices) != set(oms.broker.rules):
            raise ValueError("explicit admission expiry and all fixture-symbol protection prices required")
        normalized = {}
        for symbol, values in prices.items():
            stop, limit = decimal(values["stop_price"]), decimal(values["limit_price"])
            tick = decimal(oms.broker.rules[symbol].tick_size)
            if not 0 < limit <= stop or stop % tick or limit % tick:
                raise ValueError("invalid frozen mock stop/limit prices")
            normalized[symbol] = {"stop_price": number(stop), "limit_price": number(limit)}
        self.oms, self.broker = oms, oms.broker
        binding = {"version": PROTECTION_VERSION, "prices": normalized, "admission_until": admission_until,
                   "emergency_policy": asdict(emergency_policy), "venue": self.broker.binding}
        row = oms.db.execute("SELECT value FROM mock_meta WHERE key='protection_state'").fetchone()
        if row:
            self.state = json.loads(row[0])
            if self.state["binding"] != binding:
                raise ValueError("protection policy/expiry/venue binding mismatch")
        else:
            self.state = {"binding": binding, "serial": 0, "tickets": [], "exiting": [],
                          "failure_latched": False, "alerts": []}
        self._guard(True, "startup_protection_reconciliation")

    def _guard(self, blocked, reason):
        guard = {"blocked": blocked, "reason": reason, "admission_until": self.state["binding"]["admission_until"]}
        with self.oms.transaction():
            self.oms.db.execute("INSERT INTO mock_meta VALUES('protection_state',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (encode(self.state),))
            self.oms.db.execute("INSERT INTO mock_meta VALUES('risk_guard',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (encode(guard),))

    def _order(self, ticket):
        try:
            return self.oms.order(ticket["intent"]["intent_id"])
        except KeyError:
            return None

    @exact_decimal
    def _quantity(self, symbol):
        rule = self.broker.rules[symbol]
        free = decimal(self.oms.account()[rule.base]["free"])
        fee_factor = 1 + decimal(self.broker.fee_rate) if self.broker.fee_asset == "base" else Decimal(1)
        step = decimal(rule.step_size)
        units = (free / (fee_factor * step)).to_integral_value(rounding=ROUND_DOWN)
        return number(units * step)

    def _ticket(self, symbol, quantity, price, kind):
        self.state["serial"] += 1
        iid = identity(kind, [self.state["binding"], symbol, self.state["serial"]])
        intent = OrderIntent(iid, symbol, "SELL", quantity, price, self.broker.rules[symbol].rule_hash)
        ticket = {"kind": kind, "intent": asdict(intent)}
        self.state["tickets"].append(ticket)
        self._guard(True, "pending_" + kind)  # Persist identity before local stage/external fixture call.
        return ticket

    def _submit(self, ticket, now):
        intent = OrderIntent(**ticket["intent"])
        if ticket["kind"] == "protection":
            self.broker.register_protection(intent, self.state["binding"]["prices"][intent.symbol]["stop_price"])
        order = self._order(ticket)
        if order is None:
            order = self.oms.stage(intent, now=now)
        if order["state"] == "RESERVED":
            order = self.oms.dispatch(intent.intent_id, now=now)
        elif order["state"] not in TERMINAL:
            order = self.oms.sync_order(intent.intent_id)
        if order["state"] not in {"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "CANCELED", "EXPIRED"}:
            raise BrokerRejected("protection/exit not confirmed: " + order["state"])
        return order

    def _failure(self, reason):
        self.state["failure_latched"] = True
        self.state["alerts"].append({"reason": reason, "action": self.state["binding"]["emergency_policy"]["action"],
                                      "delivered_to_owner": False})
        self._guard(True, "protection_failure_latched")
        if self.state["binding"]["emergency_policy"]["action"] == "CANCEL_ENTRY_REMAINDERS_AND_ALERT":
            for order in self.oms.status()["orders"]:
                if order["payload"]["side"] == "BUY" and order["state"] not in TERMINAL:
                    self.oms.cancel(order["intent_id"])
        # Existing protective SELLs are never canceled by the emergency handler.
        return self.status()

    @exact_decimal
    def _uncovered(self):
        covered = {r.base: Decimal(0) for r in self.broker.rules.values()}
        for ticket in self.state["tickets"]:
            order = self._order(ticket)
            if ticket["kind"] != "protection" or not order or order["state"] not in {"ACKNOWLEDGED", "PARTIALLY_FILLED"}:
                continue
            if order["client_id"] not in self.broker.protection_gates:
                continue
            intent = OrderIntent(**ticket["intent"])
            asset, amount = reservation(intent, decimal(intent.quantity) - decimal(order["filled"]),
                                        self.broker.rules[intent.symbol], self.broker.fee_rate, self.broker.fee_asset)
            covered[asset] += amount
        return {asset: number(max(Decimal(0), decimal(self.oms.account()[asset]["total"]) - amount))
                for asset, amount in covered.items()}

    def reconcile_and_protect(self, *, now):
        self._guard(True, "protection_reconciliation")
        if not self.oms.recover()["ready"]:
            return self.status()
        if self.state["failure_latched"]:
            self._guard(True, "protection_failure_latched")
            return self.status()
        try:
            for ticket in self.state["tickets"]:
                if ticket["kind"] == "protection" and ticket["intent"]["symbol"] in self.state["exiting"]:
                    continue
                order = self._order(ticket)
                if order is None or order["state"] == "RESERVED":
                    self._submit(ticket, now)
            for symbol, prices in self.state["binding"]["prices"].items():
                if symbol in self.state["exiting"]:
                    continue
                rule = self.broker.rules[symbol]
                free = decimal(self.oms.account()[rule.base]["free"])
                if free > 0:
                    quantity = self._quantity(symbol)
                    ticket = self._ticket(symbol, quantity, prices["limit_price"], "protection")
                    self._submit(ticket, now)
        except (BrokerRejected, UnknownExecution) as exc:
            return self._failure(str(exc))
        uncovered = any(decimal(value) > 0 for value in self._uncovered().values())
        triggered = any(g["triggered"] and self.broker.orders.get(cid, {}).get("status") not in TERMINAL
                        for cid, g in self.broker.protection_gates.items())
        blocked = uncovered or triggered or bool(self.state["exiting"]) or now > self.state["binding"]["admission_until"]
        self._guard(blocked, "uncovered_triggered_exiting_or_expired" if blocked else "mock_protection_confirmed")
        return self.status()

    def on_fill(self, fill, *, now):
        self.oms.apply_fill(fill)
        return self.reconcile_and_protect(now=now)

    def trigger(self, symbol, *, bid, observation_id):
        results = []
        for ticket in self.state["tickets"]:
            order = self._order(ticket)
            if (ticket["kind"] == "protection" and ticket["intent"]["symbol"] == symbol and order
                    and order["state"] not in TERMINAL):
                results.append(self.broker.trigger_protection(order["client_id"], bid=bid, observation_id=observation_id))
        if any(r["triggered"] for r in results):
            self._guard(True, "mock_protection_triggered_no_fill_guarantee")
        return results

    def strategy_exit(self, symbol, *, limit_price, now):
        if symbol not in self.state["binding"]["prices"]:
            raise ValueError("unsupported exit symbol")
        price = number(limit_price)
        if symbol not in self.state["exiting"]:
            self.state["exiting"].append(symbol)
        self._guard(True, "strategy_exit_reconciliation")
        # Settle entry remainders first, then cancel protection and query actual fills.
        for order in self.oms.status()["orders"]:
            if order["payload"]["symbol"] == symbol and order["payload"]["side"] == "BUY" and order["state"] not in TERMINAL:
                if self.oms.cancel(order["intent_id"])["state"] not in TERMINAL:
                    return self.status()
        for ticket in self.state["tickets"]:
            if ticket["intent"]["symbol"] != symbol:
                continue
            order = self._order(ticket)
            if ticket["kind"] == "strategy_exit":
                if ticket["intent"]["limit_price"] != price:
                    raise ValueError("exit retry cannot change the frozen price")
                if order is None or order["state"] == "RESERVED":
                    if self.oms.recover()["ready"]:
                        self._submit(ticket, now)
                elif order["state"] not in TERMINAL:
                    self.oms.sync_order(order["intent_id"])
                return self.status()
            if order and order["state"] not in TERMINAL:
                if self.oms.cancel(order["intent_id"])["state"] not in TERMINAL:
                    return self.status()
        if not self.oms.recover()["ready"]:
            return self.status()
        if decimal(self._quantity(symbol)) == 0:
            return self.status()
        ticket = self._ticket(symbol, self._quantity(symbol), price, "strategy_exit")
        try:
            self._submit(ticket, now)
        except (BrokerRejected, UnknownExecution) as exc:
            return self._failure(str(exc))
        return self.status()

    def status(self):
        return {"scope": PROTECTION_VERSION, "guard": self.oms.risk_guard(), "state": deepcopy(self.state),
                "account": self.oms.account(), "uncovered_inventory": self._uncovered(),
                "native_protection_status": "UNKNOWN_UNVERIFIED",
                "trigger_guarantees_fill": False, "G8": "NOT_PASSED"}
