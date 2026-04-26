"""
Tool registry - imports and registers tool modules with the MCP server.
"""

from __future__ import annotations

import copy
import importlib
from pathlib import Path
from typing import Any

from friday.config import disabled_tool_modules, tool_module_enabled
from friday.logger import logger


_LAST_REGISTRATION_REPORT: dict[str, Any] = {
    "attempted": False,
    "discovered_modules": [],
    "enabled_modules": [],
    "disabled_modules": [],
    "registered_modules": [],
    "failed_modules": {},
    "ready": False,
    "issues": [],
}


def _file_declares_register(file_path: Path) -> bool:
    try:
        contents = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "def register(" in contents


def _tool_module_paths() -> list[Path]:
    tools_dir = Path(__file__).parent
    return [
        file_path
        for file_path in sorted(tools_dir.glob("*.py"))
        if (
            file_path.name != "__init__.py"
            and not file_path.name.startswith(".")
            and _file_declares_register(file_path)
        )
    ]


def _new_registration_report() -> dict[str, Any]:
    discovered_modules = [file_path.stem for file_path in _tool_module_paths()]
    disabled_modules = sorted(disabled_tool_modules())
    enabled_modules = [
        module_name for module_name in discovered_modules if tool_module_enabled(module_name)
    ]
    return {
        "attempted": False,
        "discovered_modules": discovered_modules,
        "enabled_modules": enabled_modules,
        "disabled_modules": disabled_modules,
        "registered_modules": [],
        "failed_modules": {},
        "ready": False,
        "issues": [],
    }


def _format_registration_error(exc: BaseException) -> str:
    detail = str(exc).strip()
    if detail:
        message = f"{type(exc).__name__}: {detail}"
    else:
        message = type(exc).__name__
    return message[:240]


def _finalize_registration_report(report: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []

    if not report["enabled_modules"]:
        issues.append("No enabled tool modules were discovered.")

    for module_name, error in sorted(report["failed_modules"].items()):
        issues.append(f"{module_name}: {error}")

    report["ready"] = bool(report["registered_modules"]) and not report["failed_modules"]
    report["issues"] = issues
    return report


def get_tool_registration_report() -> dict[str, Any]:
    """Return the most recent actual tool-registration outcome."""
    return copy.deepcopy(_LAST_REGISTRATION_REPORT)


def preview_tool_registration_report() -> dict[str, Any]:
    """
    Inspect tool modules without mutating the live registration report.

    This gives `/status` and startup diagnostics a best-effort view even when
    the server has not finished registering tools yet.
    """
    report = _new_registration_report()

    for module_name in report["enabled_modules"]:
        import_name = f"friday.tools.{module_name}"
        try:
            module = importlib.import_module(import_name)
        except Exception as exc:
            report["failed_modules"][module_name] = _format_registration_error(exc)
            continue

        if hasattr(module, "register"):
            report["registered_modules"].append(module_name)
        else:
            report["failed_modules"][module_name] = "Module does not define register(mcp)."

    return _finalize_registration_report(report)


def register_all_tools(mcp) -> None:
    """Dynamically register enabled tool groups onto the MCP server instance."""
    global _LAST_REGISTRATION_REPORT

    report = _new_registration_report()
    disabled = report["disabled_modules"]

    if disabled:
        logger.info(
            "Skipping disabled tool modules: "
            + ", ".join(sorted(f"friday.tools.{name}" for name in disabled))
        )

    for file_path in _tool_module_paths():
        module_stem = file_path.stem
        if not tool_module_enabled(module_stem):
            logger.debug(f"Skipped tool module friday.tools.{module_stem}")
            continue

        module_name = f"friday.tools.{module_stem}"
        try:
            module = importlib.import_module(module_name)
            if not hasattr(module, "register"):
                report["failed_modules"][module_stem] = "Module does not define register(mcp)."
                logger.error(f"Tool module {module_name} is missing register(mcp)")
                continue

            module.register(mcp)
            report["registered_modules"].append(module_stem)
            logger.debug(f"Registered tools from {module_name}")
        except Exception as exc:
            report["failed_modules"][module_stem] = _format_registration_error(exc)
            logger.error(f"Failed to load tool module {module_name}: {exc}")

    report["attempted"] = True
    _LAST_REGISTRATION_REPORT = _finalize_registration_report(report)
