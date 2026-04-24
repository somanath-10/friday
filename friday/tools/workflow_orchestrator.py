"""
Workflow orchestrator tools for goal-level planning, preflight, and progress tracking.
"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from friday.path_utils import workspace_dir
from friday.tools.error_handling import safe_tool, validate_inputs

CAPABILITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "browser": (
        "browser",
        "browse",
        "click",
        "website",
        "web page",
        "open url",
        "login",
        "form",
    ),
    "desktop": (
        "desktop",
        "screen",
        "screenshot",
        "window",
        "app",
        "application",
        "open edge",
        "open chrome",
        "notepad",
        "finder",
    ),
    "files": (
        "file",
        "folder",
        "directory",
        "write",
        "save",
        "read",
        "pdf",
        "csv",
        "document",
    ),
    "git": (
        "git",
        "commit",
        "push",
        "pull",
        "branch",
        "diff",
        "merge",
    ),
    "network": (
        "web",
        "search",
        "latest",
        "current",
        "fetch",
        "url",
        "api",
        "download",
    ),
    "shell": (
        "shell",
        "terminal",
        "command",
        "install",
        "build",
        "test",
        "pytest",
        "npm",
        "run",
    ),
    "provider_ai": (
        "ai",
        "llm",
        "model",
        "vision",
        "summarize",
        "analyze",
        "classify",
        "generate",
        "research",
    ),
    "destructive": (
        "delete",
        "remove",
        "overwrite",
        "reset",
        "clean",
        "drop",
    ),
}

SUGGESTED_TOOLS: dict[str, list[str]] = {
    "browser": ["browser_navigate", "browser_read_page", "browser_get_state"],
    "desktop": ["run_permission_diagnostics", "inspect_desktop_screen", "list_open_windows"],
    "files": ["get_file_contents", "write_file", "list_directory_tree"],
    "git": ["git_status", "git_diff", "git_commit"],
    "network": ["search_web", "fetch_url", "deep_scrape_url"],
    "shell": ["run_shell_command", "execute_python_code"],
    "provider_ai": ["decompose_task", "reflect_on_step", "synthesize_knowledge"],
    "destructive": ["create_workflow_plan", "record_workflow_progress"],
}

VALID_PROGRESS_STATUSES = {"pending", "running", "passed", "failed", "blocked", "skipped"}


def _workflows_dir() -> Path:
    path = workspace_dir() / "workflows"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _latest_file() -> Path:
    return _workflows_dir() / "latest_workflow.txt"


def _workflow_file(workflow_id: str) -> Path:
    safe_id = Path(workflow_id).name
    return _workflows_dir() / f"{safe_id}.json"


def _load_workflow(workflow_id: str) -> dict[str, Any]:
    path = _workflow_file(workflow_id)
    if not path.exists():
        raise FileNotFoundError(f"No workflow found with id: {workflow_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_workflow(data: dict[str, Any]) -> Path:
    workflow_id = str(data["workflow_id"])
    path = _workflow_file(workflow_id)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _latest_file().write_text(workflow_id, encoding="utf-8")
    return path


def _resolve_workflow_id(workflow_id: str) -> str:
    if workflow_id and workflow_id != "latest":
        return workflow_id
    latest = _latest_file()
    if not latest.exists():
        raise FileNotFoundError("No latest workflow has been created yet.")
    return latest.read_text(encoding="utf-8").strip()


def _detect_capabilities(goal: str) -> list[str]:
    text = goal.lower()
    capabilities = [
        capability
        for capability, keywords in CAPABILITY_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    ]
    if not capabilities:
        capabilities = ["general"]
    return capabilities


def _tools_for_capabilities(capabilities: list[str]) -> list[str]:
    tools: list[str] = []
    for capability in capabilities:
        for tool in SUGGESTED_TOOLS.get(capability, []):
            if tool not in tools:
                tools.append(tool)
    return tools


def _check_macos_permission(command: list[str], denied_hint: str, timeout: int = 5) -> dict[str, str]:
    try:
        import subprocess

        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return {"status": "READY", "message": "Permission check passed."}
        detail = (result.stderr or result.stdout or denied_hint).strip()
        return {"status": "BLOCKED", "message": detail}
    except Exception as exc:
        return {"status": "WARN", "message": f"Permission check could not run: {exc}"}


def _preflight_checks(goal: str, live_checks: bool = False) -> dict[str, Any]:
    capabilities = _detect_capabilities(goal)
    checks: list[dict[str, str]] = []

    workspace = workspace_dir()
    checks.append(
        {
            "name": "workspace",
            "status": "READY" if os.access(workspace, os.W_OK) else "BLOCKED",
            "message": f"Workspace is writable: {workspace}",
        }
    )

    if "browser" in capabilities:
        checks.append(
            {
                "name": "playwright",
                "status": "READY" if importlib.util.find_spec("playwright") else "BLOCKED",
                "message": "Playwright is available." if importlib.util.find_spec("playwright") else "Install Playwright and browser binaries.",
            }
        )

    if "provider_ai" in capabilities:
        has_provider = bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
        checks.append(
            {
                "name": "llm_provider",
                "status": "READY" if has_provider else "WARN",
                "message": "At least one LLM provider key is configured." if has_provider else "No OPENAI_API_KEY or GOOGLE_API_KEY detected; use non-LLM fallbacks when possible.",
            }
        )

    if "network" in capabilities:
        checks.append(
            {
                "name": "network",
                "status": "READY",
                "message": "Network-dependent tools should use retries and cached fallbacks.",
            }
        )

    if "desktop" in capabilities:
        system = platform.system()
        if system == "Darwin" and live_checks:
            with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
                screen = _check_macos_permission(
                    ["screencapture", "-x", tmp.name],
                    "Screen Recording permission is required.",
                )
            checks.append(
                {
                    "name": "screen_recording",
                    "status": screen["status"],
                    "message": screen["message"],
                }
            )
            access = _check_macos_permission(
                ["osascript", "-e", 'tell application "System Events" to get name of every process'],
                "Accessibility permission is required.",
            )
            checks.append(
                {
                    "name": "accessibility",
                    "status": access["status"],
                    "message": access["message"],
                }
            )
        elif system == "Darwin":
            checks.append(
                {
                    "name": "desktop_permissions",
                    "status": "WARN",
                    "message": "Run run_permission_diagnostics before desktop automation.",
                }
            )
        else:
            checks.append(
                {
                    "name": "desktop_permissions",
                    "status": "WARN",
                    "message": f"Desktop checks are platform-specific on {system}. Verify permissions before GUI control.",
                }
            )

    if "destructive" in capabilities:
        checks.append(
            {
                "name": "confirmation",
                "status": "BLOCKED",
                "message": "Destructive actions need explicit user confirmation before execution.",
            }
        )

    aggregate = "READY"
    if any(check["status"] == "BLOCKED" for check in checks):
        aggregate = "BLOCKED"
    elif any(check["status"] == "WARN" for check in checks):
        aggregate = "WARN"

    return {
        "goal": goal,
        "capabilities": capabilities,
        "suggested_tools": _tools_for_capabilities(capabilities),
        "status": aggregate,
        "checks": checks,
    }


def _build_steps(goal: str, capabilities: list[str], mode: str) -> list[dict[str, Any]]:
    execute_tools = _tools_for_capabilities(capabilities)
    execute_detail = (
        "Run the minimum necessary tool chain for the goal."
        if execute_tools
        else "Answer directly or use the most relevant available tool."
    )
    return [
        {
            "id": "understand",
            "title": "Clarify intent and constraints",
            "status": "pending",
            "detail": f"Confirm objective, inputs, outputs, and safety level for: {goal}",
            "verification": "The requested outcome is concrete and testable.",
        },
        {
            "id": "preflight",
            "title": "Check readiness",
            "status": "pending",
            "detail": "Validate required permissions, provider keys, workspace access, and dependencies.",
            "verification": "No blocker remains before execution.",
        },
        {
            "id": "execute",
            "title": "Execute with tools",
            "status": "pending",
            "detail": execute_detail,
            "tools": execute_tools,
            "verification": "Each tool output is checked before moving to the next step.",
        },
        {
            "id": "verify",
            "title": "Verify result",
            "status": "pending",
            "detail": "Run tests, inspect files, check UI state, or validate generated output.",
            "verification": "The final artifact or action matches the user's goal.",
        },
        {
            "id": "recover",
            "title": "Recover if needed",
            "status": "pending",
            "detail": "If a step fails, use fallback tools, cached data, or a smaller safe action.",
            "verification": "Failures have a next action instead of a dead end.",
        },
        {
            "id": "report",
            "title": "Report and remember",
            "status": "pending",
            "detail": f"Summarize outcome, changed files, checks run, and follow-up risk. Mode: {mode}.",
            "verification": "The user can see exactly what worked and what remains.",
        },
    ]


def _format_preflight(preflight: dict[str, Any]) -> str:
    lines = [
        "=== Workflow Preflight ===",
        f"Goal: {preflight['goal']}",
        f"Status: {preflight['status']}",
        "Capabilities: " + ", ".join(preflight["capabilities"]),
    ]
    if preflight["suggested_tools"]:
        lines.append("Suggested tools: " + ", ".join(preflight["suggested_tools"]))
    lines.append("")
    for check in preflight["checks"]:
        lines.append(f"[{check['status']}] {check['name']}: {check['message']}")
    return "\n".join(lines)


def _format_workflow(data: dict[str, Any]) -> str:
    lines = [
        "=== Workflow Plan ===",
        f"ID: {data['workflow_id']}",
        f"Goal: {data['goal']}",
        f"Mode: {data['mode']}",
        f"Status: {data['status']}",
        f"Preflight: {data['preflight']['status']}",
        f"File: {data['path']}",
        "",
        "Steps:",
    ]
    for step in data["steps"]:
        lines.append(f"- [{step['status']}] {step['id']}: {step['title']}")
        lines.append(f"  Verify: {step['verification']}")
    return "\n".join(lines)


def analyze_workflow(goal: str) -> str:
    """
    Analyze a user goal and return the likely capabilities and tool families needed.
    Use this before complex tasks to choose a smooth, low-friction execution path.
    """
    capabilities = _detect_capabilities(goal)
    payload = {
        "goal": goal,
        "capabilities": capabilities,
        "suggested_tools": _tools_for_capabilities(capabilities),
        "requires_confirmation": "destructive" in capabilities,
    }
    return json.dumps(payload, indent=2)


@safe_tool
@validate_inputs(max_str_len=12000)
def run_workflow_preflight(goal: str, live_checks: bool = False) -> str:
    """
    Check likely blockers before starting a workflow.
    live_checks=True performs OS permission probes for desktop automation.
    """
    return _format_preflight(_preflight_checks(goal, live_checks=live_checks))


@safe_tool
@validate_inputs(max_str_len=12000)
def create_workflow_plan(goal: str, mode: str = "safe", live_checks: bool = False) -> str:
    """
    Create and persist a goal-level workflow plan with preflight, verification, and recovery steps.
    mode can be safe, balanced, or power; safe mode flags destructive work for confirmation.
    """
    normalized_mode = mode.strip().lower() or "safe"
    if normalized_mode not in {"safe", "balanced", "power"}:
        normalized_mode = "safe"

    preflight = _preflight_checks(goal, live_checks=live_checks)
    workflow_id = f"wf_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    data = {
        "workflow_id": workflow_id,
        "goal": goal,
        "mode": normalized_mode,
        "status": "blocked" if preflight["status"] == "BLOCKED" else "planned",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "preflight": preflight,
        "steps": _build_steps(goal, preflight["capabilities"], normalized_mode),
        "events": [],
    }
    path = _save_workflow(data)
    data["path"] = str(path)
    _save_workflow(data)
    return _format_workflow(data)


@safe_tool
@validate_inputs(max_str_len=12000)
def record_workflow_progress(
    workflow_id: str = "latest",
    step_id: str = "",
    status: str = "running",
    result: str = "",
    next_action: str = "",
) -> str:
    """
    Update a workflow step and append an event to the workflow journal.
    Status values: pending, running, passed, failed, blocked, skipped.
    """
    resolved_id = _resolve_workflow_id(workflow_id)
    data = _load_workflow(resolved_id)
    normalized_status = status.strip().lower()
    if normalized_status not in VALID_PROGRESS_STATUSES:
        return f"Invalid status '{status}'. Use one of: {', '.join(sorted(VALID_PROGRESS_STATUSES))}."

    matched = False
    for step in data["steps"]:
        if step["id"] == step_id:
            step["status"] = normalized_status
            if result:
                step["result"] = result
            if next_action:
                step["next_action"] = next_action
            matched = True
            break
    if not matched:
        return f"No step found with id '{step_id}'."

    data["events"].append(
        {
            "timestamp": datetime.now().isoformat(),
            "step_id": step_id,
            "status": normalized_status,
            "result": result,
            "next_action": next_action,
        }
    )
    if normalized_status in {"failed", "blocked"}:
        data["status"] = normalized_status
    elif all(step["status"] in {"passed", "skipped"} for step in data["steps"]):
        data["status"] = "ready_to_complete"
    elif any(step["status"] == "running" for step in data["steps"]):
        data["status"] = "running"
    else:
        data["status"] = "planned"
    data["updated_at"] = datetime.now().isoformat()
    path = _save_workflow(data)
    return f"Workflow {resolved_id} updated: {step_id} -> {normalized_status}\nFile: {path}"


@safe_tool
def get_workflow_status(workflow_id: str = "latest") -> str:
    """Return a compact status report for the latest or specified workflow."""
    resolved_id = _resolve_workflow_id(workflow_id)
    data = _load_workflow(resolved_id)
    return _format_workflow(data)


@safe_tool
@validate_inputs(max_str_len=12000)
def complete_workflow(workflow_id: str = "latest", outcome: str = "", verified: bool = True) -> str:
    """
    Mark a workflow complete and persist the final outcome.
    Use verified=False when work finished but still has an explicit testing gap.
    """
    resolved_id = _resolve_workflow_id(workflow_id)
    data = _load_workflow(resolved_id)
    data["status"] = "completed" if verified else "completed_with_risk"
    data["outcome"] = outcome
    data["verified"] = bool(verified)
    data["updated_at"] = datetime.now().isoformat()
    data["events"].append(
        {
            "timestamp": datetime.now().isoformat(),
            "step_id": "complete",
            "status": data["status"],
            "result": outcome,
            "next_action": "",
        }
    )
    path = _save_workflow(data)
    return f"Workflow {resolved_id} marked {data['status']}.\nFile: {path}"


def register(mcp):
    mcp.tool()(analyze_workflow)
    mcp.tool()(run_workflow_preflight)
    mcp.tool()(create_workflow_plan)
    mcp.tool()(record_workflow_progress)
    mcp.tool()(get_workflow_status)
    mcp.tool()(complete_workflow)
