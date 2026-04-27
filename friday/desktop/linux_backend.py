"""
Linux desktop backend using common X11 tools when available.
"""

from __future__ import annotations

import shutil
import subprocess


class LinuxBackend:
    name = "linux"

    def open_application(self, app_name: str) -> dict:
        command = [app_name]
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"ok": True, "message": f"Opened {app_name}."}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def focus_application(self, app_name: str) -> dict:
        if not shutil.which("wmctrl"):
            return {"ok": False, "message": "wmctrl is not installed."}
        result = subprocess.run(["wmctrl", "-a", app_name], capture_output=True, text=True, timeout=10)
        return {"ok": result.returncode == 0, "message": f"Focused {app_name}." if result.returncode == 0 else result.stderr}

    def close_application(self, app_name: str) -> dict:
        if not shutil.which("wmctrl"):
            return {"ok": False, "message": "wmctrl is not installed."}
        result = subprocess.run(["wmctrl", "-c", app_name], capture_output=True, text=True, timeout=10)
        return {"ok": result.returncode == 0, "message": f"Requested {app_name} close." if result.returncode == 0 else result.stderr}

    def list_open_windows(self) -> list[dict]:
        if not shutil.which("wmctrl"):
            return []
        result = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return []
        return [{"title": " ".join(line.split()[3:]), "app": ""} for line in result.stdout.splitlines() if line.strip()]

    def get_active_window(self) -> dict:
        return {"ok": False, "title": "", "app": "", "message": "Active window detection depends on the Linux window manager."}

    def list_installed_apps(self) -> list[dict]:
        return []
