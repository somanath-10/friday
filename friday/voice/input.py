"""Voice input helpers that feed the same core pipeline as text."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from friday.core.permissions import load_permissions_config
from friday.core.executor import run_command_pipeline
from friday.integrations.registry import resolve_input_source
from friday.memory.store import MemoryStore
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


def _sentences(text: str) -> list[str]:
    return [segment.strip() for segment in re.split(r"(?<=[.!?])\s+|\n+", text) if segment.strip()]


def summarize_transcript(text: str) -> str:
    sentences = _sentences(text)
    if not sentences:
        return ""
    summary = " ".join(sentences[:2]).strip()
    return summary[:320]


def extract_action_items(text: str) -> list[str]:
    markers = (
        "i will",
        "we will",
        "need to",
        "todo",
        "to do",
        "follow up",
        "remind me",
        "please",
        "send",
        "schedule",
    )
    items: list[str] = []
    for sentence in _sentences(text):
        lowered = sentence.lower()
        if any(marker in lowered for marker in markers):
            items.append(sentence[:240])
    return items[:10]


def save_voice_transcript(command: VoiceCommand, *, store: MemoryStore | None = None) -> dict[str, Any]:
    summary = summarize_transcript(command.transcript)
    action_items = extract_action_items(command.transcript)
    source_manifest = resolve_input_source(command.source)
    try:
        selected = store or MemoryStore()
        result = selected.append_record(
            "conversations",
            {
                "source": source_manifest.source,
                "source_name": source_manifest.name,
                "source_kind": source_manifest.kind,
                "language": command.language,
                "transcript": command.transcript,
                "summary": summary,
                "action_items": action_items,
                "user_owned_data": source_manifest.user_owned_data,
                "searchable_text": f"{command.transcript}\n{summary}\n" + "\n".join(action_items),
            },
        )
    except Exception as exc:
        return {
            "saved": False,
            "message": f"Could not save transcript memory: {exc}",
            "path": "",
            "summary": summary,
            "action_items": action_items,
        }
    return {
        "saved": result.ok,
        "message": result.message,
        "path": result.path,
        "summary": summary,
        "action_items": action_items,
    }


def search_voice_memory(query: str, *, store: MemoryStore | None = None, limit: int = 20) -> list[dict[str, Any]]:
    selected = store or MemoryStore()
    needle = query.lower()
    return [
        record
        for record in selected.list_records("conversations", limit=200)
        if needle in str(record.get("searchable_text", "")).lower()
        or needle in str(record.get("transcript", "")).lower()
        or needle in str(record.get("summary", "")).lower()
    ][:limit]


def route_voice_command(command: VoiceCommand, *, dry_run: bool = True) -> dict[str, Any]:
    result = run_command_pipeline(command.transcript, dry_run=dry_run)
    payload = result.to_dict()
    permissions = load_permissions_config()
    save_transcripts = bool(permissions.get("voice", {}).get("save_transcripts", True))
    source_manifest = resolve_input_source(command.source)
    payload["input_source"] = source_manifest.to_dict()
    if save_transcripts:
        payload["transcript_memory"] = save_voice_transcript(command)
    else:
        payload["transcript_memory"] = {"saved": False, "message": "Voice transcript storage is disabled by configuration."}
    return payload
