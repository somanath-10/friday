"""Safe git operation helpers."""

from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from friday.core.permissions import check_tool_permission


@dataclass(frozen=True)
class GitOperationResult:
    ok: bool
    message: str
    permission_decision: str = "allow"
    stdout: str = ""
    stderr: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def git_status(repo_path: str | Path) -> GitOperationResult:
    result = subprocess.run(["git", "status", "--short", "--branch"], cwd=str(repo_path), capture_output=True, text=True, timeout=20)
    return GitOperationResult(result.returncode == 0, "Git status complete." if result.returncode == 0 else "Git status failed.", stdout=result.stdout, stderr=result.stderr)


def git_diff(repo_path: str | Path, *, max_chars: int = 8000) -> GitOperationResult:
    result = subprocess.run(["git", "diff"], cwd=str(repo_path), capture_output=True, text=True, timeout=20)
    stdout = result.stdout[:max_chars] + ("\n... [truncated]" if len(result.stdout) > max_chars else "")
    return GitOperationResult(result.returncode == 0, "Git diff complete." if result.returncode == 0 else "Git diff failed.", stdout=stdout, stderr=result.stderr)


def require_git_commit_permission(repo_path: str | Path, message: str) -> GitOperationResult:
    decision = check_tool_permission("git_commit", {"repo_path": str(repo_path), "message": message}, subject=str(repo_path))
    return GitOperationResult(decision.decision == "allow", decision.reason, permission_decision=decision.decision)


def require_git_push_permission(repo_path: str | Path) -> GitOperationResult:
    decision = check_tool_permission("git_push", {"repo_path": str(repo_path)}, subject=str(repo_path))
    return GitOperationResult(decision.decision == "allow", decision.reason, permission_decision=decision.decision)
