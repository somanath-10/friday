"""
Structured data models for FRIDAY's command pipeline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class IntentClass(str, Enum):
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


class ExecutorFamily(str, Enum):
    DESKTOP = "desktop"
    BROWSER = "browser"
    FILES = "files"
    SHELL = "shell"
    CODE = "code"
    RESEARCH = "research"
    WORKFLOW = "workflow"
    SYSTEM = "system"


@dataclass
class IntentRoute:
    intent: str
    confidence: float
    required_capabilities: list[str]
    likely_risk: int
    suggested_executor: str
    rationale: str = ""
    should_use_legacy_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlanStep:
    id: str
    description: str
    executor: str
    action_type: str
    tool_name: str
    parameters: dict[str, Any]
    expected_result: str
    risk_level: int
    needs_approval: bool
    verification_method: str
    verification_target: str = ""
    allow_recovery: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionPlan:
    goal: str
    intent: str
    confidence: float
    required_capabilities: list[str]
    suggested_executor: str
    steps: list[PlanStep]
    dry_run: bool = False
    summary: str = ""
    notes: list[str] = field(default_factory=list)
    supported: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass
class VerificationResult:
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StepExecutionResult:
    step_id: str
    tool_name: str
    ok: bool
    output: str
    verification: VerificationResult
    attempts: int = 1
    recovered: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["verification"] = self.verification.to_dict()
        return payload


@dataclass
class PipelineRunResult:
    handled: bool
    success: bool
    reply: str
    route: IntentRoute | None = None
    plan: ExecutionPlan | None = None
    step_results: list[StepExecutionResult] = field(default_factory=list)
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    pipeline_events: list[dict[str, Any]] = field(default_factory=list)
    permission_pending: bool = False
    used_legacy_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "handled": self.handled,
            "success": self.success,
            "reply": self.reply,
            "route": self.route.to_dict() if self.route else None,
            "plan": self.plan.to_dict() if self.plan else None,
            "step_results": [result.to_dict() for result in self.step_results],
            "tool_events": list(self.tool_events),
            "pipeline_events": list(self.pipeline_events),
            "permission_pending": self.permission_pending,
            "used_legacy_fallback": self.used_legacy_fallback,
        }
