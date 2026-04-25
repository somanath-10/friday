"""
Autonomous Self-Healing Sub-Agent Core (Mark V)
This script is executed by F.R.I.D.A.Y's subagent delegator.
Features an Agent-Computer Interface (ACI) loop mimicking SWE-agent or Devin.
"""
import sys
import os
import httpx
import time
import subprocess
import re
import base64
from io import BytesIO
from typing import Any
try:
    from PIL import ImageGrab
except ImportError:
    ImageGrab = None

# Devin/SWE-agent style Agent-Computer Interface system prompt
ACI_PROMPT_ADDENDUM = """
You are an autonomous AI Agent embedded in a persistent environment.
To interact with the system and fix bugs or run tasks, use the following XML-like commands.
You can ONLY use one command per turn. I will execute the command and return the result.
Iterate until the objective is resolved.

COMMANDS:
1. Shell Execution:
<shell>
npm run test
</shell>

2. Python Scratchpad:
<python>
import os
print(os.listdir("."))
</python>

3. Read File:
<read_file>path/to/file.py</read_file>

4. Write File (Overwrites entirely, use carefully):
<write_file path="path/to/file.py">
# new contents
</write_file>

5. Inspect Screen (Take a picture of the desktop):
<screenshot>
I want to see what is currently open on my screen.
</screenshot>

6. Task Complete:
<task_complete>
Summary of what was accomplished and reasoning.
</task_complete>

If a command fails, read the error output and try an alternative.
Avoid repeating the exact same failed command.
"""

TASK_SYSTEM_PROMPTS = {
    "coding": (
        "You are an autonomous self-healing coding worker using the Agent-Computer Interface (ACI). "
        "Solve the objective safely and test your code.\n" + ACI_PROMPT_ADDENDUM
    ),
    "research": (
        "You are an autonomous research worker. "
        "Use the ACI to crawl, execute scripts, and gather information. "
        "Summarize the findings dynamically.\n" + ACI_PROMPT_ADDENDUM
    ),
    "writing": (
        "You are an autonomous writing worker. "
        "Use ACI file tools to write docs and draft reports.\n" + ACI_PROMPT_ADDENDUM
    ),
    "auto": (
        "You are an autonomous general-purpose AI worker using the ACI. "
        "Analyze the objective, run terminal commands, write/modify scripts, and debug them. "
        "Iterate and self-correct until the task is complete.\n" + ACI_PROMPT_ADDENDUM
    ),
}

def _python_command() -> str:
    return sys.executable or os.environ.get("PYTHON", "python")


def _text_from_parts(parts: list[dict[str, Any]]) -> str:
    text_parts: list[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            text_parts.append(text)
        elif part.get("inlineData"):
            text_parts.append("[image attachment omitted]")
    return "\n".join(text_parts).strip()


def _openai_messages(conversation_history: list[dict[str, Any]]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for turn in conversation_history:
        role = "assistant" if turn.get("role") == "model" else "user"
        content = _text_from_parts(turn.get("parts", []))
        if content:
            messages.append({"role": role, "content": content})
    return messages


def _extract_gemini_text(data: dict[str, Any]) -> str:
    return (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
    )


def _post_with_retries(
    url: str,
    *,
    json_payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout: float = 90.0,
    max_attempts: int = 3,
) -> dict[str, Any]:
    last_error: Exception | None = None
    retriable_statuses = {429, 500, 502, 503, 504}

    for attempt in range(1, max_attempts + 1):
        try:
            response = httpx.post(url, json=json_payload, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            last_error = exc
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code not in retriable_statuses or attempt == max_attempts:
                raise
            retry_after = exc.response.headers.get("Retry-After", "") if exc.response is not None else ""
            try:
                delay = max(1.0, float(retry_after))
            except ValueError:
                delay = float(min(2 ** (attempt - 1), 8))
            time.sleep(delay)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            last_error = exc
            if attempt == max_attempts:
                raise
            time.sleep(float(min(2 ** (attempt - 1), 8)))

    if last_error is not None:
        raise last_error
    raise RuntimeError("No response received from AI provider.")


def _generate_ai_response(conversation_history: list[dict[str, Any]]) -> tuple[str, str]:
    google_api_key = os.environ.get("GOOGLE_API_KEY")
    openai_api_key = os.environ.get("OPENAI_API_KEY")

    gemini_error: Exception | None = None
    if google_api_key:
        model = os.environ.get("GEMINI_LLM_MODEL", "gemini-2.5-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={google_api_key}"
        payload = {"contents": conversation_history}
        try:
            data = _post_with_retries(url, json_payload=payload, timeout=90.0)
            return _extract_gemini_text(data), "gemini"
        except Exception as exc:
            gemini_error = exc

    if openai_api_key:
        messages = _openai_messages(conversation_history)
        if messages:
            model = os.environ.get("OPENAI_LLM_MODEL", "gpt-4o")
            payload = {"model": model, "messages": messages}
            headers = {"Authorization": f"Bearer {openai_api_key}", "Content-Type": "application/json"}
            data = _post_with_retries(
                "https://api.openai.com/v1/chat/completions",
                json_payload=payload,
                headers=headers,
                timeout=90.0,
            )
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return text.strip(), "openai"

    if gemini_error is not None:
        raise gemini_error
    raise RuntimeError("No supported AI provider is configured. Set GOOGLE_API_KEY or OPENAI_API_KEY.")


def _resolve_workspace_path(workspace_dir: str, path: str) -> str:
    workspace_root = os.path.abspath(workspace_dir)
    candidate = os.path.abspath(os.path.join(workspace_root, path))
    try:
        if os.path.commonpath([workspace_root, candidate]) != workspace_root:
            raise ValueError
    except ValueError:
        raise ValueError("Access denied. Cannot access outside workspace.") from None
    return candidate


def handle_aci_command(ai_message: str, workspace_dir: str, env: dict) -> tuple[bool, str, str | None]:
    """Parses ai_message for ACI tags and executes them. Returns (is_complete, feedback_string, optional_base64_image)."""

    # 1. Check for complete
    complete_match = re.search(r"<task_complete>(.*?)</task_complete>", ai_message, re.DOTALL)
    if complete_match:
        return True, "Task marked as complete by AI.", None

    # 2. Check for shell
    shell_match = re.search(r"<shell>\n?(.*?)\n?</shell>", ai_message, re.DOTALL)
    if shell_match:
        cmd = shell_match.group(1).strip()
        try:
            result = subprocess.run(
                cmd, shell=True, cwd=workspace_dir, capture_output=True, text=True, timeout=120, env=env
            )
            out = result.stdout[:2000] + ("\n...[truncated]" if len(result.stdout) > 2000 else "")
            err = result.stderr[:2000] + ("\n...[truncated]" if len(result.stderr) > 2000 else "")
            return False, f"Exit code: {result.returncode}\nSTDOUT:\n{out}\nSTDERR:\n{err}", None
        except subprocess.TimeoutExpired:
            return False, "Error: Command timed out after 120s.", None
        except Exception as e:
            return False, f"Error: {e}", None

    # 3. Check for python
    python_match = re.search(r"<python>\n?(.*?)\n?</python>", ai_message, re.DOTALL)
    if python_match:
        code = python_match.group(1).strip()
        script_path = os.path.join(workspace_dir, "scratchpad.py")
        try:
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(code)
            result = subprocess.run(
                [_python_command(), script_path], cwd=workspace_dir, capture_output=True, text=True, timeout=120, env=env
            )
            out = result.stdout[:2000]
            err = result.stderr[:2000]
            return False, f"Exit code: {result.returncode}\nSTDOUT:\n{out}\nSTDERR:\n{err}", None
        except Exception as e:
            return False, f"Error: {e}", None

    # 4. Check for read_file
    read_match = re.search(r"<read_file>\n?(.*?)\n?</read_file>", ai_message, re.DOTALL)
    if read_match:
        path = read_match.group(1).strip()
        try:
            full_path = _resolve_workspace_path(workspace_dir, path)
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
                return False, f"File Content ({path}):\n{content[:5000]}", None
        except ValueError as e:
            return False, f"Error: {e}", None
        except Exception as e:
            return False, f"Error reading file {path}: {e}", None

    # 5. Check for write_file
    write_match = re.search(r"<write_file path=\"(.*?)\">\n?(.*?)\n?</write_file>", ai_message, re.DOTALL)
    if write_match:
        path = write_match.group(1).strip()
        content = write_match.group(2)
        try:
            full_path = _resolve_workspace_path(workspace_dir, path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return False, f"Successfully wrote to {path}.", None
        except ValueError as e:
            return False, f"Error: {e}", None
        except Exception as e:
            return False, f"Error writing file {path}: {e}", None

    # 6. Check for screenshot
    screenshot_match = re.search(r"<screenshot>\n?(.*?)\n?</screenshot>", ai_message, re.DOTALL)
    if screenshot_match:
        if not ImageGrab:
            return False, "Error: PIL is not installed. Cannot take screenshot.", None
        try:
            img = ImageGrab.grab(all_screens=True)
            img.thumbnail((1920, 1080))
            if getattr(img, "mode", "") not in {"RGB", "L"}:
                img = img.convert("RGB")
            buffered = BytesIO()
            img.save(buffered, format="JPEG", quality=80)
            img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            return False, "Screenshot taken successfully. Look at the image provided in this turn carefully.", img_b64
        except Exception as e:
            return False, f"Error capturing screenshot: {e}", None

    # Fallback if no tags
    return False, "Error: No valid ACI command found. Please use <shell>, <python>, <read_file>, <write_file>, <screenshot>, or <task_complete>.", None


def main():
    if len(sys.argv) < 3:
        sys.exit("Usage: python worker_core.py <objective> <workspace_dir> [task_type]")

    objective = sys.argv[1]
    workspace_dir = sys.argv[2]
    task_type = sys.argv[3] if len(sys.argv) > 3 else "auto"

    if task_type not in TASK_SYSTEM_PROMPTS:
        task_type = "auto"

    api_key = os.environ.get("GOOGLE_API_KEY")
    log_file = os.path.join(workspace_dir, "subagent_log.md")

    with open(log_file, "w", encoding="utf-8") as f:
        f.write(
            f"# Mark V Autonomous Subagent (ACI Loop)\n"
            f"**Objective:** {objective}\n"
            f"**Task Type:** {task_type}\n"
            f"**Started:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        )

    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key and not openai_api_key:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("**Error:** Cannot start — neither GOOGLE_API_KEY nor OPENAI_API_KEY is set in environment.\n")
        sys.exit(1)
    if not api_key and openai_api_key:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write("**Info:** GOOGLE_API_KEY is missing, so Mark V will use OpenAI fallback.\n")

    max_iterations = int(os.environ.get("MAX_SUBAGENT_ITERATIONS", "25"))  # Increased for ACI loops
    system_prompt = TASK_SYSTEM_PROMPTS[task_type]

    conversation_history = [
        {
            "role": "user",
            "parts": [{"text": f"{system_prompt}\n\nObjective: {objective}"}]
        }
    ]

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{project_root}{os.pathsep}{env.get('PYTHONPATH', '')}"

    for attempt in range(1, max_iterations + 1):
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"## Iteration {attempt} — {time.strftime('%H:%M:%S')}\n\n")

        try:
            ai_message, provider_name = _generate_ai_response(conversation_history)

            if not ai_message:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write("> Empty response from AI. Stopping.\n\n-- Task Aborted --\n")
                break

            conversation_history.append(
                {"role": "model", "parts": [{"text": ai_message}]}
            )

            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"**AI Provider:** {provider_name}\n\n")
                f.write(f"**AI Reasoning:**\n\n```\n{ai_message[:800]}{'...' if len(ai_message) > 800 else ''}\n```\n\n")

            is_complete, feedback, image_b64 = handle_aci_command(ai_message, workspace_dir, env)

            with open(log_file, "a", encoding="utf-8") as f:
                if image_b64:
                    f.write(f"**System Feedback:**\n\n```\n{feedback}\n```\n\n*[System attached an image payload (screenshot)]*\n\n")
                else:
                    f.write(f"**System Feedback:**\n\n```\n{feedback[:500]}{'...' if len(feedback) > 500 else ''}\n```\n\n")

            if is_complete:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write("-- Task Completed --\n")

                # Write final output
                output_path = os.path.join(workspace_dir, "output.md")
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(f"# Final Mark V Output\n\n{ai_message}")
                break

            user_turn_parts = [{"text": feedback}]
            if image_b64:
                user_turn_parts.append({
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": image_b64
                    }
                })

            conversation_history.append({
                "role": "user",
                "parts": user_turn_parts
            })

        except Exception as e:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"**⚠️ Fatal ACI Error:** {str(e)}\n\n")
            break

    # Final status check
    with open(log_file, "r", encoding="utf-8") as f:
        final_content = f.read()

    if "-- Task Completed --" not in final_content and "-- Task Aborted --" not in final_content:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"\n-- Max iterations ({max_iterations}) reached. Task aborted. --\n")


if __name__ == "__main__":
    main()
