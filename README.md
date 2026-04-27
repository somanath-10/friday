# F.R.I.D.A.Y. — Tony Stark Demo

> *"Fully Responsive Intelligent Digital Assistant for You"*

A Tony Stark-inspired AI assistant with a local browser mode and an optional legacy voice-worker mode:

| Component | What it is |
|-----------|-----------|
| **Local Console** (`uv run friday`) | A [FastMCP](https://github.com/jlowin/fastmcp) server that exposes tools over SSE and also serves a local browser page at `http://127.0.0.1:8000/`. This is now the primary way to use FRIDAY. |
| **Legacy Voice Agent** (`uv run friday_voice`) | A [LiveKit Agents](https://github.com/livekit/agents) voice pipeline kept for compatibility. It is optional if you use the local browser page. |

---

The core FRIDAY stack is built around the browser, filesystem, shell, desktop, and visible-app workflows that work across both Windows and macOS. Extra integrations should stay optional rather than being part of the required startup path.

## How it works

Primary local browser mode uses OpenAI for the backend chat/tool loop. The older
LiveKit voice worker can still use Deepgram/Sarvam/Whisper for STT,
Gemini/OpenAI for LLM, and Sarvam/OpenAI for TTS when those keys are configured.

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
- open a visible terminal window and type commands into it when you explicitly ask
- open files with their default apps, and copy, move, or delete files and folders across the machine
- detect Chrome profiles and open a specific Chrome account directly, which helps skip the Chrome account picker on multi-profile setups
- inspect the live desktop with screenshots and optional vision analysis before clicking or typing, and estimate target coordinates for GUI actions
- inspect browser pages as indexed interactive elements, then click or type by element number instead of relying only on CSS selectors
- persist conversation turns and action traces so FRIDAY can retain a lightweight execution journal across sessions
- relay spoken or typed requests into the VS Code Codex extension with a local project snapshot first

FRIDAY still works within the permissions of the user account and shell you start it with. Tasks that require administrator rights still need the host process to be run elevated.
Calendar export is optional and disabled by default, so the base desktop/browser workflow does not depend on it.

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

For the broadest Windows control, start the terminal itself with **Run as administrator** before launching FRIDAY. Without that, standard user tasks will still work, but administrator-only actions can fail.

Then open:

```text
http://127.0.0.1:8000/
```

The local page now handles text chat, browser microphone input when supported, browser speech output, and backend MCP tool calls without sending you to the LiveKit playground.

If you want FRIDAY's Playwright browser actions to be visible on screen instead of hidden, set:

```text
FRIDAY_BROWSER_HEADLESS=0
```

On Windows, plain `open chrome` now prefers a detected Chrome profile instead of the Chrome account picker when multiple profiles exist. FRIDAY can also list the available Chrome profiles and open a specific one by name.

For more reliable GUI work, FRIDAY now has screen-aware operator tools. It can capture the live desktop, summarize what is visible, and estimate where a requested button or field is located before using mouse or keyboard tools. If `OPENAI_API_KEY` is configured, these tools use a vision-capable OpenAI model; set `OPENAI_VISION_MODEL` if you want to override the default.

FRIDAY also now keeps a lightweight memory trail for local chat runs by storing conversation turns and action traces under the configured memory directory. That makes it easier to inspect what worked and build toward more reusable workflows.

### 4a. Optional: VS Code Codex relay mode

The browser console now has a **Dispatch Mode** switch:

- `FRIDAY Local Chat` keeps the existing in-browser FRIDAY assistant flow
- `VS Code Codex Relay` opens or focuses VS Code, opens the Codex sidebar, starts a fresh thread, and pastes a project-aware prompt

Relay mode is built for workflows like "listen to my voice, open this project in VS Code, and send the job to Codex." By default it targets the current repo root, but you can override that with `FRIDAY_CODEX_PROJECT_DIR`.

Requirements for relay mode:

- VS Code must be installed and the `code` launcher should be available, or set `FRIDAY_CODEX_VSCODE_EXECUTABLE`
- the OpenAI VS Code extension (`openai.chatgpt`, displayed as **Codex – OpenAI's coding agent**) must be installed
- browser microphone support still depends on Edge or Chrome speech APIs

To run a local verification pass before using it:

```bash
uv run friday_healthcheck
# or:
uv run python -m friday.healthcheck
```

The plain `python -m friday.healthcheck` form also works if your synced project virtualenv is already active.

The healthcheck validates imports, tool registration, the local web UI startup path, and a broad set of offline-safe tools. Networked features are reported separately as config-dependent.

Optional deeper checks:

```bash
uv run python -m friday.healthcheck --desktop
uv run python -m friday.healthcheck --browser
uv run python -m friday.healthcheck --desktop --browser
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
| `SARVAM_API_KEY` | optional | Only needed when legacy voice uses Sarvam STT/TTS |
| `OPENAI_API_KEY` | ✅ local browser | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) — required for the primary local browser chat and browser mic transcription |
| `DEEPGRAM_API_KEY` | optional | [console.deepgram.com](https://console.deepgram.com) |
| `GOOGLE_APPLICATION_CREDENTIALS` | optional | GCP service-account JSON path — only for `STT_PROVIDER = "google"` |
| `GOOGLE_API_KEY` | optional | [aistudio.google.com](https://aistudio.google.com/projects) — only needed when legacy voice/internal utilities use Gemini |
| `FRIDAY_MAX_TOOL_STEPS` | optional | Raises per-turn tool budget for more complex tasks; default is `8` |
| `FRIDAY_LOCAL_MAX_TOOL_ROUNDS` | optional | Raises the local browser chat tool-call budget; default is `14` |
| `FRIDAY_LOCAL_MAX_OPENAI_TOOLS` | optional | Caps how many MCP tools the local browser chat exposes at once; default is `64` for faster replies |
| `FRIDAY_BROWSER_HEADLESS` | optional | Set to `0` for a visible automation browser, or `1` for hidden Playwright sessions |
| `FRIDAY_ENABLE_CALENDAR_TOOL` | optional | Set to `1` only if you want the `.ics` calendar export tool loaded; default is `0` |
| `FRIDAY_DISABLED_TOOL_MODULES` | optional | Comma-separated tool module names to keep out of startup entirely, for example `calendar_tool` |
| `OPENAI_VISION_MODEL` | optional | Override the model used by desktop vision tools; otherwise FRIDAY reuses `OPENAI_LLM_MODEL` |
| `FRIDAY_CODEX_PROJECT_DIR` | optional | Default folder that relay mode opens in VS Code before sending your prompt |
| `FRIDAY_CODEX_VSCODE_EXECUTABLE` | optional | Explicit path to `code` / `Code.exe` if the VS Code launcher is not on `PATH` |
| `SUPABASE_URL` | optional | [supabase.com](https://supabase.com) — for the ticketing tool |
| `SUPABASE_API_KEY` | optional | Supabase project → API settings |

---

## Switching providers

For the primary local browser console, keep:

```text
LLM_PROVIDER=openai
OPENAI_API_KEY=...
```

For the optional legacy voice worker, set provider variables in `.env`:

```text
STT_PROVIDER=deepgram   # deepgram | sarvam | whisper
LLM_PROVIDER=gemini     # gemini | openai
TTS_PROVIDER=sarvam     # sarvam | openai
```

---

## Adding a new tool

1. Create a new `.py` file in `friday/tools/`
2. Define a `register(mcp)` function and decorate your tools with `@mcp.tool()`
3. **That's it.** The dynamic plugin loader discovers and registers it automatically on next start — no changes to `__init__.py` needed.

> [!TIP]
> Apply `@safe_tool` from `friday.tools.error_handling` for automatic error handling and timing.
> Apply `@cached_tool(ttl_seconds=N)` from `friday.tools.cache` for instant repeat lookups.

---

## Architecture (Phase 1–4 Upgrades)

| Upgrade | What Changed |
|---------|-------------|
| **Dynamic Plugin Loader** | `friday/tools/__init__.py` uses `importlib` to auto-discover every `.py` file in the tools folder. Adding a new tool = drop a file. |
| **Structured Logging** | All tool calls flow through `friday/logger.py`. Debug logs go to `workspace/logs/friday.log`; INFO goes to console. |
| **Performance Caching** | `@cached_tool(ttl_seconds)` in `friday/tools/cache.py` provides in-memory caching. `search_web` and `fetch_url` cache for 30 min. |
| **Input Validation** | `@validate_inputs(max_str_len)` in `error_handling.py` blocks oversized payloads before they reach the LLM. |
| **Permissions Diagnostics** | `run_permission_diagnostics` tool tests Screen Recording and Accessibility on macOS and returns exact fix commands. |
| **Context Manager** | 5 new tools (`get_context_stats`, `trim_context`, `get_session_summary`, `save_session_note`, `clear_session_context`) for managing conversation history. |
| **Workflow Orchestrator** | Goal-level tools create preflighted plans, track progress, verify results, and preserve recovery context. |
| **Optional Tool Gating** | Tool modules can be disabled by env so platform-specific or non-core integrations do not weaken the main Windows/macOS desktop flow. |
| **Testing Suite** | `pytest` + `pytest-mock` with unit and mock tests. Install with `uv sync --group dev`, then run `uv run pytest tests/`. |

---

## Documentation

- [`docs/TOOLS.md`](docs/TOOLS.md) — Full catalogue of every MCP tool
- [`docs/WORKFLOWS.md`](docs/WORKFLOWS.md) — Five end-to-end workflow examples

## Dev Tooling

- Install test and lint tooling: `uv sync --group dev`
- Run tests: `uv run pytest tests/`
- Run hooks once across the repo: `uv run pre-commit run --all-files`
- CI uses the same `pytest` suite on a clean machine

---

## Tech stack

- **[FastMCP](https://github.com/jlowin/fastmcp)** — MCP server framework
- **[LiveKit Agents](https://github.com/livekit/agents)** — real-time voice pipeline
- **Deepgram Nova-3** — STT
- **Google Gemini 2.5 Flash / OpenAI** — LLM (configurable)
- **Sarvam Bulbul v3 / OpenAI** — TTS (configurable)
- **[Playwright](https://playwright.dev/)** — headless browser automation
- **[uv](https://github.com/astral-sh/uv)** — fast Python package manager
- **pytest + pytest-mock** — testing infrastructure

---
