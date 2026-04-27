"""Persistent workflow store."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from friday.path_utils import workspace_dir
from friday.safety.secrets_filter import redact_value


def workflows_dir() -> Path:
    path = workspace_dir() / "workflows"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class WorkflowRecord:
    workflow_id: str
    goal: str
    intent: str
    risk_level: int
    status: str = "created"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    steps: list[dict[str, Any]] = field(default_factory=list)
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    verification_results: list[dict[str, Any]] = field(default_factory=list)
    recovery_notes: list[str] = field(default_factory=list)
    final_outcome: str = ""

    def to_dict(self) -> dict[str, Any]:
        return redact_value(asdict(self))


class WorkflowStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or workflows_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, workflow_id: str) -> Path:
        return self.root / f"{Path(workflow_id).name}.json"

    def create(self, goal: str, *, intent: str = "general", risk_level: int = 0, steps: list[dict[str, Any]] | None = None) -> WorkflowRecord:
        record = WorkflowRecord(
            workflow_id=f"wf_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
            goal=goal,
            intent=intent,
            risk_level=risk_level,
            steps=steps or [],
        )
        self.save(record)
        return record

    def save(self, record: WorkflowRecord) -> Path:
        record.updated_at = datetime.now(timezone.utc).isoformat()
        path = self.path_for(record.workflow_id)
        path.write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")
        (self.root / "latest_workflow.txt").write_text(record.workflow_id, encoding="utf-8")
        return path

    def load(self, workflow_id: str = "latest") -> WorkflowRecord:
        if workflow_id == "latest":
            workflow_id = (self.root / "latest_workflow.txt").read_text(encoding="utf-8").strip()
        payload = json.loads(self.path_for(workflow_id).read_text(encoding="utf-8"))
        return WorkflowRecord(**payload)

    def list(self) -> list[WorkflowRecord]:
        records: list[WorkflowRecord] = []
        for path in sorted(self.root.glob("wf_*.json")):
            try:
                records.append(WorkflowRecord(**json.loads(path.read_text(encoding="utf-8"))))
            except Exception:
                continue
        return records

    def search(self, query: str) -> list[WorkflowRecord]:
        needle = query.lower()
        return [record for record in self.list() if needle in record.goal.lower() or needle in record.intent.lower()]
