"""
Local browser chat bridge for FRIDAY.

This module lets the local web UI talk to the existing MCP tool server without
going through LiveKit. The browser handles microphone input and speech output,
while the backend handles LLM reasoning and tool execution.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.sse import sse_client


logger = logging.getLogger("friday.local_chat")

load_dotenv()

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
MAX_TOOL_ROUNDS = int(os.getenv("FRIDAY_LOCAL_MAX_TOOL_ROUNDS", "8"))
MAX_HISTORY_MESSAGES = int(os.getenv("FRIDAY_LOCAL_MAX_HISTORY_MESSAGES", "18"))
MAX_TOOL_OUTPUT_CHARS = int(os.getenv("FRIDAY_LOCAL_MAX_TOOL_OUTPUT_CHARS", "6000"))
EXCLUDED_TOOLS = {"voice_filler"}


@dataclass
class LocalChatResult:
    reply: str
    tool_events: list[dict[str, Any]]


def _load_system_prompt() -> str:
    prompt_path = os.getenv("FRIDAY_SYSTEM_PROMPT_PATH", "friday/prompts/system_prompt.txt")
    try:
        with open(prompt_path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return "I am F.R.I.D.A.Y., a precise and helpful desktop assistant."


def local_greeting() -> str:
    return os.getenv(
        "FRIDAY_GREETING",
        "Greetings, boss. Local systems are online. What shall we do first?",
    )


def local_mode_issues() -> list[str]:
    issues: list[str] = []
    if os.getenv("LLM_PROVIDER", "openai").strip().lower() != "openai":
        issues.append("Set LLM_PROVIDER=openai for local browser mode.")
    if not os.getenv("OPENAI_API_KEY"):
        issues.append("OPENAI_API_KEY is required for local browser mode.")
    return issues


def local_mode_ready() -> bool:
    return not local_mode_issues()


def _browser_system_prompt() -> str:
    base = _load_system_prompt()
    extra = (
        "You are speaking through FRIDAY's local browser page. "
        "Keep responses concise because the browser may read them aloud. "
        "Use tools whenever an action touches the computer or filesystem. "
        "Never claim success unless a tool result confirms it."
    )
    return f"{base}\n\n{extra}"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 32] + "\n\n... [tool output truncated] ..."


def _sanitize_history(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in messages[-MAX_HISTORY_MESSAGES:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def _normalize_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    if not schema:
        return {"type": "object", "properties": {}}

    normalized = dict(schema)
    if "type" not in normalized:
        normalized["type"] = "object"
    if normalized["type"] == "object" and "properties" not in normalized:
        normalized["properties"] = {}
    return normalized


def _tool_to_openai(tool: Any) -> dict[str, Any]:
    description = (tool.description or "").strip()
    if not description:
        description = f"Run the {tool.name} tool."

    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": description,
            "parameters": _normalize_schema(tool.inputSchema),
        },
    }


def _render_tool_result(result: Any) -> str:
    parts: list[str] = []

    if getattr(result, "structuredContent", None):
        try:
            parts.append(
                json.dumps(result.structuredContent, ensure_ascii=False, indent=2)
            )
        except TypeError:
            parts.append(str(result.structuredContent))

    for block in getattr(result, "content", []) or []:
        block_type = getattr(block, "type", "")
        if block_type == "text":
            parts.append(getattr(block, "text", ""))
        elif block_type == "image":
            parts.append("[image output omitted]")
        elif block_type == "audio":
            parts.append("[audio output omitted]")
        elif block_type == "resource":
            resource = getattr(block, "resource", None)
            uri = getattr(resource, "uri", "") if resource else ""
            parts.append(f"[embedded resource: {uri or 'resource'}]")
        elif block_type == "resource_link":
            parts.append(f"[resource link: {getattr(block, 'uri', '')}]")
        else:
            try:
                dumped = block.model_dump()  # type: ignore[attr-defined]
            except Exception:
                dumped = str(block)
            parts.append(str(dumped))

    rendered = "\n".join(part for part in parts if part).strip()
    if not rendered:
        rendered = "Tool completed with no text output."

    if getattr(result, "isError", False):
        rendered = f"TOOL ERROR\n{rendered}"

    return _truncate(rendered, MAX_TOOL_OUTPUT_CHARS)


async def _openai_completion(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing.")

    payload: dict[str, Any] = {
        "model": os.getenv("OPENAI_LLM_MODEL", "gpt-4o"),
        "messages": messages,
        "temperature": 0.3,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
        payload["parallel_tool_calls"] = False

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    timeout = httpx.Timeout(90.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(OPENAI_CHAT_URL, headers=headers, json=payload)

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text.strip()
        raise RuntimeError(f"OpenAI request failed: {detail}") from exc

    data = response.json()
    try:
        return data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected OpenAI response: {data}") from exc


async def run_local_chat(messages: list[dict[str, Any]], mcp_url: str) -> LocalChatResult:
    if not local_mode_ready():
        raise RuntimeError("; ".join(local_mode_issues()))

    history = _sanitize_history(messages)
    openai_messages: list[dict[str, Any]] = [{"role": "system", "content": _browser_system_prompt()}]
    openai_messages.extend(history)
    tool_events: list[dict[str, Any]] = []

    async with sse_client(mcp_url) as streams:
        read_stream, write_stream = streams
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listed_tools = await session.list_tools()
            openai_tools = [
                _tool_to_openai(tool)
                for tool in listed_tools.tools
                if tool.name not in EXCLUDED_TOOLS
            ]

            for _ in range(MAX_TOOL_ROUNDS):
                assistant_message = await _openai_completion(openai_messages, openai_tools)
                tool_calls = assistant_message.get("tool_calls") or []
                assistant_content = assistant_message.get("content") or ""

                if tool_calls:
                    openai_messages.append(
                        {
                            "role": "assistant",
                            "content": assistant_content,
                            "tool_calls": tool_calls,
                        }
                    )

                    for tool_call in tool_calls:
                        function_info = tool_call.get("function", {})
                        tool_name = function_info.get("name", "")
                        raw_arguments = function_info.get("arguments", "") or "{}"

                        try:
                            parsed_arguments = json.loads(raw_arguments)
                        except json.JSONDecodeError:
                            parsed_arguments = {}

                        result = await session.call_tool(tool_name, parsed_arguments)
                        rendered_result = _render_tool_result(result)
                        tool_events.append(
                            {
                                "name": tool_name,
                                "ok": not result.isError,
                                "preview": _truncate(rendered_result, 220),
                            }
                        )
                        openai_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.get("id", ""),
                                "content": rendered_result,
                            }
                        )
                    continue

                final_reply = str(assistant_content).strip()
                if final_reply:
                    return LocalChatResult(reply=final_reply, tool_events=tool_events)

                break

    fallback = (
        "I hit a dead end before I had a clean reply. "
        "Try the request again in one smaller step."
    )
    return LocalChatResult(reply=fallback, tool_events=tool_events)
