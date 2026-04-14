"""
Subagent delegation — allows the real-time voice agent to offload massive coding or reasoning tasks to an autonomous background worker.
"""

import json
import os
import uuid
import subprocess
from pathlib import Path

# Provide a lightweight self-contained worker script snippet that the system will run in isolation.
BACKGROUND_WORKER_CODE = """
import sys
import os
import httpx
import json
import time

objective = sys.argv[1]
workspace_dir = sys.argv[2]
api_key = os.environ.get("GOOGLE_API_KEY")

log_file = os.path.join(workspace_dir, "subagent_log.md")

with open(log_file, "w") as f:
    f.write(f"# Subagent Task Log\\n**Objective:** {objective}\\n\\n")

if not api_key:
    with open(log_file, "a") as f:
        f.write("Error: Local subagent cannot start without GOOGLE_API_KEY.\\n")
    sys.exit(1)

# Very simple autonomous coding loop via REST API
url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"

prompt = f\"\"\"
You are an autonomous background coding worker for F.R.I.D.A.Y.
Your objective is: {objective}

You cannot ask the user questions. You must try to write a python script that accomplishes the objective, 
or output the text required. 

Provide your final response as a python script or final report.
Wrap any code in ```python blocks.
\"\"\"

payload = {
    "contents": [{"parts": [{"text": prompt}]}]
}

try:
    response = httpx.post(url, json=payload, timeout=60.0)
    response.raise_for_status()
    data = response.json()
    
    # Extract the text
    text_result = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
    
    with open(log_file, "a") as f:
        f.write(f"## Final Result\\n\\n{text_result}\\n\\n-- Task Completed --")
        
except Exception as e:
    with open(log_file, "a") as f:
        f.write(f"## Error\\n\\nThe subagent encountered a fatal error:\\n{str(e)}\\n")
    sys.exit(1)
"""

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
            workspace_dir = os.path.abspath(f"workspace/subagent_{task_id}")
            os.makedirs(workspace_dir, exist_ok=True)
            
            worker_script_path = os.path.join(workspace_dir, "worker.py")
            with open(worker_script_path, "w") as f:
                f.write(BACKGROUND_WORKER_CODE)
                
            # Spawn it entirely detached
            subprocess.Popen(
                ["python3", worker_script_path, objective, workspace_dir],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=workspace_dir
            )
            
            return f"Subagent delegated successfully! Background worker started in {workspace_dir}. It will log its progress there. Tell the user it's on it."
        except Exception as e:
            return f"Failed to delegate to subagent: {str(e)}"
