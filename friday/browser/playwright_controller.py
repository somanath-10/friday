"""Small Playwright availability wrapper used by BrowserRuntime."""

from __future__ import annotations

import importlib.util
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class PlaywrightReadiness:
    available: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def playwright_readiness() -> PlaywrightReadiness:
    if importlib.util.find_spec("playwright") is None:
        return PlaywrightReadiness(False, "Playwright is not installed.")
    return PlaywrightReadiness(True, "Playwright package is installed.")
