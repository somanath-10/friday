"""
Memory tools — persistent storage for user preferences, context, and conversation history.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from friday.path_utils import memory_dir
from friday.tools.llm_utils import call_llm


class MemoryManager:
    def __init__(self):
        self.memory_dir = memory_dir()
        self.core_identity_file = self.memory_dir / "core_identity.json"
        self.episodic_file = self.memory_dir / "episodic_knowledge.json"
        self.semantic_file = self.memory_dir / "semantic_context.json"
        self.history_file = self.memory_dir / "conversation_history.json"
        self.action_journal_file = self.memory_dir / "action_journal.json"

        for f in [
            self.core_identity_file,
            self.episodic_file,
            self.semantic_file,
            self.history_file,
            self.action_journal_file,
        ]:
            if not f.exists():
                f.write_text(json.dumps({"metadata": {"created": datetime.now().isoformat()}, "data": []}, indent=2))

    def _read(self, file_path: Path) -> dict:
        return json.loads(file_path.read_text())

    def _write(self, file_path: Path, data: dict):
        file_path.write_text(json.dumps(data, indent=2))


mgr = MemoryManager()


async def store_core_fact(fact: str, category: str = "identity") -> str:
    """Store a permanent, core fact about F.R.I.D.A.Y. or the User (e.g. Identity, Core Values)."""
    store = mgr._read(mgr.core_identity_file)
    store["data"].append({
        "fact": fact,
        "category": category,
        "timestamp": datetime.now().isoformat()
    })
    mgr._write(mgr.core_identity_file, store)
    return f"Core fact securely archived in {category}."


async def synthesize_knowledge(task_description: str, outcome: str) -> str:
    """
    Synthesizes a completed task into a 'Knowledge Nugget' for long-term episodic memory.
    This allows F.R.I.D.A.Y. to 'learn' from the success/failure of complex operations.
    """
    system_prompt = (
        "You are F.R.I.D.A.Y.'s Memory Synthesizer. "
        "Convert a task outcome into a concise, semantic 'Knowledge Nugget'. "
        "Focus on: What worked, What failed, and Generalizable patterns. "
        "Output MUST be a JSON object: {\"nugget\": \"...\", \"keywords\": [...], \"confidence\": 0.0-1.0}"
    )
    prompt = f"Task: {task_description}\nOutcome: {outcome}"

    try:
        nugget_json = await call_llm(prompt, system_prompt, json_mode=True)
        nugget_data = json.loads(nugget_json)

        store = mgr._read(mgr.episodic_file)
        store["data"].append({
            "nugget": nugget_data["nugget"],
            "keywords": nugget_data["keywords"],
            "confidence": nugget_data["confidence"],
            "timestamp": datetime.now().isoformat()
        })
        mgr._write(mgr.episodic_file, store)
        return f"New knowledge synthesized: {nugget_data['nugget']}"
    except Exception as e:
        return f"Synthesis failed: {str(e)}"


async def query_agentic_memory(query: str) -> str:
    """
    Perform a semantic query across all memory tiers (Core, Episodic, Semantic) to find relevant context.
    Uses F.R.I.D.A.Y's reasoning engine to find meaning rather than just keywords.
    """
    core = mgr._read(mgr.core_identity_file)["data"]
    episodic = mgr._read(mgr.episodic_file)["data"]
    semantic = mgr._read(mgr.semantic_file)["data"]

    context_dump = json.dumps({
        "core": core[-10:],
        "episodic": episodic[-15:],
        "semantic": semantic[-20:]
    })

    system_prompt = (
        "You are F.R.I.D.A.Y.'s Neural Recall Engine. "
        "Analyze the provided memory dump and answer the user query based ONLY on relevant stored context. "
        "If no relevant info is found, say 'No relevant patterns found in memory.'"
    )
    return await call_llm(f"Query: {query}\n\nMemory Dump: {context_dump}", system_prompt)


async def update_semantic_context(key: str, value: Any) -> str:
    """Update the current semantic state/context of the workspace or user interactions."""
    store = mgr._read(mgr.semantic_file)
    # Store as key-value for quick lookup
    entry = next((item for item in store["data"] if item.get("key") == key), None)
    if entry:
        entry["value"] = value
        entry["timestamp"] = datetime.now().isoformat()
    else:
        store["data"].append({
            "key": key,
            "value": value,
            "timestamp": datetime.now().isoformat()
        })
    mgr._write(mgr.semantic_file, store)
    return f"Semantic context updated: {key}"


async def get_recent_history(limit: int = 10) -> str:
    """Retrieve recent conversation history."""
    try:
        store = mgr._read(mgr.history_file)
        turns = store.get("data", [])[-limit:]
        return json.dumps(turns, indent=2)
    except Exception:
        return "No history found."


async def record_conversation_turn(
    user_message: str,
    assistant_reply: str,
    tool_events: list[dict[str, Any]] | None = None,
) -> str:
    """
    Persist a conversation turn with optional tool activity.
    This gives FRIDAY a durable interaction trail across browser and voice sessions.
    """
    try:
        store = mgr._read(mgr.history_file)
        store.setdefault("data", []).append(
            {
                "user_message": user_message,
                "assistant_reply": assistant_reply,
                "tool_events": tool_events or [],
                "timestamp": datetime.now().isoformat(),
            }
        )
        mgr._write(mgr.history_file, store)
        return "Conversation turn recorded."
    except Exception as e:
        return f"Failed to record conversation turn: {str(e)}"


async def store_action_trace(
    goal: str,
    outcome: str,
    tool_events: list[dict[str, Any]] | None = None,
    status: str = "completed",
) -> str:
    """
    Persist a lightweight action trace for successful or failed desktop/web tasks.
    This mirrors the trajectory logging pattern used by many computer-use projects.
    """
    try:
        store = mgr._read(mgr.action_journal_file)
        store.setdefault("data", []).append(
            {
                "goal": goal,
                "status": status,
                "outcome": outcome,
                "tool_events": tool_events or [],
                "timestamp": datetime.now().isoformat(),
            }
        )
        mgr._write(mgr.action_journal_file, store)
        return "Action trace stored."
    except Exception as e:
        return f"Failed to store action trace: {str(e)}"


async def get_recent_action_traces(limit: int = 10) -> str:
    """Retrieve recent action traces recorded from FRIDAY's tool-driven work."""
    try:
        store = mgr._read(mgr.action_journal_file)
        traces = store.get("data", [])[-limit:]
        return json.dumps(traces, indent=2)
    except Exception:
        return "No action traces found."


def register(mcp):
    mcp.tool()(store_core_fact)
    mcp.tool()(synthesize_knowledge)
    mcp.tool()(query_agentic_memory)
    mcp.tool()(update_semantic_context)
    mcp.tool()(get_recent_history)
    mcp.tool()(record_conversation_turn)
    mcp.tool()(store_action_trace)
    mcp.tool()(get_recent_action_traces)
