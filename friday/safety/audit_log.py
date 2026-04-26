"""
Audit-log helpers for permission-gated FRIDAY actions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

from friday.path_utils import workspace_dir


@dataclass
class AuditRecord:
    timestamp: str
    tool: str
    action: str
    decision: str
    risk_level: int
    result: str
    command: str = ""
    path: str = ""
    domain: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def audit_log_path() -> Path:
    log_dir = workspace_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "audit.jsonl"


def append_audit_record(
    *,
    tool: str,
    action: str,
    decision: str,
    risk_level: int,
    result: str,
    command: str = "",
    path: str = "",
    domain: str = "",
    metadata: dict[str, Any] | None = None,
) -> Path:
    record = AuditRecord(
        timestamp=datetime.now(timezone.utc).isoformat(),
        tool=tool,
        action=action,
        decision=decision,
        risk_level=risk_level,
        result=result,
        command=command,
        path=path,
        domain=domain,
        metadata=metadata or {},
    )
    output_path = audit_log_path()
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(record), ensure_ascii=True) + "\n")
    return output_path

