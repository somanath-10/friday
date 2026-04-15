"""
Apps & System Control tools — open applications, take screenshots,
manage clipboard, send notifications, and set timers on macOS.
"""

import subprocess
import os
import threading
import time
import json
from pathlib import Path


def _workspace_dir() -> str:
    base = os.environ.get("FRIDAY_WORKSPACE_DIR", "workspace")
    Path(base).mkdir(parents=True, exist_ok=True)
    return base


def register(mcp):

    @mcp.tool()
    def open_application(app_name: str) -> str:
        """
        Open any macOS application by name.
        Examples: 'Safari', 'Spotify', 'Terminal', 'Finder', 'Xcode', 'VS Code', 'Chrome'.
        Use this whenever the user asks to 'open', 'launch', or 'start' an app.
        """
        try:
            result = subprocess.run(
                ["open", "-a", app_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return f"Launched {app_name} successfully."
            else:
                # Try without -a flag (for paths or generic opens)
                result2 = subprocess.run(
                    ["open", app_name],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result2.returncode == 0:
                    return f"Opened {app_name} successfully."
                return f"Could not open '{app_name}': {result.stderr.strip()}"
        except Exception as e:
            return f"Error launching application: {str(e)}"

    @mcp.tool()
    def take_screenshot(filename: str = "") -> str:
        """
        Take a screenshot of the entire screen and save it to the workspace folder.
        Filename is optional — auto-generated if not provided. Returns the saved file path.
        Use this when the user asks to 'take a screenshot', 'capture the screen', etc.
        """
        try:
            if not filename:
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{timestamp}.png"

            workspace = _workspace_dir()
            save_path = os.path.join(workspace, filename)

            result = subprocess.run(
                ["screencapture", "-x", save_path],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0 and os.path.exists(save_path):
                return f"Screenshot saved to: {os.path.abspath(save_path)}"
            else:
                return f"Screenshot failed: {result.stderr.strip()}"
        except Exception as e:
            return f"Error taking screenshot: {str(e)}"

    @mcp.tool()
    def get_clipboard() -> str:
        """
        Read the current contents of the macOS clipboard (pasteboard).
        Use this when the user says 'what's in my clipboard' or 'read my clipboard'.
        """
        try:
            result = subprocess.run(
                ["pbpaste"],
                capture_output=True,
                text=True,
                timeout=5
            )
            content = result.stdout
            if not content.strip():
                return "Clipboard is currently empty."
            return f"Clipboard contents:\n{content[:2000]}"
        except Exception as e:
            return f"Error reading clipboard: {str(e)}"

    @mcp.tool()
    def set_clipboard(text: str) -> str:
        """
        Write text to the macOS clipboard (pasteboard).
        Use this when the user wants to copy something or says 'put this in my clipboard'.
        """
        try:
            process = subprocess.run(
                ["pbcopy"],
                input=text,
                capture_output=True,
                text=True,
                timeout=5
            )
            if process.returncode == 0:
                return f"Copied {len(text)} characters to clipboard."
            return f"Clipboard write failed: {process.stderr.strip()}"
        except Exception as e:
            return f"Error writing to clipboard: {str(e)}"

    @mcp.tool()
    def send_notification(title: str, message: str, subtitle: str = "") -> str:
        """
        Send a macOS system notification (appears in top-right corner / Notification Center).
        Use this to alert the user, confirm task completion, or deliver a reminder.
        """
        try:
            subtitle_part = f'subtitle "{subtitle}"' if subtitle else ""
            script = f'display notification "{message}" with title "{title}" {subtitle_part}'
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return f"Notification sent: '{title}' — {message}"
            return f"Notification failed: {result.stderr.strip()}"
        except Exception as e:
            return f"Error sending notification: {str(e)}"

    @mcp.tool()
    def set_timer(seconds: int, label: str = "Timer") -> str:
        """
        Set a background countdown timer. When it expires, a macOS notification pops up.
        Use this when the user says 'set a timer for X minutes/seconds', 'remind me in X minutes', etc.
        seconds: Number of seconds to wait before the notification fires.
        label: What the timer is for (e.g. 'Tea', 'Meeting', 'Stand up').
        """
        try:
            def _fire_timer(secs: int, lbl: str):
                time.sleep(secs)
                try:
                    minutes = secs // 60
                    remaining = secs % 60
                    if minutes > 0:
                        time_str = f"{minutes}m {remaining}s" if remaining else f"{minutes}m"
                    else:
                        time_str = f"{secs}s"
                    script = f'display notification "Your {lbl} timer is done!" with title "⏰ Timer Finished" subtitle "{time_str} elapsed"'
                    subprocess.run(["osascript", "-e", script], timeout=5)
                    # Also play system alert sound
                    subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], timeout=5)
                except Exception:
                    pass

            t = threading.Thread(target=_fire_timer, args=(seconds, label), daemon=True)
            t.start()

            minutes = seconds // 60
            secs_rem = seconds % 60
            if minutes > 0:
                human_time = f"{minutes} minute{'s' if minutes != 1 else ''}"
                if secs_rem:
                    human_time += f" and {secs_rem} second{'s' if secs_rem != 1 else ''}"
            else:
                human_time = f"{seconds} second{'s' if seconds != 1 else ''}"

            return f"Timer set for {human_time} — '{label}'. You'll get a notification when it's done."
        except Exception as e:
            return f"Error setting timer: {str(e)}"

    @mcp.tool()
    def get_running_apps() -> str:
        """
        List all currently running applications visible to the user.
        Use this when the user asks 'what apps are open?' or 'what's running?'.
        """
        try:
            script = 'tell application "System Events" to get name of every process where background only is false'
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                apps = [a.strip() for a in result.stdout.strip().split(",") if a.strip()]
                return f"Running apps ({len(apps)}):\n" + "\n".join(f"  • {a}" for a in sorted(apps))
            return f"Could not list apps: {result.stderr.strip()}"
        except Exception as e:
            return f"Error listing apps: {str(e)}"

    @mcp.tool()
    def type_text(text: str) -> str:
        """
        Type text into the currently focused application using keyboard simulation.
        Use this to paste/type text into any app that's in focus.
        """
        try:
            script = f'tell application "System Events" to keystroke "{text}"'
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return f"Typed {len(text)} characters into active app."
            return f"Keystroke failed: {result.stderr.strip()}"
        except Exception as e:
            return f"Error typing text: {str(e)}"
