# FRIDAY Plugin And Tool System

FRIDAY's plugin model is currently a lightweight tool-module contract. It is
not an external package marketplace yet; it is a local extension surface for
adding MCP tools safely and predictably.

## Contract

Each Python file in `friday/tools/` is discovered at startup. Files are loaded in
sorted order for deterministic behavior.

A tool module should expose:

```python
def register(mcp):
    @mcp.tool()
    def tool_name(...):
        """Short user-facing behavior description."""
        ...
```

If a module does not define `register(mcp)`, it is recorded as disabled. If
import or registration raises, the error is recorded and startup continues.

## Metadata

`friday.project.json` is the project-level manifest. It does not replace tool
code; it documents capability ownership, roots, risk level, docs, and quality
gates. This is the FRIDAY equivalent of OpenClaw's metadata-first plugin
orientation.

Use the manifest for:

- architecture and capability discovery
- security review
- docs navigation
- CI/release gate clarity
- future plugin packaging

Do not use it for:

- executing plugin code
- storing secrets
- bypassing permission checks

At startup, the dynamic tool registry now turns every loaded module into a
small metadata record:

- `module`
- `enabled`
- `capability`
- `capability_name`
- `risk`
- `summary`
- `requires_approval`
- `error`

Metadata is inferred from `friday.project.json` roots by default. A tool module
can override it with module-level constants:

```python
TOOL_METADATA = {
    "capability": "filesystem",
    "capability_name": "File Operations",
    "risk": "high",
    "summary": "Reads and writes workspace files.",
    "requires_approval": True,
}
```

The `/status` endpoint exposes a `tool_capabilities` snapshot, and the
`get_tool_manifest` MCP tool returns the same capability grouping for chat,
health checks, or future UI surfaces.

## Adding A Tool

1. Add a focused module under `friday/tools/`.
2. Implement `register(mcp)`.
3. Route risky operations through `friday.core.permissions` or existing safety
   helpers.
4. Add tests for parsing, permission behavior, and success/failure output.
5. Update `docs/TOOLS.md` if it adds user-visible capabilities.
6. Run `uv run pytest tests -q` and `uv run friday_healthcheck`.

## Future Shape

The next natural step is external plugin packaging: a manifest file per plugin,
an offline compatibility inspector, and a fixture suite that verifies tool
contracts before a plugin is trusted by the local assistant.
