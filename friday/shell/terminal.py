"""Terminal execution primitives with timeouts and output limits."""

from __future__ import annotations

import platform
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from friday.subprocess_utils import run_powershell
from friday.safety.secrets_filter import redact_text
from friday.shell.command_policy import sanitize_environment


@dataclass(frozen=True)
class TerminalResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_terminal_command(
    command: str,
    *,
    cwd: str | Path,
    timeout_seconds: int = 60,
    max_output_chars: int = 8000,
) -> TerminalResult:
    try:
        if platform.system() == "Windows":
            lowered = command.strip().lower()
            if lowered.startswith(("powershell ", "pwsh ")) or any(
                marker in lowered
                for marker in ("get-childitem", "get-location", "remove-item", "set-executionpolicy", "$env:")
            ):
                script = command
                if lowered.startswith("powershell "):
                    script = command.split(None, 1)[1] if len(command.split(None, 1)) == 2 else ""
                result = run_powershell(script, timeout=max(1, timeout_seconds), no_profile=False, force_utf8=True)
                stdout = redact_text(result.stdout or "")
                stderr = redact_text(result.stderr or "")
                if len(stdout) > max_output_chars:
                    stdout = stdout[:max_output_chars] + "\n... [truncated]"
                if len(stderr) > max_output_chars:
                    stderr = stderr[:max_output_chars] + "\n... [truncated]"
                return TerminalResult(result.returncode, stdout, stderr)

        result = subprocess.run(
            command,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=max(1, timeout_seconds),
            env=sanitize_environment(),
        )
        stdout = redact_text(result.stdout or "")
        stderr = redact_text(result.stderr or "")
        if len(stdout) > max_output_chars:
            stdout = stdout[:max_output_chars] + "\n... [truncated]"
        if len(stderr) > max_output_chars:
            stderr = stderr[:max_output_chars] + "\n... [truncated]"
        return TerminalResult(result.returncode, stdout, stderr)
    except subprocess.TimeoutExpired as exc:
        return TerminalResult(-1, redact_text(exc.stdout or ""), redact_text(exc.stderr or ""), timed_out=True)
