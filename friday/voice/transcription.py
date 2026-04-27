"""Speech-to-text provider configuration."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class TranscriptionConfig:
    provider: str
    model: str
    configured: bool
    missing_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "sarvam": "SARVAM_API_KEY",
    "deepgram": "DEEPGRAM_API_KEY",
}


def load_transcription_config() -> TranscriptionConfig:
    provider = os.getenv("STT_PROVIDER", "openai").strip().lower() or "openai"
    key = PROVIDER_KEYS.get(provider, "OPENAI_API_KEY")
    model = os.getenv("STT_MODEL", "gpt-4o-mini-transcribe").strip() or "gpt-4o-mini-transcribe"
    configured = bool(os.getenv(key, "").strip())
    return TranscriptionConfig(provider, model, configured, "" if configured else key)
