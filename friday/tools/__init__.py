"""
Tool registry — imports and registers all tool modules with the MCP server.
Add new tool modules here as you build them.
"""

import importlib
from pathlib import Path

from friday.logger import logger

def register_all_tools(mcp):
    """Dynamically register all tool groups onto the MCP server instance."""
    tools_dir = Path(__file__).parent

    # Sorting keeps startup deterministic across platforms and filesystems.
    for file_path in sorted(tools_dir.glob("*.py")):
        if file_path.name == "__init__.py" or file_path.name.startswith("."):
            continue

        module_name = f"friday.tools.{file_path.stem}"
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "register"):
                module.register(mcp)
                logger.debug(f"Registered tools from {module_name}")
        except Exception as e:
            logger.error(f"Failed to load tool module {module_name}: {e}")
