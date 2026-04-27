"""
Append-only JSONL audit logging for local actions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from friday.path_utils import workspace_dir
from friday.safety.secrets_filter import redact_value


def audit_log_path() -> Path:
    log_dir = workspace_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "audit.jsonl"


def append_audit_record(
    *,
    command: str,
    risk_level: int,
    decision: str,
    tool: str,
    result: str = "",
    intent: str = "",
    plan: Any = None,
    verification: Any = None,
    errors: Any = None,
    recovery_attempts: Any = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    record: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "command": redact_value(command),
        "intent": redact_value(intent),
        "plan": redact_value(plan),
        "risk_level": risk_level,
        "tool": redact_value(tool),
        "permission_decision": decision,
        "result": redact_value(result),
        "verification": redact_value(verification),
        "errors": redact_value(errors),
        "recovery_attempts": redact_value(recovery_attempts),
    }
    if extra:
        record.update(redact_value(extra))

    path = audit_log_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return path


def read_audit_records(limit: int = 50) -> list[dict[str, Any]]:
    path = audit_log_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    records: list[dict[str, Any]] = []
    for line in lines[-max(limit, 1):]:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records
