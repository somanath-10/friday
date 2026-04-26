"""
Risk classification helpers for FRIDAY actions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit
import re


RISK_LEVEL_LABELS = {
    0: "Read-only",
    1: "Safe write",
    2: "Reversible change",
    3: "Sensitive action",
    4: "Dangerous/restricted",
}

_READ_ONLY_SHELL_PATTERNS = (
    r"^\s*pwd\s*$",
    r"^\s*(ls|dir)(\s+.+)?$",
    r"^\s*whoami\s*$",
    r"^\s*python(\.exe)?\s+--version\s*$",
    r"^\s*node\s+--version\s*$",
    r"^\s*git\s+status(\s+.*)?$",
    r"^\s*git\s+diff(\s+.*)?$",
    r"^\s*git\s+rev-parse(\s+.*)?$",
    r"^\s*(python(\.exe)?\s+-m\s+)?pytest(\s+.*)?$",
    r"^\s*npm\s+test(\s+.*)?$",
    r"^\s*pip\s+list(\s+.*)?$",
)

_SAFE_WRITE_SHELL_PATTERNS = (
    r"^\s*mkdir(\s+.+)+$",
    r"^\s*new-item\s+.+-itemtype\s+directory.*$",
)

_INSTALL_SHELL_PATTERNS = (
    r"\bpip\s+install\b",
    r"\buv\s+pip\s+install\b",
    r"\bnpm\s+install\b",
    r"\bpnpm\s+install\b",
    r"\byarn\s+add\b",
    r"\bwinget\s+install\b",
    r"\bchoco\s+install\b",
    r"\bapt(-get)?\s+install\b",
    r"\bbrew\s+install\b",
)

_ADMIN_SHELL_PATTERNS = (
    r"\bsudo\b",
    r"\brunas\b",
    r"-verb\s+runas",
    r"\bset-executionpolicy\b",
    r"\bsc\s+(start|stop|config)\b",
    r"\bshutdown\b",
    r"\breboot\b",
)

_COMMIT_SHELL_PATTERNS = (
    r"^\s*git\s+commit\b",
    r"^\s*git\s+add\b",
)

_PUSH_SHELL_PATTERNS = (r"^\s*git\s+push\b",)

_DELETE_SHELL_PATTERNS = (
    r"\brm\b",
    r"\bdel\b",
    r"\brmdir\b",
    r"\bremove-item\b",
)

_DANGEROUS_SHELL_PATTERNS = (
    r"\brm\s+-rf\s+/\s*$",
    r"\brm\s+-rf\s+--no-preserve-root\s+/\s*$",
    r"\bdel\s+/[a-z\s]*\bc:\\\b",
    r"\brmdir\s+/s\s+/q\s+c:\\\b",
    r"\bformat\s+[a-z]:",
    r"\bdiskpart\b",
    r"\bvssadmin\s+delete\s+shadows\b",
    r"\bwbadmin\s+delete\b",
    r"\bbcdedit\b",
    r"\bset-mppreference\b",
    r"\bmimikatz\b",
    r"\bprocdump\b.+\blsass\b",
)

_SENSITIVE_BROWSER_TERMS = {
    "account",
    "auth",
    "bank",
    "buy",
    "card",
    "checkout",
    "email",
    "enter",
    "financial",
    "invoice",
    "login",
    "message",
    "password",
    "pay",
    "payment",
    "purchase",
    "security",
    "send",
    "settings",
    "signin",
    "submit",
    "transfer",
}


@dataclass(frozen=True)
class RiskAssessment:
    """Structured risk metadata for an intended action."""

    action: str
    category: str
    risk_level: int
    reason: str
    needs_approval: bool = False
    blocked: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def risk_label(self) -> str:
        return risk_level_label(self.risk_level)


def risk_level_label(level: int) -> str:
    return RISK_LEVEL_LABELS.get(level, "Unknown")


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _sensitive_browser_context(url: str = "", element_label: str = "", text: str = "") -> bool:
    combined = " ".join(part for part in (url, element_label, text) if part).lower()
    return any(term in combined for term in _SENSITIVE_BROWSER_TERMS)


def classify_shell_command(command: str) -> RiskAssessment:
    """Classify a shell command by risk level."""
    normalized = (command or "").strip()
    lowered = normalized.lower()

    if not normalized:
        return RiskAssessment(
            action="shell.command",
            category="shell.command",
            risk_level=0,
            reason="Empty command.",
        )

    if _matches_any(lowered, _DANGEROUS_SHELL_PATTERNS):
        return RiskAssessment(
            action="shell.command",
            category="shell.dangerous",
            risk_level=4,
            reason="Command matches a blocked dangerous shell pattern.",
            blocked=True,
        )

    if _matches_any(lowered, _PUSH_SHELL_PATTERNS):
        return RiskAssessment(
            action="shell.command",
            category="shell.git_push",
            risk_level=3,
            reason="Git push sends code to a remote repository.",
            needs_approval=True,
        )

    if _matches_any(lowered, _COMMIT_SHELL_PATTERNS):
        return RiskAssessment(
            action="shell.command",
            category="shell.git_commit",
            risk_level=3,
            reason="Git staging and commit commands modify repository history.",
            needs_approval=True,
        )

    if _matches_any(lowered, _INSTALL_SHELL_PATTERNS):
        return RiskAssessment(
            action="shell.command",
            category="shell.install",
            risk_level=2,
            reason="Install commands change the local environment.",
            needs_approval=True,
        )

    if _matches_any(lowered, _ADMIN_SHELL_PATTERNS):
        return RiskAssessment(
            action="shell.command",
            category="shell.admin",
            risk_level=3,
            reason="Administrative or system-wide shell commands require explicit approval.",
            needs_approval=True,
        )

    if _matches_any(lowered, _DELETE_SHELL_PATTERNS):
        return RiskAssessment(
            action="shell.command",
            category="shell.delete",
            risk_level=3,
            reason="Destructive shell commands require explicit approval.",
            needs_approval=True,
        )

    if _matches_any(lowered, _READ_ONLY_SHELL_PATTERNS):
        return RiskAssessment(
            action="shell.command",
            category="shell.read_only",
            risk_level=0,
            reason="Command matches an allowlisted read-only shell pattern.",
        )

    if _matches_any(lowered, _SAFE_WRITE_SHELL_PATTERNS):
        return RiskAssessment(
            action="shell.command",
            category="shell.safe_write",
            risk_level=1,
            reason="Command performs a simple local write in a likely reversible way.",
        )

    return RiskAssessment(
        action="shell.command",
        category="shell.command",
        risk_level=1,
        reason="Command does not match a blocked or approval-gated shell pattern.",
    )


def classify_file_operation(
    action: str,
    *,
    path: str = "",
    destination_path: str = "",
    overwrite: bool = False,
    recursive: bool = False,
    target_exists: bool | None = None,
) -> RiskAssessment:
    """Classify a file operation by risk level."""
    normalized_action = (action or "").strip().lower()
    details = {
        "path": path,
        "destination_path": destination_path,
        "overwrite": overwrite,
        "recursive": recursive,
        "target_exists": target_exists,
    }

    if normalized_action in {"delete", "delete_path", "delete_workspace_file"}:
        return RiskAssessment(
            action="filesystem.delete",
            category="filesystem.delete",
            risk_level=3,
            reason="Deleting files or folders is a sensitive action.",
            needs_approval=True,
            details=details,
        )

    if normalized_action in {"write", "write_file", "copy", "copy_path", "move", "move_path"}:
        if overwrite or target_exists:
            return RiskAssessment(
                action="filesystem.overwrite",
                category="filesystem.overwrite",
                risk_level=3,
                reason="Overwriting an existing file or folder is a sensitive action.",
                needs_approval=True,
                details=details,
            )

    if normalized_action in {"move", "move_path", "rename"}:
        return RiskAssessment(
            action="filesystem.move",
            category="filesystem.move",
            risk_level=2,
            reason="Moving or renaming files is usually reversible.",
            details=details,
        )

    if normalized_action in {"append", "append_to_file", "write", "write_file", "copy", "copy_path"}:
        return RiskAssessment(
            action="filesystem.write",
            category="filesystem.write",
            risk_level=1,
            reason="Creating or extending files is a low-risk write action.",
            details=details,
        )

    return RiskAssessment(
        action="filesystem.action",
        category="filesystem.action",
        risk_level=1,
        reason="General file action.",
        details=details,
    )


def classify_browser_action(
    action: str,
    *,
    url: str = "",
    element_label: str = "",
    press_enter: bool = False,
    text: str = "",
) -> RiskAssessment:
    """Classify a browser action by risk level."""
    normalized_action = (action or "").strip().lower()
    details = {
        "url": url,
        "element_label": element_label,
        "press_enter": press_enter,
        "text": text,
    }

    if press_enter or normalized_action in {"submit", "submit_form"}:
        return RiskAssessment(
            action="browser.submit_form",
            category="browser.submit_form",
            risk_level=3,
            reason="Submitting a browser form requires approval.",
            needs_approval=True,
            details=details,
        )

    if _sensitive_browser_context(url=url, element_label=element_label, text=text):
        return RiskAssessment(
            action="browser.sensitive",
            category="browser.sensitive",
            risk_level=3,
            reason="Browser action appears to touch a sensitive page or form.",
            needs_approval=True,
            details=details,
        )

    return RiskAssessment(
        action="browser.action",
        category="browser.action",
        risk_level=0,
        reason="Observed browser interaction without a sensitive submit signal.",
        details=details,
    )


def classify_desktop_action(action: str, *, target: str = "") -> RiskAssessment:
    """Classify a desktop or app action by risk level."""
    lowered = f"{action} {target}".lower()
    if any(term in lowered for term in ("password", "force quit", "admin", "system setting")):
        return RiskAssessment(
            action="desktop.action",
            category="desktop.sensitive",
            risk_level=3,
            reason="Desktop action may touch passwords, forced app control, or system settings.",
            needs_approval=True,
            details={"target": target},
        )

    return RiskAssessment(
        action="desktop.action",
        category="desktop.action",
        risk_level=0,
        reason="Desktop action appears non-destructive.",
        details={"target": target},
    )


def classify_tool_call(tool_name: str, params: dict[str, Any]) -> RiskAssessment:
    """Classify an MCP tool call by dispatching to the most relevant classifier."""
    name = (tool_name or "").strip()
    payload = params or {}

    if name in {"run_shell_command", "execute_shell_command"}:
        return classify_shell_command(str(payload.get("command", "")))

    if name == "git_push":
        return RiskAssessment(
            action="git.push",
            category="shell.git_push",
            risk_level=3,
            reason="Git push sends committed changes to a remote repository.",
            needs_approval=True,
            details={"remote": payload.get("remote", "origin"), "branch": payload.get("branch", "")},
        )

    if name in {"write_file", "copy_path", "move_path", "delete_path", "delete_workspace_file"}:
        action = name
        return classify_file_operation(
            action,
            path=str(payload.get("file_path") or payload.get("path") or payload.get("filename") or payload.get("source_path") or ""),
            destination_path=str(payload.get("destination_path", "")),
            overwrite=bool(payload.get("overwrite", False)),
            recursive=bool(payload.get("recursive", False)),
        )

    if name == "browser_type_index":
        return classify_browser_action(
            name,
            url=str(payload.get("current_url", "")),
            element_label=str(payload.get("element_label", "")),
            press_enter=bool(payload.get("press_enter", False)),
            text=str(payload.get("text", "")),
        )

    if name == "browser_press_key":
        current_url = str(payload.get("current_url", ""))
        key = str(payload.get("key", ""))
        return classify_browser_action(
            name,
            url=current_url,
            element_label=key,
            press_enter=key.strip().lower() == "enter",
        )

    if name.startswith("browser_"):
        return classify_browser_action(name, url=str(payload.get("current_url", "")))

    return RiskAssessment(
        action=name or "tool.call",
        category="tool.call",
        risk_level=0,
        reason="Tool call is not yet mapped to a higher-risk classifier.",
        details=payload,
    )


def classify_planned_step(step: dict[str, Any]) -> RiskAssessment:
    """Classify a planner-style step dict."""
    if "tool_name" in step:
        return classify_tool_call(str(step["tool_name"]), dict(step.get("parameters", {})))

    action_type = str(step.get("action_type", "")).lower()
    description = str(step.get("description", ""))
    if action_type == "shell":
        return classify_shell_command(description)
    if action_type == "browser":
        return classify_browser_action(description)
    if action_type == "files":
        return classify_file_operation(description)
    if action_type == "desktop":
        return classify_desktop_action(description)

    return RiskAssessment(
        action=action_type or "plan.step",
        category="plan.step",
        risk_level=0,
        reason="Planner step does not match a specific classifier yet.",
        details=step,
    )


def browser_domain(url: str) -> str:
    """Extract a normalized browser domain."""
    if not url:
        return ""
    return urlsplit(url).hostname or ""

