"""
Verification helpers for pipeline step results.
"""

from __future__ import annotations

from pathlib import Path
import re

from friday.core.models import PlanStep, StepExecutionResult, VerificationResult
from friday.path_utils import resolve_user_path


def _normalize_result(result: StepExecutionResult | str) -> StepExecutionResult:
    if isinstance(result, StepExecutionResult):
        return result
    text = str(result)
    lowered = text.lower().strip()
    success = not (
        lowered.startswith(("error", "failed", "command failed", "failure:", "permission denied"))
        or re.search(r"exited with code\s+(?!0\b)\d+", lowered) is not None
        or any(marker in lowered for marker in ("cancelled", "canceled", "user cancelled", "user canceled"))
        or "needs clarification" in lowered
        or "clarification is required" in lowered
    )
    return StepExecutionResult(
        step_id="",
        status="succeeded" if success else "failed",
        output=text,
        dry_run=False,
        error="" if success else text,
    )


def _result_text(result: StepExecutionResult | str) -> str:
    if isinstance(result, StepExecutionResult):
        return f"{result.output}\n{result.error}".strip()
    return str(result)


def verify_step_sync(step: PlanStep, result: StepExecutionResult | str) -> VerificationResult:
    normalized = _normalize_result(result)
    method = step.verification_method
    raw_text = _result_text(result)

    if method == "path_available":
        path_text = str(step.verification_target or step.parameters.get("path") or step.parameters.get("file_path") or "")
        try:
            target = resolve_user_path(path_text)
        except Exception:
            target = Path(path_text)
        return VerificationResult(step.id, not target.exists(), method, f"Path available for creation: {target}")

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

    if method == "browser_video_opened":
        lowered = raw_text.lower()
        signals = (
            "/watch" in lowered
            or "watch?v=" in lowered
            or "video" in lowered and any(marker in lowered for marker in ("player", "views", "subscribe", "youtube"))
            or "clicked" in lowered and "video" in lowered
        )
        return VerificationResult(step.id, signals, method, raw_text[:300] or "No browser state evidence returned.")

    if method == "browser_result_opened":
        lowered = raw_text.lower()
        signals = any(marker in lowered for marker in ("clicked", "navigated", "url:", "page title:", "opened"))
        return VerificationResult(step.id, signals, method, raw_text[:300] or "No browser state evidence returned.")

    if method == "react_project_verified":
        lowered = raw_text.lower()
        signals = (
            "verified" in lowered
            or "built" in lowered
            or "build" in lowered and "success" in lowered
            or "created" in lowered and "calculator" in lowered
        )
        return VerificationResult(step.id, signals, method, raw_text[:300] or "No project verification evidence returned.")

    if method == "artifact_or_output":
        lowered = raw_text.lower()
        signals = any(marker in lowered for marker in ("screenshot", ".png", "artifact", "ocr", "captured", "saved"))
        return VerificationResult(step.id, signals, method, raw_text[:300] or "No screenshot evidence returned.")

    if method == "screen_recording_started":
        lowered = raw_text.lower()
        signals = "recording started" in lowered or "screen recording started" in lowered
        return VerificationResult(step.id, signals, method, raw_text[:300] or "No recording start evidence returned.")

    if method == "screen_recording_stopped":
        lowered = raw_text.lower()
        signals = "recording stopped" in lowered or "screen recording stopped" in lowered or "no screen recording is active" not in lowered and "artifact" in lowered
        return VerificationResult(step.id, signals, method, raw_text[:300] or "No recording stop evidence returned.")

    if method in {"output_nonempty", "text_contains", "window_active", "screen_contains", "dynamic_goal_progress"}:
        if "needs clarification" in raw_text.lower() or "clarification is required" in raw_text.lower():
            return VerificationResult(step.id, False, method, raw_text[:300] or "Clarification is required.")
        return VerificationResult(step.id, bool(normalized.output.strip()), method, normalized.output[:300])

    return VerificationResult(step.id, True, method, "No specialized verifier for this method; command result was successful.")


def verify_step(step: PlanStep, result: StepExecutionResult | str) -> VerificationResult:
    return verify_step_sync(step, result)
