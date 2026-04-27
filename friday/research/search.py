"""Search provider configuration for local research workflows."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SearchProviderStatus:
    provider: str
    configured: bool
    issue: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def search_provider_status() -> SearchProviderStatus:
    if os.getenv("BRAVE_API_KEY"):
        return SearchProviderStatus("brave", True)
    return SearchProviderStatus("duckduckgo_fallback", True, "BRAVE_API_KEY is missing; use lightweight fallback or browser search.")


def build_search_trace(query: str) -> dict[str, Any]:
    status = search_provider_status()
    return {
        "query": query,
        "provider": status.provider,
        "configured": status.configured,
        "issue": status.issue,
    }
