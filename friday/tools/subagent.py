"""
Subagent delegation — allows the real-time voice agent to offload massive coding or reasoning tasks to an autonomous background worker.
"""

import json
import os
import uuid
import subprocess
from pathlib import Path

def register(mcp):
    @mcp.tool()
    def delegate_to_subagent(objective: str) -> str:
        """
        Dumps a massive, complex objective into a background autonomous worker.
        USE THIS INSTEAD OF DOING IT YOURSELF IF:
        - The user asks you to write a huge app, framework, or full project.
        - The user gives you a 5-minute long brain dump of instructions.
        - The task requires intense iteration.
        """
        try:
            task_id = str(uuid.uuid4())[:8]
            base_workspace = os.environ.get("FRIDAY_WORKSPACE_DIR", "workspace")
            workspace_dir = os.path.abspath(os.path.join(base_workspace, f"subagent_{task_id}"))
            os.makedirs(workspace_dir, exist_ok=True)
            
            # The core worker is situated alongside this tool
            core_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker_core.py")
                
            # Spawn it entirely detached
            subprocess.Popen(
                ["python3", core_script, objective, workspace_dir],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=workspace_dir
            )
            
            return f"Mark IV Subagent dispatched successfully! Background worker started in {workspace_dir}. It will auto-correct its own bugs and log its progress there. Tell the user it's on it."
        except Exception as e:
            return f"Failed to delegate to Mark IV subagent: {str(e)}"
