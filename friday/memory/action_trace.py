"""Action trace memory helpers."""

from __future__ import annotations

from typing import Any

from friday.memory.store import MemoryStore, MemoryWriteResult


def save_action_trace(
    command: str,
    plan: dict[str, Any],
    result: dict[str, Any],
    *,
    store: MemoryStore | None = None,
    artifacts: list[str] | None = None,
    sources: list[str] | None = None,
) -> MemoryWriteResult:
    selected = store or MemoryStore()
    return selected.append_record(
        "action_traces",
        {
            "command": command,
            "plan": plan,
            "result": result,
            "artifacts": list(artifacts or []),
            "sources": list(sources or []),
        },
    )


def recent_action_traces(limit: int = 20, *, store: MemoryStore | None = None) -> list[dict[str, Any]]:
    selected = store or MemoryStore()
    return selected.list_records("action_traces", limit=limit)
