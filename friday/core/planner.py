"""
Structured planning for FRIDAY's command pipeline.
"""

from __future__ import annotations

from pathlib import Path
import re

from friday.core.models import ExecutionPlan, IntentRoute, PlanStep
from friday.core.risk import classify_tool_call
from friday.path_utils import workspace_path


def _make_step(
    step_id: str,
    description: str,
    executor: str,
    action_type: str,
    tool_name: str,
    parameters: dict[str, object],
    expected_result: str,
    verification_method: str,
    verification_target: str = "",
    allow_recovery: bool = True,
) -> PlanStep:
    assessment = classify_tool_call(tool_name, dict(parameters))
    return PlanStep(
        id=step_id,
        description=description,
        executor=executor,
        action_type=action_type,
        tool_name=tool_name,
        parameters=dict(parameters),
        expected_result=expected_result,
        risk_level=assessment.risk_level,
        needs_approval=assessment.needs_approval or assessment.blocked,
        verification_method=verification_method,
        verification_target=verification_target,
        allow_recovery=allow_recovery,
    )


def _extract_quoted_text(message: str) -> str:
    match = re.search(r'"([^"]+)"', message)
    if match:
        return match.group(1).strip()
    match = re.search(r"'([^']+)'", message)
    if match:
        return match.group(1).strip()
    return ""


def _clean_fragment(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip(" .,!?\n\t")).strip()


def _extract_special_root(message: str) -> str:
    lowered = message.lower()
    if "downloads" in lowered:
        return "Downloads"
    if "documents" in lowered:
        return "Documents"
    if "desktop" in lowered:
        return "Desktop"
    if "workspace" in lowered:
        return "."
    return "."


def _desktop_plan(message: str, route: IntentRoute) -> ExecutionPlan:
    normalized = message.strip()
    match = re.search(r"open\s+(.+?)\s+and\s+type\s+(.+)$", normalized, flags=re.IGNORECASE)
    steps: list[PlanStep] = []
    notes: list[str] = []

    if match:
        app_name = _clean_fragment(match.group(1))
        typed_text = _clean_fragment(match.group(2))
        steps.append(
            _make_step(
                "open_app",
                f"Open {app_name}",
                route.suggested_executor,
                "desktop.open_app",
                "open_application",
                {"app_name": app_name},
                f"Application {app_name} is open",
                "window_present",
                verification_target=app_name,
            )
        )
        steps.append(
            _make_step(
                "type_text",
                f"Type text into {app_name}",
                route.suggested_executor,
                "desktop.type_text",
                "type_text",
                {"text": typed_text},
                "Text was typed into the focused window",
                "tool_output_contains",
                verification_target="Typed",
            )
        )
    else:
        open_match = re.search(r"open\s+(.+)$", normalized, flags=re.IGNORECASE)
        if open_match:
            app_name = _clean_fragment(open_match.group(1))
            steps.append(
                _make_step(
                    "open_app",
                    f"Open {app_name}",
                    route.suggested_executor,
                    "desktop.open_app",
                    "open_application",
                    {"app_name": app_name},
                    f"Application {app_name} is open",
                    "window_present",
                    verification_target=app_name,
                )
            )
        else:
            notes.append("The desktop command did not match a supported structured pattern.")

    return ExecutionPlan(
        goal=message,
        intent=route.intent,
        confidence=route.confidence,
        required_capabilities=route.required_capabilities,
        suggested_executor=route.suggested_executor,
        steps=steps,
        summary="Desktop command plan",
        notes=notes,
        supported=bool(steps),
    )


def _browser_url_for_message(message: str) -> str:
    explicit_url = re.search(r"(https?://\S+)", message, flags=re.IGNORECASE)
    if explicit_url:
        return explicit_url.group(1).rstrip(".,)")
    if "google" in message.lower():
        return "https://www.google.com"
    if "youtube" in message.lower():
        return "https://www.youtube.com"
    return ""


def _browser_plan(message: str, route: IntentRoute) -> ExecutionPlan:
    steps: list[PlanStep] = []
    notes: list[str] = []
    url = _browser_url_for_message(message)

    if url:
        tool_name = "open_url" if "open " in message.lower() else "browser_navigate"
        steps.append(
            _make_step(
                "open_browser_target",
                f"Open {url}",
                route.suggested_executor,
                "browser.navigate",
                tool_name,
                {"url": url},
                f"Browser reached {url}",
                "tool_output_contains",
                verification_target=url.split("//", 1)[-1].split("/", 1)[0],
            )
        )
        if tool_name == "browser_navigate":
            steps.append(
                _make_step(
                    "inspect_browser_state",
                    "Inspect the browser state",
                    route.suggested_executor,
                    "browser.inspect",
                    "browser_get_state",
                    {},
                    "Browser state is available",
                    "tool_output_contains",
                    verification_target="Interactive elements",
                    allow_recovery=False,
                )
            )
    else:
        notes.append("The browser command needs an explicit URL or a supported well-known site.")

    return ExecutionPlan(
        goal=message,
        intent=route.intent,
        confidence=route.confidence,
        required_capabilities=route.required_capabilities,
        suggested_executor=route.suggested_executor,
        steps=steps,
        summary="Browser command plan",
        notes=notes,
        supported=bool(steps),
    )


def _path_name_from_message(message: str, default_name: str) -> str:
    quoted = _extract_quoted_text(message)
    if quoted:
        return quoted
    filename_match = re.search(r"\b([\w\-]+\.(?:txt|md|json|csv|py))\b", message, flags=re.IGNORECASE)
    if filename_match:
        return filename_match.group(1)
    return default_name


def _files_plan(message: str, route: IntentRoute) -> ExecutionPlan:
    lowered = message.lower()
    steps: list[PlanStep] = []
    notes: list[str] = []

    if any(word in lowered for word in ("list", "show")):
        path_value = _extract_special_root(message)
        steps.append(
            _make_step(
                "list_files",
                f"List files in {path_value}",
                route.suggested_executor,
                "files.list",
                "list_directory_tree",
                {"path": path_value, "max_depth": 2},
                "Directory listing is available",
                "tool_output_contains",
                verification_target="/",
            )
        )
    elif any(word in lowered for word in ("read", "show file", "open file")):
        file_path = _path_name_from_message(message, "README.md")
        steps.append(
            _make_step(
                "read_file",
                f"Read {file_path}",
                route.suggested_executor,
                "files.read",
                "get_file_contents",
                {"file_path": file_path},
                f"File contents for {file_path} are available",
                "tool_output_nonempty",
                verification_target=file_path,
            )
        )
    elif any(word in lowered for word in ("create", "write", "save")):
        filename = _path_name_from_message(message, "report.md" if "report" in lowered else "note.txt")
        content = "# Report\n\nCreated by FRIDAY.\n" if filename.endswith(".md") else "Created by FRIDAY.\n"
        steps.append(
            _make_step(
                "write_file",
                f"Write {filename}",
                route.suggested_executor,
                "files.write",
                "write_file",
                {"file_path": filename, "content": content},
                f"Created {filename}",
                "file_exists",
                verification_target=str(workspace_path(filename)),
            )
        )
    elif "delete" in lowered:
        target = _path_name_from_message(message, ".")
        steps.append(
            _make_step(
                "delete_path",
                f"Delete {target}",
                route.suggested_executor,
                "files.delete",
                "delete_path",
                {"path": target},
                f"Delete request issued for {target}",
                "permission_or_absence",
                verification_target=str(target),
            )
        )
    else:
        notes.append("The file command did not match a supported structured pattern.")

    return ExecutionPlan(
        goal=message,
        intent=route.intent,
        confidence=route.confidence,
        required_capabilities=route.required_capabilities,
        suggested_executor=route.suggested_executor,
        steps=steps,
        summary="Filesystem command plan",
        notes=notes,
        supported=bool(steps),
    )


def _shell_command_from_message(message: str) -> str:
    quoted = _extract_quoted_text(message)
    if quoted:
        return quoted
    if "pytest" in message.lower() or "run tests" in message.lower():
        return "pytest tests -q"
    return ""


def _shell_or_code_plan(message: str, route: IntentRoute) -> ExecutionPlan:
    steps: list[PlanStep] = []
    notes: list[str] = []
    command = _shell_command_from_message(message)

    if command:
        steps.append(
            _make_step(
                "run_command",
                f"Run `{command}`",
                route.suggested_executor,
                "shell.command",
                "run_shell_command",
                {"command": command},
                "Command exits successfully",
                "command_output_ok",
                verification_target=command,
            )
        )
    elif "git status" in message.lower():
        steps.append(
            _make_step(
                "git_status",
                "Inspect repository status",
                route.suggested_executor,
                "code.git_status",
                "git_status",
                {},
                "Git status is available",
                "tool_output_contains",
                verification_target="Git Status",
            )
        )
    else:
        notes.append("The shell/code command needs an explicit supported command pattern.")

    supported = bool(steps) and "fix error" not in message.lower()
    if "fix error" in message.lower():
        notes.append("Automatic code fixing still falls back to the legacy tool loop.")

    return ExecutionPlan(
        goal=message,
        intent=route.intent,
        confidence=route.confidence,
        required_capabilities=route.required_capabilities,
        suggested_executor=route.suggested_executor,
        steps=steps,
        summary="Shell or code command plan",
        notes=notes,
        supported=supported,
    )


def _research_plan(message: str, route: IntentRoute) -> ExecutionPlan:
    lowered = message.lower()
    steps: list[PlanStep] = []
    notes: list[str] = []
    query = _clean_fragment(
        re.sub(r"^(search|research|find|look up)\s+", "", message, flags=re.IGNORECASE)
    ) or message.strip()

    steps.append(
        _make_step(
            "search_web",
            f"Search the web for {query}",
            route.suggested_executor,
            "research.search",
            "search_web",
            {"query": query},
            "Search results are available",
            "tool_output_nonempty",
            verification_target="search results",
        )
    )

    if any(word in lowered for word in ("save", "report", "write")):
        steps.append(
            _make_step(
                "write_report",
                "Save a local research report draft",
                route.suggested_executor,
                "research.write_report",
                "write_file",
                {"file_path": "research_report.md", "content": f"# Research Report\n\nTopic: {query}\n"},
                "Research report file exists",
                "file_exists",
                verification_target=str(workspace_path("research_report.md")),
            )
        )

    return ExecutionPlan(
        goal=message,
        intent=route.intent,
        confidence=route.confidence,
        required_capabilities=route.required_capabilities,
        suggested_executor=route.suggested_executor,
        steps=steps,
        summary="Research command plan",
        notes=notes,
        supported=bool(steps),
    )


def _workflow_plan(message: str, route: IntentRoute) -> ExecutionPlan:
    lowered = message.lower()
    if "status" in lowered:
        steps = [
            _make_step(
                "workflow_status",
                "Read the latest workflow status",
                route.suggested_executor,
                "workflow.status",
                "get_workflow_status",
                {},
                "Workflow status is available",
                "tool_output_contains",
                verification_target="Workflow Plan",
                allow_recovery=False,
            )
        ]
    else:
        steps = [
            _make_step(
                "workflow_plan",
                "Create a workflow plan",
                route.suggested_executor,
                "workflow.plan",
                "create_workflow_plan",
                {"goal": message, "mode": "safe"},
                "Workflow plan was created",
                "tool_output_contains",
                verification_target="Workflow Plan",
            )
        ]

    return ExecutionPlan(
        goal=message,
        intent=route.intent,
        confidence=route.confidence,
        required_capabilities=route.required_capabilities,
        suggested_executor=route.suggested_executor,
        steps=steps,
        summary="Workflow command plan",
        supported=True,
    )


def _memory_plan(message: str, route: IntentRoute) -> ExecutionPlan:
    lowered = message.lower()
    if any(word in lowered for word in ("trace", "action", "workflow")):
        tool_name = "get_recent_action_traces"
        params: dict[str, object] = {"limit": 5}
    else:
        tool_name = "get_recent_history"
        params = {"limit": 5}

    return ExecutionPlan(
        goal=message,
        intent=route.intent,
        confidence=route.confidence,
        required_capabilities=route.required_capabilities,
        suggested_executor=route.suggested_executor,
        steps=[
            _make_step(
                "memory_read",
                "Read recent memory state",
                route.suggested_executor,
                "memory.read",
                tool_name,
                params,
                "Memory results are available",
                "tool_output_nonempty",
                verification_target="memory",
                allow_recovery=False,
            )
        ],
        summary="Memory command plan",
        supported=True,
    )


def _system_plan(message: str, route: IntentRoute) -> ExecutionPlan:
    lowered = message.lower()
    if any(word in lowered for word in ("time", "date")):
        step = _make_step(
            "system_time",
            "Read the current time",
            route.suggested_executor,
            "system.time",
            "get_current_time",
            {},
            "Current time is available",
            "tool_output_contains",
            verification_target="ISO 8601",
            allow_recovery=False,
        )
    elif "running apps" in lowered:
        step = _make_step(
            "running_apps",
            "List running applications",
            route.suggested_executor,
            "system.running_apps",
            "get_running_apps",
            {},
            "Running app list is available",
            "tool_output_nonempty",
            verification_target="Running apps",
            allow_recovery=False,
        )
    else:
        step = _make_step(
            "system_telemetry",
            "Read system telemetry",
            route.suggested_executor,
            "system.telemetry",
            "get_system_telemetry",
            {},
            "System telemetry is available",
            "tool_output_nonempty",
            verification_target="os",
            allow_recovery=False,
        )

    return ExecutionPlan(
        goal=message,
        intent=route.intent,
        confidence=route.confidence,
        required_capabilities=route.required_capabilities,
        suggested_executor=route.suggested_executor,
        steps=[step],
        summary="System command plan",
        supported=True,
    )


def build_execution_plan(message: str, route: IntentRoute, *, dry_run: bool = False) -> ExecutionPlan:
    """Build a structured execution plan for a routed intent."""
    if route.intent == "desktop":
        plan = _desktop_plan(message, route)
    elif route.intent == "browser":
        plan = _browser_plan(message, route)
    elif route.intent == "files":
        plan = _files_plan(message, route)
    elif route.intent in {"shell", "code"}:
        plan = _shell_or_code_plan(message, route)
    elif route.intent == "research":
        plan = _research_plan(message, route)
    elif route.intent == "workflow":
        plan = _workflow_plan(message, route)
    elif route.intent == "memory":
        plan = _memory_plan(message, route)
    elif route.intent == "system":
        plan = _system_plan(message, route)
    else:
        plan = ExecutionPlan(
            goal=message,
            intent=route.intent,
            confidence=route.confidence,
            required_capabilities=route.required_capabilities,
            suggested_executor=route.suggested_executor,
            steps=[],
            dry_run=dry_run,
            summary="No structured plan is available for this command.",
            notes=["This command should fall back to the legacy local chat loop."],
            supported=False,
        )

    plan.dry_run = dry_run
    if not plan.supported or not plan.steps:
        plan.supported = False
        if "This command should fall back to the legacy local chat loop." not in plan.notes:
            plan.notes.append("This command should fall back to the legacy local chat loop.")
    return plan
