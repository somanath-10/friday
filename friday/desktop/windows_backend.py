"""
Windows desktop backend using UI Automation, PowerShell, and shell launchers.
"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from friday.subprocess_utils import run_powershell


WINDOWS_ONLY_MESSAGE = "This desktop-control feature is currently implemented for Windows only."

WINDOWS_APP_ALIASES: dict[str, tuple[str, ...]] = {
    "notepad": ("notepad.exe",),
    "calculator": ("calc.exe",),
    "calc": ("calc.exe",),
    "file explorer": ("explorer.exe",),
    "explorer": ("explorer.exe",),
    "chrome": ("chrome.exe",),
    "google chrome": ("chrome.exe",),
    "edge": ("msedge.exe",),
    "microsoft edge": ("msedge.exe",),
    "powershell": ("powershell.exe",),
    "command prompt": ("cmd.exe",),
    "cmd": ("cmd.exe",),
    "terminal": ("wt.exe", "powershell.exe"),
    "vscode": ("Code.exe",),
    "visual studio code": ("Code.exe",),
}


@dataclass(frozen=True)
class ResolvedApplication:
    requested_name: str
    display_name: str
    executable: str
    available: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WindowsDesktopStatus:
    is_windows: bool
    windows_version: str
    pywinauto_available: bool
    pyautogui_available: bool
    powershell_available: bool
    chrome_available: bool
    edge_available: bool
    setup_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _module_available(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def _windows_program_files_roots() -> list[Path]:
    roots: list[Path] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        value = os.environ.get(env_name, "").strip()
        if value:
            roots.append(Path(value))
    return roots


def _candidate_windows_paths(executable: str) -> list[Path]:
    lower = executable.lower()
    candidates: list[Path] = []
    if lower == "chrome.exe":
        for root in _windows_program_files_roots():
            if root.name.lower() == "localappdata":
                candidates.append(root / "Google" / "Chrome" / "Application" / "chrome.exe")
            else:
                candidates.append(root / "Google" / "Chrome" / "Application" / "chrome.exe")
    elif lower == "msedge.exe":
        for root in _windows_program_files_roots():
            candidates.append(root / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    elif lower == "code.exe":
        for root in _windows_program_files_roots():
            if root.name.lower() == "localappdata":
                candidates.append(root / "Programs" / "Microsoft VS Code" / "Code.exe")
            else:
                candidates.append(root / "Microsoft VS Code" / "Code.exe")
    elif lower == "wt.exe":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            candidates.append(
                Path(local_app_data)
                / "Microsoft"
                / "WindowsApps"
                / "wt.exe"
            )
    return candidates


def _find_windows_executable(executable: str) -> str:
    direct = shutil.which(executable)
    if direct:
        return direct
    for candidate in _candidate_windows_paths(executable):
        if candidate.exists():
            return str(candidate)
    return ""


def resolve_windows_application(app_name: str) -> ResolvedApplication:
    requested = app_name.strip() or "application"
    normalized = requested.lower()
    candidates = WINDOWS_APP_ALIASES.get(normalized, (requested,))
    for executable in candidates:
        resolved = _find_windows_executable(executable)
        if resolved:
            return ResolvedApplication(requested, executable, resolved, True)
    fallback = candidates[0]
    return ResolvedApplication(requested, fallback, fallback, bool(shutil.which(fallback)))


def chrome_available() -> bool:
    return bool(_find_windows_executable("chrome.exe"))


def edge_available() -> bool:
    return bool(_find_windows_executable("msedge.exe"))


def powershell_available() -> bool:
    return bool(_find_windows_executable("powershell.exe") or shutil.which("powershell"))


def pywinauto_available() -> bool:
    return _module_available("pywinauto")


def pyautogui_available() -> bool:
    return _module_available("pyautogui")


def desktop_windows_status() -> WindowsDesktopStatus:
    is_windows = _is_windows()
    issues: list[str] = []
    warnings: list[str] = []
    if not is_windows:
        warnings.append(WINDOWS_ONLY_MESSAGE)
        return WindowsDesktopStatus(
            is_windows=False,
            windows_version="",
            pywinauto_available=False,
            pyautogui_available=False,
            powershell_available=False,
            chrome_available=False,
            edge_available=False,
            setup_issues=issues,
            warnings=warnings,
        )

    pw = powershell_available()
    pyw = pywinauto_available()
    pyg = pyautogui_available()
    if not pw:
        issues.append("PowerShell was not found on PATH; Windows automation helpers will be limited.")
    if not pyw:
        warnings.append("pywinauto is not installed; FRIDAY will rely on PowerShell and PyAutoGUI fallbacks.")
    if not pyg:
        warnings.append("pyautogui is not installed; cursor typing/click fallback is unavailable.")
    if not chrome_available():
        warnings.append("Chrome was not detected in common Windows locations.")
    if not edge_available():
        warnings.append("Edge was not detected in common Windows locations.")

    return WindowsDesktopStatus(
        is_windows=True,
        windows_version=platform.version(),
        pywinauto_available=pyw,
        pyautogui_available=pyg,
        powershell_available=pw,
        chrome_available=chrome_available(),
        edge_available=edge_available(),
        setup_issues=issues,
        warnings=warnings,
    )


class WindowsBackend:
    name = "windows"
    unsupported_message = WINDOWS_ONLY_MESSAGE

    def _unsupported(self) -> dict[str, Any]:
        return {"ok": False, "message": self.unsupported_message}

    def _pywinauto_active_window(self) -> dict[str, Any]:
        try:
            from pywinauto import Desktop  # type: ignore

            window = Desktop(backend="uia").get_active()
            title = ""
            try:
                title = window.window_text()
            except Exception:
                title = ""
            process_id = None
            try:
                process_id = window.process_id()
            except Exception:
                process_id = None
            process_name = ""
            if process_id:
                ps_script = (
                    f"$p = Get-Process -Id {int(process_id)} -ErrorAction SilentlyContinue; "
                    "if ($p) { $p.ProcessName }"
                )
                result = run_powershell(ps_script, timeout=5)
                process_name = result.stdout.strip()
            return {"ok": True, "title": title, "app": process_name, "pid": process_id or 0}
        except Exception:
            return {"ok": False, "title": "", "app": "", "pid": 0}

    def open_application(self, app_name: str) -> dict[str, Any]:
        if not _is_windows():
            return self._unsupported()
        resolved = resolve_windows_application(app_name)
        command = resolved.executable or resolved.display_name
        try:
            subprocess.Popen([command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"ok": True, "message": f"Opened {resolved.requested_name}.", "app": resolved.display_name}
        except Exception:
            try:
                result = subprocess.run(
                    ["cmd", "/c", "start", "", command],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                ok = result.returncode == 0
                return {
                    "ok": ok,
                    "message": f"Opened {resolved.requested_name}." if ok else (result.stderr.strip() or result.stdout.strip() or f"Could not open {app_name}."),
                    "app": resolved.display_name,
                }
            except Exception as exc:
                return {"ok": False, "message": f"Could not open {app_name}: {exc}", "app": resolved.display_name}

    def focus_application(self, app_name: str) -> dict[str, Any]:
        if not _is_windows():
            return self._unsupported()
        if pywinauto_available():
            try:
                from pywinauto import Desktop  # type: ignore

                needle = app_name.lower()
                for window in Desktop(backend="uia").windows():
                    title = ""
                    try:
                        title = window.window_text()
                    except Exception:
                        title = ""
                    if needle in title.lower():
                        window.set_focus()
                        return {"ok": True, "message": f"Focused {app_name}."}
            except Exception:
                pass

        script = f"""
$wshell = New-Object -ComObject WScript.Shell
$ok = $wshell.AppActivate('{app_name.replace("'", "''")}')
Write-Output $ok
"""
        result = run_powershell(script, timeout=10)
        ok = "true" in result.stdout.lower()
        return {"ok": ok, "message": f"Focused {app_name}." if ok else (result.stderr.strip() or result.stdout.strip() or f"Could not focus {app_name}.")}

    def close_application(self, app_name: str) -> dict[str, Any]:
        if not _is_windows():
            return self._unsupported()
        resolved = resolve_windows_application(app_name)
        process_name = Path(resolved.display_name).stem.replace("'", "''")
        script = f"Get-Process -Name '{process_name}' -ErrorAction SilentlyContinue | Stop-Process"
        result = run_powershell(script, timeout=10)
        return {
            "ok": result.returncode == 0,
            "message": f"Requested {app_name} close." if result.returncode == 0 else (result.stderr.strip() or result.stdout.strip() or f"Could not close {app_name}."),
        }

    def list_open_windows(self) -> list[dict[str, Any]]:
        if not _is_windows():
            return []
        script = """
Get-Process |
  Where-Object { $_.MainWindowTitle -and $_.MainWindowTitle.Trim() -ne '' } |
  Select-Object ProcessName,MainWindowTitle,Id |
  ConvertTo-Json -Compress
"""
        result = run_powershell(script, timeout=10)
        if result.returncode != 0 or not result.stdout.strip():
            return []
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []
        rows = parsed if isinstance(parsed, list) else [parsed]
        return [
            {
                "app": str(row.get("ProcessName", "")),
                "title": str(row.get("MainWindowTitle", "")),
                "pid": int(row.get("Id", 0) or 0),
            }
            for row in rows
            if isinstance(row, dict)
        ]

    def get_active_window(self) -> dict[str, Any]:
        if not _is_windows():
            return {"ok": False, "title": "", "app": "", "message": self.unsupported_message}

        preferred = self._pywinauto_active_window()
        if preferred.get("ok"):
            return preferred

        script = r"""
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class FridayUser32 {
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
}
"@
$hwnd = [FridayUser32]::GetForegroundWindow()
if ($hwnd -eq [IntPtr]::Zero) {
  [PSCustomObject]@{ app=''; title=''; pid=0; ok=$false; message='No active window detected.' } | ConvertTo-Json -Compress
  exit 0
}
$builder = New-Object System.Text.StringBuilder 1024
[void][FridayUser32]::GetWindowText($hwnd, $builder, $builder.Capacity)
$pid = 0
[void][FridayUser32]::GetWindowThreadProcessId($hwnd, [ref]$pid)
$proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
[PSCustomObject]@{
  app = if ($proc) { $proc.ProcessName } else { '' }
  title = $builder.ToString()
  pid = $pid
  ok = $true
  message = ''
} | ConvertTo-Json -Compress
"""
        result = run_powershell(script, timeout=10)
        if result.returncode != 0 or not result.stdout.strip():
            return {"ok": False, "title": "", "app": "", "message": result.stderr.strip() or "Active window detection failed."}
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"ok": False, "title": "", "app": "", "message": "Active window detection returned invalid data."}
        if not isinstance(payload, dict):
            return {"ok": False, "title": "", "app": "", "message": "Active window detection returned invalid payload."}
        return {
            "ok": bool(payload.get("ok", True)),
            "title": str(payload.get("title", "")),
            "app": str(payload.get("app", "")),
            "pid": int(payload.get("pid", 0) or 0),
            "message": str(payload.get("message", "")),
        }

    def list_installed_apps(self) -> list[dict[str, Any]]:
        if not _is_windows():
            return []
        rows: list[dict[str, Any]] = []
        for alias in ("notepad", "calculator", "file explorer", "chrome", "edge", "powershell", "cmd", "terminal", "vscode"):
            resolved = resolve_windows_application(alias)
            rows.append(
                {
                    "name": alias,
                    "path": resolved.executable if resolved.available else "",
                    "available": resolved.available,
                }
            )
        return rows
