"""
Planning tools — task decomposition, planning, and execution coordination.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any
import os
from friday.tools.llm_utils import call_llm


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


async def build_task_decomposition(request: str) -> dict[str, Any]:
    """
    Dynamically decomposes a complex request using the internal LLM reasoning engine.
    This replaces the old hardcoded templates with SOTA agentic planning.
    """
    system_prompt = (
        "You are F.R.I.D.A.Y.'s Strategic Planning Engine. "
        "Your goal is to decompose a complex user request into a sequence of atomic, actionable steps. "
        "Each step must use ONE tool from the following available set: "
        "web_search, fetch_url, calculate, list_files, read_file, write_file, "
        "run_shell, git_op, zip_files, etc.\n\n"
        "Output MUST be a valid JSON object with the following structure:\n"
        "{\n"
        "  \"decomposition\": [\n"
        "    {\n"
        "      \"id\": \"step1\",\n"
        "      \"description\": \"Brief human-readable goal\",\n"
        "      \"tool_needed\": \"tool_name\",\n"
        "      \"parameters\": { \"param1\": \"val1\" },\n"
        "      \"dependencies\": []\n"
        "    }\n"
        "  ],\n"
        "  \"summary\": \"Overall strategy overview\"\n"
        "}"
    )

    prompt = f"Decompose this request into a logical, multi-step plan: {request}"
    
    try:
        response_text = await call_llm(prompt, system_prompt, json_mode=True)
        plan_data = json.loads(response_text)
        
        # Ensure 'next_action' is present
        if "decomposition" in plan_data and plan_data["decomposition"]:
            plan_data["next_action"] = plan_data["decomposition"][0]["description"]
        else:
            plan_data["next_action"] = "No decomposition required"
            
        return plan_data
    except Exception as e:
        return {
            "error": f"Dynamic planning failed: {str(e)}",
            "decomposition": [],
            "summary": "Falling back to direct execution.",
            "next_action": "Execute directly"
        }


async def decompose_task(request: str) -> str:
    """
    Break down a complex user request into actionable steps using F.R.I.D.A.Y's dynamic reasoning engine.
    Identifies required subtasks, parameters, and dependencies automatically.
    """
    result = await build_task_decomposition(request)
    return json.dumps(result, indent=2)


async def reflect_on_step(step_description: str, tool_output: str) -> str:
    """
    Analyze the output of a completed task step to determine if the goal was met or if a pivot is needed.
    Part of F.R.I.D.A.Y's SOTA self-correction loop.
    """
    system_prompt = (
        "You are F.R.I.D.A.Y.'s Reflection and Error Correction engine. "
        "Analyze the tool output versus the step's goal. "
        "Determine if: 1. Goal met, 2. Partial success (adjust next step), or 3. Failure (pivot needed). "
        "Output your analysis and a recommended next course of action."
    )
    prompt = f"Goal: {step_description}\nTool Output: {tool_output}"
    
    return await call_llm(prompt, system_prompt)


async def track_plan_in_workspace(plan_json: str, workspace_path: str | None = None) -> str:
    """
    Takes the JSON output from decompose_task and writes it as a Markdown checklist to the workspace.
    This provides a tangible, persistent tracker for long-running or complex tasks F.R.I.D.A.Y handles.
    """
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


async def monitor_progress(workspace_path: str = "workspace/current_plan.md") -> str:
    """
    Reads the current markdown plan tracker file to check the progress of the active task.
    """
    if not os.path.exists(workspace_path):
        return f"No active plan tracking file found at {workspace_path}."

    try:
        with open(workspace_path, "r", encoding="utf-8") as f:
            content = f.read()
        return f"--- Current Plan Tracker ({workspace_path}) ---\n{content}"
    except Exception as e:
        return f"Error reading tracker: {str(e)}"


def register(mcp):
    mcp.tool()(decompose_task)
    mcp.tool()(reflect_on_step)
    mcp.tool()(track_plan_in_workspace)
    mcp.tool()(monitor_progress)
