"""Independent durable mock OMS/outbox. Never an external exactly-once claim.

Only MockBroker is accepted. A process-scoped writer lock plus SQLite transactions
protect local state. SUBMITTING/CANCEL_PENDING survive crashes and are QUERY ONLY
on recovery. Unknown/not-found outcomes retain reservations and block new risk.
The caller must keep the mock venue alive across OMS restarts (separate authority).
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3

from .hybrid_mock_broker import (BrokerRejected, MockBroker, OrderIntent, TERMINAL,
                                 UnknownExecution, decimal, encode, exact_decimal, fill_deltas, number, reservation)

TABLES = {"mock_meta", "mock_balances", "mock_outbox", "mock_fills", "mock_events"}
UNCERTAIN = {"SUBMITTING", "UNKNOWN", "CANCEL_PENDING"}
STATES = {"CREATED", "VALIDATED", "RESERVED", "SUBMITTING", "ACKNOWLEDGED", "UNKNOWN",
          "REJECTED", "PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELED", "EXPIRED"}


@contextmanager
def _writer_lock(path):
    file = path.open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            file.seek(0, os.SEEK_END)
            if file.tell() == 0:
                file.write(b"0")
                file.flush()
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
        yield
    finally:
        if locked:
            if os.name == "nt":
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file, fcntl.LOCK_UN)
        file.close()


class MockOMS:
    def __init__(self, path, broker):
        if not isinstance(broker, MockBroker):
            raise TypeError("isolated MockBroker required; no production transport accepted")
        self.broker = broker
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = _writer_lock(self.path.with_suffix(self.path.suffix + ".writer.lock"))
        self._lock.__enter__()
        self.db = None
        self.ready = False
        self.reason = "startup_reconciliation_required"
        try:
            self.db = sqlite3.connect(self.path, timeout=1, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            tables = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables - TABLES:
                raise ValueError("mock OMS requires a dedicated database")
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS mock_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS mock_balances (asset TEXT PRIMARY KEY, amount TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS mock_outbox (
                    intent_id TEXT PRIMARY KEY, client_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
                    state TEXT NOT NULL, filled TEXT NOT NULL DEFAULT '0', revision INTEGER NOT NULL DEFAULT 0,
                    submitted INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS mock_fills (
                    trade_id TEXT PRIMARY KEY, client_id TEXT NOT NULL REFERENCES mock_outbox(client_id), payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS mock_events (
                    sequence INTEGER PRIMARY KEY, intent_id TEXT NOT NULL, state TEXT NOT NULL, detail TEXT NOT NULL);
            ''')
            binding = encode(broker.binding)
            old = self.db.execute("SELECT value FROM mock_meta WHERE key='binding'").fetchone()
            if old and old[0] != binding:
                raise ValueError("mock execution/rules/epoch/fee binding mismatch; never absorb venue reset")
            if old is None:
                if broker.get_open_orders() or broker.get_fills()["fills"]:
                    raise ValueError("new mock ledger requires a clean fixture venue")
                snapshot = broker.get_account_snapshot()
                with self.transaction():
                    self.db.execute("INSERT INTO mock_meta VALUES('binding',?)", (binding,))
                    self.db.execute("INSERT INTO mock_meta VALUES('fill_cursor','0')")
                    for asset, value in snapshot["balances"].items():
                        self.db.execute("INSERT INTO mock_balances VALUES(?,?)", (asset, value["total"]))
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        if self._lock is not None:
            self._lock.__exit__(None, None, None)
            self._lock = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @contextmanager
    def transaction(self):
        try:
            self.db.execute("BEGIN IMMEDIATE")
            yield
            self.db.execute("COMMIT")
        except BaseException as exc:
            self.ready = False
            self.reason = "transaction_failed_reconcile_before_new_risk"
            try:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
            except sqlite3.Error as rollback_error:
                exc.add_note(f"Rollback also failed: {type(rollback_error).__name__}")
            raise

    def _binding(self):
        old = self.db.execute("SELECT value FROM mock_meta WHERE key='binding'").fetchone()[0]
        if old != encode(self.broker.binding):
            self.ready = False
            raise ValueError("mock execution/rules/epoch/fee binding changed")

    def order(self, intent_id):
        row = self.db.execute("SELECT * FROM mock_outbox WHERE intent_id=?", (intent_id,)).fetchone()
        if row is None:
            raise KeyError(intent_id)
        return {**dict(row), "payload": json.loads(row["payload"])}

    def _state(self, intent_id, state, detail=""):
        if state not in STATES:
            raise ValueError("unknown local OMS state")
        self.db.execute("UPDATE mock_outbox SET state=? WHERE intent_id=?", (state, intent_id))
        self.db.execute("INSERT INTO mock_events(intent_id,state,detail) VALUES(?,?,?)", (intent_id, state, detail))

    def risk_guard(self):
        row = self.db.execute("SELECT value FROM mock_meta WHERE key='risk_guard'").fetchone()
        return json.loads(row[0]) if row else None

    def _admit(self, intent, now):
        guard = self.risk_guard()
        if intent.side == "BUY" and guard and (guard["blocked"] or now > guard["admission_until"]):
            raise BrokerRejected("mock protection/admission guard blocks new risk")

    @exact_decimal
    def account(self):
        balances = {r[0]: decimal(r[1]) for r in self.db.execute("SELECT asset,amount FROM mock_balances")}
        reserved = {}
        for row in self.db.execute("SELECT * FROM mock_outbox"):
            if row["state"] in TERMINAL:
                continue
            intent = OrderIntent(**json.loads(row["payload"]))
            asset, amount = reservation(intent, decimal(intent.quantity) - decimal(row["filled"]),
                                        self.broker.rules[intent.symbol], self.broker.fee_rate, self.broker.fee_asset)
            reserved[asset] = reserved.get(asset, Decimal(0)) + amount
        return {a: {"total": number(v), "reserved": number(reserved.get(a, 0)),
                    "free": number(v - reserved.get(a, 0))} for a, v in balances.items()}

    @exact_decimal
    def stage(self, intent, *, now):
        self._binding()
        payload = encode(asdict(intent))
        existing = self.db.execute("SELECT payload FROM mock_outbox WHERE intent_id=?", (intent.intent_id,)).fetchone()
        if existing:
            if existing[0] != payload:
                raise ValueError("intent ID cannot be reused for another economic instruction")
            return self.order(intent.intent_id)
        if not self.ready or self.db.execute("SELECT 1 FROM mock_outbox WHERE state IN ('UNKNOWN','SUBMITTING','CANCEL_PENDING')").fetchone():
            raise RuntimeError("reconciliation/UNKNOWN blocks new intents")
        self._admit(intent, now)
        rule = self.broker.rules[intent.symbol]
        rule.validate(intent, now)
        asset, amount = reservation(intent, intent.quantity, rule, self.broker.fee_rate, self.broker.fee_asset)
        with self.transaction():
            if amount > decimal(self.account().get(asset, {"free": "0"})["free"]):
                raise BrokerRejected("insufficient unreserved balance")
            self.db.execute("INSERT INTO mock_outbox(intent_id,client_id,payload,state) VALUES(?,?,?,'CREATED')",
                            (intent.intent_id, self.broker.client_id(intent.intent_id), payload))
            for state in ("CREATED", "VALIDATED", "RESERVED"):
                self._state(intent.intent_id, state)
        return self.order(intent.intent_id)

    def dispatch(self, intent_id, *, now):
        self._binding()
        order = self.order(intent_id)
        if order["state"] != "RESERVED":
            if not order["submitted"]:
                return order
            return self.sync_order(intent_id)  # Includes UNKNOWN: query only, no blind submit.
        if not self.ready:
            raise RuntimeError("recover before dispatch")
        self._admit(OrderIntent(**order["payload"]), now)
        with self.transaction():
            self._state(intent_id, "SUBMITTING")
            self.db.execute("UPDATE mock_outbox SET submitted=1 WHERE intent_id=?", (intent_id,))
        try:
            ack = self.broker.submit_order(OrderIntent(**order["payload"]), now=now)
        except UnknownExecution as exc:
            with self.transaction():
                self._state(intent_id, "UNKNOWN", str(exc))
            self.ready = False
        except BrokerRejected as exc:
            with self.transaction():
                self._state(intent_id, "REJECTED", str(exc))
        else:
            with self.transaction():
                self._ack(intent_id, ack)
        return self.order(intent_id)

    def _ack(self, intent_id, ack):
        local = self.order(intent_id)
        expected_id = self.broker.client_id(intent_id)
        if (ack["client_order_id"] != expected_id or ack["intent"] != local["payload"]
                or ack["exchange_order_id"] != self.broker.orders[expected_id]["exchange_order_id"]):
            raise ValueError("order acknowledgement identity mismatch")
        if ack["revision"] < local["revision"]:
            return
        self.db.execute("UPDATE mock_outbox SET revision=? WHERE intent_id=?", (ack["revision"], intent_id))
        executed = decimal(ack["executed_quantity"])
        filled = decimal(local["filled"])
        if executed != filled:
            self._state(intent_id, "UNKNOWN", "ACK cumulative quantity requires individual fill reconciliation")
            self.ready = False
        else:
            self._state(intent_id, ack["status"], "acknowledgement; no synthetic fill inferred")

    @exact_decimal
    def _fill(self, fill):
        encoded = encode(fill)
        old = self.db.execute("SELECT payload FROM mock_fills WHERE trade_id=?", (fill["exchange_trade_id"],)).fetchone()
        if old:
            if old[0] != encoded:
                raise ValueError("conflicting duplicate trade ID")
            return False
        row = self.db.execute("SELECT intent_id FROM mock_outbox WHERE client_id=?", (fill["client_order_id"],)).fetchone()
        if row is None:
            raise ValueError("unmanaged fill; manual/external trade must not be silently absorbed")
        order = self.order(row[0])
        intent = OrderIntent(**order["payload"])
        rules = self.broker.rules[intent.symbol]
        q, p = decimal(fill["quantity"]), decimal(fill["price"])
        expected = next((f for f in self.broker.get_fills()["fills"] if f["exchange_trade_id"] == fill["exchange_trade_id"]), None)
        if (expected != fill or fill["epoch"] != self.broker.epoch or fill["symbol"] != intent.symbol
                or fill["side"] != intent.side or q <= 0 or p <= 0
                or decimal(order["filled"]) + q > decimal(intent.quantity)):
            raise ValueError("fill does not match authoritative fixture or order")
        self.db.execute("INSERT INTO mock_fills VALUES(?,?,?)", (fill["exchange_trade_id"], fill["client_order_id"], encoded))
        for asset, change in fill_deltas(fill, rules).items():
            balance = self.db.execute("SELECT amount FROM mock_balances WHERE asset=?", (asset,)).fetchone()
            amount = (decimal(balance[0]) if balance else Decimal(0)) + change
            if amount < 0:
                raise ValueError("negative ledger balance")
            self.db.execute("INSERT INTO mock_balances VALUES(?,?) ON CONFLICT(asset) DO UPDATE SET amount=excluded.amount", (asset, number(amount)))
        filled = decimal(order["filled"]) + q
        self.db.execute("UPDATE mock_outbox SET filled=? WHERE intent_id=?", (number(filled), intent.intent_id))
        # An unseen partial fill may arrive after a cancel ACK; cancellation stays terminal.
        state = "FILLED" if filled == decimal(intent.quantity) else (order["state"] if order["state"] in TERMINAL else "PARTIALLY_FILLED")
        self._state(intent.intent_id, state, "individual fill applied; protection required, not installed")
        guard = self.risk_guard()
        if intent.side == "BUY" and guard:
            guard.update(blocked=True, reason="new_partial_inventory_requires_protection")
            self.db.execute("UPDATE mock_meta SET value=? WHERE key='risk_guard'", (encode(guard),))
        self.account()  # Validate free + reserved = total, including pending orders.
        return True

    def apply_fill(self, fill):
        self._binding()
        with self.transaction():
            return self._fill(fill)

    def sync_order(self, intent_id):
        self._binding()
        order = self.order(intent_id)
        if not order["submitted"] or order["state"] == "REJECTED":
            return order
        try:
            ack = self.broker.get_order(order["client_id"])
            fills = self.broker.get_fills()
        except UnknownExecution:
            ack, fills = None, {"fills": []}
        with self.transaction():
            for fill in fills["fills"]:
                if fill["client_order_id"] == order["client_id"]:
                    self._fill(fill)
            if ack is None:
                self._state(intent_id, "UNKNOWN", "query missing/failed is not proof of rejection; reservation retained")
                self.ready = False
            else:
                self._ack(intent_id, ack)
        return self.order(intent_id)

    def cancel(self, intent_id):
        self._binding()
        order = self.order(intent_id)
        if order["state"] == "RESERVED":
            with self.transaction():
                self._state(intent_id, "CANCELED", "unsent local reservation canceled")
            return self.order(intent_id)
        if order["state"] in UNCERTAIN or order["state"] in TERMINAL:
            return self.sync_order(intent_id)
        with self.transaction():
            self._state(intent_id, "CANCEL_PENDING")
        try:
            self.broker.cancel_order(order["client_id"])
        except UnknownExecution as exc:
            with self.transaction():
                self._state(intent_id, "UNKNOWN", str(exc))
            self.ready = False
            return self.order(intent_id)
        return self.sync_order(intent_id)

    def recover(self):
        self.ready = False
        self._binding()
        for row in self.db.execute("SELECT intent_id FROM mock_outbox").fetchall():
            if self.order(row[0])["state"] != "RESERVED":
                self.sync_order(row[0])
        try:
            snapshot = self.broker.get_account_snapshot()
            fills = self.broker.get_fills()
            open_orders = self.broker.get_open_orders()
        except UnknownExecution:
            self.reason = "venue_unavailable"
            return self.status()
        tracked = {r[0] for r in self.db.execute("SELECT trade_id FROM mock_fills")}
        local = {a: v["total"] for a, v in self.account().items()}
        remote = {a: v["total"] for a, v in snapshot["balances"].items()}
        unknown = self.db.execute("SELECT 1 FROM mock_outbox WHERE state IN ('UNKNOWN','SUBMITTING','CANCEL_PENDING')").fetchone()
        unmatched = sorted(f["exchange_trade_id"] for f in fills["fills"] if f["exchange_trade_id"] not in tracked)
        unmanaged = sorted(o["client_order_id"] for o in open_orders if not self.db.execute(
            "SELECT 1 FROM mock_outbox WHERE client_id=?", (o["client_order_id"],)).fetchone())
        balances_match = set(local) == set(remote) and all(decimal(local[a]) == decimal(remote[a]) for a in local)
        self.ready = not (unknown or unmatched or unmanaged) and balances_match
        self.reason = "reconciled_mock_only" if self.ready else "UNKNOWN_or_account_fill_order_mismatch"
        differences = {'scope': 'ISOLATED_MOCK_ONLY', 'epoch': snapshot['epoch'],
            'balance_differences': [{'asset': a, 'local_total': local.get(a), 'venue_total': remote.get(a)}
                for a in sorted(set(local) | set(remote))
                if a not in local or a not in remote or decimal(local[a]) != decimal(remote[a])],
            'unmatched_fill_ids': unmatched, 'unmanaged_order_ids': unmanaged,
            'unknown_orders_present': bool(unknown), 'consistent': self.ready,
            'market_pnl_inferred': False, 'automatic_balance_adjustment': False}
        with self.transaction():
            self.db.execute("INSERT OR REPLACE INTO mock_meta VALUES('last_reconciliation',?)", (encode(differences),))
            self.db.execute("INSERT INTO mock_events(intent_id,state,detail) VALUES(?,?,?)",
                            ('', 'RECONCILIATION', encode(differences)))
            if self.ready:
                self.db.execute("UPDATE mock_meta SET value=? WHERE key='fill_cursor'", (str(fills["cursor"]),))
        return self.status()

    def status(self):
        reconciliation = self.db.execute("SELECT value FROM mock_meta WHERE key='last_reconciliation'").fetchone()
        return {"ready": self.ready, "reason": self.reason, "account": self.account(),
                "last_reconciliation": json.loads(reconciliation[0]) if reconciliation else None,
                "orders": [self.order(r[0]) for r in self.db.execute("SELECT intent_id FROM mock_outbox")],
                "fill_cursor": int(self.db.execute("SELECT value FROM mock_meta WHERE key='fill_cursor'").fetchone()[0]),
                "risk_guard": self.risk_guard(), "protection_installed": False,
                "evidence_scope": "ISOLATED_MOCK_ONLY", "G8": "NOT_PASSED"}
