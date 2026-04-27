"""
Risk classification for planned actions and tool calls.

This phase intentionally keeps the classifier deterministic and conservative.
The goal is not perfect natural-language understanding; it is to prevent
obvious dangerous actions from reaching local tools silently.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any


class RiskLevel(IntEnum):
    READ_ONLY = 0
    SAFE_WRITE = 1
    REVERSIBLE_CHANGE = 2
    SENSITIVE_ACTION = 3
    DANGEROUS_RESTRICTED = 4


@dataclass(frozen=True)
class RiskAssessment:
    level: RiskLevel
    reason: str
    category: str

    @property
    def label(self) -> str:
        return RISK_LABELS[self.level]


RISK_LABELS = {
    RiskLevel.READ_ONLY: "Level 0 - Read-only",
    RiskLevel.SAFE_WRITE: "Level 1 - Safe write",
    RiskLevel.REVERSIBLE_CHANGE: "Level 2 - Reversible change",
    RiskLevel.SENSITIVE_ACTION: "Level 3 - Sensitive action",
    RiskLevel.DANGEROUS_RESTRICTED: "Level 4 - Dangerous/restricted",
}

DANGEROUS_SHELL_PATTERNS = (
    "rm -rf /",
    "rm -fr /",
    "mkfs",
    "diskpart",
    "format ",
    "dd if=",
    ":(){",
    "chmod -r 777 /",
    "chown -r",
    "shutdown",
    "reboot",
    "halt",
    "disable-firewall",
    "set-mppreference",
    "security dump-keychain",
)

SENSITIVE_SHELL_TOKENS = {
    "sudo",
    "su",
    "doas",
    "rm",
    "rmdir",
    "del",
    "erase",
    "format",
    "git push",
    "git commit",
    "pip install",
    "uv pip install",
    "npm install",
    "brew install",
    "apt install",
    "apt-get install",
    "winget install",
    "defaults write",
    "systemctl",
    "launchctl",
}

READONLY_COMMANDS = {
    "pwd",
    "ls",
    "dir",
    "whoami",
    "id",
    "date",
    "python",
    "python3",
    "node",
    "npm",
    "uv",
    "pytest",
    "git",
    "cat",
    "head",
    "tail",
    "wc",
    "rg",
    "grep",
}


def _normalized_command(command: str) -> str:
    return " ".join(command.strip().lower().split())


def _first_command_token(command: str) -> str:
    try:
        parts = shlex.split(command, posix=True)
    except ValueError:
        parts = command.strip().split()
    return Path(parts[0]).name.lower() if parts else ""


def _command_parts(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.strip().split()


def _looks_like_readonly_python(parts: list[str]) -> bool:
    if not parts:
        return False
    executable = Path(parts[0]).name.lower()
    if executable not in {"python", "python3", "py"}:
        return False
    lowered = [part.lower() for part in parts[1:]]
    if not lowered:
        return False
    readonly_flags = {"--version", "-v", "-vv", "-h", "--help"}
    if lowered[0] in readonly_flags:
        return True
    return any(part in {"pytest", "unittest"} for part in lowered[:3])


def _looks_like_readonly_git(parts: list[str]) -> bool:
    if not parts or Path(parts[0]).name.lower() != "git":
        return False
    if len(parts) == 1:
        return False
    return parts[1].lower() in {"status", "diff", "log", "show", "branch", "rev-parse"}


def _looks_like_project_test(parts: list[str]) -> bool:
    lowered = [part.lower() for part in parts]
    if not lowered:
        return False
    first = Path(lowered[0]).name
    if first == "pytest":
        return True
    if first == "npm" and len(lowered) > 1 and lowered[1] in {"test", "run"}:
        return "test" in lowered[1:3]
    if first == "uv" and any(part == "pytest" for part in lowered[:4]):
        return True
    return False


def classify_shell_command(command: str) -> RiskAssessment:
    normalized = _normalized_command(command)
    if not normalized:
        return RiskAssessment(RiskLevel.READ_ONLY, "No command provided.", "shell")

    if any(pattern in normalized for pattern in DANGEROUS_SHELL_PATTERNS):
        return RiskAssessment(
            RiskLevel.DANGEROUS_RESTRICTED,
            "Command matches a destructive or system-disruptive pattern.",
            "shell",
        )

    if "rm -rf" in normalized or "rm -fr" in normalized:
        return RiskAssessment(
            RiskLevel.DANGEROUS_RESTRICTED,
            "Recursive forced deletion is restricted.",
            "shell",
        )

    if any(marker in normalized for marker in ("|", ";", "&&", "||", "$(", "`")):
        return RiskAssessment(RiskLevel.REVERSIBLE_CHANGE, "Compound shell command requires conservative handling.", "shell")

    if "git push" in normalized:
        return RiskAssessment(RiskLevel.SENSITIVE_ACTION, "Pushing code requires approval.", "shell")
    if "git commit" in normalized:
        return RiskAssessment(RiskLevel.SENSITIVE_ACTION, "Committing code requires approval.", "shell")
    if any(token in normalized for token in ("pip install", "uv pip install", "npm install", "brew install", "winget install", "apt install", "apt-get install")):
        return RiskAssessment(RiskLevel.SENSITIVE_ACTION, "Installing software/packages requires approval.", "shell")
    if normalized.startswith(("sudo ", "su ", "doas ")):
        return RiskAssessment(RiskLevel.SENSITIVE_ACTION, "Elevated/admin command requires approval.", "shell")
    if normalized.startswith(("rm ", "rmdir ", "del ", "erase ")):
        return RiskAssessment(RiskLevel.SENSITIVE_ACTION, "Delete command requires approval.", "shell")
    if any(token in normalized for token in (" > ", ">>", "mv ", "cp ", "chmod ", "chown ", "git add")):
        return RiskAssessment(RiskLevel.REVERSIBLE_CHANGE, "Command may modify files or permissions.", "shell")

    parts = _command_parts(command)
    if _looks_like_project_test(parts):
        return RiskAssessment(RiskLevel.READ_ONLY, "Command runs project tests.", "shell")
    if _looks_like_readonly_python(parts):
        return RiskAssessment(RiskLevel.READ_ONLY, "Python command appears read-only or test-oriented.", "shell")
    if _looks_like_readonly_git(parts):
        return RiskAssessment(RiskLevel.READ_ONLY, "Git command is read-only.", "shell")

    first = _first_command_token(command)
    if first in {"pwd", "ls", "dir", "whoami", "id", "date", "cat", "head", "tail", "wc", "rg", "grep"}:
        return RiskAssessment(RiskLevel.READ_ONLY, "Command appears read-only.", "shell")

    if first in {"python", "python3", "py", "node", "npm", "uv", "git"}:
        return RiskAssessment(
            RiskLevel.REVERSIBLE_CHANGE,
            "Interpreter/package/git command may change local state unless it is a recognized read-only/test command.",
            "shell",
        )

    return RiskAssessment(RiskLevel.REVERSIBLE_CHANGE, "Unknown command may change local state.", "shell")


def classify_file_operation(operation: str, path: str = "", *, overwrite: bool = False) -> RiskAssessment:
    op = operation.strip().lower()
    if op in {"read", "list", "search", "stat"}:
        return RiskAssessment(RiskLevel.READ_ONLY, "File operation is read-only.", "files")
    if op in {"create", "append", "write_new", "mkdir"} and not overwrite:
        return RiskAssessment(RiskLevel.SAFE_WRITE, "Operation creates or appends without replacing existing data.", "files")
    if op in {"copy", "move", "rename"} and not overwrite:
        return RiskAssessment(RiskLevel.REVERSIBLE_CHANGE, "Operation changes file organization.", "files")
    if overwrite or op in {"overwrite", "edit"}:
        return RiskAssessment(RiskLevel.SENSITIVE_ACTION, "Overwriting files requires approval.", "files")
    if op in {"delete", "remove", "recursive_delete"}:
        return RiskAssessment(RiskLevel.SENSITIVE_ACTION, "Deleting files requires approval.", "files")
    return RiskAssessment(RiskLevel.REVERSIBLE_CHANGE, f"File operation {op or 'unknown'} may change local data.", "files")


def classify_browser_action(action: str, url: str = "") -> RiskAssessment:
    normalized = action.strip().lower()
    if normalized in {"read", "navigate", "snapshot", "extract", "search"}:
        return RiskAssessment(RiskLevel.READ_ONLY, "Browser action is observational.", "browser")
    if normalized in {"type", "draft", "download"}:
        return RiskAssessment(RiskLevel.REVERSIBLE_CHANGE, "Browser action may change browser state.", "browser")
    if normalized in {"submit", "send", "purchase", "payment", "upload", "password"}:
        return RiskAssessment(RiskLevel.SENSITIVE_ACTION, "Sensitive browser action requires approval.", "browser")
    return RiskAssessment(RiskLevel.REVERSIBLE_CHANGE, "Browser action may change page state.", "browser")


def classify_desktop_action(action: str) -> RiskAssessment:
    normalized = action.strip().lower()
    if normalized in {"inspect_screen", "screenshot", "list_apps", "list_windows", "active_window"}:
        return RiskAssessment(RiskLevel.READ_ONLY, "Desktop action is observational.", "desktop")
    if normalized in {"open_app", "focus_window", "type_text", "hotkey", "click", "scroll", "drag"}:
        return RiskAssessment(RiskLevel.REVERSIBLE_CHANGE, "Desktop action changes visible machine state.", "desktop")
    if normalized in {"close_app", "force_quit", "system_settings", "password_field"}:
        return RiskAssessment(RiskLevel.SENSITIVE_ACTION, "Sensitive desktop action requires approval.", "desktop")
    return RiskAssessment(RiskLevel.REVERSIBLE_CHANGE, "Desktop action may affect local UI state.", "desktop")


def classify_tool_call(tool_name: str, arguments: dict[str, Any] | None = None) -> RiskAssessment:
    args = arguments or {}
    name = tool_name.strip().lower()

    if name in {"run_shell_command", "execute_shell_command"}:
        return classify_shell_command(str(args.get("command", "")))
    if name == "git_push":
        return RiskAssessment(RiskLevel.SENSITIVE_ACTION, "git push requires approval.", "git")
    if name == "git_commit":
        return RiskAssessment(RiskLevel.SENSITIVE_ACTION, "git commit requires approval.", "git")
    if name in {"read_file", "get_file_contents", "read_file_snippet", "list_directory_tree", "search_in_files", "search_paths_by_name"}:
        return classify_file_operation("read")
    if name in {"delete_path", "delete_workspace_file"}:
        return classify_file_operation("delete", str(args.get("path") or args.get("filename") or ""))
    if name == "create_folder":
        return classify_file_operation("mkdir")
    if name == "append_to_file":
        return classify_file_operation("append")
    if name in {"write_file", "create_document"}:
        operation = str(args.get("operation", "")).strip().lower()
        if operation == "append":
            return classify_file_operation("append")
        return classify_file_operation("overwrite" if args.get("overwrite") else "write_new")
    if name in {"copy_path", "move_path"}:
        return classify_file_operation("move" if name == "move_path" else "copy", overwrite=bool(args.get("overwrite")))
    if name in {"browser_submit_sensitive_form", "browser_submit_form"}:
        return classify_browser_action("submit")
    if name == "browser_download_executable":
        return RiskAssessment(RiskLevel.SENSITIVE_ACTION, "Downloading executable files requires approval.", "browser")
    if name == "browser_download":
        return classify_browser_action("download")
    if name.startswith("browser_"):
        if name in {"browser_read_page", "browser_get_state", "browser_navigate"}:
            return classify_browser_action("read")
        if "type" in name:
            return classify_browser_action("type")
        if "click" in name:
            return classify_browser_action("click")
    if name in {"open_application", "focus_application", "type_text", "press_key", "gui_click"}:
        return classify_desktop_action("open_app" if name == "open_application" else name)

    return RiskAssessment(RiskLevel.REVERSIBLE_CHANGE, "Unknown tool call may change local state.", "tool")
