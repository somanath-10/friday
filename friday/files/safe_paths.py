"""Safe local path resolution for FRIDAY file operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from friday.core.permissions import PermissionDecision, check_tool_permission
from friday.path_utils import resolve_user_path
from friday.safety.secrets_filter import is_protected_secret_path


RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass(frozen=True)
class SafePathResult:
    path: Path
    decision: PermissionDecision
    ok: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path)
        data["decision"] = self.decision.to_dict()
        return data


def contains_path_traversal(raw_path: str) -> bool:
    parts = Path(raw_path.replace("\\", "/")).parts
    return ".." in parts


def contains_reserved_windows_name(raw_path: str) -> bool:
    parts = Path(raw_path.replace("\\", "/")).parts
    for part in parts:
        if not part or part in {"/", "\\"}:
            continue
        stem = part.split(".", 1)[0].rstrip(" .").upper()
        if stem in RESERVED_WINDOWS_NAMES:
            return True
    return False


def resolve_safe_path(path: str, *, tool_name: str = "read_file", operation: str = "read") -> SafePathResult:
    if contains_path_traversal(path) and not Path(path).expanduser().is_absolute():
        dummy = check_tool_permission(tool_name, {"path": path}, subject=path)
        blocked = PermissionDecision("block", "Relative path traversal is not allowed.", dummy.risk_level, dummy.risk_label, dummy.category, dummy.action, path)
        return SafePathResult(Path(path), blocked, False, blocked.reason)

    if contains_reserved_windows_name(path):
        dummy = check_tool_permission(tool_name, {"path": path}, subject=path)
        blocked = PermissionDecision("block", "Reserved Windows device filenames are not allowed.", dummy.risk_level, dummy.risk_label, dummy.category, dummy.action, path)
        return SafePathResult(Path(path), blocked, False, blocked.reason)

    target = resolve_user_path(path)
    if is_protected_secret_path(target):
        dummy = check_tool_permission(tool_name, {"path": str(target)}, subject=str(target))
        blocked = PermissionDecision("block", "Protected secret paths require explicit advanced approval.", dummy.risk_level, dummy.risk_label, dummy.category, dummy.action, str(target))
        return SafePathResult(target, blocked, False, blocked.reason)

    decision = check_tool_permission(tool_name, {"path": str(target), "operation": operation}, subject=str(target))
    return SafePathResult(target, decision, decision.decision == "allow", decision.reason)


def preview_bulk_operation(paths: list[str], *, operation: str) -> dict[str, Any]:
    resolved = [resolve_safe_path(path, tool_name=f"{operation}_path", operation=operation) for path in paths]
    return {
        "operation": operation,
        "total": len(paths),
        "allowed": [str(item.path) for item in resolved if item.decision.decision == "allow"],
        "approval_required": [str(item.path) for item in resolved if item.decision.decision == "ask"],
        "blocked": [{"path": str(item.path), "reason": item.reason or item.decision.reason} for item in resolved if item.decision.decision == "block"],
    }
