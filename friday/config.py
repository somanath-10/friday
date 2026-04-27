"""
Configuration and startup diagnostics for FRIDAY.

The local browser console is the primary mode. Today that chat bridge uses
OpenAI for LLM/tool calling, while legacy voice and a few internal utilities can
still be configured with other providers.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from friday.path_utils import workspace_dir

load_dotenv()


TRUE_VALUES = {"1", "true", "yes", "on"}


LLM_PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
}

VOICE_PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "whisper": "OPENAI_API_KEY",
    "deepgram": "DEEPGRAM_API_KEY",
    "sarvam": "SARVAM_API_KEY",
    "google": "GOOGLE_APPLICATION_CREDENTIALS",
    "gemini": "GOOGLE_API_KEY",
}


def env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean environment variable using common truthy spellings."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in TRUE_VALUES


def env_int(name: str, default: int) -> int:
    """Read an integer environment variable without letting bad values crash startup."""
    try:
        return int(os.getenv(name, str(default)).strip())
    except (TypeError, ValueError):
        return default


def _env_text(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _command_available(*names: str) -> bool:
    return any(shutil.which(name) for name in names)


def _find_windows_browser(binary_name: str) -> bool:
    if platform.system() != "Windows":
        return False
    if shutil.which(binary_name):
        return True
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    program_files = os.environ.get("ProgramFiles", "").strip()
    program_files_x86 = os.environ.get("ProgramFiles(x86)", "").strip()
    candidates: list[Path] = []
    if binary_name.lower() == "chrome.exe":
        if local_app_data:
            candidates.append(Path(local_app_data) / "Google" / "Chrome" / "Application" / "chrome.exe")
        if program_files:
            candidates.append(Path(program_files) / "Google" / "Chrome" / "Application" / "chrome.exe")
        if program_files_x86:
            candidates.append(Path(program_files_x86) / "Google" / "Chrome" / "Application" / "chrome.exe")
    elif binary_name.lower() == "msedge.exe":
        if program_files:
            candidates.append(Path(program_files) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
        if program_files_x86:
            candidates.append(Path(program_files_x86) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    return any(candidate.exists() for candidate in candidates)


def _windows_desktop_status() -> dict[str, Any]:
    is_windows = platform.system() == "Windows"
    pywinauto = _module_available("pywinauto") if is_windows else False
    pyautogui = _module_available("pyautogui") if is_windows else False
    powershell = _command_available("powershell", "pwsh") if is_windows else False
    chrome = _find_windows_browser("chrome.exe")
    edge = _find_windows_browser("msedge.exe")
    desktop_ready = is_windows and (pywinauto or pyautogui or powershell)
    return {
        "is_windows": is_windows,
        "windows_version": platform.version() if is_windows else "",
        "pywinauto_available": pywinauto,
        "pyautogui_available": pyautogui,
        "powershell_available": powershell,
        "chrome_available": chrome,
        "edge_available": edge,
        "desktop_control_ready": desktop_ready,
    }


def _selected_llm_provider() -> str:
    return _env_text("LLM_PROVIDER", "openai").lower() or "openai"


def _selected_llm_model(provider: str) -> str:
    if provider == "openai":
        return _env_text("OPENAI_LLM_MODEL", "gpt-4o") or "gpt-4o"
    if provider in {"gemini", "google"}:
        return _env_text("GEMINI_LLM_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash"
    if provider == "groq":
        return _env_text("GROQ_LLM_MODEL", "llama-3.3-70b-versatile") or "llama-3.3-70b-versatile"
    return _env_text("OPENAI_LLM_MODEL", "gpt-4o") or "gpt-4o"


def _workspace_writable(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix=".friday-write-", dir=path, delete=True):
            pass
        return True, ""
    except OSError as exc:
        return False, str(exc)


def _provider_missing_key(provider: str, mapping: dict[str, str]) -> str:
    required = mapping.get(provider.strip().lower(), "")
    if required and not _env_text(required):
        return required
    return ""


def _voice_configuration() -> tuple[bool, list[str], list[str]]:
    warnings: list[str] = []
    next_steps: list[str] = []

    browser_transcription_ready = bool(_env_text("OPENAI_API_KEY"))
    livekit_configured = all(
        _env_text(key)
        for key in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
    )

    stt_provider = _env_text("STT_PROVIDER", "whisper").lower() or "whisper"
    tts_provider = _env_text("TTS_PROVIDER", "openai").lower() or "openai"
    missing_voice_keys = [
        f"STT:{missing}"
        for missing in [_provider_missing_key(stt_provider, VOICE_PROVIDER_KEYS)]
        if missing
    ]
    missing_voice_keys.extend(
        f"TTS:{missing}"
        for missing in [_provider_missing_key(tts_provider, VOICE_PROVIDER_KEYS)]
        if missing
    )

    if livekit_configured and missing_voice_keys:
        warnings.append(
            "Legacy LiveKit voice is configured but provider keys are missing: "
            + ", ".join(missing_voice_keys)
        )
        next_steps.append("Add the missing voice provider keys, or leave LiveKit disabled for browser text mode.")
    elif not livekit_configured:
        warnings.append("Legacy LiveKit voice credentials are not configured; local browser text mode is unaffected.")

    if not browser_transcription_ready:
        warnings.append("Browser microphone transcription needs OPENAI_API_KEY; typed chat can still be diagnosed separately.")

    return browser_transcription_ready or (livekit_configured and not missing_voice_keys), warnings, next_steps


@dataclass(frozen=True)
class ConfigDiagnostics:
    app_ready: bool
    server_name: str
    mode: str
    host: str
    port: int
    workspace_path: str
    python_version: str
    os: str
    is_windows: bool
    windows_version: str
    llm_provider: str
    llm_model: str
    openai_configured: bool
    voice_configured: bool
    browser_automation_ready: bool
    desktop_control_ready: bool
    pywinauto_available: bool
    pyautogui_available: bool
    playwright_available: bool
    chrome_available: bool
    edge_available: bool
    powershell_available: bool
    enabled_tool_modules: list[str]
    disabled_tool_modules: list[dict[str, str]]
    setup_issues: list[str]
    warnings: list[str]
    next_steps: list[str]
    chat_ready: bool
    access_mode: str
    permissions_summary: dict[str, Any]
    emergency_stop: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_config_diagnostics(
    *,
    enabled_tool_modules: list[str] | None = None,
    disabled_tool_modules: list[dict[str, str]] | None = None,
) -> ConfigDiagnostics:
    """Return a structured local setup report used by `/status` and tests."""
    setup_issues: list[str] = []
    warnings: list[str] = []
    next_steps: list[str] = []

    host = _env_text("MCP_SERVER_HOST", "0.0.0.0") or "0.0.0.0"
    port_raw = _env_text("MCP_SERVER_PORT", "8000") or "8000"
    port = env_int("MCP_SERVER_PORT", 8000)
    if str(port) != port_raw:
        warnings.append(f"MCP_SERVER_PORT={port_raw!r} is invalid; using {port}.")
        next_steps.append("Set MCP_SERVER_PORT to a valid integer if you need a custom port.")

    workspace = workspace_dir()
    workspace_ok, workspace_error = _workspace_writable(workspace)
    if not workspace_ok:
        setup_issues.append(f"Workspace is not writable: {workspace_error}")
        next_steps.append(f"Fix permissions or set FRIDAY_WORKSPACE_DIR to a writable path. Current: {workspace}")

    provider = _selected_llm_provider()
    model = _selected_llm_model(provider)
    openai_configured = bool(_env_text("OPENAI_API_KEY"))
    windows_status = _windows_desktop_status()

    if provider != "openai":
        setup_issues.append(
            "Local browser chat currently supports LLM_PROVIDER=openai. "
            f"Current LLM_PROVIDER={provider!r}."
        )
        next_steps.append(
            "Set LLM_PROVIDER=openai for the local browser console. "
            "Gemini/Groq-style providers remain for legacy voice or internal utility code where supported."
        )

    if not openai_configured:
        setup_issues.append("OPENAI_API_KEY is missing; local browser chat and browser microphone transcription are disabled.")
        next_steps.append("Add OPENAI_API_KEY to .env, then restart `uv run friday`.")

    selected_provider_key = _provider_missing_key(provider, LLM_PROVIDER_KEYS)
    if selected_provider_key and selected_provider_key != "OPENAI_API_KEY":
        warnings.append(f"{selected_provider_key} is missing for LLM_PROVIDER={provider}.")

    voice_configured, voice_warnings, voice_next_steps = _voice_configuration()
    warnings.extend(voice_warnings)
    next_steps.extend(voice_next_steps)

    playwright_available = _module_available("playwright")
    browser_automation_ready = playwright_available and (windows_status["chrome_available"] or windows_status["edge_available"] or not windows_status["is_windows"])
    if not playwright_available:
        warnings.append("Playwright is not installed; browser automation tools will fall back or fail gracefully.")
        next_steps.append("Run `uv sync` and `uv run playwright install chromium` before browser automation.")
    elif windows_status["is_windows"] and not (windows_status["chrome_available"] or windows_status["edge_available"]):
        warnings.append("Playwright is installed, but Chrome/Edge were not detected in common Windows locations.")

    desktop_control_ready = bool(windows_status["desktop_control_ready"])
    if windows_status["is_windows"]:
        if not windows_status["pywinauto_available"]:
            warnings.append("pywinauto is not installed; FRIDAY will use PowerShell and PyAutoGUI fallbacks for desktop control.")
            next_steps.append("Install pywinauto for stronger Windows UI Automation support.")
        if not windows_status["pyautogui_available"]:
            warnings.append("pyautogui is not installed; cursor-based fallback actions are unavailable.")
            next_steps.append("Install pyautogui for screenshot/cursor fallbacks on Windows.")
        if not windows_status["powershell_available"]:
            warnings.append("PowerShell was not detected; some Windows automation and diagnostics will fail.")
    else:
        warnings.append("Desktop control is currently implemented for Windows only.")
        next_steps.append("Desktop control is currently implemented for Windows only.")

    from friday.core.permissions import access_mode_summary
    from friday.safety.emergency_stop import emergency_stop_status

    permissions_summary = access_mode_summary()
    if permissions_summary["mode"] == "full_control":
        warnings.append("FRIDAY_ACCESS_MODE=full_control is active. Sensitive actions still require approval and dangerous actions remain blocked.")
    if not next_steps and not setup_issues:
        next_steps.append(f"Open http://127.0.0.1:{port}/ for the local browser console.")

    chat_ready = not setup_issues
    return ConfigDiagnostics(
        app_ready=chat_ready,
        server_name=_env_text("SERVER_NAME", "Friday") or "Friday",
        mode=_env_text("FRIDAY_MODE", "local-browser") or "local-browser",
        host=host,
        port=port,
        workspace_path=str(workspace),
        python_version=sys.version.split()[0],
        os=f"{platform.system()} {platform.release()}".strip(),
        is_windows=bool(windows_status["is_windows"]),
        windows_version=str(windows_status["windows_version"]),
        llm_provider=provider,
        llm_model=model,
        openai_configured=openai_configured,
        voice_configured=voice_configured,
        browser_automation_ready=browser_automation_ready,
        desktop_control_ready=desktop_control_ready,
        pywinauto_available=bool(windows_status["pywinauto_available"]),
        pyautogui_available=bool(windows_status["pyautogui_available"]),
        playwright_available=playwright_available,
        chrome_available=bool(windows_status["chrome_available"]),
        edge_available=bool(windows_status["edge_available"]),
        powershell_available=bool(windows_status["powershell_available"]),
        enabled_tool_modules=enabled_tool_modules or [],
        disabled_tool_modules=disabled_tool_modules or [],
        setup_issues=setup_issues,
        warnings=warnings,
        next_steps=next_steps,
        chat_ready=chat_ready,
        access_mode=str(permissions_summary["mode"]),
        permissions_summary=permissions_summary,
        emergency_stop=emergency_stop_status(),
    )


class Config:
    SERVER_NAME: str = _env_text("SERVER_NAME", "Friday") or "Friday"
    DEBUG: bool = env_bool("DEBUG", False)
    OPENAI_API_KEY: str = _env_text("OPENAI_API_KEY")
    MCP_SERVER_HOST: str = _env_text("MCP_SERVER_HOST", "0.0.0.0") or "0.0.0.0"
    MCP_SERVER_PORT: int = env_int("MCP_SERVER_PORT", 8000)
    MCP_MOUNT_PATH: str = _env_text("MCP_MOUNT_PATH", "/") or "/"
    MCP_SSE_PATH: str = _env_text("MCP_SSE_PATH", "/sse") or "/sse"
    SERVER_INSTRUCTIONS: str = os.getenv(
        "SERVER_INSTRUCTIONS",
        "I am F.R.I.D.A.Y., a Tony Stark-style AI assistant. "
        "I have access to a comprehensive set of tools. "
        "Be concise, accurate, and a little witty.",
    )


config = Config()


def tool_registration_status() -> dict[str, Any]:
    """Return a normalized summary of the dynamic tool registry state."""
    try:
        from friday.tools import get_tool_module_status

        module_status = get_tool_module_status()
    except Exception as exc:
        return {
            "attempted": True,
            "discovered_modules": [],
            "enabled_modules": [],
            "disabled_modules": [],
            "registered_modules": [],
            "failed_modules": {"registry": str(exc)},
            "ready": False,
            "issues": [f"Tool registry status could not be loaded: {exc}"],
        }

    enabled = [str(item.get("module", "")) for item in module_status if item.get("enabled")]
    disabled = [str(item.get("module", "")) for item in module_status if not item.get("enabled")]
    failed = {
        str(item.get("module", "")): str(item.get("error", ""))
        for item in module_status
        if not item.get("enabled")
    }
    return {
        "attempted": bool(module_status),
        "discovered_modules": [str(item.get("module", "")) for item in module_status],
        "enabled_modules": enabled,
        "disabled_modules": disabled,
        "registered_modules": enabled,
        "failed_modules": failed,
        "ready": bool(enabled),
        "issues": [f"{module}: {error}" for module, error in failed.items() if error],
    }


def build_runtime_status() -> dict[str, Any]:
    """Compatibility runtime status used by older UI and config tests."""
    warnings: list[str] = []
    next_steps: list[str] = []
    setup_issues: list[str] = []

    host = _env_text("MCP_SERVER_HOST", "0.0.0.0") or "0.0.0.0"
    port_raw = _env_text("MCP_SERVER_PORT", "8000") or "8000"
    port = env_int("MCP_SERVER_PORT", 8000)
    if str(port) != port_raw:
        warnings.append(f"MCP_SERVER_PORT={port_raw!r} is invalid; using {port}.")

    configured_provider = _selected_llm_provider()
    llm_provider = "openai"
    llm_model = _selected_llm_model("openai")
    openai_configured = bool(_env_text("OPENAI_API_KEY"))
    if configured_provider != "openai":
        warnings.append(
            f"LLM_PROVIDER={configured_provider} is not used by local browser chat; using openai instead."
        )

    if not openai_configured:
        setup_issues.append("OPENAI_API_KEY is required for local browser chat.")
        next_steps.append("Add OPENAI_API_KEY to .env, then restart the app.")

    registration = tool_registration_status()
    enabled_tool_modules = list(registration.get("enabled_modules", []))
    disabled_tool_modules = [
        {"module": module, "error": str(registration.get("failed_modules", {}).get(module, ""))}
        for module in registration.get("disabled_modules", [])
    ]
    if not enabled_tool_modules or not registration.get("ready") or not registration.get("registered_modules"):
        setup_issues.append("No enabled tool modules were successfully registered.")

    windows_status = _windows_desktop_status()
    playwright_available = _module_available("playwright")
    browser_automation_ready = playwright_available and (windows_status["chrome_available"] or windows_status["edge_available"] or not windows_status["is_windows"])
    desktop_control_ready = bool(windows_status["desktop_control_ready"])
    voice_configured = all(
        _env_text(key)
        for key in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
    )

    local_mcp_server_url = f"http://127.0.0.1:{port}{_env_text('MCP_SSE_PATH', '/sse') or '/sse'}"
    configured_mcp_server_url = _env_text("MCP_SERVER_URL")
    conflicting_override = bool(configured_mcp_server_url) and configured_mcp_server_url != local_mcp_server_url
    if conflicting_override:
        warnings.append("MCP_SERVER_URL does not match the local host/port settings.")
    if not windows_status["is_windows"]:
        warnings.append("Desktop control is currently implemented for Windows only.")
        next_steps.append("Desktop control is currently implemented for Windows only.")
    elif not windows_status["pywinauto_available"]:
        warnings.append("pywinauto is not installed; Windows UI Automation will fall back to PowerShell or PyAutoGUI.")

    from friday.core.permissions import access_mode_summary
    from friday.safety.emergency_stop import emergency_stop_status

    permissions_summary = access_mode_summary()
    if permissions_summary["mode"] == "full_control":
        warnings.append("FRIDAY_ACCESS_MODE=full_control is active. Sensitive actions still require approval and dangerous actions remain blocked.")

    workspace = workspace_dir()
    app_ready = not setup_issues
    return {
        "app_ready": app_ready,
        "server_name": _env_text("SERVER_NAME", "Friday") or "Friday",
        "mode": "local-browser",
        "host": host,
        "port": port,
        "workspace_path": str(workspace),
        "python_version": sys.version.split()[0],
        "os": f"{platform.system()} {platform.release()}".strip(),
        "is_windows": bool(windows_status["is_windows"]),
        "windows_version": str(windows_status["windows_version"]),
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "openai_configured": openai_configured,
        "voice_configured": voice_configured,
        "browser_automation_ready": browser_automation_ready,
        "desktop_control_ready": desktop_control_ready,
        "pywinauto_available": bool(windows_status["pywinauto_available"]),
        "pyautogui_available": bool(windows_status["pyautogui_available"]),
        "playwright_available": playwright_available,
        "chrome_available": bool(windows_status["chrome_available"]),
        "edge_available": bool(windows_status["edge_available"]),
        "powershell_available": bool(windows_status["powershell_available"]),
        "enabled_tool_modules": enabled_tool_modules,
        "disabled_tool_modules": disabled_tool_modules,
        "tool_registration_ready": bool(registration.get("ready")),
        "tool_registration_issues": list(registration.get("issues", [])),
        "setup_issues": setup_issues,
        "warnings": warnings,
        "next_steps": next_steps,
        "chat_ready": app_ready,
        "access_mode": permissions_summary["mode"],
        "permissions_summary": permissions_summary,
        "emergency_stop": emergency_stop_status(),
        "diagnostics": {
            "transport": {
                "configured_mcp_server_url": configured_mcp_server_url,
                "effective_local_mcp_server_url": local_mcp_server_url,
                "conflicting_override": conflicting_override,
            },
            "tool_registration": registration,
        },
        "mcp_server_url": local_mcp_server_url,
    }


def local_browser_setup_issues() -> list[str]:
    """Compatibility helper for the local chat bridge."""
    return list(build_runtime_status().get("setup_issues", []))
