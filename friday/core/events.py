"""
Event helpers for FRIDAY's structured command pipeline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PipelineEvent:
    event_type: str
    message: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventRecorder:
    """Collects pipeline events in memory for UI and tests."""

    def __init__(self) -> None:
        self._events: list[PipelineEvent] = []

    def emit(self, event_type: str, message: str, **data: Any) -> PipelineEvent:
        event = PipelineEvent(event_type=event_type, message=message, data=data)
        self._events.append(event)
        return event

    def as_list(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self._events]
