# F.R.I.D.A.Y. — Tony Stark Demo

> *"Fully Responsive Intelligent Digital Assistant for You"*

A Tony Stark-inspired AI assistant with a local browser mode and an optional legacy voice-worker mode:

| Component | What it is |
|-----------|-----------|
| **Local Console** (`uv run friday`) | A [FastMCP](https://github.com/jlowin/fastmcp) server that exposes tools over SSE and also serves a local browser page at `http://127.0.0.1:8000/`. This is now the primary way to use FRIDAY. |
| **Legacy Voice Agent** (`uv run friday_voice`) | A [LiveKit Agents](https://github.com/livekit/agents) voice pipeline kept for compatibility. It is optional if you use the local browser page. |

---

## How it works

```
Microphone ──► STT (Sarvam Saaras v3)
                    │
                    ▼
             LLM (Gemini 2.5 Flash)  ◄──────► MCP Server (FastMCP / SSE)
                    │                              ├─ get_world_news
                    ▼                              ├─ open_world_monitor
             TTS (Sarvam Bulbul v3)                ├─ search_web
                    │                              └─ …more tools
                    ▼
             Speaker / LiveKit room
```

The voice agent connects to the MCP server via SSE at `http://127.0.0.1:8000/sse` by default. Host, port, mount path, and SSE path are all configurable through `.env`.

---
## Desktop capabilities

FRIDAY can now operate much more of the local machine from the browser chat or voice agent:

- launch, focus, close, and search installed applications
- inspect open windows, installed software, startup items, services, scheduled tasks, and disk drives
- open folders and URLs, manage files across Desktop/Documents/Downloads/Workspace, and take screenshots
- type into the focused app, send hotkeys, use the clipboard, and run shell commands when needed

FRIDAY still works within the permissions of the user account and shell you start it with. Tasks that require administrator rights still need the host process to be run elevated.

---
## Quick start

### 1. Prerequisites

- Python ≥ 3.11
- [`uv`](https://github.com/astral-sh/uv) — `pip install uv` or `curl -Lsf https://astral.sh/uv/install.sh | sh`
- An OpenAI API key for the local browser mode

### 2. Clone & install

```bash
git clone https://github.com/SAGAR-TAMANG/friday-tony-stark-demo.git
cd friday-tony-stark-demo
uv sync          # creates .venv and installs all dependencies
```

### 3. Set up environment

```bash
cp .env.example .env
# Open .env and fill in your API keys (see the section below)
```

### 4. Run — local browser mode

Start the server:

```bash
uv run friday
```

Then open:

```text
http://127.0.0.1:8000/
```

The local page now handles text chat, browser microphone input when supported, browser speech output, and backend MCP tool calls without sending you to the LiveKit playground.

To run a local verification pass before using it:

```bash
python -m friday.healthcheck
# or, after syncing the project scripts:
uv run friday_healthcheck
```

The healthcheck validates imports, tool registration, the local web UI startup path, and a broad set of offline-safe tools. Networked features are reported separately as config-dependent.

Optional deeper checks:

```bash
python -m friday.healthcheck --desktop
python -m friday.healthcheck --browser
python -m friday.healthcheck --desktop --browser
```

`--desktop` runs real machine workflows like Documents folder creation, Edge discovery, app launch, and URL opening. `--browser` runs the Playwright browser tool checks.

### 5. Optional legacy LiveKit mode

If you still want the older LiveKit pipeline:

```bash
uv run friday_voice
```

---

## `uv run friday` vs `uv run friday_voice`

| Command | Entry point | What it does |
|---------|------------|--------------|
| `uv run friday` | `server.py → main()` | Launches the **FastMCP server** and the local browser console at `/`. For most users this is the only command needed. |
| `uv run friday_voice` | `agent_friday.py → dev()` | Launches the optional **LiveKit voice agent** for the older room-based flow. |

---

## Environment variables

Copy `.env.example` → `.env` and fill in the values below.

| Variable | Required | Where to get it |
|----------|----------|----------------|
| `LIVEKIT_URL` | optional | Only needed for the legacy LiveKit flow |
| `LIVEKIT_API_KEY` | optional | Only needed for the legacy LiveKit flow |
| `LIVEKIT_API_SECRET` | optional | Only needed for the legacy LiveKit flow |
| `GROQ_API_KEY` | optional | [console.groq.com](https://console.groq.com) — only needed if you switch `LLM_PROVIDER` to `"groq"` |
| `SARVAM_API_KEY` | ✅ (default STT) | [dashboard.sarvam.ai](https://dashboard.sarvam.ai) |
| `OPENAI_API_KEY` | ✅ (default TTS) | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| `DEEPGRAM_API_KEY` | optional | [console.deepgram.com](https://console.deepgram.com) |
| `GOOGLE_APPLICATION_CREDENTIALS` | optional | GCP service-account JSON path — only for `STT_PROVIDER = "google"` |
| `GOOGLE_API_KEY` | ✅ (default LLM) | [aistudio.google.com](https://aistudio.google.com/projects) |
| `FRIDAY_MAX_TOOL_STEPS` | optional | Raises per-turn tool budget for more complex tasks; default is `8` |
| `SUPABASE_URL` | optional | [supabase.com](https://supabase.com) — for the ticketing tool |
| `SUPABASE_API_KEY` | optional | Supabase project → API settings |

---

## Switching providers

Open `agent_friday.py` and change the provider constants at the top:

```python
STT_PROVIDER = "deepgram"   # "deepgram" | "sarvam" | "whisper"
LLM_PROVIDER = "gemini"     # "gemini" | "openai"
TTS_PROVIDER = "sarvam"     # "sarvam" | "openai"
```

---

## Adding a new tool

1. Create or open a file in `friday/tools/`
2. Define a `register(mcp)` function and decorate tools with `@mcp.tool()`
3. Import and call `register(mcp)` inside `friday/tools/__init__.py`

The MCP server will pick it up on next start.

---

## Tech stack

- **[FastMCP](https://github.com/jlowin/fastmcp)** — MCP server framework
- **[LiveKit Agents](https://github.com/livekit/agents)** — real-time voice pipeline
- **Deepgram Nova-3** — STT
- **Google Gemini 2.5 Flash** — LLM
- **Sarvam Bulbul v3** — TTS
- **[uv](https://github.com/astral-sh/uv)** — fast Python package manager

---
