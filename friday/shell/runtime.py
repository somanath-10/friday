"""Permission-aware shell runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from friday.core.models import PlanStep
from friday.safety.audit_log import append_audit_record
from friday.safety.approval_gate import create_approval_request
from friday.shell.command_policy import validate_command
from friday.shell.terminal import run_terminal_command


@dataclass(frozen=True)
class ShellResult:
    ok: bool
    command: str
    message: str
    returncode: int | None = None
    stdout: str = ""
    stderr: str = ""
    permission_decision: str = "allow"
    dry_run: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ShellRuntime:
    def __init__(self, *, timeout_seconds: int = 60, max_output_chars: int = 8000) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars

    def execute_command(self, command: str, *, cwd: str | Path | None = None, dry_run: bool = False) -> ShellResult:
        policy = validate_command(command, cwd=cwd)
        if policy.decision == "block":
            append_audit_record(command=command, risk_level=policy.risk_level, decision="block", tool="shell.execute", result=policy.reason)
            return ShellResult(False, command, policy.reason, permission_decision="block", metadata={"policy": policy.to_dict()})
        if policy.decision == "ask":
            approval = create_approval_request(policy.permission, tool="shell.execute", command=command)
            message = f"Approval required before shell command: {approval.action_summary}"
            append_audit_record(command=command, risk_level=policy.risk_level, decision="ask", tool="shell.execute", result=message)
            return ShellResult(False, command, message, permission_decision="ask", metadata={"approval": approval.to_dict(), "policy": policy.to_dict()})
        if dry_run:
            return ShellResult(True, command, f"Dry run: would execute `{command}` in {policy.cwd}", dry_run=True, metadata={"policy": policy.to_dict()})

        result = run_terminal_command(command, cwd=policy.cwd, timeout_seconds=self.timeout_seconds, max_output_chars=self.max_output_chars)
        message = "Command timed out." if result.timed_out else f"Command exited with code {result.returncode}."
        append_audit_record(command=command, risk_level=policy.risk_level, decision="allow", tool="shell.execute", result=f"{message}\n{result.stdout}\n{result.stderr}")
        return ShellResult(result.ok, command, message, returncode=result.returncode, stdout=result.stdout, stderr=result.stderr, metadata={"policy": policy.to_dict()})

    def execute(self, goal: str, plan_step: PlanStep, *, dry_run: bool = True) -> ShellResult:
        return self.execute_command(str(plan_step.parameters.get("command", "")), dry_run=dry_run)
