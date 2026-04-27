"""Local-first integration registry inspired by Omi-style app/input manifests."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IntegrationManifest:
    name: str
    kind: str
    source: str
    description: str
    enabled: bool = True
    local_first: bool = True
    user_owned_data: bool = True
    aliases: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def matches(self, query: str) -> bool:
        lowered = query.strip().lower()
        return lowered == self.source.lower() or lowered == self.name.lower() or lowered in {
            alias.lower() for alias in self.aliases
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def integration_manifest_dir() -> Path:
    return _repo_root() / "config" / "integrations"


def _builtin_integrations() -> list[IntegrationManifest]:
    return [
        IntegrationManifest(
            name="Browser Upload",
            kind="input_source",
            source="browser_upload",
            aliases=("browser", "mic_upload", "web"),
            description="Browser microphone uploads that enter FRIDAY's local pipeline.",
            metadata={"supports_transcripts": True, "supports_text_commands": True},
        ),
        IntegrationManifest(
            name="Desktop Microphone",
            kind="input_source",
            source="desktop_microphone",
            aliases=("desktop_voice", "local_mic"),
            description="Local desktop microphone capture for future Windows-native voice input.",
            metadata={"supports_transcripts": True, "supports_push_to_talk": True},
        ),
        IntegrationManifest(
            name="Mobile Sync",
            kind="input_source",
            source="mobile_sync",
            aliases=("phone", "android", "ios", "mobile"),
            description="Optional synced mobile capture that still lands in user-owned local memory.",
            metadata={"supports_sync": True, "supports_transcripts": True},
        ),
        IntegrationManifest(
            name="Wearable Sync",
            kind="input_source",
            source="wearable_sync",
            aliases=("wearable", "pendant", "glasses"),
            description="Optional wearable-style transcript ingestion through the same local-first memory flow.",
            metadata={"supports_sync": True, "supports_transcripts": True},
        ),
        IntegrationManifest(
            name="Chat Text",
            kind="input_source",
            source="chat_text",
            aliases=("text", "chat", "keyboard"),
            description="Typed commands from the local browser UI or chat client.",
            metadata={"supports_text_commands": True},
        ),
    ]


def _load_manifest(path: Path) -> IntegrationManifest | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        aliases = payload.get("aliases", [])
        return IntegrationManifest(
            name=str(payload["name"]),
            kind=str(payload.get("kind", "integration")),
            source=str(payload["source"]),
            description=str(payload.get("description", "")),
            enabled=bool(payload.get("enabled", True)),
            local_first=bool(payload.get("local_first", True)),
            user_owned_data=bool(payload.get("user_owned_data", True)),
            aliases=tuple(str(item) for item in aliases if str(item).strip()),
            metadata=dict(payload.get("metadata", {})),
        )
    except (KeyError, TypeError, ValueError):
        return None


def list_integrations() -> list[IntegrationManifest]:
    manifests = list(_builtin_integrations())
    manifest_dir = integration_manifest_dir()
    if not manifest_dir.exists():
        return manifests
    for path in sorted(manifest_dir.glob("*.json")):
        manifest = _load_manifest(path)
        if manifest is not None:
            manifests.append(manifest)
    return manifests


def resolve_input_source(source: str) -> IntegrationManifest:
    query = source.strip() or "chat_text"
    for manifest in list_integrations():
        if manifest.kind == "input_source" and manifest.matches(query):
            return manifest
    return IntegrationManifest(
        name="Custom Input",
        kind="input_source",
        source=query.lower().replace(" ", "_"),
        description="Custom local input source routed through FRIDAY's unified command pipeline.",
        aliases=(),
        metadata={"custom": True},
    )
