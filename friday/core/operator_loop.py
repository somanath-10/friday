"""Reusable observe-act-verify loop for dynamic operators."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from friday.core.events import EventLog, EventType
from friday.safety.emergency_stop import is_emergency_stopped


@dataclass(frozen=True)
class OperatorLoopConfig:
    max_steps: int = 8
    stop_on_approval: bool = True
    dry_run: bool = True


@dataclass(frozen=True)
class OperatorLoopStep:
    index: int
    observation: dict[str, Any]
    action: dict[str, Any]
    result: dict[str, Any]
    verification: dict[str, Any]
    recovery: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OperatorLoopResult:
    completed: bool
    status: str
    message: str
    steps: list[OperatorLoopStep]
    events: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "completed": self.completed,
            "status": self.status,
            "message": self.message,
            "steps": [step.to_dict() for step in self.steps],
            "events": list(self.events),
        }


ObserveFn = Callable[[], dict[str, Any]]
DecideFn = Callable[[dict[str, Any], list[OperatorLoopStep]], dict[str, Any]]
PermissionFn = Callable[[dict[str, Any]], dict[str, Any]]
ExecuteFn = Callable[[dict[str, Any]], dict[str, Any]]
VerifyFn = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]]
RecoverFn = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]]


class OperatorLoop:
    """Small deterministic loop used by browser and desktop dynamic operators."""

    def __init__(self, *, event_log: EventLog | None = None, config: OperatorLoopConfig | None = None) -> None:
        self.event_log = event_log or EventLog()
        self.config = config or OperatorLoopConfig()

    def run(
        self,
        *,
        observe: ObserveFn,
        decide: DecideFn,
        permission: PermissionFn,
        execute: ExecuteFn,
        verify: VerifyFn,
        recover: RecoverFn,
    ) -> OperatorLoopResult:
        steps: list[OperatorLoopStep] = []
        for index in range(1, self.config.max_steps + 1):
            if is_emergency_stopped():
                self.event_log.emit(EventType.TASK_BLOCKED, "Emergency stop is active.", step=index)
                return OperatorLoopResult(False, "blocked", "Emergency stop is active.", steps, self.event_log.to_list())

            observation = observe()
            self.event_log.emit(EventType.ELEMENT_MAP_CREATED, "Observation map created.", step=index, observation=observation)
            action = decide(observation, steps)
            if not action or action.get("type") in {"complete", "done"}:
                self.event_log.emit(EventType.TASK_COMPLETED, action.get("message", "Goal completed."), step=index)
                return OperatorLoopResult(True, "completed", action.get("message", "Goal completed."), steps, self.event_log.to_list())

            self.event_log.emit(EventType.TARGET_SELECTED, "Next target selected.", step=index, action=action)
            decision = permission(action)
            if decision.get("decision") == "ask":
                self.event_log.emit(EventType.PERMISSION_REQUIRED, decision.get("reason", "Approval required."), step=index, action=action)
                return OperatorLoopResult(False, "approval_required", decision.get("reason", "Approval required."), steps, self.event_log.to_list())
            if decision.get("decision") == "block":
                self.event_log.emit(EventType.TASK_BLOCKED, decision.get("reason", "Action blocked."), step=index, action=action)
                return OperatorLoopResult(False, "blocked", decision.get("reason", "Action blocked."), steps, self.event_log.to_list())

            self.event_log.emit(EventType.ACTION_STARTED, "Action started.", step=index, action=action)
            result = execute(action)
            self.event_log.emit(EventType.ACTION_COMPLETED, "Action completed.", step=index, result=result)
            self.event_log.emit(EventType.VERIFICATION_STARTED, "Verification started.", step=index)
            verification = verify(observation, action, result)
            if verification.get("success"):
                self.event_log.emit(EventType.VERIFICATION_SUCCEEDED, verification.get("reason", "Verified."), step=index)
                loop_step = OperatorLoopStep(index, observation, action, result, verification)
                steps.append(loop_step)
                if verification.get("goal_completed"):
                    self.event_log.emit(EventType.TASK_COMPLETED, verification.get("reason", "Goal completed."), step=index)
                    return OperatorLoopResult(True, "completed", verification.get("reason", "Goal completed."), steps, self.event_log.to_list())
                continue

            self.event_log.emit(EventType.VERIFICATION_FAILED, verification.get("reason", "Verification failed."), step=index)
            recovery = recover(observation, action, result)
            self.event_log.emit(EventType.RECOVERY_STARTED, recovery.get("reason", "Recovery started."), step=index)
            loop_step = OperatorLoopStep(index, observation, action, result, verification, recovery)
            steps.append(loop_step)
            if not recovery.get("retryable"):
                self.event_log.emit(EventType.RECOVERY_FAILED, recovery.get("reason", "Recovery failed."), step=index)
                return OperatorLoopResult(False, "failed", recovery.get("reason", "Recovery failed."), steps, self.event_log.to_list())

        self.event_log.emit(EventType.TASK_BLOCKED, "Maximum dynamic operator steps reached.", steps=self.config.max_steps)
        return OperatorLoopResult(False, "max_steps", "Maximum dynamic operator steps reached.", steps, self.event_log.to_list())
