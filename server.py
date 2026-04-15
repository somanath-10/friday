"""
Friday MCP Server — Entry Point
Run with: uv run friday
"""

import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from friday.tools import register_all_tools
from friday.prompts import register_all_prompts
from friday.resources import register_all_resources
from friday.config import config

load_dotenv()

# All server identity & bind settings come from env vars
SERVER_NAME         = os.getenv("SERVER_NAME", "Friday")
SERVER_HOST         = os.getenv("MCP_SERVER_HOST", "0.0.0.0")
SERVER_PORT         = int(os.getenv("MCP_SERVER_PORT", "8000"))
SERVER_INSTRUCTIONS = os.getenv(
    "SERVER_INSTRUCTIONS",
    "I am F.R.I.D.A.Y., a Tony Stark-style AI assistant. "
    "I have access to a comprehensive set of tools. "
    "Be concise, accurate, and a little witty."
)

# Create the MCP server instance — fully dynamic
mcp = FastMCP(
    name=SERVER_NAME,
    instructions=SERVER_INSTRUCTIONS,
)

# Register tools, prompts, and resources
register_all_tools(mcp)
register_all_prompts(mcp)
register_all_resources(mcp)


def main():
    mcp.run(transport='sse')


if __name__ == "__main__":
    main()