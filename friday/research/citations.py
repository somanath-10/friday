"""Citation formatting helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Citation:
    title: str
    url: str
    accessed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def format_citation(citation: Citation, index: int) -> str:
    title = citation.title or citation.url
    accessed = f" Accessed: {citation.accessed_at}." if citation.accessed_at else ""
    return f"[{index}] {title}. {citation.url}.{accessed}"
