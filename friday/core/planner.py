"""
Deterministic structured planner for FRIDAY.

The planner intentionally handles safe, repeatable workflows itself and leaves
open-ended reasoning or repair tasks to the legacy LLM tool loop. That keeps
local control permission-aware without pretending every natural-language
request can be solved by a fixed template.
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


SPECIAL_PATH_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("downloads", "download folder", "download directory"), "Downloads"),
    (("documents", "document folder", "document directory"), "Documents"),
    (("desktop",), "Desktop"),
    (("pictures", "picture folder", "photos"), "Pictures"),
    (("videos", "video folder"), "Videos"),
    (("music", "songs"), "Music"),
    (("home", "user folder"), "home"),
    (("reports folder", "report folder", "reports directory"), "workspace/reports"),
    (("workspace", "work space"), "workspace"),
)

APP_ALIASES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("notepad",), "Notepad"),
    (("chrome", "google chrome"), "Chrome"),
    (("edge", "microsoft edge"), "Edge"),
    (("vscode", "vs code", "visual studio code"), "Visual Studio Code"),
    (("calculator", "calc"), "Calculator"),
    (("file explorer", "explorer"), "File Explorer"),
    (("terminal",), "Windows Terminal"),
    (("command prompt", "cmd"), "Command Prompt"),
    (("powershell",), "Windows PowerShell"),
)


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
    fallback_strategy: str = "",
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
        fallback_strategy=fallback_strategy,
    )


def _extract_quoted_text(message: str) -> str:
    match = re.search(r"['\"]([^'\"]+)['\"]", message)
    return match.group(1) if match else ""


def _special_path_from_text(message: str) -> str:
    lowered = message.lower()
    for markers, path in SPECIAL_PATH_HINTS:
        if any(marker in lowered for marker in markers):
            return path
    return ""


def _extract_path_hint(message: str) -> str:
    quoted = _extract_quoted_text(message)
    if quoted and any(sep in quoted for sep in ("/", "\\", ".")):
        return quoted

    special = _special_path_from_text(message)
    if special:
        return special

    match = re.search(r"\b(?:delete|remove|list|read|open|move|rename|copy)\s+([^\s]+)", message, flags=re.IGNORECASE)
    if not match:
        return ""
    candidate = match.group(1).strip(".,;:()[]{}")
    blocked_words = {"all", "files", "folders", "everything", "the", "my"}
    return "" if candidate.lower() in blocked_words else candidate


def _extract_move_paths(message: str) -> tuple[str, str]:
    lowered = message.lower()
    source = _special_path_from_text(message) or _extract_path_hint(message)
    destination = ""
    to_match = re.search(r"\bto\s+([^,.]+)", lowered)
    if to_match:
        destination = to_match.group(1).strip().strip("'").strip('"')
        for markers, path in SPECIAL_PATH_HINTS:
            if any(marker in destination for marker in markers):
                destination = path
                break
    return source, destination


def _is_folder_open_request(message: str) -> bool:
    lowered = message.lower()
    if not any(marker in lowered for marker in ("open", "show", "reveal")):
        return False
    if "file explorer" in lowered or " in explorer" in lowered or " folder" in lowered:
        return True
    return any(marker in lowered for marker in ("desktop", "downloads", "documents", "pictures", "videos", "music", "workspace")) and "type " not in lowered


def _extract_app_name(message: str) -> str:
    lowered = message.lower()
    for markers, app_name in APP_ALIASES:
        if any(marker in lowered for marker in markers):
            return app_name
    quoted = _extract_quoted_text(message)
    if quoted:
        return quoted
    match = re.search(r"\bopen\s+([a-zA-Z0-9_. -]+?)(?:\s+and\s+|\s+then\s+|$)", message, flags=re.IGNORECASE)
    if match:
        candidate = match.group(1).strip(" .,;:")
        if candidate:
            return candidate
    return "requested application"


def _extract_type_text(message: str) -> str:
    quoted = _extract_quoted_text(message)
    if quoted:
        return quoted
    match = re.search(r"\btype\s+(.+)$", message, flags=re.IGNORECASE)
    if not match:
        return "hello"
    text = match.group(1).strip()
    text = re.sub(
        r"\s+(?:in|into|inside)\s+(?:notepad|chrome|edge|the app|application).*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.strip(" .,;:") or "hello"


def _extract_browser_name(message: str) -> str:
    lowered = message.lower()
    if "edge" in lowered:
        return "Edge"
    if "chrome" in lowered:
        return "Chrome"
    return "Browser"


def _file_plan(message: str, intent: IntentResult) -> list[PlanStep]:
    lowered = message.lower()
    if _is_folder_open_request(message) and any(word in lowered for word in ("open", "show", "reveal")):
        assessment = classify_file_operation("read")
        return [
            _step(
                1,
                description="Open the requested folder in Windows File Explorer after safe path resolution.",
                executor="files",
                action_type="open_path",
                parameters={"path": _extract_path_hint(message) or _special_path_from_text(message) or "workspace"},
                expected_result="The folder opens in File Explorer.",
                risk_level=assessment.level,
                needs_approval=False,
                verification_method="file_exists",
            )
        ]

    if any(word in lowered for word in ("list", "show files", "tree")) and "delete" not in lowered:
        assessment = classify_file_operation("list")
        return [
            _step(
                1,
                description="List the requested directory through the filesystem runtime.",
                executor="files",
                action_type="list_tree",
                parameters={"path": _extract_path_hint(message) or "Downloads", "limit": 200},
                expected_result="Directory entries are returned without modifying files.",
                risk_level=assessment.level,
                needs_approval=False,
                verification_method="output_nonempty",
            )
        ]

    if "delete" in lowered or "remove" in lowered:
        target = _extract_path_hint(message)
        preview = _step(
            1,
            description="Preview the destructive file request before any deletion is possible.",
            executor="files",
            action_type="list_tree",
            parameters={"path": target or "Downloads", "limit": 500},
            expected_result="User can see the affected files before approval.",
            risk_level=RiskLevel.READ_ONLY,
            needs_approval=False,
            verification_method="output_nonempty",
        )
        assessment = classify_file_operation("delete")
        delete = _step(
            2,
            description="Request approval before deleting the selected path or files.",
            executor="files",
            action_type="delete_path",
            parameters={"path": target, "requires_preview": True},
            expected_result="Deletion is blocked until the user approves it.",
            risk_level=assessment.level,
            needs_approval=True,
            verification_method="path_absent",
        )
        return [preview, delete]

    if any(word in lowered for word in ("move", "rename", "copy")):
        source, destination = _extract_move_paths(message)
        operation = "copy" if "copy" in lowered else "move"
        assessment = classify_file_operation(operation)
        return [
            _step(
                1,
                description=f"{operation.title()} the requested file or folder after path safety checks.",
                executor="files",
                action_type="copy_path" if operation == "copy" else "move_path",
                parameters={"source_path": source, "destination_path": destination, "overwrite": False},
                expected_result="Path exists at the destination and original state is preserved or moved safely.",
                risk_level=assessment.level,
                needs_approval=assessment.level >= RiskLevel.SENSITIVE_ACTION,
                verification_method="file_exists",
            )
        ]

    assessment = classify_file_operation("write_new")
    path_text = re.sub(r"['\"][^'\"]+['\"]", "", lowered)
    wants_report_path = any(
        phrase in path_text
        for phrase in ("report file", "reports folder", "report folder", "make report", "save report")
    )
    default_path = "workspace/reports/report.md" if wants_report_path else "workspace/generated_by_friday.txt"
    return [
        _step(
            1,
            description="Create or save the requested file in the workspace.",
            executor="files",
            action_type="write_file",
            parameters={"path": default_path, "content": _extract_quoted_text(message) or message},
            expected_result="File exists at the target path.",
            risk_level=assessment.level,
            needs_approval=False,
            verification_method="file_exists",
        )
    ]


def _shell_or_code_plan(message: str, intent: IntentResult) -> list[PlanStep]:
    lowered = message.lower()
    if lowered.startswith("open ") and any(term in lowered for term in ("powershell", "cmd", "command prompt", "terminal")):
        return _desktop_plan(message)
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
    lowered = message.lower()
    if "screenshot" in lowered or "screen" in lowered and "error" in lowered:
        assessment = classify_desktop_action("inspect_screen")
        return [
            _step(
                1,
                description="Capture and inspect the screen before giving a local error-analysis response.",
                executor="desktop",
                action_type="inspect_screen",
                parameters={"question": message},
                expected_result="A screenshot artifact is saved and any available analysis is returned.",
                risk_level=assessment.level,
                needs_approval=False,
                verification_method="output_nonempty",
                fallback_strategy="Use screenshot/OCR fallback if direct screen inspection is unavailable.",
            )
        ]

    if lowered.startswith("focus "):
        assessment = classify_desktop_action("focus_window")
        app_name = _extract_app_name(message.replace("focus", "open", 1))
        return [
            _step(
                1,
                description=f"Focus {app_name} by app/window name.",
                executor="desktop",
                action_type="focus_window",
                parameters={"app_name": app_name},
                expected_result="Requested window is active.",
                risk_level=assessment.level,
                needs_approval=False,
                verification_method="window_active",
                fallback_strategy="List windows and ask the user if no matching window is found.",
            )
        ]

    if lowered.startswith("close "):
        assessment = classify_desktop_action("close_app")
        app_name = _extract_app_name(message.replace("close", "open", 1))
        return [
            _step(
                1,
                description=f"Request permission before closing {app_name}.",
                executor="desktop",
                action_type="close_app",
                parameters={"app_name": app_name},
                expected_result="Requested window is closed after approval if needed.",
                risk_level=assessment.level,
                needs_approval=assessment.level >= RiskLevel.SENSITIVE_ACTION,
                verification_method="window_absent",
                fallback_strategy="Ask the user to take over if unsaved changes or a modal blocks close.",
            )
        ]

    assessment = classify_desktop_action("open_app")
    app_name = _extract_app_name(message)
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
            fallback_strategy="Resolve Windows app alias, then use PowerShell launch fallback.",
        )
    ]
    if "type" in message.lower() or "press" in message.lower():
        type_assessment = classify_desktop_action("type_text")
        steps.append(
            _step(
                2,
                description="Observe the active window and perform the requested desktop action using UI Automation targets.",
                executor="desktop",
                action_type="dynamic_desktop_task",
                parameters={"goal": message, "text": _extract_type_text(message)},
                expected_result="Requested desktop interaction is completed through observed controls.",
                risk_level=type_assessment.level,
                needs_approval=False,
                verification_method="dynamic_goal_progress",
                fallback_strategy="Use hotkeys, screenshot/OCR, or user takeover if UI Automation cannot identify the control.",
            )
        )
    return steps


def _browser_or_research_plan(message: str, intent: IntentResult) -> list[PlanStep]:
    lowered = message.lower()
    executor = "research" if intent.intent == Intent.RESEARCH else "browser"
    steps: list[PlanStep] = []
    mentions_browser_app = any(name in lowered for name in ("chrome", "edge"))
    browser_task_markers = ("search", "go to", "visit", "website", "url", "login", "bank", "http://", "https://", "latest", "news", "page")
    if mentions_browser_app:
        launch_assessment = classify_desktop_action("open_app")
        steps.append(
            _step(
                1,
                description="Open the requested browser application before the web task.",
                executor="desktop",
                action_type="open_app",
                parameters={"app_name": _extract_browser_name(message)},
                expected_result="The requested browser window is open and available.",
                risk_level=launch_assessment.level,
                needs_approval=False,
                verification_method="window_active",
            )
        )
    if mentions_browser_app and not any(marker in lowered for marker in browser_task_markers):
        return steps
    sensitive_goal = any(word in lowered for word in ("login", "password", "submit", "send", "purchase", "payment", "checkout", "bank"))
    assessment = classify_browser_action("submit" if sensitive_goal else "read")
    steps.append(
        _step(
            len(steps) + 1,
            description="Run a generic browser observe-act-verify loop using DOM/accessibility targets.",
            executor=executor if executor == "research" else "browser",
            action_type="dynamic_browser_task",
            parameters={"goal": message, "browser": _extract_browser_name(message)},
            expected_result="The browser task progresses through observed page elements, not hardcoded site selectors.",
            risk_level=assessment.level,
            needs_approval=sensitive_goal,
            verification_method="dynamic_goal_progress",
            fallback_strategy="Use accessibility snapshot, then screenshot fallback; ask user on login, captcha, payment, or permission prompts.",
        )
    )
    if any(word in lowered for word in ("save", "report", "summary")):
        file_assessment = classify_file_operation("write_new")
        steps.append(
            _step(
                len(steps) + 1,
                description="Save a local report placeholder after research output is produced.",
                executor="files",
                action_type="write_file",
                parameters={
                    "path": "workspace/reports/research_report.md",
                    "content": (
                        "# Research Report\n\n"
                        f"Topic: {message}\n\n"
                        "Run the full local chat workflow to populate this report with cited sources."
                    ),
                },
                expected_result="Report file exists in the workspace reports folder.",
                risk_level=file_assessment.level,
                needs_approval=False,
                verification_method="file_exists",
            )
        )
    return steps


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


def _should_use_legacy_for_complex_task(lowered: str, route: IntentRoute) -> bool:
    if route.should_use_legacy_fallback or route.intent == "mixed":
        return True
    if route.intent == "code" and any(word in lowered for word in ("fix", "patch", "repair")):
        return True
    dynamic_report = any(word in lowered for word in ("latest", "news", "research", "search")) and any(
        word in lowered for word in ("save", "report", "summary", "summarize")
    )
    return dynamic_report


def build_execution_plan(user_message: str, route: IntentRoute) -> ExecutionPlan:
    """Compatibility planning surface for the structured command tests and local chat bridge."""
    lowered = user_message.strip().lower()
    if _should_use_legacy_for_complex_task(lowered, route):
        return ExecutionPlan(
            goal=user_message,
            intent=route.intent,
            confidence=route.confidence,
            required_capabilities=list(route.required_capabilities),
            suggested_executor=route.suggested_executor,
            steps=[],
            supported=False,
            notes=[
                "This request needs dynamic reasoning, credentials, source synthesis, or code repair; "
                "falling back to the legacy local chat loop for now."
            ],
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
                "open_path": "open_path",
                "list_tree": "list_directory_tree",
                "copy_path": "copy_path",
                "move_path": "move_path",
                "shell_command": "run_shell_command",
                "dynamic_desktop_task": "desktop_dynamic_loop",
                "dynamic_browser_task": "browser_dynamic_loop",
                "browser_observe": "search_web",
                "browser_submit_form": "browser_submit_form",
                "status": "get_host_control_status",
            }.get(step.action_type, step.action_type)

        parameters = dict(step.parameters)
        if step.action_type == "write_file":
            path_value = str(parameters.get("path") or ("report.md" if "report" in lowered else "generated_by_friday.txt"))
            parameters = {
                "file_path": Path(path_value).name if not path_value.startswith("workspace/") else path_value,
                "content": parameters.get("content", ""),
            }
        verification_target = ""
        if step.action_type == "write_file":
            from friday.path_utils import resolve_user_path

            verification_target = str(resolve_user_path(str(parameters["file_path"])))
        elif step.action_type == "open_app":
            verification_target = str(parameters.get("app_name", ""))
        elif step.action_type in {"delete_path", "list_tree", "open_path"}:
            verification_target = str(parameters.get("path", ""))
        elif step.action_type in {"dynamic_browser_task", "dynamic_desktop_task"}:
            verification_target = str(parameters.get("goal", user_message))

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
                fallback_strategy=step.fallback_strategy,
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
