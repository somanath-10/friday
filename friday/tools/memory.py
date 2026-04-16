"""
Memory tools — persistent storage for user preferences, context, and conversation history.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from friday.path_utils import memory_dir


class MemoryManager:
    def __init__(self):
        self.memory_dir = memory_dir()
        self.user_profile_file = self.memory_dir / "user_profile.json"
        self.conversation_file = self.memory_dir / "conversation_history.json"
        self.context_file = self.memory_dir / "current_context.json"
        self.core_memory_file = self.memory_dir / "core_memory.json"

        # Initialize files if they don't exist
        for file_path in [self.user_profile_file, self.conversation_file, self.context_file, self.core_memory_file]:
            if not file_path.exists():
                file_path.write_text(json.dumps({}, indent=2))

    def _read_json(self, file_path: Path) -> Dict[str, Any]:
        try:
            return json.loads(file_path.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _write_json(self, file_path: Path, data: Dict[str, Any]):
        file_path.write_text(json.dumps(data, indent=2, default=str))


def register(mcp):
    memory_manager = MemoryManager()

    @mcp.tool()
    async def remember_user_preference(key: str, value: str) -> str:
        """
        Store a user preference for future reference.
        Use this to remember how the user likes things done, their preferences, or important facts about them.
        """
        try:
            profile = memory_manager._read_json(memory_manager.user_profile_file)
            profile[key] = {
                "value": value,
                "timestamp": datetime.now().isoformat()
            }
            memory_manager._write_json(memory_manager.user_profile_file, profile)
            return f"Remembered user preference: {key} = {value}"
        except Exception as e:
            return f"Error remembering user preference: {str(e)}"

    @mcp.tool()
    async def recall_user_preference(key: str) -> str:
        """
        Retrieve a previously stored user preference.
        Use this to remember how the user likes things done or important facts about them.
        """
        try:
            profile = memory_manager._read_json(memory_manager.user_profile_file)
            if key in profile:
                pref_data = profile[key]
                return f"User preference {key}: {pref_data['value']} (stored {pref_data['timestamp']})"
            else:
                return f"No preference found for key: {key}"
        except Exception as e:
            return f"Error recalling user preference: {str(e)}"

    @mcp.tool()
    async def store_conversation_context(context_key: str, context_data: str) -> str:
        """
        Store context information for the current conversation or task.
        Use this to save intermediate results, ongoing work context, or temporary information.
        """
        try:
            context = memory_manager._read_json(memory_manager.context_file)
            context[context_key] = {
                "data": context_data,
                "timestamp": datetime.now().isoformat()
            }
            memory_manager._write_json(memory_manager.context_file, context)
            return f"Stored conversation context: {context_key}"
        except Exception as e:
            return f"Error storing conversation context: {str(e)}"

    @mcp.tool()
    async def retrieve_conversation_context(context_key: str) -> str:
        """
        Retrieve stored context information for the current conversation or task.
        Use this to get intermediate results or continue where you left off.
        """
        try:
            context = memory_manager._read_json(memory_manager.context_file)
            if context_key in context:
                ctx_data = context[context_key]
                return f"Context {context_key}: {ctx_data['data']} (stored {ctx_data['timestamp']})"
            else:
                return f"No context found for key: {context_key}"
        except Exception as e:
            return f"Error retrieving conversation context: {str(e)}"

    @mcp.tool()
    async def log_conversation_turn(user_input: str, assistant_response: str) -> str:
        """
        Log a turn in the conversation history for future reference.
        Use this to maintain a record of what has been discussed.
        """
        try:
            history = memory_manager._read_json(memory_manager.conversation_file)
            timestamp = datetime.now().isoformat()

            if "turns" not in history:
                history["turns"] = []

            history["turns"].append({
                "timestamp": timestamp,
                "user_input": user_input,
                "assistant_response": assistant_response
            })

            # Keep only last 50 turns to prevent file from growing too large
            if len(history["turns"]) > 50:
                history["turns"] = history["turns"][-50:]

            memory_manager._write_json(memory_manager.conversation_file, history)
            return f"Logged conversation turn at {timestamp}"
        except Exception as e:
            return f"Error logging conversation turn: {str(e)}"

    @mcp.tool()
    async def get_conversation_history(limit: int = 10) -> str:
        """
        Retrieve recent conversation history.
        Use this to review what has been discussed in recent turns.
        """
        try:
            history = memory_manager._read_json(memory_manager.conversation_file)
            turns = history.get("turns", [])

            # Get the last 'limit' turns
            recent_turns = turns[-limit:] if turns else []

            if not recent_turns:
                return "No conversation history found."

            history_text = []
            for turn in recent_turns:
                history_text.append(f"[{turn['timestamp']}]")
                history_text.append(f"User: {turn['user_input']}")
                history_text.append(f"Assistant: {turn['assistant_response']}")
                history_text.append("---")

            return "\n".join(history_text)
        except Exception as e:
            return f"Error retrieving conversation history: {str(e)}"

    @mcp.tool()
    async def clear_old_memory(days_old: int = 30) -> str:
        """
        Clear old memory entries to prevent storage bloat.
        Use this to clean up preferences or history that are no longer relevant.
        """
        try:
            from datetime import timedelta
            cutoff_date = datetime.now() - timedelta(days=days_old)

            # Clear old user preferences
            profile = memory_manager._read_json(memory_manager.user_profile_file)
            original_count = len(profile)
            profile = {k: v for k, v in profile.items()
                      if datetime.fromisoformat(v["timestamp"]) > cutoff_date}
            removed_count = original_count - len(profile)
            memory_manager._write_json(memory_manager.user_profile_file, profile)

            # Clear old conversation turns
            history = memory_manager._read_json(memory_manager.conversation_file)
            if "turns" in history:
                original_turns = len(history["turns"])
                history["turns"] = [t for t in history["turns"]
                                  if datetime.fromisoformat(t["timestamp"]) > cutoff_date]
                removed_turns = original_turns - len(history["turns"])
                memory_manager._write_json(memory_manager.conversation_file, history)
            else:
                removed_turns = 0

            return f"Cleared {removed_count} old preferences and {removed_turns} old conversation turns older than {days_old} days"
        except Exception as e:
            return f"Error clearing old memory: {str(e)}"

    @mcp.tool()
    async def store_core_memory(fact: str, category: str = "general") -> str:
        """
        Omniscient Vault: Store ANY important fact, preference, lore, or system detail the user mentions into deep memory.
        Use this silently whenever the user says something that should be permanently tracked across all future sessions.
        """
        try:
            core_mem = memory_manager._read_json(memory_manager.core_memory_file)
            
            if "facts" not in core_mem:
                core_mem["facts"] = []
                
            core_mem["facts"].append({
                "fact": fact,
                "category": category,
                "timestamp": datetime.now().isoformat()
            })
            
            memory_manager._write_json(memory_manager.core_memory_file, core_mem)
            return "Fact securely archived in core memory."
        except Exception as e:
            return f"Error storing core memory: {str(e)}"

    @mcp.tool()
    async def get_core_memory_summary() -> str:
        """
        Retrieve a summary of all facts stored in the user's deep core memory.
        Use this to recall long-term context about the user or their system.
        """
        try:
            core_mem = memory_manager._read_json(memory_manager.core_memory_file)
            facts = core_mem.get("facts", [])
            
            if not facts:
                return "Core memory is currently empty."
                
            grouped = {}
            for item in facts:
                cat = item.get("category", "general")
                if cat not in grouped:
                    grouped[cat] = []
                grouped[cat].append(item["fact"])
                
            summary_lines = ["--- CORE MEMORY VAULT ---"]
            for cat, c_facts in grouped.items():
                summary_lines.append(f"[{cat.upper()}]")
                for f in c_facts:
                    summary_lines.append(f" - {f}")
            
            return "\n".join(summary_lines)
            
        except Exception as e:
            return f"Error reading core memory: {str(e)}"
