"""
Desktop application backend selection.
"""

from __future__ import annotations

import platform
from typing import Any

from friday.desktop.windows_backend import WINDOWS_ONLY_MESSAGE, WindowsBackend


class UnsupportedDesktopBackend:
    name = "unsupported"
    unsupported_message = WINDOWS_ONLY_MESSAGE

    def __init__(self, system_name: str) -> None:
        self.system_name = system_name

    def _response(self) -> dict[str, Any]:
        return {"ok": False, "message": self.unsupported_message, "platform": self.system_name}

    def open_application(self, app_name: str) -> dict[str, Any]:
        return self._response()

    def focus_application(self, app_name: str) -> dict[str, Any]:
        return self._response()

    def close_application(self, app_name: str) -> dict[str, Any]:
        return self._response()

    def list_open_windows(self) -> list[dict[str, Any]]:
        return []

    def get_active_window(self) -> dict[str, Any]:
        return self._response() | {"title": "", "app": ""}

    def list_installed_apps(self) -> list[dict[str, Any]]:
        return []


def get_backend():
    system = platform.system()
    if system == "Windows":
        return WindowsBackend()
    return UnsupportedDesktopBackend(system)
