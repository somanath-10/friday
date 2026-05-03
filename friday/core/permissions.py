"""
Permission decisions for local-first FRIDAY actions.

The checker combines static risk classification with a local permission config.
It returns explicit allow/ask/block decisions; tools can then refuse execution
or surface an approval request without guessing.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from friday.core.risk import RiskAssessment, RiskLevel, classify_shell_command, classify_tool_call
from friday.path_utils import resolve_user_path, workspace_dir
from friday.safety.emergency_stop import is_emergency_stopped
from friday.safety.policy import evaluate_safety_policy
from friday.safety.secrets_filter import is_protected_secret_path


DEFAULT_PERMISSIONS: dict[str, Any] = {
    "mode": "local_permission_based",
    "access_mode": "safe",
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
        "allowed_roots": ["~/Desktop", "~/Documents", "~/Downloads", "~/Workspace", "./workspace"],
        "protected_paths": [
            "~/.ssh",
            "~/.aws",
            "~/.config",
            "/etc",
            "/System",
            "C:/Windows",
            "C:/Program Files",
            "C:/Program Files (x86)",
            "%USERPROFILE%/.ssh",
            "%USERPROFILE%/.aws",
            "%USERPROFILE%/AppData",
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


ACCESS_MODES = {"safe", "trusted", "full_control"}


@dataclass(frozen=True)
class PermissionDecision:
    decision: str
    reason: str
    risk_level: RiskLevel
    risk_label: str
    category: str
    action: str
    subject: str = ""
    domain: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"

    @property
    def needs_approval(self) -> bool:
        return self.decision == "ask"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["risk_level"] = int(self.risk_level)
        return data


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _config_path() -> Path:
    configured = os.getenv("FRIDAY_PERMISSIONS_CONFIG", "").strip()
    if configured:
        return Path(os.path.expanduser(configured)).resolve()
    return _repo_root() / "config" / "permissions.yaml"


def _merge_dict(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _parse_scalar(value: str) -> Any:
    stripped = value.strip()
    if stripped.lower() in {"true", "false"}:
        return stripped.lower() == "true"
    if stripped.lower() in {"null", "none"}:
        return None
    if stripped.startswith("[") and stripped.endswith("]"):
        try:
            return json.loads(stripped.replace("'", '"'))
        except json.JSONDecodeError:
            return stripped
    try:
        return int(stripped)
    except ValueError:
        return stripped.strip('"').strip("'")


def _simple_yaml_load(text: str) -> dict[str, Any]:
    """Load the subset of YAML used by config/permissions.yaml without a dependency."""
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    last_key_at_indent: dict[int, str] = {}
    last_parent_at_indent: dict[int, tuple[dict[str, Any], str]] = {}

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]

        if line.startswith("- "):
            parent_items = [
                (level, parent, key)
                for level, (parent, key) in last_parent_at_indent.items()
                if level < indent
            ]
            if parent_items:
                _, parent, key = sorted(parent_items, key=lambda item: item[0])[-1]
                if not isinstance(parent.get(key), list):
                    parent[key] = []
                parent[key].append(_parse_scalar(line[2:]))
            continue

        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if value.strip():
            current[key] = _parse_scalar(value)
        else:
            current[key] = {}
            stack.append((indent, current[key]))
            last_key_at_indent[indent] = key
            last_parent_at_indent[indent] = (current, key)

    return root


def load_permissions_config(path: Path | None = None) -> dict[str, Any]:
    """Load permission config from YAML when present, falling back to defaults."""
    config_path = path or _config_path()
    if not config_path.exists():
        return DEFAULT_PERMISSIONS

    text = config_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        parsed = yaml.safe_load(text) or {}
    except Exception:
        parsed = _simple_yaml_load(text)
    if not isinstance(parsed, dict):
        parsed = {}
    merged = _merge_dict(DEFAULT_PERMISSIONS, parsed)
    env_mode = os.getenv("FRIDAY_ACCESS_MODE", "").strip().lower()
    if env_mode:
        merged["access_mode"] = env_mode
    return merged


def get_access_mode(config: dict[str, Any] | None = None) -> str:
    permissions = config or load_permissions_config()
    mode = str(permissions.get("access_mode") or os.getenv("FRIDAY_ACCESS_MODE") or "safe").strip().lower()
    return mode if mode in ACCESS_MODES else "safe"


def access_mode_summary(config: dict[str, Any] | None = None) -> dict[str, Any]:
    mode = get_access_mode(config)
    return {
        "mode": mode,
        "description": {
            "safe": "Workspace-first mode. Sensitive actions ask, dangerous actions are blocked.",
            "trusted": "Desktop, browser, filesystem, and shell are enabled with approvals for sensitive actions.",
            "full_control": "Broad local access can be requested, but Level 3 still asks and Level 4 remains blocked.",
        }[mode],
        "requires_approval_for_level_3": True,
        "blocks_level_4": True,
    }


def _expand_path(raw_path: str) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(raw_path)))
    if not path.is_absolute():
        path = (_repo_root() / path).resolve()
    return path.resolve()


def _looks_like_windows_absolute(path_text: str) -> bool:
    return bool(re.match(r"^[a-zA-Z]:[\\/]", path_text.strip())) or path_text.strip().startswith("\\\\")


def _normalize_windows_path_text(path_text: str) -> str:
    expanded = re.sub(
        r"%([^%]+)%",
        lambda match: os.environ.get(match.group(1), match.group(0)),
        path_text,
    )
    return expanded.replace("\\", "/").rstrip("/").lower()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _protected_path_reason(path_text: str, config: dict[str, Any]) -> str:
    if not path_text:
        return ""
    if _looks_like_windows_absolute(path_text):
        normalized_target = _normalize_windows_path_text(path_text)
        for raw_root in config.get("filesystem", {}).get("protected_paths", []):
            if not _looks_like_windows_absolute(str(raw_root)) and "%" not in str(raw_root):
                continue
            normalized_root = _normalize_windows_path_text(str(raw_root))
            if normalized_target == normalized_root or normalized_target.startswith(normalized_root + "/"):
                return f"Path is protected: {raw_root}"
    try:
        target = resolve_user_path(path_text)
    except Exception:
        target = _expand_path(path_text)
    if is_protected_secret_path(target):
        return f"Path is protected because it appears to contain credentials or secrets: {target}"
    protected = config.get("filesystem", {}).get("protected_paths", [])
    for raw_root in protected:
        root = _expand_path(str(raw_root))
        if _is_relative_to(target, root):
            return f"Path is protected: {root}"
    return ""


def _filesystem_allowed(path_text: str, config: dict[str, Any]) -> bool:
    if not path_text:
        return True
    roots = config.get("filesystem", {}).get("allowed_roots", [])
    expanded_roots = [_expand_path(str(root)) for root in roots]
    expanded_roots.append(workspace_dir())

    if _looks_like_windows_absolute(path_text):
        normalized_target = _normalize_windows_path_text(path_text)
        for root in expanded_roots:
            normalized_root = _normalize_windows_path_text(str(root))
            if normalized_target == normalized_root or normalized_target.startswith(normalized_root + "/"):
                return True
        return False
    try:
        target = resolve_user_path(path_text)
    except Exception:
        target = _expand_path(path_text)

    return any(_is_relative_to(target, root) for root in expanded_roots)


def permission_for_assessment(
    action: str,
    assessment: RiskAssessment,
    *,
    subject: str = "",
    config: dict[str, Any] | None = None,
) -> PermissionDecision:
    permissions = config or load_permissions_config()
    if is_emergency_stopped():
        return PermissionDecision(
            "block",
            "Emergency stop is active; clear it before running more local actions.",
            RiskLevel.DANGEROUS_RESTRICTED,
            RiskLevel.DANGEROUS_RESTRICTED.name,
            assessment.category,
            action,
            subject,
        )

    policy_decision = evaluate_safety_policy(action, {"subject": subject, "category": assessment.category})
    if policy_decision.decision == "block":
        return PermissionDecision(
            "block",
            policy_decision.reason,
            RiskLevel.DANGEROUS_RESTRICTED,
            RiskLevel.DANGEROUS_RESTRICTED.name,
            assessment.category,
            action,
            subject,
        )
    access_mode = get_access_mode(permissions)

    if assessment.level >= RiskLevel.DANGEROUS_RESTRICTED:
        return PermissionDecision(
            "block",
            assessment.reason,
            assessment.level,
            assessment.label,
            assessment.category,
            action,
            subject,
        )

    if assessment.category == "shell" and not permissions.get("shell", {}).get("enabled", True):
        return PermissionDecision("block", "Shell tools are disabled by permissions config.", assessment.level, assessment.label, "shell", action, subject)
    if assessment.category == "files" and not permissions.get("filesystem", {}).get("enabled", True):
        return PermissionDecision("block", "Filesystem tools are disabled by permissions config.", assessment.level, assessment.label, "files", action, subject)
    if assessment.category == "browser" and not permissions.get("browser", {}).get("enabled", True):
        return PermissionDecision("block", "Browser tools are disabled by permissions config.", assessment.level, assessment.label, "browser", action, subject)
    if assessment.category == "desktop" and not permissions.get("desktop", {}).get("enabled", True):
        return PermissionDecision("block", "Desktop tools are disabled by permissions config.", assessment.level, assessment.label, "desktop", action, subject)

    if assessment.category == "files":
        protected_reason = _protected_path_reason(subject, permissions)
        if protected_reason:
            return PermissionDecision("block", protected_reason, RiskLevel.DANGEROUS_RESTRICTED, RiskLevel.DANGEROUS_RESTRICTED.name, "files", action, subject)
        if not _filesystem_allowed(subject, permissions):
            return PermissionDecision("ask", "Path is outside configured allowed roots.", assessment.level, assessment.label, "files", action, subject)

    if access_mode == "safe" and assessment.category == "shell" and assessment.level >= RiskLevel.SENSITIVE_ACTION:
        return PermissionDecision("ask", "Safe mode requires approval for sensitive shell actions.", assessment.level, assessment.label, assessment.category, action, subject)

    if assessment.level <= RiskLevel.SAFE_WRITE:
        return PermissionDecision("allow", assessment.reason, assessment.level, assessment.label, assessment.category, action, subject)

    if assessment.level == RiskLevel.REVERSIBLE_CHANGE:
        return PermissionDecision("allow", assessment.reason, assessment.level, assessment.label, assessment.category, action, subject)

    from friday.safety.approval_gate import approval_key_for, consume_approval_key, has_session_approval

    approval_key = approval_key_for(
        action=action,
        category=assessment.category,
        subject=subject,
        risk_level=int(assessment.level),
    )
    if consume_approval_key(approval_key) or has_session_approval(assessment.category):
        return PermissionDecision(
            "allow",
            f"Approved by user: {assessment.reason}",
            assessment.level,
            assessment.label,
            assessment.category,
            action,
            subject,
        )

    return PermissionDecision("ask", assessment.reason, assessment.level, assessment.label, assessment.category, action, subject)


def check_shell_permission(command: str, *, config: dict[str, Any] | None = None) -> PermissionDecision:
    return permission_for_assessment("shell.command", classify_shell_command(command), subject=command, config=config)


def check_tool_permission(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    subject: str = "",
    config: dict[str, Any] | None = None,
) -> PermissionDecision:
    assessment = classify_tool_call(tool_name, arguments or {})
    resolved_subject = subject
    if not resolved_subject and arguments:
        resolved_subject = str(arguments.get("path") or arguments.get("file_path") or arguments.get("filename") or arguments.get("command") or "")
    return permission_for_assessment(tool_name, assessment, subject=resolved_subject, config=config)


def _extract_domain(arguments: dict[str, Any] | None = None) -> str:
    if not arguments:
        return ""
    raw_url = str(arguments.get("current_url") or arguments.get("url") or "").strip()
    if not raw_url:
        return ""
    return urlsplit(raw_url).hostname or ""


def authorize_tool_call(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    config: dict[str, Any] | None = None,
) -> tuple[PermissionDecision, Any | None]:
    """Compatibility wrapper for older tool modules that expect approval payloads."""
    args = arguments or {}
    subject = str(
        args.get("path")
        or args.get("file_path")
        or args.get("filename")
        or args.get("command")
        or args.get("current_url")
        or args.get("url")
        or ""
    )
    decision = check_tool_permission(tool_name, args, subject=subject, config=config)
    enriched = PermissionDecision(
        decision.decision,
        decision.reason,
        decision.risk_level,
        decision.risk_label,
        decision.category,
        decision.action,
        decision.subject,
        domain=_extract_domain(args),
        metadata=dict(args),
    )
    approval_request = None
    if enriched.decision == "ask":
        from friday.safety.approval_gate import create_approval_request

        approval_request = create_approval_request(
            enriched,
            tool=tool_name,
            command=str(args.get("command", "")),
            path=str(args.get("path") or args.get("file_path") or ""),
            domain=enriched.domain,
        )
    return enriched, approval_request


def format_permission_response(
    decision: PermissionDecision,
    *,
    approval_request: Any | None = None,
) -> str:
    if approval_request is not None:
        from friday.safety.approval_gate import format_approval_required

        return format_approval_required(approval_request)
    return decision.reason


def record_tool_result(
    tool_name: str,
    decision: PermissionDecision,
    *,
    result: str,
    domain: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    from friday.safety.audit_log import append_audit_record

    append_audit_record(
        command=decision.subject or tool_name,
        intent=decision.category,
        risk_level=int(decision.risk_level),
        decision=decision.decision,
        tool=tool_name,
        result=result,
        extra={
            "domain": domain or decision.domain,
            "metadata": metadata or decision.metadata,
        },
    )
