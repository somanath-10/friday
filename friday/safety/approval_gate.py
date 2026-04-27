"""
Structured approval requests for risky local actions.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from friday.core.permissions import PermissionDecision


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    action_summary: str
    risk_level: int
    risk_label: str
    risk_explanation: str
    decision_reason: str
    tool: str
    command: str = ""
    path: str = ""
    domain: str = ""
    approval_modes: tuple[str, ...] = ("one_time", "session_limited")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["approval_modes"] = list(self.approval_modes)
        return data


_APPROVED_ONCE: set[str] = set()
_SESSION_APPROVALS: dict[str, float] = {}


def create_approval_request(
    decision: PermissionDecision,
    *,
    tool: str,
    command: str = "",
    path: str = "",
    domain: str = "",
) -> ApprovalRequest:
    subject = command or path or domain or decision.subject
    summary = f"{tool}: {subject}" if subject else tool
    return ApprovalRequest(
        approval_id=f"apr_{uuid.uuid4().hex[:16]}",
        action_summary=summary,
        risk_level=int(decision.risk_level),
        risk_label=decision.risk_label,
        risk_explanation=decision.reason,
        decision_reason=decision.reason,
        tool=tool,
        command=command,
        path=path,
        domain=domain,
    )


def format_approval_required(request: ApprovalRequest) -> str:
    payload = request.to_dict()
    return "Approval required before running this action:\n" + "\n".join(
        f"{key}: {value}" for key, value in payload.items() if value != "" and value != []
    )


def approve_once(approval_id: str) -> None:
    _APPROVED_ONCE.add(approval_id)


def approve_session(category: str, *, minutes: int = 10) -> None:
    _SESSION_APPROVALS[category] = time.time() + max(minutes, 1) * 60


def consume_one_time_approval(approval_id: str) -> bool:
    if approval_id in _APPROVED_ONCE:
        _APPROVED_ONCE.remove(approval_id)
        return True
    return False


def has_session_approval(category: str) -> bool:
    expires_at = _SESSION_APPROVALS.get(category, 0)
    if expires_at > time.time():
        return True
    _SESSION_APPROVALS.pop(category, None)
    return False
