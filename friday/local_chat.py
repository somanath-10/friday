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
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any

import httpx
from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.sse import sse_client

from friday.config import local_browser_setup_issues
from friday.core.executor import resume_approved_structured_command, run_structured_command
from friday.safety.approval_gate import list_pending_approvals, resolve_pending_approval
from friday.tools.memory import record_conversation_turn, store_action_trace


logger = logging.getLogger("friday.local_chat")

load_dotenv()

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"
MAX_TOOL_ROUNDS = int(os.getenv("FRIDAY_LOCAL_MAX_TOOL_ROUNDS", "14"))
MAX_HISTORY_MESSAGES = int(os.getenv("FRIDAY_LOCAL_MAX_HISTORY_MESSAGES", "18"))
MAX_TOOL_OUTPUT_CHARS = int(os.getenv("FRIDAY_LOCAL_MAX_TOOL_OUTPUT_CHARS", "6000"))
MAX_OPENAI_TOOLS = int(os.getenv("FRIDAY_LOCAL_MAX_OPENAI_TOOLS", "72"))
TOOL_DESCRIPTOR_CACHE_SECONDS = int(os.getenv("FRIDAY_LOCAL_TOOL_CACHE_SECONDS", "300"))
RECOVERY_HINT_CONTEXT_CHARS = int(os.getenv("FRIDAY_LOCAL_RECOVERY_HINT_CONTEXT_CHARS", "1600"))
EXCLUDED_TOOLS = {"voice_filler"}
DEFAULT_BROWSER_STT_MODEL = "gpt-4o-mini-transcribe"
FALLBACK_BROWSER_STT_MODEL = "whisper-1"
CORE_OPENAI_TOOLS = {
    "browser_click_index",
    "browser_click_text",
    "browser_get_state",
    "browser_navigate",
    "browser_read_page",
    "browser_type_index",
    "create_folder",
    "execute_python_code",
    "execute_shell_command",
    "fetch_url",
    "get_file_contents",
    "get_host_control_status",
    "get_running_apps",
    "get_special_paths",
    "gui_click",
    "inspect_desktop_screen",
    "list_directory_tree",
    "list_installed_apps",
    "list_open_windows",
    "locate_screen_target",
    "open_application",
    "open_url",
    "open_elevated_terminal",
    "open_in_finder",
    "open_path",
    "open_terminal",
    "open_terminal_and_type",
    "press_key",
    "read_file_snippet",
    "run_shell_command",
    "search_paths_by_name",
    "search_local_apps",
    "search_web",
    "type_text",
    "write_file",
}
TERMINAL_TOOL_NAMES = {
    "execute_shell_command",
    "open_elevated_terminal",
    "open_terminal",
    "open_terminal_and_type",
    "run_shell_command",
}
DESKTOP_TOOL_NAMES = {
    "focus_application",
    "get_running_apps",
    "gui_click",
    "inspect_desktop_screen",
    "list_installed_apps",
    "list_open_windows",
    "locate_screen_target",
    "open_application",
    "search_local_apps",
    "take_screenshot",
    "type_text",
    "press_key",
}
BROWSER_TOOL_NAMES = {
    "browser_click",
    "browser_click_index",
    "browser_click_text",
    "browser_get_state",
    "browser_navigate",
    "browser_press_key",
    "browser_read_page",
    "browser_scroll",
    "browser_type",
    "browser_type_index",
    "browser_wait_for_text",
}
TOOL_FAILURE_PREFIXES = (
    "tool error",
    "error ",
    "error:",
    "command failed",
    "command execution timed out",
    "could not ",
    "couldn't ",
    "failed ",
    "failure:",
    "no command provided",
    "no target description provided",
    "unable to ",
)
TOOL_FAILURE_MARKERS = (
    '"found": false',
    "access is denied",
    "could not be confirmed",
    "does not exist",
    "not found within",
    "permission denied",
    "timed out after",
)
_TOOL_DESCRIPTOR_CACHE: dict[str, tuple[float, tuple["ToolDescriptor", ...]]] = {}
APPROVAL_ALLOW_PHRASES = {
    "allow",
    "approve",
    "approved",
    "continue",
    "do it",
    "go ahead",
    "ok do it",
    "okay do it",
    "proceed",
    "yes",
    "yes approve",
}
APPROVAL_DENY_PHRASES = {
    "cancel",
    "deny",
    "denied",
    "do not",
    "don't",
    "dont",
    "no",
    "no stop",
    "reject",
    "stop",
}


@dataclass
class LocalChatResult:
    reply: str
    tool_events: list[dict[str, Any]]
    pipeline_events: list[dict[str, Any]] = field(default_factory=list)
    approval_requests: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class BrowserOpenShortcut:
    url: str
    reply: str


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    description: str
    input_schema: dict[str, Any] | None


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
    return local_browser_setup_issues()


def local_mode_ready() -> bool:
    return not local_mode_issues()


def _browser_system_prompt() -> str:
    base = _load_system_prompt()
    extra = (
        "You are speaking through FRIDAY's local browser page. "
        "Keep responses concise because the browser may read them aloud. "
        "Use tools whenever an action touches the computer or filesystem. "
        "When the boss asks for a folder, project, repo, or file by name and no exact path is given, use search_paths_by_name before saying it was not found. "
        "Do not assume a project is only on Desktop. Search common user roots like Desktop, Documents, Downloads, workspace, and home first. "
        "When the boss asks to open a public website, search page, or online video in the real browser, prefer open_url with a direct destination URL. "
        "For YouTube requests, open either the exact video URL or a YouTube search-results URL that matches the request, then confirm it opened. "
        "Never claim success unless a tool result confirms it. "
        "If a terminal command, browser step, or desktop action fails, keep working until you either recover with follow-up tools or hit a real blocker. "
        "If you use open_terminal_and_type, remember that it only confirms the command was typed, not that it succeeded, so verify important outcomes with shell-output or screen-inspection tools. "
        "If a visible app, dialog, or desktop state may be blocking progress, inspect the live screen before retrying. "
        "Only stop and ask the boss when you need credentials, permission, or a decision."
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


def _latest_user_message(messages: list[dict[str, str]]) -> str:
    for item in reversed(messages):
        if item.get("role") == "user":
            return item.get("content", "")
    return ""


def _normalize_decision_text(message: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9\s]+", " ", message.lower()).split())


def _approval_decision_from_message(message: str) -> str | None:
    normalized = _normalize_decision_text(message)
    if not normalized:
        return None

    if normalized in APPROVAL_ALLOW_PHRASES:
        return "approved"
    if normalized in APPROVAL_DENY_PHRASES:
        return "denied"

    tokens = normalized.split()
    if len(tokens) <= 8:
        first = tokens[0]
        if first in {"approve", "approved", "allow", "continue", "proceed", "yes"}:
            return "approved"
        if first in {"deny", "denied", "reject", "cancel", "stop", "no"}:
            return "denied"
    return None


def _approval_mode_from_message(message: str) -> str:
    normalized = _normalize_decision_text(message)
    if any(phrase in normalized for phrase in ("this session", "for session", "session approval", "similar actions")):
        return "session_limited"
    return "one_time"


def _approval_text(record: dict[str, Any]) -> str:
    request = record.get("request", {}) if isinstance(record, dict) else {}
    parts = [
        str(record.get("approval_id", "")),
        str(request.get("action_summary", "")),
        str(request.get("tool", "")),
        str(request.get("command", "")),
        str(request.get("path", "")),
        str(request.get("domain", "")),
        str(request.get("subject", "")),
    ]
    return " ".join(part for part in parts if part).lower()


def _match_pending_approval(message: str, pending: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not pending:
        return None
    if len(pending) == 1:
        return pending[0]

    normalized = _normalize_decision_text(message)
    if not normalized or normalized in APPROVAL_ALLOW_PHRASES or normalized in APPROVAL_DENY_PHRASES:
        return None

    best_record: dict[str, Any] | None = None
    best_score = 0
    tokens = [token for token in normalized.split() if len(token) > 2]
    for record in pending:
        haystack = _approval_text(record)
        score = sum(1 for token in tokens if token in haystack)
        if score > best_score:
            best_score = score
            best_record = record
        elif score == best_score and score > 0:
            best_record = None
    return best_record if best_score > 0 else None


def _pending_approval_disambiguation(pending: list[dict[str, Any]]) -> str:
    lines = ["I have multiple approvals waiting. Say 'approve' with the action name, for example:"]
    for record in pending[:3]:
        request = record.get("request", {}) if isinstance(record, dict) else {}
        summary = str(request.get("action_summary") or request.get("tool") or record.get("approval_id", "pending action"))
        lines.append(f"- approve {summary}")
    return "\n".join(lines)


async def _handle_pending_approval_reply(
    latest_user_message: str,
    mcp_url: str,
) -> tuple[LocalChatResult, str] | None:
    decision = _approval_decision_from_message(latest_user_message)
    if decision is None:
        return None

    pending = list_pending_approvals()
    if not pending:
        return LocalChatResult(
            reply="There is no pending approval waiting right now.",
            tool_events=[],
        ), "completed"

    target = _match_pending_approval(latest_user_message, pending)
    if target is None:
        if len(pending) == 1:
            target = pending[0]
        else:
            return LocalChatResult(reply=_pending_approval_disambiguation(pending), tool_events=[]), "approval_required"

    approval_id = str(target.get("approval_id", "")).strip()
    if not approval_id:
        return LocalChatResult(reply="I could not resolve that approval request.", tool_events=[]), "failed"

    mode = _approval_mode_from_message(latest_user_message)
    resolved = resolve_pending_approval(approval_id, decision, approval_mode=mode)
    if resolved is None:
        return LocalChatResult(reply="That approval request is no longer available.", tool_events=[]), "failed"

    request = resolved.get("request", {}) if isinstance(resolved, dict) else {}
    summary = str(request.get("action_summary") or request.get("tool") or approval_id)
    if decision == "denied":
        return LocalChatResult(
            reply=f"Understood. I did not run: {summary}",
            tool_events=[],
        ), "cancelled"

    resumed = await resume_approved_local_action(approval_id, mcp_url)
    if mode == "session_limited" and resumed.reply:
        resumed.reply = f"Session approval recorded for this category.\n\n{resumed.reply}"
    status = "completed"
    lowered_reply = resumed.reply.lower()
    if "not been approved" in lowered_reply or "failed" in lowered_reply:
        status = "failed"
    if resumed.approval_requests:
        status = "approval_required"
    return resumed, status


def _real_browser_opening_hint(latest_user_message: str) -> str | None:
    lowered = latest_user_message.strip().lower()
    if not lowered:
        return None

    action_markers = (
        "open ",
        "go to ",
        "take me to ",
        "show me ",
        "watch ",
        "play ",
    )
    target_markers = (
        "youtube",
        "video",
        "website",
        "site",
        "browser",
        "url",
        "link",
        "google",
        "gmail",
        "drive",
        "maps",
        "web",
    )
    if not any(marker in lowered for marker in action_markers):
        return None
    if not any(marker in lowered for marker in target_markers):
        return None

    return (
        "The latest request sounds like it should open something in the user's visible web browser. "
        "Prefer open_url for that. "
        "If the request is for YouTube or another site search, construct the destination URL directly and open it, "
        "then confirm the browser-opening tool succeeded."
    )


def _direct_browser_open_shortcut(latest_user_message: str) -> BrowserOpenShortcut | None:
    lowered = " ".join(latest_user_message.strip().lower().split())
    if not lowered:
        return None

    lowered = re.sub(r"^(?:hey\s+)?friday[, ]+", "", lowered)
    action_pattern = r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?(?:open|play|watch|show(?:\s+me)?)\s+"
    if not re.match(action_pattern, lowered):
        return None

    if any(
        marker in lowered
        for marker in (
            " folder",
            " file",
            " desktop",
            " documents",
            " downloads",
            " workspace",
            ".mp4",
            ".mkv",
            ".mov",
            ".avi",
            ".webm",
        )
    ):
        return None

    wants_youtube = any(
        marker in lowered
        for marker in (
            "youtube",
            " video",
            " videos",
            " song",
            " songs",
            " music",
            " trailer",
            " clip",
            " short",
            " shorts",
        )
    )
    if not wants_youtube:
        return None

    query = re.sub(action_pattern, "", lowered)
    query = re.sub(r"\b(?:on|in|from)\s+youtube\b", " ", query)
    query = re.sub(r"\byoutube\b", " ", query)
    query = re.sub(r"\s+", " ", query).strip(" .,!?-")

    while True:
        trimmed = re.sub(
            r"(?:\b(?:video|videos|song|songs|music|trailer|clip|short|shorts)\b[\s.,!?-]*)$",
            "",
            query,
        ).strip(" .,!?-")
        if trimmed == query:
            break
        query = trimmed

    if not query:
        return None

    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
    return BrowserOpenShortcut(
        url=url,
        reply=f"Opened YouTube results for '{query}' in your browser.",
    )


def _tool_name(tool: Any) -> str:
    return str(getattr(tool, "name", "")).strip()


def _tool_description(tool: Any) -> str:
    return str(getattr(tool, "description", "") or "").strip()


def _tool_schema(tool: Any) -> dict[str, Any] | None:
    schema = getattr(tool, "inputSchema", None)
    if schema is None:
        schema = getattr(tool, "input_schema", None)
    return schema


def _tool_cache_key(mcp_url: str) -> str:
    return mcp_url.strip().lower()


def _cached_tool_descriptors(mcp_url: str) -> list[ToolDescriptor] | None:
    cache_key = _tool_cache_key(mcp_url)
    cached = _TOOL_DESCRIPTOR_CACHE.get(cache_key)
    if not cached:
        return None

    cached_at, tools = cached
    if time.monotonic() - cached_at > TOOL_DESCRIPTOR_CACHE_SECONDS:
        _TOOL_DESCRIPTOR_CACHE.pop(cache_key, None)
        return None

    return list(tools)


async def _load_tool_descriptors(session: ClientSession, mcp_url: str) -> list[ToolDescriptor]:
    cached = _cached_tool_descriptors(mcp_url)
    if cached is not None:
        return cached

    listed_tools = await session.list_tools()
    descriptors = [
        ToolDescriptor(
            name=_tool_name(tool),
            description=_tool_description(tool),
            input_schema=_tool_schema(tool),
        )
        for tool in listed_tools.tools
    ]
    _TOOL_DESCRIPTOR_CACHE[_tool_cache_key(mcp_url)] = (
        time.monotonic(),
        tuple(descriptors),
    )
    return descriptors


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
    tool_name = _tool_name(tool)
    description = _tool_description(tool)
    if not description:
        description = f"Run the {tool_name} tool."

    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": description,
            "parameters": _normalize_schema(_tool_schema(tool)),
        },
    }


def _tool_match_tokens(text: str) -> set[str]:
    return {match.group(0) for match in re.finditer(r"[a-z0-9]{3,}", text.lower())}


def _select_openai_tools(tools: list[Any], latest_user_message: str) -> list[dict[str, Any]]:
    available_tools = [tool for tool in tools if _tool_name(tool) not in EXCLUDED_TOOLS]
    if len(available_tools) <= MAX_OPENAI_TOOLS:
        return [_tool_to_openai(tool) for tool in available_tools]

    always_included = [tool for tool in available_tools if _tool_name(tool) in CORE_OPENAI_TOOLS]
    always_included_names = {_tool_name(tool) for tool in always_included}
    if len(always_included) >= MAX_OPENAI_TOOLS:
        selected_tools = always_included[:MAX_OPENAI_TOOLS]
        return [_tool_to_openai(tool) for tool in selected_tools]

    candidate_tools = [tool for tool in available_tools if _tool_name(tool) not in always_included_names]
    remaining_slots = MAX_OPENAI_TOOLS - len(always_included)
    tokens = _tool_match_tokens(latest_user_message)
    if not tokens:
        selected_tools = always_included + candidate_tools[:remaining_slots]
    else:
        scored_tools: list[tuple[int, int, Any]] = []
        for index, tool in enumerate(candidate_tools):
            name = _tool_name(tool).lower()
            description = _tool_description(tool).lower()
            haystack = f"{name} {description}"
            score = 0

            for token in tokens:
                if token in name:
                    score += 4
                elif token in haystack:
                    score += 1

            scored_tools.append((score, index, tool))

        scored_tools.sort(key=lambda item: (-item[0], item[1]))
        selected_tools = always_included + [tool for _, _, tool in scored_tools[:remaining_slots]]

    dropped_tools = [_tool_name(tool) for tool in available_tools if tool not in selected_tools]
    logger.info(
        "Trimmed local chat tool list from %s to %s. Kept %s core tools. Dropped tools: %s",
        len(available_tools),
        len(selected_tools),
        len(always_included),
        ", ".join(dropped_tools[:16]) + (" ..." if len(dropped_tools) > 16 else ""),
    )
    return [_tool_to_openai(tool) for tool in selected_tools]


def _first_non_empty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _tool_output_indicates_failure(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False

    first_line = _first_non_empty_line(lowered)
    if any(first_line.startswith(prefix) for prefix in TOOL_FAILURE_PREFIXES):
        return True

    return any(marker in lowered for marker in TOOL_FAILURE_MARKERS)


def _iter_result_texts(value: Any) -> list[str]:
    texts: list[str] = []

    if value is None:
        return texts
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            texts.append(stripped)
        return texts
    if isinstance(value, dict):
        for item in value.values():
            texts.extend(_iter_result_texts(item))
        return texts
    if isinstance(value, (list, tuple, set)):
        for item in value:
            texts.extend(_iter_result_texts(item))
        return texts

    text = getattr(value, "text", None)
    if isinstance(text, str) and text.strip():
        texts.append(text.strip())
    return texts


def _tool_call_failed(result: Any, rendered_result: str) -> bool:
    if getattr(result, "isError", False):
        return True

    if _tool_output_indicates_failure(rendered_result):
        return True

    candidates = _iter_result_texts(getattr(result, "structuredContent", None))
    candidates.extend(_iter_result_texts(getattr(result, "content", None)))
    return any(_tool_output_indicates_failure(text) for text in candidates)


def _tool_failure_recovery_message(tool_name: str, rendered_result: str) -> str:
    normalized_name = tool_name.strip().lower()
    lowered_result = rendered_result.lower()

    lines = [
        "A recent tool result shows a failure or blocked state.",
        "Stay in tool mode and try to recover before ending the turn.",
    ]

    if normalized_name in TERMINAL_TOOL_NAMES:
        lines.append(
            "If this involved a visible terminal or typed command, capture the exact failure and correct it. "
            "Remember that open_terminal_and_type only proves the command was typed. "
            "Use run_shell_command or execute_shell_command for exact output, and inspect_desktop_screen if a visible terminal window or popup may be blocking the task."
        )
    elif normalized_name in DESKTOP_TOOL_NAMES:
        lines.append(
            "If this was a desktop or app issue, inspect the live screen before retrying. "
            "Use inspect_desktop_screen to look for dialogs or errors, locate_screen_target before gui_click when coordinates are unclear, "
            "and search_local_apps or list_installed_apps if the app may not have opened."
        )
    elif normalized_name in BROWSER_TOOL_NAMES:
        lines.append(
            "If this was a browser issue, re-check the current page with browser_get_state and prefer browser_click_index or browser_type_index instead of guessing."
        )
    else:
        lines.append(
            "Inspect the real machine state, choose the next best tool-based fallback, and retry if the goal is still achievable."
        )

    if any(
        marker in lowered_result
        for marker in ("access is denied", "administrator", "permission denied", "elevated")
    ):
        lines.append(
            "Permissions may be the blocker. Use get_host_control_status to confirm, and use open_elevated_terminal if the boss wants an administrator shell."
        )

    lines.append("Only ask the boss for help if you need credentials, permission, or a decision.")
    lines.append("Recent tool result:\n" + _truncate(rendered_result, RECOVERY_HINT_CONTEXT_CHARS))
    return "\n\n".join(lines)


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

    if _tool_call_failed(result, rendered):
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


async def transcribe_browser_audio(
    audio_bytes: bytes,
    *,
    filename: str = "friday-mic.webm",
    content_type: str = "audio/webm",
) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing.")
    if not audio_bytes:
        raise RuntimeError("No audio was received for transcription.")

    model = os.getenv("FRIDAY_BROWSER_STT_MODEL", DEFAULT_BROWSER_STT_MODEL).strip() or DEFAULT_BROWSER_STT_MODEL
    language = os.getenv("FRIDAY_BROWSER_STT_LANGUAGE", "en").strip()
    prompt = os.getenv(
        "FRIDAY_BROWSER_STT_PROMPT",
        (
            "Transcribe spoken English accurately. Preserve technical terms and product names exactly, "
            "including FRIDAY, Codex, VS Code, OpenAI, Python, Playwright, PowerShell, Windows, MCP, "
            "FastMCP, GitHub, file paths, and command-line words."
        ),
    ).strip()

    headers = {
        "Authorization": f"Bearer {api_key}",
    }
    candidate_models: list[str] = [model]
    if model != FALLBACK_BROWSER_STT_MODEL:
        candidate_models.append(FALLBACK_BROWSER_STT_MODEL)

    timeout = httpx.Timeout(90.0, connect=15.0)
    last_error: RuntimeError | None = None

    for candidate_model in candidate_models:
        data: dict[str, Any] = {
            "model": candidate_model,
            "response_format": "json",
            "temperature": "0",
        }
        if language:
            data["language"] = language
        if prompt:
            data["prompt"] = prompt

        files = {
            "file": (filename or "friday-mic.webm", audio_bytes, content_type or "audio/webm"),
        }

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                OPENAI_TRANSCRIBE_URL,
                headers=headers,
                data=data,
                files=files,
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip()
            last_error = RuntimeError(f"Audio transcription failed: {detail}")
            detail_lower = detail.lower()
            fallback_allowed = candidate_model != FALLBACK_BROWSER_STT_MODEL and any(
                marker in detail_lower
                for marker in (
                    "model",
                    "unsupported",
                    "not found",
                    "access",
                    "does not exist",
                )
            )
            if fallback_allowed:
                logger.warning(
                    "Browser transcription model %s failed; retrying with %s",
                    candidate_model,
                    FALLBACK_BROWSER_STT_MODEL,
                )
                continue
            raise last_error from exc

        response_type = response.headers.get("content-type", "").lower()
        if "application/json" in response_type:
            payload = response.json()
            text = str(payload.get("text", "")).strip()
        else:
            text = response.text.strip()

        if text:
            return text

        last_error = RuntimeError("The transcription service returned an empty result.")

    raise last_error or RuntimeError("Audio transcription failed.")


def _structured_pipeline_enabled() -> bool:
    value = os.getenv("FRIDAY_ENABLE_STRUCTURED_PIPELINE", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


async def _invoke_rendered_tool(
    session: ClientSession,
    tool_name: str,
    params: dict[str, object],
) -> str:
    result = await session.call_tool(tool_name, params)
    return _render_tool_result(result)


async def run_local_chat(messages: list[dict[str, Any]], mcp_url: str) -> LocalChatResult:
    history = _sanitize_history(messages)
    latest_user_message = _latest_user_message(history)
    approval_response = await _handle_pending_approval_reply(latest_user_message, mcp_url)
    if approval_response is not None:
        approval_result, status = approval_response
        try:
            await record_conversation_turn(
                user_message=latest_user_message,
                assistant_reply=approval_result.reply,
                tool_events=approval_result.tool_events,
            )
            await store_action_trace(
                goal=latest_user_message,
                outcome=approval_result.reply,
                tool_events=approval_result.tool_events,
                status=status,
            )
        except Exception:
            logger.exception("Failed to persist approval-response trace")
        return approval_result

    if not local_mode_ready():
        raise RuntimeError("; ".join(local_mode_issues()))

    openai_messages: list[dict[str, Any]] = [{"role": "system", "content": _browser_system_prompt()}]
    openai_messages.extend(history)
    browser_opening_hint = _real_browser_opening_hint(latest_user_message)
    if browser_opening_hint:
        openai_messages.append({"role": "system", "content": browser_opening_hint})
    tool_events: list[dict[str, Any]] = []

    async with sse_client(mcp_url) as streams:
        read_stream, write_stream = streams
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            direct_browser_open = _direct_browser_open_shortcut(latest_user_message)
            if direct_browser_open is not None:
                result = await session.call_tool("open_url", {"url": direct_browser_open.url})
                rendered_result = _render_tool_result(result)
                tool_failed = _tool_call_failed(result, rendered_result)
                tool_events.append(
                    {
                        "name": "open_url",
                        "ok": not tool_failed,
                        "preview": _truncate(rendered_result, 220),
                    }
                )
                if not tool_failed:
                    try:
                        await record_conversation_turn(
                            user_message=latest_user_message,
                            assistant_reply=direct_browser_open.reply,
                            tool_events=tool_events,
                        )
                        await store_action_trace(
                            goal=latest_user_message,
                            outcome=direct_browser_open.reply,
                            tool_events=tool_events,
                            status="completed",
                        )
                    except Exception:
                        logger.exception("Failed to persist local chat trace")
                    return LocalChatResult(reply=direct_browser_open.reply, tool_events=tool_events)

                openai_messages.append(
                    {
                        "role": "system",
                        "content": (
                            "A deterministic browser-opening attempt with open_url failed. "
                            "Recover with tools before ending the turn.\n\n"
                            + _tool_failure_recovery_message("open_url", rendered_result)
                        ),
                    }
                )
            if _structured_pipeline_enabled() and latest_user_message:
                structured_result = await run_structured_command(
                    latest_user_message,
                    lambda tool_name, params: _invoke_rendered_tool(session, tool_name, params),
                )
                if structured_result.handled:
                    tool_events.extend(structured_result.tool_events)
                    status = "completed" if structured_result.success else (
                        "approval_required" if structured_result.permission_pending else "failed"
                    )
                    try:
                        await record_conversation_turn(
                            user_message=latest_user_message,
                            assistant_reply=structured_result.reply,
                            tool_events=tool_events,
                        )
                        await store_action_trace(
                            goal=latest_user_message,
                            outcome=structured_result.reply,
                            tool_events=tool_events,
                            status=status,
                        )
                    except Exception:
                        logger.exception("Failed to persist structured local chat trace")
                    return LocalChatResult(
                        reply=structured_result.reply,
                        tool_events=tool_events,
                        pipeline_events=structured_result.pipeline_events,
                        approval_requests=structured_result.approval_requests,
                    )

            tool_descriptors = await _load_tool_descriptors(session, mcp_url)
            openai_tools = _select_openai_tools(tool_descriptors, latest_user_message)

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
                        tool_failed = _tool_call_failed(result, rendered_result)
                        tool_events.append(
                            {
                                "name": tool_name,
                                "ok": not tool_failed,
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
                        if tool_failed:
                            openai_messages.append(
                                {
                                    "role": "system",
                                    "content": _tool_failure_recovery_message(tool_name, rendered_result),
                                }
                            )
                    continue

                final_reply = str(assistant_content).strip()
                if final_reply:
                    try:
                        await record_conversation_turn(
                            user_message=latest_user_message,
                            assistant_reply=final_reply,
                            tool_events=tool_events,
                        )
                        await store_action_trace(
                            goal=latest_user_message,
                            outcome=final_reply,
                            tool_events=tool_events,
                            status="completed",
                        )
                    except Exception:
                        logger.exception("Failed to persist local chat trace")
                    return LocalChatResult(reply=final_reply, tool_events=tool_events)

                break

    fallback = (
        "I hit a dead end before I had a clean reply. "
        "Try the request again in one smaller step."
    )
    try:
        await record_conversation_turn(
            user_message=latest_user_message,
            assistant_reply=fallback,
            tool_events=tool_events,
        )
        await store_action_trace(
            goal=latest_user_message,
            outcome=fallback,
            tool_events=tool_events,
            status="incomplete",
        )
    except Exception:
        logger.exception("Failed to persist fallback local chat trace")
    return LocalChatResult(reply=fallback, tool_events=tool_events)


async def resume_approved_local_action(approval_id: str, mcp_url: str) -> LocalChatResult:
    """Resume a structured local command after the browser UI approves it."""
    async with sse_client(mcp_url) as streams:
        read_stream, write_stream = streams
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            structured_result = await resume_approved_structured_command(
                approval_id,
                lambda tool_name, params: _invoke_rendered_tool(session, tool_name, params),
            )
            status = "completed" if structured_result.success else (
                "approval_required" if structured_result.permission_pending else "failed"
            )
            try:
                await record_conversation_turn(
                    user_message=f"approval:{approval_id}",
                    assistant_reply=structured_result.reply,
                    tool_events=structured_result.tool_events,
                )
                await store_action_trace(
                    goal=f"approval:{approval_id}",
                    outcome=structured_result.reply,
                    tool_events=structured_result.tool_events,
                    status=status,
                )
            except Exception:
                logger.exception("Failed to persist approval resume trace")
            return LocalChatResult(
                reply=structured_result.reply,
                tool_events=structured_result.tool_events,
                pipeline_events=structured_result.pipeline_events,
                approval_requests=structured_result.approval_requests,
            )
