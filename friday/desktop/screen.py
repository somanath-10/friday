"""
Screen observation helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from friday.path_utils import workspace_dir


@dataclass(frozen=True)
class ScreenshotResult:
    ok: bool
    path: str = ""
    error: str = ""


def _load_pyautogui():
    import pyautogui

    pyautogui.FAILSAFE = True
    return pyautogui


def screenshot_path(filename: str = "") -> Path:
    name = Path(filename).name if filename else "desktop_screenshot.png"
    path = workspace_dir() / "screenshots" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def take_screenshot(filename: str = "") -> ScreenshotResult:
    try:
        target = screenshot_path(filename)
        pyautogui = _load_pyautogui()
        image = pyautogui.screenshot()
        image.save(target)
        return ScreenshotResult(ok=True, path=str(target))
    except Exception as exc:
        return ScreenshotResult(ok=False, error=f"Screenshot failed: {exc}")


def inspect_screen(question: str = "") -> dict[str, str | bool]:
    screenshot = take_screenshot()
    if not screenshot.ok:
        return {"ok": False, "error": screenshot.error, "question": question}
    return {
        "ok": True,
        "screenshot": screenshot.path,
        "summary": "Screenshot captured. Visual analysis can be layered on top when a vision provider is configured.",
        "question": question,
    }
