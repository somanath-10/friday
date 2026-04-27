"""Workflow lifecycle and replay engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from friday.core.permissions import permission_for_assessment
from friday.core.risk import RiskAssessment, RiskLevel
from friday.workflows.store import WorkflowRecord, WorkflowStore


@dataclass(frozen=True)
class WorkflowReplayResult:
    ok: bool
    message: str
    workflow_id: str
    permission_decisions: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WorkflowEngine:
    def __init__(self, store: WorkflowStore | None = None) -> None:
        self.store = store or WorkflowStore()

    def create_workflow(self, goal: str, *, intent: str = "general", risk_level: int = 0, steps: list[dict[str, Any]] | None = None) -> WorkflowRecord:
        return self.store.create(goal, intent=intent, risk_level=risk_level, steps=steps)

    def update_step(self, workflow_id: str, step_id: str, status: str, result: str = "") -> WorkflowRecord:
        record = self.store.load(workflow_id)
        for step in record.steps:
            if step.get("id") == step_id:
                step["status"] = status
                if result:
                    step["result"] = result
                break
        record.tool_events.append({"step_id": step_id, "status": status, "result": result})
        if status in {"failed", "blocked"}:
            record.status = status
        self.store.save(record)
        return record

    def complete_workflow(self, workflow_id: str, outcome: str, *, verified: bool = True) -> WorkflowRecord:
        record = self.store.load(workflow_id)
        record.status = "completed" if verified else "completed_with_risk"
        record.final_outcome = outcome
        self.store.save(record)
        return record

    def fail_workflow(self, workflow_id: str, reason: str) -> WorkflowRecord:
        record = self.store.load(workflow_id)
        record.status = "failed"
        record.recovery_notes.append(reason)
        self.store.save(record)
        return record

    def replay_workflow(self, workflow_id: str, *, parameters: dict[str, Any] | None = None, dry_run: bool = True) -> WorkflowReplayResult:
        record = self.store.load(workflow_id)
        decisions: list[dict[str, Any]] = []
        for step in record.steps:
            risk = RiskLevel(int(step.get("risk_level", record.risk_level)))
            decision = permission_for_assessment(
                str(step.get("action_type", "workflow.replay")),
                RiskAssessment(risk, str(step.get("description", "Replay workflow step.")), str(step.get("executor", "workflow"))),
                subject=str(step.get("subject", "")),
            )
            decisions.append(decision.to_dict())
            if decision.decision == "block":
                return WorkflowReplayResult(False, decision.reason, record.workflow_id, decisions)
            if decision.decision == "ask":
                return WorkflowReplayResult(False, "Replay requires approval before continuing.", record.workflow_id, decisions)
        return WorkflowReplayResult(True, "Dry run replay is ready." if dry_run else "Workflow replay checks passed.", record.workflow_id, decisions)

    def template_from_record(self, workflow_id: str) -> dict[str, Any]:
        record = self.store.load(workflow_id)
        return {
            "name": record.goal.lower().replace(" ", "_")[:64],
            "intent": record.intent,
            "risk_level": record.risk_level,
            "steps": record.steps,
        }
