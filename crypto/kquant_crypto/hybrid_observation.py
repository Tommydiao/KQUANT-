"""Isolated, replayable label observer. No network, model or order dependencies.

Quotes without independently evidenced source time/size are retained but cannot
fill. The unchanged candidate portfolio owns all prices, costs and protection.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sqlite3

from .candidate_policy import digest
from .candidate_simulation import CandidatePortfolio
from .hybrid_contracts import DecisionTimeline
from .hybrid_features import snapshot as feature_snapshot
from .strategy_dual_mode_v1 import Bar

POLICY = {
    "version": "hybrid_quote_observer_m2_v1",
    "label_execution_policy_id": "QUOTE_AWARE_BASE_10_2_STRICT_SOURCE_TIME",
    "execution_quality": "observed_bbo_virtual_not_exchange_fill",
    "delay_basis": "PREREGISTERED_SIMULATED_DELAY_NOT_MEASURED_MODEL_LATENCY",
    "simulated_delay_seconds": 4,
    "entry_expiry_seconds": 30,
    "quote_max_age_seconds": 30,
    "size_policy": "full_reserved_quantity_both_sides_or_abstain",
    "training_enabled": False,
    "filtering_enabled": False,
    "executable": False,
}


def finite(value):
    return not isinstance(value, bool) and isinstance(value, (float, int)) and math.isfinite(value)


def legacy_state(opportunity, label):
    """New projection, never changes the frozen legacy label or fills a non-fill."""
    trade = label.get("executed_trade")
    return {
        "economic_signal_id": opportunity["economic_signal_id"],
        "symbol": opportunity["symbol"], "mode": opportunity["mode"],
        "signal_time": opportunity["signal_time"],
        "fill_status": "FILLED" if trade else "UNFILLED",
        "label_status": label["status"].upper() if trade else "NOT_APPLICABLE_UNFILLED",
        "entry_attempted": "SIGNAL_RESERVED" in opportunity["original_reasons"],
        "reasons": opportunity["original_reasons"],
        "outcome_reason": label["reason"],
        "net_r": label["net_r"] if trade else None,
        "label_available_at": label["label_available_at"] if "label_available_at" in label else label.get("available_at"),
        "label_execution_policy_id": "LEGACY_BAR_PROXY_BASE_10_5",
        "execution_quality": "LEGACY_BAR_PROXY",
        "label_source": label["source"],
        "legacy_label_hash": label["label_hash"],
        "counterfactual": False,
        "received_at": None, "feature_snapshot_frozen_at": None,
        "evaluation_finished_at": None, "decision_committed_at": None, "earliest_fill_at": None,
        "time_basis": "LEGACY_MARKET_CLOSE_ASSUMPTION_NO_MEASURED_DECISION_CLOCK",
    }


class Observer:
    def __init__(self, policy, rules, state=None):
        self.portfolio = CandidatePortfolio(policy, rules, execution="quotes")
        self.opportunities = {}
        self.watermarks = {}
        self.audit = []
        if state:
            self.portfolio.restore(state["portfolio"])
            self.opportunities = deepcopy(state["opportunities"])
            self.watermarks = deepcopy(state["watermarks"])

    def state(self):
        return {"portfolio": self.portfolio.snapshot(),
                "opportunities": deepcopy(self.opportunities), "watermarks": deepcopy(self.watermarks)}

    def _note(self, reason, event, **extra):
        self.audit.append({"reason": reason, "input_hash": digest(event), **extra})

    def _results(self):
        drained = self.portfolio.drain()
        for trade in drained["trades"]:
            item = next((o for o in self.opportunities.values() if o.get("trade_id") == trade["trade_id"]), None)
            if item is None:
                raise ValueError("Unbound virtual trade")
            risk = trade["quantity"] * trade["unit_net_risk"]
            if risk <= 0 or not math.isclose(trade["net_r"], trade["net_pnl"] / risk, rel_tol=1e-12):
                raise ValueError("BASE denominator changed")
            censored = item.get("path_unverifiable") or trade.get("path_unverifiable")
            item.update(fill_status="FILLED", label_status="CENSORED" if censored else "MATURE",
                        net_r=None if censored else trade["net_r"], descriptive_net_r=trade["net_r"],
                        label_available_at=trade["exit_time"], outcome_reason=trade["exit_reason"],
                        trade=trade)
        for item in self.opportunities.values():
            symbol = item["symbol"]
            position = self.portfolio.positions.get(symbol)
            if position and position["trade_id"] == item.get("trade_id"):
                item.update(fill_status="FILLED", label_status="CENSORED" if item.get("path_unverifiable") else "PENDING",
                            entry_time=position["entry_time"], quantity=position["quantity"],
                            base_risk_denominator=position["risk_amount"])
            elif item['fill_status'] == 'AWAITING_QUOTE' and symbol not in self.portfolio.pending:
                reasons = [r.get('reason', r['kind']) for r in drained['events'] if r.get('symbol') == symbol]
                item.update(fill_status='UNFILLED', label_status='NOT_APPLICABLE_UNFILLED',
                            outcome_reason=reasons[-1] if reasons else 'original_pending_canceled')
        self.audit.extend(drained["events"])

    def closed_batch(self, event):
        now = event["received_at"]
        five = {s: Bar(**b) for s, b in event["five"].items()}
        hourly = {s: Bar(**b) for s, b in event.get("hourly", {}).items()}
        closes = {b.start + 300 for b in five.values()}
        if len(closes) != 1 or not finite(now):
            raise ValueError("Common closed batch required")
        close = next(iter(closes))
        if now < close:
            raise ValueError("Forming candle")
        if close <= self.watermarks.get("bar", -1):
            self._note("old_closed_batch_no_replay", event)
            return
        if self.watermarks.get("bar") and close != self.watermarks["bar"] + 300:
            self.disconnected({"received_at": now, "reason": "closed_bar_gap"})
        if close % 3600 == 0:
            from .candidate_forward import aggregate_hour
            for symbol, current in five.items():
                parts = self.portfolio.kernels[symbol].five_bars[-11:] + [current]
                derived = aggregate_hour(parts)
                if symbol in hourly and hourly[symbol] != derived:
                    raise ValueError('Unproven hourly aggregation')
                hourly[symbol] = derived
        fresh = 0 <= now - close <= POLICY["entry_expiry_seconds"]
        complete = set(five) == set(self.portfolio.policy["symbols"])
        self.portfolio.on_closed_batch(five, hourly, int(now), allow_entries=fresh and complete)
        self.watermarks["bar"] = close
        for symbol in five:
            decision = self.portfolio.decisions.get(symbol, {})
            if not decision.get("signal"):
                continue
            feature = feature_snapshot(self.portfolio, symbol, available_at=now)
            feature['availability_basis'] = 'observed_closed_batch_receipt'
            feature['snapshot_hash'] = digest({k: v for k, v in feature.items() if k != 'snapshot_hash'})
            if not feature:
                continue
            identity = feature["economic_signal_id"]
            if identity in self.opportunities:
                continue
            pending = self.portfolio.pending.get(symbol)
            reserved = pending is not None and pending["signal_time"] == close
            commit = now + POLICY["simulated_delay_seconds"]
            timeline = None
            if commit < close + 30:
                timeline = asdict(DecisionTimeline(close, now, now, now, commit, commit, commit, close + 30))
            if reserved and timeline is None:
                del self.portfolio.pending[symbol]
                reserved = False
            self.opportunities[identity] = {
                "economic_signal_id": identity, "symbol": symbol, "mode": decision["signal"]["mode"],
                "signal_time": close, "available_at": now, "feature_snapshot": feature,
                "feature_snapshot_frozen_at": now, "timeline": timeline,
                "delay_basis": POLICY["delay_basis"], "entry_attempted": reserved,
                "clock_basis": "LOGICAL_SIMULATED_DELAY_WITH_PHYSICAL_COMMIT_LOWER_BOUND",
                "requires_commit_observation": event.get('requires_commit_observation',False),
                "physical_decision_commit_observed_at": None,
                "trade_id": pending["trade_id"] if reserved else None,
                "fill_status": "AWAITING_QUOTE" if reserved else "UNFILLED",
                "label_status": "PENDING_ENTRY" if reserved else "NOT_APPLICABLE_UNFILLED",
                "outcome_reason": None if reserved else "original_entry_gate_or_expired_decision",
                "label_source": "executed_virtual", "net_r": None,
                "label_execution_policy_id": POLICY["label_execution_policy_id"],
                "execution_quality": POLICY["execution_quality"], "counterfactual": False,
            }
        self._results()

    def quote(self, event):
        symbol = event.get("symbol")
        if symbol not in self.portfolio.kernels:
            self._note("unsupported_identity", event)
            return
        fields = ("source_time", "received_at", "bid", "ask", "bid_size", "ask_size")
        missing = [k for k in fields if not finite(event.get(k))]
        if missing or event.get("source_time_basis") != "exchange_event_time":
            self._note("missing_proven_quote_fields", event, missing=missing,
                       source_time_basis=event.get("source_time_basis"))
            return
        source, receipt = event["source_time"], event["received_at"]
        seq = event.get("sequence")
        if source > receipt:
            self._note('source_time_after_receipt_clock_conflict', event, source_minus_receipt=source-receipt)
            return
        if (event.get("venue") != "binance" or event.get("market_type") != "spot"
                or event.get("provider_status") != "live" or not event.get("source")
                or type(seq) is not int or seq < 0
                or source < 0 or not 0 <= receipt-source <= POLICY["quote_max_age_seconds"]
                or not 0 < event["bid"] <= event["ask"] or min(event["bid_size"], event["ask_size"]) <= 0):
            self._note("invalid_or_stale_quote", event)
            return
        previous = self.watermarks.get(symbol, {})
        if seq <= previous.get("sequence", -1) or receipt <= previous.get("received_at", -1) or source < previous.get("source_time", -1):
            self._note("out_of_order_quote", event)
            return
        if previous and receipt-previous['received_at'] > POLICY['quote_max_age_seconds'] and symbol in self.portfolio.positions:
            self.disconnected({'received_at':receipt,'reason':'quote_observation_gap'})
        self.watermarks[symbol] = {"sequence": seq, "received_at": receipt, "source_time": source}
        item = next((o for o in self.opportunities.values() if o["symbol"] == symbol and
                     o["fill_status"] == "AWAITING_QUOTE"), None)
        pending = self.portfolio.pending.get(symbol)
        held = self.portfolio.positions.get(symbol)
        if pending and item is None:
            raise ValueError('Pending plan lacks bound decision timeline')
        if held and source <= held["entry_time"]:
            self._note("protection_quote_precedes_entry", event)
            return
        if item and pending:
            if item.get('requires_commit_observation') and item.get('physical_decision_commit_observed_at') is None:
                self._note('decision_commit_not_observed', event)
                return
            timeline = DecisionTimeline(**item["timeline"])
            if receipt > timeline.signal_expires_at:
                del self.portfolio.pending[symbol]
                item.update(fill_status="UNFILLED", label_status="NOT_APPLICABLE_UNFILLED",
                            outcome_reason="no_eligible_quote_before_expiry", label_available_at=receipt)
            elif not timeline.permits_fill(source, receipt):
                self._note("quote_before_decision_commit", event)
                return
            elif min(event["bid_size"], event["ask_size"]) < pending["quantity"]:
                self._note("insufficient_quote_quantity", event)
                return
            else:
                item["entry_quote"] = deepcopy(event)
        if held and event["bid_size"] < held["quantity"]:
            self.disconnected({"received_at": receipt, "reason": "exit_size_unavailable"})
            self._note("insufficient_exit_quantity", event)
            return
        self.portfolio.on_quote(symbol, event["bid"], event["ask"], receipt, seq)
        self._results()
        for row in self.opportunities.values():
            if row.get("trade", {}).get("exit_time") == receipt:
                row["exit_quote"] = deepcopy(event)
        self._note("valid_quote_consumed", event)

    def disconnected(self, event):
        now = event["received_at"]
        self.portfolio.accept_entries = False
        self.portfolio.pending.clear()
        for item in self.opportunities.values():
            if item["fill_status"] == "AWAITING_QUOTE":
                item.update(fill_status="UNFILLED", label_status="NOT_APPLICABLE_UNFILLED",
                            outcome_reason=event.get("reason", "disconnected"), label_available_at=now)
            elif item["fill_status"] == "FILLED" and item["label_status"] in ("PENDING", "CENSORED"):
                item.update(path_unverifiable=True, label_status="CENSORED", net_r=None,
                            outcome_reason="missing_observation_path", label_available_at=now)
        self._note("observation_interrupted_no_fabricated_liquidation", event)

    def clock(self, event):
        now = event["received_at"]
        if any(now-self.watermarks.get(s,{}).get('received_at',float('-inf')) > POLICY['quote_max_age_seconds']
               for s in self.portfolio.positions):
            self.disconnected({'received_at':now,'reason':'quote_observation_gap'})
        for item in self.opportunities.values():
            if item["fill_status"] == "AWAITING_QUOTE" and now > item["timeline"]["signal_expires_at"]:
                self.portfolio.pending.pop(item["symbol"], None)
                item.update(fill_status="UNFILLED", label_status="NOT_APPLICABLE_UNFILLED",
                            outcome_reason="no_eligible_quote_before_expiry", label_available_at=now)
        self._note("clock_advanced", event)

    def warmup(self, event):
        if self.portfolio.positions or self.portfolio.pending or self.watermarks.get('bar'):
            raise ValueError('Warmup may only initialize a new flat observer')
        five = {s: [Bar(**b) for b in series] for s, series in event['five'].items()}
        hourly = {s: {int(t): Bar(**b) for t, b in series.items()} for s, series in event['hourly'].items()}
        if set(five) != set(self.portfolio.kernels) or len({len(v) for v in five.values()}) != 1:
            raise ValueError('Common fixed-universe warmup required')
        for i in range(len(next(iter(five.values())))):
            batch = {s: v[i] for s, v in five.items()}
            close = next(iter(batch.values())).start+300
            hours = {s: hourly[s][close-3600] for s in batch} if close % 3600 == 0 else {}
            self.portfolio.on_closed_batch(batch, hours, close, allow_entries=False)
            if self.portfolio.drain()['trades']:
                raise ValueError('Warmup must not generate trades')
        self.watermarks['bar'] = close
        self._note('public_history_warmup_not_forward_outcomes', event, last_close=close)

    def committed(self,event):
        now=event['received_at']
        if not finite(now):raise ValueError('Physical commit observation required')
        for item in self.opportunities.values():
            if item['signal_time']!=event['signal_time'] or item['fill_status']!='AWAITING_QUOTE':continue
            old=item['timeline']; freeze=max(now,old['feature_snapshot_frozen_at'])
            evaluated=max(freeze,old['evaluation_finished_at'])
            if evaluated>=old['signal_expires_at']:
                self.portfolio.pending.pop(item['symbol'],None)
                item.update(fill_status='UNFILLED',label_status='NOT_APPLICABLE_UNFILLED',
                            outcome_reason='decision_commit_after_expiry',label_available_at=now)
                continue
            timeline=DecisionTimeline(old['signal_time'],old['received_at'],freeze,freeze,
                                      evaluated,evaluated,evaluated,old['signal_expires_at'])
            item.update(timeline=asdict(timeline),physical_decision_commit_observed_at=now,
                        feature_snapshot_frozen_at=freeze)
        self._note('physical_commit_lower_bound_recorded_simulated_delay_retained',event)

    def apply(self, event):
        handlers = {"closed_batch": self.closed_batch, "quote": self.quote,
                    "disconnect": self.disconnected, "observation_end": self.disconnected, "clock": self.clock,
                    "warmup": self.warmup, "commit_observed": self.committed}
        if event["type"] not in handlers:
            raise ValueError("Unsupported observation event")
        handlers[event["type"]](event)


class ObservationStore:
    """Atomic event/checkpoint/immutable label revisions in a new database only."""
    def __init__(self, path, policy, rules):
        path = Path(path).resolve()
        if not path.name.startswith("hybrid_"):
            raise ValueError("Independent hybrid_ database required")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=2)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS observer_contract(id INTEGER PRIMARY KEY CHECK(id=1),hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS observer_events(id TEXT PRIMARY KEY,hash TEXT NOT NULL,payload TEXT NOT NULL,audit TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS observer_checkpoint(id INTEGER PRIMARY KEY CHECK(id=1),state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS observer_labels(signal_id TEXT,version INTEGER,hash TEXT NOT NULL,payload TEXT NOT NULL,
                PRIMARY KEY(signal_id,version),UNIQUE(signal_id,hash));
            CREATE TABLE IF NOT EXISTS legacy_label_revisions(signal_id TEXT,version INTEGER,hash TEXT NOT NULL,
                parent_hash TEXT,source_manifest_hash TEXT NOT NULL,reason TEXT,payload TEXT NOT NULL,
                PRIMARY KEY(signal_id,version),UNIQUE(signal_id,hash));
        """)
        root=Path(__file__).parent
        self.code_hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in
            ('hybrid_observation.py','hybrid_public_observer.py','hybrid_features.py','hybrid_contracts.py',
             'candidate_simulation.py','candidate_policy.py','strategy_dual_mode_v1.py','candidate_forward.py')}
        self.contract = digest({"observer": POLICY, "candidate": policy, "rules": rules,'source_hashes':self.code_hashes})
        old = self.db.execute("SELECT hash FROM observer_contract WHERE id=1").fetchone()
        if old and old[0] != self.contract:
            self.db.close()
            raise ValueError("Frozen observer contract mismatch; create a new database")
        self.db.execute("INSERT OR IGNORE INTO observer_contract VALUES(1,?)", (self.contract,))
        self.db.commit()
        self.policy, self.rules = policy, rules

    def import_legacy(self, row, source_manifest_hash, *, parent_hash=None, correction_reason=None):
        if row['label_execution_policy_id'] != 'LEGACY_BAR_PROXY_BASE_10_5' or row['counterfactual']:
            raise ValueError('Legacy actual population only; do not mix quote or counterfactual labels')
        if row['fill_status'] == 'UNFILLED' and (row['net_r'] is not None or row['label_status'] != 'NOT_APPLICABLE_UNFILLED'):
            raise ValueError('Unfilled opportunity has no return label')
        if not source_manifest_hash or not row.get('legacy_label_hash'):
            raise ValueError('Source manifest and label hashes required')
        sid=row['economic_signal_id']; hashed=digest(row)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            prior=self.db.execute('SELECT version,hash FROM legacy_label_revisions WHERE signal_id=? ORDER BY version DESC LIMIT 1',(sid,)).fetchone()
            if prior and prior[1]==hashed:
                return False
            if prior and (parent_hash!=prior[1] or not correction_reason):
                raise ValueError('Historical corrections require latest parent hash and explicit reason')
            if not prior and parent_hash is not None:
                raise ValueError('Unknown correction parent')
            self.db.execute('INSERT INTO legacy_label_revisions VALUES(?,?,?,?,?,?,?)',
                (sid,prior[0]+1 if prior else 1,hashed,parent_hash,source_manifest_hash,correction_reason,json.dumps(row,sort_keys=True,allow_nan=False)))
        return True

    def process(self, identity, event, *, fail_before_commit=False):
        encoded = json.dumps(event, sort_keys=True, allow_nan=False)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            old = self.db.execute("SELECT hash FROM observer_events WHERE id=?", (identity,)).fetchone()
            if old:
                if old[0] != digest(event):
                    raise ValueError("Immutable input changed; submit an explicit new revision")
                return {"duplicate": True}
            saved = self.db.execute("SELECT state FROM observer_checkpoint WHERE id=1").fetchone()
            observer = Observer(self.policy, self.rules, json.loads(saved[0]) if saved else None)
            observer.apply(event)
            for sid, label in observer.opportunities.items():
                hashed = digest(label)
                prior = self.db.execute("SELECT version,hash FROM observer_labels WHERE signal_id=? ORDER BY version DESC LIMIT 1", (sid,)).fetchone()
                if prior and prior[1] == hashed:
                    continue
                version = prior[0]+1 if prior else 1
                self.db.execute("INSERT INTO observer_labels VALUES(?,?,?,?)", (sid, version, hashed, json.dumps(label, sort_keys=True, allow_nan=False)))
            self.db.execute("INSERT OR REPLACE INTO observer_checkpoint VALUES(1,?)", (json.dumps(observer.state(), sort_keys=True, allow_nan=False),))
            self.db.execute("INSERT INTO observer_events VALUES(?,?,?,?)", (identity, digest(event), encoded, json.dumps(observer.audit, sort_keys=True, allow_nan=False)))
            if fail_before_commit:
                raise sqlite3.OperationalError("injected rollback")
        return {"duplicate": False, "audit": observer.audit}

    def close(self):
        self.db.close()
