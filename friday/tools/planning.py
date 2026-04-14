"""
Planning tools — task decomposition, planning, and execution coordination.
"""

import json
import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from enum import Enum


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
    parameters: Dict[str, Any]
    dependencies: List[str]  # IDs of steps that must complete first
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None


def register(mcp):

    @mcp.tool()
    async def decompose_task(request: str) -> str:
        """
        Break down a complex user request into actionable steps.
        Analyzes the request and identifies required subtasks, tools needed, and dependencies.
        Use this when the user asks for something complex that requires multiple operations.
        """

        # Simple rule-based decomposition (can be enhanced with LLM later)
        request_lower = request.lower()

        steps = []

        # Pattern matching for common complex requests
        if "analyze" in request_lower and ("code" in request_lower or "project" in request_lower):
            steps.extend([
                TaskStep(
                    id="step1",
                    description="Examine project structure and file types",
                    tool_needed="glob",
                    parameters={"pattern": "**/*", "path": "."},
                    dependencies=[]
                ),
                TaskStep(
                    id="step2",
                    description="Read key configuration files",
                    tool_needed="read",
                    parameters={"file_path": ""},  # Will be filled based on step1 results
                    dependencies=["step1"]
                ),
                TaskStep(
                    id="step3",
                    description="Analyze code quality and structure",
                    tool_needed="execute_python_code",
                    parameters={"code": ""},  # Will be filled with analysis code
                    dependencies=["step1", "step2"]
                )
            ])

        elif "search" in request_lower and ("information" in request_lower or "research" in request_lower):
            steps.extend([
                TaskStep(
                    id="step1",
                    description="Search for general information",
                    tool_needed="search_web",
                    parameters={"query": ""},  # Will extract from request
                    dependencies=[]
                ),
                TaskStep(
                    id="step2",
                    description="Search for technical/code resources",
                    tool_needed="search_code",
                    parameters={"query": ""},  # Will extract from request
                    dependencies=[]
                ),
                TaskStep(
                    id="step3",
                    description="Fetch and summarize relevant URLs",
                    tool_needed="fetch_url",
                    parameters={"url": ""},  # Will be filled from search results
                    dependencies=["step1", "step2"]
                )
            ])

        elif "create" in request_lower or "build" in request_lower:
            steps.extend([
                TaskStep(
                    id="step1",
                    description="Plan the implementation approach",
                    tool_needed="format_json",
                    parameters={"data": '{"approach": "to_be_determined"}'},  # Placeholder
                    dependencies=[]
                ),
                TaskStep(
                    id="step2",
                    description="Create necessary files",
                    tool_needed="write_file",
                    parameters={"file_path": "", "content": ""},  # Will be filled
                    dependencies=["step1"]
                ),
                TaskStep(
                    id="step3",
                    description="Test and validate the creation",
                    tool_needed="execute_python_code",
                    parameters={"code": ""},  # Will be filled with test code
                    dependencies=["step2"]
                )
            ])
        else:
            # Generic fallback - break into logical steps based on keywords
            steps.append(
                TaskStep(
                    id="step1",
                    description="Gather initial information",
                    tool_needed="search_web",
                    parameters={"query": request},
                    dependencies=[]
                )
            )

            if any(word in request_lower for word in ["analyze", "examine", "review"]):
                steps.append(
                    TaskStep(
                        id="step2",
                        description="Process and analyze gathered information",
                        tool_needed="execute_python_code",
                        parameters={"code": "# Analysis code will be generated based on step1 results"},
                        dependencies=["step1"]
                    )
                )

        # Convert to JSON for return
        steps_data = []
        for step in steps:
            step_dict = asdict(step)
            step_dict['status'] = step.status.value
            steps_data.append(step_dict)

        return json.dumps({
            "decomposition": steps_data,
            "summary": f"Broken down into {len(steps)} actionable steps",
            "next_action": "Execute steps in order, respecting dependencies"
        }, indent=2)

    @mcp.tool()
    async def track_plan_in_workspace(plan_json: str, workspace_path: str = "workspace/current_plan.md") -> str:
        """
        Takes the JSON output from decompose_task and writes it as a Markdown checklist to the workspace.
        This provides a tangible, persistent tracker for long-running or complex tasks F.R.I.D.A.Y handles.
        """
        import os
        try:
            plan_data = json.loads(plan_json)
            steps = plan_data.get("decomposition", [])
            
            os.makedirs(os.path.dirname(os.path.abspath(workspace_path)), exist_ok=True)
            
            lines = ["# F.R.I.D.A.Y Task Execution Plan\n"]
            for step in steps:
                lines.append(f"- [ ] **Step {step['id']}**: {step['description']} (Tool: `{step['tool_needed']}`)")
            
            with open(workspace_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
                
            return f"Plan successfully tracked. Checklist written to {os.path.abspath(workspace_path)}. Please read / update this file to track your task."
            
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
            with open(workspace_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return f"--- Current Plan Tracker ({workspace_path}) ---\n{content}"
        except Exception as e:
            return f"Error reading tracker: {str(e)}"