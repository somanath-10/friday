"""
System tools - time, environment info, process management, and host telemetry.
Supports: macOS, Linux, and Windows.
"""

from __future__ import annotations

import datetime
import json
import ctypes
import os
import platform
import shutil
import subprocess
import base64
from pathlib import Path
from typing import Any

from friday.path_utils import known_user_paths, resolve_user_path, workspace_dir

OS = platform.system()  # "Darwin" | "Linux" | "Windows"


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _powershell(script: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _load_json_records(raw: str) -> list[dict[str, Any]]:
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


def _storage_root() -> str:
    for candidate in (Path.home().anchor, workspace_dir().anchor, os.path.abspath(os.path.sep)):
        if candidate:
            return candidate
    return os.path.abspath(os.path.sep)


def _is_elevated() -> bool | None:
    try:
        if OS == "Windows":
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        if hasattr(os, "geteuid"):
            return os.geteuid() == 0
    except Exception:
        return None
    return None


def _short(value: Any, limit: int = 110) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _format_section(title: str, lines: list[str], empty_message: str) -> str:
    body = lines or [empty_message]
    return "\n".join([f"=== {title} ===", *body])


def _format_drive_rows(rows: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        device = str(row.get("DeviceID") or "?")
        drive_type = str(row.get("DriveType") or "Drive")
        volume_name = str(row.get("VolumeName") or "-")
        free_gb = row.get("FreeGB")
        size_gb = row.get("SizeGB")
        free_text = f"{free_gb} GB" if free_gb not in (None, "") else "?"
        size_text = f"{size_gb} GB" if size_gb not in (None, "") else "?"
        lines.append(
            f"- {device} | {drive_type} | volume={volume_name} | free={free_text} / total={size_text}"
        )
    return lines


def _task_display_name(row: dict[str, Any]) -> str:
    task_path = str(row.get("TaskPath") or "\\")
    task_name = str(row.get("TaskName") or "(unnamed)")
    return f"{task_path}{task_name}"


def _windows_python_drive_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for code in range(ord("A"), ord("Z") + 1):
        device = f"{chr(code)}:\\"
        if not os.path.exists(device):
            continue
        try:
            total, _used, free = shutil.disk_usage(device)
        except Exception:
            continue
        rows.append(
            {
                "DeviceID": device.rstrip("\\"),
                "VolumeName": "",
                "DriveType": "FileSystem",
                "SizeGB": round(total / (1024 ** 3), 1),
                "FreeGB": round(free / (1024 ** 3), 1),
            }
        )
    return rows


def _windows_disk_drives() -> list[dict[str, Any]]:
    primary_script = """
Get-CimInstance Win32_LogicalDisk |
  Where-Object { $_.DriveType -in 2,3,4,5 } |
  Sort-Object DeviceID |
  Select-Object DeviceID, VolumeName,
    @{Name='DriveType'; Expression = {
      switch ($_.DriveType) {
        2 { 'Removable' }
        3 { 'Local' }
        4 { 'Network' }
        5 { 'CD/DVD' }
        default { 'Unknown' }
      }
    }},
    @{Name='SizeGB'; Expression = {
      if ($null -ne $_.Size) { [math]::Round($_.Size / 1GB, 1) } else { $null }
    }},
    @{Name='FreeGB'; Expression = {
      if ($null -ne $_.FreeSpace) { [math]::Round($_.FreeSpace / 1GB, 1) } else { $null }
    }} |
  ConvertTo-Json -Compress
"""
    try:
        result = _powershell(primary_script, timeout=20)
    except subprocess.TimeoutExpired:
        result = subprocess.CompletedProcess(args=["powershell"], returncode=1, stdout="", stderr="Drive query timed out")
    if result.returncode == 0:
        rows = _load_json_records(result.stdout)
        if rows:
            return rows

    fallback_script = """
Get-PSDrive -PSProvider FileSystem |
  Sort-Object Name |
  Select-Object
    @{Name='DeviceID'; Expression = { $_.Name + ':' }},
    @{Name='VolumeName'; Expression = { $_.Description }},
    @{Name='DriveType'; Expression = { 'FileSystem' }},
    @{Name='SizeGB'; Expression = {
      if ($null -ne $_.Used -and $null -ne $_.Free) { [math]::Round(($_.Used + $_.Free) / 1GB, 1) } else { $null }
    }},
    @{Name='FreeGB'; Expression = {
      if ($null -ne $_.Free) { [math]::Round($_.Free / 1GB, 1) } else { $null }
    }} |
  ConvertTo-Json -Compress
"""
    try:
        fallback = _powershell(fallback_script, timeout=20)
    except subprocess.TimeoutExpired:
        fallback = subprocess.CompletedProcess(args=["powershell"], returncode=1, stdout="", stderr="Drive fallback query timed out")

    if fallback.returncode == 0:
        rows = _load_json_records(fallback.stdout)
        if rows:
            return rows

    python_rows = _windows_python_drive_rows()
    if python_rows:
        return python_rows

    detail = fallback.stderr.strip() or result.stderr.strip() or "Failed to enumerate Windows drives"
    raise RuntimeError(detail)


def _windows_open_windows(query: str = "", limit: int = 25) -> list[dict[str, Any]]:
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
    result = _powershell(ps_script, timeout=20)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to enumerate open windows")
    return _load_json_records(result.stdout)


def _windows_startup_items(query: str = "", limit: int = 25) -> list[dict[str, Any]]:
    escaped_query = _ps_quote(query)
    ps_script = f"""
$query = {escaped_query}
$limit = {int(limit)}
$entries = New-Object System.Collections.Generic.List[object]

function Add-Entry([string]$source, [string]$name, [string]$command, [string]$location) {{
  if ([string]::IsNullOrWhiteSpace($name) -and [string]::IsNullOrWhiteSpace($command)) {{
    return
  }}
  $entries.Add([pscustomobject]@{{
    Source = $source
    Name = $name
    Command = $command
    Location = $location
  }})
}}

$startupFolders = @(
  "$env:ProgramData\\Microsoft\\Windows\\Start Menu\\Programs\\Startup",
  "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\Startup"
)
foreach ($dir in $startupFolders) {{
  if (Test-Path $dir) {{
    Get-ChildItem -Path $dir -Force -ErrorAction SilentlyContinue |
      ForEach-Object {{
        Add-Entry 'StartupFolder' $_.BaseName $_.FullName $dir
      }}
  }}
}}

$runKeys = @(
  "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
  "HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Run",
  "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run"
)
foreach ($key in $runKeys) {{
  if (Test-Path $key) {{
    $item = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
    if ($item) {{
      foreach ($prop in $item.PSObject.Properties) {{
        if ($prop.Name -notin @('PSPath','PSParentPath','PSChildName','PSProvider','PSDrive')) {{
          Add-Entry 'RegistryRun' $prop.Name ([string]$prop.Value) $key
        }}
      }}
    }}
  }}
}}

$entries |
  Where-Object {{
    (-not $query) -or
    $_.Name -like "*$query*" -or
    $_.Command -like "*$query*" -or
    $_.Location -like "*$query*"
  }} |
  Sort-Object Source, Name |
  Select-Object -First $limit Source, Name, Command, Location |
  ConvertTo-Json -Compress
"""
    result = _powershell(ps_script, timeout=20)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to enumerate startup items")
    return _load_json_records(result.stdout)


def _windows_services(query: str = "", status: str = "all", limit: int = 25) -> list[dict[str, Any]]:
    escaped_query = _ps_quote(query)
    normalized_status = status.strip().lower()
    if normalized_status == "running":
        state_filter = "Running"
    elif normalized_status == "stopped":
        state_filter = "Stopped"
    else:
        state_filter = "all"
    escaped_state = _ps_quote(state_filter)
    ps_script = f"""
$query = {escaped_query}
$state = {escaped_state}
$limit = {int(limit)}
Get-CimInstance Win32_Service |
  Where-Object {{ (-not $query) -or $_.Name -like "*$query*" -or $_.DisplayName -like "*$query*" }} |
  Where-Object {{ $state -eq 'all' -or $_.State -eq $state }} |
  Sort-Object DisplayName |
  Select-Object -First $limit Name, DisplayName, State, StartMode |
  ConvertTo-Json -Compress
"""
    result = _powershell(ps_script, timeout=25)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to enumerate Windows services")
    return _load_json_records(result.stdout)


def _windows_scheduled_tasks(query: str = "", limit: int = 25) -> list[dict[str, Any]]:
    escaped_query = _ps_quote(query)
    ps_script = f"""
$query = {escaped_query}
$limit = {int(limit)}
Get-ScheduledTask -ErrorAction SilentlyContinue |
  Where-Object {{ (-not $query) -or $_.TaskName -like "*$query*" -or $_.TaskPath -like "*$query*" }} |
  Sort-Object TaskPath, TaskName |
  Select-Object -First $limit TaskName, TaskPath, State |
  ConvertTo-Json -Compress
"""
    result = _powershell(ps_script, timeout=25)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to enumerate scheduled tasks")
    return _load_json_records(result.stdout)


def _windows_installed_app_records(query: str = "", limit: int = 25) -> list[dict[str, Any]]:
    escaped_query = _ps_quote(query)
    ps_script = f"""
$query = {escaped_query}
$limit = {int(limit)}
$apps = New-Object System.Collections.Generic.List[object]

function Add-App([string]$name, [string]$version, [string]$installLocation) {{
  if ([string]::IsNullOrWhiteSpace($name)) {{
    return
  }}
  $apps.Add([pscustomobject]@{{
    Name = $name
    Version = $version
    InstallLocation = $installLocation
  }})
}}

$uninstallKeys = @(
  "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*",
  "HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*",
  "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*"
)
foreach ($key in $uninstallKeys) {{
  Get-ItemProperty -Path $key -ErrorAction SilentlyContinue |
    Where-Object {{ $_.DisplayName }} |
    ForEach-Object {{
      Add-App $_.DisplayName $_.DisplayVersion $_.InstallLocation
    }}
}}

$startMenuDirs = @(
  "$env:ProgramData\\Microsoft\\Windows\\Start Menu\\Programs",
  "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs"
)
foreach ($dir in $startMenuDirs) {{
  if (Test-Path $dir) {{
    Get-ChildItem -Path $dir -Recurse -Include *.lnk,*.appref-ms -ErrorAction SilentlyContinue |
      ForEach-Object {{
        Add-App $_.BaseName '' $_.FullName
      }}
  }}
}}

$apps |
  Where-Object {{
    (-not $query) -or
    $_.Name -like "*$query*" -or
    $_.InstallLocation -like "*$query*"
  }} |
  Sort-Object Name -Unique |
  Select-Object -First $limit Name, Version, InstallLocation |
  ConvertTo-Json -Compress
"""
    result = _powershell(ps_script, timeout=25)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to enumerate installed applications")
    return _load_json_records(result.stdout)


def register(mcp):

    @mcp.tool()
    def get_current_time() -> str:
        """Return the current date and time in both ISO 8601 and human-readable format."""
        now = datetime.datetime.now()
        return (
            f"Current time: {now.strftime('%A, %B %d, %Y at %I:%M:%S %p')}\n"
            f"ISO 8601: {now.isoformat()}"
        )

    @mcp.tool()
    def get_system_telemetry() -> dict:
        """
        Fetch host machine telemetry: CPU load, memory, and storage.
        Use this to monitor host health, especially before spawning heavy background tasks.
        """
        import multiprocessing

        telemetry = {
            "os": OS,
            "os_version": platform.version(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "cpu_cores": multiprocessing.cpu_count(),
        }

        try:
            if OS != "Windows":
                load1, load5, load15 = os.getloadavg()
                cpu_load_pct = round((load1 / telemetry["cpu_cores"]) * 100, 2)
                telemetry["cpu_load_1m_pct"] = cpu_load_pct
                telemetry["load_average"] = {"1m": load1, "5m": load5, "15m": load15}
                telemetry["thermal_status"] = "WARNING: HIGH LOAD" if cpu_load_pct > 80 else "NOMINAL"
            else:
                result = _powershell(
                    "(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average",
                    timeout=10,
                )
                cpu_load_pct = float(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip() else -1
                telemetry["cpu_load_pct"] = cpu_load_pct
                telemetry["thermal_status"] = "WARNING: HIGH LOAD" if cpu_load_pct > 80 else "NOMINAL"
        except Exception:
            telemetry["cpu_load_pct"] = "UNKNOWN"

        try:
            if OS == "Darwin":
                mem = subprocess.check_output(["sysctl", "-n", "hw.memsize"]).decode().strip()
                total_gb = int(mem) // (1024 ** 3)
                telemetry["total_memory_gb"] = total_gb
                vm = subprocess.check_output(["vm_stat"]).decode()
                page_size = 4096
                pages_active = int(
                    next(
                        (line.split(":")[1].strip().rstrip(".") for line in vm.splitlines() if "Pages active" in line),
                        0,
                    )
                )
                telemetry["used_memory_gb"] = round(pages_active * page_size / (1024 ** 3), 2)
            elif OS == "Linux":
                with open("/proc/meminfo", "r", encoding="utf-8") as handle:
                    mem_info = handle.read()
                total_kb = int(next(line.split()[1] for line in mem_info.splitlines() if line.startswith("MemTotal")))
                avail_kb = int(next(line.split()[1] for line in mem_info.splitlines() if line.startswith("MemAvailable")))
                telemetry["total_memory_gb"] = round(total_kb / (1024 ** 2), 1)
                telemetry["used_memory_gb"] = round((total_kb - avail_kb) / (1024 ** 2), 1)
                telemetry["free_memory_gb"] = round(avail_kb / (1024 ** 2), 1)
            elif OS == "Windows":
                result = _powershell(
                    "$m=(Get-CimInstance Win32_OperatingSystem); "
                    "Write-Output \"$($m.TotalVisibleMemorySize) $($m.FreePhysicalMemory)\"",
                    timeout=10,
                )
                if result.returncode == 0:
                    parts = result.stdout.strip().split()
                    if len(parts) >= 2:
                        total_kb, free_kb = int(parts[0]), int(parts[1])
                        telemetry["total_memory_gb"] = round(total_kb / (1024 ** 2), 1)
                        telemetry["free_memory_gb"] = round(free_kb / (1024 ** 2), 1)
                        telemetry["used_memory_gb"] = round((total_kb - free_kb) / (1024 ** 2), 1)
        except Exception:
            telemetry["total_memory_gb"] = "UNKNOWN"

        try:
            target = _storage_root()
            total, used, free = shutil.disk_usage(target)
            telemetry["storage_target"] = target
            telemetry["storage_total_gb"] = total // (1024 ** 3)
            telemetry["storage_used_gb"] = used // (1024 ** 3)
            telemetry["storage_free_gb"] = free // (1024 ** 3)
        except Exception:
            pass

        return telemetry

    @mcp.tool()
    def list_running_processes(top_n: int = 15) -> str:
        """
        List the top N running processes sorted by CPU usage.
        Use this when the user asks 'what's eating my CPU?', 'what processes are running?',
        or 'why is my computer slow?'.
        """
        try:
            if top_n <= 0:
                return "top_n must be greater than zero."

            if OS == "Darwin":
                result = subprocess.run(["ps", "aux", "-r"], capture_output=True, text=True, timeout=10)
            elif OS == "Linux":
                result = subprocess.run(["ps", "aux", "--sort=-%cpu"], capture_output=True, text=True, timeout=10)
            elif OS == "Windows":
                result = _powershell(
                    "Get-Process | Sort-Object CPU -Descending | "
                    f"Select-Object -First {int(top_n)} Name,CPU,WorkingSet,Id | "
                    "Format-Table Name,CPU,WorkingSet,Id -AutoSize | Out-String",
                    timeout=15,
                )
            else:
                return f"Unsupported OS: {OS}"

            if result.returncode != 0:
                return f"Could not list processes: {result.stderr.strip()}"

            lines = result.stdout.strip().splitlines()
            if OS != "Windows":
                output = [f"Top {top_n} processes (by CPU):"] + lines[: top_n + 1]
            else:
                output = [f"Top {top_n} processes (by CPU):"] + lines

            return "\n".join(output)
        except Exception as e:
            return f"Error listing processes: {str(e)}"

    @mcp.tool()
    def kill_process(identifier: str) -> str:
        """
        Kill a running process by PID (number) or process name.
        Use this when the user says 'kill X', 'stop X', or 'terminate X'.
        identifier: Either a numeric PID (e.g. '1234') or a name (e.g. 'Spotify').
        """
        try:
            if OS == "Windows":
                if identifier.isdigit():
                    result = subprocess.run(["taskkill", "/PID", identifier, "/F"], capture_output=True, text=True, timeout=5)
                else:
                    image_name = identifier if identifier.lower().endswith(".exe") else f"{identifier}.exe"
                    result = subprocess.run(["taskkill", "/IM", image_name, "/F"], capture_output=True, text=True, timeout=5)
            else:
                if identifier.isdigit():
                    result = subprocess.run(["kill", "-9", identifier], capture_output=True, text=True, timeout=5)
                else:
                    result = subprocess.run(["pkill", "-f", identifier], capture_output=True, text=True, timeout=5)

            if result.returncode == 0:
                return f"Process '{identifier}' terminated."
            if result.returncode == 1 and OS != "Windows":
                return f"No process found matching '{identifier}'."
            return f"Error killing '{identifier}': {result.stderr.strip()}"
        except Exception as e:
            return f"Error killing process: {str(e)}"

    @mcp.tool()
    def get_environment_info() -> str:
        """
        Return a summary of the current runtime environment - OS, Python, paths, user.
        """
        try:
            elevated = _is_elevated()
            info = {
                "os": f"{OS} {platform.release()}",
                "os_version": platform.version(),
                "machine": platform.machine(),
                "hostname": platform.node(),
                "python": platform.python_version(),
                "user": os.environ.get("USER", os.environ.get("USERNAME", "unknown")),
                "home": str(os.path.expanduser("~")),
                "workspace": str(workspace_dir()),
                "shell": os.environ.get("SHELL", os.environ.get("COMSPEC", "unknown")),
                "elevated": elevated if elevated is not None else "unknown",
            }
            lines = [f"{key}: {value}" for key, value in info.items()]
            return "=== System Environment ===\n" + "\n".join(lines)
        except Exception as e:
            return f"Error getting environment: {str(e)}"

    @mcp.tool()
    def get_host_control_status() -> str:
        """
        Return whether FRIDAY is running with broad desktop-control prerequisites.
        Use this before system-wide tasks so the agent knows whether it has elevated
        rights, where the workspace is, and whether visible browser automation is enabled.
        """
        try:
            elevated = _is_elevated()
            status = {
                "os": OS,
                "hostname": platform.node(),
                "user": os.environ.get("USER", os.environ.get("USERNAME", "unknown")),
                "workspace": str(workspace_dir()),
                "shell": os.environ.get("SHELL", os.environ.get("COMSPEC", "unknown")),
                "elevated": elevated if elevated is not None else "unknown",
                "browser_headless": os.environ.get("FRIDAY_BROWSER_HEADLESS", "").strip().lower() in {"1", "true", "yes", "on"},
                "code_cli_available": bool(shutil.which("code")),
            }
            notes: list[str] = []
            if elevated is False:
                notes.append("Administrator-only tasks may fail until FRIDAY is started from an elevated terminal.")
            if status["browser_headless"]:
                notes.append("Browser automation is currently headless; set FRIDAY_BROWSER_HEADLESS=0 for visible browsing.")
            if not status["code_cli_available"]:
                notes.append("VS Code launcher was not found on PATH.")
            status["notes"] = notes
            return json.dumps(status, indent=2)
        except Exception as e:
            return f"Error getting host control status: {str(e)}"

    @mcp.tool()
    def open_elevated_terminal(command: str = "", working_directory: str = "") -> str:
        """
        Open an Administrator PowerShell window on Windows, optionally preloaded with a command.
        The user will still need to approve the Windows UAC prompt.
        Use this when a task truly needs elevated rights and the boss wants a visible admin shell.
        """
        try:
            if OS != "Windows":
                return "Elevated terminal launching is currently implemented for Windows only."

            target_dir = resolve_user_path(working_directory) if working_directory.strip() else Path.cwd().resolve()
            script_lines = [f"Set-Location -LiteralPath {_ps_quote(str(target_dir))}"]
            if command.strip():
                script_lines.append(command)
            payload = "\n".join(script_lines)
            encoded = base64.b64encode(payload.encode("utf-16le")).decode("ascii")

            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    (
                        "Start-Process powershell "
                        f"-Verb RunAs -WorkingDirectory {_ps_quote(str(target_dir))} "
                        f"-ArgumentList @('-NoExit','-EncodedCommand','{encoded}')"
                    ),
                ],
                capture_output=True,
                text=True,
                timeout=20,
            )

            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip() or "Could not open elevated terminal."
                return f"Error opening elevated terminal: {detail}"

            if command.strip():
                return (
                    f"Opened an Administrator PowerShell at {target_dir}. "
                    f"After UAC approval it will run: {command}"
                )
            return f"Opened an Administrator PowerShell at {target_dir}. Approve the UAC prompt to continue."
        except Exception as e:
            return f"Error opening elevated terminal: {str(e)}"

    @mcp.tool()
    def list_disk_drives() -> str:
        """
        List mounted drives with size and free-space information.
        Use this when the user asks about available disks, partitions, removable drives,
        or where FRIDAY can read and write files.
        """
        try:
            if OS == "Windows":
                rows = _windows_disk_drives()
                return _format_section("Disk Drives", _format_drive_rows(rows), "No mounted drives found.")

            target = _storage_root()
            total, used, free = shutil.disk_usage(target)
            lines = [f"- {target} | free={free // (1024 ** 3)} GB / total={total // (1024 ** 3)} GB"]
            return _format_section("Disk Drives", lines, "No mounted drives found.")
        except Exception as e:
            return f"Error listing disk drives: {str(e)}"

    @mcp.tool()
    def list_startup_items(query: str = "", limit: int = 25) -> str:
        """
        List startup items that launch automatically when the user signs in.
        Useful when the user asks what auto-runs on boot or how to audit login-time programs.
        """
        try:
            if limit <= 0:
                return "Limit must be greater than zero."
            if OS != "Windows":
                return "Startup item inspection is currently implemented for Windows only."

            rows = _windows_startup_items(query=query, limit=limit)
            lines = [
                f"- {row.get('Name') or '(unnamed)'} | {row.get('Source') or 'Unknown'} | {_short(row.get('Command') or row.get('Location'))}"
                for row in rows
            ]
            return _format_section("Startup Items", lines, "No startup items found.")
        except Exception as e:
            return f"Error listing startup items: {str(e)}"

    @mcp.tool()
    def list_windows_services(query: str = "", status: str = "all", limit: int = 25) -> str:
        """
        List Windows services, optionally filtered by query and status.
        status: 'all', 'running', or 'stopped'.
        """
        try:
            if limit <= 0:
                return "Limit must be greater than zero."
            if OS != "Windows":
                return "Windows service inspection is available on Windows only."

            rows = _windows_services(query=query, status=status, limit=limit)
            lines = [
                f"- {row.get('DisplayName') or row.get('Name') or '(unnamed)'} | state={row.get('State') or '?'} | start={row.get('StartMode') or '?'} | name={row.get('Name') or '?'}"
                for row in rows
            ]
            return _format_section("Windows Services", lines, "No matching services found.")
        except Exception as e:
            return f"Error listing Windows services: {str(e)}"

    @mcp.tool()
    def list_scheduled_tasks(query: str = "", limit: int = 25) -> str:
        """
        List scheduled tasks on Windows.
        Use this when the user wants to inspect background automations, maintenance tasks, or login triggers.
        """
        try:
            if limit <= 0:
                return "Limit must be greater than zero."
            if OS != "Windows":
                return "Scheduled task inspection is currently implemented for Windows only."

            rows = _windows_scheduled_tasks(query=query, limit=limit)
            lines = [
                f"- {_task_display_name(row)} | state={row.get('State') or '?'}"
                for row in rows
            ]
            return _format_section("Scheduled Tasks", lines, "No matching scheduled tasks found.")
        except Exception as e:
            return f"Error listing scheduled tasks: {str(e)}"

    @mcp.tool()
    def scan_system_inventory(section: str = "summary", query: str = "", limit: int = 15) -> str:
        """
        Build a broader machine inventory snapshot.
        section options:
        - 'summary': overview, key paths, drives, open windows, and installed apps
        - 'drives', 'windows', 'apps', 'startup', 'services', 'scheduled_tasks'
        - 'all': a deeper Windows-wide scan across every section above
        Use this when the user asks to scan the system, audit what is installed, or inspect the machine at a high level.
        """
        normalized = section.strip().lower() or "summary"
        aliases = {
            "open_windows": "windows",
            "tasks": "scheduled_tasks",
        }
        normalized = aliases.get(normalized, normalized)
        valid_sections = {"summary", "drives", "windows", "apps", "startup", "services", "scheduled_tasks", "all"}

        if normalized not in valid_sections:
            allowed = ", ".join(sorted(valid_sections))
            return f"Unknown section '{section}'. Use one of: {allowed}."
        if limit <= 0:
            return "Limit must be greater than zero."

        try:
            telemetry = get_system_telemetry()
        except Exception:
            telemetry = {}

        try:
            overview_lines = [
                f"OS: {OS} {platform.release()}",
                f"Hostname: {platform.node()}",
                f"User: {os.environ.get('USER', os.environ.get('USERNAME', 'unknown'))}",
                f"Python: {platform.python_version()}",
            ]
            elevated = _is_elevated()
            overview_lines.append(
                "Privileges: "
                + (
                    "elevated/admin"
                    if elevated is True
                    else "standard user"
                    if elevated is False
                    else "unknown"
                )
            )
            if "cpu_load_pct" in telemetry:
                overview_lines.append(f"CPU load: {telemetry['cpu_load_pct']}%")
            elif "cpu_load_1m_pct" in telemetry:
                overview_lines.append(f"CPU load (1m): {telemetry['cpu_load_1m_pct']}%")
            if "used_memory_gb" in telemetry and "total_memory_gb" in telemetry:
                overview_lines.append(
                    f"Memory: {telemetry['used_memory_gb']} GB used / {telemetry['total_memory_gb']} GB total"
                )
            if "storage_free_gb" in telemetry and "storage_total_gb" in telemetry:
                overview_lines.append(
                    f"Storage ({telemetry.get('storage_target', _storage_root())}): "
                    f"{telemetry['storage_free_gb']} GB free / {telemetry['storage_total_gb']} GB total"
                )

            path_lines = [f"- {name}: {path}" for name, path in known_user_paths().items()]
            parts = [
                _format_section("System Overview", overview_lines, "No overview data available."),
                _format_section("Key Paths", path_lines, "No user paths resolved."),
            ]

            if OS != "Windows":
                if normalized in {"summary", "drives", "all"}:
                    parts.append(list_disk_drives())
                if normalized in {"summary", "windows", "apps", "startup", "services", "scheduled_tasks", "all"}:
                    parts.append(
                        "Detailed machine inventory sections beyond basic drives and environment are currently Windows-focused."
                    )
                return "\n\n".join(parts)

            if normalized in {"summary", "drives", "all"}:
                parts.append(
                    _format_section(
                        "Disk Drives",
                        _format_drive_rows(_windows_disk_drives()[:limit]),
                        "No mounted drives found.",
                    )
                )

            if normalized in {"summary", "windows", "all"}:
                window_rows = _windows_open_windows(query=query, limit=limit)
                window_lines = [
                    f"- {row.get('ProcessName') or '?'} [{row.get('Id') or '?'}] | {_short(row.get('MainWindowTitle'))}"
                    for row in window_rows
                ]
                parts.append(_format_section("Open Windows", window_lines, "No matching windows found."))

            if normalized in {"summary", "apps", "all"}:
                app_rows = _windows_installed_app_records(query=query, limit=limit)
                app_lines = [
                    f"- {row.get('Name') or '(unnamed)'}"
                    + (f" | version={row.get('Version')}" if row.get("Version") not in (None, "") else "")
                    + (
                        f" | location={_short(row.get('InstallLocation'))}"
                        if row.get("InstallLocation") not in (None, "")
                        else ""
                    )
                    for row in app_rows
                ]
                parts.append(_format_section("Installed Applications", app_lines, "No matching installed applications found."))

            if normalized in {"startup", "all"}:
                startup_rows = _windows_startup_items(query=query, limit=limit)
                startup_lines = [
                    f"- {row.get('Name') or '(unnamed)'} | {row.get('Source') or 'Unknown'} | {_short(row.get('Command') or row.get('Location'))}"
                    for row in startup_rows
                ]
                parts.append(_format_section("Startup Items", startup_lines, "No matching startup items found."))

            if normalized in {"services", "all"}:
                service_rows = _windows_services(query=query, status="all", limit=limit)
                service_lines = [
                    f"- {row.get('DisplayName') or row.get('Name') or '(unnamed)'} | state={row.get('State') or '?'} | start={row.get('StartMode') or '?'}"
                    for row in service_rows
                ]
                parts.append(_format_section("Windows Services", service_lines, "No matching services found."))

            if normalized in {"scheduled_tasks", "all"}:
                task_rows = _windows_scheduled_tasks(query=query, limit=limit)
                task_lines = [
                    f"- {_task_display_name(row)} | state={row.get('State') or '?'}"
                    for row in task_rows
                ]
                parts.append(_format_section("Scheduled Tasks", task_lines, "No matching scheduled tasks found."))

            if normalized == "summary":
                parts.append(
                    "Tip: use scan_system_inventory with section='all', 'startup', 'services', or 'scheduled_tasks' for a deeper Windows audit."
                )

            return "\n\n".join(parts)
        except Exception as e:
            return f"Error scanning system inventory: {str(e)}"
