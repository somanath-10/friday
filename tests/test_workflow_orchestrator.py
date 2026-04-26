import json
import pytest

from friday.tools import workflow_orchestrator as wf


@pytest.mark.parametrize(
    ("goal", "expected_capabilities", "requires_confirmation"),
    [
        (
            "Search the web, write a file, run tests, and commit the change",
            {"network", "files", "shell", "git"},
            False,
        ),
        (
            "Open Chrome, login to the website, and submit the form",
            {"browser", "desktop"},
            False,
        ),
        (
            "Delete the temp folder and reset the git branch",
            {"files", "git", "destructive"},
            True,
        ),
        (
            "Use AI to analyze and summarize this report",
            {"provider_ai"},
            False,
        ),
    ],
)
def test_analyze_workflow_capability_matrix(goal, expected_capabilities, requires_confirmation):
    result = json.loads(wf.analyze_workflow(goal))

    assert expected_capabilities.issubset(set(result["capabilities"]))
    assert result["requires_confirmation"] is requires_confirmation


def test_analyze_workflow_detects_capabilities():
    result = json.loads(
        wf.analyze_workflow("Search the web, write a file, run tests, and commit the change")
    )

    assert "network" in result["capabilities"]
    assert "files" in result["capabilities"]
    assert "shell" in result["capabilities"]
    assert "git" in result["capabilities"]
    assert "search_web" in result["suggested_tools"]


def test_preflight_warns_for_missing_ai_provider(monkeypatch, mock_workspace):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    report = wf.run_workflow_preflight("Use AI to analyze and summarize this report")

    assert "Status: WARN" in report
    assert "llm_provider" in report
    assert "No OPENAI_API_KEY or GOOGLE_API_KEY" in report


def test_preflight_blocks_destructive_workflow(mock_workspace):
    report = wf.run_workflow_preflight("Delete the downloaded folder and clean the workspace")

    assert "Status: BLOCKED" in report
    assert "[BLOCKED] confirmation" in report


def test_preflight_blocks_browser_workflow_when_playwright_missing(monkeypatch, mock_workspace):
    original_find_spec = wf.importlib.util.find_spec

    def fake_find_spec(module_name: str):
        if module_name == "playwright":
            return None
        return original_find_spec(module_name)

    monkeypatch.setattr(wf.importlib.util, "find_spec", fake_find_spec)

    report = wf.run_workflow_preflight("Open a website in the browser and click the login form")

    assert "Status: BLOCKED" in report
    assert "[BLOCKED] playwright" in report


def test_create_workflow_plan_persists_latest_status(mock_workspace):
    report = wf.create_workflow_plan("Read a file and write a summary", mode="balanced")

    assert "=== Workflow Plan ===" in report
    assert "Mode: balanced" in report
    assert (mock_workspace / "workflows" / "latest_workflow.txt").exists()

    status = wf.get_workflow_status()
    assert "read a file" in status.lower()
    assert "verify" in status.lower()


def test_create_workflow_plan_marks_blocked_when_preflight_blocks(mock_workspace):
    report = wf.create_workflow_plan("Delete the report folder and clean everything", mode="safe")

    assert "Status: blocked" in report
    assert "Preflight: BLOCKED" in report


def test_record_progress_and_complete_workflow(mock_workspace):
    wf.create_workflow_plan("Run tests and report the result")

    update = wf.record_workflow_progress(
        step_id="execute",
        status="passed",
        result="pytest passed",
        next_action="verify output",
    )
    assert "execute -> passed" in update

    complete = wf.complete_workflow(outcome="All checks passed", verified=True)
    assert "marked completed" in complete
    assert "Status: completed" in wf.get_workflow_status()


def test_record_progress_invalid_status_is_rejected(mock_workspace):
    wf.create_workflow_plan("Run tests and report the result")

    result = wf.record_workflow_progress(step_id="execute", status="donezo")

    assert "Invalid status" in result


def test_record_progress_rejects_unknown_step(mock_workspace):
    wf.create_workflow_plan("Run tests and report the result")

    result = wf.record_workflow_progress(step_id="nonexistent", status="running")

    assert "No step found" in result


def test_record_progress_sets_workflow_running_and_failed_states(mock_workspace):
    wf.create_workflow_plan("Run tests and report the result")

    running = wf.record_workflow_progress(step_id="execute", status="running")
    assert "execute -> running" in running
    assert "Status: running" in wf.get_workflow_status()

    failed = wf.record_workflow_progress(step_id="verify", status="failed", result="tests failed")
    assert "verify -> failed" in failed
    assert "Status: failed" in wf.get_workflow_status()


def test_complete_workflow_can_mark_completed_with_risk(mock_workspace):
    wf.create_workflow_plan("Run tests and report the result")

    complete = wf.complete_workflow(outcome="Finished but not fully verified", verified=False)

    assert "completed_with_risk" in complete
    assert "Status: completed_with_risk" in wf.get_workflow_status()


def test_register_adds_workflow_tools(mock_mcp):
    wf.register(mock_mcp)

    assert "create_workflow_plan" in mock_mcp.tools
    assert "run_workflow_preflight" in mock_mcp.tools
    assert "complete_workflow" in mock_mcp.tools
