"""
Desktop application backend selection.
"""

from __future__ import annotations

import platform

from friday.desktop.linux_backend import LinuxBackend
from friday.desktop.macos_backend import MacOSBackend
from friday.desktop.windows_backend import WindowsBackend


def get_backend():
    system = platform.system()
    if system == "Darwin":
        return MacOSBackend()
    if system == "Windows":
        return WindowsBackend()
    return LinuxBackend()
