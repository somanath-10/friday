"""
Timeline event schema for command execution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventType(str, Enum):
    COMMAND_RECEIVED = "command_received"
    CONTEXT_RESOLVED = "context_resolved"
    INTENT_DETECTED = "intent_detected"
    PLAN_CREATED = "plan_created"
    STEP_STARTED = "step_started"
    OBSERVATION_STARTED = "observation_started"
    OBSERVATION_COMPLETED = "observation_completed"
    BROWSER_OBSERVED = "browser_observed"
    DESKTOP_OBSERVED = "desktop_observed"
    ELEMENT_MAP_CREATED = "element_map_created"
    TARGET_SELECTED = "target_selected"
    PERMISSION_REQUIRED = "permission_required"
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_DENIED = "permission_denied"
    ACTION_STARTED = "action_started"
    ACTION_COMPLETED = "action_completed"
    TOOL_STARTED = "tool_started"
    TOOL_SUCCEEDED = "tool_succeeded"
    TOOL_FAILED = "tool_failed"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_SUCCEEDED = "verification_succeeded"
    VERIFICATION_FAILED = "verification_failed"
    RECOVERY_STARTED = "recovery_started"
    RECOVERY_SUCCEEDED = "recovery_succeeded"
    RECOVERY_FAILED = "recovery_failed"
    WORKFLOW_SAVED = "workflow_saved"
    WORKFLOW_COMPLETED = "workflow_completed"
    ARTIFACT_CREATED = "artifact_created"
    EMERGENCY_STOP_TRIGGERED = "emergency_stop_triggered"
    TASK_COMPLETED = "task_completed"
    TASK_PARTIAL = "task_partial"
    TASK_BLOCKED = "task_blocked"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"


@dataclass(frozen=True)
class TimelineEvent:
    event_type: EventType
    message: str
    data: dict[str, Any]
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["event_type"] = self.event_type.value
        return payload


class EventLog:
    def __init__(self) -> None:
        self._events: list[TimelineEvent] = []

    def emit(self, event_type: EventType, message: str, **data: Any) -> TimelineEvent:
        event = TimelineEvent(
            event_type=event_type,
            message=message,
            data=data,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._events.append(event)
        try:
            from friday.observability.timeline import append_timeline_event

            append_timeline_event(event_type.value, message, **data)
        except Exception:
            pass
        return event

    def to_list(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self._events]
