"""
Tool registry — imports and registers all tool modules with the MCP server.
Add new tool modules here as you build them.
"""

import importlib
from dataclasses import asdict, dataclass
from pathlib import Path

from friday.logger import logger


@dataclass(frozen=True)
class ToolModuleStatus:
    module: str
    enabled: bool
    error: str = ""


_TOOL_MODULE_STATUS: list[ToolModuleStatus] = []


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
                statuses.append(ToolModuleStatus(module=module_name, enabled=True))
                logger.debug(f"Registered tools from {module_name}")
            else:
                statuses.append(
                    ToolModuleStatus(
                        module=module_name,
                        enabled=False,
                        error="Module does not define register(mcp).",
                    )
                )
        except Exception as e:
            statuses.append(ToolModuleStatus(module=module_name, enabled=False, error=str(e)))
            logger.error(f"Failed to load tool module {module_name}: {e}")

    _TOOL_MODULE_STATUS = statuses
    return get_tool_module_status()


def get_tool_module_status() -> list[dict[str, str | bool]]:
    """Return the most recent dynamic tool-registration report."""
    return [asdict(status) for status in _TOOL_MODULE_STATUS]
