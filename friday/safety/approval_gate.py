"""
Structured approval-request helpers for permission-gated FRIDAY actions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

from friday.core.risk import risk_level_label


@dataclass
class ApprovalRequest:
    """Structured approval payload for one risky action."""

    request_id: str
    created_at: str
    tool: str
    action: str
    category: str
    risk_level: int
    risk_label: str
    reason: str
    command: str = ""
    path: str = ""
    domain: str = ""
    session_category: str = ""
    options: list[str] = field(default_factory=lambda: ["one_time", "session"])
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SessionApproval:
    category: str
    value: str
    expires_at: datetime


class ApprovalGate:
    """Tracks pending approvals plus simple in-memory session approvals."""

    def __init__(self) -> None:
        self._pending: dict[str, ApprovalRequest] = {}
        self._approved_once: set[str] = set()
        self._session_approvals: list[SessionApproval] = []

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def create_request(
        self,
        *,
        tool: str,
        action: str,
        category: str,
        risk_level: int,
        reason: str,
        command: str = "",
        path: str = "",
        domain: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            request_id=f"apr_{uuid.uuid4().hex[:12]}",
            created_at=self._now().isoformat(),
            tool=tool,
            action=action,
            category=category,
            risk_level=risk_level,
            risk_label=risk_level_label(risk_level),
            reason=reason,
            command=command,
            path=path,
            domain=domain,
            session_category=category,
            metadata=metadata or {},
        )
        self._pending[request.request_id] = request
        return request

    def approve_once(self, request_id: str) -> bool:
        if request_id not in self._pending:
            return False
        self._approved_once.add(request_id)
        return True

    def consume_once_approval(self, request_id: str) -> bool:
        if request_id not in self._approved_once:
            return False
        self._approved_once.discard(request_id)
        self._pending.pop(request_id, None)
        return True

    def grant_session_approval(self, category: str, *, value: str = "*", minutes: int = 10) -> SessionApproval:
        approval = SessionApproval(
            category=category,
            value=value,
            expires_at=self._now() + timedelta(minutes=max(1, minutes)),
        )
        self._session_approvals.append(approval)
        return approval

    def has_session_approval(self, category: str, *, value: str = "*") -> bool:
        self.clear_expired()
        for approval in self._session_approvals:
            if approval.category != category:
                continue
            if approval.value in {"*", value}:
                return True
        return False

    def clear_expired(self) -> None:
        now = self._now()
        self._session_approvals = [
            approval for approval in self._session_approvals if approval.expires_at > now
        ]

    def pending_requests(self) -> list[ApprovalRequest]:
        return list(self._pending.values())


_APPROVAL_GATE = ApprovalGate()


def get_approval_gate() -> ApprovalGate:
    return _APPROVAL_GATE


def format_approval_request(request: ApprovalRequest) -> str:
    """Format a readable approval request for current tool responses."""
    lines = [
        f"[Approval Required] {request.action}",
        f"Request ID: {request.request_id}",
        f"Risk: {request.risk_level} ({request.risk_label})",
        f"Reason: {request.reason}",
    ]

    if request.command:
        lines.append(f"Command: {request.command}")
    if request.path:
        lines.append(f"Path: {request.path}")
    if request.domain:
        lines.append(f"Domain: {request.domain}")

    lines.append("Approval options: one_time, session")
    return "\n".join(lines)

