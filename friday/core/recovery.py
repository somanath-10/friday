"""
Minimal safe recovery policy for failed pipeline steps.
"""

from __future__ import annotations

from friday.core.models import PlanStep, RecoveryAction, RecoveryResult, StepExecutionResult


def recover_step(step: PlanStep, result: StepExecutionResult) -> RecoveryResult:
    if result.status in {"permission_required", "blocked"}:
        return RecoveryResult(
            step_id=step.id,
            attempted=False,
            recovered=False,
            detail="Recovery skipped because the step needs user permission or is blocked by policy.",
        )

    if result.status == "dry_run":
        return RecoveryResult(
            step_id=step.id,
            attempted=False,
            recovered=True,
            detail="Dry-run step does not need recovery.",
        )

    if result.status == "succeeded":
        return RecoveryResult(
            step_id=step.id,
            attempted=False,
            recovered=True,
            detail="Step succeeded; recovery was not needed.",
        )

    return RecoveryResult(
        step_id=step.id,
        attempted=True,
        recovered=False,
        detail=f"Safe automatic retry is not available for {step.executor}.{step.action_type}: {result.error or result.output}",
    )


def choose_recovery_action(
    step: PlanStep,
    error_text: str,
    *,
    attempts: int = 0,
) -> RecoveryAction | None:
    """Return a lightweight fallback action for a failed structured step."""
    if attempts >= 2:
        return None

    normalized = error_text.lower()
    if step.tool_name == "browser_navigate" or step.action_type == "browser.navigate":
        return RecoveryAction(
            tool_name="open_url",
            parameters={"url": step.parameters.get("url", "")},
            reason="Retry navigation by opening the URL directly.",
        )
    if step.tool_name == "open_application" or step.action_type == "desktop.open_app":
        return RecoveryAction(
            tool_name="search_local_apps",
            parameters={"query": step.parameters.get("app_name", "")},
            reason="Search installed apps to find a better local match.",
        )
    if "not found" in normalized and step.verification_target:
        return RecoveryAction(
            tool_name="list_open_windows",
            parameters={"query": step.verification_target},
            reason="Inspect open windows to verify whether the target is already available.",
        )
    return None
