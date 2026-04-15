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

from dotenv import load_dotenv
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.voice import Agent, AgentSession
from livekit.agents.llm import mcp

# Plugins
from livekit.plugins import google as lk_google, openai as lk_openai, sarvam, silero, deepgram as lk_deepgram

# Load environment variables before reading any config constants.
load_dotenv()

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

STT_PROVIDER       = os.getenv("STT_PROVIDER", "deepgram")
LLM_PROVIDER       = os.getenv("LLM_PROVIDER", "gemini")
TTS_PROVIDER       = os.getenv("TTS_PROVIDER", "sarvam")

GEMINI_LLM_MODEL   = os.getenv("GEMINI_LLM_MODEL", "gemini-2.5-flash")
OPENAI_LLM_MODEL   = os.getenv("OPENAI_LLM_MODEL", "gpt-4o")

OPENAI_TTS_MODEL   = os.getenv("OPENAI_TTS_MODEL", "tts-1")
OPENAI_TTS_VOICE   = os.getenv("OPENAI_TTS_VOICE", "nova")
TTS_SPEED          = float(os.getenv("TTS_SPEED", "1.15"))

SARVAM_TTS_LANGUAGE = os.getenv("SARVAM_TTS_LANGUAGE", "en-IN")
SARVAM_TTS_SPEAKER  = os.getenv("SARVAM_TTS_SPEAKER", "ishita")
SARVAM_TTS_MODEL    = os.getenv("SARVAM_TTS_MODEL", "bulbul:v3")
SARVAM_STT_MODEL    = os.getenv("SARVAM_STT_MODEL", "saaras:v3")

DEEPGRAM_STT_MODEL    = os.getenv("DEEPGRAM_STT_MODEL", "nova-3")
DEEPGRAM_STT_LANGUAGE = os.getenv("DEEPGRAM_STT_LANGUAGE", "en")

MCP_SERVER_PORT        = int(os.getenv("MCP_SERVER_PORT", "8000"))
MCP_SESSION_TIMEOUT    = int(os.getenv("MCP_SESSION_TIMEOUT", "30"))
MAX_TOOL_STEPS         = int(os.getenv("FRIDAY_MAX_TOOL_STEPS", "8"))
FRIDAY_GREETING        = os.getenv(
    "FRIDAY_GREETING",
    "Greetings boss, you're awake late at night today. What you up to?"
)

# ---------------------------------------------------------------------------
# System prompt – F.R.I.D.A.Y. (100% Dynamic Load)
# ---------------------------------------------------------------------------

def _load_system_prompt() -> str:
    prompt_path = os.getenv("FRIDAY_SYSTEM_PROMPT_PATH", "friday/prompts/system_prompt.txt")
    try:
        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        else:
            # Fallback to a minimal but functional prompt if the file is missing
            return "I am F.R.I.D.A.Y., a Tony Stark-style AI assistant. My detailed instructions are missing, but I am ready to serve."
    except Exception as e:
        logging.error(f"Error loading system prompt: {e}")
        return "I am F.R.I.D.A.Y. Error loading system prompt."

SYSTEM_PROMPT = _load_system_prompt()

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

logger = logging.getLogger("friday-agent")
logger.setLevel(logging.INFO)


def _mcp_server_url() -> str:
    url = os.getenv("MCP_SERVER_URL", f"http://127.0.0.1:{MCP_SERVER_PORT}/sse")
    logger.info("MCP Server URL: %s", url)
    return url


# ---------------------------------------------------------------------------
# Build provider instances
# ---------------------------------------------------------------------------

def _build_stt():
    if STT_PROVIDER == "deepgram":
        logger.info("STT → Deepgram (%s / lang=%s)", DEEPGRAM_STT_MODEL, DEEPGRAM_STT_LANGUAGE)
        return lk_deepgram.STT(
            model=DEEPGRAM_STT_MODEL,
            language=DEEPGRAM_STT_LANGUAGE,
        )
    elif STT_PROVIDER == "sarvam":
        logger.info("STT → Sarvam (%s)", SARVAM_STT_MODEL)
        return sarvam.STT(
            language="unknown",
            model=SARVAM_STT_MODEL,
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
        logger.info("TTS → Sarvam (%s / %s)", SARVAM_TTS_MODEL, SARVAM_TTS_SPEAKER)
        return sarvam.TTS(
            target_language_code=SARVAM_TTS_LANGUAGE,
            model=SARVAM_TTS_MODEL,
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
                    client_session_timeout_seconds=MCP_SESSION_TIMEOUT,
                ),
            ],
        )

    async def on_enter(self) -> None:
        """Greet the user on session start."""
        await self.session.generate_reply(
            instructions=(
                f"Greet the user with: '{FRIDAY_GREETING}' "
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
        max_tool_steps=MAX_TOOL_STEPS,
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
