"""Log path helpers."""

from __future__ import annotations

from pathlib import Path

from friday.path_utils import workspace_dir


def logs_dir() -> Path:
    path = workspace_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_paths() -> dict[str, str]:
    root = logs_dir()
    return {
        "audit": str(root / "audit.jsonl"),
        "timeline": str(root / "timeline.jsonl"),
        "emergency_stop": str(root / "emergency_stop.json"),
    }
