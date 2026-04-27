"""
macOS desktop backend using AppleScript/open where possible.
"""

from __future__ import annotations

import subprocess


class MacOSBackend:
    name = "macos"

    def open_application(self, app_name: str) -> dict:
        result = subprocess.run(["open", "-a", app_name], capture_output=True, text=True, timeout=15)
        return {
            "ok": result.returncode == 0,
            "message": f"Opened {app_name}." if result.returncode == 0 else result.stderr.strip() or result.stdout.strip(),
        }

    def focus_application(self, app_name: str) -> dict:
        script = f'tell application "{app_name}" to activate'
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        return {
            "ok": result.returncode == 0,
            "message": f"Focused {app_name}." if result.returncode == 0 else result.stderr.strip() or result.stdout.strip(),
        }

    def close_application(self, app_name: str) -> dict:
        script = f'tell application "{app_name}" to quit'
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        return {
            "ok": result.returncode == 0,
            "message": f"Requested {app_name} quit." if result.returncode == 0 else result.stderr.strip() or result.stdout.strip(),
        }

    def list_open_windows(self) -> list[dict]:
        script = 'tell application "System Events" to get name of every process whose background only is false'
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return []
        return [{"title": item.strip(), "app": item.strip()} for item in result.stdout.split(",") if item.strip()]

    def get_active_window(self) -> dict:
        script = 'tell application "System Events" to get name of first process whose frontmost is true'
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
        title = result.stdout.strip()
        return {"ok": result.returncode == 0, "title": title, "app": title}

    def list_installed_apps(self) -> list[dict]:
        result = subprocess.run(["find", "/Applications", "-maxdepth", "2", "-name", "*.app"], capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            return []
        return [{"name": line.rsplit("/", 1)[-1].removesuffix(".app"), "path": line} for line in result.stdout.splitlines() if line.strip()]
