"""
Structured execution for FRIDAY's command pipeline.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from friday.core.events import EventRecorder
from friday.core.models import (
    ExecutionPlan,
    IntentRoute,
    PipelineRunResult,
    PlanStep,
    StepExecutionResult,
    VerificationResult,
)
from friday.core.permissions import authorize_tool_call, format_permission_response
from friday.core.planner import build_execution_plan
from friday.core.recovery import choose_recovery_action
from friday.core.router import route_user_command
from friday.core.verifier import verify_step
from friday.path_utils import workspace_dir


ToolInvoker = Callable[[str, dict[str, object]], Awaitable[str]]


class StructuredExecutor:
    """Executes structured plans with permission checks, verification, and recovery."""

    def __init__(self, tool_invoker: ToolInvoker, recorder: EventRecorder | None = None) -> None:
        self.tool_invoker = tool_invoker
        self.recorder = recorder or EventRecorder()
        self.tool_events: list[dict[str, object]] = []

    async def execute(self, plan: ExecutionPlan) -> PipelineRunResult:
        self.recorder.emit(
            "plan_created",
            "Structured execution plan created.",
            step_count=len(plan.steps),
            intent=plan.intent,
            dry_run=plan.dry_run,
        )

        if not plan.supported or not plan.steps:
            return PipelineRunResult(
                handled=False,
                success=False,
                reply="The structured pipeline could not build a supported plan for this command.",
                plan=plan,
                pipeline_events=self.recorder.as_list(),
                tool_events=list(self.tool_events),
                used_legacy_fallback=True,
            )

        step_results: list[StepExecutionResult] = []
        permission_pending = False

        for step in plan.steps:
            if plan.dry_run:
                self.recorder.emit(
                    "tool_started",
                    f"Dry run prepared step {step.id}.",
                    step_id=step.id,
                    tool=step.tool_name,
                )
                verification = VerificationResult(
                    passed=True,
                    detail="Dry run mode skips real execution.",
                )
                result = StepExecutionResult(
                    step_id=step.id,
                    tool_name=step.tool_name,
                    ok=True,
                    output=f"Dry run: would call {step.tool_name} with {step.parameters}",
                    verification=verification,
                    attempts=0,
                )
                step_results.append(result)
                self.tool_events.append(
                    {
                        "name": step.tool_name,
                        "ok": True,
                        "preview": result.output,
                    }
                )
                self.recorder.emit(
                    "verification_succeeded",
                    f"Dry run recorded for step {step.id}.",
                    step_id=step.id,
                )
                continue

            decision, approval_request = authorize_tool_call(
                step.tool_name,
                step.parameters,
                working_directory=self._working_directory_for_step(step),
            )
            if decision.decision != "allow":
                permission_pending = decision.decision == "ask"
                message = format_permission_response(decision, approval_request=approval_request)
                event_type = "permission_required" if permission_pending else "permission_denied"
                self.recorder.emit(
                    event_type,
                    message,
                    step_id=step.id,
                    tool=step.tool_name,
                    risk_level=decision.risk_level,
                )
                self.tool_events.append(
                    {
                        "name": step.tool_name,
                        "ok": False,
                        "preview": message,
                    }
                )
                step_results.append(
                    StepExecutionResult(
                        step_id=step.id,
                        tool_name=step.tool_name,
                        ok=False,
                        output=message,
                        verification=VerificationResult(
                            passed=permission_pending or decision.decision == "block",
                            detail="Permission handling completed.",
                        ),
                        error=decision.reason,
                    )
                )
                break

            executed = await self._execute_step(step, attempts=1)
            step_results.append(executed)
            if not executed.ok and step.allow_recovery:
                recovered = await self._attempt_recovery(step, executed)
                if recovered is not None:
                    step_results[-1] = recovered
                    executed = recovered

            if not executed.ok:
                break

        success = all(result.ok for result in step_results) and bool(step_results)
        reply = self._build_reply(plan, step_results, permission_pending=permission_pending, success=success)
        self.recorder.emit(
            "workflow_completed",
            "Structured workflow completed." if success else "Structured workflow stopped before completion.",
            success=success,
            permission_pending=permission_pending,
        )
        return PipelineRunResult(
            handled=True,
            success=success,
            reply=reply,
            plan=plan,
            step_results=step_results,
            tool_events=list(self.tool_events),
            pipeline_events=self.recorder.as_list(),
            permission_pending=permission_pending,
        )

    async def _execute_step(self, step: PlanStep, *, attempts: int) -> StepExecutionResult:
        self.recorder.emit(
            "tool_started",
            f"Running step {step.id}.",
            step_id=step.id,
            tool=step.tool_name,
            parameters=step.parameters,
        )
        output = await self.tool_invoker(step.tool_name, step.parameters)
        verification = await verify_step(step, output, tool_invoker=self.tool_invoker)
        ok = verification.passed
        event_type = "tool_succeeded" if ok else "tool_failed"
        self.recorder.emit(
            event_type,
            f"Step {step.id} {'passed' if ok else 'failed'}.",
            step_id=step.id,
            tool=step.tool_name,
            verification=verification.detail,
        )
        verification_event = "verification_succeeded" if verification.passed else "verification_failed"
        self.recorder.emit(
            verification_event,
            verification.detail,
            step_id=step.id,
            tool=step.tool_name,
        )
        self.tool_events.append(
            {
                "name": step.tool_name,
                "ok": ok,
                "preview": output[:220],
            }
        )
        return StepExecutionResult(
            step_id=step.id,
            tool_name=step.tool_name,
            ok=ok,
            output=output,
            verification=verification,
            attempts=attempts,
            error="" if ok else verification.detail,
        )

    async def _attempt_recovery(
        self,
        step: PlanStep,
        failed_result: StepExecutionResult,
    ) -> StepExecutionResult | None:
        recovery = choose_recovery_action(
            step,
            failed_result.output,
            attempts=failed_result.attempts,
        )
        if recovery is None:
            return None

        self.recorder.emit(
            "recovery_started",
            recovery.reason,
            step_id=step.id,
            recovery_tool=recovery.tool_name,
        )
        recovery_step = PlanStep(
            id=f"{step.id}_recovery",
            description=f"Recovery for {step.description}",
            executor=step.executor,
            action_type=f"{step.action_type}.recovery",
            tool_name=recovery.tool_name,
            parameters=recovery.parameters,
            expected_result=step.expected_result,
            risk_level=step.risk_level,
            needs_approval=False,
            verification_method="tool_output_nonempty",
            verification_target=step.verification_target,
            allow_recovery=False,
        )
        recovered = await self._execute_step(recovery_step, attempts=failed_result.attempts + 1)
        recovered.step_id = step.id
        recovered.recovered = recovered.ok
        return recovered

    def _working_directory_for_step(self, step: PlanStep) -> str:
        if step.tool_name == "run_shell_command":
            return str(workspace_dir())
        repo_path = step.parameters.get("repo_path")
        if repo_path:
            return str(repo_path)
        return str(workspace_dir())

    def _build_reply(
        self,
        plan: ExecutionPlan,
        step_results: list[StepExecutionResult],
        *,
        permission_pending: bool,
        success: bool,
    ) -> str:
        if permission_pending and step_results:
            return step_results[-1].output
        if plan.dry_run:
            return (
                f"Dry run ready for a {plan.intent} command with {len(plan.steps)} planned step(s). "
                f"First step: {plan.steps[0].description}."
            )
        if success:
            completed = ", ".join(result.tool_name for result in step_results)
            return f"Completed the structured {plan.intent} workflow and verified: {completed}."
        if step_results:
            failed = step_results[-1]
            return (
                f"The structured {plan.intent} workflow stopped at step '{failed.step_id}'. "
                f"Reason: {failed.error or failed.output}"
            )
        return "The structured workflow did not execute any steps."


async def run_structured_command(
    message: str,
    tool_invoker: ToolInvoker,
    *,
    dry_run: bool = False,
) -> PipelineRunResult:
    """Route, plan, execute, and verify a command using the structured pipeline."""
    recorder = EventRecorder()
    recorder.emit("command_received", "Structured command received.", command=message)
    route = route_user_command(message)
    recorder.emit(
        "intent_detected",
        f"Detected intent '{route.intent}'.",
        intent=route.intent,
        confidence=route.confidence,
        likely_risk=route.likely_risk,
    )

    if route.should_use_legacy_fallback:
        return PipelineRunResult(
            handled=False,
            success=False,
            reply="The command should fall back to the legacy local chat loop.",
            route=route,
            pipeline_events=recorder.as_list(),
            used_legacy_fallback=True,
        )

    plan = build_execution_plan(message, route, dry_run=dry_run)
    if not plan.supported:
        return PipelineRunResult(
            handled=False,
            success=False,
            reply="The structured pipeline could not support this command yet.",
            route=route,
            plan=plan,
            pipeline_events=recorder.as_list(),
            used_legacy_fallback=True,
        )

    executor = StructuredExecutor(tool_invoker, recorder=recorder)
    result = await executor.execute(plan)
    result.route = route
    return result
