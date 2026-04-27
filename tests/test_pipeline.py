from friday.core.events import EventType
from friday.core.executor import run_command_pipeline
from friday.core.models import Intent, StepExecutionResult
from friday.core.planner import create_plan
from friday.core.router import route_intent
from friday.core.verifier import verify_step


def test_router_detects_core_intents():
    assert route_intent("open notepad and type hello").intent == Intent.DESKTOP
    assert route_intent("move pdfs from downloads to invoices").intent == Intent.FILES
    assert route_intent("run tests and fix errors").intent == Intent.CODE
    assert route_intent("open chrome and login to portal").intent == Intent.BROWSER


def test_router_treats_explorer_folder_open_as_file_task():
    result = route_intent("open desktop in file explorer")

    assert result.intent == Intent.FILES
    assert result.suggested_executor == "files"


def test_planner_marks_git_push_for_approval():
    plan = create_plan("commit and push changes")

    assert plan.intent.intent == Intent.CODE
    assert plan.steps[0].needs_approval is True
    assert plan.steps[0].risk_level >= 3


def test_verifier_accepts_dry_run_result():
    plan = create_plan("create a report file")
    step = plan.steps[0]
    result = StepExecutionResult(step.id, "dry_run", "Dry run", dry_run=True)

    verification = verify_step(step, result)

    assert verification.ok is True
    assert verification.method == step.verification_method


def test_pipeline_dry_run_emits_events_and_audit(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))

    result = run_command_pipeline("create a report file", dry_run=True)

    event_types = [event["event_type"] for event in result.events]
    assert EventType.COMMAND_RECEIVED.value in event_types
    assert EventType.INTENT_DETECTED.value in event_types
    assert EventType.PLAN_CREATED.value in event_types
    assert result.status == "completed"
    assert result.step_results[0].status == "dry_run"
    assert (tmp_path / "logs" / "audit.jsonl").exists()


def test_pipeline_pauses_for_sensitive_action(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))

    result = run_command_pipeline("delete all files in Downloads", dry_run=True)

    assert result.status == "paused"
    assert any(step.status == "permission_required" for step in result.step_results)
    assert any(event["event_type"] == EventType.PERMISSION_REQUIRED.value for event in result.events)


def test_planner_preserves_desktop_type_text():
    plan = create_plan("open notepad and type meeting notes")

    assert plan.intent.intent == Intent.DESKTOP
    assert plan.steps[1].parameters["text"] == "meeting notes"


def test_planner_creates_open_path_for_windows_folder_open():
    plan = create_plan("open desktop in file explorer")

    assert plan.intent.intent == Intent.FILES
    assert plan.steps[0].action_type == "open_path"
    assert plan.steps[0].parameters["path"] == "Desktop"


def test_pipeline_can_execute_safe_file_write(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))

    result = run_command_pipeline("create 'hello report' file", dry_run=False)

    assert result.status == "completed"
    assert result.step_results[0].status == "succeeded"
    assert (tmp_path / "generated_by_friday.txt").exists()


def test_pipeline_folder_open_is_a_file_workflow(monkeypatch, tmp_path):
    monkeypatch.setenv("FRIDAY_WORKSPACE_DIR", str(tmp_path))

    result = run_command_pipeline("open desktop in file explorer", dry_run=True)

    assert result.plan.intent.intent == Intent.FILES
    assert result.plan.steps[0].action_type == "open_path"
