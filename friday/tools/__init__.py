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
    subagent,
    apps,        # macOS/Windows/Linux app launcher, screenshot, clipboard, timers, notifications
    weather,     # Real-time weather via Open-Meteo (no API key required)
    files,       # Download files, read PDFs, workspace management
    translate,   # Language translation via MyMemory (no API key required)
    shell,       # Raw shell command execution
    browser,     # Headless Chromium automation via Playwright
    operator,    # Screen-aware desktop inspection and target grounding

    finance,     # Stock prices, crypto, currency conversion (all free)
    git_tool,    # Git operations: status, log, diff, commit, push, pull, clone
    compression, # Zip/unzip archives
    network,     # Ping, IP info, port check, DNS, traceroute
    media,       # Volume control, audio playback
    image_tool,  # AI image generation (Pollinations.ai), resize, convert
    calendar_tool,  # Calendar events (.ics) and reminders
    firecrawl_tool, # SOTA web scraping/research
    codex_tool,  # VS Code Codex relay and project snapshot helpers
    research,    # Custom deep research with visual grid integration
)


def register_all_tools(mcp):
    """Register all tool groups onto the MCP server instance."""
    web.register(mcp)
    system.register(mcp)
    utils.register(mcp)
    planning.register(mcp)
    memory.register(mcp)
    subagent.register(mcp)
    apps.register(mcp)
    weather.register(mcp)
    files.register(mcp)
    translate.register(mcp)
    shell.register(mcp)
    browser.register(mcp)
    operator.register(mcp)

    finance.register(mcp)
    git_tool.register(mcp)
    compression.register(mcp)
    network.register(mcp)
    media.register(mcp)
    image_tool.register(mcp)
    calendar_tool.register(mcp)
    firecrawl_tool.register(mcp)
    codex_tool.register(mcp)
    research.register(mcp)

