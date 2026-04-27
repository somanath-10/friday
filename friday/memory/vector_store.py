"""Future vector-store abstraction with a local keyword fallback."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class VectorRecord:
    record_id: str
    text: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InMemoryVectorStore:
    def __init__(self) -> None:
        self.records: list[VectorRecord] = []

    def add(self, record_id: str, text: str, metadata: dict[str, Any] | None = None) -> None:
        self.records.append(VectorRecord(record_id, text, metadata or {}))

    def search(self, query: str, limit: int = 5) -> list[VectorRecord]:
        terms = set(query.lower().split())
        scored = []
        for record in self.records:
            score = len(terms.intersection(record.text.lower().split()))
            if score:
                scored.append((score, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [record for _, record in scored[:limit]]
