"""Explicit, permission-gated screen recording state helpers."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from friday.path_utils import workspace_dir
from friday.safety.audit_log import append_audit_record


@dataclass(frozen=True)
class ScreenRecordingResult:
    ok: bool
    action: str
    message: str
    artifact_path: str = ""
    permission_decision: str = "allow"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def recordings_dir() -> Path:
    path = workspace_dir() / "recordings"
    path.mkdir(parents=True, exist_ok=True)
    return path


def recording_state_path() -> Path:
    path = workspace_dir() / "logs" / "screen_recording_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_state() -> dict[str, Any]:
    path = recording_state_path()
    if not path.exists():
        return {"active": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"active": False}
    return data if isinstance(data, dict) else {"active": False}


def _write_state(data: dict[str, Any]) -> None:
    recording_state_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def current_recording_state() -> dict[str, Any]:
    return _read_state()


def _recorder_available() -> bool:
    return shutil.which("ffmpeg") is not None


def start_screen_recording(*, max_duration_seconds: int = 60, dry_run: bool = False) -> ScreenRecordingResult:
    state = _read_state()
    if state.get("active"):
        message = "Screen recording is already active."
        append_audit_record(
            command="start_screen_recording",
            intent="screen_recording",
            risk_level=3,
            decision="block",
            tool="screen_recording.start",
            result=message,
            extra={"artifact_path": str(state.get("artifact_path", ""))},
        )
        return ScreenRecordingResult(False, "start_screen_recording", message, permission_decision="block", metadata=state)

    if dry_run:
        return ScreenRecordingResult(
            True,
            "start_screen_recording",
            f"Dry run: would start an explicit screen recording for up to {max_duration_seconds} seconds.",
        )

    if not _recorder_available():
        message = "Screen recording backend is not configured. Install/configure ffmpeg before recording."
        append_audit_record(
            command="start_screen_recording",
            intent="screen_recording",
            risk_level=3,
            decision="allow",
            tool="screen_recording.start",
            result=message,
        )
        return ScreenRecordingResult(False, "start_screen_recording", message, permission_decision="block")

    started_at = datetime.now(timezone.utc).isoformat()
    artifact = recordings_dir() / f"screen_recording_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.mp4"
    state = {
        "active": True,
        "started_at": started_at,
        "artifact_path": str(artifact),
        "max_duration_seconds": max(1, int(max_duration_seconds)),
        "backend": "ffmpeg",
        "note": "Recording process startup is platform-specific and must be wired by the host runtime.",
    }
    _write_state(state)
    append_audit_record(
        command="start_screen_recording",
        intent="screen_recording",
        risk_level=3,
        decision="allow",
        tool="screen_recording.start",
        result="recording state started",
        extra={"artifact_path": str(artifact)},
    )
    return ScreenRecordingResult(True, "start_screen_recording", f"Screen recording started: {artifact}", artifact_path=str(artifact), metadata=state)


def stop_screen_recording() -> ScreenRecordingResult:
    state = _read_state()
    if not state.get("active"):
        return ScreenRecordingResult(False, "stop_screen_recording", "No screen recording is active.")
    stopped_at = datetime.now(timezone.utc).isoformat()
    state = {**state, "active": False, "stopped_at": stopped_at}
    _write_state(state)
    artifact = str(state.get("artifact_path") or "")
    append_audit_record(
        command="stop_screen_recording",
        intent="screen_recording",
        risk_level=0,
        decision="allow",
        tool="screen_recording.stop",
        result="recording stopped",
        extra={"artifact_path": artifact},
    )
    return ScreenRecordingResult(True, "stop_screen_recording", f"Screen recording stopped. Artifact: {artifact}", artifact_path=artifact, metadata=state)
