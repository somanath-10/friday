"""Controllable local JSON memory store."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from friday.core.permissions import load_permissions_config
from friday.path_utils import memory_dir
from friday.safety.secrets_filter import redact_value


@dataclass(frozen=True)
class MemoryWriteResult:
    ok: bool
    message: str
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MemoryStore:
    def __init__(self, root: Path | None = None, *, enabled: bool | None = None) -> None:
        permissions = load_permissions_config()
        self.enabled = bool(permissions.get("memory", {}).get("enabled", True)) if enabled is None else enabled
        self.root = root or memory_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        safe = Path(name).name
        if not safe.endswith(".json"):
            safe += ".json"
        return self.root / safe

    def _read(self, name: str) -> dict[str, Any]:
        path = self._path(name)
        if not path.exists():
            return {"metadata": {"created_at": datetime.now(timezone.utc).isoformat()}, "data": []}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {"metadata": {"created_at": datetime.now(timezone.utc).isoformat()}, "data": []}
        return payload if isinstance(payload, dict) else {"metadata": {}, "data": []}

    def _write(self, name: str, payload: dict[str, Any]) -> MemoryWriteResult:
        if not self.enabled:
            return MemoryWriteResult(False, "Memory is disabled by configuration.")
        path = self._path(name)
        payload["metadata"] = {**payload.get("metadata", {}), "updated_at": datetime.now(timezone.utc).isoformat()}
        path.write_text(json.dumps(redact_value(payload), indent=2, ensure_ascii=False), encoding="utf-8")
        return MemoryWriteResult(True, "Memory saved.", str(path))

    def save_preference(self, key: str, value: Any) -> MemoryWriteResult:
        payload = self._read("user_preferences")
        data = payload.setdefault("data", [])
        data[:] = [item for item in data if item.get("key") != key]
        data.append({"key": key, "value": redact_value(value), "updated_at": datetime.now(timezone.utc).isoformat()})
        return self._write("user_preferences", payload)

    def load_preference(self, key: str, default: Any = None) -> Any:
        for item in reversed(self._read("user_preferences").get("data", [])):
            if item.get("key") == key:
                return item.get("value", default)
        return default

    def append_record(self, collection: str, record: dict[str, Any]) -> MemoryWriteResult:
        payload = self._read(collection)
        payload.setdefault("data", []).append(redact_value({**record, "timestamp": datetime.now(timezone.utc).isoformat()}))
        return self._write(collection, payload)

    def list_records(self, collection: str, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._read(collection).get("data", []))[-max(1, limit):]

    def clear(self) -> MemoryWriteResult:
        if not self.enabled:
            return MemoryWriteResult(False, "Memory is disabled by configuration.")
        for path in self.root.glob("*.json"):
            path.unlink()
        return MemoryWriteResult(True, "Memory cleared.", str(self.root))

    def export(self) -> dict[str, Any]:
        return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in self.root.glob("*.json")}
