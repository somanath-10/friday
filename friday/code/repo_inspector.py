"""Local repository inspection helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProjectInfo:
    root: Path
    project_type: str
    test_command: str
    important_files: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["root"] = str(self.root)
        return data


def detect_project_type(repo_path: str | Path) -> str:
    root = Path(repo_path)
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        return "python"
    if (root / "package.json").exists():
        return "node"
    if (root / "Cargo.toml").exists():
        return "rust"
    return "unknown"


def detect_test_command(repo_path: str | Path) -> str:
    root = Path(repo_path)
    project_type = detect_project_type(root)
    if project_type == "python":
        return "uv run pytest tests -q" if (root / "uv.lock").exists() else "pytest tests -q"
    if project_type == "node":
        return "npm test"
    if project_type == "rust":
        return "cargo test"
    return ""


def inspect_repo(repo_path: str | Path) -> ProjectInfo:
    root = Path(repo_path).expanduser().resolve()
    candidates = ["pyproject.toml", "requirements.txt", "package.json", "Cargo.toml", "README.md", ".gitignore"]
    important = [name for name in candidates if (root / name).exists()]
    return ProjectInfo(root=root, project_type=detect_project_type(root), test_command=detect_test_command(root), important_files=important)
