# FRIDAY Architecture

FRIDAY is a local-first personal assistant. The current product shape is closer
to a compact OpenClaw-style gateway than a single script: one local control
plane, many tool surfaces, a permission layer, and a browser UI.

## Runtime Shape

```text
Browser UI / MCP client
        |
        v
FastMCP SSE server (`server.py`)
        |
        +-- dynamic tool registry (`friday/tools`)
        +-- prompts/resources (`friday/prompts`, `friday/resources`)
        +-- local status and web UI (`friday/web_ui.py`)
        |
        v
Capability modules
  browser | desktop | files | shell | memory | workflows | research | voice
        |
        v
Safety layer
  permissions | approvals | audit log | emergency stop | path guards
```

## Control Plane

`server.py` creates the FastMCP server, registers tools/prompts/resources, and
serves the local browser UI. The server defaults to port `8000` and exposes:

- `/` for the local UI
- `/status` for runtime diagnostics
- `/sse` for MCP transport

`friday.project.json` is the metadata-first map of the system. It describes
entry points, capabilities, security boundaries, docs, and quality gates without
loading every tool module. Once tools are loaded, the registry also publishes a
capability manifest that groups modules by capability, risk, and approval
posture.

## Tool Loading

Tools are loaded dynamically from `friday/tools/*.py`. A module participates by
defining:

```python
def register(mcp):
    @mcp.tool()
    def my_tool(...):
        ...
```

Startup records which modules loaded and which failed. Status surfaces can read
that registry instead of guessing.

## Agent Loop

The browser chat path sends user requests through the local server and exposes a
bounded MCP tool set. The workflow orchestrator can create persistent plans,
record step progress, and preserve recovery context under the configured
workspace.

## State

State is intentionally local:

- workspace files under `FRIDAY_WORKSPACE_DIR` or `workspace/`
- memory under `FRIDAY_MEMORY_DIR` or workspace-backed defaults
- audit and approval state under the safety/memory helpers

## Design Direction

The OpenClaw-inspired direction for FRIDAY is:

- keep local-first defaults
- make every capability discoverable before it is invoked
- keep workflow tools always available to the browser chat loop for complex
  plan/execute/verify tasks
- keep risky surfaces behind permission decisions
- prefer small tool modules with clear ownership
- keep healthcheck and tests as the release gate
