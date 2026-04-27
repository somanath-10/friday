"""Workflow memory helpers."""

from __future__ import annotations

from typing import Any

from friday.memory.store import MemoryStore, MemoryWriteResult


def remember_workflow_pattern(goal: str, template: dict[str, Any], *, store: MemoryStore | None = None) -> MemoryWriteResult:
    return (store or MemoryStore()).append_record("workflow_memory", {"goal": goal, "template": template})


def search_workflow_memory(query: str, *, store: MemoryStore | None = None) -> list[dict[str, Any]]:
    selected = store or MemoryStore()
    needle = query.lower()
    return [
        record
        for record in selected.list_records("workflow_memory", limit=200)
        if needle in str(record.get("goal", "")).lower() or needle in str(record.get("template", "")).lower()
    ]
