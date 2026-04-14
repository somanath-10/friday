"""
Autonomous Self-Healing Sub-Agent Core (Mark IV)
This script is executed by F.R.I.D.A.Y's subagent delegator.
"""
import sys
import os
import httpx
import json
import time
import subprocess
import re

def main():
    if len(sys.argv) < 3:
        sys.exit("Usage: python3 worker_core.py <objective> <workspace_dir>")
        
    objective = sys.argv[1]
    workspace_dir = sys.argv[2]
    api_key = os.environ.get("GOOGLE_API_KEY")

    log_file = os.path.join(workspace_dir, "subagent_log.md")
    
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(f"# Mark IV Autonomous Subagent\n**Objective:** {objective}\n\n")

    if not api_key:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("Error: Local subagent cannot start without GOOGLE_API_KEY.\n")
        sys.exit(1)

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{os.environ.get('GEMINI_LLM_MODEL', 'gemini-2.5-flash')}:generateContent?key={api_key}"
    
    conversation_history = [
        {"role": "user", "parts": [{"text": f"Objective: {objective}\n\nYou are an autonomous self-healing coding worker. Write a Python script to solve this. Enclose your python code strictly in ```python ... ``` blocks. Your code will be immediately executed. If it fails, I will send you the stderr, and you must fix it."}]}
    ]

    max_iterations = int(os.environ.get("MAX_SUBAGENT_ITERATIONS", 5))
    for attempt in range(1, max_iterations + 1):
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"## Attempt {attempt}\n")
            
        payload = {"contents": conversation_history}
        try:
            response = httpx.post(url, json=payload, timeout=60.0)
            response.raise_for_status()
            data = response.json()
            
            ai_message = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            
            # Append AI response to history
            conversation_history.append({"role": "model", "parts": [{"text": ai_message}]})

            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"Generated Code:\n\n{ai_message}\n\n")

            # Extract python code
            code_blocks = re.findall(r"```python\n(.*?)\n```", ai_message, re.DOTALL)
            if not code_blocks:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write("> No python code blocks found. Assuming completion or non-coding task.\n\n-- Task Completed --")
                break
                
            code_to_run = code_blocks[0]
            script_path = os.path.join(workspace_dir, f"sandbox_script_v{attempt}.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(code_to_run)
                
            # Execute it safely
            with open(log_file, "a", encoding="utf-8") as f:
                f.write("> Executing sandbox script...\n")
                
            sandbox_process = subprocess.run(
                ["python3", script_path],
                cwd=workspace_dir,
                capture_output=True,
                text=True,
                timeout=30.0
            )
            
            if sandbox_process.returncode == 0:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(f"**Execution Success!**\nOutput:\n```\n{sandbox_process.stdout}\n```\n\n-- Task Completed --\n")
                break
            else:
                error_msg = f"Execution failed with return code {sandbox_process.returncode}.\nSTDOUT: {sandbox_process.stdout}\nSTDERR: {sandbox_process.stderr}"
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(f"**Execution Failed.** Feeding error back to matrix.\n```\n{error_msg}\n```\n\n")
                
                # Feedback loop
                conversation_history.append({"role": "user", "parts": [{"text": f"Your script failed.\n\n{error_msg}\n\nPlease fix the bug and rewrite the complete script."}]})
                
        except Exception as e:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"**Fatal Subagent Error:** {str(e)}\n")
            break

if __name__ == "__main__":
    main()
