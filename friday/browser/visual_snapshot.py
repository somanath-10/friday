"""Visual snapshot path helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from friday.path_utils import workspace_dir


def screenshot_path(prefix: str = "browser") -> Path:
    root = workspace_dir() / "screenshots"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return root / f"{prefix}_{stamp}.png"
