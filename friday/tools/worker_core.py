"""
Autonomous Self-Healing Sub-Agent Core (Mark IV)
This script is executed by F.R.I.D.A.Y's subagent delegator.
Supports: coding, research, writing, and auto-detection tasks.
"""
import sys
import os
import httpx
import json
import time
import subprocess
import re
from pathlib import Path

TASK_SYSTEM_PROMPTS = {
    "coding": (
        "You are an autonomous self-healing coding worker. "
        "Write a Python script to solve the objective. "
        "Enclose Python code strictly in ```python ... ``` blocks. "
        "Your code will be immediately executed. If it fails, I'll send you the stderr and you must fix it. "
        "Keep iterating until the code runs successfully."
    ),
    "research": (
        "You are an autonomous research worker. "
        "Your job is to deeply research the given objective, gather information, "
        "and produce a well-structured Markdown report. "
        "Write the final report inside a ```markdown ... ``` block. "
        "Include key findings, sources/references, and a summary."
    ),
    "writing": (
        "You are an autonomous writing worker. "
        "Your job is to produce high-quality written content for the given objective. "
        "Output the final content inside a ```markdown ... ``` block. "
        "Make it complete, professional, and ready to use."
    ),
    "auto": (
        "You are an autonomous general-purpose AI worker. "
        "Analyze the objective and decide the best approach: "
        "- If it requires code, write Python in ```python ... ``` blocks and they will be executed. "
        "- If it requires research or writing, produce a Markdown report in ```markdown ... ``` blocks. "
        "- If it requires both, do both. "
        "Iterate and self-correct until the task is complete."
    ),
}


def main():
    if len(sys.argv) < 3:
        sys.exit("Usage: python3 worker_core.py <objective> <workspace_dir> [task_type]")

    objective = sys.argv[1]
    workspace_dir = sys.argv[2]
    task_type = sys.argv[3] if len(sys.argv) > 3 else "auto"

    # Validate task_type
    if task_type not in TASK_SYSTEM_PROMPTS:
        task_type = "auto"

    api_key = os.environ.get("GOOGLE_API_KEY")
    log_file = os.path.join(workspace_dir, "subagent_log.md")

    with open(log_file, "w", encoding="utf-8") as f:
        f.write(
            f"# Mark IV Autonomous Subagent\n"
            f"**Objective:** {objective}\n"
            f"**Task Type:** {task_type}\n"
            f"**Started:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

    if not api_key:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("**Error:** Cannot start — GOOGLE_API_KEY is not set in environment.\n")
        sys.exit(1)

    model = os.environ.get("GEMINI_LLM_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    max_iterations = int(os.environ.get("MAX_SUBAGENT_ITERATIONS", "5"))
    
    # Allow dynamic override of system prompts via environment variables if needed
    custom_coding_prompt = os.environ.get("SUBAGENT_CODING_PROMPT")
    custom_research_prompt = os.environ.get("SUBAGENT_RESEARCH_PROMPT")
    custom_writing_prompt = os.environ.get("SUBAGENT_WRITING_PROMPT")
    custom_auto_prompt = os.environ.get("SUBAGENT_AUTO_PROMPT")

    if custom_coding_prompt: TASK_SYSTEM_PROMPTS["coding"] = custom_coding_prompt
    if custom_research_prompt: TASK_SYSTEM_PROMPTS["research"] = custom_research_prompt
    if custom_writing_prompt: TASK_SYSTEM_PROMPTS["writing"] = custom_writing_prompt
    if custom_auto_prompt: TASK_SYSTEM_PROMPTS["auto"] = custom_auto_prompt

    system_prompt = TASK_SYSTEM_PROMPTS[task_type]

    conversation_history = [
        {
            "role": "user",
            "parts": [{"text": f"{system_prompt}\n\nObjective: {objective}"}]
        }
    ]

    for attempt in range(1, max_iterations + 1):
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"## Attempt {attempt} — {time.strftime('%H:%M:%S')}\n\n")

        payload = {"contents": conversation_history}

        try:
            response = httpx.post(url, json=payload, timeout=90.0)
            response.raise_for_status()
            data = response.json()

            ai_message = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )

            if not ai_message:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write("> Empty response from AI. Stopping.\n\n-- Task Aborted --\n")
                break

            conversation_history.append(
                {"role": "model", "parts": [{"text": ai_message}]}
            )

            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"**AI Response:**\n\n{ai_message}\n\n")

            # --- Handle Python code blocks ---
            python_blocks = re.findall(r"```python\n(.*?)\n```", ai_message, re.DOTALL)
            if python_blocks:
                code_to_run = python_blocks[0]
                script_path = os.path.join(workspace_dir, f"sandbox_script_v{attempt}.py")

                with open(script_path, "w", encoding="utf-8") as f:
                    f.write(code_to_run)

                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(f"> Executing `sandbox_script_v{attempt}.py`...\n\n")

                timeout = int(os.environ.get("PYTHON_EXEC_TIMEOUT", "120"))
                sandbox_process = subprocess.run(
                    ["python3", script_path],
                    cwd=workspace_dir,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )

                if sandbox_process.returncode == 0:
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(
                            f"**✅ Execution Successful!**\n\n"
                            f"```\n{sandbox_process.stdout}\n```\n\n"
                            f"-- Task Completed --\n"
                        )
                    break
                else:
                    error_msg = (
                        f"Exit code: {sandbox_process.returncode}\n"
                        f"STDOUT: {sandbox_process.stdout}\n"
                        f"STDERR: {sandbox_process.stderr}"
                    )
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(
                            f"**❌ Execution Failed.** Feeding error back to matrix.\n\n"
                            f"```\n{error_msg}\n```\n\n"
                        )
                    conversation_history.append({
                        "role": "user",
                        "parts": [{"text": (
                            f"Your script failed with the following error:\n\n{error_msg}\n\n"
                            f"Please analyze the error, fix the bug, and rewrite the complete corrected script."
                        )}]
                    })
                continue

            # --- Handle Markdown report blocks ---
            md_blocks = re.findall(r"```markdown\n(.*?)\n```", ai_message, re.DOTALL)
            if md_blocks:
                report_content = md_blocks[0]
                report_path = os.path.join(workspace_dir, "report.md")
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(report_content)
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(f"**✅ Report written to `report.md`**\n\n-- Task Completed --\n")
                break

            # --- No code blocks found: check if it's a final answer ---
            if any(marker in ai_message.lower() for marker in [
                "task complete", "finished", "done", "here is", "here's the", "summary:"
            ]):
                # Save the response as a text output
                output_path = os.path.join(workspace_dir, "output.md")
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(f"# Task Output\n\n{ai_message}")
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(f"**✅ Task answered directly. Saved to `output.md`**\n\n-- Task Completed --\n")
                break
            else:
                # Ask AI to continue or wrap up
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write("> No code or markdown block found. Asking AI to proceed...\n\n")
                conversation_history.append({
                    "role": "user",
                    "parts": [{"text": "Please continue and complete the task. Provide your output in the appropriate code block format."}]
                })

        except subprocess.TimeoutExpired:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"**⏰ Script timed out after {timeout}s.** Asking AI to optimize...\n\n")
            conversation_history.append({
                "role": "user",
                "parts": [{"text": f"Your script timed out after {timeout} seconds. Please rewrite it to be more efficient or break it into smaller steps."}]
            })

        except Exception as e:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"**⚠️ Fatal Subagent Error:** {str(e)}\n\n")
            break

    # Final status
    with open(log_file, "r", encoding="utf-8") as f:
        final_content = f.read()

    if "-- Task Completed --" not in final_content and "-- Task Aborted --" not in final_content:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n-- Max iterations ({max_iterations}) reached. Review output above. --\n")


if __name__ == "__main__":
    main()
