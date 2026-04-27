"""
Desktop permission diagnostics.
"""

from __future__ import annotations

import platform
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class DesktopPermissionStatus:
    screen: str
    accessibility: str
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_desktop_permissions(*, live_checks: bool = False) -> DesktopPermissionStatus:
    system = platform.system()
    warnings: list[str] = []

    if system == "Darwin":
        if not live_checks:
            return DesktopPermissionStatus(
                screen="unknown",
                accessibility="unknown",
                warnings=[
                    "macOS may require Screen Recording and Accessibility permissions for desktop control.",
                    "Run live permission diagnostics before coordinate clicking or typing.",
                ],
            )

        screen = "unknown"
        accessibility = "unknown"
        with tempfile.NamedTemporaryFile(suffix=".png") as tmp:
            try:
                result = subprocess.run(["screencapture", "-x", tmp.name], capture_output=True, text=True, timeout=5)
                screen = "granted" if result.returncode == 0 else "missing"
            except Exception as exc:
                screen = "unknown"
                warnings.append(f"Screen Recording check failed: {exc}")
        try:
            result = subprocess.run(
                ["osascript", "-e", 'tell application "System Events" to get name of every process'],
                capture_output=True,
                text=True,
                timeout=5,
            )
            accessibility = "granted" if result.returncode == 0 else "missing"
        except Exception as exc:
            accessibility = "unknown"
            warnings.append(f"Accessibility check failed: {exc}")
        return DesktopPermissionStatus(screen=screen, accessibility=accessibility, warnings=warnings)

    if system == "Windows":
        return DesktopPermissionStatus(
            screen="available",
            accessibility="available",
            warnings=["Some desktop actions may still require Administrator or UAC approval."],
        )

    return DesktopPermissionStatus(
        screen="unknown",
        accessibility="unknown",
        warnings=["Linux desktop control depends on X11/Wayland and installed tools such as xdotool or wmctrl."],
    )
