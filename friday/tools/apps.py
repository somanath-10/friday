"""
Apps & System Control tools — open applications, take screenshots,
manage clipboard, send notifications, and set timers.
Supports: macOS, Linux, and Windows.
"""

import json
import subprocess
import os
import threading
import time
import platform
from pathlib import Path

from friday.path_utils import safe_filename, workspace_dir, workspace_path

OS = platform.system()  # "Darwin" | "Linux" | "Windows"


def _workspace_dir() -> str:
    return str(workspace_dir())


def _escape_applescript_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _powershell(script: str, timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _load_json_records(raw: str) -> list[dict]:
    text = raw.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        return [parsed]
    return []


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


def _windows_paste_text(text: str, press_enter: bool) -> str:
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
        raise RuntimeError(result.stderr.strip() or "Windows clipboard paste fallback failed")
    return f"Typed {len(text)} characters" + (" and pressed Enter." if press_enter else ".")


def _windows_search_results(query: str, limit: int = 20) -> list[str]:
    escaped_query = _ps_quote(query)
    ps_script = f"""
$query = {escaped_query}
$pattern = "*$query*"
$limit = {int(limit)}
$results = New-Object System.Collections.Generic.List[string]
function Add-Result([string]$value) {{
  if (-not [string]::IsNullOrWhiteSpace($value) -and -not $results.Contains($value)) {{
    $results.Add($value)
  }}
}}

$cmd = Get-Command -Name $query -ErrorAction SilentlyContinue | Select-Object -First 1
if ($cmd) {{ Add-Result $cmd.Source }}

$startMenuDirs = @(
  "$env:ProgramData\\Microsoft\\Windows\\Start Menu\\Programs",
  "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs"
)
foreach ($dir in $startMenuDirs) {{
  if (Test-Path $dir) {{
    Get-ChildItem -Path $dir -Recurse -Include *.lnk,*.appref-ms -ErrorAction SilentlyContinue |
      Where-Object {{ $_.BaseName -like $pattern }} |
      Select-Object -First $limit |
      ForEach-Object {{ Add-Result $_.FullName }}
  }}
}}

$searchRoots = @(
  "$env:LOCALAPPDATA\\Programs",
  "$env:ProgramFiles",
  "${{env:ProgramFiles(x86)}}",
  "$env:LOCALAPPDATA\\Microsoft\\WindowsApps"
)
foreach ($dir in $searchRoots) {{
  if (Test-Path $dir) {{
    Get-ChildItem -Path $dir -Recurse -Depth 3 -Filter "*$query*.exe" -File -ErrorAction SilentlyContinue |
      Select-Object -First $limit |
      ForEach-Object {{ Add-Result $_.FullName }}
  }}
}}

$uninstallKeys = @(
  "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*",
  "HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*",
  "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*"
)
foreach ($key in $uninstallKeys) {{
  Get-ItemProperty -Path $key -ErrorAction SilentlyContinue |
    Where-Object {{ $_.DisplayName -like $pattern }} |
    Select-Object -First $limit |
    ForEach-Object {{
      if ($_.DisplayIcon) {{ Add-Result $_.DisplayIcon }}
      if ($_.InstallLocation) {{ Add-Result ("{{0}} :: {{1}}" -f $_.DisplayName, $_.InstallLocation) }}
      else {{ Add-Result $_.DisplayName }}
    }}
}}

$results | Select-Object -First $limit
"""
    result = _powershell(ps_script, timeout=20)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "PowerShell app search failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _windows_launch_application(app_name: str) -> str:
    escaped_name = _ps_quote(app_name)
    ps_script = f"""
$app = {escaped_name}
function Try-Launch([string]$target) {{
  if ([string]::IsNullOrWhiteSpace($target)) {{ return $false }}
  try {{
    Start-Process -FilePath $target -ErrorAction Stop | Out-Null
    Write-Output $target
    return $true
  }} catch {{
    return $false
  }}
}}

if (Try-Launch $app) {{ exit 0 }}

$cmd = Get-Command -Name $app -ErrorAction SilentlyContinue | Select-Object -First 1
if ($cmd -and (Try-Launch $cmd.Source)) {{ exit 0 }}

$pattern = "*$app*"
$startMenuDirs = @(
  "$env:ProgramData\\Microsoft\\Windows\\Start Menu\\Programs",
  "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs"
)
foreach ($dir in $startMenuDirs) {{
  if (Test-Path $dir) {{
    $match = Get-ChildItem -Path $dir -Recurse -Include *.lnk,*.appref-ms -ErrorAction SilentlyContinue |
      Where-Object {{ $_.BaseName -like $pattern }} |
      Select-Object -First 1
    if ($match -and (Try-Launch $match.FullName)) {{ exit 0 }}
  }}
}}

$searchRoots = @(
  "$env:LOCALAPPDATA\\Programs",
  "$env:ProgramFiles",
  "${{env:ProgramFiles(x86)}}",
  "$env:LOCALAPPDATA\\Microsoft\\WindowsApps"
)
foreach ($dir in $searchRoots) {{
  if (Test-Path $dir) {{
    $match = Get-ChildItem -Path $dir -Recurse -Depth 3 -Filter "*$app*.exe" -File -ErrorAction SilentlyContinue |
      Select-Object -First 1
    if ($match -and (Try-Launch $match.FullName)) {{ exit 0 }}
  }}
}}

Write-Error "Could not find or launch application: $app"
exit 1
"""
    result = _powershell(ps_script, timeout=20)
    if result.returncode == 0:
        launched = result.stdout.strip().splitlines()
        target = launched[-1] if launched else app_name
        return f"Launched application: {target}"
    raise RuntimeError(result.stderr.strip() or f"Could not launch {app_name}")


def _windows_installed_apps(query: str = "", limit: int = 50) -> list[str]:
    escaped_query = _ps_quote(query)
    filter_clause = "$true" if not query.strip() else "$_ -like $pattern"
    ps_script = f"""
$query = {escaped_query}
$pattern = "*$query*"
$limit = {int(limit)}
$results = New-Object System.Collections.Generic.List[string]
function Add-Result([string]$value) {{
  if (-not [string]::IsNullOrWhiteSpace($value) -and -not $results.Contains($value)) {{
    $results.Add($value)
  }}
}}

$startMenuDirs = @(
  "$env:ProgramData\\Microsoft\\Windows\\Start Menu\\Programs",
  "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs"
)
foreach ($dir in $startMenuDirs) {{
  if (Test-Path $dir) {{
    Get-ChildItem -Path $dir -Recurse -Include *.lnk,*.appref-ms -ErrorAction SilentlyContinue |
      ForEach-Object {{ Add-Result $_.BaseName }}
  }}
}}

$uninstallKeys = @(
  "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*",
  "HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*",
  "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*"
)
foreach ($key in $uninstallKeys) {{
  Get-ItemProperty -Path $key -ErrorAction SilentlyContinue |
    Where-Object {{ $_.DisplayName }} |
    ForEach-Object {{ Add-Result $_.DisplayName }}
}}

$results |
  Sort-Object -Unique |
  Where-Object {{ {filter_clause} }} |
  Select-Object -First $limit
"""
    result = _powershell(ps_script, timeout=20)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "PowerShell installed app query failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def register(mcp):

    @mcp.tool()
    def open_application(app_name: str) -> str:
        """
        Open any application by name or system command.
        Examples: 'Safari', 'Spotify', 'code', 'python3', 'Notepad', 'Files'.
        On Windows, this searches Start Menu shortcuts, AppData programs, and Program Files.
        Use this whenever the user asks to 'open', 'launch', or 'start' an app/software.
        """
        try:
            if OS == "Darwin":
                result = subprocess.run(["open", "-a", app_name], capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    return f"Launched application: {app_name}"
                result = subprocess.run(["open", app_name], capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    return f"Launched application: {app_name}"
                return f"Could not launch '{app_name}': {result.stderr.strip()}"
            elif OS == "Windows":
                return _windows_launch_application(app_name)
            else:
                result = subprocess.run(["xdg-open", app_name], capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    return f"Launched application: {app_name}"
                return f"Could not launch '{app_name}': {result.stderr.strip()}"
        except Exception as e:
            return f"Error launching application: {str(e)}"

    @mcp.tool()
    def close_application(app_name: str) -> str:
        """
        Gracefully attempt to close an application by name.
        Use this when the user says 'close X', 'shut down X', 'quit X'.
        """
        try:
            if OS == "Darwin":
                script = f'tell application "{_escape_applescript_string(app_name)}" to quit'
                result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
            elif OS == "Windows":
                # Try graceful taskkill first (no /F)
                result = subprocess.run(["taskkill", "/IM", f"{app_name}.exe"], capture_output=True, text=True, timeout=10)
            else:  # Linux
                # Try wmctrl first for graceful window close
                result = subprocess.run(["wmctrl", "-c", app_name], capture_output=True, text=True, timeout=10)
                if result.returncode != 0:
                    # Fallback to pkill (SIGTERM)
                    result = subprocess.run(["pkill", app_name], capture_output=True, text=True, timeout=10)

            if result.returncode == 0:
                return f"Closed {app_name} successfully."
            return f"Could not close '{app_name}': {result.stderr.strip()}"
        except Exception as e:
            return f"Error closing application: {str(e)}"

    @mcp.tool()
    def focus_application(app_name: str) -> str:
        """
        Bring an application to the front/focus.
        Use this when the user says 'switch to X', 'show X', 'focus on X'.
        """
        try:
            if OS == "Darwin":
                script = f'tell application "{_escape_applescript_string(app_name)}" to activate'
                result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
            elif OS == "Windows":
                ps_script = (
                    f"$wshell = New-Object -ComObject WScript.Shell; "
                    f"$focused = $wshell.AppActivate({_ps_quote(app_name)}); "
                    f"if ($focused) {{ Write-Output 'focused' }} else {{ exit 1 }}"
                )
                result = _powershell(ps_script, timeout=10)
            else:  # Linux
                result = subprocess.run(["wmctrl", "-a", app_name], capture_output=True, text=True, timeout=10)
                if result.returncode != 0:
                    return f"wmctrl failed to focus '{app_name}'. Is it running?"

            if result.returncode == 0:
                return f"Focused '{app_name}' successfully."
            return f"Could not focus '{app_name}': {result.stderr.strip()}"
        except Exception as e:
            return f"Error focusing application: {str(e)}"

    @mcp.tool()
    def take_screenshot(filename: str = "") -> str:
        """
        Take a screenshot of the entire screen and save it to the workspace folder.
        Use this when the user asks to 'take a screenshot', 'capture the screen', etc.
        """
        try:
            if not filename:
                filename = f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
            filename = safe_filename(filename, f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png")

            save_path = str(workspace_path(filename))

            if OS == "Darwin":
                result = subprocess.run(["screencapture", "-x", save_path], capture_output=True, text=True, timeout=10)
            elif OS == "Windows":
                # Use PowerShell
                ps_script = (
                    f"Add-Type -AssemblyName System.Windows.Forms; "
                    f"$bmp = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
                    f"$img = New-Object System.Drawing.Bitmap $bmp.Width,$bmp.Height; "
                    f"$g = [System.Drawing.Graphics]::FromImage($img); "
                    f"$g.CopyFromScreen($bmp.Location, [System.Drawing.Point]::Empty, $bmp.Size); "
                    f"$img.Save({_ps_quote(save_path)});"
                )
                result = _powershell(ps_script, timeout=15)
            else:  # Linux
                # Try scrot, then gnome-screenshot, then import (ImageMagick)
                for cmd in [
                    ["scrot", save_path],
                    ["gnome-screenshot", "-f", save_path],
                    ["import", "-window", "root", save_path],
                ]:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        break

            if os.path.exists(save_path):
                return f"Screenshot saved to: {os.path.abspath(save_path)}"
            return f"Screenshot failed: {result.stderr.strip()}"
        except Exception as e:
            return f"Error taking screenshot: {str(e)}"

    @mcp.tool()
    def get_clipboard() -> str:
        """
        Read the current contents of the clipboard.
        Use this when the user says 'what's in my clipboard' or 'read my clipboard'.
        """
        try:
            if OS == "Darwin":
                result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
                content = result.stdout
            elif OS == "Windows":
                result = subprocess.run(
                    ["powershell", "-Command", "Get-Clipboard"],
                    capture_output=True, text=True, timeout=5
                )
                content = result.stdout
            else:  # Linux
                for cmd in [["xclip", "-o", "-selection", "clipboard"], ["xsel", "--clipboard", "--output"]]:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if result.returncode == 0:
                        content = result.stdout
                        break
                else:
                    return "Clipboard tool not found. Install xclip or xsel: sudo apt install xclip"

            if not content.strip():
                return "Clipboard is currently empty."
            return f"Clipboard contents:\n{content[:2000]}"
        except Exception as e:
            return f"Error reading clipboard: {str(e)}"

    @mcp.tool()
    def set_clipboard(text: str) -> str:
        """
        Write text to the clipboard.
        Use this when the user wants to copy something or says 'put this in my clipboard'.
        """
        try:
            if OS == "Darwin":
                process = subprocess.run(["pbcopy"], input=text, capture_output=True, text=True, timeout=5)
            elif OS == "Windows":
                process = _powershell(f"Set-Clipboard -Value {_ps_quote(text)}", timeout=5)
            else:  # Linux
                for cmd_prefix in [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]:
                    process = subprocess.run(cmd_prefix, input=text, capture_output=True, text=True, timeout=5)
                    if process.returncode == 0:
                        break
                else:
                    return "Clipboard tool not found. Install xclip: sudo apt install xclip"

            if process.returncode == 0:
                return f"Copied {len(text)} characters to clipboard."
            return f"Clipboard write failed: {process.stderr.strip()}"
        except Exception as e:
            return f"Error writing to clipboard: {str(e)}"

    @mcp.tool()
    def send_notification(title: str, message: str, subtitle: str = "") -> str:
        """
        Send a system notification (appears in notification area).
        Use this to alert the user, confirm task completion, or deliver a reminder.
        """
        try:
            if OS == "Darwin":
                subtitle_part = f'subtitle "{subtitle}"' if subtitle else ""
                script = (
                    f'display notification "{_escape_applescript_string(message)}" '
                    f'with title "{_escape_applescript_string(title)}" '
                    f'{subtitle_part and subtitle_part.replace(subtitle, _escape_applescript_string(subtitle))}'
                ).strip()
                result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
            elif OS == "Windows":
                ps_script = (
                    f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
                    f"$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
                    f"$template.SelectSingleNode('//text[@id=1]').InnerText = {_ps_quote(title)}; "
                    f"$template.SelectSingleNode('//text[@id=2]').InnerText = {_ps_quote(message)}; "
                    f"$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
                    f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('FRIDAY').Show($toast);"
                )
                result = _powershell(ps_script, timeout=10)
            else:  # Linux
                result = subprocess.run(
                    ["notify-send", title, message],
                    capture_output=True, text=True, timeout=10
                )

            if result.returncode == 0:
                return f"Notification sent: '{title}' — {message}"
            return f"Notification sent (may not have appeared): {result.stderr.strip()}"
        except Exception as e:
            return f"Error sending notification: {str(e)}"

    @mcp.tool()
    def set_timer(seconds: int, label: str = "Timer") -> str:
        """
        Set a background countdown timer. When it expires, a system notification fires.
        Use this when the user says 'set a timer for X minutes/seconds', 'remind me in X minutes'.
        seconds: Number of seconds to wait. CONVERT: '5 minutes' = 300 seconds, '1 hour' = 3600 seconds.
        """
        try:
            if seconds <= 0:
                return "Timer duration must be greater than zero seconds."

            def _fire(secs: int, lbl: str):
                time.sleep(secs)
                try:
                    msg = f"Your {lbl} timer is done!"
                    if OS == "Darwin":
                        subprocess.run(
                            [
                                "osascript",
                                "-e",
                                (
                                    f'display notification "{_escape_applescript_string(msg)}" '
                                    'with title "Timer Done"'
                                ),
                            ],
                            timeout=5
                        )
                        subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], timeout=5)
                    elif OS == "Windows":
                        _powershell(
                            f"[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
                            f"[System.Windows.Forms.MessageBox]::Show({_ps_quote(msg)}, {_ps_quote('Timer Done')})",
                            timeout=10,
                        )
                    else:  # Linux
                        subprocess.run(["notify-send", "⏰ Timer Done", msg], timeout=5)
                        subprocess.run(["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"], timeout=5)
                except Exception:
                    pass

            threading.Thread(target=_fire, args=(seconds, label), daemon=True).start()

            minutes, secs_rem = divmod(seconds, 60)
            if minutes > 0:
                human_time = f"{minutes}m {secs_rem}s" if secs_rem else f"{minutes}m"
            else:
                human_time = f"{seconds}s"

            return f"Timer set for {human_time} — '{label}'. You'll get a notification when done."
        except Exception as e:
            return f"Error setting timer: {str(e)}"

    @mcp.tool()
    def get_running_apps() -> str:
        """
        List all currently running applications.
        Use this when the user asks 'what apps are open?' or 'what's running?'.
        """
        try:
            if OS == "Darwin":
                script = 'tell application "System Events" to get name of every process where background only is false'
                result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    apps = sorted([a.strip() for a in result.stdout.strip().split(",") if a.strip()])
                    return f"Running apps ({len(apps)}):\n" + "\n".join(f"  • {a}" for a in apps)
            elif OS == "Windows":
                result = subprocess.run(
                    ["powershell", "-Command", "Get-Process | Where-Object {$_.MainWindowTitle -ne ''} | Select-Object -ExpandProperty ProcessName"],
                    capture_output=True, text=True, timeout=10
                )
                apps = sorted([a.strip() for a in result.stdout.strip().splitlines() if a.strip()])
                return f"Running apps ({len(apps)}):\n" + "\n".join(f"  • {a}" for a in apps)
            else:  # Linux
                result = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    lines = [line.split(None, 3)[-1] for line in result.stdout.strip().splitlines() if line]
                    return f"Open windows ({len(lines)}):\n" + "\n".join(f"  • {line}" for line in lines)
                # Fallback
                result = subprocess.run(["ps", "-eo", "comm="], capture_output=True, text=True, timeout=10)
                apps = sorted(set(result.stdout.strip().splitlines()))[:30]
                return "Running processes (top 30):\n" + "\n".join(f"  • {a}" for a in apps)

            return f"Could not list apps: {result.stderr.strip()}"
        except Exception as e:
            return f"Error listing apps: {str(e)}"

    @mcp.tool()
    def list_installed_apps(query: str = "", limit: int = 50) -> str:
        """
        List installed applications on the local system.
        Use this when the user asks what software is installed, not just what is running.
        """
        try:
            if limit <= 0:
                return "Limit must be greater than zero."

            if OS == "Windows":
                apps = _windows_installed_apps(query=query, limit=limit)
            elif OS == "Darwin":
                result = subprocess.run(
                    ["find", "/Applications", "/System/Applications", "-maxdepth", "2", "-name", "*.app"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                apps = [Path(line).stem for line in result.stdout.splitlines() if line.strip()]
                if query.strip():
                    needle = query.lower()
                    apps = [app for app in apps if needle in app.lower()]
                apps = sorted(dict.fromkeys(apps))[:limit]
            else:
                result = subprocess.run(
                    ["find", "/usr/share/applications", "-maxdepth", "2", "-name", "*.desktop"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                apps = [Path(line).stem for line in result.stdout.splitlines() if line.strip()]
                if query.strip():
                    needle = query.lower()
                    apps = [app for app in apps if needle in app.lower()]
                apps = sorted(dict.fromkeys(apps))[:limit]

            if not apps:
                qualifier = f" matching '{query}'" if query.strip() else ""
                return f"No installed applications found{qualifier}."
            return f"Installed applications ({len(apps)}):\n" + "\n".join(f"  • {app}" for app in apps)
        except Exception as e:
            return f"Error listing installed apps: {str(e)}"

    @mcp.tool()
    def search_local_apps(query: str) -> str:
        """
        Search for installed software/applications on the local system.
        Use this when the user asks 'do I have X?', 'where is X?', or if 'open_application' fails.
        """
        try:
            results = []
            if OS == "Darwin":
                # Search common Mac app folders
                search_paths = ["/Applications", "/System/Applications", "~/Applications"]
                pattern = f"*{query}*.app"
                for path in search_paths:
                    expanded = os.path.expanduser(path)
                    if os.path.exists(expanded):
                        res = subprocess.run(
                            ["find", expanded, "-maxdepth", "2", "-iname", pattern],
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )
                        results.extend(res.stdout.strip().splitlines())
            elif OS == "Windows":
                results.extend(_windows_search_results(query, limit=20))
            else:  # Linux
                res = subprocess.run(
                    ["find", "/usr/share/applications", "/usr/bin", "-iname", f"*{query}*"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                results.extend(res.stdout.strip().splitlines())

            if not results:
                return f"No applications found matching '{query}'."
            return f"Found {len(results)} matches:\n" + "\n".join(f"  • {r}" for r in results[:20])
        except Exception as e:
            return f"Error searching for apps: {str(e)}"

    @mcp.tool()
    def list_open_windows(query: str = "", limit: int = 25) -> str:
        """
        List visible application windows, including titles when available.
        Use this when the user asks what windows are open, which app is focused,
        or which browser/document window to target next.
        """
        try:
            if limit <= 0:
                return "Limit must be greater than zero."

            if OS == "Windows":
                escaped_query = _ps_quote(query)
                ps_script = f"""
$query = {escaped_query}
$limit = {int(limit)}
Get-Process |
  Where-Object {{ $_.MainWindowTitle -and $_.MainWindowTitle.Trim() -ne '' }} |
  Where-Object {{ (-not $query) -or $_.ProcessName -like "*$query*" -or $_.MainWindowTitle -like "*$query*" }} |
  Sort-Object ProcessName, Id |
  Select-Object -First $limit Id, ProcessName, MainWindowTitle |
  ConvertTo-Json -Compress
"""
                result = _powershell(ps_script, timeout=15)
                if result.returncode != 0:
                    return f"Could not list open windows: {result.stderr.strip()}"

                rows = _load_json_records(result.stdout)
                if not rows:
                    qualifier = f" matching '{query}'" if query.strip() else ""
                    return f"No open windows found{qualifier}."

                lines = [
                    f"  - {row.get('ProcessName') or '?'} [{row.get('Id') or '?'}] :: {row.get('MainWindowTitle') or '(untitled)'}"
                    for row in rows
                ]
                return f"Open windows ({len(lines)}):\n" + "\n".join(lines)

            if OS == "Darwin":
                script = 'tell application "System Events" to get name of every process where background only is false'
                result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
                apps = [item.strip() for item in result.stdout.split(",") if item.strip()]
                if query.strip():
                    needle = query.lower()
                    apps = [app for app in apps if needle in app.lower()]
                if not apps:
                    return f"No open windows found matching '{query}'." if query.strip() else "No open windows found."
                return f"Open windows ({len(apps[:limit])}):\n" + "\n".join(f"  - {app}" for app in apps[:limit])

            result = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return f"Could not list open windows: {result.stderr.strip()}"
            windows = [line.split(None, 3)[-1] for line in result.stdout.strip().splitlines() if line.strip()]
            if query.strip():
                needle = query.lower()
                windows = [window for window in windows if needle in window.lower()]
            if not windows:
                return f"No open windows found matching '{query}'." if query.strip() else "No open windows found."
            return f"Open windows ({len(windows[:limit])}):\n" + "\n".join(f"  - {window}" for window in windows[:limit])
        except Exception as e:
            return f"Error listing open windows: {str(e)}"

    @mcp.tool()
    def type_text(text: str, press_enter: bool = False, interval_ms: int = 20) -> str:
        """
        Type text into the currently focused application or field.
        Use this after opening or focusing an app when the user wants FRIDAY to
        enter text, search queries, or commands.
        """
        try:
            interval_seconds = max(0, interval_ms) / 1000.0
            pyautogui = _load_pyautogui()
            pyautogui.write(text, interval=interval_seconds)
            if press_enter:
                pyautogui.press("enter")
            return f"Typed {len(text)} characters" + (" and pressed Enter." if press_enter else ".")
        except Exception as primary_error:
            if OS == "Windows":
                try:
                    return _windows_paste_text(text, press_enter=press_enter)
                except Exception as fallback_error:
                    return f"Error typing text: {fallback_error}"
            return f"Error typing text: {primary_error}"

    @mcp.tool()
    def gui_get_mouse_pos() -> str:
        """
        Get the current (x, y) coordinates of the mouse cursor.
        Use this to help determine where to click.
        """
        try:
            if OS == "Darwin":
                script = 'use framework "AppKit"\nreturn (current application\'s NSEvent\'s mouseLocation())\n'
                result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
                # Parse "x=..., y=..." (Note: Mac Y is from bottom, convert to top-down in next steps if needed)
                return f"Current mouse position (OS Raw): {result.stdout.strip()}"
            elif OS == "Windows":
                ps_script = (
                    "Add-Type -AssemblyName System.Windows.Forms; "
                    "$pos = [System.Windows.Forms.Cursor]::Position; "
                    'Write-Output ("X={0}, Y={1}" -f $pos.X, $pos.Y)'
                )
                result = _powershell(ps_script, timeout=5)
                return f"Current mouse position: {result.stdout.strip()}"
            return "Mouse coordinates not supported on this OS without extra libs."
        except Exception as e:
            return f"Error getting mouse pos: {str(e)}"

    @mcp.tool()
    def gui_click(x: int, y: int, button: str = "left") -> str:
        """
        Perform a mouse click at specific screen coordinates (x, y).
        Use this to interact with software buttons that 'type_text' can't reach.
        """
        try:
            if OS == "Darwin":
                # AppleScript for clicking is complex, use python-based approach in subagent if possible, 
                # or native 'cliclick' if installed. Falling back to native instructions.
                script = f'tell application "System Events" to click at {{{x}, {y}}}'
                subprocess.run(["osascript", "-e", script], timeout=5)
            elif OS == "Windows":
                flags = {
                    "left": ("0x0002", "0x0004"),
                    "right": ("0x0008", "0x0010"),
                    "middle": ("0x0020", "0x0040"),
                }
                if button.lower() not in flags:
                    return f"Unsupported mouse button: {button}"
                down_flag, up_flag = flags[button.lower()]
                ps_script = f"""
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class MouseTools {{
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);
}}
"@;
[MouseTools]::SetCursorPos({x}, {y}) | Out-Null;
Start-Sleep -Milliseconds 60;
[MouseTools]::mouse_event({down_flag}, 0, 0, 0, [UIntPtr]::Zero);
Start-Sleep -Milliseconds 60;
[MouseTools]::mouse_event({up_flag}, 0, 0, 0, [UIntPtr]::Zero);
"""
                _powershell(ps_script, timeout=5)
            
            return f"Synthesized {button} click at ({x}, {y})."
        except Exception as e:
            return f"Error performing GUI click: {str(e)}"

    @mcp.tool()
    def press_key(key: str) -> str:
        """
        Press a special key or combination.
        Examples: 'enter', 'esc', 'tab', 'down', 'up', 'command+tab', 'ctrl+c'.
        """
        try:
            normalized_parts = [_normalize_hotkey_part(part) for part in key.split("+") if part.strip()]
            if not normalized_parts:
                return "No key provided."

            try:
                pyautogui = _load_pyautogui()
                if len(normalized_parts) == 1:
                    pyautogui.press(normalized_parts[0])
                else:
                    pyautogui.hotkey(*normalized_parts)
            except Exception:
                if OS == "Windows":
                    send_keys = _windows_sendkeys_combo(key)
                    if not send_keys:
                        return f"Unsupported key combination: {key}"
                    fallback = _powershell(
                        f"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait({_ps_quote(send_keys)})",
                        timeout=5,
                    )
                    if fallback.returncode != 0:
                        return f"Error pressing key: {fallback.stderr.strip()}"
                elif OS == "Darwin":
                    script = f'tell application "System Events" to keystroke "{_escape_applescript_string(key)}"'
                    subprocess.run(["osascript", "-e", script], timeout=5)
                else:
                    raise

            return f"Pressed key: {key}"
        except Exception as e:
            return f"Error pressing key: {str(e)}"

    @mcp.tool()
    async def voice_filler(filler_type: str = "thinking") -> str:
        """
        Trigger a preemptive, short audio filler ('Thinking...', 'Looking that up...', etc.) 
        to fill silence during long reasoning tasks. Part of F.R.I.D.A.Y's SOTA UX.
        """
        fillers = {
            "thinking": "One moment, let me think about that...",
            "researching": "I'm looking that up for you now, boss...",
            "analyzing": "Analyzing the data now...",
            "coding": "Drafting the code for you...",
            "wait": "Just a second..."
        }
        text = fillers.get(filler_type, "One moment...")
        # In a real LiveKit agent, this handles an 'immediate_speak' event.
        # Here we return the intent to the system.
        return f"PREEMPTIVE_VOICE_FILLER: {text}"
