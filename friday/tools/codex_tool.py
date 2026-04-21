"""
Codex relay tools.

These tools let FRIDAY inspect the configured project target and dispatch a
prompt into the OpenAI Codex VS Code extension.
"""

from __future__ import annotations

import json

from friday.codex_bridge import (
    build_project_snapshot,
    codex_relay_status,
    compose_codex_prompt,
    dispatch_to_vscode_codex,
)


def register(mcp):

    @mcp.tool()
    def get_codex_relay_status(project_path: str = "") -> str:
        """
        Inspect whether VS Code Codex relay mode is ready on this machine.
        Use this before voice-to-Codex automation, or when the user asks whether
        FRIDAY can send a prompt into the VS Code Codex extension.
        """
        return json.dumps(codex_relay_status(project_path), indent=2)

    @mcp.tool()
    def build_codex_project_brief(project_path: str = "") -> str:
        """
        Build a compact local project brief for the folder FRIDAY will target in VS Code.
        Use this when the user wants Codex to first understand the current project.
        """
        snapshot = build_project_snapshot(project_path)
        return snapshot.summary

    @mcp.tool()
    def preview_codex_prompt(user_request: str, project_path: str = "", include_project_snapshot: bool = True) -> str:
        """
        Compose the exact prompt FRIDAY would send to the VS Code Codex extension.
        Useful for debugging or reviewing the generated project-aware request first.
        """
        payload = compose_codex_prompt(
            user_request,
            project_path=project_path,
            include_project_snapshot=include_project_snapshot,
        )
        return payload["prompt"]

    @mcp.tool()
    def dispatch_to_codex_in_vscode(
        user_request: str,
        project_path: str = "",
        include_project_snapshot: bool = True,
        press_enter: bool = True,
    ) -> str:
        """
        Open or focus VS Code, open the Codex sidebar, start a new thread, and paste the request.
        The request can optionally include a FRIDAY-generated project snapshot beforehand.
        """
        result = dispatch_to_vscode_codex(
            user_request,
            project_path=project_path,
            include_project_snapshot=include_project_snapshot,
            press_enter=press_enter,
        )
        return json.dumps(result, indent=2)
