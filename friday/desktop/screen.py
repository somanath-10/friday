"""
Windows-first screen observation helpers.
"""

from __future__ import annotations

import importlib.util
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from friday.path_utils import workspace_dir
from friday.safety.secrets_filter import redact_text


WINDOWS_ONLY_MESSAGE = "This desktop-control feature is currently implemented for Windows only."


@dataclass(frozen=True)
class ScreenshotResult:
    ok: bool
    path: str = ""
    error: str = ""


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


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
    if not _is_windows():
        return ScreenshotResult(ok=False, error=WINDOWS_ONLY_MESSAGE)

    target = screenshot_path(filename)
    try:
        pyautogui = _load_pyautogui()
        image = pyautogui.screenshot()
        image.save(target)
        return ScreenshotResult(ok=True, path=str(target))
    except Exception as first_exc:
        if _module_available("PIL.ImageGrab"):
            try:
                from PIL import ImageGrab  # type: ignore

                image = ImageGrab.grab(all_screens=True)
                image.save(target)
                return ScreenshotResult(ok=True, path=str(target))
            except Exception as second_exc:
                return ScreenshotResult(ok=False, error=f"Screenshot failed: {second_exc}")
        return ScreenshotResult(ok=False, error=f"Screenshot failed: {first_exc}")


def _ocr_text(image_path: str) -> tuple[str, str]:
    if not _module_available("pytesseract"):
        return "", "OCR is not configured locally. Install `pytesseract` and Tesseract OCR for on-screen text analysis."
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore

        text = pytesseract.image_to_string(Image.open(image_path))
        cleaned = redact_text(text.strip())
        if not cleaned:
            return "", "OCR ran, but no readable text was detected."
        return cleaned, ""
    except Exception as exc:
        return "", f"OCR failed: {exc}"


def inspect_screen(question: str = "") -> dict[str, Any]:
    screenshot = take_screenshot()
    if not screenshot.ok:
        return {"ok": False, "error": screenshot.error, "question": question}

    ocr_text, analysis_message = _ocr_text(screenshot.path)
    summary = "Screenshot captured for manual review."
    if ocr_text:
        excerpt = ocr_text[:500]
        summary = f"Screenshot captured. OCR extracted visible text for analysis.\n\n{excerpt}"
    elif analysis_message:
        summary = f"Screenshot captured. {analysis_message}"

    return {
        "ok": True,
        "screenshot": screenshot.path,
        "summary": summary,
        "question": question,
        "ocr_text": ocr_text,
        "analysis_message": analysis_message,
        "analysis_available": bool(ocr_text),
    }
