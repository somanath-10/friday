"""Permission-aware filesystem runtime."""

from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from friday.core.models import PlanStep
from friday.files.backup import create_backup
from friday.files.document_reader import read_document
from friday.files.document_writer import write_text_document
from friday.files.safe_paths import preview_bulk_operation, resolve_safe_path
from friday.safety.audit_log import append_audit_record


@dataclass(frozen=True)
class FileResult:
    ok: bool
    action: str
    message: str
    path: str = ""
    backup_path: str = ""
    permission_decision: str = "allow"
    dry_run: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FileRuntime:
    def _blocked_or_approval(self, action: str, safe_result) -> FileResult | None:
        decision = safe_result.decision
        if decision.decision == "allow":
            return None
        message = f"Approval required before file action: {safe_result.path}" if decision.decision == "ask" else decision.reason
        append_audit_record(command=str(safe_result.path), risk_level=int(decision.risk_level), decision=decision.decision, tool=f"files.{action}", result=message)
        return FileResult(False, action, message, path=str(safe_result.path), permission_decision=decision.decision)

    def read_file(self, path: str) -> FileResult:
        safe = resolve_safe_path(path, tool_name="read_file", operation="read")
        blocked = self._blocked_or_approval("read", safe)
        if blocked:
            return blocked
        if not safe.path.exists():
            return FileResult(False, "read", f"File not found: {safe.path}", path=str(safe.path))
        return FileResult(True, "read", read_document(safe.path), path=str(safe.path))

    def write_new_file(self, path: str, content: str, *, dry_run: bool = False) -> FileResult:
        safe = resolve_safe_path(path, tool_name="create_document", operation="write_new")
        blocked = self._blocked_or_approval("write_new", safe)
        if blocked:
            return blocked
        if safe.path.exists():
            return FileResult(False, "write_new", f"Refusing to overwrite existing file: {safe.path}", path=str(safe.path), permission_decision="block")
        if dry_run:
            return FileResult(True, "write_new", f"Dry run: would write {safe.path}", path=str(safe.path), dry_run=True)
        write_text_document(safe.path, content)
        append_audit_record(command=str(safe.path), risk_level=1, decision="allow", tool="files.write_new", result="created")
        return FileResult(True, "write_new", f"Wrote file: {safe.path}", path=str(safe.path))

    def append_file(self, path: str, content: str, *, dry_run: bool = False) -> FileResult:
        safe = resolve_safe_path(path, tool_name="create_document", operation="append")
        blocked = self._blocked_or_approval("append", safe)
        if blocked:
            return blocked
        if dry_run:
            return FileResult(True, "append", f"Dry run: would append to {safe.path}", path=str(safe.path), dry_run=True)
        safe.path.parent.mkdir(parents=True, exist_ok=True)
        with safe.path.open("a", encoding="utf-8") as handle:
            handle.write(content)
        return FileResult(True, "append", f"Appended to file: {safe.path}", path=str(safe.path))

    def overwrite_file(self, path: str, content: str, *, approved: bool = False, dry_run: bool = False) -> FileResult:
        safe = resolve_safe_path(path, tool_name="write_file", operation="overwrite")
        if safe.decision.decision != "allow" and not approved:
            return self._blocked_or_approval("overwrite", safe) or FileResult(False, "overwrite", "Approval required.", permission_decision=safe.decision.decision)
        backup_path = ""
        if safe.path.exists() and not dry_run:
            backup_path = str(create_backup(safe.path))
        if dry_run:
            return FileResult(True, "overwrite", f"Dry run: would overwrite {safe.path}", path=str(safe.path), dry_run=True)
        write_text_document(safe.path, content)
        return FileResult(True, "overwrite", f"Overwrote file: {safe.path}", path=str(safe.path), backup_path=backup_path)

    def copy_path(self, source_path: str, destination_path: str, *, overwrite: bool = False, dry_run: bool = False) -> FileResult:
        source = resolve_safe_path(source_path, tool_name="read_file", operation="read")
        destination = resolve_safe_path(destination_path, tool_name="copy_path", operation="copy")
        blocked = self._blocked_or_approval("copy", source) or self._blocked_or_approval("copy", destination)
        if blocked:
            return blocked
        if not source.path.exists():
            return FileResult(False, "copy", f"Source path does not exist: {source.path}")
        if destination.path.exists() and not overwrite:
            return FileResult(False, "copy", f"Destination exists: {destination.path}", permission_decision="block")
        if dry_run:
            return FileResult(True, "copy", f"Dry run: would copy {source.path} to {destination.path}", dry_run=True)
        destination.path.parent.mkdir(parents=True, exist_ok=True)
        if source.path.is_dir():
            if destination.path.exists():
                shutil.rmtree(destination.path)
            shutil.copytree(source.path, destination.path)
        else:
            shutil.copy2(source.path, destination.path)
        return FileResult(True, "copy", f"Copied to {destination.path}", path=str(destination.path))

    def move_path(self, source_path: str, destination_path: str, *, overwrite: bool = False, dry_run: bool = False) -> FileResult:
        source = resolve_safe_path(source_path, tool_name="move_path", operation="move")
        destination = resolve_safe_path(destination_path, tool_name="move_path", operation="move")
        blocked = self._blocked_or_approval("move", source) or self._blocked_or_approval("move", destination)
        if blocked:
            return blocked
        if not source.path.exists():
            return FileResult(False, "move", f"Source path does not exist: {source.path}")
        if destination.path.exists() and not overwrite:
            return FileResult(False, "move", f"Destination exists: {destination.path}", permission_decision="block")
        if dry_run:
            return FileResult(True, "move", f"Dry run: would move {source.path} to {destination.path}", dry_run=True)
        destination.path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source.path), str(destination.path))
        return FileResult(True, "move", f"Moved to {destination.path}", path=str(destination.path))

    def delete_path(self, path: str, *, approved: bool = False, dry_run: bool = False) -> FileResult:
        safe = resolve_safe_path(path, tool_name="delete_path", operation="delete")
        if safe.decision.decision != "allow" and not approved:
            return self._blocked_or_approval("delete", safe) or FileResult(False, "delete", "Approval required.", permission_decision=safe.decision.decision)
        if not safe.path.exists():
            return FileResult(False, "delete", f"Path not found: {safe.path}", path=str(safe.path))
        if dry_run:
            return FileResult(True, "delete", f"Dry run: would delete {safe.path}", path=str(safe.path), dry_run=True)
        backup_path = str(create_backup(safe.path))
        if safe.path.is_dir():
            shutil.rmtree(safe.path)
        else:
            safe.path.unlink()
        return FileResult(True, "delete", f"Deleted {safe.path}", path=str(safe.path), backup_path=backup_path)

    def list_tree(self, path: str = ".", *, limit: int = 200) -> FileResult:
        safe = resolve_safe_path(path, tool_name="read_file", operation="list")
        blocked = self._blocked_or_approval("list", safe)
        if blocked:
            return blocked
        if not safe.path.exists():
            return FileResult(False, "list", f"Path not found: {safe.path}")
        lines: list[str] = []
        for item in sorted(safe.path.rglob("*"))[:limit]:
            lines.append(str(item.relative_to(safe.path)))
        return FileResult(True, "list", "\n".join(lines), path=str(safe.path), metadata={"count": len(lines)})

    def preview_bulk(self, paths: list[str], *, operation: str) -> FileResult:
        preview = preview_bulk_operation(paths, operation=operation)
        return FileResult(not preview["blocked"], "preview_bulk", "Bulk operation preview generated.", metadata=preview)

    def execute(self, goal: str, plan_step: PlanStep, *, dry_run: bool = True) -> FileResult:
        params = plan_step.parameters
        action = plan_step.action_type
        if action in {"write_file", "files.write"}:
            return self.write_new_file(str(params.get("path") or params.get("file_path") or "generated.txt"), str(params.get("content", "")), dry_run=dry_run)
        if action in {"append_file", "files.append"}:
            return self.append_file(str(params.get("path") or params.get("file_path") or "generated.txt"), str(params.get("content", "")), dry_run=dry_run)
        if action in {"list_tree", "files.list", "preview_delete"}:
            return self.list_tree(str(params.get("path") or params.get("directory") or "."), limit=int(params.get("limit", 200)))
        if action in {"delete_path", "files.delete"}:
            return self.delete_path(str(params.get("path") or params.get("file_path") or ""), dry_run=dry_run)
        if action in {"copy_path", "files.copy"}:
            return self.copy_path(
                str(params.get("source_path", "")),
                str(params.get("destination_path", "")),
                overwrite=bool(params.get("overwrite", False)),
                dry_run=dry_run,
            )
        if action in {"move_path", "files.move", "rename_path"}:
            return self.move_path(
                str(params.get("source_path", "")),
                str(params.get("destination_path", "")),
                overwrite=bool(params.get("overwrite", False)),
                dry_run=dry_run,
            )
        return FileResult(False, action, f"No file runtime handler for action: {action}")
