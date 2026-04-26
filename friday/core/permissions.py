"""
Permission-policy helpers for FRIDAY tool execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import os

import yaml

from friday.core.risk import (
    RiskAssessment,
    browser_domain,
    classify_file_operation,
    classify_shell_command,
    classify_tool_call,
    risk_level_label,
)
from friday.path_utils import resolve_user_path, workspace_dir
from friday.safety.approval_gate import (
    ApprovalRequest,
    format_approval_request,
    get_approval_gate,
)
from friday.safety.audit_log import append_audit_record


@dataclass
class PermissionDecision:
    action: str
    category: str
    risk_level: int
    risk_label: str
    decision: str
    reason: str
    command: str = ""
    path: str = ""
    domain: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_permissions_config() -> dict[str, Any]:
    return {
        "mode": "local_permission_based",
        "desktop": {
            "enabled": True,
            "inspect_screen": True,
            "click": True,
            "type": True,
            "hotkeys": True,
            "ask_before_password_fields": True,
        },
        "apps": {
            "allow_open_any_app": True,
            "allow_close_apps": True,
            "ask_before_force_quit": True,
        },
        "filesystem": {
            "enabled": True,
            "allowed_roots": [
                "~/Desktop",
                "~/Documents",
                "~/Downloads",
                "~/Workspace",
                "./workspace",
            ],
            "protected_paths": [
                "~/.ssh",
                "~/.aws",
                "~/.config",
                ".env",
                "C:/Windows",
                "C:/Program Files",
                "/etc",
                "/System",
            ],
            "ask_before_delete": True,
            "ask_before_overwrite": True,
            "backup_before_edit": True,
            "preview_bulk_operations": True,
        },
        "browser": {
            "enabled": True,
            "use_isolated_profile": True,
            "allow_main_profile": False,
            "ask_before_submit_forms": True,
            "ask_before_payment": True,
            "ask_before_sending_messages": True,
            "ask_before_downloading_executables": True,
        },
        "shell": {
            "enabled": True,
            "allow_readonly_commands": True,
            "ask_before_install": True,
            "ask_before_git_push": True,
            "ask_before_admin": True,
            "block_dangerous_commands": True,
            "timeout_seconds": 60,
        },
        "voice": {
            "enabled": True,
            "push_to_talk": True,
            "wake_word": False,
            "save_transcripts": True,
        },
        "memory": {
            "enabled": True,
            "save_action_traces": True,
            "save_user_preferences": True,
        },
        "admin": {
            "allow_elevation": "ask",
            "remember_admin_permission_for_minutes": 10,
        },
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merged[key] = _deep_merge(base[key], value)
        else:
            merged[key] = value
    return merged


def permissions_config_path() -> Path:
    configured = os.environ.get("FRIDAY_PERMISSIONS_PATH", "").strip()
    if configured:
        path = Path(os.path.expandvars(os.path.expanduser(configured)))
        if not path.is_absolute():
            path = _repo_root() / path
        return path.resolve()
    return (_repo_root() / "config" / "permissions.yaml").resolve()


def _expand_policy_path(raw_path: str) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(raw_path)))
    if not path.is_absolute():
        path = (_repo_root() / path).resolve()
    return path.resolve(strict=False)


def load_permission_config() -> dict[str, Any]:
    config = _default_permissions_config()
    path = permissions_config_path()

    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Permission config must be a mapping: {path}")
        config = _deep_merge(config, loaded)

    filesystem = dict(config.get("filesystem", {}))
    allowed_roots = [_expand_policy_path(str(item)) for item in filesystem.get("allowed_roots", [])]
    protected_paths = [_expand_policy_path(str(item)) for item in filesystem.get("protected_paths", [])]

    dynamic_workspace = workspace_dir().resolve()
    if dynamic_workspace not in allowed_roots:
        allowed_roots.append(dynamic_workspace)

    filesystem["allowed_roots"] = [str(item) for item in allowed_roots]
    filesystem["protected_paths"] = [str(item) for item in protected_paths]
    config["filesystem"] = filesystem
    config["_config_path"] = str(path)
    return config


class PermissionEngine:
    """Evaluate actions against the loaded permission config."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or load_permission_config()
        self._approval_gate = get_approval_gate()

    def _allowed_roots(self) -> list[Path]:
        return [
            Path(item).resolve(strict=False)
            for item in self.config.get("filesystem", {}).get("allowed_roots", [])
        ]

    def _protected_paths(self) -> list[Path]:
        return [
            Path(item).resolve(strict=False)
            for item in self.config.get("filesystem", {}).get("protected_paths", [])
        ]

    def _path_within(self, target: Path, root: Path) -> bool:
        try:
            target.resolve(strict=False).relative_to(root.resolve(strict=False))
            return True
        except ValueError:
            return False

    def _in_allowed_roots(self, target: Path) -> bool:
        return any(self._path_within(target, root) or target == root for root in self._allowed_roots())

    def _is_protected_path(self, target: Path) -> bool:
        return any(self._path_within(target, root) or target == root for root in self._protected_paths())

    def _resolve_tool_path(self, value: str) -> Path:
        return resolve_user_path(value).resolve(strict=False)

    def _make_decision(
        self,
        assessment: RiskAssessment,
        *,
        decision: str,
        reason: str | None = None,
        command: str = "",
        path: str = "",
        domain: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> PermissionDecision:
        return PermissionDecision(
            action=assessment.action,
            category=assessment.category,
            risk_level=assessment.risk_level,
            risk_label=risk_level_label(assessment.risk_level),
            decision=decision,
            reason=reason or assessment.reason,
            command=command,
            path=path,
            domain=domain,
            metadata=metadata or assessment.details,
        )

    def evaluate_shell_command(
        self,
        command: str,
        *,
        tool_name: str,
        working_directory: str = "",
    ) -> PermissionDecision:
        shell_config = self.config.get("shell", {})
        assessment = classify_shell_command(command)

        if not shell_config.get("enabled", True):
            return self._make_decision(assessment, decision="block", reason="Shell access is disabled in permissions config.", command=command)

        if assessment.blocked and shell_config.get("block_dangerous_commands", True):
            return self._make_decision(assessment, decision="block", command=command)

        if assessment.category == "shell.read_only":
            if shell_config.get("allow_readonly_commands", True):
                return self._make_decision(assessment, decision="allow", command=command)
            return self._make_decision(assessment, decision="block", reason="Read-only shell commands are disabled in permissions config.", command=command)

        if tool_name == "execute_shell_command":
            if self._approval_gate.has_session_approval("shell.host_command"):
                return self._make_decision(
                    assessment,
                    decision="allow",
                    reason="Session approval is active for host-level shell commands.",
                    command=command,
                )
            return self._make_decision(
                assessment,
                decision="ask",
                reason="Host-level shell commands require explicit approval outside the workspace shell.",
                command=command,
                metadata={"working_directory": working_directory or str(workspace_dir())},
            )

        if assessment.category == "shell.install" and shell_config.get("ask_before_install", True):
            if self._approval_gate.has_session_approval("shell.install"):
                return self._make_decision(
                    assessment,
                    decision="allow",
                    reason="Session approval is active for install commands.",
                    command=command,
                )
            return self._make_decision(assessment, decision="ask", command=command)

        if assessment.category == "shell.git_push" and shell_config.get("ask_before_git_push", True):
            if self._approval_gate.has_session_approval("shell.git_push"):
                return self._make_decision(
                    assessment,
                    decision="allow",
                    reason="Session approval is active for git push.",
                    command=command,
                )
            return self._make_decision(assessment, decision="ask", command=command)

        if assessment.category in {"shell.admin", "shell.delete", "shell.git_commit"}:
            if self._approval_gate.has_session_approval(assessment.category):
                return self._make_decision(
                    assessment,
                    decision="allow",
                    reason="Session approval is active for this shell category.",
                    command=command,
                )
            return self._make_decision(assessment, decision="ask", command=command)

        return self._make_decision(assessment, decision="allow", command=command)

    def evaluate_file_action(
        self,
        action: str,
        *,
        path_value: str,
        destination_value: str = "",
        overwrite: bool = False,
        recursive: bool = False,
    ) -> PermissionDecision:
        filesystem = self.config.get("filesystem", {})
        if not filesystem.get("enabled", True):
            assessment = classify_file_operation(action, path=path_value, destination_path=destination_value, overwrite=overwrite, recursive=recursive)
            return self._make_decision(assessment, decision="block", reason="Filesystem access is disabled in permissions config.")

        target = self._resolve_tool_path(path_value)
        destination = self._resolve_tool_path(destination_value) if destination_value else None

        assessment = classify_file_operation(
            action,
            path=str(target),
            destination_path=str(destination) if destination else "",
            overwrite=overwrite,
            recursive=recursive,
            target_exists=(destination.exists() if destination else target.exists()),
        )

        paths_to_check = [target]
        if destination is not None:
            paths_to_check.append(destination)

        for candidate in paths_to_check:
            if self._is_protected_path(candidate):
                return self._make_decision(
                    assessment,
                    decision="block",
                    reason=f"Path is protected by policy: {candidate}",
                    path=str(candidate),
                )
            if not self._in_allowed_roots(candidate):
                return self._make_decision(
                    assessment,
                    decision="block",
                    reason=f"Path is outside the allowed roots: {candidate}",
                    path=str(candidate),
                )

        if action in {"delete_path", "delete_workspace_file"}:
            if target in self._allowed_roots() and recursive:
                return self._make_decision(
                    assessment,
                    decision="block",
                    reason="Deleting an entire allowed root recursively is blocked by policy.",
                    path=str(target),
                )
            if self._approval_gate.has_session_approval("filesystem.delete"):
                return self._make_decision(
                    assessment,
                    decision="allow",
                    reason="Session approval is active for file deletion.",
                    path=str(target),
                )
            if filesystem.get("ask_before_delete", True):
                return self._make_decision(assessment, decision="ask", path=str(target))

        if assessment.category == "filesystem.overwrite":
            if self._approval_gate.has_session_approval("filesystem.overwrite"):
                return self._make_decision(
                    assessment,
                    decision="allow",
                    reason="Session approval is active for file overwrite.",
                    path=str(destination or target),
                )
            if filesystem.get("ask_before_overwrite", True):
                return self._make_decision(assessment, decision="ask", path=str(destination or target))

        return self._make_decision(assessment, decision="allow", path=str(destination or target))

    def evaluate_browser_action(
        self,
        action: str,
        *,
        url: str = "",
        element_label: str = "",
        press_enter: bool = False,
        text: str = "",
    ) -> PermissionDecision:
        browser_config = self.config.get("browser", {})
        assessment = classify_tool_call(
            "browser_type_index" if action == "browser_type_index" else action,
            {
                "current_url": url,
                "element_label": element_label,
                "press_enter": press_enter,
                "text": text,
            },
        )

        if not browser_config.get("enabled", True):
            return self._make_decision(assessment, decision="block", reason="Browser automation is disabled in permissions config.", domain=browser_domain(url))

        if assessment.needs_approval:
            if self._approval_gate.has_session_approval(assessment.category, value=browser_domain(url) or "*"):
                return self._make_decision(
                    assessment,
                    decision="allow",
                    reason="Session approval is active for this browser action category.",
                    domain=browser_domain(url),
                )
            return self._make_decision(assessment, decision="ask", domain=browser_domain(url))

        return self._make_decision(assessment, decision="allow", domain=browser_domain(url))

    def evaluate_tool_call(
        self,
        tool_name: str,
        params: dict[str, Any],
        *,
        working_directory: str = "",
    ) -> PermissionDecision:
        payload = params or {}

        if tool_name in {"run_shell_command", "execute_shell_command"}:
            return self.evaluate_shell_command(
                str(payload.get("command", "")),
                tool_name=tool_name,
                working_directory=working_directory,
            )

        if tool_name == "install_package":
            package_name = str(payload.get("package_name", "")).strip()
            return self.evaluate_shell_command(
                f"pip install {package_name}".strip(),
                tool_name=tool_name,
                working_directory=working_directory,
            )

        if tool_name == "git_commit":
            message = str(payload.get("message", "")).strip()
            command = 'git commit -m "<message>"' if message else "git commit"
            return self.evaluate_shell_command(command, tool_name=tool_name)

        if tool_name == "git_push":
            branch = str(payload.get("branch", "")).strip()
            remote = str(payload.get("remote", "origin")).strip() or "origin"
            command = f"git push {remote}" + (f" {branch}" if branch else "")
            return self.evaluate_shell_command(command, tool_name=tool_name)

        if tool_name == "write_file":
            target = self._resolve_tool_path(str(payload.get("file_path", "")))
            return self.evaluate_file_action(
                tool_name,
                path_value=str(target),
                overwrite=target.exists(),
            )

        if tool_name == "copy_path":
            destination = self._resolve_tool_path(str(payload.get("destination_path", "")))
            return self.evaluate_file_action(
                tool_name,
                path_value=str(payload.get("source_path", "")),
                destination_value=str(destination),
                overwrite=bool(payload.get("overwrite", False) or destination.exists()),
            )

        if tool_name == "move_path":
            destination = self._resolve_tool_path(str(payload.get("destination_path", "")))
            return self.evaluate_file_action(
                tool_name,
                path_value=str(payload.get("source_path", "")),
                destination_value=str(destination),
                overwrite=bool(payload.get("overwrite", False) or destination.exists()),
            )

        if tool_name == "delete_path":
            return self.evaluate_file_action(
                tool_name,
                path_value=str(payload.get("path", "")),
                recursive=bool(payload.get("recursive", False)),
            )

        if tool_name == "delete_workspace_file":
            return self.evaluate_file_action(
                tool_name,
                path_value=str(payload.get("filename", "")),
            )

        if tool_name == "browser_type_index":
            return self.evaluate_browser_action(
                tool_name,
                url=str(payload.get("current_url", "")),
                element_label=str(payload.get("element_label", f"indexed element [{payload.get('index', '?')}]")),
                press_enter=bool(payload.get("press_enter", False)),
                text=str(payload.get("text", "")),
            )

        if tool_name == "browser_press_key":
            key = str(payload.get("key", "")).strip()
            return self.evaluate_browser_action(
                tool_name,
                url=str(payload.get("current_url", "")),
                element_label=key,
                press_enter=key.lower() == "enter",
            )

        assessment = classify_tool_call(tool_name, payload)
        return self._make_decision(assessment, decision="allow")


def authorize_tool_call(
    tool_name: str,
    params: dict[str, Any],
    *,
    working_directory: str = "",
) -> tuple[PermissionDecision, ApprovalRequest | None]:
    engine = PermissionEngine()
    decision = engine.evaluate_tool_call(tool_name, params, working_directory=working_directory)

    if decision.decision == "allow":
        return decision, None

    request: ApprovalRequest | None = None
    if decision.decision == "ask":
        request = get_approval_gate().create_request(
            tool=tool_name,
            action=decision.action,
            category=decision.category,
            risk_level=decision.risk_level,
            reason=decision.reason,
            command=decision.command,
            path=decision.path,
            domain=decision.domain,
            metadata=decision.metadata,
        )

    append_audit_record(
        tool=tool_name,
        action=decision.action,
        decision=decision.decision,
        risk_level=decision.risk_level,
        result="approval_required" if decision.decision == "ask" else "blocked_by_policy",
        command=decision.command,
        path=decision.path,
        domain=decision.domain,
        metadata=decision.metadata,
    )
    return decision, request


def format_permission_response(
    decision: PermissionDecision,
    *,
    approval_request: ApprovalRequest | None = None,
) -> str:
    if decision.decision == "ask" and approval_request is not None:
        return format_approval_request(approval_request)

    header = "[Permission Blocked]" if decision.decision == "block" else "[Permission]"
    lines = [
        f"{header} {decision.action}",
        f"Risk: {decision.risk_level} ({decision.risk_label})",
        f"Reason: {decision.reason}",
    ]
    if decision.command:
        lines.append(f"Command: {decision.command}")
    if decision.path:
        lines.append(f"Path: {decision.path}")
    if decision.domain:
        lines.append(f"Domain: {decision.domain}")
    return "\n".join(lines)


def record_tool_result(
    tool_name: str,
    decision: PermissionDecision,
    *,
    result: str,
    command: str = "",
    path: str = "",
    domain: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    append_audit_record(
        tool=tool_name,
        action=decision.action,
        decision=decision.decision,
        risk_level=decision.risk_level,
        result=result,
        command=command or decision.command,
        path=path or decision.path,
        domain=domain or decision.domain,
        metadata=metadata or decision.metadata,
    )
