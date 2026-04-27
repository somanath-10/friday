"""Command policy for permission-aware shell execution."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from friday.core.permissions import PermissionDecision, check_shell_permission, load_permissions_config
from friday.core.risk import RiskLevel
from friday.path_utils import workspace_dir


@dataclass(frozen=True)
class CommandPolicyDecision:
    decision: str
    reason: str
    risk_level: int
    permission: PermissionDecision
    cwd: Path

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["cwd"] = str(self.cwd)
        data["permission"] = self.permission.to_dict()
        return data


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def sanitize_environment(env: dict[str, str] | None = None) -> dict[str, str]:
    source = env or os.environ
    blocked_markers = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
    safe: dict[str, str] = {}
    for key, value in source.items():
        if any(marker in key.upper() for marker in blocked_markers):
            continue
        safe[key] = value
    return safe


def validate_command(command: str, *, cwd: str | Path | None = None, config: dict[str, Any] | None = None) -> CommandPolicyDecision:
    permissions = config or load_permissions_config()
    decision = check_shell_permission(command, config=permissions)
    shell_config = permissions.get("shell", {})
    root = workspace_dir()
    resolved_cwd = Path(cwd).expanduser().resolve() if cwd else root

    if not _is_relative_to(resolved_cwd, root) and decision.risk_level > RiskLevel.READ_ONLY:
        return CommandPolicyDecision("ask", "Commands that can modify state must run inside the FRIDAY workspace unless approved.", int(decision.risk_level), decision, resolved_cwd)

    if decision.decision == "block":
        return CommandPolicyDecision("block", decision.reason, int(decision.risk_level), decision, resolved_cwd)
    if decision.decision == "ask":
        return CommandPolicyDecision("ask", decision.reason, int(decision.risk_level), decision, resolved_cwd)
    if not shell_config.get("allow_readonly_commands", True) and decision.risk_level == RiskLevel.READ_ONLY:
        return CommandPolicyDecision("block", "Read-only shell commands are disabled by config.", int(decision.risk_level), decision, resolved_cwd)
    return CommandPolicyDecision("allow", decision.reason, int(decision.risk_level), decision, resolved_cwd)
