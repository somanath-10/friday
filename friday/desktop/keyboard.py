"""
Keyboard helpers with graceful optional dependency handling.
"""

from __future__ import annotations


def _load_pyautogui():
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.02
    return pyautogui


def type_text(text: str, *, interval_ms: int = 20) -> str:
    pyautogui = _load_pyautogui()
    pyautogui.write(text, interval=max(interval_ms, 0) / 1000)
    return f"Typed {len(text)} characters."


def send_hotkey(*keys: str) -> str:
    cleaned = [key for key in keys if key]
    if not cleaned:
        return "No hotkeys provided."
    pyautogui = _load_pyautogui()
    pyautogui.hotkey(*cleaned)
    return f"Sent hotkey: {'+'.join(cleaned)}"
