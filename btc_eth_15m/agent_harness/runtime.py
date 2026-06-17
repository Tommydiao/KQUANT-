from __future__ import annotations

from pathlib import Path
from typing import Any

from btc_eth_15m.agent_harness.approval import ApprovalManager
from btc_eth_15m.agent_harness.audit_log import AuditLogger
from btc_eth_15m.agent_harness.risk_manager import HIGH_RISK_ACTIONS, RiskManager
from btc_eth_15m.agent_harness.state_store import StateStore
from btc_eth_15m.agent_harness.tool_registry import ToolRegistry
from btc_eth_15m.agent_harness.tools import _options_data_audit, register_default_tools


class AgentRuntime:
    def __init__(
        self,
        *,
        store: StateStore,
        registry: ToolRegistry,
        audit: AuditLogger,
        risk_manager: RiskManager,
        approval_manager: ApprovalManager,
        outputs_dir: str | Path = "outputs",
    ) -> None:
        self.store = store
        self.registry = registry
        self.audit = audit
        self.risk_manager = risk_manager
        self.approval_manager = approval_manager
        self.outputs_dir = Path(outputs_dir)

    def create_task(
        self,
        task_type: str,
        payload: dict[str, Any] | None = None,
        *,
        priority: int = 0,
        created_by: str = "cli",
    ) -> str:
        task = self.store.create_task(task_type, payload or {}, priority=priority, created_by=created_by)
        self.audit.record(
            "task.created",
            task_id=task["id"],
            actor=created_by,
            message=f"Task created: {task_type}",
            status="created",
            metadata={"task_type": task_type},
        )
        return task["id"]

    def run_task(self, task_id: str) -> None:
        task = self._require_task(task_id)
        if task["status"] in {"cancelled", "completed"}:
            return
        self.store.update_task(task_id, status="running", current_step="started", error_message=None)
        self.audit.record("task.started", task_id=task_id, actor="agent_runtime", message="Task started.", status="running")
        try:
            if task["task_type"] == "noop":
                self._complete(task_id, {"message": "noop completed"})
                return
            if task["task_type"] == "btc_market_review":
                self._run_btc_market_review(task_id, task)
                return
            if task["task_type"] == "us_options_scan":
                self._run_us_options_scan(task_id, task)
                return
            if task["task_type"] in {"dry_run", "backtest", "paper_trade", "live_order"}:
                self._run_dry_flow(task_id, task)
                return
            self._complete(task_id, {"message": f"No handler for task type {task['task_type']}; no-op completed."})
        except Exception as exc:
            self.store.update_task(
                task_id,
                status="failed",
                current_step="failed",
                error_message=str(exc),
                result={"error": str(exc)},
            )
            self.audit.record(
                "task.failed",
                task_id=task_id,
                actor="agent_runtime",
                message="Task failed.",
                status="failed",
                error_message=str(exc),
            )
            raise

    def pause_task(self, task_id: str, reason: str) -> None:
        self._require_task(task_id)
        self.store.update_task(task_id, status="paused", current_step="paused")
        self.audit.record(
            "task.paused",
            task_id=task_id,
            actor="agent_runtime",
            message="Task paused.",
            status="paused",
            metadata={"reason": reason},
        )

    def resume_task(self, task_id: str) -> None:
        task = self._require_task(task_id)
        approvals = self.approval_manager.pending(task_id)
        if approvals:
            self.store.update_task(task_id, status="waiting_approval", current_step="waiting_approval", requires_approval=True)
            return
        rejected = [
            event
            for event in self.store.list_audit_events(task_id)
            if event.get("event_type") == "approval.rejected" and event.get("status") in {"rejected", "expired"}
        ]
        if rejected:
            self.store.update_task(
                task_id,
                status="failed",
                current_step="approval_rejected",
                error_message="Approval was rejected or expired.",
            )
            return
        if task["status"] == "waiting_approval":
            self.store.update_task(
                task_id,
                status="completed",
                current_step="approval_acknowledged",
                result={"message": "Approval acknowledged. Live execution remains unavailable in MVP."},
                requires_approval=False,
            )
            self.audit.record(
                "order.live.blocked",
                task_id=task_id,
                actor="agent_runtime",
                message="Live execution is intentionally not implemented in MVP.",
                status="blocked",
            )
            self.audit.record(
                "task.completed",
                task_id=task_id,
                actor="agent_runtime",
                message="Task completed after approval acknowledgement.",
                status="completed",
            )
            return
        self.run_task(task_id)

    def cancel_task(self, task_id: str, reason: str) -> None:
        self._require_task(task_id)
        self.store.update_task(task_id, status="cancelled", current_step="cancelled", error_message=reason)
        self.audit.record(
            "task.cancelled",
            task_id=task_id,
            actor="agent_runtime",
            message="Task cancelled.",
            status="cancelled",
            metadata={"reason": reason},
        )

    def get_task_status(self, task_id: str) -> dict[str, Any]:
        task = self._require_task(task_id)
        return {
            "task": task,
            "pending_approvals": self.approval_manager.pending(task_id),
            "events": self.store.list_audit_events(task_id),
        }

    def _run_dry_flow(self, task_id: str, task: dict[str, Any]) -> None:
        payload = task.get("payload", {})
        context = self._context(task_id)
        symbols = payload.get("symbols") or ["BTCUSDT", "ETHUSDT"]
        strategy_id = str(payload.get("strategy_id") or "strategy-dry-run")

        self.store.update_task(task_id, status="running", current_step="market_data")
        market_data = self.registry.execute(
            "mock_market_data",
            {"symbols": symbols, "timeframe": payload.get("timeframe", "15m")},
            context,
        )

        self.store.update_task(task_id, status="running", current_step="backtest")
        backtest = self.registry.execute(
            "backtest",
            {
                "strategy_id": strategy_id,
                "symbols": symbols,
                "timeframe": payload.get("timeframe", "15m"),
                "source_type": market_data.get("source_type", "mock"),
                "summary": "Dry-run backtest adapter executed by Agent Harness.",
                "trade_count": payload.get("mock_trade_count", 0),
                "total_return_pct": payload.get("mock_total_return_pct", 0.0),
                "max_drawdown_pct": payload.get("mock_max_drawdown_pct", 0.0),
                "win_rate_pct": payload.get("mock_win_rate_pct", 0.0),
            },
            context,
        )

        action_type = "paper_order"
        if task["task_type"] == "live_order" or payload.get("request_live_order"):
            action_type = "live_order"
        elif payload.get("action_type"):
            action_type = str(payload["action_type"])

        self.store.update_task(task_id, status="running", current_step="risk_check")
        risk_payload = {
            "strategy_id": strategy_id,
            "notional": payload.get("notional", 25.0),
            "asset_exposure": payload.get("asset_exposure", 0.0),
            "daily_loss": payload.get("daily_loss", 0.0),
        }
        risk_result = self.registry.execute(
            "risk_check",
            {"action_type": action_type, "payload": risk_payload},
            context,
        )
        if action_type in HIGH_RISK_ACTIONS:
            approval = self.approval_manager.create_request(
                task_id=task_id,
                approval_type=action_type,
                request_summary=f"Approval required for {action_type}.",
                risk_summary="; ".join(risk_result.get("violations") or ["High-risk action requires approval."]),
                payload={"action_type": action_type, "risk_level": risk_result.get("risk_level"), "risk_result": risk_result},
            )
            self.store.update_task(
                task_id,
                status="waiting_approval",
                current_step="waiting_approval",
                result={"risk_result": risk_result, "approval_request": approval},
                requires_approval=True,
            )
            return

        paper_order = None
        if task["task_type"] == "paper_trade" or payload.get("create_paper_order", True):
            self.store.update_task(task_id, status="running", current_step="paper_trading")
            paper_order = self.registry.execute(
                "paper_trading",
                {
                    "symbol": str(payload.get("symbol") or symbols[0]).upper(),
                    "side": str(payload.get("side", "long")),
                    "quantity": float(payload.get("quantity", 0.001)),
                    "price": float(payload.get("price", 100.0)),
                    "strategy_id": strategy_id,
                    "notes": "Agent Harness dry-run simulated paper order.",
                },
                context,
            )

        self.store.update_task(task_id, status="running", current_step="report")
        report = self.registry.execute(
            "report",
            {
                "task_id": task_id,
                "payload": {
                    "summary": "Agent Harness dry-run flow completed.",
                    "strategy_id": strategy_id,
                    "data_source": market_data.get("source_type"),
                    "risk_result": risk_result,
                    "approval_status": "not_required",
                },
            },
            context,
        )
        self._complete(
            task_id,
            {
                "market_data": market_data,
                "backtest": backtest,
                "risk_result": risk_result,
                "paper_order": paper_order,
                "report": report,
            },
        )

    def _run_btc_market_review(self, task_id: str, task: dict[str, Any]) -> None:
        payload = task.get("payload", {})
        context = self._context(task_id)
        symbol = str((payload.get("symbols") or ["BTCUSDT"])[0]).upper()
        strategy_id = str(payload.get("strategy_id") or "btc-live-review")

        self.store.update_task(task_id, status="running", current_step="live_market_data")
        market_data = self.registry.execute(
            "live_market_data",
            {
                "symbol": symbol,
                "kline_refresh": payload.get("live_btc_kline_refresh") or payload.get("kline_refresh") or {},
                "ticker_override": payload.get("ticker_override"),
            },
            context,
        )

        ticker = market_data.get("ticker") or {}
        freshness = market_data.get("kline_freshness") or {}
        self.store.update_task(task_id, status="running", current_step="risk_check")
        risk_result = self.registry.execute(
            "risk_check",
            {
                "action_type": "market_review",
                "payload": {
                    "strategy_id": strategy_id,
                    "risk_level": "read_only",
                    "notional": 0.0,
                    "asset_exposure": 0.0,
                    "daily_loss": 0.0,
                },
            },
            context,
        )

        paper_order = None
        if payload.get("create_paper_order") is True:
            self.store.update_task(task_id, status="running", current_step="paper_trading")
            paper_order = self.registry.execute(
                "paper_trading",
                {
                    "symbol": symbol,
                    "side": str(payload.get("side", "long")),
                    "quantity": float(payload.get("quantity", 0.001)),
                    "price": float(payload.get("price") or ticker.get("price") or 0.0),
                    "strategy_id": strategy_id,
                    "notes": "Optional local paper order from BTC market review; no exchange call.",
                },
                context,
            )

        summary = (
            f"BTC market review completed. Live ticker is {'available' if ticker.get('ok') else 'unavailable'}; "
            f"BTC 15m freshness is {'fresh' if freshness.get('is_fresh') else 'stale'}."
        )
        self.store.update_task(task_id, status="running", current_step="report")
        report = self.registry.execute(
            "report",
            {
                "task_id": task_id,
                "payload": {
                    "summary": summary,
                    "strategy_id": strategy_id,
                    "data_source": market_data.get("source_type"),
                    "market_data": market_data,
                    "risk_result": risk_result,
                    "approval_status": "not_required",
                },
            },
            context,
        )
        self._complete(
            task_id,
            {
                "market_data": market_data,
                "risk_result": risk_result,
                "paper_order": paper_order,
                "report": report,
            },
        )

    def _run_us_options_scan(self, task_id: str, task: dict[str, Any]) -> None:
        payload = task.get("payload", {})
        context = self._context(task_id)
        symbols = payload.get("symbols") or ["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "MSFT", "AMD", "META"]
        strategy_id = str(payload.get("strategy_id") or "us-options-live-scanner")

        self.store.update_task(task_id, status="running", current_step="us_options_scanner")
        scanner = self.registry.execute(
            "us_options_scanner",
            {
                "symbols": symbols,
                "source": payload.get("source", "live"),
                "timeout": payload.get("timeout", 8.0),
                "scanner_override": payload.get("scanner_override"),
            },
            context,
        )
        data_audit = _options_data_audit(scanner)

        action_type = "live_order" if payload.get("request_live_order") else "market_review"
        self.store.update_task(task_id, status="running", current_step="risk_check")
        risk_result = self.registry.execute(
            "risk_check",
            {
                "action_type": action_type,
                "payload": {
                    "strategy_id": strategy_id,
                    "risk_level": "read_only",
                    "notional": 0.0,
                    "asset_exposure": 0.0,
                    "daily_loss": 0.0,
                    "source_type": scanner.get("source_type"),
                },
            },
            context,
        )
        if action_type in HIGH_RISK_ACTIONS:
            approval = self.approval_manager.create_request(
                task_id=task_id,
                approval_type=action_type,
                request_summary=f"Approval required for {action_type}.",
                risk_summary="; ".join(risk_result.get("violations") or ["High-risk action requires approval."]),
                payload={"action_type": action_type, "risk_level": risk_result.get("risk_level"), "risk_result": risk_result},
            )
            self.store.update_task(
                task_id,
                status="waiting_approval",
                current_step="waiting_approval",
                result={
                    "scanner": scanner,
                    "data_audit": data_audit,
                    "risk_result": risk_result,
                    "approval_request": approval,
                    "paper_order": None,
                },
                requires_approval=True,
            )
            return

        summary = (
            "US options scan completed. "
            f"Overall recommendation: {scanner.get('overall_recommendation', 'NO TRADE')}. "
            "This is read-only market data review; broker execution is not wired."
        )
        self.store.update_task(task_id, status="running", current_step="report")
        report = self.registry.execute(
            "report",
            {
                "task_id": task_id,
                "payload": {
                    "summary": summary,
                    "strategy_id": strategy_id,
                    "data_source": scanner.get("source_type"),
                    "market_data": scanner,
                    "data_audit": data_audit,
                    "risk_result": risk_result,
                    "approval_status": "not_required",
                    "limitations": [
                        "US options scan is read-only and does not authorize a trade.",
                        "No broker key is read, no broker account state is fetched, and no order endpoint is wired.",
                        "Live remains locked; high-risk actions require approval and still cannot execute live orders in MVP.",
                    ],
                },
            },
            context,
        )
        self._complete(
            task_id,
            {
                "scanner": scanner,
                "data_audit": data_audit,
                "risk_result": risk_result,
                "paper_order": None,
                "report": report,
            },
        )

    def _complete(self, task_id: str, result: dict[str, Any]) -> None:
        self.store.update_task(task_id, status="completed", current_step="completed", result=result, requires_approval=False)
        self.audit.record(
            "task.completed",
            task_id=task_id,
            actor="agent_runtime",
            message="Task completed.",
            status="completed",
            metadata={"result_keys": sorted(result)},
        )

    def _context(self, task_id: str) -> dict[str, Any]:
        return {
            "task_id": task_id,
            "store": self.store,
            "audit": self.audit,
            "risk_manager": self.risk_manager,
            "approval_manager": self.approval_manager,
            "outputs_dir": str(self.outputs_dir),
            "actor": "agent_runtime",
        }

    def _require_task(self, task_id: str) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        if not task:
            raise KeyError(f"Task was not found: {task_id}")
        return task


def default_runtime(db_path: str | Path = "work/market.sqlite3", outputs_dir: str | Path = "outputs") -> AgentRuntime:
    store = StateStore(db_path)
    audit = AuditLogger(store)
    risk_manager = RiskManager(store, audit)
    approval_manager = ApprovalManager(store, audit)
    registry = ToolRegistry(store, audit)
    register_default_tools(registry)
    return AgentRuntime(
        store=store,
        registry=registry,
        audit=audit,
        risk_manager=risk_manager,
        approval_manager=approval_manager,
        outputs_dir=outputs_dir,
    )
