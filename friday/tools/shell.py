"""
Shell command execution tool — allows F.R.I.D.A.Y. to run arbitrary OS terminal commands.
"""

import subprocess
import platform
import os

from friday.subprocess_utils import run_powershell

OS = platform.system()

def register(mcp):

    @mcp.tool()
    def execute_shell_command(command: str) -> str:
        """
        Execute an arbitrary shell or command-line program on the host OS.
        Use this to handle all unseen types of tasks (like running git, executing scripts, modifying OS settings, etc.).
        Returns the standard output and standard error. Note: The process will timeout after 60 seconds.
        """
        try:
            if OS == "Windows":
                # Use powershell for rich capabilities
                result = run_powershell(command, timeout=60, no_profile=False, force_utf8=False)
            else:
                # Use bash for Linux/macOS
                result = subprocess.run(
                    command,
                    shell=True,
                    executable="/bin/bash" if os.path.exists("/bin/bash") else None,
                    capture_output=True,
                    text=True,
                    timeout=60
                )

            output = ""
            if result.stdout:
                output += "STDOUT:\n" + result.stdout.strip() + "\n"
            if result.stderr:
                output += "STDERR:\n" + result.stderr.strip() + "\n"

            if not output.strip():
                output = f"Command executed successfully (exit code {result.returncode}) but returned no output."

            if len(output) > 4000:
                output = output[:4000] + "\n... [TRUNCATED]"

            return output
        except subprocess.TimeoutExpired:
            return "Command execution timed out after 60 seconds."
        except Exception as e:
            return f"Error executing command: {str(e)}"
