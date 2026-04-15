"""
Subagent delegation — allows the real-time voice agent to offload massive coding,
research, or multi-step tasks to an autonomous background worker.
"""

import json
import os
import uuid
import subprocess
from pathlib import Path


def register(mcp):

    @mcp.tool()
    def delegate_to_subagent(objective: str, task_type: str = "auto") -> str:
        """
        Dispatch any large, complex, or long-running task to the Mark IV autonomous background worker.

        USE THIS WHENEVER:
        - The user asks to build a full app, tool, script, or project.
        - The task requires multiple steps, iterations, or heavy computation.
        - The user gives a complex multi-part instruction.
        - Doing it inline would freeze the voice pipeline.
        - Research tasks that require searching + writing long reports.

        task_type: Hint to the subagent about what kind of task this is.
          - 'coding'   → Write, execute, and debug Python code iteratively.
          - 'research' → Search the web, collect data, write a report.
          - 'writing'  → Draft a document, report, or structured content.
          - 'auto'     → Let the subagent figure it out from the objective.
        """
        try:
            task_id = str(uuid.uuid4())[:8]
            base_workspace = os.environ.get("FRIDAY_WORKSPACE_DIR", "workspace")
            workspace_dir = os.path.abspath(os.path.join(base_workspace, f"subagent_{task_id}"))
            os.makedirs(workspace_dir, exist_ok=True)

            core_script = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "worker_core.py"
            )

            # Pass task_type as extra arg to the worker
            subprocess.Popen(
                ["python3", core_script, objective, workspace_dir, task_type],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=workspace_dir,
                env={**os.environ},  # Pass full env so worker has API keys & settings
            )

            return (
                f"Mark IV Subagent dispatched! (ID: {task_id}, Type: {task_type})\n"
                f"Working directory: {workspace_dir}\n"
                f"Progress log: {workspace_dir}/subagent_log.md\n"
                f"The worker will auto-correct its own errors and iterate until done."
            )
        except Exception as e:
            return f"Failed to delegate to Mark IV subagent: {str(e)}"

    @mcp.tool()
    def check_subagent_progress(workspace_path: str) -> str:
        """
        Check the current progress of a Mark IV subagent by reading its log file.
        workspace_path: The working directory path returned by delegate_to_subagent.
        Use this when the user asks 'how's my task going?', 'is it done yet?', 'any progress?'.
        """
        try:
            if not workspace_path:
                # Try to find the most recent subagent folder
                base = os.environ.get("FRIDAY_WORKSPACE_DIR", "workspace")
                subagent_dirs = sorted(
                    [d for d in Path(base).glob("subagent_*") if d.is_dir()],
                    key=lambda d: d.stat().st_mtime,
                    reverse=True
                )
                if not subagent_dirs:
                    return "No subagent workspaces found."
                workspace_path = str(subagent_dirs[0])

            log_path = os.path.join(workspace_path, "subagent_log.md")

            if not os.path.exists(log_path):
                return f"No log found at {log_path}. The subagent may still be starting up."

            with open(log_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Return last 3000 chars of the log (most recent activity)
            if len(content) > 3000:
                content = "... [earlier log truncated] ...\n\n" + content[-3000:]

            # Check if completed
            is_done = "-- Task Completed --" in content or "Fatal Subagent Error" in content
            status = "✅ COMPLETED" if "-- Task Completed --" in content else (
                "❌ FAILED" if "Fatal Subagent Error" in content else "⏳ IN PROGRESS"
            )

            return f"Subagent Status: {status}\nWorkspace: {workspace_path}\n\n{content}"
        except Exception as e:
            return f"Error checking subagent progress: {str(e)}"
