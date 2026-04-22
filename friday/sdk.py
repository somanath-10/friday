"""
F.R.I.D.A.Y. SDK
This module is intended to be used by autonomous subagents to easily interface with
the host system, the web, and F.R.I.D.A.Y.'s custom tool sets.
"""

import subprocess
import platform
import os

from friday.subprocess_utils import run_powershell

OS = platform.system()

def execute_shell(command: str, timeout: int = 60) -> str:
    """Execute a shell command on the host OS."""
    try:
        if OS == "Windows":
            result = run_powershell(command, timeout=timeout, no_profile=False, force_utf8=False)
        else:
            result = subprocess.run(command, shell=True, executable="/bin/bash" if os.path.exists("/bin/bash") else None, capture_output=True, text=True, timeout=timeout)
        output = ""
        if result.stdout:
            output += result.stdout.strip() + "\n"
        if result.stderr:
            output += "STDERR: " + result.stderr.strip() + "\n"
        return output if output.strip() else f"Command succeeded (exit code {result.returncode})"
    except Exception as e:
        return f"Shell execution error: {e}"

def search_web(query: str) -> str:
    """Search the web for a query."""
    # We can utilize duckduckgo via shell as a simple fallback, or use the DDG html search.
    # To keep it completely dependency free for the sandbox, let's use python's urllib
    import urllib.request
    import urllib.parse
    import re
    try:
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote_plus(query)}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=10).read().decode('utf-8')
        
        blocks = re.findall(r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
        out = []
        for url_raw, title, snippet in blocks[:5]:
            t = re.sub('<[^>]+>', '', title).strip()
            s = re.sub('<[^>]+>', '', snippet).strip()
            out.append(f"- {t}\n  {s}")
        return "\n".join(out) if out else "No web results found."
    except Exception as e:
        return f"Web search error: {str(e)}"

def spawn_subagent(objective: str, task_type: str = "auto") -> str:
    """
    Delegate a sub-task to another autonomous agent. 
    This allows parallel or hierarchical execution.
    """
    try:
        import sys
        # Core script is one level down in tools
        sdk_dir = os.path.dirname(os.path.abspath(__file__))
        core_script = os.path.join(sdk_dir, "tools", "worker_core.py")
        
        import uuid
        task_id = str(uuid.uuid4())[:6]
        
        workspace_dir = os.environ.get("FRIDAY_WORKSPACE_DIR", os.path.join(sdk_dir, "..", "workspace"))
        task_workspace = os.path.join(workspace_dir, f"subagent_{task_id}")
        os.makedirs(task_workspace, exist_ok=True)
        
        # Fire and forget
        subprocess.Popen(
            [sys.executable, core_script, objective, task_workspace, task_type],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=task_workspace,
            env={**os.environ}
        )
        return f"Spawned new subagent. Workspace: {task_workspace}"
    except Exception as e:
        return f"Error spawning subagent: {e}"

def read_file(filepath: str) -> str:
    """Read a file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

def write_file(filepath: str, content: str) -> str:
    """Write to a file."""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    return "File written successfully."
