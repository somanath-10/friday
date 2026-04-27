"""User preference profile helpers."""

from __future__ import annotations

from typing import Any

from friday.memory.store import MemoryStore, MemoryWriteResult


def save_user_preference(key: str, value: Any, *, store: MemoryStore | None = None) -> MemoryWriteResult:
    return (store or MemoryStore()).save_preference(key, value)


def load_user_preference(key: str, default: Any = None, *, store: MemoryStore | None = None) -> Any:
    return (store or MemoryStore()).load_preference(key, default)
