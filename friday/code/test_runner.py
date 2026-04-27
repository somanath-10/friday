"""Project test execution helpers."""

from __future__ import annotations

from pathlib import Path

from friday.shell.runtime import ShellResult, ShellRuntime


def run_project_tests(repo_path: str | Path, command: str, *, dry_run: bool = False) -> ShellResult:
    if not command:
        return ShellResult(False, "", "No test command was detected.")
    return ShellRuntime(timeout_seconds=120).execute_command(command, cwd=Path(repo_path), dry_run=dry_run)
