"""
Verification helpers for FRIDAY's structured command pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable

from friday.core.models import PlanStep, VerificationResult


ToolInvoker = Callable[[str, dict[str, object]], Awaitable[str]]


def _output_indicates_failure(output: str) -> bool:
    lowered = (output or "").strip().lower()
    if not lowered:
        return True
    return lowered.startswith(
        (
            "tool error",
            "error ",
            "error:",
            "could not ",
            "failed ",
            "failure:",
            "[permission blocked]",
        )
    ) or "[approval required]" in lowered


async def verify_step(
    step: PlanStep,
    output: str,
    *,
    tool_invoker: ToolInvoker | None = None,
) -> VerificationResult:
    """Verify the output of a plan step."""
    method = step.verification_method
    target = step.verification_target

    if method == "tool_output_contains":
        passed = target.lower() in (output or "").lower()
        return VerificationResult(passed=passed, detail=f"Expected '{target}' in tool output.")

    if method == "tool_output_nonempty":
        passed = bool((output or "").strip()) and not _output_indicates_failure(output)
        return VerificationResult(passed=passed, detail="Expected a non-empty successful tool output.")

    if method == "command_output_ok":
        passed = not _output_indicates_failure(output)
        return VerificationResult(passed=passed, detail="Expected the command output to indicate success.")

    if method == "file_exists":
        passed = bool(target) and Path(target).exists()
        return VerificationResult(passed=passed, detail=f"Expected file to exist: {target}")

    if method == "permission_or_absence":
        lowered = (output or "").lower()
        if "[approval required]" in lowered:
            return VerificationResult(passed=True, detail="Sensitive action correctly requested approval.")
        if "[permission blocked]" in lowered:
            return VerificationResult(passed=True, detail="Sensitive action was correctly blocked.")
        passed = bool(target) and not Path(str(target)).exists()
        return VerificationResult(passed=passed, detail=f"Expected target to be absent after deletion: {target}")

    if method == "window_present":
        if tool_invoker is None:
            return VerificationResult(passed=not _output_indicates_failure(output), detail="No tool invoker was available for window verification.")
        query = target or step.parameters.get("app_name", "")
        result = await tool_invoker("list_open_windows", {"query": str(query), "limit": 10})
        lowered = result.lower()
        passed = (
            "open windows" in lowered
            and "no open windows found" not in lowered
            and str(query).lower() in lowered
        )
        return VerificationResult(passed=passed, detail=f"Expected a visible window matching '{query}'.")

    if method == "browser_state":
        if tool_invoker is None:
            return VerificationResult(passed=not _output_indicates_failure(output), detail="No tool invoker was available for browser verification.")
        result = await tool_invoker("browser_get_state", {})
        passed = not _output_indicates_failure(result) and (not target or target.lower() in result.lower())
        return VerificationResult(passed=passed, detail=f"Expected browser state containing '{target}'.")

    return VerificationResult(
        passed=not _output_indicates_failure(output),
        detail="Used the default successful-output verifier.",
    )
