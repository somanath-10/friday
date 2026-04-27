"""Append-only action timeline for the local UI."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from friday.path_utils import workspace_dir
from friday.safety.secrets_filter import redact_value


def timeline_path() -> Path:
    path = workspace_dir() / "logs" / "timeline.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def append_timeline_event(event_type: str, message: str, **data: Any) -> Path:
    payload = redact_value(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "message": message,
            "data": data,
        }
    )
    path = timeline_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    return path


def read_timeline_events(limit: int = 100) -> list[dict[str, Any]]:
    path = timeline_path()
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-max(1, limit):]:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def clear_timeline() -> None:
    path = timeline_path()
    if path.exists():
        path.unlink()
