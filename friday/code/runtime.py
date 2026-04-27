"""Project assistant runtime for inspect-test-fix workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from friday.code.git_ops import git_diff, git_status, require_git_commit_permission, require_git_push_permission
from friday.code.patcher import replace_file_text
from friday.code.repo_inspector import inspect_repo
from friday.code.sandbox import sandbox_summary
from friday.code.test_runner import run_project_tests
from friday.core.models import PlanStep


@dataclass(frozen=True)
class CodeResult:
    ok: bool
    action: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CodeRuntime:
    def __init__(self, repo_path: str | Path = ".") -> None:
        self.repo_path = Path(repo_path).expanduser().resolve()

    def inspect(self) -> CodeResult:
        info = inspect_repo(self.repo_path)
        data = info.to_dict()
        data["sandbox"] = sandbox_summary()
        return CodeResult(True, "inspect", f"Detected {info.project_type} project.", metadata=data)

    def run_tests(self, *, dry_run: bool = False) -> CodeResult:
        info = inspect_repo(self.repo_path)
        result = run_project_tests(self.repo_path, info.test_command, dry_run=dry_run)
        return CodeResult(result.ok, "run_tests", result.message, metadata=result.to_dict(), dry_run=dry_run)

    def propose_fix_plan(self, error_text: str) -> CodeResult:
        return CodeResult(
            True,
            "propose_fix_plan",
            "Created a conservative fix plan from the captured error.",
            metadata={
                "steps": [
                    "Read the failing traceback or assertion.",
                    "Locate the smallest affected module and test.",
                    "Patch only the relevant lines.",
                    "Rerun the detected test command.",
                    "Summarize the diff and remaining risk.",
                ],
                "error_preview": error_text[:1000],
            },
        )

    def patch_text(self, path: str | Path, old: str, new: str, *, dry_run: bool = True) -> CodeResult:
        result = replace_file_text(Path(path), old, new, dry_run=dry_run)
        return CodeResult(result.ok, "patch_text", result.message, metadata=result.to_dict(), dry_run=dry_run)

    def git_status(self) -> CodeResult:
        result = git_status(self.repo_path)
        return CodeResult(result.ok, "git_status", result.message, metadata=result.to_dict())

    def git_diff(self) -> CodeResult:
        result = git_diff(self.repo_path)
        return CodeResult(result.ok, "git_diff", result.message, metadata=result.to_dict())

    def require_commit_approval(self, message: str) -> CodeResult:
        result = require_git_commit_permission(self.repo_path, message)
        return CodeResult(result.ok, "git_commit", result.message, metadata=result.to_dict())

    def require_push_approval(self) -> CodeResult:
        result = require_git_push_permission(self.repo_path)
        return CodeResult(result.ok, "git_push", result.message, metadata=result.to_dict())

    def execute(self, goal: str, plan_step: PlanStep, *, dry_run: bool = True) -> CodeResult:
        action = plan_step.action_type
        if action == "shell_command" and "test" in str(plan_step.parameters.get("command", "")).lower():
            return self.run_tests(dry_run=dry_run)
        if action == "git_status":
            return self.git_status()
        if action == "git_diff":
            return self.git_diff()
        return CodeResult(False, action, f"No code runtime handler for action: {action}")
