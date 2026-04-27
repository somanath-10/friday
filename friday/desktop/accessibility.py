"""
Desktop permission diagnostics for the Windows-first control layer.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, asdict
from typing import Any

from friday.desktop.windows_backend import WINDOWS_ONLY_MESSAGE, desktop_windows_status


@dataclass(frozen=True)
class DesktopPermissionStatus:
    screen: str
    accessibility: str
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_desktop_permissions(*, live_checks: bool = False) -> DesktopPermissionStatus:
    system = platform.system()
    if system != "Windows":
        return DesktopPermissionStatus(
            screen="unsupported",
            accessibility="unsupported",
            warnings=[WINDOWS_ONLY_MESSAGE],
        )

    status = desktop_windows_status()
    warnings = list(status.warnings)
    if live_checks:
        warnings.append("Windows desktop checks rely on UI Automation, PowerShell, and screenshot fallbacks rather than OS privacy prompts.")
    else:
        warnings.append("Run a dry-run desktop task first, then a real Notepad open/type check, before broader automation.")

    if status.pywinauto_available:
        accessibility = "available"
    elif status.powershell_available:
        accessibility = "limited"
    else:
        accessibility = "missing"

    screen = "available" if status.pyautogui_available else "limited"
    return DesktopPermissionStatus(screen=screen, accessibility=accessibility, warnings=warnings)
