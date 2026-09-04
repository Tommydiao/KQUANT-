from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .alert_agent import emit_evaluated_alert
from .config import Settings
from .instruction_models import instruction_from_evaluation
from .instruction_store import save_instruction
from .notifications import NotificationHub


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RealtimeSupervisor:
    """Bridge market/signal/EVAL output into auditable instruction state.

    This is deliberately an evaluation-aware supervisor, not an exchange
    executor.  It can only pass an EVAL-approved result downstream; the
    current foundation policy keeps that downstream path closed.
    """

    def __init__(
        self,
        db_path: Path,
        hub: NotificationHub,
        settings: Settings | None = None,
        execution_sink: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ):
        self.db_path = db_path
        self.hub = hub
        self.settings = settings
        self.started_at = _now()
        self.last_market_event_at: str | None = None
        self.last_evaluation_at: str | None = None
        self.last_instruction_at: str | None = None
        self.evaluations_seen = 0
        self.instructions_created = 0
        self.duplicates_suppressed = 0
        self.alerts_emitted = 0
        self.execution_sink = execution_sink
        self.last_execution_admission: dict[str, Any] | None = None

    def on_market_event(self, event: Any) -> None:
        self.last_market_event_at = str(getattr(event, "received_at", None) or _now())

    def accept_evaluation(self, evaluation: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        self.evaluations_seen += 1
        self.last_evaluation_at = str(evaluation.get("evaluated_at") or now)
        instruction = instruction_from_evaluation(evaluation, now=now)
        value, created = save_instruction(self.db_path, instruction)
        if created:
            self.instructions_created += 1
            self.last_instruction_at = now
        else:
            self.duplicates_suppressed += 1

        # Alert Agent is reachable only through this EVAL output.  With the
        # foundation gate closed this branch is intentionally never entered.
        alert = None
        if created and bool(evaluation.get("allowed_alert")):
            alert = emit_evaluated_alert(
                self.db_path,
                self.hub,
                evaluation,
                title=f"{instruction.symbol} research instruction",
                body=f"EVAL approved {instruction.state}; review the research plan.",
                deep_link=f"/?asset={instruction.asset_id}",
                settings=self.settings,
            )
            if alert is not None:
                self.alerts_emitted += 1
        execution = None
        if created and self.execution_sink is not None:
            execution = self.execution_sink(evaluation)
            self.last_execution_admission = execution
        return {"instruction": value, "created": created, "alert": alert, "execution": execution}

    def status(self) -> dict[str, Any]:
        return {
            "status": "running",
            "mode": "eval_gated_research_only",
            "started_at": self.started_at,
            "last_market_event_at": self.last_market_event_at,
            "last_evaluation_at": self.last_evaluation_at,
            "last_instruction_at": self.last_instruction_at,
            "evaluations_seen": self.evaluations_seen,
            "instructions_created": self.instructions_created,
            "duplicates_suppressed": self.duplicates_suppressed,
            "alerts_emitted": self.alerts_emitted,
            "last_execution_admission": self.last_execution_admission,
            "alert_path": "EVAL only",
            "paper_enabled": False,
            "shadow_enabled": False,
            "order_submission": False,
        }
