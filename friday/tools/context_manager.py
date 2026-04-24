"""
Context Manager — intelligent conversation context trimming and summarisation.

When a long-running session accumulates many conversation turns, this module
provides tools to summarise and compress the history so the LLM context
window never overflows and performance stays sharp.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from friday.path_utils import memory_dir
from friday.logger import logger


class ContextManager:
    """Manages the active session context, providing trim/summarise operations."""

    MAX_TURNS_BEFORE_SUMMARY = 20  # Summarise when history exceeds this

    def __init__(self):
        self._memory_dir = memory_dir()
        self._history_file = self._memory_dir / "conversation_history.json"
        self._summary_file = self._memory_dir / "session_summary.json"

    def _read_history(self) -> list[dict[str, Any]]:
        if not self._history_file.exists():
            return []
        try:
            data = json.loads(self._history_file.read_text())
            return data.get("data", [])
        except Exception:
            return []

    def _write_history(self, turns: list[dict[str, Any]]) -> None:
        self._history_file.write_text(
            json.dumps({"metadata": {"updated": datetime.now().isoformat()}, "data": turns}, indent=2)
        )

    def _read_summary(self) -> str:
        if not self._summary_file.exists():
            return ""
        try:
            data = json.loads(self._summary_file.read_text())
            return data.get("summary", "")
        except Exception:
            return ""

    def _write_summary(self, summary: str) -> None:
        self._summary_file.write_text(
            json.dumps({"summary": summary, "generated_at": datetime.now().isoformat()}, indent=2)
        )

    def get_context_stats(self) -> dict[str, Any]:
        turns = self._read_history()
        summary = self._read_summary()
        total_chars = sum(
            len(t.get("user_message", "")) + len(t.get("assistant_reply", ""))
            for t in turns
        )
        return {
            "turn_count": len(turns),
            "total_characters": total_chars,
            "has_summary": bool(summary),
            "needs_trim": len(turns) > self.MAX_TURNS_BEFORE_SUMMARY,
            "oldest_turn": turns[0].get("timestamp") if turns else None,
            "newest_turn": turns[-1].get("timestamp") if turns else None,
        }

    def trim_to_recent(self, keep_last: int = 10) -> tuple[int, int]:
        """Trim history to last N turns. Returns (removed_count, remaining_count)."""
        turns = self._read_history()
        before = len(turns)
        trimmed = turns[-keep_last:] if len(turns) > keep_last else turns
        self._write_history(trimmed)
        logger.info(f"Context trimmed: {before} → {len(trimmed)} turns")
        return (before - len(trimmed), len(trimmed))

    def build_inline_summary(self, max_turns: int = 30) -> str:
        """Build a plain-text summary of recent turns for injecting into a prompt."""
        turns = self._read_history()[-max_turns:]
        if not turns:
            return "No conversation history."
        lines = ["=== Recent Session Context ==="]
        prior_summary = self._read_summary()
        if prior_summary:
            lines.append(f"[Prior summary] {prior_summary}")
            lines.append("")
        for t in turns:
            ts = t.get("timestamp", "")[:16]
            lines.append(f"[{ts}] User: {t.get('user_message', '')[:200]}")
            lines.append(f"[{ts}] FRIDAY: {t.get('assistant_reply', '')[:200]}")
        return "\n".join(lines)

    def clear_all(self) -> int:
        """Wipe the entire history. Returns number of turns cleared."""
        turns = self._read_history()
        count = len(turns)
        self._write_history([])
        if self._summary_file.exists():
            self._summary_file.unlink()
        logger.info(f"Session context cleared: {count} turns removed")
        return count


_ctx = ContextManager()


def register(mcp):

    @mcp.tool()
    def get_context_stats() -> str:
        """
        Return statistics about the current session context: number of conversation turns,
        total characters, whether a summary exists, and if trimming is needed.
        Use this to understand how large the conversation history has grown.
        """
        stats = _ctx.get_context_stats()
        lines = [
            "=== Session Context Stats ===",
            f"Turns recorded  : {stats['turn_count']}",
            f"Total characters: {stats['total_characters']:,}",
            f"Has prior summary: {'Yes' if stats['has_summary'] else 'No'}",
            f"Needs trimming   : {'Yes — run trim_context' if stats['needs_trim'] else 'No'}",
        ]
        if stats["oldest_turn"]:
            lines.append(f"Oldest turn      : {stats['oldest_turn'][:16]}")
        if stats["newest_turn"]:
            lines.append(f"Newest turn      : {stats['newest_turn'][:16]}")
        return "\n".join(lines)

    @mcp.tool()
    def trim_context(keep_last: int = 10) -> str:
        """
        Trim the conversation history to the most recent N turns.
        Use this when the context is getting very long and you want to free up token budget.
        The oldest turns are removed; the most recent ones are preserved.
        """
        if keep_last < 1:
            return "keep_last must be at least 1."
        removed, remaining = _ctx.trim_to_recent(keep_last=keep_last)
        return f"Context trimmed: removed {removed} old turn(s), kept {remaining} recent turn(s)."

    @mcp.tool()
    def get_session_summary() -> str:
        """
        Retrieve the current inline session summary including recent conversation turns.
        Use this when you need to remind yourself (or the user) what has happened so far in this session.
        """
        return _ctx.build_inline_summary()

    @mcp.tool()
    def save_session_note(note: str) -> str:
        """
        Save a persistent human-readable summary/note about what happened in this session.
        Use this at the end of a complex task to bookmark what was accomplished.
        Example: 'Deployed the Friday server and ran all healthchecks. All 71 tests passed.'
        """
        _ctx._write_summary(note)
        return f"Session note saved ({len(note)} chars)."

    @mcp.tool()
    def clear_session_context() -> str:
        """
        Completely wipe the conversation history and any saved session note.
        Use this when starting a fresh task and you want a clean slate.
        WARNING: This action is irreversible.
        """
        count = _ctx.clear_all()
        return f"Session context cleared. {count} turn(s) removed."
