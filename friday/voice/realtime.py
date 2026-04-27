"""Realtime voice mode configuration."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class RealtimeVoiceConfig:
    mode: str
    push_to_talk: bool
    configured: bool
    issue: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_realtime_voice_config() -> RealtimeVoiceConfig:
    mode = os.getenv("FRIDAY_VOICE_MODE", "browser_upload").strip().lower() or "browser_upload"
    push_to_talk = os.getenv("FRIDAY_VOICE_PUSH_TO_TALK", "1").strip().lower() not in {"0", "false", "no"}
    if mode == "browser_upload":
        return RealtimeVoiceConfig(mode, push_to_talk, True)
    if mode == "openai_realtime":
        configured = bool(os.getenv("OPENAI_API_KEY", "").strip())
        return RealtimeVoiceConfig(mode, push_to_talk, configured, "" if configured else "OPENAI_API_KEY is missing.")
    if mode == "livekit":
        configured = all(os.getenv(key, "").strip() for key in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"))
        return RealtimeVoiceConfig(mode, push_to_talk, configured, "" if configured else "LiveKit credentials are incomplete.")
    return RealtimeVoiceConfig(mode, push_to_talk, False, f"Unknown voice mode: {mode}")
