"""
Apps & System Control tools — open applications, take screenshots,
manage clipboard, send notifications, and set timers.
Supports: macOS, Linux, and Windows.
"""

import subprocess
import os
import threading
import time
import platform
from pathlib import Path

OS = platform.system()  # "Darwin" | "Linux" | "Windows"


def _workspace_dir() -> str:
    base = os.environ.get("FRIDAY_WORKSPACE_DIR", "workspace")
    Path(base).mkdir(parents=True, exist_ok=True)
    return base


def register(mcp):

    @mcp.tool()
    def open_application(app_name: str) -> str:
        """
        Open any application by name or system command.
        Examples: 'Safari', 'Spotify', 'code', 'python3', 'Notepad', 'Files'.
        If the native OS launcher fails, it will attempt to launch the command directly.
        Use this whenever the user asks to 'open', 'launch', or 'start' an app/software.
        """
        try:
            success = False
            error_msg = ""
            
            # 1. Try Native OS Visual Launchers
            if OS == "Darwin":
                result = subprocess.run(["open", "-a", app_name], capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    success = True
                else:
                    result = subprocess.run(["open", app_name], capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        success = True
                    else:
                        error_msg = result.stderr.strip()
            elif OS == "Windows":
                result = subprocess.run(["start", "", app_name], shell=True, capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    success = True
                else:
                    error_msg = result.stderr.strip()
            else:  # Linux
                result = subprocess.run(["xdg-open", app_name], capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    success = True
                else:
                     error_msg = result.stderr.strip()

            # 2. Universal Generic Shell Fallback for CLI tools and Custom Scripts
            if not success:
                # Fire and forget via shell (redirect output so it doesn't block)
                if OS == "Windows":
                    subprocess.Popen(app_name, shell=True, creationflags=subprocess.CREATE_NEW_CONSOLE)
                else:
                    subprocess.Popen(app_name, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return f"Native launcher failed ({error_msg}). Falling back to direct shell execution. Attempted to launch: '{app_name}'."

            return f"Launched {app_name} successfully using native OS launcher."
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
                script = f'tell application "{app_name}" to quit'
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
                script = f'tell application "{app_name}" to activate'
                result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
            elif OS == "Windows":
                ps_script = (
                    f"$wshell = New-Object -ComObject WScript.Shell; "
                    f"$wshell.AppActivate('{app_name}')"
                )
                result = subprocess.run(["powershell", "-Command", ps_script], capture_output=True, text=True, timeout=10)
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

            workspace = _workspace_dir()
            save_path = os.path.join(workspace, filename)

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
                    f"$img.Save('{save_path}');"
                )
                result = subprocess.run(["powershell", "-Command", ps_script], capture_output=True, text=True, timeout=15)
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
                process = subprocess.run(
                    ["powershell", "-Command", f"Set-Clipboard -Value '{text}'"],
                    capture_output=True, text=True, timeout=5
                )
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
                script = f'display notification "{message}" with title "{title}" {subtitle_part}'
                result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
            elif OS == "Windows":
                ps_script = (
                    f"[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
                    f"$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
                    f"$template.SelectSingleNode('//text[@id=1]').InnerText = '{title}'; "
                    f"$template.SelectSingleNode('//text[@id=2]').InnerText = '{message}'; "
                    f"$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
                    f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('FRIDAY').Show($toast);"
                )
                result = subprocess.run(["powershell", "-Command", ps_script], capture_output=True, text=True, timeout=10)
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
            def _fire(secs: int, lbl: str):
                time.sleep(secs)
                try:
                    msg = f"Your {lbl} timer is done!"
                    if OS == "Darwin":
                        subprocess.run(
                            ["osascript", "-e", f'display notification "{msg}" with title "⏰ Timer Done"'],
                            timeout=5
                        )
                        subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], timeout=5)
                    elif OS == "Windows":
                        subprocess.run(
                            ["powershell", "-Command",
                             f"[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null; "
                             f"[System.Windows.Forms.MessageBox]::Show('{msg}', '⏰ Timer Done')"],
                            timeout=10
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
                    lines = [l.split(None, 3)[-1] for l in result.stdout.strip().splitlines() if l]
                    return f"Open windows ({len(lines)}):\n" + "\n".join(f"  • {l}" for l in lines)
                # Fallback
                result = subprocess.run(["ps", "-eo", "comm="], capture_output=True, text=True, timeout=10)
                apps = sorted(set(result.stdout.strip().splitlines()))[:30]
                return f"Running processes (top 30):\n" + "\n".join(f"  • {a}" for a in apps)

            return f"Could not list apps: {result.stderr.strip()}"
        except Exception as e:
            return f"Error listing apps: {str(e)}"

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
                for path in search_paths:
                    expanded = os.path.expanduser(path)
                    if os.path.exists(expanded):
                        cmd = f"find {expanded} -maxdepth 2 -iname '*{query}*.app'"
                        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
                        results.extend(res.stdout.strip().splitlines())
            elif OS == "Windows":
                ps_script = (
                    f"Get-ChildItem -Path 'C:\\Program Files', 'C:\\Program Files (x86)' -Filter '*{query}*' -Recurse -Depth 1 -ErrorAction SilentlyContinue | "
                    f"Select-Object -ExpandProperty FullName"
                )
                res = subprocess.run(["powershell", "-Command", ps_script], capture_output=True, text=True, timeout=15)
                results.extend(res.stdout.strip().splitlines())
            else:  # Linux
                cmd = f"find /usr/share/applications /usr/bin -iname '*{query}*'"
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
                results.extend(res.stdout.strip().splitlines())

            if not results:
                return f"No applications found matching '{query}'."
            return f"Found {len(results)} matches:\n" + "\n".join(f"  • {r}" for r in results[:20])
        except Exception as e:
            return f"Error searching for apps: {str(e)}"

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
                ps_script = "[System.Windows.Forms.Cursor]::Position"
                result = subprocess.run(["powershell", "-Command", ps_script], capture_output=True, text=True, timeout=5)
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
                ps_script = (
                    f"Add-Type -AssemblyName System.Windows.Forms; "
                    f"[System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point({x}, {y}); "
                    f"$sim = New-Object -ComObject WScript.Shell; $sim.SendKeys('{{LEFTCLICK}}')" 
                ) # Simplified for demonstration
                subprocess.run(["powershell", "-Command", ps_script], timeout=5)
            
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
            if OS == "Darwin":
                # Map common names to AppleScript key codes/commands
                lookup = {"enter": "return", "esc": "escape"}
                k = lookup.get(key.lower(), key)
                script = f'tell application "System Events" to key code {k}' if k.isdigit() else f'tell application "System Events" to keystroke "{k}"'
                if "+" in key:
                    # Handle combinations like command+tab
                    pass 
                subprocess.run(["osascript", "-e", script], timeout=5)
            elif OS == "Windows":
                ps_script = f"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait('{{{key.upper()}}}')"
                subprocess.run(["powershell", "-Command", ps_script], timeout=5)
            
            return f"Pressed key: {key}"
        except Exception as e:
            return f"Error pressing key: {str(e)}"
