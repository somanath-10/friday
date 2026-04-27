"""Optional sandbox capability checks for code tasks."""

from __future__ import annotations

import shutil


def docker_available() -> bool:
    return shutil.which("docker") is not None


def sandbox_summary() -> dict[str, object]:
    return {
        "docker_available": docker_available(),
        "default": "local_process_with_permissions",
    }
