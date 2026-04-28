import asyncio
from pathlib import Path

from friday.core.executor import StructuredExecutor, resume_approved_structured_command, run_structured_command
from friday.core.models import ExecutionPlan, IntentRoute, PlanStep
from friday.core.recovery import choose_recovery_action
from friday.core.router import route_user_command
from friday.core.planner import build_execution_plan
from friday.core.risk import RiskLevel
from friday.core.task_context import reset_task_context, update_task_context
from friday.core.verifier import verify_step
from friday.path_utils import resolve_user_path
from friday.safety.approval_gate import resolve_pending_approval


class FakeToolInvoker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def __call__(self, tool_name: str, params: dict[str, object]) -> str:
        self.calls.append((tool_name, dict(params)))

        if tool_name == "write_file":
            path = resolve_user_path(str(params["file_path"]))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(params["content"]), encoding="utf-8")
            return f"Written to: {path}"

        if tool_name == "open_path":
            path = resolve_user_path(str(params["path"]))
            return f"Opened folder view: {path}"

        if tool_name == "run_shell_command":
            return "================ 73 passed in 4.35s ================"

        if tool_name == "open_url":
            return f"Opened {params.get('url')} in your browser."

        if tool_name == "browser_get_state":
            return "Page title: YouTube video\nURL: https://www.youtube.com/watch?v=demo\nInteractive elements: 3 total\n[1] button :: Play"

        if tool_name == "browser_dynamic_loop":
            return "Step 1: selected click_element (Open the first visible video target.)\nResult: Clicked browser element [1] a :: Demo video"

        if tool_name == "open_application":
            return "Error launching application: Not found"

        if tool_name == "search_local_apps":
            return "Found 1 matches:\n  - Notepad"

        if tool_name == "list_open_windows":
            query = str(params.get("query", "")).lower()
            if "notepad" in query:
                return "No open windows found matching 'Notepad'."
            return "Open windows (1):\n  - Code [100] :: project"

        if tool_name == "search_web":
            return "Top results:\n- Example source one\n- Example source two"

        if tool_name == "get_current_time":
            return "Current time: Example\nISO 8601: 2026-01-01T00:00:00"

        return "OK"


def test_route_user_command_detects_desktop_intent():
    route = route_user_command("open notepad and type hello")

    assert route.intent == "desktop"
    assert route.suggested_executor == "desktop"
    assert route.confidence >= 0.58
    assert route.should_use_legacy_fallback is False


def test_route_user_command_detects_research_intent():
    route = route_user_command("search the latest AI news and save a report")

    assert route.intent == "research"
    assert route.suggested_executor == "research"
    assert route.likely_risk >= 1


def test_build_execution_plan_for_code_command():
    route = route_user_command("run tests and report the result")
    plan = build_execution_plan("run tests and report the result", route)

    assert plan.supported is True
    assert plan.intent == "code"
    assert plan.steps[0].tool_name == "run_shell_command"
    assert plan.steps[0].verification_method == "command_output_ok"


def test_build_execution_plan_for_unsupported_fix_error_falls_back():
    route = route_user_command("run my tests and fix the error")
    plan = build_execution_plan("run my tests and fix the error", route)

    assert plan.supported is False
    assert any("legacy local chat loop" in note for note in plan.notes)


def test_verify_step_file_exists(mock_workspace):
    target = mock_workspace / "report.md"
    target.write_text("hello", encoding="utf-8")
    step = PlanStep(
        id="write_file",
        description="Write report",
        executor="files",
        action_type="files.write",
        tool_name="write_file",
        parameters={"file_path": "report.md", "content": "hello"},
        expected_result="Report exists",
        risk_level=1,
        needs_approval=False,
        verification_method="file_exists",
        verification_target=str(target),
    )

    result = verify_step(step, "Written")

    assert result.passed is True


def test_choose_recovery_action_for_browser_navigation():
    step = PlanStep(
        id="open_browser_target",
        description="Open browser target",
        executor="browser",
        action_type="browser.navigate",
        tool_name="browser_navigate",
        parameters={"url": "https://example.com"},
        expected_result="Browser reached the page",
        risk_level=0,
        needs_approval=False,
        verification_method="browser_state",
    )

    recovery = choose_recovery_action(step, "Error navigating browser: timeout", attempts=1)

    assert recovery is not None
    assert recovery.tool_name == "open_url"


def test_structured_executor_requires_permission_for_delete(mock_workspace):
    route = IntentRoute(
        intent="files",
        confidence=0.9,
        required_capabilities=["filesystem"],
        likely_risk=3,
        suggested_executor="files",
    )
    plan = build_execution_plan("delete report.md", route)
    invoker = FakeToolInvoker()

    result = asyncio.run(StructuredExecutor(invoker).execute(plan))

    assert result.handled is True
    assert result.success is False
    assert result.task_status == "needs_approval"
    assert result.final_goal_verified is False
    assert result.permission_pending is True
    assert invoker.calls[0][0] == "list_directory_tree"
    assert "[Approval Required]" in result.reply
    assert result.approval_requests
    assert result.approval_requests[0]["approval_id"].startswith("apr_")


def test_resume_approved_structured_command_runs_pending_step(mock_workspace):
    route = IntentRoute(
        intent="files",
        confidence=0.9,
        required_capabilities=["filesystem"],
        likely_risk=3,
        suggested_executor="files",
    )
    plan = build_execution_plan("delete report.md", route)
    invoker = FakeToolInvoker()

    paused = asyncio.run(StructuredExecutor(invoker).execute(plan))
    approval_id = paused.approval_requests[0]["approval_id"]
    resolve_pending_approval(approval_id, "approved")
    resumed = asyncio.run(resume_approved_structured_command(approval_id, invoker))

    assert resumed.success is True
    assert invoker.calls
    assert invoker.calls[-1][0] == "delete_path"


def test_run_structured_command_dry_run_desktop():
    invoker = FakeToolInvoker()

    result = asyncio.run(
        run_structured_command("open notepad and type hello", invoker, dry_run=True)
    )

    assert result.handled is True
    assert result.success is True
    assert result.plan is not None
    assert result.plan.dry_run is True
    assert invoker.calls == []


def test_build_execution_plan_preserves_unquoted_type_text():
    route = route_user_command("open notepad and type meeting notes")
    plan = build_execution_plan("open notepad and type meeting notes", route)

    assert plan.supported is True
    assert plan.steps[0].tool_name == "open_application"
    assert plan.steps[1].parameters["text"] == "meeting notes"


def test_build_execution_plan_for_explorer_folder_open():
    route = route_user_command("open desktop in file explorer")
    plan = build_execution_plan("open desktop in file explorer", route)

    assert plan.supported is True
    assert plan.intent == "files"
    assert plan.steps[0].tool_name == "open_path"
    assert plan.steps[0].parameters["path"] == "Desktop"


def test_build_execution_plan_for_open_chrome_uses_app_open_step():
    route = route_user_command("open chrome")
    plan = build_execution_plan("open chrome", route)

    assert plan.supported is True
    assert plan.steps[0].tool_name == "open_application"
    assert plan.steps[0].parameters["app_name"] == "Chrome"


def test_run_structured_command_executes_and_verifies_file_write(mock_workspace):
    invoker = FakeToolInvoker()

    result = asyncio.run(
        run_structured_command("create a report file in workspace", invoker)
    )

    assert result.handled is True
    assert result.success is True
    assert (mock_workspace / "reports" / "report.md").exists()
    assert any(event["name"] == "write_file" for event in result.tool_events)


def test_structured_executor_uses_recovery_for_failed_app_open():
    plan = ExecutionPlan(
        goal="open notepad",
        intent="desktop",
        confidence=0.9,
        required_capabilities=["desktop_control"],
        suggested_executor="desktop",
        steps=[
            PlanStep(
                id="open_app",
                description="Open notepad",
                executor="desktop",
                action_type="desktop.open_app",
                tool_name="open_application",
                parameters={"app_name": "Notepad"},
                expected_result="Notepad is open",
                risk_level=0,
                needs_approval=False,
                verification_method="window_present",
                verification_target="Notepad",
            )
        ],
        supported=True,
    )
    invoker = FakeToolInvoker()

    result = asyncio.run(StructuredExecutor(invoker).execute(plan))

    assert result.success is False
    assert result.task_status == "failed"
    assert result.final_goal_verified is False
    assert result.step_results[0].recovered is True
    assert any(event["event_type"] == "recovery_started" for event in result.pipeline_events)


def test_false_completion_reports_partial_when_later_step_fails():
    plan = ExecutionPlan(
        goal="complete four dependent steps",
        intent="browser",
        confidence=0.9,
        required_capabilities=["browser"],
        suggested_executor="browser",
        steps=[
            PlanStep(
                id=f"step_{index}",
                description=f"Step {index}",
                executor="browser",
                action_type="dynamic_browser_task",
                tool_name=f"tool_{index}",
                parameters={"goal": f"step {index}"},
                expected_result="Step succeeds",
                risk_level=RiskLevel.READ_ONLY,
                needs_approval=False,
                verification_method="output_nonempty",
            )
            for index in range(1, 5)
        ],
    )

    class PartialInvoker:
        def __init__(self) -> None:
            self.calls = 0

        async def __call__(self, tool_name, params):
            self.calls += 1
            return "OK" if self.calls == 1 else "Error: second step failed"

    result = asyncio.run(StructuredExecutor(PartialInvoker()).execute(plan))

    assert result.success is False
    assert result.task_status == "partially_completed"
    assert result.completed_steps == ["step_1"]
    assert result.remaining_steps == ["step_2", "step_3", "step_4"]
    assert result.final_goal_verified is False
    assert result.reply != "Structured command completed."


def test_youtube_follow_up_uses_browser_click_context():
    reset_task_context()
    update_task_context(
        last_intent="browser",
        last_site="youtube",
        last_search_query="today famous",
        last_browser_url="https://www.youtube.com/results?search_query=today+famous",
        last_unfinished_goal="open first video",
    )
    invoker = FakeToolInvoker()

    result = asyncio.run(run_structured_command("open first video in it", invoker))

    assert result.handled is True
    assert result.plan is not None
    assert result.plan.intent == "browser"
    assert any(step.action_type == "click_first_result" for step in result.plan.steps)
    assert not any(step.tool_name == "open_application" for step in result.plan.steps)
    assert any(call[0] == "browser_dynamic_loop" for call in invoker.calls)


def test_only_click_the_video_uses_browser_click_context():
    reset_task_context()
    update_task_context(
        last_intent="browser",
        last_site="youtube",
        last_search_query="today famous",
        last_browser_url="https://www.youtube.com/results?search_query=today+famous",
        last_unfinished_goal="open first video",
    )
    invoker = FakeToolInvoker()

    result = asyncio.run(run_structured_command("u only click the video", invoker))

    assert result.plan is not None
    assert any(step.action_type == "click_first_result" for step in result.plan.steps)
    assert not any(call[0] == "open_application" for call in invoker.calls)


def test_react_project_command_builds_multi_step_plan(monkeypatch, mock_workspace):
    documents = mock_workspace / "Documents"
    documents.mkdir()
    monkeypatch.setenv("USERPROFILE", str(mock_workspace))
    reset_task_context()

    route = route_user_command("initialize a react project in Documents in the name demos and make a calculator web page")
    plan = build_execution_plan("initialize a react project in Documents in the name demos and make a calculator web page", route)

    assert plan.intent == "code"
    assert [step.action_type for step in plan.steps] == [
        "check_project_path",
        "shell_command",
        "shell_command",
        "write_file",
        "write_file",
        "shell_command",
        "verify_react_project",
    ]
    assert "npm create vite@latest demos -- --template react" in plan.steps[1].parameters["command"]
    assert plan.steps[2].parameters["command"].endswith("npm install")
    assert "calculator" in plan.steps[3].parameters["content"].lower()
    assert plan.steps[5].parameters["command"].endswith("npm run build")


def test_terminal_initialize_react_needs_project_name_and_location():
    reset_task_context()
    invoker = FakeToolInvoker()

    result = asyncio.run(run_structured_command("open terminal and initialize a react project", invoker))

    assert result.handled is True
    assert result.success is False
    assert result.task_status == "needs_clarification"
    assert "project name and location" in result.reply.lower()
    assert invoker.calls == []


def test_existing_react_project_requires_approval(monkeypatch, mock_workspace):
    documents = mock_workspace / "Documents"
    project = documents / "demos"
    project.mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(mock_workspace))

    route = route_user_command("initialize a react project in Documents in the name demos")
    plan = build_execution_plan("initialize a react project in Documents in the name demos", route)

    assert len(plan.steps) == 1
    assert plan.steps[0].action_type == "confirm_existing_project"
    assert plan.steps[0].needs_approval is True
    assert plan.steps[0].risk_level >= RiskLevel.SENSITIVE_ACTION


def test_dangerous_shell_command_is_blocked():
    route = IntentRoute(
        intent="shell",
        confidence=0.9,
        required_capabilities=["shell"],
        likely_risk=int(RiskLevel.DANGEROUS_RESTRICTED),
        suggested_executor="shell",
    )
    plan = build_execution_plan("rm -rf /", route)
    invoker = FakeToolInvoker()

    result = asyncio.run(StructuredExecutor(invoker).execute(plan))

    assert result.success is False
    assert result.task_status == "blocked"
    assert result.final_goal_verified is False
    assert invoker.calls == []


def test_run_structured_command_falls_back_for_ambiguous_message():
    invoker = FakeToolInvoker()

    result = asyncio.run(run_structured_command("can you handle this for me", invoker))

    assert result.handled is False
    assert result.used_legacy_fallback is True
