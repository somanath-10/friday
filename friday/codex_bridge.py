"""
VS Code Codex relay helpers for FRIDAY.

This module builds a compact local project snapshot and can dispatch a prompt
into the OpenAI Codex VS Code extension by driving VS Code on the host machine.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from friday.path_utils import resolve_user_path, workspace_dir


OS = platform.system()

IGNORED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    ".next",
    ".turbo",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".uv-cache",
    ".idea",
    ".vscode-test",
    ".playwright",
    ".cache",
    "coverage",
    "tmp",
    "temp",
}

KEY_FILE_CANDIDATES = (
    "README.md",
    "pyproject.toml",
    "package.json",
    "requirements.txt",
    "Pipfile",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "server.py",
    "main.py",
    "app.py",
    "manage.py",
)

MAX_TREE_DEPTH = int(os.getenv("FRIDAY_CODEX_TREE_DEPTH", "2"))
MAX_TREE_LINES = int(os.getenv("FRIDAY_CODEX_TREE_LINES", "120"))
MAX_EXCERPT_CHARS = int(os.getenv("FRIDAY_CODEX_EXCERPT_CHARS", "900"))
MAX_SNAPSHOT_CHARS = int(os.getenv("FRIDAY_CODEX_MAX_SNAPSHOT_CHARS", "5000"))
MAX_KEY_FILES = int(os.getenv("FRIDAY_CODEX_MAX_KEY_FILES", "12"))


@dataclass
class ProjectSnapshot:
    project_path: str
    file_count: int
    directory_count: int
    top_extensions: list[dict[str, Any]]
    key_files: list[str]
    tree_preview: list[str]
    excerpt_map: dict[str, str]
    summary: str


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _powershell(script: str, timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _load_pyautogui():
    import pyautogui

    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0
    return pyautogui


def _normalize_hotkey_part(value: str) -> str:
    base = value.strip().lower()
    command_key = "win" if OS == "Windows" else "command"
    option_key = "option" if OS == "Darwin" else "alt"
    lookup = {
        "control": "ctrl",
        "ctl": "ctrl",
        "return": "enter",
        "escape": "esc",
        "command": command_key,
        "cmd": command_key,
        "windows": "win",
        "super": "win",
        "meta": "win",
        "option": option_key,
        "pgup": "pageup",
        "pgdn": "pagedown",
        "page_up": "pageup",
        "page_down": "pagedown",
        "spacebar": "space",
        "del": "delete",
        "ins": "insert",
    }
    return lookup.get(base, base)


def _windows_sendkeys_token(value: str) -> str:
    normalized = _normalize_hotkey_part(value)
    named = {
        "enter": "{ENTER}",
        "esc": "{ESC}",
        "tab": "{TAB}",
        "up": "{UP}",
        "down": "{DOWN}",
        "left": "{LEFT}",
        "right": "{RIGHT}",
        "home": "{HOME}",
        "end": "{END}",
        "delete": "{DELETE}",
        "backspace": "{BACKSPACE}",
        "pagedown": "{PGDN}",
        "pageup": "{PGUP}",
        "space": " ",
        "insert": "{INSERT}",
    }
    if normalized in named:
        return named[normalized]
    if normalized.startswith("f") and normalized[1:].isdigit():
        return "{" + normalized.upper() + "}"
    return normalized


def _windows_sendkeys_combo(value: str) -> str:
    parts = [_normalize_hotkey_part(part) for part in value.split("+") if part.strip()]
    if not parts:
        return ""

    modifier_map = {
        "ctrl": "^",
        "alt": "%",
        "shift": "+",
    }
    modifiers = [modifier_map[part] for part in parts if part in modifier_map]
    keys = [part for part in parts if part not in modifier_map and part != "win"]

    if not keys:
        keys = [parts[-1]]

    return "".join(modifiers) + "".join(_windows_sendkeys_token(part) for part in keys)


def _windows_paste_text(text: str, press_enter: bool) -> None:
    ps_script = (
        "$previous = Get-Clipboard -Raw -ErrorAction SilentlyContinue; "
        f"Set-Clipboard -Value {_ps_quote(text)}; "
        "Add-Type -AssemblyName System.Windows.Forms; "
        "[System.Windows.Forms.SendKeys]::SendWait('^v'); "
        + ("[System.Windows.Forms.SendKeys]::SendWait('{ENTER}'); " if press_enter else "")
        + "Start-Sleep -Milliseconds 50; "
        "if ($null -ne $previous) { Set-Clipboard -Value $previous }"
    )
    result = _powershell(ps_script, timeout=10)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Clipboard paste into VS Code failed.")


def _press_hotkey(hotkey: str) -> None:
    parts = [_normalize_hotkey_part(part) for part in hotkey.split("+") if part.strip()]
    if not parts:
        return

    try:
        pyautogui = _load_pyautogui()
        if len(parts) == 1:
            pyautogui.press(parts[0])
        else:
            pyautogui.hotkey(*parts)
        return
    except Exception:
        pass

    if OS == "Windows":
        send_keys = _windows_sendkeys_combo(hotkey)
        if not send_keys:
            raise RuntimeError(f"Unsupported key combination: {hotkey}")
        result = _powershell(
            f"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait({_ps_quote(send_keys)})",
            timeout=5,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"Unable to send hotkey: {hotkey}")
        return

    raise RuntimeError(f"Unable to send hotkey: {hotkey}")


def _paste_text(text: str, press_enter: bool = False) -> None:
    if OS == "Windows":
        _windows_paste_text(text, press_enter=press_enter)
        return

    pyautogui = _load_pyautogui()
    pyautogui.write(text, interval=0.01)
    if press_enter:
        pyautogui.press("enter")


def _command_palette_hotkey() -> str:
    if OS == "Darwin":
        return "command+shift+p"
    return "ctrl+shift+p"


def _resolve_project_path(project_path: str = "") -> Path:
    raw = project_path.strip() or os.getenv("FRIDAY_CODEX_PROJECT_DIR", "").strip()
    if not raw:
        return Path.cwd().resolve()
    return resolve_user_path(raw, base=Path.cwd()).resolve()


def _vscode_executable() -> str:
    configured = os.getenv("FRIDAY_CODEX_VSCODE_EXECUTABLE", "").strip()
    if configured:
        return configured

    detected = shutil.which("code")
    if detected:
        return detected

    if OS == "Windows":
        default_path = Path.home() / "AppData" / "Local" / "Programs" / "Microsoft VS Code" / "Code.exe"
        if default_path.exists():
            return str(default_path)

    return ""


def _extension_manifest_path() -> Path | None:
    roots = []
    userprofile = os.environ.get("USERPROFILE", "").strip()
    if userprofile:
        roots.append(Path(userprofile) / ".vscode" / "extensions")
    roots.append(Path.home() / ".vscode" / "extensions")

    for root in roots:
        if not root.exists():
            continue
        candidates = sorted(
            root.glob("openai.chatgpt-*"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for candidate in candidates:
            manifest = candidate / "package.json"
            if manifest.exists():
                return manifest
    return None


def _load_extension_manifest() -> dict[str, Any] | None:
    manifest_path = _extension_manifest_path()
    if manifest_path is None:
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _command_label_from_manifest(manifest: dict[str, Any] | None, command_id: str, fallback: str) -> str:
    if manifest:
        for item in manifest.get("contributes", {}).get("commands", []) or []:
            if item.get("command") != command_id:
                continue
            title = str(item.get("title", "")).strip()
            category = str(item.get("category", "")).strip()
            if title and category:
                return f"{category}: {title}"
            if title:
                return title
    return fallback


def _codex_sidebar_command(manifest: dict[str, Any] | None = None) -> str:
    configured = os.getenv("FRIDAY_CODEX_OPEN_SIDEBAR_COMMAND", "").strip()
    if configured:
        return configured
    return _command_label_from_manifest(
        manifest,
        "chatgpt.openSidebar",
        "Codex: Open Codex Sidebar",
    )


def _codex_new_thread_command(manifest: dict[str, Any] | None = None) -> str:
    configured = os.getenv("FRIDAY_CODEX_NEW_THREAD_COMMAND", "").strip()
    if configured:
        return configured
    return _command_label_from_manifest(
        manifest,
        "chatgpt.newChat",
        "Codex: New Thread in Codex Sidebar",
    )


def codex_relay_status(project_path: str = "") -> dict[str, Any]:
    project_root = _resolve_project_path(project_path)
    vscode_executable = _vscode_executable()
    manifest = _load_extension_manifest()
    issues: list[str] = []

    if not project_root.exists():
        issues.append(f"Project path does not exist: {project_root}")
    elif not project_root.is_dir():
        issues.append(f"Project path is not a folder: {project_root}")

    if not vscode_executable:
        issues.append("VS Code executable was not found. Set FRIDAY_CODEX_VSCODE_EXECUTABLE or install the `code` launcher.")

    if manifest is None:
        issues.append("The OpenAI Codex VS Code extension is not installed in ~/.vscode/extensions.")

    return {
        "ready": not issues,
        "issues": issues,
        "project_path": str(project_root),
        "vscode_executable": vscode_executable,
        "vscode_cli_available": bool(vscode_executable),
        "extension_installed": manifest is not None,
        "extension_display_name": str((manifest or {}).get("displayName", "Codex")),
        "open_sidebar_command": _codex_sidebar_command(manifest),
        "new_thread_command": _codex_new_thread_command(manifest),
        "snapshot_enabled": _truthy(os.getenv("FRIDAY_CODEX_INCLUDE_PROJECT_SNAPSHOT"), default=True),
    }


def _skip_file(filename: str) -> bool:
    lowered = filename.lower()
    return lowered in {".ds_store", "thumbs.db"}


def _read_excerpt(path: Path) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    text = raw.strip()
    if not text:
        return ""
    if len(text) > MAX_EXCERPT_CHARS:
        text = text[: MAX_EXCERPT_CHARS - 28].rstrip() + "\n... [excerpt truncated]"
    return text


def _collect_tree(root: Path) -> tuple[int, int, dict[str, int], list[str]]:
    file_count = 0
    directory_count = 0
    extension_counts: dict[str, int] = {}
    tree_lines: list[str] = []

    for current_root, dirs, files in os.walk(root):
        dirs[:] = sorted(
            directory
            for directory in dirs
            if directory not in IGNORED_DIR_NAMES and not directory.startswith(".pytest")
        )
        files = sorted(files)

        rel_root = Path(current_root).relative_to(root)
        depth = len(rel_root.parts)
        directory_count += len(dirs)

        if depth <= MAX_TREE_DEPTH and len(tree_lines) < MAX_TREE_LINES:
            label = "." if depth == 0 else rel_root.name
            tree_lines.append(f"{'  ' * depth}{label}/")

        for filename in files:
            if _skip_file(filename):
                continue
            file_count += 1
            extension = Path(filename).suffix.lower() or "[no extension]"
            extension_counts[extension] = extension_counts.get(extension, 0) + 1

            if depth <= MAX_TREE_DEPTH and len(tree_lines) < MAX_TREE_LINES:
                tree_lines.append(f"{'  ' * (depth + 1)}{filename}")

    return file_count, directory_count, extension_counts, tree_lines


def _existing_key_files(root: Path) -> list[str]:
    key_files: list[str] = []

    for relative in KEY_FILE_CANDIDATES:
        candidate = root / relative
        if candidate.exists() and candidate.is_file():
            key_files.append(relative.replace("\\", "/"))
        if len(key_files) >= MAX_KEY_FILES:
            return key_files

    for candidate in sorted(root.glob("*.py")):
        rel_path = candidate.relative_to(root).as_posix()
        if rel_path not in key_files:
            key_files.append(rel_path)
        if len(key_files) >= MAX_KEY_FILES:
            break

    return key_files


def build_project_snapshot(project_path: str = "") -> ProjectSnapshot:
    root = _resolve_project_path(project_path)
    if not root.exists():
        raise RuntimeError(f"Project path does not exist: {root}")
    if not root.is_dir():
        raise RuntimeError(f"Project path is not a folder: {root}")

    file_count, directory_count, extension_counts, tree_preview = _collect_tree(root)
    key_files = _existing_key_files(root)
    excerpt_map = {
        relative: excerpt
        for relative in key_files[:4]
        if (excerpt := _read_excerpt(root / relative))
    }

    top_extensions = [
        {"extension": extension, "count": count}
        for extension, count in sorted(
            extension_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:8]
    ]

    lines = [
        f"Project root: {root}",
        f"Files scanned: {file_count}",
        f"Directories scanned: {directory_count}",
    ]

    if top_extensions:
        extension_text = ", ".join(f"{item['extension']} ({item['count']})" for item in top_extensions)
        lines.append(f"Most common file types: {extension_text}")

    if key_files:
        lines.append("")
        lines.append("Key files:")
        lines.extend(f"- {relative}" for relative in key_files)

    if tree_preview:
        lines.append("")
        lines.append("Project tree preview:")
        lines.append("```text")
        lines.extend(tree_preview)
        lines.append("```")

    for relative, excerpt in excerpt_map.items():
        lines.append("")
        lines.append(f"{relative} excerpt:")
        lines.append("```text")
        lines.append(excerpt)
        lines.append("```")

    summary = "\n".join(lines).strip()
    if len(summary) > MAX_SNAPSHOT_CHARS:
        summary = summary[: MAX_SNAPSHOT_CHARS - 34].rstrip() + "\n\n... [snapshot truncated]"

    return ProjectSnapshot(
        project_path=str(root),
        file_count=file_count,
        directory_count=directory_count,
        top_extensions=top_extensions,
        key_files=key_files,
        tree_preview=tree_preview,
        excerpt_map=excerpt_map,
        summary=summary,
    )


def compose_codex_prompt(
    user_request: str,
    *,
    project_path: str = "",
    include_project_snapshot: bool | None = None,
) -> dict[str, Any]:
    if not user_request.strip():
        raise RuntimeError("User request is empty.")

    snapshot_enabled = (
        _truthy(os.getenv("FRIDAY_CODEX_INCLUDE_PROJECT_SNAPSHOT"), default=True)
        if include_project_snapshot is None
        else include_project_snapshot
    )
    snapshot = build_project_snapshot(project_path) if snapshot_enabled else None
    resolved_project = snapshot.project_path if snapshot else str(_resolve_project_path(project_path))

    prompt_sections = [
        "You are working through the VS Code Codex extension.",
        f"Target project folder: {resolved_project}",
        "Before making changes, inspect the relevant files in that folder yourself.",
    ]

    preamble = os.getenv("FRIDAY_CODEX_PROMPT_PREAMBLE", "").strip()
    if preamble:
        prompt_sections.append(preamble)

    if snapshot is not None:
        prompt_sections.append("FRIDAY-generated project snapshot for fast orientation:")
        prompt_sections.append(snapshot.summary)

    prompt_sections.append("User request:")
    prompt_sections.append(user_request.strip())
    prompt_sections.append("Carry the task through inside this project and explain the result in Codex when you are done.")

    prompt_text = "\n\n".join(section.strip() for section in prompt_sections if section and section.strip())
    return {
        "project_path": resolved_project,
        "snapshot_enabled": snapshot is not None,
        "snapshot": asdict(snapshot) if snapshot is not None else None,
        "prompt": prompt_text,
    }


def _save_dispatch_artifacts(prompt_payload: dict[str, Any]) -> dict[str, str]:
    dispatch_dir = workspace_dir() / "codex_dispatches"
    dispatch_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_name = Path(prompt_payload["project_path"]).name or "project"
    safe_name = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in project_name).strip("_") or "project"

    prompt_path = dispatch_dir / f"prompt_{stamp}_{safe_name}.md"
    prompt_path.write_text(prompt_payload["prompt"], encoding="utf-8")

    saved = {"prompt_path": str(prompt_path)}

    snapshot = prompt_payload.get("snapshot")
    if snapshot:
        snapshot_path = dispatch_dir / f"snapshot_{stamp}_{safe_name}.md"
        snapshot_path.write_text(str(snapshot.get("summary", "")).strip(), encoding="utf-8")
        saved["snapshot_path"] = str(snapshot_path)

    return saved


def _launch_vscode(project_root: Path) -> None:
    executable = _vscode_executable()
    if not executable:
        raise RuntimeError("VS Code executable not found.")

    args = [executable]
    name = Path(executable).name.lower()
    if name.startswith("code"):
        args.extend(["-r", str(project_root)])
    else:
        args.append(str(project_root))

    subprocess.Popen(
        args,
        cwd=project_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _focus_vscode(project_root: Path) -> None:
    if OS == "Darwin":
        subprocess.run(
            ["osascript", "-e", 'tell application "Visual Studio Code" to activate'],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return

    if OS == "Linux":
        subprocess.run(
            ["wmctrl", "-a", "code"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return

    title_hint = _ps_quote(project_root.name)
    ps_script = f"""
$hint = {title_hint}
$targets = Get-Process Code -ErrorAction SilentlyContinue |
  Where-Object {{ $_.MainWindowTitle -and $_.MainWindowTitle.Trim() -ne '' }}
if ($targets) {{
  $preferred = $targets | Where-Object {{ $_.MainWindowTitle -like "*$hint*" }} | Select-Object -First 1
  if (-not $preferred) {{
    $preferred = $targets | Select-Object -First 1
  }}
  if ($preferred) {{
    $wshell = New-Object -ComObject WScript.Shell
    if ($wshell.AppActivate($preferred.Id)) {{
      Write-Output $preferred.MainWindowTitle
      exit 0
    }}
  }}
}}
exit 1
"""
    result = _powershell(ps_script, timeout=10)
    if result.returncode != 0:
        raise RuntimeError("Unable to focus the VS Code window.")


def _run_palette_command(label: str) -> None:
    _press_hotkey(_command_palette_hotkey())
    time.sleep(0.25)
    _paste_text(label, press_enter=True)


def dispatch_to_vscode_codex(
    user_request: str,
    *,
    project_path: str = "",
    include_project_snapshot: bool | None = None,
    press_enter: bool = True,
) -> dict[str, Any]:
    status = codex_relay_status(project_path)
    if not status["ready"]:
        raise RuntimeError("; ".join(status["issues"]))

    prompt_payload = compose_codex_prompt(
        user_request,
        project_path=project_path,
        include_project_snapshot=include_project_snapshot,
    )
    saved = _save_dispatch_artifacts(prompt_payload)

    project_root = Path(prompt_payload["project_path"])
    _launch_vscode(project_root)

    launch_wait = max(250, int(os.getenv("FRIDAY_CODEX_LAUNCH_WAIT_MS", "1600")))
    command_wait = max(150, int(os.getenv("FRIDAY_CODEX_COMMAND_WAIT_MS", "700")))
    time.sleep(launch_wait / 1000.0)

    _focus_vscode(project_root)
    time.sleep(command_wait / 1000.0)
    _run_palette_command(status["open_sidebar_command"])
    time.sleep(command_wait / 1000.0)
    _run_palette_command(status["new_thread_command"])
    time.sleep(command_wait / 1000.0)
    _paste_text(prompt_payload["prompt"], press_enter=press_enter)

    message = (
        f"Sent your request to VS Code Codex for {project_root}. "
        f"Prompt saved to {saved['prompt_path']}."
    )
    if "snapshot_path" in saved:
        message += f" Project snapshot saved to {saved['snapshot_path']}."

    return {
        "ok": True,
        "reply": message,
        "project_path": str(project_root),
        "prompt_path": saved["prompt_path"],
        "snapshot_path": saved.get("snapshot_path", ""),
        "prompt_preview": prompt_payload["prompt"][:700],
        "snapshot_enabled": prompt_payload["snapshot_enabled"],
    }
