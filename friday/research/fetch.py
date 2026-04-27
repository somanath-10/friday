"""URL fetch helpers for research workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class FetchResult:
    ok: bool
    url: str
    text: str = ""
    status_code: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fetch_url(url: str, *, timeout_seconds: float = 15.0, max_chars: int = 60000) -> FetchResult:
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout_seconds) as client:
            response = client.get(url)
        return FetchResult(response.is_success, str(response.url), response.text[:max_chars], response.status_code, "" if response.is_success else response.reason_phrase)
    except Exception as exc:
        return FetchResult(False, url, error=str(exc))
