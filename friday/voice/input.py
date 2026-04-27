"""Voice input helpers that feed the same core pipeline as text."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from friday.core.executor import run_command_pipeline
from friday.path_utils import workspace_dir


@dataclass(frozen=True)
class VoiceCommand:
    transcript: str
    source: str = "browser_upload"
    language: str = "en"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def transcripts_dir() -> Path:
    path = workspace_dir() / "voice" / "transcripts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def transcript_path(session_id: str) -> Path:
    safe = Path(session_id).name or "session"
    return transcripts_dir() / f"{safe}.txt"


def route_voice_command(command: VoiceCommand, *, dry_run: bool = True) -> dict[str, Any]:
    result = run_command_pipeline(command.transcript, dry_run=dry_run)
    return result.to_dict()
