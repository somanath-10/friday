"""
Tool registry - imports and registers tool modules with the MCP server.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from friday.config import disabled_tool_modules, tool_module_enabled
from friday.logger import logger


def register_all_tools(mcp) -> None:
    """Dynamically register enabled tool groups onto the MCP server instance."""
    tools_dir = Path(__file__).parent
    disabled = disabled_tool_modules()

    if disabled:
        logger.info(
            "Skipping disabled tool modules: "
            + ", ".join(sorted(f"friday.tools.{name}" for name in disabled))
        )

    # Sorting keeps startup deterministic across platforms and filesystems.
    for file_path in sorted(tools_dir.glob("*.py")):
        if file_path.name == "__init__.py" or file_path.name.startswith("."):
            continue

        module_stem = file_path.stem
        if not tool_module_enabled(module_stem):
            logger.debug(f"Skipped tool module friday.tools.{module_stem}")
            continue

        module_name = f"friday.tools.{module_stem}"
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "register"):
                module.register(mcp)
                logger.debug(f"Registered tools from {module_name}")
        except Exception as exc:
            logger.error(f"Failed to load tool module {module_name}: {exc}")
