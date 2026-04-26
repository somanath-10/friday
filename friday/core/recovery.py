"""
Recovery helpers for FRIDAY's structured command pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable
from pathlib import Path

from friday.core.models import PlanStep


ToolInvoker = Callable[[str, dict[str, object]], Awaitable[str]]


@dataclass
class RecoveryAction:
    tool_name: str
    parameters: dict[str, object]
    reason: str


def _basename(value: object) -> str:
    return Path(str(value or "")).name or str(value or "")


def choose_recovery_action(step: PlanStep, output: str, *, attempts: int) -> RecoveryAction | None:
    """Return a retry or fallback action when a step fails safely."""
    lowered = (output or "").lower()
    if attempts >= 2:
        return None

    if "timed out" in lowered and step.risk_level <= 1:
        return RecoveryAction(
            tool_name=step.tool_name,
            parameters=dict(step.parameters),
            reason="Retrying a low-risk step after a timeout.",
        )

    if step.tool_name == "open_application":
        return RecoveryAction(
            tool_name="search_local_apps",
            parameters={"query": str(step.parameters.get("app_name", ""))},
            reason="Application launch failed, so search for matching installed apps.",
        )

    if step.tool_name == "browser_navigate":
        return RecoveryAction(
            tool_name="open_url",
            parameters={"url": str(step.parameters.get("url", ""))},
            reason="Browser automation failed, so open the target in the visible browser.",
        )

    if step.tool_name == "list_directory_tree":
        original_path = str(step.parameters.get("path", ""))
        return RecoveryAction(
            tool_name="search_paths_by_name",
            parameters={"name": _basename(original_path), "directories_only": True},
            reason="Directory listing failed, so search for the target path name.",
        )

    return None
