"""
Tool registry - imports and registers all tool modules with the MCP server.
Add new tool modules here as you build them.
"""

from __future__ import annotations

import importlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from friday.logger import logger
from friday.project_manifest import infer_tool_module_metadata


@dataclass(frozen=True)
class ToolModuleStatus:
    module: str
    enabled: bool
    error: str = ""
    capability: str = "extension"
    capability_name: str = "Local Extension"
    risk: str = "medium"
    summary: str = ""
    requires_approval: bool = False


_TOOL_MODULE_STATUS: list[ToolModuleStatus] = []


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _first_doc_line(module: Any) -> str:
    doc = str(getattr(module, "__doc__", "") or "").strip()
    if not doc:
        return ""
    return next((line.strip() for line in doc.splitlines() if line.strip()), "")


def _module_metadata(module_name: str, module: Any | None = None) -> dict[str, Any]:
    inferred = infer_tool_module_metadata(module_name)
    explicit = getattr(module, "TOOL_METADATA", {}) if module is not None else {}
    if not isinstance(explicit, dict):
        explicit = {}

    risk = str(
        explicit.get("risk")
        or getattr(module, "TOOL_RISK", "")
        or inferred["risk"]
        or "medium"
    )
    capability = str(
        explicit.get("capability")
        or getattr(module, "TOOL_CAPABILITY", "")
        or inferred["capability"]
        or "extension"
    )
    requires_approval = explicit.get(
        "requires_approval",
        getattr(module, "TOOL_REQUIRES_APPROVAL", risk.lower() in {"high", "critical"}),
    )
    return {
        "capability": capability,
        "capability_name": str(
            explicit.get("capability_name")
            or getattr(module, "TOOL_CAPABILITY_NAME", "")
            or inferred["capability_name"]
            or capability.replace("_", " ").title()
        ),
        "risk": risk,
        "summary": str(
            explicit.get("summary")
            or getattr(module, "TOOL_SUMMARY", "")
            or _first_doc_line(module)
            or "Local FRIDAY tool module."
        ),
        "requires_approval": _truthy(requires_approval),
    }


def _status_for(
    module_name: str,
    *,
    enabled: bool,
    error: str = "",
    module: Any | None = None,
) -> ToolModuleStatus:
    metadata = _module_metadata(module_name, module)
    return ToolModuleStatus(
        module=module_name,
        enabled=enabled,
        error=error,
        capability=str(metadata["capability"]),
        capability_name=str(metadata["capability_name"]),
        risk=str(metadata["risk"]),
        summary=str(metadata["summary"]),
        requires_approval=bool(metadata["requires_approval"]),
    )


def register_all_tools(mcp):
    """Dynamically register all tool groups onto the MCP server instance."""
    global _TOOL_MODULE_STATUS

    tools_dir = Path(__file__).parent
    statuses: list[ToolModuleStatus] = []

    # Sorting keeps startup deterministic across platforms and filesystems.
    for file_path in sorted(tools_dir.glob("*.py")):
        if file_path.name == "__init__.py" or file_path.name.startswith("."):
            continue

        module_name = f"friday.tools.{file_path.stem}"
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "register"):
                module.register(mcp)
                statuses.append(_status_for(module_name, enabled=True, module=module))
                logger.debug(f"Registered tools from {module_name}")
            else:
                statuses.append(
                    _status_for(
                        module_name,
                        enabled=False,
                        error="Module does not define register(mcp).",
                        module=module,
                    )
                )
        except Exception as e:
            statuses.append(_status_for(module_name, enabled=False, error=str(e)))
            logger.error(f"Failed to load tool module {module_name}: {e}")

    _TOOL_MODULE_STATUS = statuses
    return get_tool_module_status()


def get_tool_module_status() -> list[dict[str, str | bool]]:
    """Return the most recent dynamic tool-registration report."""
    return [asdict(status) for status in _TOOL_MODULE_STATUS]


def build_tool_capability_manifest(
    module_status: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return an OpenClaw-style capability snapshot for discovered tool modules."""
    statuses = module_status if module_status is not None else get_tool_module_status()
    capabilities: dict[str, dict[str, Any]] = {}
    for item in statuses:
        module_name = str(item.get("module", ""))
        metadata = infer_tool_module_metadata(module_name)
        capability = str(item.get("capability") or metadata["capability"] or "extension")
        bucket = capabilities.setdefault(
            capability,
            {
                "id": capability,
                "name": str(item.get("capability_name") or metadata["capability_name"]),
                "enabled_count": 0,
                "disabled_count": 0,
                "modules": [],
            },
        )
        if item.get("enabled"):
            bucket["enabled_count"] += 1
        else:
            bucket["disabled_count"] += 1
        bucket["modules"].append(
            {
                "module": module_name,
                "enabled": bool(item.get("enabled")),
                "risk": str(item.get("risk") or metadata["risk"]),
                "requires_approval": bool(item.get("requires_approval", False)),
                "summary": str(item.get("summary", "")),
                "error": str(item.get("error", "")),
            }
        )

    ordered = sorted(capabilities.values(), key=lambda entry: entry["id"])
    return {
        "module_count": len(statuses),
        "enabled_count": sum(1 for item in statuses if item.get("enabled")),
        "disabled_count": sum(1 for item in statuses if not item.get("enabled")),
        "capabilities": ordered,
    }


def get_tool_capability_manifest() -> dict[str, Any]:
    """Return capability metadata for the most recently registered tool modules."""
    return build_tool_capability_manifest()
