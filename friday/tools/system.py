"""
System tools — time, environment info, process management, and host telemetry.
Supports: macOS, Linux, and Windows.
"""

import datetime
import platform
import subprocess
import os

OS = platform.system()  # "Darwin" | "Linux" | "Windows"


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
        import shutil
        import multiprocessing

        telemetry = {
            "os": OS,
            "os_version": platform.version(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "cpu_cores": multiprocessing.cpu_count(),
        }

        # CPU Load
        try:
            if OS != "Windows":
                load1, load5, load15 = os.getloadavg()
                cpu_load_pct = round((load1 / telemetry["cpu_cores"]) * 100, 2)
                telemetry["cpu_load_1m_pct"] = cpu_load_pct
                telemetry["thermal_status"] = "WARNING: HIGH LOAD" if cpu_load_pct > 80 else "NOMINAL"
            else:
                result = subprocess.run(
                    ["powershell", "-Command",
                     "(Get-WmiObject Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average"],
                    capture_output=True, text=True, timeout=10
                )
                cpu_load_pct = float(result.stdout.strip()) if result.returncode == 0 else -1
                telemetry["cpu_load_pct"] = cpu_load_pct
                telemetry["thermal_status"] = "WARNING: HIGH LOAD" if cpu_load_pct > 80 else "NOMINAL"
        except Exception:
            telemetry["cpu_load_1m_pct"] = "UNKNOWN"

        # Memory
        try:
            if OS == "Darwin":
                mem = subprocess.check_output(["sysctl", "-n", "hw.memsize"]).decode().strip()
                total_gb = int(mem) // (1024 ** 3)
                telemetry["total_memory_gb"] = total_gb
                vm = subprocess.check_output(["vm_stat"]).decode()
                page_size = 4096
                pages_active = int(next(
                    (l.split(":")[1].strip().rstrip(".") for l in vm.splitlines() if "Pages active" in l), 0
                ))
                telemetry["used_memory_gb"] = round(pages_active * page_size / (1024 ** 3), 2)
            elif OS == "Linux":
                mem_info = open("/proc/meminfo").read()
                total_kb = int(next(l.split()[1] for l in mem_info.splitlines() if l.startswith("MemTotal")))
                avail_kb = int(next(l.split()[1] for l in mem_info.splitlines() if l.startswith("MemAvailable")))
                telemetry["total_memory_gb"] = round(total_kb / (1024 ** 2), 1)
                telemetry["used_memory_gb"] = round((total_kb - avail_kb) / (1024 ** 2), 1)
                telemetry["free_memory_gb"] = round(avail_kb / (1024 ** 2), 1)
            elif OS == "Windows":
                result = subprocess.run(
                    ["powershell", "-Command",
                     "$m=(Get-WmiObject Win32_OperatingSystem); "
                     "Write-Output \"$($m.TotalVisibleMemorySize) $($m.FreePhysicalMemory)\""],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    parts = result.stdout.strip().split()
                    total_kb, free_kb = int(parts[0]), int(parts[1])
                    telemetry["total_memory_gb"] = round(total_kb / (1024 ** 2), 1)
                    telemetry["free_memory_gb"] = round(free_kb / (1024 ** 2), 1)
                    telemetry["used_memory_gb"] = round((total_kb - free_kb) / (1024 ** 2), 1)
        except Exception:
            telemetry["total_memory_gb"] = "UNKNOWN"

        # Storage
        try:
            total, used, free = shutil.disk_usage("/")
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
        'why is my computer slow?'.
        """
        try:
            if OS == "Darwin":
                result = subprocess.run(["ps", "aux", "-r"], capture_output=True, text=True, timeout=10)
            elif OS == "Linux":
                result = subprocess.run(["ps", "aux", "--sort=-%cpu"], capture_output=True, text=True, timeout=10)
            elif OS == "Windows":
                result = subprocess.run(
                    ["powershell", "-Command",
                     "Get-Process | Sort-Object CPU -Descending | Select-Object -First 15 | "
                     "Format-Table Name,CPU,WorkingSet -AutoSize | Out-String"],
                    capture_output=True, text=True, timeout=10
                )

            if result.returncode != 0:
                return f"Could not list processes: {result.stderr.strip()}"

            lines = result.stdout.strip().splitlines()
            if OS != "Windows":
                output = [f"Top {top_n} processes (by CPU):"] + lines[:top_n + 1]
            else:
                output = [f"Top processes (by CPU):"] + lines

            return "\n".join(output)
        except Exception as e:
            return f"Error listing processes: {str(e)}"

    @mcp.tool()
    def kill_process(identifier: str) -> str:
        """
        Kill a running process by PID (number) or process name.
        Use this when the user says 'kill X', 'stop X', 'terminate X'.
        identifier: Either a numeric PID (e.g. '1234') or a name (e.g. 'Spotify').
        """
        try:
            if OS == "Windows":
                if identifier.isdigit():
                    result = subprocess.run(["taskkill", "/PID", identifier, "/F"], capture_output=True, text=True, timeout=5)
                else:
                    result = subprocess.run(["taskkill", "/IM", f"{identifier}.exe", "/F"], capture_output=True, text=True, timeout=5)
            else:  # macOS / Linux
                if identifier.isdigit():
                    result = subprocess.run(["kill", "-9", identifier], capture_output=True, text=True, timeout=5)
                else:
                    result = subprocess.run(["pkill", "-f", identifier], capture_output=True, text=True, timeout=5)

            if result.returncode == 0:
                return f"Process '{identifier}' terminated."
            elif result.returncode == 1 and OS != "Windows":
                return f"No process found matching '{identifier}'."
            return f"Error killing '{identifier}': {result.stderr.strip()}"
        except Exception as e:
            return f"Error killing process: {str(e)}"

    @mcp.tool()
    def get_environment_info() -> str:
        """
        Return a summary of the current runtime environment — OS, Python, paths, user.
        """
        try:
            info = {
                "os": f"{OS} {platform.release()}",
                "os_version": platform.version(),
                "machine": platform.machine(),
                "hostname": platform.node(),
                "python": platform.python_version(),
                "user": os.environ.get("USER", os.environ.get("USERNAME", "unknown")),
                "home": str(os.path.expanduser("~")),
                "workspace": os.path.abspath(os.environ.get("FRIDAY_WORKSPACE_DIR", "workspace")),
                "shell": os.environ.get("SHELL", os.environ.get("COMSPEC", "unknown")),
            }
            lines = [f"{k}: {v}" for k, v in info.items()]
            return "=== System Environment ===\n" + "\n".join(lines)
        except Exception as e:
            return f"Error getting environment: {str(e)}"
