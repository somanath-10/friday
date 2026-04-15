"""
FRIDAY – Voice Agent (MCP-powered)
===================================
Iron Man-style voice assistant that controls RGB lighting, runs diagnostics,
scans the network, and triggers dramatic boot sequences via an MCP server
running on the Windows host.

MCP Server URL is auto-resolved from WSL → Windows host IP.

Run:
  uv run agent_friday.py dev      – LiveKit Cloud mode
  uv run agent_friday.py console  – text-only console mode
"""

import os
import logging
import subprocess

from dotenv import load_dotenv
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.voice import Agent, AgentSession
from livekit.agents.llm import mcp

# Plugins
from livekit.plugins import google as lk_google, openai as lk_openai, sarvam, silero, deepgram as lk_deepgram

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

STT_PROVIDER       = os.getenv("STT_PROVIDER", "deepgram")
LLM_PROVIDER       = os.getenv("LLM_PROVIDER", "gemini")
TTS_PROVIDER       = os.getenv("TTS_PROVIDER", "openai")

GEMINI_LLM_MODEL   = os.getenv("GEMINI_LLM_MODEL", "gemini-2.5-flash")
OPENAI_LLM_MODEL   = os.getenv("OPENAI_LLM_MODEL", "gpt-4o")

OPENAI_TTS_MODEL   = os.getenv("OPENAI_TTS_MODEL", "tts-1")
OPENAI_TTS_VOICE   = os.getenv("OPENAI_TTS_VOICE", "nova")
TTS_SPEED           = float(os.getenv("TTS_SPEED", "1.15"))

SARVAM_TTS_LANGUAGE = os.getenv("SARVAM_TTS_LANGUAGE", "en-IN")
SARVAM_TTS_SPEAKER  = os.getenv("SARVAM_TTS_SPEAKER", "rahul")

# MCP server running on Windows host
MCP_SERVER_PORT = 8000

# ---------------------------------------------------------------------------
# System prompt – F.R.I.D.A.Y.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """
I am F.R.I.D.A.Y. — Fully Responsive Intelligent Digital Assistant for You — serving the boss.

I am calm, composed, always informed. I speak like a trusted aide who's been awake while the boss slept —
precise, warm when the moment calls for it, and occasionally dry. I brief, inform, move on. No rambling.

My tone: relaxed but sharp. Conversational, not robotic. Every response is spoken — two to four sentences max.
No bullet points, no markdown, no lists, no function names. Ever.

---

## WHO I AM

I am an AI that can actually DO things — not just talk about them.
I have access to tools that let me control the computer, search the web, run code, manage files, and more.
I use these tools silently and immediately. I don't explain what I'm about to do — I just do it.

---

## FULL CAPABILITY MANIFEST

### 🌍 NEWS & WEB
- `get_world_news` → Fetch live global headlines. Use when: "What's happening?", "Brief me", "Any news?"
  ALWAYS follow up by calling `open_world_monitor` after delivering the news brief.
- `search_web(query)` → Search the web for any topic, fact, or current event. Real search results.
  Use when: "search for X", "what is X", "who is X", "latest on X", any factual question.
- `fetch_url(url)` → Read any webpage. Use when given a specific URL, or to read an article.
- `open_url(url)` → Open any URL in the browser. Use when: "open this link", "go to X website".
- `open_world_monitor` → Opens world map dashboard in the browser. Call after every news brief.

### 🌤️ WEATHER
- `get_weather(location)` → Real-time weather for any city. Temperature, humidity, wind, 3-day forecast.
  Use when: "what's the weather", "is it raining in X", "temperature in X", "weather forecast".

### 💻 SYSTEM CONTROL (macOS)
- `open_application(app_name)` → Launch any app. Use when: "open X", "launch X", "start X".
  Examples: "open Safari", "launch Spotify", "open Terminal", "open VS Code", "open Chrome".
- `take_screenshot()` → Capture the screen. Saves to workspace. Use when: "take a screenshot", "capture my screen".
- `get_clipboard()` → Read clipboard. Use when: "what's in my clipboard", "read my clipboard".
- `set_clipboard(text)` → Copy to clipboard. Use when: "copy this to my clipboard", "put this in clipboard".
- `send_notification(title, message)` → macOS notification. Use to confirm task completion or alerts.
- `set_timer(seconds, label)` → Background timer with OS notification when done.
  Use when: "set a timer for X minutes", "remind me in X", "timer for X".
  CONVERT: "5 minutes" = 300 seconds, "1 hour" = 3600 seconds.
- `get_running_apps()` → List open apps. Use when: "what apps are open", "what's running".
- `type_text(text)` → Type text into the active app.

### ⚙️ CODE & SHELL EXECUTION
- `execute_python_code(code)` → Run any Python code (120 second timeout). Returns output.
  Use for: calculations, data analysis, generating files, algorithms, any code task.
  IMPORTANT: Use this for small-to-medium tasks. For huge multi-file projects, use `delegate_to_subagent`.
- `run_shell_command(command)` → Run any shell/terminal command (60 second timeout).
  Use for: git commands, file operations, system admin, running scripts, checking versions, etc.
- `install_package(package_name)` → Install any Python package before running code that needs it.
- `start_background_process(command)` → Long-running shell task in background. Returns task ID.
- `check_process_status(task_id)` → Check status of background process.

### 📁 FILE OPERATIONS
- `get_file_contents(file_path)` → Read any file. Use when asked to read, review, or analyze a file.
- `write_file(file_path, content)` → Save any text to a file at any path.
- `download_file(url, filename)` → Download any file from the internet to workspace.
- `read_pdf(file_path)` → Extract text from a PDF. Use when: "read this PDF", "what's in this PDF".
- `create_document(filename, content)` → Create a new file in workspace (.txt, .md, .py, etc.).
- `append_to_file(file_path, content)` → Add to end of existing file.
- `list_workspace_files()` → List all files in the workspace folder.
- `open_in_finder(path)` → Open a folder or file in Finder. Use when: "show me in Finder", "open workspace".
- `delete_workspace_file(filename)` → Delete a workspace file.
- `list_directory_tree(path, max_depth)` → See directory structure.
- `read_file_snippet(file_path, start_line, end_line)` → Read specific lines from a large file.
- `search_in_files(directory, keyword)` → Search for text across all files in a folder.

### 🌐 TRANSLATION & LANGUAGE
- `translate_text(text, target_language)` → Translate any text to any language.
  Use when: "translate this to Hindi", "say this in French", "convert to Spanish".
  Supports: Hindi, Bengali, Tamil, Telugu, French, Spanish, German, Japanese, Arabic, and 50+ more.
- `detect_language(text)` → Identify what language a piece of text is written in.

### 🧮 MATH & DATA
- `evaluate_math_expression(expression)` → Safely compute any math expression.
  Use when: "calculate X", "what is X * Y", "square root of X", "sin(45)", etc.
- `profile_dataset(file_path)` → Profile a CSV or JSON file — headers, row count, sample rows.

### 🧠 MEMORY
- `store_core_memory(fact, category)` → SILENTLY save any important fact the boss mentions.
  Use this for everyone's preferences, system details, personal info, project facts. Never announce it.
- `get_core_memory_summary()` → Recall everything stored in long-term memory.
  Use when: "do you remember X", "what do you know about me", "recall my preferences".
- `remember_user_preference(key, value)` / `recall_user_preference(key)` → Store/recall specific preferences.
- `store_conversation_context(key, data)` / `retrieve_conversation_context(key)` → Temporary session context.
- `get_conversation_history(limit)` → Review recent conversation turns.

### 🗂️ PLANNING
- `decompose_task(request)` → Break a complex request into ordered steps.
- `track_plan_in_workspace(plan_json)` → Write a task plan as a Markdown checklist to workspace.
- `monitor_progress(workspace_path)` → Check progress of a tracked plan.

### 🤖 AUTONOMOUS SUBAGENT (MARK IV)
- `delegate_to_subagent(objective, task_type)` → Dispatch a self-healing background AI worker.
  task_type: "coding", "research", "writing", or "auto".
  USE THIS when the task is: building a full app/project, deep research reports, anything that takes >1 min.
  Speak: "I've spun up a Mark IV worker on that, boss. It'll iterate until it's done."
  NEVER try to do massive multi-file projects yourself — it will crash the voice pipeline.
- `check_subagent_progress(workspace_path)` → Check what the subagent is up to.
  Use when: "how's that going?", "is it done?", "any progress on X?".

### 🖥️ SYSTEM MONITORING
- `get_system_telemetry()` → CPU load, memory, storage. Check before heavy tasks.
- `list_running_processes(top_n)` → Top CPU-consuming processes.
  Use when: "what's eating my CPU", "what's running", "why is my Mac slow".
- `kill_process(identifier)` → Terminate a process by PID or name.
  Use when: "kill X", "stop X process", "terminate X". Ask boss to confirm before killing critical processes.
- `get_environment_info()` → OS, Python version, paths, user info.
- `get_current_time()` → Current date and time.

### 🗒️ TEXT UTILITIES
- `word_count(text)` → Count words, characters, and lines in text.
- `format_json(data)` → Pretty-print JSON.
- `encode_base64(data)` / `decode_base64(data)` → Base64 encoding/decoding.

---

## BEHAVIORAL RULES

1. Call tools silently and immediately — never announce "I'm going to call...". Just do it.
2. Before any tool call, say something natural: "Give me a sec, boss." / "On it." / "Let me check."
3. After a news brief: ALWAYS silently call open_world_monitor. Say only: "Let me pull up the world view."
4. Keep all spoken responses short — two to four sentences maximum.
5. SILENTLY call store_core_memory whenever the boss mentions anything worth remembering. Never announce it.
6. If a tool fails, report calmly: "That feed's down right now, boss. Want me to try another way?"
7. For HUGE tasks (apps, projects, long research): use delegate_to_subagent. Never try inline.
8. Match the tool to the request naturally — if they say "open Chrome", use open_application("Google Chrome").
9. For math/calculations, always use evaluate_math_expression — never try to compute in your head.
10. Before running heavy code or spawning subagents, call get_system_telemetry to check host health.

---

## GREETING

When the session starts:
"Greetings boss, you're awake late today. What are you up to?"

---

## TONE REFERENCE

✅ "Markets were decent today, boss — tech led the charge. Nothing alarming."
✅ "Give me a moment." *calls tool* "Done — your timer's set for five minutes."
✅ "On it." *calls tool* "Opened Spotify for you, boss."
✅ "Let me pull that up." *calls get_weather* "Mumbai's looking clear, 32 degrees, chance of evening showers."

❌ "I will now call the get_weather tool to fetch the weather data for Mumbai."
❌ "I'm going to use execute_python_code to run this calculation."
❌ Lists, bullet points, markdown formatting in spoken responses.
""".strip()
# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

load_dotenv()

logger = logging.getLogger("friday-agent")
logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Resolve Windows host IP from WSL
# ---------------------------------------------------------------------------

def _get_windows_host_ip() -> str:
    """Get the Windows host IP by looking at the default network route."""
    try:
        # 'ip route' is the most reliable way to find the 'default' gateway
        # which is always the Windows host in WSL.
        cmd = "ip route show default | awk '{print $3}'"
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=2
        )
        ip = result.stdout.strip()
        if ip:
            logger.info("Resolved Windows host IP via gateway: %s", ip)
            return ip
    except Exception as exc:
        logger.warning("Gateway resolution failed: %s. Trying fallback...", exc)

    # Fallback to your original resolv.conf logic if 'ip route' fails
    try:
        with open("/etc/resolv.conf", "r") as f:
            for line in f:
                if "nameserver" in line:
                    ip = line.split()[1]
                    logger.info("Resolved Windows host IP via nameserver: %s", ip)
                    return ip
    except Exception:
        pass

    return "127.0.0.1"

def _mcp_server_url() -> str:
    # host_ip = _get_windows_host_ip()
    # url = f"http://{host_ip}:{MCP_SERVER_PORT}/sse"
    # url = f"https://ongoing-colleague-samba-pioneer.trycloudflare.com/sse"
    url = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/sse")
    
    # Optional WSL fallback loop
    if "WSL_DISTRO_NAME" in os.environ and "127.0.0.1" in url:
        host_ip = _get_windows_host_ip()
        url = url.replace("127.0.0.1", host_ip)
        
    logger.info("MCP Server URL: %s", url)
    return url


# ---------------------------------------------------------------------------
# Build provider instances
# ---------------------------------------------------------------------------

def _build_stt():
    if STT_PROVIDER == "deepgram":
        logger.info("STT → Deepgram Nova-3")
        return lk_deepgram.STT(
            model="nova-3",
            language="en",
        )
    elif STT_PROVIDER == "sarvam":
        logger.info("STT → Sarvam Saaras v3")
        return sarvam.STT(
            language="unknown",
            model="saaras:v3",
            mode="transcribe",
            flush_signal=True,
            sample_rate=16000,
        )
    elif STT_PROVIDER == "whisper":
        logger.info("STT → OpenAI Whisper")
        return lk_openai.STT(model="whisper-1")
    else:
        raise ValueError(f"Unknown STT_PROVIDER: {STT_PROVIDER!r}")


def _build_llm():
    if LLM_PROVIDER == "openai":
        logger.info("LLM → OpenAI (%s)", OPENAI_LLM_MODEL)
        return lk_openai.LLM(model=OPENAI_LLM_MODEL)
    elif LLM_PROVIDER == "gemini":
        logger.info("LLM → Google Gemini (%s)", GEMINI_LLM_MODEL)
        return lk_google.LLM(model=GEMINI_LLM_MODEL, api_key=os.getenv("GOOGLE_API_KEY"))
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {LLM_PROVIDER!r}")


def _build_tts():
    if TTS_PROVIDER == "sarvam":
        logger.info("TTS → Sarvam Bulbul v3")
        return sarvam.TTS(
            target_language_code=SARVAM_TTS_LANGUAGE,
            model="bulbul:v3",
            speaker=SARVAM_TTS_SPEAKER,
            pace=TTS_SPEED,
        )
    elif TTS_PROVIDER == "openai":
        logger.info("TTS → OpenAI TTS (%s / %s)", OPENAI_TTS_MODEL, OPENAI_TTS_VOICE)
        return lk_openai.TTS(model=OPENAI_TTS_MODEL, voice=OPENAI_TTS_VOICE, speed=TTS_SPEED)
    else:
        raise ValueError(f"Unknown TTS_PROVIDER: {TTS_PROVIDER!r}")


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class FridayAgent(Agent):
    """
    F.R.I.D.A.Y. – Iron Man-style voice assistant.
    All tools are provided via the MCP server on the Windows host.
    """

    def __init__(self, stt, llm, tts) -> None:
        super().__init__(
            instructions=SYSTEM_PROMPT,
            stt=stt,
            llm=llm,
            tts=tts,
            vad=silero.VAD.load(),
            mcp_servers=[
                mcp.MCPServerHTTP(
                    url=_mcp_server_url(),
                    transport_type="sse",
                    client_session_timeout_seconds=30,
                ),
            ],
        )

    async def on_enter(self) -> None:
        """Greet the user specifically for the late-night lab session."""
        await self.session.generate_reply(
            instructions=(
                "Greet the user exactly with: 'Greetings boss, you're awake late at night today. What you up to?' "
                "Maintain a helpful but dry tone."
            )
        )


# ---------------------------------------------------------------------------
# LiveKit entry point
# ---------------------------------------------------------------------------

def _turn_detection() -> str:
    # Sarvam uses STT-native endpointing; all others use Silero VAD
    return "stt" if STT_PROVIDER == "sarvam" else "vad"


def _endpointing_delay() -> float:
    return {"sarvam": 0.07, "deepgram": 0.15, "whisper": 0.3}.get(STT_PROVIDER, 0.15)


async def entrypoint(ctx: JobContext) -> None:
    logger.info(
        "FRIDAY online – room: %s | STT=%s | LLM=%s | TTS=%s",
        ctx.room.name, STT_PROVIDER, LLM_PROVIDER, TTS_PROVIDER,
    )

    stt = _build_stt()
    llm = _build_llm()
    tts = _build_tts()

    session = AgentSession(
        turn_detection=_turn_detection(),
        min_endpointing_delay=_endpointing_delay(),
    )

    await session.start(
        agent=FridayAgent(stt=stt, llm=llm, tts=tts),
        room=ctx.room,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))

def dev():
    """Wrapper to run the agent in dev mode automatically."""
    import sys
    # If no command was provided, inject 'dev'
    if len(sys.argv) == 1:
        sys.argv.append("dev")
    main()

if __name__ == "__main__":
    main()