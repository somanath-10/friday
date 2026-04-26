"""
Local healthcheck for FRIDAY.

This module focuses on:
- verifying imports and server registration
- exercising core offline-safe MCP tools
- smoke-testing the local web UI startup
- reporting configuration status for network-dependent features
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import importlib.util
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Callable

from friday.config import build_runtime_status, tool_module_enabled
from friday.subprocess_utils import decode_subprocess_text


PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"
SKIP = "SKIP"


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


def _has_module(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _restore_env(previous: dict[str, str | None], keys: list[str]) -> None:
    for key in keys:
        original = previous.get(key)
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original


@contextlib.contextmanager
def _isolated_env(repo_root: Path):
    keys = [
        "FRIDAY_WORKSPACE_DIR",
        "FRIDAY_MEMORY_DIR",
        "MCP_SERVER_URL",
        "FRIDAY_BROWSER_HEADLESS",
    ]
    previous = {key: os.environ.get(key) for key in keys}

    scratch_root = repo_root / "workspace"
    scratch_root.mkdir(parents=True, exist_ok=True)
    workspace_dir = scratch_root / f"friday-health-work-{uuid.uuid4().hex[:8]}"
    memory_dir = scratch_root / f"friday-health-memory-{uuid.uuid4().hex[:8]}"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    memory_dir.mkdir(parents=True, exist_ok=True)
    os.environ["FRIDAY_WORKSPACE_DIR"] = str(workspace_dir)
    os.environ["FRIDAY_MEMORY_DIR"] = str(memory_dir)
    os.environ["MCP_SERVER_URL"] = ""
    os.environ["FRIDAY_BROWSER_HEADLESS"] = "1"
    try:
        yield workspace_dir, memory_dir
    finally:
        _restore_env(previous, keys)
        for temp_path in (workspace_dir, memory_dir):
            try:
                shutil.rmtree(temp_path, ignore_errors=True)
            except Exception:
                pass


def _extract_text(result: Any) -> str:
    content = result
    meta: dict[str, Any] = {}

    if isinstance(result, tuple):
        content = result[0]
        if len(result) > 1 and isinstance(result[1], dict):
            meta = result[1]

    if isinstance(meta.get("result"), str):
        return meta["result"]

    structured = meta.get("structured_content")
    if structured is not None:
        try:
            return json.dumps(structured, indent=2, ensure_ascii=False)
        except TypeError:
            return str(structured)

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text:
                parts.append(text)
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()

    return str(result)


def _record(results: list[CheckResult], name: str, status: str, detail: str) -> None:
    results.append(CheckResult(name=name, status=status, detail=detail))


def _missing_dependency_detail(module_name: str) -> str:
    return (
        f"Missing dependency '{module_name}'. "
        "Run `uv sync`, then use `uv run friday_healthcheck` "
        "or `uv run python -m friday.healthcheck`."
    )


def _module_name_from_error_text(text: str) -> str:
    match = re.search(r"No module named '([^']+)'", text)
    return match.group(1) if match else ""


def _truncate_detail(text: str, limit: int = 280) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 20] + "... [truncated]"


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass


def _stop_subprocess(process: subprocess.Popen[bytes]) -> tuple[str, str]:
    _stop_process(process)

    try:
        stdout, stderr = process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=2)

    return (
        _truncate_detail(decode_subprocess_text(stdout)),
        _truncate_detail(decode_subprocess_text(stderr)),
    )


def _read_temp_output(handle: Any) -> str:
    if handle is None:
        return ""

    try:
        handle.flush()
    except Exception:
        pass

    try:
        handle.seek(0)
        data = handle.read()
    except Exception:
        return ""

    if isinstance(data, str):
        return _truncate_detail(data)
    return _truncate_detail(decode_subprocess_text(data))


def _stop_process_with_output(
    process: subprocess.Popen[bytes],
    *,
    stdout_handle: Any = None,
    stderr_handle: Any = None,
) -> tuple[str, str]:
    _stop_process(process)

    stdout = _read_temp_output(stdout_handle)
    stderr = _read_temp_output(stderr_handle)
    if stdout or stderr:
        return stdout, stderr

    return _stop_subprocess(process)


async def _call_text(mcp: Any, tool_name: str, args: dict[str, Any] | None = None) -> str:
    result = await mcp.call_tool(tool_name, args or {})
    return _extract_text(result)


def _flag_enabled(*flags: str, env_name: str | None = None) -> bool:
    if any(flag in sys.argv[1:] for flag in flags):
        return True
    if env_name:
        value = os.getenv(env_name, "").strip().lower()
        return value in {"1", "true", "yes", "on"}
    return False


def _browser_check_enabled() -> bool:
    return _flag_enabled("--browser", env_name="FRIDAY_CHECK_BROWSER")


def _desktop_check_enabled() -> bool:
    return _flag_enabled("--desktop", env_name="FRIDAY_CHECK_DESKTOP")


class _LocalPageHandler(BaseHTTPRequestHandler):
    body = b"""<!doctype html><html><body><h1>FRIDAY Healthcheck</h1><p>Local fetch works.</p></body></html>"""

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def _desktop_permission_results() -> list[CheckResult]:
    results: list[CheckResult] = []
    system = platform.system()

    if system == "Darwin":
        try:
            from friday.tools.diagnostics import (
                _check_macos_accessibility,
                _check_macos_screen_recording,
            )
        except Exception as exc:
            _record(
                results,
                "config.desktop_permissions",
                WARN,
                f"Could not load macOS permission diagnostics: {exc}",
            )
            return results

        screen = _check_macos_screen_recording()
        accessibility = _check_macos_accessibility()
        _record(
            results,
            "config.desktop.screen_recording",
            PASS if screen.get("status") == "Granted" else WARN,
            screen.get("message", screen.get("status", "Unknown")),
        )
        _record(
            results,
            "config.desktop.accessibility",
            PASS if accessibility.get("status") == "Granted" else WARN,
            accessibility.get("message", accessibility.get("status", "Unknown")),
        )
        return results

    if system == "Windows":
        _record(
            results,
            "config.desktop_permissions",
            PASS,
            "Windows desktop control usually works without separate OS permission prompts. Administrator-only actions still need an elevated terminal.",
        )
        return results

    _record(
        results,
        "config.desktop_permissions",
        WARN,
        "Linux desktop automation depends on display-server policy and helper tools such as scrot, wmctrl, or xdotool.",
    )
    return results


def _build_env_readiness() -> list[CheckResult]:
    results: list[CheckResult] = []

    status = build_runtime_status()
    diagnostics = status.get("diagnostics", {})
    transport = diagnostics.get("transport", {})
    tool_registration = diagnostics.get("tool_registration", {})

    _record(
        results,
        "config.openai",
        PASS if status["openai_configured"] else WARN,
        (
            "OPENAI_API_KEY is configured for local browser chat."
            if status["openai_configured"]
            else "OPENAI_API_KEY is missing. Local browser chat and browser audio transcription will stay offline."
        ),
    )

    workspace_status = PASS if status.get("workspace_writable") else WARN
    workspace_detail = (
        f"Workspace is writable: {status['workspace_path']}"
        if status.get("workspace_writable")
        else f"Workspace is not writable: {status.get('workspace_error') or status['workspace_path']}"
    )
    _record(results, "config.workspace", workspace_status, workspace_detail)

    if status["app_ready"]:
        _record(
            results,
            "config.local_browser",
            PASS,
            f"Local browser mode is ready using {status['llm_provider']} / {status['llm_model']}.",
        )
    else:
        _record(
            results,
            "config.local_browser",
            WARN,
            "; ".join(status["setup_issues"]),
        )

    if transport.get("conflicting_override"):
        _record(
            results,
            "config.mcp_server_url",
            WARN,
            "MCP_SERVER_URL overrides the local host/port settings. The browser UI now uses the current local request URL to avoid stale local-browser routing.",
        )
    else:
        configured_url = transport.get("configured_mcp_server_url") or transport.get("effective_local_mcp_server_url")
        _record(
            results,
            "config.mcp_server_url",
            PASS,
            f"Local MCP endpoint: {configured_url}",
        )

    if status["legacy_livekit_configured"]:
        _record(results, "config.livekit", PASS, "LiveKit credentials are present.")
    else:
        _record(
            results,
            "config.livekit",
            WARN,
            "LiveKit credentials are incomplete. The optional friday_voice worker will not be able to join rooms.",
        )

    providers = status["voice_providers"]
    if status["voice_configured"]:
        _record(
            results,
            "config.voice_providers",
            PASS,
            f"Voice providers are configured for STT={providers['stt']}, LLM={providers['llm']}, TTS={providers['tts']}.",
        )
    else:
        _record(
            results,
            "config.voice_providers",
            WARN,
            "Optional legacy voice mode is missing: " + ", ".join(status["voice_missing_keys"]),
        )

    browser_status = PASS if status["browser_automation_ready"] else WARN
    browser_detail = (
        "Playwright browser automation is ready."
        if status["browser_automation_ready"]
        else "Playwright browser automation is not ready. Browser tools can still use non-Playwright fallbacks where available."
    )
    _record(results, "config.browser_automation", browser_status, browser_detail)

    desktop_status = PASS if status["desktop_control_ready"] else WARN
    desktop_detail = (
        "Desktop control prerequisites are available."
        if status["desktop_control_ready"]
        else "Desktop control prerequisites are incomplete. Run the desktop healthcheck or permission diagnostics for details."
    )
    _record(results, "config.desktop_control", desktop_status, desktop_detail)
    results.extend(_desktop_permission_results())

    if tool_registration.get("ready"):
        _record(
            results,
            "config.tool_registration",
            PASS,
            f"Registered {len(tool_registration.get('registered_modules', []))} enabled tool modules.",
        )
    else:
        issues = tool_registration.get("issues") or ["Tool registration status is incomplete."]
        _record(
            results,
            "config.tool_registration",
            WARN,
            "; ".join(issues),
        )

    if os.getenv("BRAVE_API_KEY"):
        _record(results, "config.brave_search", PASS, "BRAVE_API_KEY is present.")
    else:
        _record(results, "config.brave_search", PASS, "BRAVE_API_KEY is missing, but search_web has a DuckDuckGo fallback.")

    if os.getenv("FIRECRAWL_API_KEY"):
        _record(results, "config.firecrawl", PASS, "FIRECRAWL_API_KEY is present.")
    elif _has_module("trafilatura"):
        _record(results, "config.firecrawl", PASS, "FIRECRAWL_API_KEY is missing, but deep_scrape_url can fall back to trafilatura.")
    else:
        _record(results, "config.firecrawl", WARN, "FIRECRAWL_API_KEY is missing and trafilatura is unavailable.")

    return results


async def _run_desktop_workflow_checks(mcp: Any, results: list[CheckResult]) -> None:
    if not _desktop_check_enabled():
        _record(
            results,
            "workflow.desktop_suite",
            SKIP,
            "Desktop workflow checks are skipped by default. Run with --desktop or set FRIDAY_CHECK_DESKTOP=1 to opt in.",
        )
        return

    documents_folder: Path | None = None

    try:
        special_paths = await _call_text(mcp, "get_special_paths", {})
        documents_path = ""
        for line in special_paths.splitlines():
            if line.lower().startswith("documents:"):
                documents_path = line.split(":", 1)[1].strip()
                break
        status = PASS if documents_path else FAIL
        _record(results, "workflow.documents_root", status, documents_path or special_paths[:240])
    except Exception as exc:
        _record(results, "workflow.documents_root", FAIL, str(exc))

    try:
        folder_name = f"FRIDAY_Desktop_Check_{uuid.uuid4().hex[:8]}"
        folder_rel = f"Documents/{folder_name}"
        await _call_text(mcp, "create_folder", {"folder_path": folder_rel})
        from friday.path_utils import resolve_user_path

        documents_folder = resolve_user_path(folder_rel)
        status = PASS if documents_folder.exists() else FAIL
        _record(results, "workflow.documents_create", status, str(documents_folder))
    except Exception as exc:
        _record(results, "workflow.documents_create", FAIL, str(exc))

    try:
        output = await _call_text(mcp, "search_local_apps", {"query": "edge"})
        status = PASS if "msedge.exe" in output.lower() or "microsoft edge" in output.lower() else FAIL
        _record(results, "workflow.edge_search", status, output[:240])
    except Exception as exc:
        _record(results, "workflow.edge_search", FAIL, str(exc))

    try:
        output = await _call_text(mcp, "list_installed_apps", {"query": "edge", "limit": 10})
        status = PASS if "microsoft edge" in output.lower() else FAIL
        _record(results, "workflow.edge_installed", status, output[:240])
    except Exception as exc:
        _record(results, "workflow.edge_installed", FAIL, str(exc))

    try:
        output = await _call_text(mcp, "open_application", {"app_name": "Microsoft Edge"})
        status = PASS if "launched application" in output.lower() else FAIL
        _record(results, "workflow.edge_launch", status, output[:240])
    except Exception as exc:
        _record(results, "workflow.edge_launch", FAIL, str(exc))

    try:
        query_url = "https://www.bing.com/search?q=friday+workflow+browser+check"
        output = await _call_text(mcp, "open_url", {"url": query_url})
        status = PASS if "opened https://www.bing.com/search" in output.lower() else FAIL
        _record(results, "workflow.browser_open_url", status, output[:240])
        time.sleep(3)

        window_text = await _call_text(mcp, "list_open_windows", {"limit": 10})
        status = PASS if "search" in window_text.lower() or "edge" in window_text.lower() or "bing" in window_text.lower() else FAIL
        _record(results, "workflow.edge_window", status, window_text[:240] or "No Edge windowed process found.")
    except Exception as exc:
        _record(results, "workflow.edge_window", FAIL, str(exc))
    finally:
        if documents_folder is not None:
            shutil.rmtree(documents_folder, ignore_errors=True)


async def _run_offline_tool_checks(server_module: Any, repo_root: Path, results: list[CheckResult]) -> None:
    mcp = server_module.mcp
    calendar_enabled = tool_module_enabled("calendar_tool")

    try:
        tools = await mcp.list_tools()
        prompts = await mcp.list_prompts()
        resources = await mcp.list_resources()
        route_count = len(getattr(mcp, "_custom_starlette_routes", []))

        _record(results, "server.tool_registry", PASS if len(tools) >= 100 else FAIL, f"Registered {len(tools)} tools.")
        _record(results, "server.prompts", PASS if len(prompts) >= 2 else FAIL, f"Registered {len(prompts)} prompts.")
        _record(results, "server.resources", PASS if len(resources) >= 1 else FAIL, f"Registered {len(resources)} resources.")
        _record(results, "server.web_routes", PASS if route_count >= 4 else FAIL, f"Registered {route_count} custom web routes.")
    except Exception as exc:
        _record(results, "server.registration", FAIL, f"Failed to inspect server registry: {exc}")
        return

    try:
        prompt = await mcp.get_prompt("summarize", {"text": "Healthcheck"})
        text = prompt.messages[0].content.text
        status = PASS if "Summarize" in text else FAIL
        _record(results, "prompt.summarize", status, text)
    except Exception as exc:
        _record(results, "prompt.summarize", FAIL, str(exc))

    try:
        resource = await mcp.read_resource("friday://info")
        text = getattr(resource[0], "content", "")
        status = PASS if "Friday MCP Server" in text else FAIL
        _record(results, "resource.friday_info", status, text)
    except Exception as exc:
        _record(results, "resource.friday_info", FAIL, str(exc))

    async def expect_text(
        name: str,
        tool_name: str,
        args: dict[str, Any],
        predicate: Callable[[str], bool],
    ) -> None:
        try:
            output = await _call_text(mcp, tool_name, args)
            status = PASS if predicate(output) else FAIL
            _record(results, name, status, output[:240])
        except Exception as exc:
            _record(results, name, FAIL, str(exc))

    def _nonempty_success(output: str) -> bool:
        stripped = output.strip()
        if not stripped:
            return False
        lowered = stripped.lower()
        return not lowered.startswith(("error ", "could not "))

    await expect_text("tool.get_current_time", "get_current_time", {}, lambda output: "ISO 8601:" in output)
    await expect_text("tool.get_system_telemetry", "get_system_telemetry", {}, lambda output: "os" in output.lower())
    await expect_text("tool.get_environment_info", "get_environment_info", {}, lambda output: "workspace:" in output.lower())
    await expect_text("tool.get_host_control_status", "get_host_control_status", {}, lambda output: "\"workspace\"" in output or "workspace" in output.lower())
    await expect_text(
        "tool.scan_system_inventory",
        "scan_system_inventory",
        {"section": "summary", "limit": 5},
        lambda output: "System Overview" in output,
    )
    await expect_text("tool.format_json", "format_json", {"data": '{"a": 1}'}, lambda output: '"a": 1' in output)
    await expect_text("tool.word_count", "word_count", {"text": "one two\nthree"}, lambda output: '"words": 3' in output)
    await expect_text(
        "tool.execute_python_code",
        "execute_python_code",
        {"code": "print('healthcheck-ok')"},
        lambda output: "healthcheck-ok" in output,
    )
    await expect_text(
        "tool.run_shell_command",
        "run_shell_command",
        {"command": "git rev-parse --is-inside-work-tree"},
        lambda output: "true" in output.lower(),
    )
    await expect_text("tool.create_document", "create_document", {"filename": "demo.txt", "content": "hello demo"}, lambda output: "demo.txt" in output)
    await expect_text("tool.append_to_file", "append_to_file", {"file_path": "demo.txt", "content": "\nmore"}, lambda output: "Appended" in output)
    await expect_text("tool.get_file_contents", "get_file_contents", {"file_path": "demo.txt"}, lambda output: "hello demo" in output and "more" in output)
    await expect_text("tool.read_file_snippet", "read_file_snippet", {"file_path": "demo.txt", "start_line": 1, "end_line": 2}, lambda output: "demo.txt" in output)
    await expect_text("tool.list_directory_tree", "list_directory_tree", {"path": "."}, lambda output: "demo.txt" in output)
    await expect_text("tool.search_in_files", "search_in_files", {"directory": ".", "keyword": "hello demo"}, lambda output: "demo.txt" in output)
    await expect_text("tool.copy_path", "copy_path", {"source_path": "demo.txt", "destination_path": "copies/demo_copy.txt"}, lambda output: "Copied file" in output)
    await expect_text("tool.move_path", "move_path", {"source_path": "copies/demo_copy.txt", "destination_path": "moved/demo_final.txt"}, lambda output: "Moved path" in output)
    await expect_text(
        "tool.delete_path",
        "delete_path",
        {"path": "moved/demo_final.txt"},
        lambda output: "Deleted file" in output or "[Approval Required]" in output,
    )
    await expect_text("tool.search_local_apps", "search_local_apps", {"query": "edge"}, _nonempty_success)
    await expect_text("tool.list_chrome_profiles", "list_chrome_profiles", {}, _nonempty_success)
    await expect_text("tool.inspect_desktop_screen", "inspect_desktop_screen", {"question": "What is visible right now?"}, lambda output: "Desktop screenshot:" in output or "Error inspecting desktop screen" not in output)
    await expect_text("tool.get_codex_relay_status", "get_codex_relay_status", {}, lambda output: "project_path" in output)
    await expect_text("tool.build_codex_project_brief", "build_codex_project_brief", {}, lambda output: "Project root:" in output)

    csv_path = Path(os.environ["FRIDAY_WORKSPACE_DIR"]) / "data.csv"
    csv_path.write_text("name,score\nTony,99\nPepper,97\n", encoding="utf-8")
    await expect_text("tool.profile_dataset", "profile_dataset", {"file_path": "data.csv"}, lambda output: '"total_rows": 2' in output)

    await expect_text("tool.zip_files", "zip_files", {"paths": "demo.txt", "output_name": "demo_bundle"}, lambda output: ".zip" in output)
    await expect_text("tool.list_zip_contents", "list_zip_contents", {"archive_path": "demo_bundle.zip"}, lambda output: "demo.txt" in output)
    await expect_text("tool.unzip_file", "unzip_file", {"archive_path": "demo_bundle.zip", "destination": "unzipped_demo"}, lambda output: "Extracted" in output)

    fixture_pdf = repo_root / "workspace" / "workflow_suite_20260417_165535" / "workspace" / "sample.pdf"
    if fixture_pdf.exists():
        await expect_text("tool.read_pdf", "read_pdf", {"file_path": str(fixture_pdf)}, _nonempty_success)
    else:
        _record(results, "tool.read_pdf", SKIP, "Sample PDF fixture not found.")

    if calendar_enabled:
        await expect_text(
            "tool.create_calendar_event",
            "create_calendar_event",
            {"title": "Health Check", "start_datetime": "2026-05-01 09:00"},
            lambda output: ".ics" in output,
        )
    else:
        _record(
            results,
            "tool.create_calendar_event",
            SKIP,
            "Calendar export is disabled by default. Set FRIDAY_ENABLE_CALENDAR_TOOL=1 to enable ICS generation.",
        )
    if calendar_enabled:
        await expect_text(
            "tool.add_reminder",
            "add_reminder",
            {"text": "Smoke test reminder", "remind_at": "2026-05-01 09:00"},
            lambda output: "Reminder set" in output,
        )
        await expect_text("tool.list_reminders", "list_reminders", {}, lambda output: "Smoke test reminder" in output)
    else:
        _record(
            results,
            "tool.add_reminder",
            SKIP,
            "Reminder tools are disabled with calendar_tool. Set FRIDAY_ENABLE_CALENDAR_TOOL=1 to enable them.",
        )
        _record(
            results,
            "tool.list_reminders",
            SKIP,
            "Reminder tools are disabled with calendar_tool. Set FRIDAY_ENABLE_CALENDAR_TOOL=1 to enable them.",
        )
    await expect_text(
        "tool.record_conversation_turn",
        "record_conversation_turn",
        {
            "user_message": "healthcheck user",
            "assistant_reply": "healthcheck assistant",
            "tool_events": [{"name": "ping", "ok": True}],
        },
        lambda output: "recorded" in output.lower(),
    )
    await expect_text(
        "tool.store_action_trace",
        "store_action_trace",
        {
            "goal": "healthcheck goal",
            "outcome": "healthcheck outcome",
            "tool_events": [{"name": "ping", "ok": True}],
            "status": "completed",
        },
        lambda output: "stored" in output.lower(),
    )
    await expect_text(
        "tool.get_recent_action_traces",
        "get_recent_action_traces",
        {"limit": 1},
        lambda output: "healthcheck goal" in output,
    )
    await expect_text(
        "tool.create_workflow_plan",
        "create_workflow_plan",
        {"goal": "Run tests and report the result", "mode": "safe"},
        lambda output: "Workflow Plan" in output and "ID:" in output,
    )
    await expect_text(
        "tool.record_workflow_progress",
        "record_workflow_progress",
        {
            "workflow_id": "latest",
            "step_id": "execute",
            "status": "passed",
            "result": "healthcheck execution passed",
        },
        lambda output: "execute -> passed" in output,
    )
    await expect_text(
        "tool.complete_workflow",
        "complete_workflow",
        {"workflow_id": "latest", "outcome": "healthcheck workflow completed", "verified": True},
        lambda output: "marked completed" in output,
    )
    await expect_text(
        "tool.get_workflow_status",
        "get_workflow_status",
        {"workflow_id": "latest"},
        lambda output: "Status: completed" in output,
    )

    if calendar_enabled:
        try:
            reminder_listing = await _call_text(mcp, "list_reminders", {})
            reminder_id = ""
            for line in reminder_listing.splitlines():
                if "Smoke test reminder" in line and (line.startswith("[TODO] ") or line.startswith("[DONE] ")):
                    parts = line.split("] [", 1)
                    if len(parts) == 2:
                        reminder_id = parts[1].split("]", 1)[0]
                    break
            if reminder_id:
                await expect_text(
                    "tool.mark_reminder_done",
                    "mark_reminder_done",
                    {"reminder_id": reminder_id},
                    lambda output: "marked as done" in output.lower(),
                )
            else:
                _record(results, "tool.mark_reminder_done", FAIL, "Could not locate reminder id in listing.")
        except Exception as exc:
            _record(results, "tool.mark_reminder_done", FAIL, str(exc))
    else:
        _record(
            results,
            "tool.mark_reminder_done",
            SKIP,
            "Reminder tools are disabled with calendar_tool. Set FRIDAY_ENABLE_CALENDAR_TOOL=1 to enable them.",
        )

    await expect_text("tool.git_status", "git_status", {"repo_path": str(repo_root)}, lambda output: "Git Status" in output or "Working tree clean" in output)
    await expect_text("tool.git_branch", "git_branch", {"repo_path": str(repo_root)}, lambda output: "Branches:" in output)
    await expect_text("tool.ping_host", "ping_host", {"host": "127.0.0.1", "count": 1}, _nonempty_success)
    await expect_text("tool.dns_lookup", "dns_lookup", {"hostname": "localhost"}, lambda output: "127.0.0.1" in output or "::1" in output)
    await expect_text("tool.get_local_network_info", "get_local_network_info", {}, lambda output: "Hostname" in output)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = int(listener.getsockname()[1])

    def _accept_once() -> None:
        try:
            conn, _ = listener.accept()
        except OSError:
            return
        conn.close()

    accept_thread = threading.Thread(target=_accept_once, daemon=True)
    accept_thread.start()
    try:
        await expect_text("tool.check_port", "check_port", {"host": "127.0.0.1", "port": port}, lambda output: "OPEN" in output)
    finally:
        listener.close()

    httpd = HTTPServer(("127.0.0.1", 0), _LocalPageHandler)
    http_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    http_thread.start()
    try:
        fetch_url = f"http://127.0.0.1:{httpd.server_port}/"
        await expect_text("tool.fetch_url", "fetch_url", {"url": fetch_url}, lambda output: "Local fetch works" in output)
        if _browser_check_enabled():
            await expect_text("tool.browser_navigate", "browser_navigate", {"url": fetch_url}, lambda output: "Page title:" in output and "URL:" in output)
            await expect_text("tool.browser_get_state", "browser_get_state", {}, lambda output: "Interactive elements:" in output)
            await expect_text("tool.browser_read_page", "browser_read_page", {}, lambda output: "FRIDAY Healthcheck" in output)
            await expect_text("tool.browser_close", "browser_close", {}, lambda output: "closed successfully" in output.lower())
        else:
            _record(
                results,
                "tool.browser_suite",
                SKIP,
                "Playwright is installed, but live browser automation is skipped by default. Run with --browser or set FRIDAY_CHECK_BROWSER=1 to opt in.",
            )
    finally:
        httpd.shutdown()
        http_thread.join(timeout=2)

    if _has_module("PIL"):
        image_path = Path(os.environ["FRIDAY_WORKSPACE_DIR"]) / "sample.png"
        from PIL import Image  # type: ignore

        Image.new("RGB", (24, 24), color=(255, 0, 0)).save(image_path)
        await expect_text("tool.get_image_info", "get_image_info", {"file_path": "sample.png"}, lambda output: "24 x 24" in output)
        await expect_text("tool.resize_image", "resize_image", {"file_path": "sample.png", "width": 16, "height": 16}, lambda output: "16x16" in output)
        await expect_text(
            "tool.convert_image_format",
            "convert_image_format",
            {"file_path": "sample.png", "target_format": "jpg", "output_name": "sample.jpg"},
            lambda output: "sample.jpg" in output,
        )
    else:
        _record(results, "tool.image_suite", SKIP, "Pillow is not installed.")

    await expect_text("tool.get_volume", "get_volume", {}, _nonempty_success)
    await expect_text("tool.get_running_apps", "get_running_apps", {}, _nonempty_success)
    await expect_text(
        "tool.list_open_windows",
        "list_open_windows",
        {"limit": 5},
        lambda output: _nonempty_success(output) and ("Open windows (" in output or "No open windows found" in output),
    )
    await expect_text("tool.list_installed_apps", "list_installed_apps", {"query": "notepad", "limit": 5}, _nonempty_success)
    await _run_desktop_workflow_checks(mcp, results)


def _wait_for_url(url: str, timeout_seconds: float = 15.0) -> str:
    deadline = time.time() + timeout_seconds
    last_error = ""

    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as exc:
            last_error = str(exc)
            time.sleep(0.4)

    raise RuntimeError(last_error or f"Timed out waiting for {url}")


def _server_startup_check(repo_root: Path) -> CheckResult:
    port = _free_port()
    env = {**os.environ}
    env["MCP_SERVER_HOST"] = "127.0.0.1"
    env["MCP_SERVER_PORT"] = str(port)
    env["MCP_SERVER_URL"] = ""
    env["FRIDAY_BROWSER_HEADLESS"] = "1"

    with tempfile.TemporaryFile() as stdout_handle, tempfile.TemporaryFile() as stderr_handle:
        process = subprocess.Popen(
            [sys.executable, "server.py"],
            cwd=repo_root,
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=False,
        )
        output_snippets: tuple[str, str] | None = None

        try:
            html = _wait_for_url(f"http://127.0.0.1:{port}/")
            status_payload = _wait_for_url(f"http://127.0.0.1:{port}/status")
            status = json.loads(status_payload)

            required_keys = {
                "app_ready",
                "server_name",
                "mode",
                "host",
                "port",
                "workspace_path",
                "python_version",
                "os",
                "llm_provider",
                "llm_model",
                "openai_configured",
                "voice_configured",
                "browser_automation_ready",
                "desktop_control_ready",
                "enabled_tool_modules",
                "disabled_tool_modules",
                "setup_issues",
                "warnings",
                "next_steps",
            }
            missing_keys = sorted(required_keys.difference(status))

            if "FRIDAY" not in html.upper() and "Friday" not in html:
                return CheckResult("server.startup", FAIL, "Server responded, but the local UI HTML did not look correct.")

            if missing_keys:
                return CheckResult(
                    "server.startup",
                    FAIL,
                    "Server responded, but /status is missing required fields: "
                    + ", ".join(missing_keys),
                )

            ready = status.get("app_ready", status.get("ready"))
            detail = (
                f"HTTP UI loaded on port {port}; "
                f"/status mode={status.get('mode')} app_ready={ready}; "
                f"warnings={len(status.get('warnings', []))}; "
                f"setup_issues={len(status.get('setup_issues', []))}."
            )
            return CheckResult("server.startup", PASS, detail)
        except Exception as exc:
            output_snippets = _stop_process_with_output(
                process,
                stdout_handle=stdout_handle,
                stderr_handle=stderr_handle,
            )
            stdout, stderr = output_snippets

            missing_module = ""
            if isinstance(exc, ModuleNotFoundError) and exc.name:
                missing_module = exc.name
            if not missing_module and stderr:
                missing_module = _module_name_from_error_text(stderr)

            detail = f"Startup smoke test failed: {exc}"
            if missing_module:
                detail += f" | {_missing_dependency_detail(missing_module)}"
            if stderr:
                detail += f" | stderr: {stderr}"
            if stdout:
                detail += f" | stdout: {stdout}"
            return CheckResult("server.startup", FAIL, detail)
        finally:
            if output_snippets is None:
                _stop_process_with_output(
                    process,
                    stdout_handle=stdout_handle,
                    stderr_handle=stderr_handle,
                )


async def _collect_results() -> list[CheckResult]:
    results: list[CheckResult] = []
    repo_root = Path(__file__).resolve().parent.parent

    try:
        from dotenv import load_dotenv

        load_dotenv(repo_root / ".env")
    except Exception:
        pass

    for module_name in ("dotenv", "PIL", "pypdf", "playwright", "trafilatura"):
        status = PASS if _has_module(module_name) else WARN
        detail = f"Module {'is' if status == PASS else 'is not'} installed: {module_name}"
        _record(results, f"dependency.{module_name.lower()}", status, detail)

    results.extend(_build_env_readiness())

    with _isolated_env(repo_root):
        try:
            server_module = importlib.import_module("server")
            importlib.import_module("agent_friday")
            sdk_module = importlib.import_module("friday.sdk")
            local_chat_module = importlib.import_module("friday.local_chat")

            _record(results, "import.server", PASS, "Imported server module successfully.")
            _record(results, "import.agent_friday", PASS, "Imported voice agent module successfully.")
            _record(results, "import.sdk", PASS, "Imported friday.sdk successfully.")

            # Use cross-platform command for SDK shell test
            import platform
            test_command = "echo 'sdk-ok'" if platform.system() != "Windows" else "Write-Output 'sdk-ok'"
            sdk_output = sdk_module.execute_shell(test_command)
            sdk_status = PASS if "sdk-ok" in sdk_output else FAIL
            _record(results, "sdk.execute_shell", sdk_status, sdk_output.strip()[:240])

            sdk_path = Path(os.environ["FRIDAY_WORKSPACE_DIR"]) / "sdk_note.txt"
            write_output = sdk_module.write_file(str(sdk_path), "sdk-check")
            read_output = sdk_module.read_file(str(sdk_path))
            sdk_file_status = PASS if "successfully" in write_output.lower() and read_output == "sdk-check" else FAIL
            _record(results, "sdk.file_io", sdk_file_status, f"{write_output} | read back: {read_output}")

            issues = local_chat_module.local_mode_issues()
            if issues:
                _record(results, "local_chat.readiness", WARN, "; ".join(issues))
            else:
                _record(results, "local_chat.readiness", PASS, "Local browser chat prerequisites are present.")

            await _run_offline_tool_checks(server_module, repo_root, results)
        except Exception as exc:
            if isinstance(exc, ModuleNotFoundError) and exc.name:
                detail = _missing_dependency_detail(exc.name)
            else:
                detail = str(exc)
            _record(results, "import.core", FAIL, detail)

        results.append(_server_startup_check(repo_root))

    return results


def _summarize(results: list[CheckResult]) -> dict[str, int]:
    counts = {PASS: 0, WARN: 0, FAIL: 0, SKIP: 0}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts


def _print_human(results: list[CheckResult]) -> None:
    encoding = sys.stdout.encoding or "utf-8"

    def _safe(text: str) -> str:
        return text.encode(encoding, errors="replace").decode(encoding, errors="replace")

    for result in results:
        print(_safe(f"[{result.status}] {result.name}"))
        if result.detail:
            print(_safe(f"  {result.detail}"))
    counts = _summarize(results)
    print()
    print(
        "Summary: "
        f"{counts.get(PASS, 0)} passed, "
        f"{counts.get(WARN, 0)} warnings, "
        f"{counts.get(FAIL, 0)} failed, "
        f"{counts.get(SKIP, 0)} skipped"
    )

    from friday.logger import logger
    logger.info(
        f"Healthcheck Summary: {counts.get(PASS, 0)} passed, {counts.get(WARN, 0)} warnings, "
        f"{counts.get(FAIL, 0)} failed, {counts.get(SKIP, 0)} skipped"
    )


def main() -> int:
    results = asyncio.run(_collect_results())

    if "--json" in sys.argv[1:]:
        print(json.dumps([asdict(result) for result in results], indent=2))
    else:
        _print_human(results)

    counts = _summarize(results)
    return 1 if counts.get(FAIL, 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
