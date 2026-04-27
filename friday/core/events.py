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
    INTENT_DETECTED = "intent_detected"
    PLAN_CREATED = "plan_created"
    PERMISSION_REQUIRED = "permission_required"
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_DENIED = "permission_denied"
    TOOL_STARTED = "tool_started"
    TOOL_SUCCEEDED = "tool_succeeded"
    TOOL_FAILED = "tool_failed"
    VERIFICATION_SUCCEEDED = "verification_succeeded"
    VERIFICATION_FAILED = "verification_failed"
    RECOVERY_STARTED = "recovery_started"
    WORKFLOW_COMPLETED = "workflow_completed"


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
