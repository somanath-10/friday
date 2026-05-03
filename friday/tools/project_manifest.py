"""MCP tools for inspecting FRIDAY's project manifest."""

from __future__ import annotations

import json

from friday.project_manifest import (
    architecture_snapshot,
    load_project_manifest,
    project_capability_table,
    validate_project_manifest,
)
from friday.tools import get_tool_capability_manifest


def register(mcp):
    @mcp.tool()
    def get_project_manifest() -> str:
        """Return the machine-readable FRIDAY project manifest."""
        manifest = load_project_manifest()
        validation = validate_project_manifest(manifest)
        payload = {
            "manifest": manifest,
            "validation": {
                "ok": validation.ok,
                "issues": validation.issues,
            },
        }
        return json.dumps(payload, indent=2)

    @mcp.tool()
    def get_project_capabilities() -> str:
        """Return FRIDAY capability ownership and risk metadata."""
        rows = project_capability_table()
        lines = ["FRIDAY capabilities:"]
        for row in rows:
            lines.append(f"- {row['id']} ({row['risk']}): {row['roots']}")
        return "\n".join(lines)

    @mcp.tool()
    def get_architecture_snapshot() -> str:
        """Return a compact architecture and trust-boundary snapshot."""
        return json.dumps(architecture_snapshot(), indent=2)

    @mcp.tool()
    def get_tool_manifest() -> str:
        """Return loaded tool modules grouped by capability, risk, and approval posture."""
        return json.dumps(get_tool_capability_manifest(), indent=2)
