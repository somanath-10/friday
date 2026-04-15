"""
System tools — time, environment info, process management, and host telemetry.
"""

import datetime
import platform
import subprocess
import os


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
        [MARK IV UPGRADE] Fetch deep host machine telemetry (CPU load, active memory, storage).
        Use this to monitor the host health, especially when running heavy background Subagents!
        """
        import shutil
        import multiprocessing

        telemetry = {
            "os": platform.system(),
            "os_version": platform.version(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
            "cpu_cores": multiprocessing.cpu_count(),
        }

        # CPU Load
        try:
            load1, load5, load15 = os.getloadavg()
            cpu_load_pct = round((load1 / telemetry["cpu_cores"]) * 100, 2)
            telemetry["cpu_load_1m_pct"] = cpu_load_pct
            telemetry["thermal_status"] = "WARNING: HIGH LOAD" if cpu_load_pct > 80 else "NOMINAL"
        except Exception:
            telemetry["cpu_load_1m_pct"] = "UNKNOWN"

        # Memory
        try:
            if telemetry["os"] == "Darwin":
                mem = subprocess.check_output(['sysctl', '-n', 'hw.memsize']).decode().strip()
                telemetry["total_memory_gb"] = int(mem) // (1024 ** 3)
                # Get used memory via vm_stat
                vm = subprocess.check_output(['vm_stat']).decode()
                pages_free = int(next((l.split(':')[1].strip().rstrip('.') for l in vm.splitlines() if 'Pages free' in l), 0))
                pages_active = int(next((l.split(':')[1].strip().rstrip('.') for l in vm.splitlines() if 'Pages active' in l), 0))
                page_size = 4096
                used_gb = round(pages_active * page_size / (1024 ** 3), 2)
                free_gb = round(pages_free * page_size / (1024 ** 3), 2)
                telemetry["used_memory_gb"] = used_gb
                telemetry["free_memory_gb"] = free_gb
            elif telemetry["os"] == "Linux":
                total = (os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')) // (1024 ** 3)
                telemetry["total_memory_gb"] = total
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
        'what's using my memory?', 'why is my Mac slow?'.
        top_n: How many top processes to return (default 15).
        """
        try:
            if platform.system() == "Darwin":
                result = subprocess.run(
                    ["ps", "aux", "-r"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode != 0:
                    return f"Could not list processes: {result.stderr.strip()}"

                lines = result.stdout.strip().splitlines()
                header = lines[0] if lines else ""
                processes = lines[1:top_n + 1]

                output = [f"Top {top_n} processes (sorted by CPU):", header]
                output.extend(processes)
                return "\n".join(output)

            elif platform.system() == "Linux":
                result = subprocess.run(
                    ["ps", "aux", "--sort=-%cpu"],
                    capture_output=True, text=True, timeout=10
                )
                lines = result.stdout.strip().splitlines()
                output = [f"Top {top_n} processes:"] + lines[:top_n + 1]
                return "\n".join(output)

            return "Process listing not supported on this OS."
        except Exception as e:
            return f"Error listing processes: {str(e)}"

    @mcp.tool()
    def kill_process(identifier: str) -> str:
        """
        Kill a running process by PID (number) or process name.
        Use this when the user says 'kill X', 'stop X', 'terminate X', 'close X process'.
        identifier: Either a numeric PID (e.g. '1234') or a process name (e.g. 'Spotify').
        WARNING: This immediately terminates the process. Be careful.
        """
        try:
            if identifier.isdigit():
                # Kill by PID
                result = subprocess.run(
                    ["kill", "-9", identifier],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    return f"Process PID {identifier} terminated."
                return f"Could not kill PID {identifier}: {result.stderr.strip()}"
            else:
                # Kill by name using pkill
                result = subprocess.run(
                    ["pkill", "-f", identifier],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    return f"Process matching '{identifier}' terminated."
                elif result.returncode == 1:
                    return f"No process found matching '{identifier}'."
                return f"Error killing '{identifier}': {result.stderr.strip()}"
        except Exception as e:
            return f"Error killing process: {str(e)}"

    @mcp.tool()
    def get_environment_info() -> str:
        """
        Return a summary of the current runtime environment — OS, Python, paths, user.
        Use this to understand the host system configuration.
        """
        try:
            info = {
                "os": f"{platform.system()} {platform.release()}",
                "os_version": platform.version(),
                "machine": platform.machine(),
                "hostname": platform.node(),
                "python": platform.python_version(),
                "user": os.environ.get("USER", os.environ.get("USERNAME", "unknown")),
                "home": str(os.path.expanduser("~")),
                "workspace": os.path.abspath(os.environ.get("FRIDAY_WORKSPACE_DIR", "workspace")),
                "shell": os.environ.get("SHELL", "unknown"),
                "path_preview": os.environ.get("PATH", "")[:200],
            }
            lines = [f"{k}: {v}" for k, v in info.items()]
            return "=== System Environment ===\n" + "\n".join(lines)
        except Exception as e:
            return f"Error getting environment: {str(e)}"
