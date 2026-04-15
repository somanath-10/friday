"""
Path helpers shared across FRIDAY modules.
"""

from __future__ import annotations

import os
from pathlib import Path


def _expand(raw_path: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(raw_path)))


def workspace_dir() -> Path:
    raw = os.environ.get("FRIDAY_WORKSPACE_DIR", "workspace")
    path = _expand(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def memory_dir() -> Path:
    raw = os.environ.get("FRIDAY_MEMORY_DIR", str(Path.home() / ".friday_memory"))
    path = _expand(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_user_path(path: str, *, base: Path | None = None) -> Path:
    candidate = _expand(path)
    if candidate.is_absolute():
        return candidate.resolve()
    anchor = base or workspace_dir()
    return (anchor / candidate).resolve()


def ensure_within(base: Path, target: Path) -> Path:
    base = base.resolve()
    target = target.resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"Path escapes the allowed workspace: {target}") from exc
    return target


def workspace_path(path: str = "") -> Path:
    root = workspace_dir()
    if not path:
        return root
    return ensure_within(root, resolve_user_path(path, base=root))


def safe_filename(name: str, default: str) -> str:
    cleaned = Path(name).name.strip()
    return cleaned or default
