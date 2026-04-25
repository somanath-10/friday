"""
Configuration helpers and startup diagnostics for FRIDAY.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from friday.path_utils import workspace_dir

load_dotenv()

LOCAL_BROWSER_MODE = "local-browser"
LOCAL_BROWSER_LLM_PROVIDER = "openai"
LOCAL_BROWSER_LLM_MODEL = "OPENAI_LLM_MODEL"
LOCAL_BROWSER_OPENAI_KEY = "OPENAI_API_KEY"

VOICE_PROVIDER_REQUIREMENTS = {
    "deepgram": "DEEPGRAM_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
    "sarvam": "SARVAM_API_KEY",
    "whisper": "OPENAI_API_KEY",
}


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_int(name: str, default: int) -> int:
    raw = env_str(name, str(default))
    try:
        return int(raw)
    except ValueError:
        return default


def env_csv(name: str) -> set[str]:
    raw = os.getenv(name, "")
    return {
        item.strip().lower()
        for item in raw.split(",")
        if item.strip()
    }


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _tool_dir() -> Path:
    return Path(__file__).resolve().parent / "tools"


def _registerable_tool_modules() -> list[str]:
    modules: list[str] = []
    for file_path in sorted(_tool_dir().glob("*.py")):
        if file_path.name == "__init__.py" or file_path.name.startswith("."):
            continue
        try:
            contents = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "def register(" in contents:
            modules.append(file_path.stem)
    return modules


def disabled_tool_modules() -> set[str]:
    disabled = env_csv("FRIDAY_DISABLED_TOOL_MODULES")
    if not env_bool("FRIDAY_ENABLE_CALENDAR_TOOL", False):
        disabled.add("calendar_tool")
    return disabled


def tool_module_enabled(module_name: str) -> bool:
    return module_name.strip().lower() not in disabled_tool_modules()


def enabled_tool_modules() -> list[str]:
    return [module for module in _registerable_tool_modules() if tool_module_enabled(module)]


def selected_voice_providers() -> dict[str, str]:
    return {
        "stt": env_str("STT_PROVIDER", "deepgram").lower() or "deepgram",
        "llm": env_str("LLM_PROVIDER", "openai").lower() or "openai",
        "tts": env_str("TTS_PROVIDER", "openai").lower() or "openai",
    }


def voice_provider_missing_keys() -> list[str]:
    missing: list[str] = []
    for stage, provider in selected_voice_providers().items():
        required_key = VOICE_PROVIDER_REQUIREMENTS.get(provider)
        if required_key and not env_str(required_key):
            missing.append(f"{stage}:{required_key}")
    return missing


def livekit_configured() -> bool:
    return all(env_str(name) for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"))


def openai_configured() -> bool:
    return bool(env_str(LOCAL_BROWSER_OPENAI_KEY))


def local_browser_llm_provider() -> str:
    return LOCAL_BROWSER_LLM_PROVIDER


def local_browser_llm_model() -> str:
    return env_str(LOCAL_BROWSER_LLM_MODEL, "gpt-4o") or "gpt-4o"


def _workspace_status() -> tuple[str, bool, str | None]:
    try:
        path = workspace_dir()
        probe = path / f".friday_probe_{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return str(path), True, None
    except Exception as exc:  # pragma: no cover - defensive fallback
        fallback = Path.cwd() / (env_str("FRIDAY_WORKSPACE_DIR", "workspace") or "workspace")
        return str(fallback), False, str(exc)


def local_browser_setup_issues() -> list[str]:
    issues: list[str] = []

    if not openai_configured():
        issues.append(
            "OPENAI_API_KEY is required for local browser chat and browser audio transcription."
        )

    _workspace_path, workspace_writable, workspace_error = _workspace_status()
    if not workspace_writable:
        issues.append(f"Workspace directory is not writable: {workspace_error}")

    return issues


def browser_automation_ready() -> bool:
    if not tool_module_enabled("browser"):
        return False
    return _module_available("playwright")


def desktop_control_ready() -> bool:
    if not all(tool_module_enabled(name) for name in ("apps", "operator", "system")):
        return False
    if platform.system() not in {"Windows", "Darwin", "Linux"}:
        return False
    return _module_available("pyautogui")


def voice_configured() -> bool:
    return not voice_provider_missing_keys()


def startup_warnings() -> list[str]:
    warnings: list[str] = []
    selected_providers = selected_voice_providers()
    workspace_path, _workspace_writable, _workspace_error = _workspace_status()
    configured_port = env_str("MCP_SERVER_PORT", "8000")

    if selected_providers["llm"] != LOCAL_BROWSER_LLM_PROVIDER:
        warnings.append(
            "Local browser mode always uses OpenAI chat today. "
            f"LLM_PROVIDER={selected_providers['llm']} only affects the optional friday_voice worker."
        )

    if configured_port and not configured_port.isdigit():
        warnings.append(
            f"MCP_SERVER_PORT={configured_port!r} is invalid. FRIDAY will fall back to port 8000."
        )

    missing_voice_keys = voice_provider_missing_keys()
    if missing_voice_keys:
        warnings.append(
            "Optional legacy voice mode is not fully configured: missing "
            + ", ".join(missing_voice_keys)
            + "."
        )
    if not livekit_configured():
        warnings.append(
            "Optional legacy voice mode also needs LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET."
        )

    if not browser_automation_ready():
        if not tool_module_enabled("browser"):
            warnings.append(
                "Browser automation tools are disabled by FRIDAY_DISABLED_TOOL_MODULES."
            )
        else:
            warnings.append(
                "Playwright browser automation is not ready. "
                "Install dependencies with `uv sync` and browser binaries with `playwright install chromium`."
            )

    system_name = platform.system()
    if system_name == "Darwin":
        warnings.append(
            "Desktop control on macOS may need Screen Recording and Accessibility permission. "
            "Run `uv run friday_healthcheck --desktop` or the run_permission_diagnostics tool."
        )
    elif system_name == "Linux":
        warnings.append(
            "Desktop control on Linux depends on display-server permissions and helper tools such as scrot or wmctrl."
        )
    elif system_name == "Windows":
        warnings.append(
            "Administrator-only desktop or shell actions still require launching FRIDAY from an elevated terminal."
        )

    if workspace_path:
        warnings.append(
            f"Workspace artifacts, logs, and generated files are stored under: {workspace_path}"
        )

    return warnings


def next_steps() -> list[str]:
    steps: list[str] = []

    if not openai_configured():
        steps.append("Set OPENAI_API_KEY in `.env`, then restart `uv run friday`.")
    else:
        steps.append("Start the app with `uv run friday`, then open http://127.0.0.1:8000/.")

    if not browser_automation_ready():
        steps.append("Install browser automation support with `uv sync` and `playwright install chromium`.")

    if voice_provider_missing_keys() or not livekit_configured():
        steps.append(
            "If you want the optional `uv run friday_voice` mode, configure the selected STT/LLM/TTS provider keys and LiveKit credentials."
        )

    if platform.system() in {"Darwin", "Linux"}:
        steps.append("Run `uv run friday_healthcheck --desktop` to validate desktop-control permissions.")

    steps.append("Run `uv run friday_healthcheck` for a full local setup report.")

    # Preserve order while removing duplicates.
    return list(dict.fromkeys(steps))


def build_runtime_status(*, mode: str = LOCAL_BROWSER_MODE) -> dict[str, Any]:
    workspace_path, workspace_writable, workspace_error = _workspace_status()
    issues = local_browser_setup_issues()
    warnings = startup_warnings()
    enabled_modules = enabled_tool_modules()
    disabled_modules = sorted(disabled_tool_modules())

    status = {
        "app_ready": not issues,
        "server_name": env_str("SERVER_NAME", "Friday") or "Friday",
        "mode": mode,
        "host": env_str("MCP_SERVER_HOST", "0.0.0.0") or "0.0.0.0",
        "port": env_int("MCP_SERVER_PORT", 8000),
        "workspace_path": workspace_path,
        "workspace_writable": workspace_writable,
        "workspace_error": workspace_error,
        "python_version": sys.version.split()[0],
        "os": platform.platform(),
        "llm_provider": local_browser_llm_provider(),
        "llm_model": local_browser_llm_model(),
        "openai_configured": openai_configured(),
        "voice_configured": voice_configured(),
        "legacy_livekit_configured": livekit_configured(),
        "browser_automation_ready": browser_automation_ready(),
        "desktop_control_ready": desktop_control_ready(),
        "enabled_tool_modules": enabled_modules,
        "disabled_tool_modules": disabled_modules,
        "setup_issues": issues,
        "warnings": warnings,
        "next_steps": next_steps(),
        # Compatibility fields used by the current web UI and healthcheck.
        "ready": not issues,
        "issues": issues,
        "voice_providers": selected_voice_providers(),
        "voice_missing_keys": voice_provider_missing_keys(),
    }
    return status


class Config:
    @property
    def SERVER_NAME(self) -> str:
        return env_str("SERVER_NAME", "Friday") or "Friday"

    @property
    def DEBUG(self) -> bool:
        return env_bool("DEBUG", False)

    @property
    def OPENAI_API_KEY(self) -> str:
        return env_str("OPENAI_API_KEY")

    @property
    def SERVER_HOST(self) -> str:
        return env_str("MCP_SERVER_HOST", "0.0.0.0") or "0.0.0.0"

    @property
    def SERVER_PORT(self) -> int:
        return env_int("MCP_SERVER_PORT", 8000)

    @property
    def SERVER_MOUNT_PATH(self) -> str:
        return env_str("MCP_MOUNT_PATH", "/") or "/"

    @property
    def SERVER_SSE_PATH(self) -> str:
        return env_str("MCP_SSE_PATH", "/sse") or "/sse"

    @property
    def SERVER_INSTRUCTIONS(self) -> str:
        return env_str(
            "SERVER_INSTRUCTIONS",
            "I am F.R.I.D.A.Y., a Tony Stark-style AI assistant. "
            "I have access to a comprehensive set of tools. "
            "Be concise, accurate, and a little witty.",
        )


config = Config()
