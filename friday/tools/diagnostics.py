import subprocess
import platform
import tempfile
from typing import Dict, Any

from friday.tools.error_handling import safe_tool

def _check_macos_screen_recording() -> Dict[str, Any]:
    """Check if macOS screen recording permission is granted."""
    with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
        # -x means mute sound
        result = subprocess.run(
            ["screencapture", "-x", tmp.name],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return {
                "status": "Granted",
                "message": "Screen recording permission is active."
            }
        else:
            return {
                "status": "Denied/Missing",
                "message": "Screen recording permission is missing.",
                "fix": "Run the following command in your terminal to open settings:\n    open \"x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture\"\nThen enable access for your terminal application."
            }

def _check_macos_accessibility() -> Dict[str, Any]:
    """Check if macOS Accessibility permission is granted."""
    script = 'tell application "System Events" to get name of every process'
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=5
    )
    if result.returncode == 0:
        return {
            "status": "Granted",
            "message": "Accessibility permission is active."
        }
    else:
        return {
            "status": "Denied/Missing",
            "message": "Accessibility permission is missing. (Error: 'Not allowed to send Apple events to System Events' or similar).",
            "fix": "Run the following command in your terminal to open settings:\n    open \"x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility\"\nThen enable access for your terminal application."
        }

def _check_windows_permissions() -> Dict[str, Any]:
    """Basic check for Windows."""
    return {
        "status": "Info",
        "message": "Windows typically does not require explicit screen/accessibility permissions for Python apps unless restricted by an Antivirus or Group Policy."
    }

def register(mcp):
    @mcp.tool()
    @safe_tool
    def run_permission_diagnostics() -> str:
        """
        Run a diagnostic check to verify if the F.R.I.D.A.Y. server has the necessary OS-level permissions.
        Use this if desktop-aware tools (like screen capture or app control) fail or if the user asks about permissions.
        Returns a formatted markdown report.
        """
        system = platform.system()
        report = [f"## F.R.I.D.A.Y. Permission Diagnostics ({system})", ""]

        if system == "Darwin":
            # macOS checks
            sr_check = _check_macos_screen_recording()
            report.append(f"### 🖥️ Screen Recording: {sr_check['status']}")
            report.append(sr_check["message"])
            if "fix" in sr_check:
                report.append("\n**How to Fix:**\n```bash\n" + sr_check["fix"].replace("    ", "") + "\n```")
            report.append("")

            acc_check = _check_macos_accessibility()
            report.append(f"### 🖱️ Accessibility: {acc_check['status']}")
            report.append(acc_check["message"])
            if "fix" in acc_check:
                report.append("\n**How to Fix:**\n```bash\n" + acc_check["fix"].replace("    ", "") + "\n```")

        elif system == "Windows":
            win_check = _check_windows_permissions()
            report.append(f"### Windows Diagnostics: {win_check['status']}")
            report.append(win_check["message"])
        else:
            report.append("### Linux Diagnostics")
            report.append("Linux permissions depend heavily on the display server (X11 vs Wayland). Ensure tools like `scrot` or `gnome-screenshot` are installed.")

        return "\n".join(report)
