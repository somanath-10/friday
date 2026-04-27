"""
Mouse helpers for coordinate-based fallback control.
"""

from __future__ import annotations


def _load_pyautogui():
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.02
    return pyautogui


def click(x: int, y: int, *, button: str = "left") -> str:
    pyautogui = _load_pyautogui()
    pyautogui.click(x=x, y=y, button=button)
    return f"Clicked {button} at ({x}, {y})."


def scroll(amount: int) -> str:
    pyautogui = _load_pyautogui()
    pyautogui.scroll(amount)
    return f"Scrolled by {amount}."


def drag(start_x: int, start_y: int, end_x: int, end_y: int, *, duration: float = 0.3) -> str:
    pyautogui = _load_pyautogui()
    pyautogui.moveTo(start_x, start_y)
    pyautogui.dragTo(end_x, end_y, duration=max(duration, 0), button="left")
    return f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})."
