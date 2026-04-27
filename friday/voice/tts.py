"""Text-to-speech provider configuration."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class TTSConfig:
    provider: str
    voice: str
    configured: bool
    missing_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "sarvam": "SARVAM_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
}


def load_tts_config() -> TTSConfig:
    provider = os.getenv("TTS_PROVIDER", "openai").strip().lower() or "openai"
    key = PROVIDER_KEYS.get(provider, "OPENAI_API_KEY")
    voice = os.getenv("TTS_VOICE", "alloy").strip() or "alloy"
    configured = bool(os.getenv(key, "").strip())
    return TTSConfig(provider, voice, configured, "" if configured else key)
