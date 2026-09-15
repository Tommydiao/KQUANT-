from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal, ROUND_DOWN
import math

from .candidate_policy import digest
from .strategy_dual_mode_v1 import Bar, DualRegimeKernel


class CandidatePortfolio:
    """Independent virtual cash account. No exchange submission dependencies."""

    def __init__(self, policy: dict, rules: dict, execution: str = "ohlcv", cost_multiplier: int = 1, only_mode: str | None = None):
        if execution not in {"ohlcv", "quotes"} or cost_multiplier not in {1, 2}:
            raise ValueError("Invalid candidate execution scenario")
        self.policy, self.rules = policy, rules
        self.execution, self.cost_multiplier, self.only_mode = execution, cost_multiplier, only_mode
        self.kernels = {s: DualRegimeKernel(candidate=policy["candidate"]) for s in policy["symbols"]}
        self.cash = float(policy["initial_cash"])
        self.positions: dict[str, dict] = {}
        self.pending: dict[str, dict] = {}
        self.exits: dict[str, str] = {}
        self.marks: dict[str, float] = {}
        self.last_bars: dict[str, int] = {}
        self.last_quotes: dict[str, dict] = {}
        self.decisions: dict[str, dict] = {}
        self.day: int | None = None
        self.day_start = self.cash
        self.day_paused = False
        self.pause_until = 0
        self.losses = 0
        self.accept_entries = False
        self.events: list[dict] = []
        self.trades: list[dict] = []
        self.equity: list[dict] = []
        self.count = 0

    @property
    def fee(self) -> float:
        return self.policy["fee_bps"] * self.cost_multiplier / 10000

    @property
    def slippage(self) -> float:
        key = "quote_extra_slippage_bps" if self.execution == "quotes" else "ohlcv_execution_cost_bps"
        return self.policy[key] * self.cost_multiplier / 10000

    def event(self, kind: str, time: float, symbol: str = "", **fields) -> None:
        self.count += 1
        self.events.append({"event_id": str(self.count), "time": time, "symbol": symbol, "kind": kind,
                            "strategy_version":self.policy["strategy_version"],"policy_hash":self.policy["policy_hash"],
                            "data_manifest_hash":self.policy.get("data_manifest_hash"),"evidence_scope":"candidate_simulation",**fields})

    def value(self) -> float:
        return self.cash + sum(p["quantity"] * self.marks.get(s, p["entry_price"]) * (1-self.slippage) * (1-self.fee) for s, p in self.positions.items())

    def _clock(self, time: float, *, force: bool = False) -> None:
        day = int(time) // 86400
        if self.day != day or force:
            self.day, self.day_start, self.day_paused = day, self.value(), False

    def _risk(self, time: float) -> None:
        if self.value() <= self.day_start * (1-self.policy["daily_loss_limit"]):
            if not self.day_paused:
                self.event("DAILY_LOSS_PAUSE", time, equity=self.value())
            self.day_paused = True
            self.exits.update({s: "daily_loss" for s in self.positions})
        if self.day_paused or time < self.pause_until:
            for s in list(self.pending):
                self.event("ENTRY_CANCELED", time, s, reason="risk_pause")
                del self.pending[s]

    def _round_quantity(self, symbol: str, quantity: float) -> float:
        rule = self.rules.get(symbol)
        if not rule:
            return 0.0
        step = Decimal(str(rule["step_size"]))
        if step <= 0:
            return 0.0
        quantity = min(quantity, float(rule.get("max_qty", quantity)))
        return float((Decimal(str(quantity))/step).to_integral_value(rounding=ROUND_DOWN)*step)

    def _reserve(self, symbol: str, signal: dict, time: int) -> None:
        if self.only_mode and signal["mode"] != self.only_mode:
            return
        reason = None
        if symbol in self.positions or symbol in self.pending:
            reason = "already_exposed"
        elif self.day_paused or time < self.pause_until:
            reason = "risk_pause"
        elif len(self.positions) + len(self.pending) >= self.policy["max_positions"]:
            reason = "position_limit"
        elif symbol not in self.rules:
            reason = "rules_unavailable"
        if reason:
            self.event("ENTRY_REJECTED", time, symbol, reason=reason)
            return
        unit = signal["unit_net_risk"]
        equity = self.value()
        risk_used = sum(p.get("estimated_risk_amount",p["risk_amount"]) for p in [*self.positions.values(), *self.pending.values()])
        budget = min(equity*self.policy["risk_per_trade"], equity*self.policy["max_open_risk"]-risk_used)
        reference = signal["entry_reference"]
        cash_reserved = sum(p["reserved_cash"] for p in self.pending.values())
        estimated = reference*(1+self.slippage)*(1+self.fee)
        stressed_stop=signal["stop"]*(1-self.slippage)
        sizing_unit=reference*(1+self.slippage)-stressed_stop+self.fee*(reference*(1+self.slippage)+stressed_stop)
        quantity = self._round_quantity(symbol, min(max(0,budget)/sizing_unit, equity*self.policy["max_symbol_notional"]/estimated, max(0,self.cash-cash_reserved)/estimated))
        rule = self.rules[symbol]
        if quantity < rule["min_qty"] or quantity*reference < rule["min_notional"]:
            self.event("ENTRY_REJECTED", time, symbol, reason="quantity_or_risk_budget")
            return
        sid = digest([self.policy["policy_hash"], symbol, signal["mode"], time])
        self.pending[symbol] = {**signal, "trade_id": sid, "symbol": symbol, "signal_time": time, "quantity": quantity,
                                "risk_amount": quantity*unit, "reserved_cash": quantity*estimated,"sizing_unit_risk":sizing_unit,
                                "estimated_risk_amount":quantity*sizing_unit,
                                "strategy_version":self.policy["strategy_version"],"policy_hash":self.policy["policy_hash"],
                                "data_manifest_hash":self.policy.get("data_manifest_hash"),"evidence_scope":"candidate_simulation",
                                "available_at":self.decisions[symbol]["available_at"],"closed_bar_id":f"binance:spot:{symbol}:5m:{time-300}"}
        self.event("SIGNAL_RESERVED", time, symbol, plan=self.pending[symbol])

    def _enter(self, symbol: str, reference: float, time: float, exit_reference: float | None = None) -> None:
        pending = self.pending.pop(symbol)
        if self.day_paused or time < self.pause_until:
            self.event("ENTRY_CANCELED", time, symbol, reason="risk_pause")
            return
        fill = reference*(1+self.slippage)
        available = self.cash - sum(p["reserved_cash"] for p in self.pending.values())
        quantity = self._round_quantity(symbol, min(pending["quantity"], max(0,available)/(fill*(1+self.fee)), self.value()*self.policy["max_symbol_notional"]/(fill*(1+self.fee))))
        rule = self.rules[symbol]
        if quantity < rule["min_qty"] or quantity*fill < rule["min_notional"]:
            self.event("ENTRY_REJECTED", time, symbol, reason="fill_cash_or_filter", reference=reference)
            return
        fee = quantity*fill*self.fee
        self.cash -= quantity*fill+fee
        position = {**pending, "quantity": quantity, "risk_amount": quantity*pending["unit_net_risk"], "entry_time": time,
                    "estimated_risk_amount":quantity*pending["sizing_unit_risk"],
                    "entry_price": fill, "entry_market_reference": reference, "entry_fee": fee, "bars_held": 0,
                    "expires_at": time+(21600 if pending["mode"] == "UP_TREND" else 10800), "path_unverifiable": False}
        self.positions[symbol] = position
        self.event("VIRTUAL_ENTRY", time, symbol, price=fill, quantity=quantity, trade_id=position["trade_id"])
        # A gap cannot retroactively remove an accepted signal.
        if fill <= position["stop"] or fill >= position["target"]:
            self._exit(symbol, reference if exit_reference is None else exit_reference, time,
                       "entry_gap_stop" if fill <= position["stop"] else "entry_gap_target")

    def _exit(self, symbol: str, reference: float, time: float, reason: str) -> None:
        p = self.positions.pop(symbol)
        fill = reference*(1-self.slippage)
        fee = p["quantity"]*fill*self.fee
        pnl = p["quantity"]*(fill-p["entry_price"])-fee-p["entry_fee"]
        self.cash += p["quantity"]*fill-fee
        trade = {**p, "exit_time": time, "exit_price": fill, "exit_market_reference": reference,
                 "exit_reason": reason, "fees": fee+p["entry_fee"], "net_pnl": pnl, "net_r": pnl/p["risk_amount"],
                 "cost_multiplier": self.cost_multiplier, "execution_source": "quote" if self.execution == "quotes" else "ohlcv",
                 "base_unit_net_risk": p["unit_net_risk"], "fee_bps": self.policy["fee_bps"]*self.cost_multiplier,
                 "execution_cost_bps": self.slippage*10000, "entry_reference":p["entry_market_reference"],
                 "signal_reference":p["entry_reference"], "exit_reference":reference, "base_unit_risk":p["unit_net_risk"],
                 "ohlcv_execution_cost_bps":self.policy["ohlcv_execution_cost_bps"]*self.cost_multiplier,
                 "quote_extra_slippage_bps":self.policy["quote_extra_slippage_bps"]*self.cost_multiplier}
        self.trades.append(trade)
        self.event("VIRTUAL_EXIT", time, symbol, trade_id=p["trade_id"], reason=reason, net_pnl=pnl)
        self.exits.pop(symbol, None)
        self.kernels[symbol].record_exit(int(time), stopped=reason in {"stop", "gap_stop", "entry_gap_stop"}, mode=p["mode"])
        self.losses = self.losses+1 if pnl < 0 else 0
        if self.losses >= self.policy["loss_streak"]:
            self.pause_until = int(time)+self.policy["pause_seconds"]
            self.losses = 0
            self.event("LOSS_STREAK_PAUSE", time, until=self.pause_until)
        self._risk(time)

    def _open_protection(self, symbol: str, bar: Bar) -> None:
        p = self.positions.get(symbol)
        if not p:
            return
        if bar.open <= p["stop"]:
            self._exit(symbol, bar.open, bar.start, "gap_stop")
        elif bar.open >= p["target"]:
            self._exit(symbol, p["target"], bar.start, "gap_target")

    def on_closed_batch(self, bars: dict[str, Bar], hourly: dict[str, Bar], now: int, allow_entries: bool = True) -> None:
        self.accept_entries = allow_entries
        if not allow_entries:
            for symbol in list(self.pending):
                self.event("ENTRY_CANCELED",now,symbol,reason="entries_suppressed")
                del self.pending[symbol]
        bars = {s:b for s,b in bars.items() if s in self.kernels and b.start > self.last_bars.get(s,-1)}
        if not bars:
            return
        start = min(b.start for b in bars.values())
        if self.execution == "ohlcv":
            self.marks.update({s:b.open for s,b in bars.items()})
            self._clock(start,force=start % 86400 == 0)
            for s in self.policy["symbols"]:
                if s not in bars:
                    continue
                b = bars[s]
                gap = s in self.last_bars and b.start != self.last_bars[s]+300
                if gap:
                    self.pending.pop(s, None)
                    if s in self.positions:
                        self.positions[s]["path_unverifiable"] = True
                        self._exit(s, min(b.open,self.positions[s]["stop"]), start,"data_gap")
                self._open_protection(s,b)
            for s in self.policy["symbols"]:
                if s in bars and s in self.exits and s in self.positions:
                    self._exit(s,bars[s].open,start,self.exits[s])
            for s in self.policy["symbols"]:
                if s in bars and s in self.pending:
                    self._enter(s,bars[s].open,start)
            for s in self.policy["symbols"]:
                if s not in bars or s not in self.positions:
                    continue
                b,p = bars[s],self.positions[s]
                if b.low <= p["stop"]:
                    self._exit(s,p["stop"],b.start+300,"stop")
                elif b.high >= p["target"]:
                    self._exit(s,p["target"],b.start+300,"target")
                else:
                    p["bars_held"] += 1
                    if p["bars_held"] >= (72 if p["mode"] == "UP_TREND" else 36):
                        self.exits[s] = "timeout"
            self.marks.update({s:b.close for s,b in bars.items()})
        else:
            self._clock(now)
        # Evaluate the candle ending the old UTC day before establishing the
        # next day's baseline. A required exit survives the date rollover.
        if self.execution == "ohlcv" and now % 86400 == 0:
            self._risk(now)
        self._clock(now)
        self._risk(now)
        for s in self.policy["symbols"]:
            if s not in bars:
                continue
            b = bars[s]
            result = self.kernels[s].on_bar(b,hourly.get(s))
            self.last_bars[s] = b.start
            self.decisions[s] = {**result,"bar_close":b.start+300,"available_at":now}
            if allow_entries:
                self.event("CLOSED_BAR_DECISION",now,s,mode=result["mode"],reason_codes=result["reason_codes"],
                           signal_time=b.start+300,available_at=now,closed_bar_id=f"binance:spot:{s}:5m:{b.start}",signal=result.get("signal"))
            if result.get("mode_invalidated"):
                self.pending.pop(s,None)
                if s in self.positions:
                    self.exits[s] = "mode_invalidated"
            signal = result.get("signal")
            if signal and allow_entries and now <= b.start+330:
                self._reserve(s,signal,b.start+300)
            elif signal:
                self.event("SIGNAL_NOT_TRADED",now,s,reason="warmup_or_late")
        unknown=self.execution=="quotes" and any(now-self.last_quotes.get(s,{}).get("time",0)>30 for s in self.positions)
        self.equity.append({"time":now,"equity":None if unknown else self.value(),"last_known_equity":self.value() if unknown else None,
                            "valuation_status":"unavailable" if unknown else "available","cash":self.cash,"open_positions":len(self.positions),"pending":len(self.pending)})

    def on_quote(self, symbol: str, bid: float, ask: float, received_at: float, sequence: int | None = None) -> None:
        if symbol not in self.kernels or not all(math.isfinite(v) and v>0 for v in (bid,ask)) or bid>ask:
            return
        last = self.last_quotes.get(symbol)
        if last and (received_at <= last["time"] or (sequence is not None and last.get("sequence") is not None and sequence <= last["sequence"])):
            return
        self.marks[symbol] = bid
        self._clock(received_at)
        self.last_quotes[symbol] = {"time":received_at,"bid":bid,"ask":ask,"sequence":sequence}
        self._risk(received_at)
        p = self.positions.get(symbol)
        if p and received_at > p["entry_time"]:
            reason = "stop" if bid<=p["stop"] else "target" if bid>=p["target"] else self.exits.get(symbol)
            if not reason and received_at >= p["expires_at"]:
                reason = "timeout"
            if reason:
                self._exit(symbol,bid,received_at,reason)
        if symbol in self.pending:
            pending=self.pending[symbol]
            if received_at > pending["signal_time"]+30 or not self.accept_entries:
                self.pending.pop(symbol)
                self.event("ENTRY_CANCELED",received_at,symbol,reason="quote_late_or_paused")
            elif received_at > self.decisions.get(symbol,{}).get("available_at",pending["signal_time"]):
                self._enter(symbol,ask,received_at,exit_reference=bid)

    def finish(self, time: int) -> None:
        for s in list(self.positions):
            self._exit(s,self.marks[s],time,"terminal_liquidation")
        self.pending.clear()
        if self.equity and self.equity[-1]["time"] == time:
            self.equity.pop()
        self.equity.append({"time":time,"equity":self.value(),"cash":self.cash,"open_positions":0,"pending":0})

    def drain(self) -> dict:
        result={"events":self.events,"trades":self.trades,"equity":self.equity}
        self.events,self.trades,self.equity=[],[],[]
        return result

    def snapshot(self) -> dict:
        names=("cash","positions","pending","exits","marks","last_bars","last_quotes","decisions","day","day_start","day_paused","pause_until","losses","accept_entries","count")
        return {**{name:getattr(self,name) for name in names},"kernels":{s:k.to_dict() for s,k in self.kernels.items()},"policy_hash":self.policy["policy_hash"],"execution":self.execution,
                "cost_multiplier":self.cost_multiplier,"only_mode":self.only_mode,"rules_hash":digest(self.rules)}

    def restore(self, state: dict) -> None:
        if (state["policy_hash"] != self.policy["policy_hash"] or state["execution"] != self.execution
            or state.get("cost_multiplier") != self.cost_multiplier or state.get("only_mode") != self.only_mode
            or state.get("rules_hash") != digest(self.rules)):
            raise ValueError("Checkpoint policy/execution mismatch")
        for name,value in state.items():
            if name not in {"kernels","policy_hash","execution","rules_hash","cost_multiplier","only_mode"}:
                setattr(self,name,value)
        self.kernels={s:DualRegimeKernel.from_dict(k) for s,k in state["kernels"].items()}

    def status(self) -> dict:
        return {"cash":self.cash,"equity":self.value(),"positions":self.positions,"pending":self.pending,"decisions":self.decisions,
                "last_bars":self.last_bars,"last_quotes":self.last_quotes,"day_paused":self.day_paused,"pause_until":self.pause_until,
                "evidence_scope":"candidate_simulation","order_submission":False,"execution":self.execution}


def replay(portfolio: CandidatePortfolio, dataset: dict, *, start: int | None = None, end: int | None = None) -> dict:
    timeline: dict[int,dict] = {}
    hours: dict[int,dict] = {}
    for symbol,series in dataset.items():
        for b in series["5m"]:
            if end is None or b.start+300<=end:
                timeline.setdefault(b.start,{})[symbol]=b
        for h in series["1h"]:
            hours.setdefault(h.start+3600,{})[symbol]=h
    for timestamp,bars in sorted(timeline.items()):
        close=timestamp+300
        allow=(start is None or close>=start) and (end is None or close<=end-21600)
        portfolio.on_closed_batch(bars,hours.get(close,{}),close,allow_entries=allow)
    if timeline:
        portfolio.finish(max(timeline)+300)
    return portfolio.drain()
