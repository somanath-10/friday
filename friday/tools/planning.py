"""
Planning tools — task decomposition, planning, and execution coordination.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskStep:
    id: str
    description: str
    tool_needed: str
    parameters: dict[str, Any]
    dependencies: list[str]
    status: TaskStatus = TaskStatus.PENDING
    result: str | None = None
    error: str | None = None


def _step(
    step_id: str,
    description: str,
    tool_needed: str,
    parameters: dict[str, Any],
    dependencies: list[str] | None = None,
) -> TaskStep:
    return TaskStep(
        id=step_id,
        description=description,
        tool_needed=tool_needed,
        parameters=parameters,
        dependencies=dependencies or [],
    )


def build_task_decomposition(request: str) -> dict[str, Any]:
    request_lower = request.lower()
    steps: list[TaskStep]

    if "analyze" in request_lower and any(word in request_lower for word in ("code", "project", "repo")):
        steps = [
            _step(
                "step1",
                "Map the repository structure and identify likely entrypoints",
                "list_directory_tree",
                {"path": ".", "max_depth": 3},
            ),
            _step(
                "step2",
                "Read the main project configuration and documentation",
                "get_file_contents",
                {"file_path": "pyproject.toml"},
                ["step1"],
            ),
            _step(
                "step3",
                "Search the codebase for the feature, bug, or area of interest",
                "search_in_files",
                {"directory": ".", "keyword": request},
                ["step1"],
            ),
            _step(
                "step4",
                "Inspect the most relevant implementation blocks in detail",
                "read_file_snippet",
                {"file_path": "agent_friday.py", "start_line": 1, "end_line": 200},
                ["step2", "step3"],
            ),
            _step(
                "step5",
                "Run a lightweight verification command once the review is complete",
                "run_shell_command",
                {"command": "python -m compileall ."},
                ["step4"],
            ),
        ]
    elif any(word in request_lower for word in ("research", "search", "latest", "find information")):
        steps = [
            _step(
                "step1",
                "Search the web for broad, current information",
                "search_web",
                {"query": request},
            ),
            _step(
                "step2",
                "Search for technical references if the request is implementation-oriented",
                "search_code",
                {"query": request},
            ),
            _step(
                "step3",
                "Open and summarize the most relevant source from the search results",
                "fetch_url",
                {"url": "<top_result_url>"},
                ["step1", "step2"],
            ),
        ]
    elif any(word in request_lower for word in ("create", "build", "implement", "make")):
        steps = [
            _step(
                "step1",
                "Inspect the current workspace before making changes",
                "list_directory_tree",
                {"path": ".", "max_depth": 3},
            ),
            _step(
                "step2",
                "Draft or update the target file(s) required for the implementation",
                "write_file",
                {"file_path": "workspace/implementation.txt", "content": "<implementation goes here>"},
                ["step1"],
            ),
            _step(
                "step3",
                "Run a validation command or script against the new implementation",
                "run_shell_command",
                {"command": "python -m compileall ."},
                ["step2"],
            ),
        ]
    else:
        steps = [
            _step(
                "step1",
                "Gather the most relevant starting context for the request",
                "search_web",
                {"query": request},
            )
        ]

    steps_data = []
    for step in steps:
        step_dict = asdict(step)
        step_dict["status"] = step.status.value
        steps_data.append(step_dict)

    return {
        "decomposition": steps_data,
        "summary": f"Broken down into {len(steps)} actionable steps",
        "next_action": steps_data[0]["description"] if steps_data else "No action required",
    }


def register(mcp):

    @mcp.tool()
    async def decompose_task(request: str) -> str:
        """
        Break down a complex user request into actionable steps.
        Analyzes the request and identifies required subtasks, tools needed, and dependencies.
        Use this when the user asks for something complex that requires multiple operations.
        """
        return json.dumps(build_task_decomposition(request), indent=2)

    @mcp.tool()
    async def track_plan_in_workspace(plan_json: str, workspace_path: str | None = None) -> str:
        """
        Takes the JSON output from decompose_task and writes it as a Markdown checklist to the workspace.
        This provides a tangible, persistent tracker for long-running or complex tasks F.R.I.D.A.Y handles.
        """
        import os

        try:
            if workspace_path is None:
                base_dir = os.environ.get("FRIDAY_WORKSPACE_DIR", "workspace")
                workspace_path = os.path.join(base_dir, "current_plan.md")

            plan_data = json.loads(plan_json)
            steps = plan_data.get("decomposition", [])

            os.makedirs(os.path.dirname(os.path.abspath(workspace_path)), exist_ok=True)

            lines = ["# F.R.I.D.A.Y Task Execution Plan\n"]
            for step in steps:
                lines.append(
                    f"- [ ] **Step {step['id']}**: {step['description']} "
                    f"(Tool: `{step['tool_needed']}`)"
                )

            with open(workspace_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))

            return (
                f"Plan successfully tracked. Checklist written to {os.path.abspath(workspace_path)}. "
                "Please read / update this file to track your task."
            )

        except Exception as e:
            return f"Error tracking plan: {str(e)}"

    @mcp.tool()
    async def monitor_progress(workspace_path: str = "workspace/current_plan.md") -> str:
        """
        Reads the current markdown plan tracker file to check the progress of the active task.
        """
        import os

        if not os.path.exists(workspace_path):
            return f"No active plan tracking file found at {workspace_path}."

        try:
            with open(workspace_path, "r", encoding="utf-8") as f:
                content = f.read()
            return f"--- Current Plan Tracker ({workspace_path}) ---\n{content}"
        except Exception as e:
            return f"Error reading tracker: {str(e)}"
