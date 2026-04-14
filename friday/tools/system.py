"""
System tools — time, environment info, shell commands, etc.
"""

import datetime
import platform


def register(mcp):

    @mcp.tool()
    def get_current_time() -> str:
        """Return the current date and time in ISO 8601 format."""
        return datetime.datetime.now().isoformat()

    @mcp.tool()
    def get_system_telemetry() -> dict:
        """
        [MARK IV UPGRADE] Fetch deep host machine telemetry (CPU load, active memory, storage).
        Use this to monitor the host health, especially when running heavy background Subagents!
        """
        import os
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
                import subprocess
                mem = subprocess.check_output(['sysctl', '-n', 'hw.memsize']).decode('utf-8').strip()
                telemetry["total_memory_gb"] = int(mem) // (1024**3)
            elif telemetry["os"] == "Linux":
                telemetry["total_memory_gb"] = (os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES')) // (1024**3)
        except Exception:
            telemetry["total_memory_gb"] = "UNKNOWN"
            
        # Storage
        try:
            total, used, free = shutil.disk_usage("/")
            telemetry["storage_total_gb"] = total // (1024**3)
            telemetry["storage_used_gb"] = used // (1024**3)
            telemetry["storage_free_gb"] = free // (1024**3)
        except Exception:
            pass
            
        return telemetry
