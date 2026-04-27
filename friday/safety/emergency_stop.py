"""
Emergency stop flag for local workflows.

The flag is file-backed so UI routes, tools, and long-running pipeline code can
observe the same stop signal without sharing process memory.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from friday.path_utils import workspace_dir


def emergency_stop_path() -> Path:
    path = workspace_dir() / "logs" / "emergency_stop.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def trigger_emergency_stop(reason: str = "user_requested") -> Path:
    payload = {
        "stopped": True,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    path = emergency_stop_path()
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def clear_emergency_stop() -> None:
    path = emergency_stop_path()
    if path.exists():
        path.unlink()


def emergency_stop_status() -> dict[str, object]:
    path = emergency_stop_path()
    if not path.exists():
        return {"stopped": False, "reason": "", "timestamp": ""}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"stopped": True, "reason": "invalid_stop_file", "timestamp": ""}
    return {
        "stopped": bool(payload.get("stopped", True)),
        "reason": str(payload.get("reason", "")),
        "timestamp": str(payload.get("timestamp", "")),
    }


def is_emergency_stopped() -> bool:
    return bool(emergency_stop_status().get("stopped"))


def assert_not_stopped() -> None:
    status = emergency_stop_status()
    if status.get("stopped"):
        raise RuntimeError(f"FRIDAY emergency stop is active: {status.get('reason') or 'no reason recorded'}")
