"""
Screen-aware operator tools for desktop automation.

These tools bridge the gap between voice/text intent and GUI interaction by
capturing the current desktop, optionally analyzing it with a vision-capable
model, and returning action-oriented guidance or target coordinates.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from friday.path_utils import safe_filename, workspace_path
from friday.tools.apps import OS, _load_json_records, _powershell, _ps_quote

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"


def _workspace_image_path(prefix: str, filename: str) -> Path:
    default_name = f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}.png"
    chosen = safe_filename(filename, default_name) if filename.strip() else default_name
    return workspace_path(chosen)


def _capture_desktop_screenshot(save_path: Path) -> None:
    save_path.parent.mkdir(parents=True, exist_ok=True)

    if OS == "Darwin":
        result = subprocess.run(
            ["screencapture", "-x", str(save_path)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "macOS screenshot capture failed")
        return

    if OS == "Windows":
        ps_script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "Add-Type -AssemblyName System.Drawing; "
            "$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
            "$image = New-Object System.Drawing.Bitmap $bounds.Width,$bounds.Height; "
            "$graphics = [System.Drawing.Graphics]::FromImage($image); "
            "$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size); "
            f"$image.Save({_ps_quote(str(save_path))}); "
            "$graphics.Dispose(); "
            "$image.Dispose();"
        )
        result = _powershell(ps_script, timeout=20)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Windows screenshot capture failed")
        return

    for command in (
        ["scrot", str(save_path)],
        ["gnome-screenshot", "-f", str(save_path)],
        ["import", "-window", "root", str(save_path)],
    ):
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return
    raise RuntimeError("Linux screenshot capture failed. Install scrot or gnome-screenshot.")


def _image_dimensions(image_path: Path) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(image_path) as image:
            return image.size
    except Exception:
        return (0, 0)


def _open_window_snapshot(limit: int = 10) -> list[str]:
    if limit <= 0:
        return []

    try:
        if OS == "Windows":
            ps_script = f"""
$limit = {int(limit)}
Get-Process |
  Where-Object {{ $_.MainWindowTitle -and $_.MainWindowTitle.Trim() -ne '' }} |
  Sort-Object ProcessName, Id |
  Select-Object -First $limit Id, ProcessName, MainWindowTitle |
  ConvertTo-Json -Compress
"""
            result = _powershell(ps_script, timeout=15)
            if result.returncode != 0:
                return []
            rows = _load_json_records(result.stdout)
            return [
                f"{row.get('ProcessName') or '?'} [{row.get('Id') or '?'}] :: {row.get('MainWindowTitle') or '(untitled)'}"
                for row in rows
            ]

        if OS == "Darwin":
            script = 'tell application "System Events" to get name of every process where background only is false'
            result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return []
            return [item.strip() for item in result.stdout.split(",") if item.strip()][:limit]

        result = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return []
        windows = [line.split(None, 3)[-1] for line in result.stdout.splitlines() if line.strip()]
        return windows[:limit]
    except Exception:
        return []


def _vision_model_name() -> str:
    return (
        os.getenv("OPENAI_VISION_MODEL", "").strip()
        or os.getenv("OPENAI_LLM_MODEL", "").strip()
        or "gpt-4o"
    )


def _image_data_url(image_path: Path) -> str:
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if "\n" in stripped:
            stripped = stripped.split("\n", 1)[1]
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response")
    return json.loads(stripped[start : end + 1])


def _openai_vision_text(image_path: Path, prompt: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing.")

    payload = {
        "model": _vision_model_name(),
        "temperature": 0,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
                ],
            }
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    response = httpx.post(OPENAI_CHAT_URL, headers=headers, json=payload, timeout=90.0)
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    if not isinstance(content, str):
        raise RuntimeError(f"Unexpected OpenAI response: {data}")
    return content.strip()


def register(mcp):
    @mcp.tool()
    def inspect_desktop_screen(question: str = "", filename: str = "", include_windows: bool = True) -> str:
        """
        Capture the current desktop and return a screen-aware summary for the next action.
        Use this before GUI-heavy tasks when FRIDAY needs to see what is currently on screen.
        If OpenAI vision is configured, the summary includes an action-oriented visual analysis.
        """
        try:
            screenshot_path = _workspace_image_path("desktop_inspect", filename)
            _capture_desktop_screenshot(screenshot_path)
            width, height = _image_dimensions(screenshot_path)
            windows = _open_window_snapshot(limit=10) if include_windows else []

            lines = [
                f"Desktop screenshot: {screenshot_path.resolve()}",
                f"Image size: {width}x{height}" if width and height else "Image size: unknown",
            ]
            if windows:
                lines.append("Visible windows:")
                lines.extend(f"  - {item}" for item in windows)

            prompt = (
                "You are assisting a desktop automation agent. Analyze this screenshot and describe "
                "what is visible in concise, actionable language. "
                "Call out any blocking dialogs, error popups, focused app, important buttons, inputs, "
                "and the most likely next step. "
                "If text is readable, include the important text exactly when practical. "
                f"Screenshot size: {width}x{height}. "
            )
            if windows:
                prompt += "Visible windows: " + " | ".join(windows) + ". "
            if question.strip():
                prompt += f"Current goal or question: {question.strip()}"
            else:
                prompt += "Current goal or question: General desktop inspection."

            try:
                analysis = _openai_vision_text(screenshot_path, prompt)
                lines.append("Vision analysis:")
                lines.append(analysis)
            except Exception as vision_error:
                lines.append(f"Vision analysis unavailable: {vision_error}")

            return "\n".join(lines)
        except Exception as e:
            return f"Error inspecting desktop screen: {str(e)}"

    @mcp.tool()
    def locate_screen_target(target: str, filename: str = "", include_windows: bool = True) -> str:
        """
        Capture the current desktop and estimate the screen coordinates of a target element.
        Use this before gui_click when the exact coordinates are unknown.
        Returns JSON-like details including x/y center coordinates, size, confidence, and reasoning.
        """
        try:
            if not target.strip():
                return "No target description provided."

            screenshot_path = _workspace_image_path("desktop_target", filename)
            _capture_desktop_screenshot(screenshot_path)
            width, height = _image_dimensions(screenshot_path)
            windows = _open_window_snapshot(limit=10) if include_windows else []

            prompt = (
                "You are a GUI grounding assistant for desktop automation. "
                "Find the best visible target matching the user's request and return JSON only. "
                "Use this schema exactly: "
                '{"found": true, "x": 0, "y": 0, "width": 0, "height": 0, '
                '"confidence": 0.0, "label": "", "reason": ""}. '
                "Coordinates must be pixel coordinates in the screenshot. "
                "x and y must be the center point of the target. "
                "If the target is not visible, return found=false and explain why. "
                f"Screenshot size: {width}x{height}. "
            )
            if windows:
                prompt += "Visible windows: " + " | ".join(windows) + ". "
            prompt += f"Target request: {target.strip()}"

            content = _openai_vision_text(screenshot_path, prompt)
            data = _extract_json(content)
            data["screenshot_path"] = str(screenshot_path.resolve())
            if width and height:
                data["image_width"] = width
                data["image_height"] = height
            return json.dumps(data, indent=2)
        except Exception as e:
            return f"Error locating screen target: {str(e)}"
