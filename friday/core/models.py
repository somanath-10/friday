"""
Shared structured models for the FRIDAY command pipeline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from friday.core.risk import RiskLevel


class Intent(str, Enum):
    DESKTOP = "desktop"
    BROWSER = "browser"
    FILES = "files"
    SHELL = "shell"
    CODE = "code"
    RESEARCH = "research"
    VOICE = "voice"
    MEMORY = "memory"
    WORKFLOW = "workflow"
    SYSTEM = "system"
    MIXED = "mixed"


@dataclass(frozen=True)
class IntentResult:
    intent: Intent
    confidence: float
    required_capabilities: list[str]
    likely_risk: RiskLevel
    suggested_executor: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["intent"] = self.intent.value
        data["likely_risk"] = int(self.likely_risk)
        return data


@dataclass(frozen=True)
class IntentRoute:
    intent: str
    confidence: float
    required_capabilities: list[str]
    likely_risk: int
    suggested_executor: str
    should_use_legacy_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlanStep:
    id: str
    description: str
    executor: str
    action_type: str
    parameters: dict[str, Any]
    expected_result: str
    risk_level: RiskLevel
    needs_approval: bool
    verification_method: str
    tool_name: str = ""
    verification_target: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["risk_level"] = int(self.risk_level)
        return data


@dataclass(frozen=True)
class Plan:
    goal: str
    intent: IntentResult
    steps: list[PlanStep]

    @property
    def max_risk_level(self) -> RiskLevel:
        if not self.steps:
            return RiskLevel.READ_ONLY
        return max((step.risk_level for step in self.steps), default=RiskLevel.READ_ONLY)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "intent": self.intent.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
            "max_risk_level": int(self.max_risk_level),
        }


@dataclass(frozen=True)
class ExecutionPlan:
    goal: str
    intent: str
    confidence: float
    required_capabilities: list[str]
    suggested_executor: str
    steps: list[PlanStep]
    supported: bool = True
    dry_run: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "intent": self.intent,
            "confidence": self.confidence,
            "required_capabilities": list(self.required_capabilities),
            "suggested_executor": self.suggested_executor,
            "steps": [step.to_dict() for step in self.steps],
            "supported": self.supported,
            "dry_run": self.dry_run,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class StepExecutionResult:
    step_id: str
    status: str
    output: str
    permission_decision: str = "allow"
    error: str = ""
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationResult:
    step_id: str
    ok: bool
    method: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def passed(self) -> bool:
        return self.ok


@dataclass(frozen=True)
class RecoveryResult:
    step_id: str
    attempted: bool
    recovered: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PipelineResult:
    command: str
    plan: Plan
    events: list[dict[str, Any]]
    step_results: list[StepExecutionResult] = field(default_factory=list)
    verification_results: list[VerificationResult] = field(default_factory=list)
    recovery_results: list[RecoveryResult] = field(default_factory=list)
    status: str = "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "plan": self.plan.to_dict(),
            "events": self.events,
            "step_results": [result.to_dict() for result in self.step_results],
            "verification_results": [result.to_dict() for result in self.verification_results],
            "recovery_results": [result.to_dict() for result in self.recovery_results],
            "status": self.status,
        }


@dataclass(frozen=True)
class RecoveryAction:
    tool_name: str
    parameters: dict[str, Any]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StructuredStepResult:
    step_id: str
    tool_name: str
    success: bool
    output: str
    verified: bool = False
    recovered: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PipelineRunResult:
    handled: bool
    success: bool
    reply: str
    plan: ExecutionPlan | None = None
    permission_pending: bool = False
    used_legacy_fallback: bool = False
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    pipeline_events: list[dict[str, Any]] = field(default_factory=list)
    step_results: list[StructuredStepResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "handled": self.handled,
            "success": self.success,
            "reply": self.reply,
            "plan": self.plan.to_dict() if self.plan else None,
            "permission_pending": self.permission_pending,
            "used_legacy_fallback": self.used_legacy_fallback,
            "tool_events": list(self.tool_events),
            "pipeline_events": list(self.pipeline_events),
            "step_results": [result.to_dict() for result in self.step_results],
        }
