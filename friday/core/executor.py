"""
Command pipeline executor.

The executor defaults to dry-run mode so this new structured layer can be wired
in without taking over the existing local chat behavior.
"""

from __future__ import annotations

import subprocess
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
from friday.core.verifier import verify_step_sync
from friday.path_utils import resolve_user_path, workspace_dir
from friday.safety.audit_log import append_audit_record
from friday.safety.approval_gate import create_approval_request, get_pending_approval, register_pending_approval


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

    status = "completed"
    if any(result.status in {"blocked", "permission_required", "failed"} for result in step_results):
        status = "paused"
    events.emit(EventType.WORKFLOW_COMPLETED, f"Pipeline {status}.", status=status)

    return PipelineResult(
        command=plan.goal,
        plan=plan,
        events=events.to_list(),
        step_results=step_results,
        verification_results=verification_results,
        recovery_results=recovery_results,
        status=status,
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
            return PipelineRunResult(
                handled=False,
                success=False,
                reply="This request should fall back to the legacy local chat loop.",
                plan=plan,
                used_legacy_fallback=True,
            )

        permission_pending = False
        overall_success = True
        for step in plan.steps:
            pipeline_events.append({"event_type": "tool_started", "name": step.tool_name, "step_id": step.id})
            decision = permission_for_assessment(
                step.tool_name or f"{step.executor}.{step.action_type}",
                _assessment_from_step(step),
                subject=str(
                    step.parameters.get("file_path")
                    or step.parameters.get("path")
                    or step.parameters.get("command")
                    or step.parameters.get("app_name")
                    or ""
                ),
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
                overall_success = False
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
                overall_success = False
                step_results.append(
                    StructuredStepResult(
                        step_id=step.id,
                        tool_name=step.tool_name,
                        success=False,
                        output=decision.reason,
                        error=decision.reason,
                    )
                )
                continue

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

            output = await self._tool_invoker(step.tool_name, dict(step.parameters))
            tool_events.append({"name": step.tool_name, "ok": True, "preview": str(output)[:220]})
            verification = verify_step_sync(step, output)
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
            if recovery is not None:
                pipeline_events.append({"event_type": "recovery_started", "name": recovery.tool_name, "step_id": step.id})
                recovery_output = await self._tool_invoker(recovery.tool_name, dict(recovery.parameters))
                tool_events.append({"name": recovery.tool_name, "ok": True, "preview": str(recovery_output)[:220]})
                if not str(recovery_output).lower().startswith(("error", "failed")):
                    step_results.append(
                        StructuredStepResult(
                            step_id=step.id,
                            tool_name=step.tool_name,
                            success=True,
                            output=str(output),
                            verified=False,
                            recovered=True,
                        )
                    )
                    continue

            overall_success = False
            pipeline_events.append({"event_type": "tool_failed", "name": step.tool_name, "step_id": step.id})
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

        if permission_pending:
            reply = "[Approval Required] One or more steps need your permission before FRIDAY can continue."
        elif overall_success:
            reply = "Structured command completed."
        else:
            reply = "Structured command could not be completed safely."

        return PipelineRunResult(
            handled=True,
            success=overall_success and not permission_pending,
            reply=reply,
            plan=plan,
            permission_pending=permission_pending,
            tool_events=tool_events,
            pipeline_events=pipeline_events,
            step_results=step_results,
            approval_requests=approval_requests,
        )


async def run_structured_command(user_message: str, tool_invoker, dry_run: bool = False) -> PipelineRunResult:
    route = route_user_command(user_message)
    plan = build_execution_plan(user_message, route)
    if not plan.supported:
        return PipelineRunResult(
            handled=False,
            success=False,
            reply="This request should fall back to the legacy local chat loop.",
            plan=plan,
            used_legacy_fallback=True,
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
    return await StructuredExecutor(tool_invoker).execute(plan)


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
        )
    if record.get("status") != "approved":
        return PipelineRunResult(
            handled=True,
            success=False,
            reply="Approval request has not been approved.",
            permission_pending=True,
        )

    payload = dict(record.get("payload") or {})
    raw_plan = payload.get("plan")
    if not isinstance(raw_plan, dict):
        return PipelineRunResult(
            handled=True,
            success=False,
            reply="Approval request did not include a resumable plan.",
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
