"""
Path helpers shared across FRIDAY modules.
"""

from __future__ import annotations

import os
from pathlib import Path


def _expand(raw_path: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(raw_path)))


def _first_existing_path(candidates: list[Path]) -> Path:
    for candidate in candidates:
        expanded = _expand(str(candidate))
        if expanded.exists():
            return expanded.resolve()
    return _expand(str(candidates[0])).resolve()


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


def home_dir() -> Path:
    return Path.home().resolve()


def desktop_dir() -> Path:
    candidates: list[Path] = []
    for env_name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            candidates.append(Path(env_value) / "Desktop")

    userprofile = os.environ.get("USERPROFILE", "").strip()
    if userprofile:
        candidates.append(Path(userprofile) / "OneDrive" / "Desktop")
        candidates.append(Path(userprofile) / "Desktop")

    candidates.append(Path.home() / "OneDrive" / "Desktop")
    candidates.append(Path.home() / "Desktop")
    return _first_existing_path(candidates)


def documents_dir() -> Path:
    candidates: list[Path] = []
    for env_name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            candidates.append(Path(env_value) / "Documents")

    userprofile = os.environ.get("USERPROFILE", "").strip()
    if userprofile:
        candidates.append(Path(userprofile) / "OneDrive" / "Documents")
        candidates.append(Path(userprofile) / "Documents")

    candidates.append(Path.home() / "OneDrive" / "Documents")
    candidates.append(Path.home() / "Documents")
    return _first_existing_path(candidates)


def downloads_dir() -> Path:
    candidates: list[Path] = []
    userprofile = os.environ.get("USERPROFILE", "").strip()
    if userprofile:
        candidates.append(Path(userprofile) / "Downloads")
        candidates.append(Path(userprofile) / "OneDrive" / "Downloads")

    for env_name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            candidates.append(Path(env_value) / "Downloads")

    candidates.append(Path.home() / "Downloads")
    return _first_existing_path(candidates)


def known_user_paths() -> dict[str, Path]:
    return {
        "home": home_dir(),
        "desktop": desktop_dir(),
        "documents": documents_dir(),
        "downloads": downloads_dir(),
        "workspace": workspace_dir(),
    }


def _resolve_special_path(path: str) -> Path | None:
    normalized = path.strip().replace("\\", "/").lstrip("./")
    if not normalized:
        return None

    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return None

    root = known_user_paths().get(parts[0].lower())
    if root is None:
        return None

    if len(parts) == 1:
        return root
    return (root / Path(*parts[1:])).resolve()


def resolve_user_path(path: str, *, base: Path | None = None) -> Path:
    candidate = _expand(path)
    if candidate.is_absolute():
        return candidate.resolve()
    special_path = _resolve_special_path(path)
    if special_path is not None:
        return special_path
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
