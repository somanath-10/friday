"""
Command pipeline executor.

The executor defaults to dry-run mode so this new structured layer can be wired
in without taking over the existing local chat behavior.
"""

from __future__ import annotations

import subprocess
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from friday.core.events import EventLog, EventType
from friday.core.models import (
    ExecutionPlan,
    PipelineResult,
    PipelineRunResult,
    Plan,
    PlanStep,
    StepExecutionResult,
    StructuredStepResult,
)
from friday.core.permissions import permission_for_assessment
from friday.core.planner import build_execution_plan, create_plan
from friday.core.recovery import choose_recovery_action, recover_step
from friday.core.risk import RiskAssessment, RiskLevel
from friday.core.router import route_intent, route_user_command
from friday.core.task_context import contextualize_user_message, remember_plan_context
from friday.core.verifier import verify_step_sync
from friday.path_utils import resolve_user_path, workspace_dir
from friday.safety.audit_log import append_audit_record
from friday.safety.approval_gate import create_approval_request, get_pending_approval, register_pending_approval
from friday.safety.emergency_stop import emergency_stop_status


def _assessment_from_step(step: PlanStep) -> RiskAssessment:
    return RiskAssessment(
        level=step.risk_level,
        reason=step.description,
        category=step.executor,
    )


def _dry_run_result(step: PlanStep, decision: str) -> StepExecutionResult:
    return StepExecutionResult(
        step_id=step.id,
        status="dry_run",
        output=f"Dry run: would execute {step.executor}.{step.action_type} with {step.parameters}",
        permission_decision=decision,
        dry_run=True,
    )


TOOL_FAILURE_PREFIXES = (
    "approval required",
    "[approval required]",
    "blocked by",
    "command failed",
    "error ",
    "error:",
    "failed ",
    "failure:",
    "permission denied",
)

TOOL_FAILURE_MARKERS = (
    "could not ",
    "couldn't ",
    "does not exist",
    "not found",
    "timed out",
    "unable to ",
)

TASK_STATUS_LABELS = {
    "completed": "completed",
    "partially_completed": "partially completed",
    "needs_approval": "approval needed",
    "needs_clarification": "needs clarification",
    "blocked": "blocked",
    "failed": "failed",
    "cancelled": "cancelled",
    "emergency_stopped": "emergency stopped",
}


def _tool_output_status(output: Any) -> str:
    text = str(output).strip().lower()
    if not text:
        return "failed"
    if text.startswith(("approval required", "[approval required]")) or "approval_id:" in text and "approval required" in text:
        return "permission_required"
    if text.startswith("blocked by"):
        return "blocked"
    if re.search(r"exited with code\s+(?!0\b)\d+", text):
        return "failed"
    if any(marker in text for marker in ("cancelled", "canceled", "user cancelled", "user canceled")):
        return "failed"
    if text.startswith("needs_clarification") or "needs clarification" in text or "clarification is required" in text:
        return "failed"
    if text.startswith(TOOL_FAILURE_PREFIXES):
        return "failed"
    if any(marker in text for marker in TOOL_FAILURE_MARKERS):
        if any(success_marker in text for success_marker in ("found ", "opened ", "clicked ", "written ", "created ", "verified")):
            return "succeeded"
        return "failed"
    return "succeeded"


def _step_title(plan: ExecutionPlan | Plan, step_id: str) -> str:
    for step in plan.steps:
        if step.id == step_id:
            return step.description or step.id
    return step_id


def _goal_completion_state(
    plan: ExecutionPlan | Plan,
    step_results: list[StructuredStepResult] | list[StepExecutionResult],
    verification_results: list[Any] | None = None,
    *,
    permission_pending: bool = False,
) -> tuple[str, list[str], list[str], bool, list[str]]:
    completed_ids: list[str] = []
    verified_ids: set[str] = set()
    evidence: list[str] = []
    joined_outputs = " ".join(
        f"{getattr(result, 'output', '')} {getattr(result, 'error', '')}".lower()
        for result in step_results
    )
    for result in step_results:
        success = (
            bool(getattr(result, "success", False))
            if isinstance(result, StructuredStepResult)
            else getattr(result, "status", "") in {"succeeded", "dry_run"}
        )
        verified = bool(getattr(result, "verified", False)) if isinstance(result, StructuredStepResult) else success
        if success and verified:
            completed_ids.append(result.step_id)
            verified_ids.add(result.step_id)
            output = str(getattr(result, "output", "") or "")
            if output:
                evidence.append(output[:300])
        elif not success:
            output = str(getattr(result, "error", "") or getattr(result, "output", "") or "")
            if output:
                evidence.append(output[:300])

    if verification_results is not None:
        completed_ids = []
        verified_ids = set()
        evidence = []
        for verification in verification_results:
            if getattr(verification, "ok", False):
                completed_ids.append(verification.step_id)
                verified_ids.add(verification.step_id)
                evidence.append(str(getattr(verification, "detail", ""))[:300])

    remaining_ids = [step.id for step in plan.steps if step.id not in verified_ids]
    final_goal_verified = bool(plan.steps) and not remaining_ids and len(step_results) == len(plan.steps)
    needs_clarification = any("needs_clarification" in note for note in getattr(plan, "notes", []))

    if "emergency stop" in joined_outputs or "emergency_stopped" in joined_outputs:
        task_status = "emergency_stopped"
    elif any(marker in joined_outputs for marker in ("cancelled", "canceled", "user cancelled", "user canceled")):
        task_status = "cancelled"
    elif needs_clarification or "needs clarification" in joined_outputs or "clarification is required" in joined_outputs:
        task_status = "needs_clarification"
    elif permission_pending:
        task_status = "needs_approval"
    elif final_goal_verified:
        task_status = "completed"
    elif completed_ids and remaining_ids:
        task_status = "partially_completed"
    elif any(
        any(
            marker in f"{getattr(result, 'output', '')} {getattr(result, 'error', '')}".lower()
            for marker in ("blocked", "restricted", "destructive", "safety policy")
        )
        for result in step_results
    ):
        task_status = "blocked"
    elif any(
        (getattr(result, "error", "") or "").strip()
        or (
            not bool(getattr(result, "success", True))
            if isinstance(result, StructuredStepResult)
            else getattr(result, "status", "") == "failed"
        )
        for result in step_results
    ):
        task_status = "failed"
    else:
        task_status = "blocked"

    return task_status, completed_ids, remaining_ids, final_goal_verified, evidence


def _format_step_list(plan: ExecutionPlan | Plan, step_ids: list[str]) -> str:
    return ", ".join(_step_title(plan, step_id) for step_id in step_ids[:3])


def _step_subject(step: PlanStep) -> str:
    return str(
        step.parameters.get("file_path")
        or step.parameters.get("path")
        or step.parameters.get("command")
        or step.parameters.get("app_name")
        or step.parameters.get("url")
        or step.parameters.get("goal")
        or step.verification_target
        or ""
    )


def _artifact_path_from_output(output: str) -> str:
    match = re.search(r"([A-Za-z]:\\[^\s]+|/[^\s]+?\.(?:png|jpg|jpeg|mp4|webm|txt|json|md))", output)
    return match.group(1).strip(".,;") if match else ""


def _next_action_for_status(plan: ExecutionPlan, task_status: str, remaining_steps: list[str]) -> str:
    if task_status == "completed":
        return "None."
    if task_status == "needs_approval":
        next_step = _format_step_list(plan, remaining_steps) or "the next protected step"
        return f"[Approval Required] Approve or deny {next_step}."
    if task_status == "needs_clarification":
        notes = " ".join(plan.notes).lower()
        if "calculator" in notes:
            return "Tell me which project folder should receive the calculator page."
        if "react project name and location" in notes:
            return "Tell me the project name and location before initialization."
        clarification = _clarification_from_notes(plan.notes)
        return clarification or "Clarify the exact target or missing details."
    if task_status == "blocked":
        return "Choose a safer target or change the request."
    if task_status == "emergency_stopped":
        return "Clear the emergency stop before running more local actions."
    if task_status == "cancelled":
        return "Restart or revise the request when you want to continue."
    return "Review the failure evidence and retry after the issue is fixed."


def _clarification_from_notes(notes: list[str]) -> str:
    for note in notes:
        if "needs_clarification:" in note:
            detail = note.split("needs_clarification:", 1)[1].strip()
            if detail:
                return detail
    return ""


def _format_task_reply(
    plan: ExecutionPlan,
    task_status: str,
    completed_steps: list[str],
    remaining_steps: list[str],
    evidence: list[str],
) -> str:
    completed = _format_step_list(plan, completed_steps) if completed_steps else "No required steps were verified."
    not_completed = _format_step_list(plan, remaining_steps) if remaining_steps else "Nothing."
    if task_status == "completed" and not completed_steps:
        completed = plan.goal
    verification = "Final goal verification passed." if task_status == "completed" else "Final goal verification did not pass."
    if evidence:
        verification = evidence[-1]
    next_action = _next_action_for_status(plan, task_status, remaining_steps)
    return (
        f"Status: {TASK_STATUS_LABELS.get(task_status, task_status)}.\n"
        "What I did:\n"
        f"- {completed}\n"
        "What I did not complete:\n"
        f"- {not_completed}\n"
        "Verification:\n"
        f"- {verification}\n"
        "Needs your input:\n"
        f"- {next_action}"
    )


def _completed_reply(plan: ExecutionPlan, evidence: list[str]) -> str:
    completed_steps = [step.id for step in plan.steps]
    return _format_task_reply(plan, "completed", completed_steps, [], evidence)


def _legacy_completed_summary(plan: ExecutionPlan, evidence: list[str]) -> str:
    lowered = plan.goal.lower()
    video_verified = any(step.action_type == "verify_video_opened" for step in plan.steps)
    video_clicked = any(
        step.action_type == "click_first_result" and "video" in step.verification_target.lower()
        for step in plan.steps
    )
    if video_verified or video_clicked:
        return "Opened the first YouTube video from the search results."
    if "react" in lowered and "calculator" in lowered:
        project_path = ""
        for step in plan.steps:
            if step.action_type == "verify_react_project":
                project_path = str(step.parameters.get("project_path") or step.verification_target)
                break
        return f"Created React calculator project at {project_path or 'the requested location'} and verified the build/project files."
    if plan.intent == "screenshot":
        return "Captured the screenshot and verified a screenshot artifact or analysis output was returned."
    if plan.intent == "screen_recording":
        if any(step.action_type == "stop_screen_recording" for step in plan.steps):
            return "Stopped the screen recording and reported the local artifact state."
        return "Completed the requested screen recording action."
    if plan.intent == "desktop" and plan.steps and plan.steps[0].action_type in {"open_app", "desktop.open_app"}:
        return f"Opened {plan.steps[0].parameters.get('app_name', 'the requested application')}."
    if plan.intent == "files" and any(step.action_type == "write_file" for step in plan.steps):
        return "Created the requested file and verified it exists."
    return f"Goal verified: {plan.goal}"


def _incomplete_reply(plan: ExecutionPlan, task_status: str, completed_steps: list[str], remaining_steps: list[str], evidence: list[str]) -> str:
    return _format_task_reply(plan, task_status, completed_steps, remaining_steps, evidence)


def _execute_allowed_step(step: PlanStep, *, goal: str = "") -> StepExecutionResult:
    try:
        if step.executor == "desktop":
            from friday.desktop.runtime import execute as execute_desktop

            desktop_result = execute_desktop(goal, step, dry_run=False)
            return StepExecutionResult(
                step.id,
                "succeeded" if desktop_result.ok else "failed",
                desktop_result.message,
                desktop_result.permission_decision,
                dry_run=False,
                error="" if desktop_result.ok else desktop_result.message,
            )

        if step.executor == "browser":
            from friday.browser.runtime import BrowserRuntime

            browser_result = BrowserRuntime().execute(goal, step, dry_run=False)
            return StepExecutionResult(
                step.id,
                "succeeded" if browser_result.ok else "failed",
                browser_result.message,
                browser_result.permission_decision,
                dry_run=False,
                error="" if browser_result.ok else browser_result.message,
            )

        if step.executor == "research":
            from friday.research.runtime import ResearchRuntime

            research_result = ResearchRuntime().execute(str(step.parameters.get("query") or goal), dry_run=False)
            return StepExecutionResult(
                step.id,
                "succeeded" if research_result.ok else "failed",
                research_result.message,
                dry_run=False,
                error="" if research_result.ok else research_result.message,
            )

        if step.executor == "code":
            from friday.code.runtime import CodeRuntime

            code_result = CodeRuntime(Path.cwd()).execute(goal, step, dry_run=False)
            return StepExecutionResult(
                step.id,
                "succeeded" if code_result.ok else "failed",
                code_result.message,
                dry_run=False,
                error="" if code_result.ok else code_result.message,
            )

        if step.executor == "files":
            from friday.files.runtime import FileRuntime

            file_result = FileRuntime().execute(goal, step, dry_run=False)
            return StepExecutionResult(
                step.id,
                "succeeded" if file_result.ok else "failed",
                file_result.message,
                file_result.permission_decision,
                dry_run=False,
                error="" if file_result.ok else file_result.message,
            )

        if step.executor == "screen_recording":
            from friday.desktop.recording import start_screen_recording, stop_screen_recording, current_recording_state, ScreenRecordingResult

            if step.action_type == "start_screen_recording":
                recording_result = start_screen_recording(
                    max_duration_seconds=int(step.parameters.get("max_duration_seconds", 60)),
                    dry_run=False,
                )
            elif step.action_type == "stop_screen_recording":
                recording_result = stop_screen_recording()
            elif step.action_type == "analyze_screen_recording":
                state = current_recording_state()
                recording_result = ScreenRecordingResult(
                    bool(state),
                    "analyze_screen_recording",
                    f"Recording state: {state}" if state else "No recording artifact is available to analyze.",
                    artifact_path=str(state.get("artifact_path", "")) if isinstance(state, dict) else "",
                    metadata=state if isinstance(state, dict) else {},
                )
            else:
                recording_result = ScreenRecordingResult(False, step.action_type, f"No screen recording handler for action: {step.action_type}")
            return StepExecutionResult(
                step.id,
                "succeeded" if recording_result.ok else "failed",
                recording_result.message,
                recording_result.permission_decision,
                dry_run=False,
                error="" if recording_result.ok else recording_result.message,
            )

        if step.action_type == "shell_command":
            from friday.shell.runtime import ShellRuntime

            command = str(step.parameters.get("command", "")).strip()
            shell_result = ShellRuntime().execute_command(command, cwd=workspace_dir(), dry_run=False)
            output = (shell_result.stdout or "").strip()
            if shell_result.stderr.strip():
                output = (output + "\n" if output else "") + shell_result.stderr.strip()
            return StepExecutionResult(
                step.id,
                "succeeded" if shell_result.ok else "failed",
                output or shell_result.message,
                shell_result.permission_decision,
                dry_run=False,
                error="" if shell_result.ok else shell_result.message,
            )

        if step.action_type == "write_file":
            path_text = str(step.parameters.get("path", ""))
            content = str(step.parameters.get("content", ""))
            target = resolve_user_path(path_text)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                return StepExecutionResult(step.id, "blocked", f"Refusing overwrite without explicit approval: {target}", "block", dry_run=False)
            target.write_text(content, encoding="utf-8")
            return StepExecutionResult(step.id, "succeeded", f"Wrote file: {target}", dry_run=False)

        if step.action_type == "status":
            return StepExecutionResult(step.id, "succeeded", f"Workspace: {workspace_dir()}", dry_run=False)

        return StepExecutionResult(
            step.id,
            "failed",
            "",
            dry_run=False,
            error=f"No concrete executor is implemented for {step.executor}.{step.action_type}.",
        )
    except Exception as exc:
        return StepExecutionResult(step.id, "failed", "", dry_run=False, error=str(exc))


def execute_plan(plan: Plan, *, dry_run: bool = True, event_log: EventLog | None = None) -> PipelineResult:
    events = event_log or EventLog()
    step_results: list[StepExecutionResult] = []
    verification_results = []
    recovery_results = []

    for step in plan.steps:
        events.emit(EventType.STEP_STARTED, f"Starting step {step.id}: {step.description}", step=step.to_dict())
        events.emit(EventType.TOOL_STARTED, f"Starting {step.id}: {step.description}", step=step.to_dict())
        decision = permission_for_assessment(
            f"{step.executor}.{step.action_type}",
            _assessment_from_step(step),
            subject=str(step.parameters.get("path") or step.parameters.get("command") or step.parameters.get("app_name") or ""),
        )

        if decision.decision == "ask":
            approval = create_approval_request(
                decision,
                tool=f"{step.executor}.{step.action_type}",
                command=str(step.parameters.get("command", "")),
                path=str(step.parameters.get("path", "")),
            )
            events.emit(EventType.PERMISSION_REQUIRED, decision.reason, approval=approval.to_dict())
            result = StepExecutionResult(step.id, "permission_required", approval.action_summary, "ask", dry_run=dry_run)
        elif decision.decision == "block":
            events.emit(EventType.PERMISSION_DENIED, decision.reason, step=step.to_dict())
            result = StepExecutionResult(step.id, "blocked", decision.reason, "block", dry_run=dry_run)
        elif dry_run:
            events.emit(EventType.PERMISSION_GRANTED, decision.reason, step=step.to_dict())
            result = _dry_run_result(step, decision.decision)
        else:
            events.emit(EventType.PERMISSION_GRANTED, decision.reason, step=step.to_dict())
            result = _execute_allowed_step(step, goal=plan.goal)

        step_results.append(result)
        append_audit_record(
            command=plan.goal,
            intent=plan.intent.intent.value,
            plan=plan.to_dict(),
            risk_level=int(step.risk_level),
            decision=result.permission_decision,
            tool=f"{step.executor}.{step.action_type}",
            result=result.output or result.error,
        )

        if result.status in {"succeeded", "dry_run"}:
            events.emit(EventType.TOOL_SUCCEEDED, f"{step.id} completed.", result=result.to_dict())
        else:
            events.emit(EventType.TOOL_FAILED, f"{step.id} failed or paused.", result=result.to_dict())

        verification = verify_step_sync(step, result)
        verification_results.append(verification)
        if verification.ok:
            events.emit(EventType.VERIFICATION_SUCCEEDED, verification.detail, verification=verification.to_dict())
        else:
            events.emit(EventType.VERIFICATION_FAILED, verification.detail, verification=verification.to_dict())
            recovery = recover_step(step, result)
            recovery_results.append(recovery)
            if recovery.attempted:
                events.emit(EventType.RECOVERY_STARTED, recovery.detail, recovery=recovery.to_dict())
            break

    permission_pending = any(result.status == "permission_required" for result in step_results)
    task_status, completed_steps, remaining_steps, final_goal_verified, evidence = _goal_completion_state(
        plan,
        step_results,
        verification_results,
        permission_pending=permission_pending,
    )
    status = "completed" if task_status == "completed" else ("failed" if task_status == "failed" else "paused")
    events.emit(EventType.WORKFLOW_COMPLETED, f"Pipeline {status}.", status=status)

    return PipelineResult(
        command=plan.goal,
        plan=plan,
        events=events.to_list(),
        step_results=step_results,
        verification_results=verification_results,
        recovery_results=recovery_results,
        status=status,
        task_status=task_status,
        completed_steps=completed_steps,
        remaining_steps=remaining_steps,
        final_goal_verified=final_goal_verified,
        verification_evidence=evidence,
    )


def run_command_pipeline(user_message: str, *, dry_run: bool = True) -> PipelineResult:
    events = EventLog()
    events.emit(EventType.COMMAND_RECEIVED, "Command received.", command=user_message)
    intent = route_intent(user_message)
    events.emit(EventType.INTENT_DETECTED, f"Intent detected: {intent.intent.value}", intent=intent.to_dict())
    plan = create_plan(user_message, intent)
    events.emit(EventType.PLAN_CREATED, "Plan created.", plan=plan.to_dict())
    result = execute_plan(plan, dry_run=dry_run, event_log=events)
    try:
        from friday.memory.action_trace import save_action_trace
        from friday.memory.workflow_memory import remember_workflow_pattern

        save_action_trace(
            user_message,
            plan.to_dict(),
            result.to_dict(),
        )
        if result.status == "completed":
            remember_workflow_pattern(
                user_message,
                {
                    "intent": intent.intent.value,
                    "steps": [step.to_dict() for step in plan.steps],
                },
            )
    except Exception:
        pass
    return result


class StructuredExecutor:
    """Async compatibility executor used by the local chat bridge and tests."""

    def __init__(self, tool_invoker):
        self._tool_invoker = tool_invoker

    async def execute(self, plan: ExecutionPlan) -> PipelineRunResult:
        pipeline_events: list[dict[str, Any]] = []
        tool_events: list[dict[str, Any]] = []
        step_results: list[StructuredStepResult] = []
        approval_requests: list[dict[str, Any]] = []

        if not plan.supported:
            reply = _format_task_reply(
                plan,
                "blocked",
                [],
                [step.id for step in plan.steps],
                ["This request needs a fallback path outside the structured executor."],
            )
            return PipelineRunResult(
                handled=False,
                success=False,
                reply=reply,
                plan=plan,
                used_legacy_fallback=True,
                task_status="blocked",
                final_goal_verified=False,
            )

        if not plan.steps:
            task_status = "needs_clarification" if any("needs_clarification" in note for note in plan.notes) else "blocked"
            reply = _incomplete_reply(plan, task_status, [], [], [])
            return PipelineRunResult(
                handled=True,
                success=False,
                reply=reply,
                plan=plan,
                task_status=task_status,
                completed_steps=[],
                remaining_steps=[],
                final_goal_verified=False,
                verification_evidence=[],
            )

        permission_pending = False
        for step in plan.steps:
            pipeline_events.append({"event_type": "step_started", "name": step.tool_name, "step_id": step.id, "executor": step.executor, "action": step.action_type})
            pipeline_events.append({"event_type": "tool_started", "name": step.tool_name, "step_id": step.id})
            pipeline_events.append({"event_type": "observation_started", "name": step.tool_name, "step_id": step.id})
            pipeline_events.append({"event_type": "observation_completed", "name": step.tool_name, "step_id": step.id})
            decision = permission_for_assessment(
                step.tool_name or f"{step.executor}.{step.action_type}",
                _assessment_from_step(step),
                subject=_step_subject(step),
            )
            if decision.decision == "ask":
                approval = create_approval_request(
                    decision,
                    tool=step.tool_name or f"{step.executor}.{step.action_type}",
                    command=str(step.parameters.get("command", "")),
                    path=str(step.parameters.get("file_path") or step.parameters.get("path") or ""),
                    domain=str(step.parameters.get("url") or ""),
                )
                approval_payload = {
                    "command": plan.goal,
                    "plan": plan.to_dict(),
                    "resume_from_step_id": step.id,
                }
                register_pending_approval(approval, payload=approval_payload)
                append_audit_record(
                    command=plan.goal,
                    intent=plan.intent,
                    plan=plan.to_dict(),
                    risk_level=int(step.risk_level),
                    decision="ask",
                    tool=step.tool_name or f"{step.executor}.{step.action_type}",
                    result=approval.action_summary,
                    extra={
                        "resolved_goal": plan.goal,
                        "executor": step.executor,
                        "action": step.action_type,
                        "target": _step_subject(step),
                        "approval_id": approval.approval_id,
                    },
                )
                approval_requests.append(approval.to_dict())
                pipeline_events.append(
                    {
                        "event_type": "permission_required",
                        "name": step.tool_name,
                        "step_id": step.id,
                        "approval_request": approval.to_dict(),
                    }
                )
                permission_pending = True
                step_results.append(
                    StructuredStepResult(
                        step_id=step.id,
                        tool_name=step.tool_name,
                        success=False,
                        output=f"[Approval Required] {approval.action_summary}",
                    )
                )
                break
            if decision.decision == "block":
                pipeline_events.append({"event_type": "permission_denied", "name": step.tool_name, "step_id": step.id})
                blocked_message = f"Blocked by FRIDAY safety policy: {decision.reason}"
                append_audit_record(
                    command=plan.goal,
                    intent=plan.intent,
                    plan=plan.to_dict(),
                    risk_level=int(step.risk_level),
                    decision="block",
                    tool=step.tool_name or f"{step.executor}.{step.action_type}",
                    result=blocked_message,
                    errors=blocked_message,
                    extra={
                        "resolved_goal": plan.goal,
                        "executor": step.executor,
                        "action": step.action_type,
                        "target": _step_subject(step),
                    },
                )
                step_results.append(
                    StructuredStepResult(
                        step_id=step.id,
                        tool_name=step.tool_name,
                        success=False,
                        output=blocked_message,
                        error=blocked_message,
                    )
                )
                break

            pipeline_events.append({"event_type": "permission_granted", "name": step.tool_name, "step_id": step.id})
            if plan.dry_run:
                pipeline_events.append({"event_type": "tool_succeeded", "name": step.tool_name, "step_id": step.id})
                step_results.append(
                    StructuredStepResult(
                        step_id=step.id,
                        tool_name=step.tool_name,
                        success=True,
                        output=f"Dry run: would call {step.tool_name}",
                        verified=True,
                    )
                )
                continue

            pipeline_events.append({"event_type": "action_started", "name": step.tool_name, "step_id": step.id})
            output = await self._tool_invoker(step.tool_name, dict(step.parameters))
            output_status = _tool_output_status(output)
            pipeline_events.append({"event_type": "action_completed", "name": step.tool_name, "step_id": step.id, "status": output_status})
            tool_events.append({"name": step.tool_name, "ok": output_status == "succeeded", "preview": str(output)[:220]})
            pipeline_events.append({"event_type": "verification_started", "name": step.tool_name, "step_id": step.id})
            verification = verify_step_sync(step, output)
            append_audit_record(
                command=plan.goal,
                intent=plan.intent,
                plan=plan.to_dict(),
                risk_level=int(step.risk_level),
                decision=decision.decision,
                tool=step.tool_name or f"{step.executor}.{step.action_type}",
                result=str(output),
                verification=verification.to_dict(),
                errors="" if output_status == "succeeded" else str(output),
                extra={
                    "resolved_goal": plan.goal,
                    "executor": step.executor,
                    "action": step.action_type,
                    "target": _step_subject(step),
                    "artifact_path": _artifact_path_from_output(str(output)),
                },
            )
            pipeline_events.append(
                {
                    "event_type": "verification_succeeded" if verification.passed else "verification_failed",
                    "name": step.tool_name,
                    "step_id": step.id,
                    "detail": verification.detail,
                }
            )
            if output_status == "permission_required":
                permission_pending = True
                pipeline_events.append({"event_type": "permission_required", "name": step.tool_name, "step_id": step.id})
                step_results.append(
                    StructuredStepResult(
                        step_id=step.id,
                        tool_name=step.tool_name,
                        success=False,
                        output=str(output),
                        verified=False,
                        error=str(output),
                    )
                )
                break
            if output_status == "blocked":
                pipeline_events.append({"event_type": "permission_denied", "name": step.tool_name, "step_id": step.id})
                step_results.append(
                    StructuredStepResult(
                        step_id=step.id,
                        tool_name=step.tool_name,
                        success=False,
                        output=str(output),
                        verified=False,
                        error=str(output),
                    )
                )
                break
            if output_status == "failed" and not verification.passed:
                recovery = choose_recovery_action(step, str(output), attempts=0)
                recovered = False
                if recovery is not None:
                    pipeline_events.append({"event_type": "recovery_started", "name": recovery.tool_name, "step_id": step.id})
                    recovery_output = await self._tool_invoker(recovery.tool_name, dict(recovery.parameters))
                    recovery_status = _tool_output_status(recovery_output)
                    tool_events.append({"name": recovery.tool_name, "ok": recovery_status == "succeeded", "preview": str(recovery_output)[:220]})
                    recovered = recovery_status == "succeeded"
                pipeline_events.append({"event_type": "tool_failed", "name": step.tool_name, "step_id": step.id})
                step_results.append(
                    StructuredStepResult(
                        step_id=step.id,
                        tool_name=step.tool_name,
                        success=False,
                        output=str(output),
                        verified=False,
                        recovered=recovered,
                        error=str(output),
                    )
                )
                break
            if verification.passed:
                pipeline_events.append({"event_type": "tool_succeeded", "name": step.tool_name, "step_id": step.id})
                step_results.append(
                    StructuredStepResult(
                        step_id=step.id,
                        tool_name=step.tool_name,
                        success=True,
                        output=str(output),
                        verified=True,
                    )
                )
                continue

            recovery = choose_recovery_action(step, str(output), attempts=0)
            recovered = False
            if recovery is not None:
                pipeline_events.append({"event_type": "recovery_started", "name": recovery.tool_name, "step_id": step.id})
                recovery_output = await self._tool_invoker(recovery.tool_name, dict(recovery.parameters))
                recovery_status = _tool_output_status(recovery_output)
                tool_events.append({"name": recovery.tool_name, "ok": recovery_status == "succeeded", "preview": str(recovery_output)[:220]})
                recovered = recovery_status == "succeeded"

            pipeline_events.append({"event_type": "tool_failed", "name": step.tool_name, "step_id": step.id})
            step_results.append(
                StructuredStepResult(
                    step_id=step.id,
                    tool_name=step.tool_name,
                    success=False,
                    output=str(output),
                    verified=False,
                    recovered=recovered,
                    error=str(output),
                )
            )
            break

        task_status, completed_steps, remaining_steps, final_goal_verified, evidence = _goal_completion_state(
            plan,
            step_results,
            permission_pending=permission_pending,
        )
        reply = _completed_reply(plan, evidence) if final_goal_verified else _incomplete_reply(
            plan,
            task_status,
            completed_steps,
            remaining_steps,
            evidence,
        )

        return PipelineRunResult(
            handled=True,
            success=task_status == "completed" and final_goal_verified,
            reply=reply,
            plan=plan,
            permission_pending=permission_pending,
            tool_events=tool_events,
            pipeline_events=pipeline_events,
            step_results=step_results,
            approval_requests=approval_requests,
            task_status=task_status,
            completed_steps=completed_steps,
            remaining_steps=remaining_steps,
            final_goal_verified=final_goal_verified,
            verification_evidence=evidence,
        )


async def execute_goal(
    user_goal: str,
    tool_invoker,
    context: Any | None = None,
    *,
    dry_run: bool = False,
    max_steps: int = 50,
) -> PipelineRunResult:
    """Execute a user goal through normalize-plan-act-observe-verify semantics."""
    timeline = EventLog()
    normalized_goal = " ".join(str(user_goal or "").strip().split())
    timeline.emit(EventType.COMMAND_RECEIVED, "Goal received.", command=normalized_goal)
    stop_status = emergency_stop_status()
    if stop_status.get("stopped"):
        timeline.emit(EventType.EMERGENCY_STOP_TRIGGERED, "Emergency stop is active.", status=stop_status)
        plan = ExecutionPlan(
            goal=normalized_goal,
            intent="system",
            confidence=1.0,
            required_capabilities=[],
            suggested_executor="none",
            steps=[],
            supported=True,
            notes=["emergency_stopped: Local task execution is paused."],
        )
        reply = _format_task_reply(
            plan,
            "emergency_stopped",
            [],
            [],
            [f"Emergency stop is active: {stop_status.get('reason') or 'no reason recorded'}"],
        )
        timeline.emit(EventType.WORKFLOW_COMPLETED, "Goal emergency_stopped.", status="emergency_stopped", final_goal_verified=False)
        return PipelineRunResult(
            handled=True,
            success=False,
            reply=reply,
            plan=plan,
            pipeline_events=timeline.to_list(),
            task_status="emergency_stopped",
            completed_steps=[],
            remaining_steps=[],
            final_goal_verified=False,
            verification_evidence=[f"Emergency stop is active: {stop_status.get('reason') or 'no reason recorded'}"],
        )
    effective_message = contextualize_user_message(normalized_goal, context)
    if effective_message != normalized_goal:
        timeline.emit(
            EventType.CONTEXT_RESOLVED,
            "Resolved contextual follow-up.",
            original=normalized_goal,
            resolved=effective_message,
        )
    route = route_user_command(effective_message)
    timeline.emit(EventType.INTENT_DETECTED, f"Intent detected: {route.intent}.", intent=route.to_dict())
    plan = build_execution_plan(effective_message, route)
    if max_steps > 0 and len(plan.steps) > max_steps:
        plan = ExecutionPlan(
            goal=plan.goal,
            intent=plan.intent,
            confidence=plan.confidence,
            required_capabilities=plan.required_capabilities,
            suggested_executor=plan.suggested_executor,
            steps=plan.steps[:max_steps],
            supported=plan.supported,
            dry_run=plan.dry_run,
            notes=[*plan.notes, "max_steps_reached: plan was truncated before execution."],
        )
    timeline.emit(EventType.PLAN_CREATED, "Execution plan created.", plan=plan.to_dict())
    if not plan.supported:
        reply = _format_task_reply(
            plan,
            "blocked",
            [],
            [step.id for step in plan.steps],
            ["This request needs a fallback path outside the structured executor."],
        )
        return PipelineRunResult(
            handled=False,
            success=False,
            reply=reply,
            plan=plan,
            used_legacy_fallback=True,
            task_status="blocked",
            final_goal_verified=False,
        )

    plan = ExecutionPlan(
        goal=plan.goal,
        intent=plan.intent,
        confidence=plan.confidence,
        required_capabilities=plan.required_capabilities,
        suggested_executor=plan.suggested_executor,
        steps=plan.steps,
        supported=plan.supported,
        dry_run=dry_run,
        notes=plan.notes,
    )
    result = await StructuredExecutor(tool_invoker).execute(plan)
    final_event = {
        "completed": EventType.TASK_COMPLETED,
        "partially_completed": EventType.TASK_PARTIAL,
        "needs_approval": EventType.PERMISSION_REQUIRED,
        "needs_clarification": EventType.TASK_BLOCKED,
        "blocked": EventType.TASK_BLOCKED,
        "failed": EventType.TASK_FAILED,
        "cancelled": EventType.TASK_CANCELLED,
        "emergency_stopped": EventType.EMERGENCY_STOP_TRIGGERED,
    }.get(result.task_status, EventType.TASK_FAILED)
    timeline.emit(final_event, f"Goal status: {result.task_status}.", status=result.task_status)
    for event in result.tool_events:
        artifact = _artifact_path_from_output(str(event.get("preview", "")))
        if artifact:
            timeline.emit(EventType.ARTIFACT_CREATED, "Artifact created.", artifact_path=artifact)
    timeline.emit(
        EventType.WORKFLOW_COMPLETED,
        f"Goal {result.task_status}.",
        status=result.task_status,
        final_goal_verified=result.final_goal_verified,
    )
    visible_state = "\n".join(str(event.get("preview", "")) for event in result.tool_events if str(event.get("name", "")).startswith("browser"))
    artifacts: dict[str, Any] = {}
    for step in plan.steps:
        if step.action_type == "verify_react_project":
            artifacts["react_project_path"] = step.parameters.get("project_path") or step.verification_target
            break
    for event in result.tool_events:
        artifact = _artifact_path_from_output(str(event.get("preview", "")))
        if artifact:
            artifacts.setdefault("artifact_path", artifact)
            if artifact.lower().endswith((".png", ".jpg", ".jpeg")):
                artifacts.setdefault("screenshot_path", artifact)
            break
    remember_plan_context(plan, visible_page_state=visible_state, artifacts=artifacts, result=result)
    try:
        from friday.memory.action_trace import save_action_trace
        from friday.memory.workflow_memory import remember_workflow_pattern

        save_action_trace(normalized_goal, plan.to_dict(), result.to_dict())
        if result.final_goal_verified:
            remember_workflow_pattern(
                normalized_goal,
                {"intent": plan.intent, "steps": [step.to_dict() for step in plan.steps]},
            )
        timeline.emit(EventType.WORKFLOW_SAVED, "Workflow trace saved.", status=result.task_status)
    except Exception:
        pass
    result = replace(result, pipeline_events=[*timeline.to_list(), *result.pipeline_events])
    return result


async def run_structured_command(user_message: str, tool_invoker, dry_run: bool = False) -> PipelineRunResult:
    return await execute_goal(user_message, tool_invoker, dry_run=dry_run)


def _plan_step_from_dict(payload: dict[str, Any]) -> PlanStep:
    return PlanStep(
        id=str(payload.get("id", "")),
        description=str(payload.get("description", "")),
        executor=str(payload.get("executor", "")),
        action_type=str(payload.get("action_type", "")),
        parameters=dict(payload.get("parameters") or {}),
        expected_result=str(payload.get("expected_result", "")),
        risk_level=RiskLevel(int(payload.get("risk_level", 0))),
        needs_approval=bool(payload.get("needs_approval", False)),
        verification_method=str(payload.get("verification_method", "")),
        tool_name=str(payload.get("tool_name", "")),
        verification_target=str(payload.get("verification_target", "")),
        fallback_strategy=str(payload.get("fallback_strategy", "")),
    )


def execution_plan_from_dict(payload: dict[str, Any]) -> ExecutionPlan:
    return ExecutionPlan(
        goal=str(payload.get("goal", "")),
        intent=str(payload.get("intent", "")),
        confidence=float(payload.get("confidence", 0.0)),
        required_capabilities=list(payload.get("required_capabilities") or []),
        suggested_executor=str(payload.get("suggested_executor", "")),
        steps=[_plan_step_from_dict(step) for step in payload.get("steps", []) if isinstance(step, dict)],
        supported=bool(payload.get("supported", True)),
        dry_run=bool(payload.get("dry_run", False)),
        notes=list(payload.get("notes") or []),
    )


def _slice_plan_from_step(plan: ExecutionPlan, step_id: str) -> ExecutionPlan:
    if not step_id:
        return plan
    start_index = 0
    for index, step in enumerate(plan.steps):
        if step.id == step_id:
            start_index = index
            break
    return ExecutionPlan(
        goal=plan.goal,
        intent=plan.intent,
        confidence=plan.confidence,
        required_capabilities=plan.required_capabilities,
        suggested_executor=plan.suggested_executor,
        steps=plan.steps[start_index:],
        supported=plan.supported,
        dry_run=False,
        notes=plan.notes,
    )


async def resume_approved_structured_command(
    approval_id: str,
    tool_invoker,
    *,
    dry_run: bool = False,
) -> PipelineRunResult:
    record = get_pending_approval(approval_id)
    if not record:
        return PipelineRunResult(
            handled=True,
            success=False,
            reply="Approval request was not found or has expired.",
            task_status="failed",
            final_goal_verified=False,
        )
    if record.get("status") != "approved":
        return PipelineRunResult(
            handled=True,
            success=False,
            reply="Approval request has not been approved.",
            permission_pending=True,
            task_status="needs_approval",
            final_goal_verified=False,
        )

    payload = dict(record.get("payload") or {})
    raw_plan = payload.get("plan")
    if not isinstance(raw_plan, dict):
        return PipelineRunResult(
            handled=True,
            success=False,
            reply="Approval request did not include a resumable plan.",
            task_status="failed",
            final_goal_verified=False,
        )

    plan = execution_plan_from_dict(raw_plan)
    plan = _slice_plan_from_step(plan, str(payload.get("resume_from_step_id", "")))
    plan = ExecutionPlan(
        goal=plan.goal,
        intent=plan.intent,
        confidence=plan.confidence,
        required_capabilities=plan.required_capabilities,
        suggested_executor=plan.suggested_executor,
        steps=plan.steps,
        supported=plan.supported,
        dry_run=dry_run,
        notes=plan.notes,
    )
    return await StructuredExecutor(tool_invoker).execute(plan)
