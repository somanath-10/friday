"""
Utility tools — text processing, formatting, code execution, file I/O, and process management.
"""

import json
import subprocess
import tempfile
import os
import sys
import base64
import uuid

from friday.core.permissions import (
    authorize_tool_call,
    format_permission_response,
    record_tool_result,
)
from friday.path_utils import resolve_user_path, workspace_dir
from friday.tools.error_handling import safe_tool

BACKGROUND_TASKS = {}

# Configurable timeouts (can override via .env)
PYTHON_EXEC_TIMEOUT = int(os.environ.get("PYTHON_EXEC_TIMEOUT", "120"))
SHELL_EXEC_TIMEOUT  = int(os.environ.get("SHELL_EXEC_TIMEOUT",  "60"))


def register(mcp):

    @mcp.tool()
    def format_json(data: str) -> str:
        """Pretty-print a JSON string."""
        try:
            parsed = json.loads(data)
            return json.dumps(parsed, indent=2)
        except json.JSONDecodeError as e:
            return f"Invalid JSON: {e}"

    @mcp.tool()
    def word_count(text: str) -> dict:
        """Count words, characters, and lines in a block of text."""
        lines = text.splitlines()
        words = text.split()
        return {
            "characters": len(text),
            "words": len(words),
            "lines": len(lines),
        }

    @mcp.tool()
    def execute_python_code(code: str, timeout: int = 0) -> str:
        """
        Execute Python code and return the output.
        Supports any Python code — data analysis, calculations, file processing, web requests, etc.
        timeout: Optional override in seconds (default uses PYTHON_EXEC_TIMEOUT env var, default 120s).
        Use this for: calculations, data processing, generating files, running algorithms, etc.
        """
        effective_timeout = timeout if timeout > 0 else PYTHON_EXEC_TIMEOUT
        try:
            # Write code to a temp file with proper workspace context
            workspace = workspace_dir()

            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.py', delete=False,
                dir=workspace, prefix='friday_exec_'
            ) as f:
                # Inject workspace path so scripts can create files there easily
                preamble = (
                    f"import os, sys\n"
                    f"WORKSPACE = {repr(str(workspace))}\n"
                    f"os.makedirs(WORKSPACE, exist_ok=True)\n\n"
                )
                f.write(preamble + code)
                temp_file = f.name

            result = subprocess.run(
                [sys.executable, temp_file],
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                cwd=workspace,
            )

            os.unlink(temp_file)

            if result.returncode == 0:
                output = result.stdout.strip()
                stderr = result.stderr.strip()
                if stderr and "warning" in stderr.lower():
                    output += f"\nWarnings: {stderr}"
                return output if output else "Code executed successfully with no output."
            else:
                return f"Code execution error (exit {result.returncode}):\n{result.stderr.strip()}"

        except subprocess.TimeoutExpired:
            try:
                os.unlink(temp_file)
            except Exception:
                pass
            return f"Error: Code execution timed out after {effective_timeout}s. Consider using delegate_to_subagent for very long tasks."
        except Exception as e:
            return f"Error executing code: {str(e)}"

    @mcp.tool()
    @safe_tool
    def get_file_contents(file_path: str) -> str:
        """
        Read and return the full contents of any text file.
        Use this to read source code, config files, notes, logs, or any text file the user mentions.
        """
        try:
            resolved_path = resolve_user_path(file_path)
            with open(resolved_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            if len(content) > 10000:
                return content[:10000] + f"\n\n... [File truncated. Total size: {len(content)} chars] ..."
            return content
        except FileNotFoundError:
            return f"File not found: {resolve_user_path(file_path)}"
        except Exception:
            raise

    @mcp.tool()
    @safe_tool
    def write_file(file_path: str, content: str) -> str:
        """
        Write content to a file at any path. Creates parent directories if needed.
        Use this to save code, notes, configurations, reports, or any content to disk.
        """
        decision, approval_request = authorize_tool_call(
            "write_file",
            {"file_path": file_path},
            working_directory=str(workspace_dir()),
        )
        if decision.decision != "allow":
            return format_permission_response(decision, approval_request=approval_request)

        try:
            resolved_path = resolve_user_path(file_path)
            directory = os.path.dirname(resolved_path)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)

            with open(resolved_path, 'w', encoding='utf-8') as f:
                f.write(content)
            size_kb = len(content.encode('utf-8')) / 1024
            record_tool_result(
                "write_file",
                decision,
                result="succeeded",
                path=str(resolved_path),
                metadata={**decision.metadata, "size_bytes": len(content.encode('utf-8'))},
            )
            return f"Written {size_kb:.2f} KB to: {resolved_path}"
        except Exception as exc:
            record_tool_result(
                "write_file",
                decision,
                result=f"error:{exc.__class__.__name__}",
                path=file_path,
            )
            raise

    @mcp.tool()
    def install_package(package_name: str) -> str:
        """
        Install a Python package using pip (or uv pip). Use this before running code that requires
        a third-party library.
        """
        decision, approval_request = authorize_tool_call(
            "install_package",
            {"package_name": package_name},
            working_directory=str(workspace_dir()),
        )
        if decision.decision != "allow":
            return format_permission_response(decision, approval_request=approval_request)

        try:
            # Prefer uv pip install into the current venv, then fall back to pip
            for cmd in [
                ['uv', 'pip', 'install', '--python', sys.executable, package_name],
                [sys.executable, '-m', 'pip', 'install', package_name],
            ]:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=120
                )
                if result.returncode == 0:
                    record_tool_result(
                        "install_package",
                        decision,
                        result="succeeded",
                        command=" ".join(cmd),
                        metadata={**decision.metadata, "package_name": package_name},
                    )
                    return f"Successfully installed into .venv: {package_name}"

            record_tool_result(
                "install_package",
                decision,
                result=f"failed_exit_{result.returncode}",
                command=" ".join(cmd),
                metadata={**decision.metadata, "package_name": package_name},
            )
            return f"Failed to install {package_name}: {result.stderr.strip()}"
        except subprocess.TimeoutExpired:
            record_tool_result(
                "install_package",
                decision,
                result="timeout",
                metadata={**decision.metadata, "package_name": package_name},
            )
            return f"Installation of {package_name} timed out (120s)."
        except Exception as e:
            record_tool_result(
                "install_package",
                decision,
                result=f"error:{e.__class__.__name__}",
                metadata={**decision.metadata, "package_name": package_name},
            )
            return f"Error installing package: {str(e)}"

    @mcp.tool()
    def run_shell_command(command: str, timeout: int = 0) -> str:
        """
        Run any shell command and return its output.
        timeout: Optional override in seconds (default uses SHELL_EXEC_TIMEOUT env var, default 60s).
        Use this for git commands, file operations, system admin tasks, running scripts, etc.
        IMPORTANT: Runs in the workspace directory by default.
        """
        effective_timeout = timeout if timeout > 0 else SHELL_EXEC_TIMEOUT
        workspace = workspace_dir()
        decision, approval_request = authorize_tool_call(
            "run_shell_command",
            {"command": command},
            working_directory=str(workspace),
        )
        if decision.decision != "allow":
            return format_permission_response(decision, approval_request=approval_request)

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                cwd=workspace,
            )

            result_status = "succeeded" if result.returncode == 0 else f"failed_exit_{result.returncode}"
            record_tool_result(
                "run_shell_command",
                decision,
                result=result_status,
                command=command,
                metadata={
                    **decision.metadata,
                    "exit_code": result.returncode,
                    "working_directory": str(workspace),
                },
            )
            if result.returncode == 0:
                output = result.stdout.strip()
                if result.stderr.strip():
                    output += f"\nStderr: {result.stderr.strip()}"
                return output if output else "Command executed successfully with no output."
            else:
                return (
                    f"Command failed (exit {result.returncode}):\n"
                    f"Stdout: {result.stdout.strip()}\n"
                    f"Stderr: {result.stderr.strip()}"
                )
        except subprocess.TimeoutExpired:
            record_tool_result(
                "run_shell_command",
                decision,
                result="timeout",
                command=command,
                metadata={**decision.metadata, "working_directory": str(workspace)},
            )
            return f"Error: Command timed out after {effective_timeout}s."
        except Exception as e:
            record_tool_result(
                "run_shell_command",
                decision,
                result=f"error:{e.__class__.__name__}",
                command=command,
                metadata={**decision.metadata, "working_directory": str(workspace)},
            )
            return f"Error running command: {str(e)}"

    @mcp.tool()
    def encode_base64(data: str) -> str:
        """Encode a string to base64."""
        try:
            return base64.b64encode(data.encode('utf-8')).decode('utf-8')
        except Exception as e:
            return f"Error encoding to base64: {str(e)}"

    @mcp.tool()
    def decode_base64(data: str) -> str:
        """Decode a base64 string."""
        try:
            return base64.b64decode(data).decode('utf-8')
        except Exception as e:
            return f"Error decoding from base64: {str(e)}"

    @mcp.tool()
    def start_background_process(command: str) -> str:
        """
        Start a long-running shell command in the background. Returns a task ID.
        Use this to kick off slow processes without blocking (e.g., a dev server, a build script).
        """
        try:
            task_id = str(uuid.uuid4())[:8]
            workspace = workspace_dir()

            log_path = os.path.join(workspace, f"bg_task_{task_id}.log")
            log_f = open(log_path, "w")

            process = subprocess.Popen(
                command,
                shell=True,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=workspace,
            )
            BACKGROUND_TASKS[task_id] = {"process": process, "log": log_path, "command": command}
            return f"Background task started. ID: {task_id}\nLog: {log_path}"
        except Exception as e:
            return f"Failed to start background task: {str(e)}"

    @mcp.tool()
    def check_process_status(task_id: str) -> str:
        """
        Check the status and output of a background process started via start_background_process.
        Returns current output and whether the process is still running.
        """
        if task_id not in BACKGROUND_TASKS:
            return f"No background task found with ID: {task_id}"

        entry = BACKGROUND_TASKS[task_id]
        process = entry["process"]
        log_path = entry.get("log", "")
        retcode = process.poll()

        log_content = ""
        if log_path and os.path.exists(log_path):
            with open(log_path, "r") as f:
                log_content = f.read()[-3000:]  # Last 3000 chars

        if retcode is None:
            return f"Task {task_id} is RUNNING.\nRecent output:\n{log_content}"

        BACKGROUND_TASKS.pop(task_id, None)
        return f"Task {task_id} COMPLETED (exit code {retcode}).\nOutput:\n{log_content}"

    @mcp.tool()
    def read_file_snippet(file_path: str, start_line: int, end_line: int) -> str:
        """
        Read a specific range of lines from a file (1-indexed).
        Use this to inspect specific sections of large files without reading the whole thing.
        """
        try:
            resolved_path = resolve_user_path(file_path)
            with open(resolved_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()

            start_line = max(1, start_line)
            end_line = min(len(lines), end_line)
            snippet = "".join(lines[start_line - 1:end_line])
            return f"--- {resolved_path} (Lines {start_line}-{end_line}) ---\n{snippet}"
        except Exception as e:
            return f"Error reading snippet: {str(e)}"

    @mcp.tool()
    def list_directory_tree(path: str, max_depth: int = 2) -> str:
        """
        List the directory structure to a given depth.
        Useful for understanding project layouts or navigating the filesystem.
        """
        try:
            resolved_path = resolve_user_path(path)
            if not os.path.exists(resolved_path):
                return f"Path does not exist: {resolved_path}"

            tree_str = []
            start_depth = str(resolved_path).rstrip(os.sep).count(os.sep)

            for root, dirs, files in os.walk(resolved_path):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                curr_depth = root.rstrip(os.sep).count(os.sep)
                depth = curr_depth - start_depth

                if depth > max_depth:
                    continue

                indent = '  ' * depth
                tree_str.append(f"{indent}{os.path.basename(root)}/")
                sub_indent = '  ' * (depth + 1)
                for fn in files:
                    if not fn.startswith('.'):
                        tree_str.append(f"{sub_indent}{fn}")

            return "\n".join(tree_str)
        except Exception as e:
            return f"Error listing directory: {str(e)}"

    @mcp.tool()
    def search_in_files(directory: str, keyword: str) -> str:
        """
        Search for a keyword in all text files within a directory.
        Use this to find where something is used in a codebase or document collection.
        """
        try:
            resolved_directory = resolve_user_path(directory)
            if not os.path.exists(resolved_directory):
                return f"Directory does not exist: {resolved_directory}"

            results = []
            for root, dirs, files in os.walk(resolved_directory):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                for file_name in files:
                    if file_name.startswith('.'):
                        continue
                    file_path = os.path.join(root, file_name)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            for idx, line in enumerate(f):
                                if keyword in line:
                                    results.append(f"{file_path}:{idx+1}: {line.strip()}")
                                    if len(results) > 50:
                                        results.append("... [More results truncated] ...")
                                        return "\n".join(results)
                    except (UnicodeDecodeError, PermissionError):
                        pass

            if not results:
                return f"'{keyword}' not found in {resolved_directory}."
            return "\n".join(results)
        except Exception as e:
            return f"Error searching files: {str(e)}"
    @mcp.tool()
    def profile_dataset(file_path: str) -> str:
        """
        Quickly profile a CSV or JSON dataset without loading it into the LLM context.
        Returns headers, row count, and sample data.
        """
        try:
            if not file_path.endswith('.csv') and not file_path.endswith('.json'):
                return "Only CSV and JSON datasets are supported for basic profiling."

            resolved_path = resolve_user_path(file_path)
            if not os.path.exists(resolved_path):
                return f"File does not exist: {resolved_path}"

            if file_path.endswith('.csv'):
                import csv
                with open(resolved_path, 'r', encoding='utf-8') as f:
                    reader = csv.reader(f)
                    try:
                        headers = next(reader)
                        sample_rows = []
                        for _ in range(3):
                            try:
                                sample_rows.append(next(reader))
                            except StopIteration:
                                break
                        row_count = len(sample_rows) + sum(1 for _ in reader)
                        return json.dumps({
                            "type": "csv",
                            "columns": headers,
                            "total_rows": row_count,
                            "sample_rows": sample_rows
                        }, indent=2)
                    except StopIteration:
                        return "CSV file appears to be empty."

            elif file_path.endswith('.json'):
                with open(resolved_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        sample = data[:3]
                        keys = list(data[0].keys()) if len(data) > 0 and isinstance(data[0], dict) else []
                        return json.dumps({
                            "type": "json_array",
                            "total_elements": len(data),
                            "keys": keys,
                            "sample": sample
                        }, indent=2)
                    elif isinstance(data, dict):
                        return json.dumps({
                            "type": "json_object",
                            "keys": list(data.keys()),
                            "key_count": len(data.keys()),
                            "sample_keys": {k: data[k] for k in list(data.keys())[:3]}
                        }, indent=2)

        except Exception as e:
            return f"Error profiling dataset: {str(e)}"
