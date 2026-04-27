"""
Structured approval requests for risky local actions.
"""

from __future__ import annotations

import time
import uuid
import json
import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from friday.core.permissions import PermissionDecision
from friday.path_utils import workspace_dir
from friday.safety.secrets_filter import redact_value


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    approval_key: str
    action_summary: str
    risk_level: int
    risk_label: str
    risk_explanation: str
    decision_reason: str
    tool: str
    command: str = ""
    path: str = ""
    domain: str = ""
    category: str = ""
    subject: str = ""
    status: str = "pending"
    created_at: str = ""
    approval_modes: tuple[str, ...] = ("one_time", "session_limited")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["approval_modes"] = list(self.approval_modes)
        return data


_APPROVED_ONCE: set[str] = set()
_APPROVED_KEYS: dict[str, int] = {}
_SESSION_APPROVALS: dict[str, float] = {}


def approval_key_for(
    *,
    action: str,
    category: str,
    subject: str = "",
    risk_level: int = 0,
) -> str:
    payload = {
        "action": action.strip().lower(),
        "category": category.strip().lower(),
        "subject": subject.strip(),
        "risk_level": int(risk_level),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"apk_{digest[:24]}"


def _approval_store_path() -> Path:
    path = workspace_dir() / "logs" / "approvals.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_store() -> dict[str, Any]:
    path = _approval_store_path()
    if not path.exists():
        return {"approvals": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {"approvals": {}}
    if not isinstance(payload, dict):
        payload = {"approvals": {}}
    payload.setdefault("approvals", {})
    return payload


def _write_store(payload: dict[str, Any]) -> None:
    _approval_store_path().write_text(json.dumps(redact_value(payload), indent=2, ensure_ascii=False), encoding="utf-8")


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
    approval_key = approval_key_for(
        action=decision.action,
        category=decision.category,
        subject=decision.subject or subject,
        risk_level=int(decision.risk_level),
    )
    return ApprovalRequest(
        approval_id=f"apr_{uuid.uuid4().hex[:16]}",
        approval_key=approval_key,
        action_summary=summary,
        risk_level=int(decision.risk_level),
        risk_label=decision.risk_label,
        risk_explanation=decision.reason,
        decision_reason=decision.reason,
        tool=tool,
        command=command,
        path=path,
        domain=domain,
        category=decision.category,
        subject=decision.subject or subject,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def format_approval_required(request: ApprovalRequest) -> str:
    payload = request.to_dict()
    return "Approval required before running this action:\n" + "\n".join(
        f"{key}: {value}" for key, value in payload.items() if value != "" and value != []
    )


def approve_once(approval_id: str) -> None:
    _APPROVED_ONCE.add(approval_id)


def approve_key_once(approval_key: str, *, uses: int = 2) -> None:
    _APPROVED_KEYS[approval_key] = max(1, uses)


def approve_session(category: str, *, minutes: int = 10) -> None:
    _SESSION_APPROVALS[category] = time.time() + max(minutes, 1) * 60


def consume_one_time_approval(approval_id: str) -> bool:
    if approval_id in _APPROVED_ONCE:
        _APPROVED_ONCE.remove(approval_id)
        return True
    return False


def consume_approval_key(approval_key: str) -> bool:
    remaining = _APPROVED_KEYS.get(approval_key, 0)
    if remaining <= 0:
        _APPROVED_KEYS.pop(approval_key, None)
        return False
    if remaining == 1:
        _APPROVED_KEYS.pop(approval_key, None)
    else:
        _APPROVED_KEYS[approval_key] = remaining - 1
    return True


def has_session_approval(category: str) -> bool:
    expires_at = _SESSION_APPROVALS.get(category, 0)
    if expires_at > time.time():
        return True
    _SESSION_APPROVALS.pop(category, None)
    return False


def register_pending_approval(request: ApprovalRequest, *, payload: dict[str, Any] | None = None) -> None:
    store = _read_store()
    approvals = store.setdefault("approvals", {})
    approvals[request.approval_id] = {
        "request": request.to_dict(),
        "payload": redact_value(payload or {}),
        "status": "pending",
        "created_at": request.created_at or datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_store(store)


def list_pending_approvals(include_resolved: bool = False) -> list[dict[str, Any]]:
    approvals = _read_store().get("approvals", {})
    records = []
    for approval_id, record in approvals.items():
        if not include_resolved and record.get("status") != "pending":
            continue
        records.append({"approval_id": approval_id, **record})
    records.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    return records


def get_pending_approval(approval_id: str) -> dict[str, Any] | None:
    record = _read_store().get("approvals", {}).get(approval_id)
    if not isinstance(record, dict):
        return None
    return {"approval_id": approval_id, **record}


def resolve_pending_approval(
    approval_id: str,
    decision: str,
    *,
    approval_mode: str = "one_time",
    session_minutes: int = 10,
) -> dict[str, Any] | None:
    store = _read_store()
    approvals = store.setdefault("approvals", {})
    record = approvals.get(approval_id)
    if not isinstance(record, dict):
        return None

    normalized = decision.strip().lower()
    if normalized not in {"approved", "denied"}:
        normalized = "denied"

    request = record.get("request", {})
    approval_key = str(request.get("approval_key", ""))
    category = str(request.get("category", ""))
    if normalized == "approved":
        if approval_mode == "session_limited" and category:
            approve_session(category, minutes=session_minutes)
        if approval_key:
            approve_key_once(approval_key, uses=3)
        approve_once(approval_id)

    record["status"] = normalized
    record["approval_mode"] = approval_mode
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    approvals[approval_id] = record
    _write_store(store)
    return {"approval_id": approval_id, **record}
