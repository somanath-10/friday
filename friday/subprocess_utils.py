"""
Subprocess helpers that keep Windows command output readable.
"""

from __future__ import annotations

import locale
import subprocess


def decode_subprocess_text(data: bytes | str | None) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        return data

    encodings: list[str] = []
    for candidate in (
        "utf-8",
        "utf-8-sig",
        locale.getpreferredencoding(False),
        "cp65001",
        "cp437",
        "cp1252",
        "latin-1",
    ):
        if candidate and candidate not in encodings:
            encodings.append(candidate)

    for encoding in encodings:
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue

    return data.decode("utf-8", errors="replace")


def completed_process_text(
    result: subprocess.CompletedProcess[bytes | str | None],
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=result.args,
        returncode=result.returncode,
        stdout=decode_subprocess_text(result.stdout),
        stderr=decode_subprocess_text(result.stderr),
    )


def run_powershell(
    script: str,
    *,
    timeout: int = 20,
    no_profile: bool = True,
    force_utf8: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = ["powershell"]
    if no_profile:
        command.append("-NoProfile")

    wrapped_script = script
    if force_utf8:
        wrapped_script = (
            "[Console]::InputEncoding = [System.Text.Encoding]::UTF8; "
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "$OutputEncoding = [System.Text.Encoding]::UTF8;\n"
            f"{script}"
        )
    result = subprocess.run(
        [*command, "-Command", wrapped_script],
        capture_output=True,
        text=False,
        timeout=timeout,
    )
    return completed_process_text(result)
