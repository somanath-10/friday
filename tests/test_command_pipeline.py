import asyncio
from pathlib import Path

from friday.core.executor import StructuredExecutor, run_structured_command
from friday.core.models import ExecutionPlan, IntentRoute, PlanStep
from friday.core.recovery import choose_recovery_action
from friday.core.router import route_user_command
from friday.core.planner import build_execution_plan
from friday.core.verifier import verify_step
from friday.path_utils import resolve_user_path


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

        if tool_name == "run_shell_command":
            return "================ 73 passed in 4.35s ================"

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
    assert result.permission_pending is True
    assert not invoker.calls
    assert "[Approval Required]" in result.reply


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


def test_run_structured_command_executes_and_verifies_file_write(mock_workspace):
    invoker = FakeToolInvoker()

    result = asyncio.run(
        run_structured_command("create a report file in workspace", invoker)
    )

    assert result.handled is True
    assert result.success is True
    assert (mock_workspace / "report.md").exists()
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

    assert result.success is True
    assert result.step_results[0].recovered is True
    assert any(event["event_type"] == "recovery_started" for event in result.pipeline_events)


def test_run_structured_command_falls_back_for_ambiguous_message():
    invoker = FakeToolInvoker()

    result = asyncio.run(run_structured_command("can you handle this for me", invoker))

    assert result.handled is False
    assert result.used_legacy_fallback is True
