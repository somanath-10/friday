"""
Windows desktop backend using PowerShell and shell launchers.
"""

from __future__ import annotations

import os
import subprocess

from friday.subprocess_utils import run_powershell


class WindowsBackend:
    name = "windows"

    def open_application(self, app_name: str) -> dict:
        try:
            os.startfile(app_name)  # type: ignore[attr-defined]
            return {"ok": True, "message": f"Opened {app_name}."}
        except Exception:
            result = subprocess.run(["cmd", "/c", "start", "", app_name], capture_output=True, text=True, timeout=10)
            return {
                "ok": result.returncode == 0,
                "message": f"Opened {app_name}." if result.returncode == 0 else result.stderr.strip() or result.stdout.strip(),
            }

    def focus_application(self, app_name: str) -> dict:
        script = f"""
$wshell = New-Object -ComObject wscript.shell
$ok = $wshell.AppActivate('{app_name.replace("'", "''")}')
Write-Output $ok
"""
        result = run_powershell(script, timeout=10)
        ok = "true" in result.stdout.lower()
        return {"ok": ok, "message": f"Focused {app_name}." if ok else result.stderr or result.stdout}

    def close_application(self, app_name: str) -> dict:
        process_name = app_name.replace(".exe", "").replace("'", "''")
        script = f"Get-Process -Name '{process_name}' -ErrorAction SilentlyContinue | Stop-Process"
        result = run_powershell(script, timeout=10)
        return {"ok": result.returncode == 0, "message": f"Requested {app_name} close." if result.returncode == 0 else result.stderr}

    def list_open_windows(self) -> list[dict]:
        script = "Get-Process | Where-Object {$_.MainWindowTitle} | Select-Object ProcessName,MainWindowTitle | ConvertTo-Json"
        result = run_powershell(script, timeout=10)
        if result.returncode != 0 or not result.stdout.strip():
            return []
        import json

        parsed = json.loads(result.stdout)
        rows = parsed if isinstance(parsed, list) else [parsed]
        return [{"app": row.get("ProcessName", ""), "title": row.get("MainWindowTitle", "")} for row in rows if isinstance(row, dict)]

    def get_active_window(self) -> dict:
        return {"ok": False, "title": "", "app": "", "message": "Active window detection is not implemented for Windows yet."}

    def list_installed_apps(self) -> list[dict]:
        return []
