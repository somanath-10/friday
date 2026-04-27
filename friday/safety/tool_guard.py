"""
Small helpers for applying permission decisions inside existing MCP tools.
"""

from __future__ import annotations

from typing import Any

from friday.core.permissions import PermissionDecision, check_shell_permission, check_tool_permission
from friday.safety.approval_gate import create_approval_request, format_approval_required
from friday.safety.audit_log import append_audit_record


def guard_tool_call(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    subject: str = "",
) -> tuple[PermissionDecision, str]:
    decision = check_tool_permission(tool_name, arguments or {}, subject=subject)
    if decision.decision == "allow":
        return decision, ""

    if decision.decision == "block":
        message = f"Blocked by FRIDAY safety policy: {decision.reason}"
    else:
        request = create_approval_request(
            decision,
            tool=tool_name,
            command=str((arguments or {}).get("command", "")),
            path=subject,
        )
        message = format_approval_required(request)

    append_audit_record(
        command=subject or str(arguments or {}),
        risk_level=int(decision.risk_level),
        decision=decision.decision,
        tool=tool_name,
        result=message,
    )
    return decision, message


def guard_shell_command(tool_name: str, command: str) -> tuple[PermissionDecision, str]:
    decision = check_shell_permission(command)
    if decision.decision == "allow":
        return decision, ""

    if decision.decision == "block":
        message = f"Blocked by FRIDAY safety policy: {decision.reason}"
    else:
        request = create_approval_request(decision, tool=tool_name, command=command)
        message = format_approval_required(request)

    append_audit_record(
        command=command,
        risk_level=int(decision.risk_level),
        decision=decision.decision,
        tool=tool_name,
        result=message,
    )
    return decision, message


def audit_allowed_tool(
    tool_name: str,
    *,
    command: str,
    risk_level: int,
    decision: str,
    result: str,
) -> None:
    append_audit_record(
        command=command,
        risk_level=risk_level,
        decision=decision,
        tool=tool_name,
        result=result[:1000],
    )
