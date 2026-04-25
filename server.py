"""
Friday MCP Server — Entry Point
Run with: uv run friday
"""

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from friday.tools import register_all_tools
from friday.prompts import register_all_prompts
from friday.resources import register_all_resources
from friday.config import config
from friday.web_ui import register_web_routes

load_dotenv()

# All server identity & bind settings come from env vars
SERVER_NAME = config.SERVER_NAME
SERVER_HOST = config.SERVER_HOST
SERVER_PORT = config.SERVER_PORT
SERVER_MOUNT_PATH = config.SERVER_MOUNT_PATH
SERVER_SSE_PATH = config.SERVER_SSE_PATH
SERVER_INSTRUCTIONS = config.SERVER_INSTRUCTIONS

# Create the MCP server instance — fully dynamic
mcp = FastMCP(
    name=SERVER_NAME,
    instructions=SERVER_INSTRUCTIONS,
    host=SERVER_HOST,
    port=SERVER_PORT,
    mount_path=SERVER_MOUNT_PATH,
    sse_path=SERVER_SSE_PATH,
    debug=config.DEBUG,
    log_level="DEBUG" if config.DEBUG else "INFO",
)

# Register tools, prompts, and resources
register_all_tools(mcp)
register_all_prompts(mcp)
register_all_resources(mcp)
register_web_routes(mcp)


def main():
    try:
        mcp.run(transport="sse", mount_path=SERVER_MOUNT_PATH)
    except KeyboardInterrupt:
        # FastMCP/anyio turns an interactive Ctrl+C into a final KeyboardInterrupt
        # after cancelling the SSE task. Keep shutdown quiet for local runs.
        pass


if __name__ == "__main__":
    main()
