"""
Tool registry — imports and registers all tool modules with the MCP server.
Add new tool modules here as you build them.
"""

from friday.tools import (
    web,
    system,
    utils,
    planning,
    memory,
    reasoning,
    subagent,
    apps,        # macOS app launcher, screenshot, clipboard, timers, notifications
    weather,     # Real-time weather via Open-Meteo (no API key required)
    files,       # Download files, read PDFs, workspace management
    translate,   # Language translation via MyMemory (no API key required)
    shell,       # Raw shell command execution
)


def register_all_tools(mcp):
    """Register all tool groups onto the MCP server instance."""
    web.register(mcp)
    system.register(mcp)
    utils.register(mcp)
    planning.register(mcp)
    memory.register(mcp)
    reasoning.register(mcp)
    subagent.register(mcp)
    apps.register(mcp)
    weather.register(mcp)
    files.register(mcp)
    translate.register(mcp)
    shell.register(mcp)
