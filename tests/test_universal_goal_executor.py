import asyncio
import json

from friday.browser.operator import BrowserOperator, build_element_map_from_html
from friday.core.events import EventType
from friday.core.executor import execute_goal
from friday.core.planner import build_execution_plan
from friday.core.router import route_user_command
from friday.core.task_context import contextualize_user_message, reset_task_context, update_task_context
from friday.core.ui import find_target
from friday.desktop import recording
from friday.desktop.operator import DesktopOperator, build_control_map
from friday.files.safe_paths import resolve_safe_path
from friday.safety.audit_log import read_audit_records
from friday.safety.emergency_stop import clear_emergency_stop, trigger_emergency_stop
from friday.shell.runtime import ShellRuntime
from friday.shell.terminal import TerminalResult


class UniversalInvoker:
    def __init__(self, outputs=None):
        self.outputs = outputs or {}
        self.calls = []

    async def __call__(self, tool_name, params):
        self.calls.append((tool_name, dict(params)))
        output = self.outputs.get(tool_name)
        if callable(output):
            return output(tool_name, params, len(self.calls))
        if output is not None:
            return output
        if tool_name == "browser_get_state":
            return "Page title: Result\nURL: https://example.test/result\nInteractive elements: 1 total"
        if tool_name == "browser_dynamic_loop":
            return "Step 1: selected click_element\nResult: Clicked browser element [1] a :: First result"
        if tool_name == "run_shell_command":
            return "build success"
        if tool_name == "write_file":
            return "Written 1 KB to: /tmp/file"
        if tool_name == "open_path":
            return "Opened folder view: /tmp/Desktop"
        if tool_name == "open_application":
            return "Application opened and verified."
        if tool_name == "desktop_dynamic_loop":
            return "Typed into editable control and verified."
        return "OK"


def test_execute_goal_tool_success_is_not_task_success():
    def output(tool_name, _params, call_count):
        return "OK" if call_count == 1 else "Error: could not continue"

    route = route_user_command("open current page first result")
    plan = build_execution_plan("On the current browser page, click the first result.", route)
    assert len(plan.steps) >= 2

    result = asyncio.run(execute_goal("On the current browser page, click the first result.", UniversalInvoker({"browser_get_state": output})))

    assert result.success is False
    assert result.final_goal_verified is False
    assert result.task_status in {"partially_completed", "failed", "blocked"}
    assert result.reply != "Structured command completed."


def test_execute_goal_returns_needs_clarification_for_missing_project_details():
    result = asyncio.run(execute_goal("open terminal and initialize a react project", UniversalInvoker()))

    assert result.task_status == "needs_clarification"
    assert result.success is False
    assert "project name and location" in result.reply.lower()
    assert "Status:" in result.reply
    assert "What I did:" in result.reply
    assert "What I did not complete:" in result.reply
    assert "Verification:" in result.reply
    assert "Needs your input:" in result.reply


def test_follow_up_resolution_across_browser_code_and_files():
    reset_task_context()
    update_task_context(last_intent="browser", last_site="google", last_search_query="python tutorials", last_browser_url="https://google.test/search?q=python+tutorials")
    assert "click the first result" in contextualize_user_message("click first one").lower()

    reset_task_context()
    update_task_context(last_intent="code", last_project_path="Documents/demos")
    assert contextualize_user_message("now build it") == "run build for the project at Documents/demos"
    assert contextualize_user_message("run it") == "run the project at Documents/demos"

    reset_task_context()
    update_task_context(last_intent="files", last_folder_path="Desktop")
    assert contextualize_user_message("open it") == "open Desktop in file explorer"


def test_ambiguous_open_it_asks_for_clarification():
    reset_task_context()
    update_task_context(
        last_intent="browser",
        last_folder_path="Downloads",
        last_browser_url="https://example.test/current",
    )

    resolved = contextualize_user_message("open it")
    result = asyncio.run(execute_goal("open it", UniversalInvoker()))

    assert resolved.startswith("needs_clarification:")
    assert result.task_status == "needs_clarification"
    assert "do you mean" in result.reply.lower()


def test_browser_generic_search_click_named_fill_and_submit_approval():
    observation = build_element_map_from_html(
        """
        <input type="search" placeholder="Search">
        <a href="/one">First result</a>
        <a href="/docs">OpenAI Docs</a>
        <input placeholder="Email">
        <button>Submit</button>
        """,
        url="https://example.test",
    )
    operator = BrowserOperator()

    search = operator.decide_next_action("search python tutorials", observation)
    named = operator.decide_next_action("click named result OpenAI Docs", observation)
    fill = operator.decide_next_action("type 'hello@example.com' into email", observation)
    submit = operator.decide_next_action("submit form", observation)
    decision = operator.permission_for_action(submit, observation)

    assert search.type == "type_into_element"
    assert named.type == "click_element"
    assert fill.type == "type_into_element"
    assert submit.type == "submit_form"
    assert submit.metadata["confidence"] >= 0.75
    assert decision["decision"] in {"ask", "block"}


def test_low_confidence_browser_target_does_not_click():
    observation = build_element_map_from_html(
        "<button>Maybe later</button><a href='/help'>Help</a>",
        url="https://example.test",
    )
    operator = BrowserOperator()

    action = operator.decide_next_action("click account settings", observation)

    assert action.type in {"needs_clarification", "screenshot_fallback"}
    assert action.type != "click_element"


def test_first_result_click_carries_medium_confidence():
    observation = build_element_map_from_html(
        "<a href='/ad'>Sponsored</a><a href='/result'>First organic result</a>",
        url="https://search.example/results",
    )
    operator = BrowserOperator()

    action = operator.decide_next_action("open first result", observation)

    assert action.type == "click_element"
    assert action.metadata["confidence"] >= 0.45


def test_generic_target_ranking_uses_context_and_roles():
    observation = build_element_map_from_html(
        "<a href='/a'>Intro</a><a href='/python'>Python Tutorials</a>",
        url="https://example.test",
    )
    match = find_target("click first result", observation, {"last_search_query": "python tutorials"})

    assert match is not None
    assert "Python" in match.element.label


def test_desktop_generic_controls_type_and_click_button():
    observation = build_control_map(
        [
            {"control_id": "editor", "role": "Edit", "name": "Document", "focused": True},
            {"control_id": "save", "role": "Button", "name": "Save"},
        ],
        active_app="editor",
        active_window="Document",
    )
    operator = DesktopOperator()

    type_action = operator.decide_next_action("type meeting notes", observation)
    click_match = operator.find_control_by_goal("Save", observation, {"preferred_roles": {"button"}})

    assert type_action["type"] == "type_text"
    assert type_action["element_id"] == "editor"
    assert click_match is not None
    assert click_match.element.element_id == "save"


def test_file_and_shell_code_generic_plans(monkeypatch, mock_workspace):
    documents = mock_workspace / "Documents"
    documents.mkdir()
    monkeypatch.setenv("USERPROFILE", str(mock_workspace))

    open_plan = build_execution_plan("open desktop in file explorer", route_user_command("open desktop in file explorer"))
    react_plan = build_execution_plan("initialize a react project in Documents in the name demos", route_user_command("initialize a react project in Documents in the name demos"))
    build_plan = build_execution_plan("run build for the project at Documents/demos", route_user_command("run build for the project at Documents/demos"))

    assert open_plan.steps[0].executor == "files"
    assert open_plan.steps[0].action_type == "open_path"
    assert any("npm install" in step.parameters.get("command", "") and step.needs_approval for step in react_plan.steps)
    assert build_plan.steps[0].tool_name == "run_shell_command"


def test_calculator_page_uses_code_file_build_verify_plan():
    plan = build_execution_plan(
        "make calculator page in the project at Documents/demos",
        route_user_command("make calculator page in the project at Documents/demos"),
    )

    assert [step.action_type for step in plan.steps] == [
        "list_tree",
        "write_file",
        "write_file",
        "shell_command",
        "verify_react_project",
    ]


def test_screenshot_goal_uses_artifact_verification_and_timeline(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    invoker = UniversalInvoker({"take_screenshot": f"Screenshot saved to: {tmp_path}/screenshots/shot.png"})

    result = asyncio.run(execute_goal("take screenshot", invoker))

    assert result.success is True
    assert result.final_goal_verified is True
    assert any(event["event_type"] == EventType.ARTIFACT_CREATED.value for event in result.pipeline_events)
    assert invoker.calls[0][0] == "take_screenshot"


def test_screenshot_analysis_graceful_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    invoker = UniversalInvoker({"inspect_desktop_screen": "Screenshot captured. OCR is not configured locally."})

    result = asyncio.run(execute_goal("analyze my screen", invoker))

    assert result.handled is True
    assert result.task_status == "completed"
    assert result.final_goal_verified is True


def test_screen_recording_requires_approval_before_start(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    invoker = UniversalInvoker()

    result = asyncio.run(execute_goal("start screen recording", invoker))

    assert result.task_status == "needs_approval"
    assert result.permission_pending is True
    assert invoker.calls == []


def test_screen_recording_start_stop_state(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(recording, "_recorder_available", lambda: True)

    started = recording.start_screen_recording(max_duration_seconds=5)
    stopped = recording.stop_screen_recording()

    assert started.ok is True
    assert recording.current_recording_state()["active"] is False
    assert stopped.ok is True
    assert stopped.artifact_path.endswith(".mp4")


def test_screen_recording_already_active_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    recording.recording_state_path().write_text(
        json.dumps({"active": True, "artifact_path": str(tmp_path / "recordings" / "active.mp4")}),
        encoding="utf-8",
    )

    started = recording.start_screen_recording(max_duration_seconds=5)

    assert started.ok is False
    assert started.permission_decision == "block"
    assert "already active" in started.message.lower()


def test_structured_audit_log_redacts_and_includes_target(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    secret = "sk-" + "a" * 48
    invoker = UniversalInvoker({"run_shell_command": f"Error: token {secret} command not found"})

    result = asyncio.run(execute_goal("run tests and report the result", invoker))

    assert result.success is False
    records = read_audit_records(limit=5)
    serialized = json.dumps(records)
    assert secret not in serialized
    assert "[REDACTED_SECRET]" in serialized
    assert any("target" in record for record in records)


def test_execute_goal_emergency_stop_blocks_before_action(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    trigger_emergency_stop("test")
    try:
        invoker = UniversalInvoker()
        result = asyncio.run(execute_goal("open notepad", invoker))
    finally:
        clear_emergency_stop()

    assert result.task_status == "emergency_stopped"
    assert result.final_goal_verified is False
    assert invoker.calls == []
    assert any(event["event_type"] == EventType.EMERGENCY_STOP_TRIGGERED.value for event in result.pipeline_events)


def test_cancelled_task_status_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    invoker = UniversalInvoker({"take_screenshot": "Cancelled by user before capture."})

    result = asyncio.run(execute_goal("take screenshot", invoker))

    assert result.task_status == "cancelled"
    assert result.final_goal_verified is False
    assert "Status: cancelled" in result.reply


def test_no_generic_fake_completion_messages_for_success(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    invoker = UniversalInvoker({"take_screenshot": f"Screenshot saved to: {tmp_path}/screenshots/shot.png"})

    result = asyncio.run(execute_goal("take screenshot", invoker))

    assert "Structured command completed" not in result.reply
    assert "Could not be completed safely" not in result.reply
    assert "Status: completed" in result.reply


def test_reserved_windows_filename_is_blocked(mock_workspace):
    safe = resolve_safe_path("workspace/CON.txt", tool_name="create_document", operation="write_new")

    assert safe.ok is False
    assert safe.decision.decision == "block"
    assert "reserved windows" in safe.reason.lower()


def test_shell_runtime_reports_timeout(monkeypatch, mock_workspace):
    def fake_run_terminal_command(*_args, **_kwargs):
        return TerminalResult(-1, "", "", timed_out=True)

    monkeypatch.setattr("friday.shell.runtime.run_terminal_command", fake_run_terminal_command)

    result = ShellRuntime(timeout_seconds=1).execute_command("pwd", cwd=mock_workspace)

    assert result.ok is False
    assert "timed out" in result.message.lower()


def test_shell_runtime_reports_command_not_found(monkeypatch, mock_workspace):
    def fake_run_terminal_command(*_args, **_kwargs):
        return TerminalResult(127, "", "command not found")

    monkeypatch.setattr("friday.shell.runtime.run_terminal_command", fake_run_terminal_command)

    result = ShellRuntime().execute_command("pwd", cwd=mock_workspace)

    assert result.ok is False
    assert result.returncode == 127
    assert "command not found" in result.stderr


def test_build_failure_response_is_truthful(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    invoker = UniversalInvoker({"run_shell_command": "Command failed: npm run build exited with code 1"})

    result = asyncio.run(execute_goal("run build for the project at Documents/demos", invoker))

    assert result.task_status == "failed"
    assert result.final_goal_verified is False
    assert "Status: failed" in result.reply
    assert "npm run build" in result.reply


def test_timeline_event_ordering_for_verified_task(tmp_path, monkeypatch):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))
    invoker = UniversalInvoker({"take_screenshot": f"Screenshot saved to: {tmp_path}/screenshots/shot.png"})

    result = asyncio.run(execute_goal("take screenshot", invoker))
    event_types = [event["event_type"] for event in result.pipeline_events]

    assert event_types.index(EventType.COMMAND_RECEIVED.value) < event_types.index(EventType.PLAN_CREATED.value)
    assert "step_started" in event_types
    assert event_types.index("verification_started") < event_types.index("verification_succeeded")
