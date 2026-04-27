"""Small metrics helpers for local status payloads."""

from __future__ import annotations

from friday.observability.timeline import read_timeline_events


def timeline_counts(limit: int = 500) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in read_timeline_events(limit=limit):
        event_type = str(event.get("event_type", "unknown"))
        counts[event_type] = counts.get(event_type, 0) + 1
    return counts
