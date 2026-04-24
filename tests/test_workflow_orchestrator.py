import json

from friday.tools import workflow_orchestrator as wf


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


def test_create_workflow_plan_persists_latest_status(mock_workspace):
    report = wf.create_workflow_plan("Read a file and write a summary", mode="balanced")

    assert "=== Workflow Plan ===" in report
    assert "Mode: balanced" in report
    assert (mock_workspace / "workflows" / "latest_workflow.txt").exists()

    status = wf.get_workflow_status()
    assert "read a file" in status.lower()
    assert "verify" in status.lower()


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


def test_register_adds_workflow_tools(mock_mcp):
    wf.register(mock_mcp)

    assert "create_workflow_plan" in mock_mcp.tools
    assert "run_workflow_preflight" in mock_mcp.tools
    assert "complete_workflow" in mock_mcp.tools
