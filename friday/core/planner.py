"""
Simple structured planner for Phase 3.
"""

from __future__ import annotations

import re
from pathlib import Path

from friday.core.models import ExecutionPlan, Intent, IntentResult, IntentRoute, Plan, PlanStep
from friday.core.permissions import check_shell_permission, check_tool_permission
from friday.core.risk import (
    RiskLevel,
    classify_browser_action,
    classify_desktop_action,
    classify_file_operation,
)
from friday.core.router import route_intent


def _step(
    index: int,
    *,
    description: str,
    executor: str,
    action_type: str,
    parameters: dict,
    expected_result: str,
    risk_level: RiskLevel,
    needs_approval: bool,
    verification_method: str,
) -> PlanStep:
    return PlanStep(
        id=f"step_{index}",
        description=description,
        executor=executor,
        action_type=action_type,
        parameters=parameters,
        expected_result=expected_result,
        risk_level=risk_level,
        needs_approval=needs_approval,
        verification_method=verification_method,
    )


def _extract_quoted_text(message: str) -> str:
    match = re.search(r"['\"]([^'\"]+)['\"]", message)
    return match.group(1) if match else ""


def _file_plan(message: str, intent: IntentResult) -> list[PlanStep]:
    lowered = message.lower()
    if "delete" in lowered or "remove" in lowered:
        assessment = classify_file_operation("delete")
        return [
            _step(
                1,
                description="Preview and request approval before deleting the requested path.",
                executor="files",
                action_type="delete_path",
                parameters={"path": _extract_quoted_text(message) or ""},
                expected_result="Deletion is blocked until the user approves it.",
                risk_level=assessment.level,
                needs_approval=True,
                verification_method="path_absent",
            )
        ]

    assessment = classify_file_operation("write_new")
    return [
        _step(
            1,
            description="Create or save the requested file in the workspace.",
            executor="files",
            action_type="write_file",
            parameters={"path": "workspace/generated_by_friday.txt", "content": _extract_quoted_text(message) or message},
            expected_result="File exists at the target path.",
            risk_level=assessment.level,
            needs_approval=False,
            verification_method="file_exists",
        )
    ]


def _shell_or_code_plan(message: str, intent: IntentResult) -> list[PlanStep]:
    lowered = message.lower()
    if "push" in lowered:
        command = "git push"
    elif "commit" in lowered:
        command = "git commit -m 'FRIDAY changes'"
    elif "test" in lowered or "pytest" in lowered:
        command = "pytest tests -q"
    else:
        command = message
    decision = check_shell_permission(command)
    return [
        _step(
            1,
            description="Run the requested local command with permission checks.",
            executor="code" if intent.intent == Intent.CODE else "shell",
            action_type="shell_command",
            parameters={"command": command},
            expected_result="Command exits successfully or returns a captured error.",
            risk_level=decision.risk_level,
            needs_approval=decision.needs_approval,
            verification_method="exit_code",
        )
    ]


def _desktop_plan(message: str) -> list[PlanStep]:
    assessment = classify_desktop_action("open_app")
    app_name = "Notepad" if "notepad" in message.lower() else _extract_quoted_text(message) or "requested application"
    steps = [
        _step(
            1,
            description=f"Open {app_name}.",
            executor="desktop",
            action_type="open_app",
            parameters={"app_name": app_name},
            expected_result="Application window is active or visible.",
            risk_level=assessment.level,
            needs_approval=False,
            verification_method="window_active",
        )
    ]
    quoted = _extract_quoted_text(message)
    if "type" in message.lower():
        type_assessment = classify_desktop_action("type_text")
        steps.append(
            _step(
                2,
                description="Type the requested text into the active application.",
                executor="desktop",
                action_type="type_text",
                parameters={"text": quoted or "hello"},
                expected_result="Text appears in the active application.",
                risk_level=type_assessment.level,
                needs_approval=False,
                verification_method="screen_contains",
            )
        )
    return steps


def _browser_or_research_plan(message: str, intent: IntentResult) -> list[PlanStep]:
    assessment = classify_browser_action("read")
    executor = "research" if intent.intent == Intent.RESEARCH else "browser"
    return [
        _step(
            1,
            description="Observe or search the requested web content before taking actions.",
            executor=executor,
            action_type="browser_observe",
            parameters={"query": message},
            expected_result="Relevant page or source text is available for summarization.",
            risk_level=assessment.level,
            needs_approval=False,
            verification_method="text_contains",
        )
    ]


def create_plan(user_message: str, intent_result: IntentResult | None = None) -> Plan:
    intent = intent_result or route_intent(user_message)
    if intent.intent == Intent.FILES:
        steps = _file_plan(user_message, intent)
    elif intent.intent in {Intent.SHELL, Intent.CODE}:
        steps = _shell_or_code_plan(user_message, intent)
    elif intent.intent == Intent.DESKTOP:
        steps = _desktop_plan(user_message)
    elif intent.intent in {Intent.BROWSER, Intent.RESEARCH}:
        steps = _browser_or_research_plan(user_message, intent)
    elif intent.intent == Intent.MIXED:
        steps = _browser_or_research_plan(user_message, intent) + _file_plan(user_message, intent)
    else:
        assessment = check_tool_permission("get_host_control_status", {}).risk_level
        steps = [
            _step(
                1,
                description="Inspect current system status before choosing a tool.",
                executor="system",
                action_type="status",
                parameters={},
                expected_result="System status is available.",
                risk_level=assessment,
                needs_approval=False,
                verification_method="output_nonempty",
            )
        ]

    return Plan(goal=user_message, intent=intent, steps=steps)


def build_execution_plan(user_message: str, route: IntentRoute) -> ExecutionPlan:
    """Compatibility planning surface for the structured command tests."""
    lowered = user_message.strip().lower()
    if route.should_use_legacy_fallback or "fix the error" in lowered or route.intent == "mixed":
        return ExecutionPlan(
            goal=user_message,
            intent=route.intent,
            confidence=route.confidence,
            required_capabilities=list(route.required_capabilities),
            suggested_executor=route.suggested_executor,
            steps=[],
            supported=False,
            notes=["This request should fall back to the legacy local chat loop for now."],
        )

    intent_result = IntentResult(
        intent=Intent(route.intent),
        confidence=route.confidence,
        required_capabilities=list(route.required_capabilities),
        likely_risk=RiskLevel(route.likely_risk),
        suggested_executor=route.suggested_executor,
    )
    plan = create_plan(user_message, intent_result)
    converted_steps: list[PlanStep] = []
    for step in plan.steps:
        tool_name = step.tool_name
        if not tool_name:
            tool_name = {
                "open_app": "open_application",
                "type_text": "type_text",
                "write_file": "write_file",
                "delete_path": "delete_path",
                "shell_command": "run_shell_command",
                "browser_observe": "search_web",
                "status": "get_host_control_status",
            }.get(step.action_type, step.action_type)

        parameters = dict(step.parameters)
        if step.action_type == "write_file":
            default_name = "report.md" if "report" in lowered else "generated_by_friday.txt"
            path_value = default_name if "report" in lowered else str(parameters.get("path", default_name))
            parameters = {
                "file_path": Path(path_value).name,
                "content": parameters.get("content", ""),
            }
        verification_target = ""
        if step.action_type == "write_file":
            from friday.path_utils import resolve_user_path

            verification_target = str(resolve_user_path(str(parameters["file_path"])))
        elif step.action_type == "open_app":
            verification_target = str(parameters.get("app_name", ""))

        verification_method = step.verification_method
        if step.action_type == "shell_command":
            verification_method = "command_output_ok"

        converted_steps.append(
            PlanStep(
                id=step.id,
                description=step.description,
                executor=step.executor,
                action_type=step.action_type,
                tool_name=tool_name,
                parameters=parameters,
                expected_result=step.expected_result,
                risk_level=step.risk_level,
                needs_approval=step.needs_approval,
                verification_method=verification_method,
                verification_target=verification_target,
            )
        )

    return ExecutionPlan(
        goal=user_message,
        intent=route.intent,
        confidence=route.confidence,
        required_capabilities=list(route.required_capabilities),
        suggested_executor=route.suggested_executor,
        steps=converted_steps,
    )
