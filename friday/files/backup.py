"""Backup helpers for reversible file operations."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from friday.path_utils import workspace_dir


def backups_dir() -> Path:
    path = workspace_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def create_backup(path: str | Path) -> Path:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Cannot back up missing path: {source}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = backups_dir() / f"{source.name}.{stamp}.bak"
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        shutil.copy2(source, target)
    return target
