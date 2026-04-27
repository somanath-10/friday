"""Download policy helpers for the browser runtime."""

from __future__ import annotations

from pathlib import Path

from friday.browser.profile_manager import friday_downloads_path
from friday.core.permissions import PermissionDecision, check_tool_permission


EXECUTABLE_SUFFIXES = {".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".app", ".bat", ".cmd", ".ps1", ".sh"}


def download_target_path(filename: str, *, downloads_dir: Path | None = None) -> Path:
    safe_name = Path(filename).name.strip() or "download.bin"
    root = downloads_dir or friday_downloads_path()
    root.mkdir(parents=True, exist_ok=True)
    return root / safe_name


def is_executable_download(path_or_name: str | Path) -> bool:
    return Path(path_or_name).suffix.lower() in EXECUTABLE_SUFFIXES


def check_download_permission(path_or_name: str | Path) -> PermissionDecision:
    target = str(path_or_name)
    if is_executable_download(target):
        return check_tool_permission("browser_download_executable", {"path": target}, subject=target)
    return check_tool_permission("browser_download", {"path": target}, subject=target)
