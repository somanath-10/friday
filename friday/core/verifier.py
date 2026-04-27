"""
Verification helpers for pipeline step results.
"""

from __future__ import annotations

from pathlib import Path

from friday.core.models import PlanStep, StepExecutionResult, VerificationResult
from friday.path_utils import resolve_user_path


def _normalize_result(result: StepExecutionResult | str) -> StepExecutionResult:
    if isinstance(result, StepExecutionResult):
        return result
    text = str(result)
    success = not text.lower().startswith(("error", "failed"))
    return StepExecutionResult(
        step_id="",
        status="succeeded" if success else "failed",
        output=text,
        dry_run=False,
        error="" if success else text,
    )


def verify_step_sync(step: PlanStep, result: StepExecutionResult | str) -> VerificationResult:
    normalized = _normalize_result(result)
    method = step.verification_method
    if normalized.status in {"permission_required", "blocked"}:
        return VerificationResult(step.id, False, method, normalized.output)
    if normalized.status == "dry_run":
        return VerificationResult(step.id, True, method, "Dry run verified plan shape without executing the action.")
    if normalized.status != "succeeded":
        return VerificationResult(step.id, False, method, normalized.error or normalized.output)

    if method == "file_exists":
        path_text = str(step.verification_target or step.parameters.get("path") or step.parameters.get("file_path") or "")
        try:
            target = resolve_user_path(path_text)
        except Exception:
            target = Path(path_text)
        return VerificationResult(step.id, target.exists(), method, f"Path exists: {target}")

    if method == "path_absent":
        path_text = str(step.verification_target or step.parameters.get("path") or "")
        try:
            target = resolve_user_path(path_text)
        except Exception:
            target = Path(path_text)
        return VerificationResult(step.id, not target.exists(), method, f"Path absent: {target}")

    if method in {"exit_code", "command_output_ok"}:
        return VerificationResult(step.id, normalized.status == "succeeded", method, normalized.output[:300])

    if method in {"output_nonempty", "text_contains", "window_active", "screen_contains"}:
        return VerificationResult(step.id, bool(normalized.output.strip()), method, normalized.output[:300])

    return VerificationResult(step.id, True, method, "No specialized verifier for this method; command result was successful.")


def verify_step(step: PlanStep, result: StepExecutionResult | str) -> VerificationResult:
    return verify_step_sync(step, result)
