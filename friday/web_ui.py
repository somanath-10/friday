"""
Local web UI routes for FRIDAY.

The default experience is now a fully local browser page that talks to the
existing MCP tool server through a backend chat bridge. LiveKit is no longer
required for the primary flow.
"""

from __future__ import annotations

import html
import json
import logging
import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from friday.codex_bridge import codex_relay_status, dispatch_to_vscode_codex
from friday.local_chat import (
    local_greeting,
    local_mode_issues,
    run_local_chat,
    transcribe_browser_audio,
)


logger = logging.getLogger("friday.web_ui")


def _nested_runtime_error(exc: BaseException) -> str | None:
    if isinstance(exc, RuntimeError):
        return str(exc)
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            detail = _nested_runtime_error(child)
            if detail:
                return detail
    return None


def _canonical_browser_host(host: str | None) -> str:
    if not host:
        return "127.0.0.1"
    if host in {"0.0.0.0", "::", "[::]"}:
        return "127.0.0.1"
    return host


def _canonicalize_url(url: str) -> str:
    if not url:
        return url

    parts = urlsplit(url)
    host = _canonical_browser_host(parts.hostname)
    if not parts.scheme or not parts.netloc:
        return url

    netloc = f"{host}:{parts.port}" if parts.port else host
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _browser_base_url(request: Request) -> str:
    scheme = request.url.scheme
    host = _canonical_browser_host(request.url.hostname)
    port = request.url.port
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    if port and not default_port:
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def _mcp_server_url(request: Request | None = None) -> str:
    sse_path = os.getenv("MCP_SSE_PATH", "/sse").strip() or "/sse"
    configured = _canonicalize_url(os.getenv("MCP_SERVER_URL", "").strip())
    if configured:
        return configured

    if request is not None:
        return f"{_browser_base_url(request)}{sse_path}"

    port = os.getenv("MCP_SERVER_PORT", "8000").strip() or "8000"
    return f"http://127.0.0.1:{port}{sse_path}"


def _local_status(request: Request | None = None) -> dict[str, Any]:
    llm_provider = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    llm_model = (
        os.getenv("OPENAI_LLM_MODEL", "gpt-4o").strip()
        if llm_provider == "openai"
        else os.getenv("GEMINI_LLM_MODEL", "gemini-2.5-flash").strip()
    )
    issues = local_mode_issues()
    codex_status = codex_relay_status()

    return {
        "server_name": os.getenv("SERVER_NAME", "Friday").strip() or "Friday",
        "mode": "local-browser",
        "mcp_server_url": _mcp_server_url(request),
        "llm_provider": llm_provider,
        "llm_model": llm_model,
        "browser_voice_input": "MediaRecorder microphone capture with backend transcription",
        "browser_voice_output": "speechSynthesis",
        "issues": issues,
        "ready": not issues,
        "greeting": local_greeting(),
        "codex_relay": codex_status,
        "legacy_livekit_configured": bool(
            os.getenv("LIVEKIT_URL") and os.getenv("LIVEKIT_API_KEY") and os.getenv("LIVEKIT_API_SECRET")
        ),
    }


def _render_page(request: Request) -> str:
    state = _local_status(request)
    codex_state = state["codex_relay"]
    server_name = html.escape(state["server_name"])
    mcp_server_url = html.escape(state["mcp_server_url"])
    llm_label = html.escape(f"{state['llm_provider']} / {state['llm_model']}")
    greeting = html.escape(state["greeting"])
    readiness = "Ready" if state["ready"] else "Needs Config"
    readiness_class = "ready" if state["ready"] else "warn"
    issues = state["issues"] or ["Local browser mode is ready."]
    issue_items = "".join(f"<li>{html.escape(item)}</li>" for item in issues)
    codex_status_label = "Ready" if codex_state["ready"] else "Needs Setup"
    codex_status_text = (
        "VS Code launcher and the Codex extension are available. Relay mode can open the sidebar, start a thread, and paste a project-aware prompt."
        if codex_state["ready"]
        else "; ".join(codex_state["issues"]) or "Codex relay is not configured yet."
    )
    codex_project_path = html.escape(codex_state["project_path"])

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{server_name} Local Console</title>
    <style>
      :root {{
        --bg: #071018;
        --bg-panel: rgba(9, 20, 31, 0.9);
        --bg-strong: rgba(12, 25, 38, 0.98);
        --line: rgba(151, 186, 214, 0.16);
        --text: #edf6ff;
        --muted: #96abc1;
        --accent: #ff7b47;
        --accent-soft: rgba(255, 123, 71, 0.16);
        --cool: #2ad1be;
        --cool-soft: rgba(42, 209, 190, 0.18);
        --ok: #54d488;
        --warn: #ffc857;
        --shadow: 0 28px 90px rgba(0, 0, 0, 0.35);
        --radius: 24px;
      }}

      * {{
        box-sizing: border-box;
      }}

      html {{
        scroll-behavior: smooth;
      }}

      body {{
        margin: 0;
        min-height: 100vh;
        font-family: "Segoe UI Variable Display", "Aptos", "Trebuchet MS", sans-serif;
        color: var(--text);
        background:
          radial-gradient(circle at 15% 10%, rgba(255, 123, 71, 0.22), transparent 26%),
          radial-gradient(circle at 85% 0%, rgba(42, 209, 190, 0.18), transparent 24%),
          linear-gradient(135deg, #050d14 0%, #09141d 45%, #0e1620 100%);
      }}

      body::before {{
        content: "";
        position: fixed;
        inset: 0;
        background:
          linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
        background-size: 28px 28px;
        mask-image: linear-gradient(to bottom, rgba(0,0,0,0.45), transparent 90%);
        pointer-events: none;
      }}

      .shell {{
        width: min(1180px, calc(100% - 28px));
        margin: 24px auto 36px;
        display: grid;
        gap: 20px;
      }}

      .hero {{
        position: relative;
        overflow: hidden;
        padding: 28px;
        border: 1px solid var(--line);
        border-radius: 30px;
        background: linear-gradient(145deg, rgba(12, 28, 42, 0.96), rgba(8, 18, 28, 0.94));
        box-shadow: var(--shadow);
      }}

      .hero::after {{
        content: "";
        position: absolute;
        width: 260px;
        height: 260px;
        top: -90px;
        right: -60px;
        border-radius: 50%;
        background: radial-gradient(circle, rgba(42, 209, 190, 0.22), transparent 68%);
      }}

      .eyebrow {{
        display: inline-flex;
        align-items: center;
        gap: 10px;
        padding: 8px 12px;
        border-radius: 999px;
        border: 1px solid rgba(255,255,255,0.1);
        background: rgba(255,255,255,0.04);
        color: var(--muted);
        font-size: 12px;
        letter-spacing: 0.16em;
        text-transform: uppercase;
      }}

      .pulse {{
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: var(--cool);
        box-shadow: 0 0 0 0 rgba(42, 209, 190, 0.45);
        animation: pulse 1.9s infinite;
      }}

      @keyframes pulse {{
        0% {{ box-shadow: 0 0 0 0 rgba(42, 209, 190, 0.55); }}
        70% {{ box-shadow: 0 0 0 16px rgba(42, 209, 190, 0); }}
        100% {{ box-shadow: 0 0 0 0 rgba(42, 209, 190, 0); }}
      }}

      h1 {{
        margin: 18px 0 10px;
        max-width: 12ch;
        font-size: clamp(2.8rem, 7vw, 5.3rem);
        line-height: 0.94;
        letter-spacing: -0.055em;
      }}

      .hero p {{
        margin: 0;
        max-width: 62ch;
        color: var(--muted);
        line-height: 1.72;
        font-size: 1.02rem;
      }}

      .hero-actions {{
        margin-top: 24px;
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
      }}

      .button {{
        appearance: none;
        border: 1px solid transparent;
        border-radius: 999px;
        padding: 13px 18px;
        font: inherit;
        font-weight: 700;
        color: var(--text);
        cursor: pointer;
        text-decoration: none;
        transition: transform 140ms ease, border-color 140ms ease, background 140ms ease;
      }}

      .button:hover {{
        transform: translateY(-1px);
      }}

      .button-primary {{
        color: #081018;
        background: linear-gradient(135deg, var(--accent), #ffb347);
      }}

      .button-secondary {{
        background: rgba(255,255,255,0.04);
        border-color: rgba(255,255,255,0.1);
      }}

      .button-mic {{
        min-width: 132px;
      }}

      .button-mic.listening {{
        background: linear-gradient(135deg, #ff7b47, #ff4d6d);
        color: #081018;
      }}

      .button-mic.starting {{
        background: rgba(255, 200, 87, 0.16);
        border-color: rgba(255, 200, 87, 0.5);
        color: var(--warn);
      }}

      .grid {{
        display: grid;
        grid-template-columns: repeat(12, 1fr);
        gap: 20px;
      }}

      .card {{
        grid-column: span 12;
        border: 1px solid var(--line);
        border-radius: var(--radius);
        background: var(--bg-panel);
        box-shadow: var(--shadow);
        backdrop-filter: blur(12px);
      }}

      .card-inner {{
        padding: 22px;
      }}

      .status-card {{
        grid-column: span 4;
      }}

      .detail-card {{
        grid-column: span 8;
      }}

      .status-pill {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 8px 12px;
        border-radius: 999px;
        font-size: 0.92rem;
        font-weight: 700;
      }}

      .status-pill.ready {{
        color: #081018;
        background: var(--ok);
      }}

      .status-pill.warn {{
        color: #251d08;
        background: var(--warn);
      }}

      .status-note {{
        margin-top: 12px;
        color: var(--muted);
        line-height: 1.62;
      }}

      .issue-list {{
        margin: 14px 0 0;
        padding-left: 18px;
        color: var(--muted);
        line-height: 1.55;
      }}

      .metric-grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 14px;
      }}

      .metric-box {{
        padding: 16px;
        border-radius: 18px;
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.06);
      }}

      .metric-label {{
        display: block;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.12em;
        font-size: 0.72rem;
        margin-bottom: 6px;
      }}

      .metric-value {{
        font-size: 1.04rem;
        font-weight: 700;
        word-break: break-word;
      }}

      .command-block {{
        margin-top: 16px;
        padding: 14px;
        border-radius: 16px;
        background: #081018;
        border: 1px solid rgba(255,255,255,0.07);
        font-family: "Cascadia Mono", "Consolas", monospace;
        color: #d8ecff;
        overflow-x: auto;
      }}

      .console {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) 280px;
        gap: 20px;
      }}

      .chat-shell {{
        display: grid;
        gap: 16px;
      }}

      .message-log {{
        min-height: 480px;
        max-height: 68vh;
        overflow-y: auto;
        padding: 18px;
        border-radius: 22px;
        background: linear-gradient(180deg, rgba(8, 18, 28, 0.94), rgba(6, 14, 21, 0.98));
        border: 1px solid rgba(255,255,255,0.06);
        display: grid;
        gap: 14px;
      }}

      .message {{
        max-width: min(82%, 700px);
        padding: 14px 16px;
        border-radius: 18px;
        line-height: 1.64;
        white-space: pre-wrap;
        word-break: break-word;
      }}

      .message.user {{
        margin-left: auto;
        background: linear-gradient(135deg, rgba(255,123,71,0.16), rgba(255,179,71,0.12));
        border: 1px solid rgba(255,123,71,0.2);
      }}

      .message.assistant {{
        background: linear-gradient(135deg, rgba(42,209,190,0.16), rgba(42,209,190,0.08));
        border: 1px solid rgba(42,209,190,0.18);
      }}

      .message.system {{
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.06);
      }}

      .message-label {{
        display: block;
        margin-bottom: 8px;
        color: var(--muted);
        font-size: 0.76rem;
        text-transform: uppercase;
        letter-spacing: 0.14em;
      }}

      .tool-strip {{
        margin-top: 10px;
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }}

      .tool-chip {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 10px;
        border-radius: 999px;
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.08);
        color: var(--muted);
        font-size: 0.78rem;
      }}

      .tool-chip.error {{
        color: #251d08;
        background: rgba(255, 200, 87, 0.18);
        border-color: rgba(255, 200, 87, 0.36);
      }}

      .composer {{
        padding: 16px;
        border-radius: 22px;
        background: var(--bg-strong);
        border: 1px solid rgba(255,255,255,0.07);
      }}

      .composer-meta {{
        display: grid;
        grid-template-columns: 180px minmax(0, 1fr);
        gap: 12px;
        margin-bottom: 14px;
      }}

      .field-stack {{
        display: grid;
        gap: 8px;
      }}

      .field-label {{
        color: var(--muted);
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.14em;
      }}

      .mode-select,
      .path-input {{
        width: 100%;
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 14px;
        background: rgba(255,255,255,0.04);
        color: var(--text);
        font: inherit;
        padding: 12px 14px;
      }}

      .codex-banner {{
        margin-bottom: 14px;
        padding: 12px 14px;
        border-radius: 16px;
        background: rgba(42, 209, 190, 0.08);
        border: 1px solid rgba(42, 209, 190, 0.16);
        color: var(--muted);
        line-height: 1.58;
      }}

      .composer textarea {{
        width: 100%;
        min-height: 112px;
        resize: vertical;
        border: 0;
        outline: 0;
        background: transparent;
        color: var(--text);
        font: inherit;
        line-height: 1.6;
      }}

      .composer-footer {{
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding-top: 12px;
        border-top: 1px solid rgba(255,255,255,0.07);
      }}

      .voice-status {{
        margin: 10px 2px 0;
        color: var(--muted);
        font-size: 0.95rem;
      }}

      .voice-status.ok {{
        color: var(--ok);
      }}

      .voice-status.warn {{
        color: var(--warn);
      }}

      .composer-actions {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
      }}

      .side-panel {{
        display: grid;
        gap: 16px;
      }}

      .side-card {{
        padding: 18px;
        border-radius: 22px;
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.06);
      }}

      .side-card h3 {{
        margin: 0 0 10px;
        font-size: 0.98rem;
      }}

      .side-card p,
      .side-card li {{
        color: var(--muted);
        line-height: 1.62;
      }}

      .side-card ul {{
        margin: 0;
        padding-left: 18px;
      }}

      .mini {{
        font-size: 0.9rem;
      }}

      .toggle {{
        display: inline-flex;
        align-items: center;
        gap: 8px;
        color: var(--muted);
      }}

      .footer-note {{
        color: var(--muted);
        font-size: 0.92rem;
      }}

      @media (max-width: 980px) {{
        .status-card,
        .detail-card {{
          grid-column: span 12;
        }}

        .metric-grid,
        .console {{
          grid-template-columns: 1fr;
        }}

        .composer-meta {{
          grid-template-columns: 1fr;
        }}
      }}
    </style>
  </head>
  <body>
    <main class="shell">
      <section class="hero">
        <div class="eyebrow"><span class="pulse"></span>Local Browser Mode</div>
        <h1>{server_name}</h1>
        <p>
          One terminal. One page. No LiveKit handoff. Type or use your browser microphone here,
          and FRIDAY will reason on the backend while calling your MCP tools locally.
        </p>
        <div class="hero-actions">
          <a class="button button-primary" href="#pilot-console">Open Console</a>
          <button class="button button-secondary" type="button" data-copy="uv run friday">Copy Run Command</button>
          <button class="button button-secondary" type="button" data-copy="{mcp_server_url}">Copy MCP URL</button>
        </div>
      </section>

      <section class="grid">
        <article class="card status-card">
          <div class="card-inner">
            <h2>System Status</h2>
            <div class="status-pill {readiness_class}" id="readiness-pill">{readiness}</div>
            <p class="status-note">
              Local browser mode only needs the server and an OpenAI key. Speech input and spoken replies are handled by your browser when supported.
            </p>
            <ul class="issue-list" id="issue-list">{issue_items}</ul>
          </div>
        </article>

        <article class="card detail-card">
          <div class="card-inner">
            <h2>Stack Snapshot</h2>
            <div class="metric-grid">
              <div class="metric-box">
                <span class="metric-label">Run Once</span>
                <span class="metric-value">uv run friday</span>
              </div>
              <div class="metric-box">
                <span class="metric-label">LLM</span>
                <span class="metric-value" id="llm-label">{llm_label}</span>
              </div>
              <div class="metric-box">
                <span class="metric-label">MCP Endpoint</span>
                <span class="metric-value" id="mcp-url">{mcp_server_url}</span>
              </div>
            </div>
            <div class="command-block">uv run friday</div>
          </div>
        </article>
      </section>

      <section class="card" id="pilot-console">
        <div class="card-inner console">
          <div class="chat-shell">
            <div class="message-log" id="message-log"></div>

            <div class="composer">
              <div class="composer-meta">
                <label class="field-stack">
                  <span class="field-label">Dispatch Mode</span>
                  <select class="mode-select" id="dispatch-mode">
                    <option value="friday">FRIDAY Local Chat</option>
                    <option value="codex">VS Code Codex Relay</option>
                  </select>
                </label>
                <label class="field-stack">
                  <span class="field-label">Project Folder</span>
                  <input class="path-input" id="project-path-input" type="text" value="{codex_project_path}" spellcheck="false">
                </label>
              </div>
              <div class="codex-banner" id="codex-banner">
                Relay mode opens VS Code on the project folder, opens the Codex sidebar, starts a new thread, and pastes a FRIDAY-generated project brief plus your request.
              </div>
              <textarea id="prompt-input" placeholder="Ask FRIDAY to open apps, create folders, search installed software, or run desktop tasks."></textarea>
              <div class="composer-footer">
                <div class="composer-actions">
                  <button class="button button-primary" id="send-button" type="button">Send</button>
                  <button class="button button-secondary button-mic" id="mic-button" type="button">Start Mic</button>
                  <button class="button button-secondary" id="stop-speech" type="button">Stop Voice</button>
                </div>
                <label class="toggle">
                  <input id="speak-toggle" type="checkbox" checked>
                  Speak replies aloud
                </label>
              </div>
              <p class="voice-status" id="voice-status">Voice idle. Click Start Mic or type your request.</p>
            </div>
          </div>

          <aside class="side-panel">
            <section class="side-card">
              <h3>What Changed</h3>
              <p class="mini">The local page is now the primary experience. You no longer need the LiveKit playground for normal use.</p>
            </section>

            <section class="side-card">
              <h3>Voice Notes</h3>
              <ul>
                <li>Mic input streams short browser-recorded chunks to the local backend for live transcription updates.</li>
                <li>Spoken replies use the browser speech engine, so voices depend on your system.</li>
                <li>In Codex relay mode, final speech is sent straight into the VS Code Codex chat flow.</li>
                <li>If browser speech is unavailable, typing still works.</li>
              </ul>
            </section>

            <section class="side-card">
              <h3>Opening Websites</h3>
              <p class="mini">Browser automation uses FRIDAY's own automation browser window. It does not take over your current Edge tab unless a desktop-control tool explicitly does that.</p>
            </section>

            <section class="side-card">
              <h3>Codex Relay</h3>
              <p class="mini" id="codex-status-note">{html.escape(codex_status_text)}</p>
              <p class="mini footer-note">Status: <span id="codex-status-label">{html.escape(codex_status_label)}</span></p>
            </section>

            <section class="side-card">
              <h3>Greeting</h3>
              <p class="mini">{greeting}</p>
            </section>

            <section class="side-card">
              <h3>Advanced</h3>
              <p class="mini footer-note">Legacy LiveKit mode can still exist in the codebase, but this page no longer depends on it.</p>
            </section>
          </aside>
        </div>
      </section>
    </main>

    <script>
      const initialGreeting = {json.dumps(state["greeting"])};
      const initialCodexStatus = {json.dumps(codex_state)};
      const appState = {{
        ready: {str(state["ready"]).lower()},
        codexReady: {str(codex_state["ready"]).lower()},
        busy: false,
        listening: false,
        micStarting: false,
        speakReplies: true,
        dispatchMode: "friday",
        messages: [
          {{ role: "assistant", content: initialGreeting, toolEvents: [] }}
        ],
      }};

      const messageLog = document.getElementById("message-log");
      const promptInput = document.getElementById("prompt-input");
      const sendButton = document.getElementById("send-button");
      const micButton = document.getElementById("mic-button");
      const stopSpeechButton = document.getElementById("stop-speech");
      const speakToggle = document.getElementById("speak-toggle");
      const dispatchMode = document.getElementById("dispatch-mode");
      const projectPathInput = document.getElementById("project-path-input");
      const voiceStatus = document.getElementById("voice-status");
      const codexBanner = document.getElementById("codex-banner");
      const codexStatusNote = document.getElementById("codex-status-note");
      const codexStatusLabel = document.getElementById("codex-status-label");
      const issueList = document.getElementById("issue-list");
      const readinessPill = document.getElementById("readiness-pill");

      let mediaRecorder = null;
      let mediaStream = null;
      let recordedChunks = [];
      let recordingTimer = null;
      let silenceMonitor = null;
      let audioContext = null;
      let analyserNode = null;
      let sourceNode = null;
      let micMimeType = "";
      let speechDetected = false;
      let recordingStartedAt = 0;
      let lastSoundAt = 0;
      let previewTranscriptRequestInFlight = false;
      let previewTranscriptQueued = false;
      let livePreviewTranscript = "";
      let livePreviewRequestAt = 0;
      let liveSessionId = 0;
      const MAX_RECORDING_MS = 20000;
      const MIN_RECORDING_MS = 900;
      const SILENCE_STOP_MS = 1800;
      const SILENCE_LEVEL_THRESHOLD = 0.015;
      const RECORDER_AUDIO_BITS_PER_SECOND = 128000;
      const LIVE_CHUNK_MS = 900;
      const LIVE_TRANSCRIBE_INTERVAL_MS = 2200;
      const MIN_LIVE_TRANSCRIBE_BYTES = 12000;

      function escapeHtml(value) {{
        return value
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;")
          .replaceAll("'", "&#39;");
      }}

      function renderMessages() {{
        messageLog.innerHTML = appState.messages.map((message) => {{
          const label = message.role === "user" ? "Boss" : (message.role === "assistant" ? "Friday" : "System");
          const toolEvents = Array.isArray(message.toolEvents) && message.toolEvents.length
            ? `<div class="tool-strip">${{message.toolEvents.map((tool) => {{
                const chipClass = tool.ok ? "tool-chip" : "tool-chip error";
                const chipLabel = tool.ok ? escapeHtml(tool.name) : `${{escapeHtml(tool.name)}} failed`;
                const chipTitle = tool.preview ? ` title="${{escapeHtml(tool.preview)}}"` : "";
                return `<span class="${{chipClass}}"${{chipTitle}}>${{chipLabel}}</span>`;
              }}).join("")}}</div>`
            : "";
          return `
            <article class="message ${{message.role}}">
              <span class="message-label">${{label}}</span>
              <div>${{escapeHtml(message.content)}}</div>
              ${{toolEvents}}
            </article>
          `;
        }}).join("");
        messageLog.scrollTop = messageLog.scrollHeight;
      }}

      function activeModeReady() {{
        return appState.dispatchMode === "codex" ? appState.codexReady : appState.ready;
      }}

      function setVoiceStatus(message, tone = "info") {{
        voiceStatus.textContent = message;
        voiceStatus.className = tone === "info" ? "voice-status" : `voice-status ${{tone}}`;
      }}

      function setBusy(isBusy) {{
        appState.busy = isBusy;
        sendButton.disabled = isBusy || !activeModeReady();
        updateMicButton();
      }}

      function updateComposerMode() {{
        appState.dispatchMode = dispatchMode.value === "codex" ? "codex" : "friday";
        const codexMode = appState.dispatchMode === "codex";
        promptInput.placeholder = codexMode
          ? "Describe what Codex should do in this project. FRIDAY will attach a local project brief before sending it."
          : "Ask FRIDAY to open apps, create folders, search installed software, or run desktop tasks.";
        codexBanner.hidden = !codexMode;
        setBusy(appState.busy);
      }}

      function addMessage(role, content, toolEvents = []) {{
        appState.messages.push({{ role, content, toolEvents }});
        if (appState.messages.length > 18) {{
          appState.messages = appState.messages.slice(-18);
        }}
        renderMessages();
      }}

      function speakReply(text) {{
        if (!appState.speakReplies || !("speechSynthesis" in window)) {{
          if (appState.speakReplies && !("speechSynthesis" in window)) {{
            setVoiceStatus("Reply ready. This browser cannot play spoken replies, so the text response is shown above.", "warn");
          }}
          return;
        }}

        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1;
        utterance.pitch = 1;
        utterance.onstart = () => {{
          setVoiceStatus("Speaking reply.", "ok");
        }};
        utterance.onend = () => {{
          if (!appState.listening && !appState.micStarting) {{
            setVoiceStatus("Voice idle. Click Start Mic or type your request.");
          }}
        }};
        utterance.onerror = () => {{
          setVoiceStatus("The browser could not play the spoken reply. The text response is still shown above.", "warn");
        }};
        window.speechSynthesis.resume();
        window.speechSynthesis.speak(utterance);
      }}

      async function refreshStatus() {{
        try {{
          const response = await fetch("/status", {{ headers: {{ "Accept": "application/json" }} }});
          const status = await response.json();
          const codex = status.codex_relay || initialCodexStatus;

          appState.ready = Boolean(status.ready);
          appState.codexReady = Boolean(codex.ready);
          readinessPill.textContent = status.ready ? "Ready" : "Needs Config";
          readinessPill.className = `status-pill ${{status.ready ? "ready" : "warn"}}`;
          issueList.innerHTML = (status.issues.length ? status.issues : ["Local browser mode is ready."])
            .map((item) => `<li>${{escapeHtml(item)}}</li>`)
            .join("");
          codexStatusLabel.textContent = codex.ready ? "Ready" : "Needs Setup";
          codexStatusNote.textContent = codex.ready
            ? "VS Code launcher and the Codex extension are available. Relay mode can open the sidebar, start a thread, and paste a project-aware prompt."
            : (Array.isArray(codex.issues) && codex.issues.length
              ? codex.issues.join("; ")
              : "Codex relay is not configured yet.");

          if (!projectPathInput.value.trim() || projectPathInput.value.trim() === initialCodexStatus.project_path) {{
            projectPathInput.value = codex.project_path || initialCodexStatus.project_path;
          }}

          document.getElementById("mcp-url").textContent = status.mcp_server_url;
          document.getElementById("llm-label").textContent = `${{status.llm_provider}} / ${{status.llm_model}}`;

          document.querySelectorAll("[data-copy]").forEach((button) => {{
            if (button.dataset.copy === {json.dumps(state["mcp_server_url"])}) {{
              button.dataset.copy = status.mcp_server_url;
            }}
          }});

          setBusy(appState.busy);
        }} catch (error) {{
          console.error("Status refresh failed", error);
        }}
      }}

      async function copyText(value, button) {{
        try {{
          await navigator.clipboard.writeText(value);
          const original = button.textContent;
          button.textContent = "Copied";
          window.setTimeout(() => {{
            button.textContent = original;
          }}, 1400);
        }} catch (error) {{
          console.error("Clipboard copy failed", error);
        }}
      }}

      async function sendPrompt(text) {{
        const trimmed = text.trim();
        if (!trimmed || appState.busy || !activeModeReady()) {{
          return;
        }}

        promptInput.value = "";
        addMessage("user", trimmed);
        setBusy(true);

        const pendingIndex = appState.messages.length;
        addMessage("system", appState.dispatchMode === "codex" ? "Sending to VS Code Codex." : "Working on it.");

        try {{
          const endpoint = appState.dispatchMode === "codex" ? "/api/codex/relay" : "/api/chat";
          const body = appState.dispatchMode === "codex"
            ? {{
                prompt: trimmed,
                project_path: projectPathInput.value.trim(),
              }}
            : {{
                messages: appState.messages
                  .filter((message) => message.role === "user" || message.role === "assistant")
                  .map((message) => ({{ role: message.role, content: message.content }})),
              }};

          const response = await fetch(endpoint, {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(body),
          }});

          const data = await response.json();
          appState.messages.splice(pendingIndex, 1);

          if (!response.ok) {{
            addMessage("system", data.error || "The local chat route failed.");
          }} else {{
            const reply = data.reply || "I did not get a usable reply back.";
            addMessage("assistant", reply, data.tool_events || []);
            speakReply(data.reply || "");
          }}
        }} catch (error) {{
          appState.messages.splice(pendingIndex, 1);
          addMessage("system", appState.dispatchMode === "codex" ? "The Codex relay route could not be reached." : "The local route could not be reached.");
          console.error("Chat request failed", error);
        }} finally {{
          setBusy(false);
        }}
      }}

      function updateMicButton() {{
        if (!supportsRecordedMic()) {{
          micButton.textContent = "Mic Unavailable";
          micButton.disabled = true;
          micButton.classList.remove("starting");
          micButton.classList.remove("listening");
          return;
        }}

        micButton.textContent = appState.micStarting
          ? "Starting..."
          : (appState.listening ? "Listening..." : "Start Mic");
        micButton.disabled = appState.busy || !activeModeReady() || appState.micStarting;
        micButton.classList.toggle("starting", appState.micStarting);
        micButton.classList.toggle("listening", appState.listening);
      }}

      function secureMicContext() {{
        return window.isSecureContext || ["localhost", "127.0.0.1", "::1", "[::1]"].includes(window.location.hostname);
      }}

      function supportsRecordedMic() {{
        return secureMicContext()
          && Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)
          && "MediaRecorder" in window;
      }}

      function pickRecorderMimeType() {{
        if (!("MediaRecorder" in window) || typeof MediaRecorder.isTypeSupported !== "function") {{
          return "";
        }}

        const candidates = [
          "audio/webm;codecs=opus",
          "audio/webm",
          "audio/mp4",
          "audio/ogg;codecs=opus",
        ];

        return candidates.find((candidate) => MediaRecorder.isTypeSupported(candidate)) || "";
      }}

      function clearRecordingTimer() {{
        if (recordingTimer) {{
          window.clearTimeout(recordingTimer);
          recordingTimer = null;
        }}
      }}

      function clearSilenceMonitor() {{
        if (silenceMonitor) {{
          window.clearTimeout(silenceMonitor);
          silenceMonitor = null;
        }}
      }}

      function closeAudioMonitor() {{
        clearSilenceMonitor();

        if (sourceNode) {{
          try {{
            sourceNode.disconnect();
          }} catch (error) {{
            console.debug("Audio source cleanup failed", error);
          }}
          sourceNode = null;
        }}

        if (analyserNode) {{
          try {{
            analyserNode.disconnect();
          }} catch (error) {{
            console.debug("Audio analyser cleanup failed", error);
          }}
          analyserNode = null;
        }}

        if (audioContext) {{
          const context = audioContext;
          audioContext = null;
          Promise.resolve(context.close()).catch((error) => {{
            console.debug("Audio context cleanup failed", error);
          }});
        }}

        speechDetected = false;
        recordingStartedAt = 0;
        lastSoundAt = 0;
        previewTranscriptQueued = false;
      }}

      function releaseMicStream() {{
        if (mediaStream) {{
          mediaStream.getTracks().forEach((track) => track.stop());
          mediaStream = null;
        }}
      }}

      function currentInputLevel() {{
        if (!analyserNode) {{
          return 0;
        }}

        const samples = new Uint8Array(analyserNode.fftSize);
        analyserNode.getByteTimeDomainData(samples);

        let sumSquares = 0;
        for (let index = 0; index < samples.length; index += 1) {{
          const normalized = (samples[index] - 128) / 128;
          sumSquares += normalized * normalized;
        }}

        return Math.sqrt(sumSquares / samples.length);
      }}

      function monitorForSilence() {{
        if (!mediaRecorder || mediaRecorder.state !== "recording") {{
          clearSilenceMonitor();
          return;
        }}

        const now = Date.now();
        const inputLevel = currentInputLevel();

        if (inputLevel >= SILENCE_LEVEL_THRESHOLD) {{
          speechDetected = true;
          lastSoundAt = now;
        }} else if (
          speechDetected
          && now - lastSoundAt >= SILENCE_STOP_MS
          && now - recordingStartedAt >= MIN_RECORDING_MS
        ) {{
          stopRecording(true, "Speech ended. Transcribing now...");
          return;
        }}

        silenceMonitor = window.setTimeout(monitorForSilence, 150);
      }}

      async function startAudioMonitor(stream) {{
        closeAudioMonitor();

        const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
        recordingStartedAt = Date.now();
        lastSoundAt = recordingStartedAt;
        speechDetected = false;

        if (!AudioContextCtor) {{
          return;
        }}

        audioContext = new AudioContextCtor();
        sourceNode = audioContext.createMediaStreamSource(stream);
        analyserNode = audioContext.createAnalyser();
        analyserNode.fftSize = 2048;
        sourceNode.connect(analyserNode);

        if (audioContext.state === "suspended") {{
          await audioContext.resume();
        }}

        monitorForSilence();
      }}

      async function requestMicrophoneStream() {{
        if (!secureMicContext()) {{
          throw new Error("Microphone input needs a secure browser page. Open FRIDAY from localhost or 127.0.0.1.");
        }}

        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {{
          throw new Error("This browser does not support microphone recording for FRIDAY. Try Microsoft Edge or Google Chrome.");
        }}

        return navigator.mediaDevices.getUserMedia({{
          audio: {{
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          }},
        }});
      }}

      function recordingFileName() {{
        if (micMimeType.includes("ogg")) {{
          return "friday-mic.ogg";
        }}
        if (micMimeType.includes("mp4")) {{
          return "friday-mic.m4a";
        }}
        return "friday-mic.webm";
      }}

      function currentRecordingBlob() {{
        return recordedChunks.length
          ? new Blob(recordedChunks, {{ type: micMimeType || recordedChunks[0].type || "audio/webm" }})
          : null;
      }}

      async function transcribeBlob(blob) {{
        const formData = new FormData();
        formData.append("audio", blob, recordingFileName());

        const response = await fetch("/api/transcribe", {{
          method: "POST",
          body: formData,
        }});
        const data = await response.json();

        if (!response.ok) {{
          throw new Error(data.error || "The transcription route failed.");
        }}

        return String(data.text || "").trim();
      }}

      function queueLiveTranscript(force = false) {{
        if (!appState.listening) {{
          return;
        }}

        if (previewTranscriptRequestInFlight) {{
          previewTranscriptQueued = true;
          return;
        }}

        void updateLiveTranscript(force, liveSessionId);
      }}

      async function updateLiveTranscript(force = false, sessionId = liveSessionId) {{
        if (!appState.listening || sessionId !== liveSessionId) {{
          return;
        }}

        const blob = currentRecordingBlob();
        if (!blob || blob.size < MIN_LIVE_TRANSCRIBE_BYTES) {{
          return;
        }}

        const now = Date.now();
        if (!force && now - livePreviewRequestAt < LIVE_TRANSCRIBE_INTERVAL_MS) {{
          return;
        }}

        previewTranscriptRequestInFlight = true;
        previewTranscriptQueued = false;
        livePreviewRequestAt = now;

        try {{
          const transcript = await transcribeBlob(blob);
          if (!transcript || sessionId !== liveSessionId || !appState.listening) {{
            return;
          }}

          livePreviewTranscript = transcript;
          promptInput.value = transcript;
          setVoiceStatus("Listening live. Keep speaking...", "ok");
        }} catch (error) {{
          console.debug("Live transcription update failed", error);
        }} finally {{
          if (sessionId === liveSessionId) {{
            previewTranscriptRequestInFlight = false;
            if (previewTranscriptQueued && appState.listening) {{
              void updateLiveTranscript(true, sessionId);
            }}
          }}
        }}
      }}

      async function transcribeRecording(blob) {{
        if (!blob || !blob.size) {{
          setVoiceStatus("I did not capture any audio. Try again and speak closer to the mic.", "warn");
          return;
        }}

        setBusy(true);
        setVoiceStatus("Transcribing your recording...", "ok");

        try {{
          const transcript = await transcribeBlob(blob);
          if (!transcript) {{
            setVoiceStatus("I captured audio, but the transcription came back empty. Try again and speak a little louder.", "warn");
            return;
          }}

          promptInput.value = transcript;
          setVoiceStatus("Voice captured. Sending it now.", "ok");
          setBusy(false);
          await sendPrompt(transcript);
          return;
        }} catch (error) {{
          console.error("Audio transcription failed", error);
          if (livePreviewTranscript.trim()) {{
            const transcript = livePreviewTranscript.trim();
            promptInput.value = transcript;
            setVoiceStatus("Final transcription failed, so I am using the live transcript I already captured.", "warn");
            setBusy(false);
            await sendPrompt(transcript);
            return;
          }}
          setVoiceStatus("The local transcription route could not be reached. Try again or type your request instead.", "warn");
        }} finally {{
          if (appState.busy) {{
            setBusy(false);
          }}
        }}
      }}

      function stopRecording(autoStopped = false, statusMessage = "") {{
        clearRecordingTimer();
        clearSilenceMonitor();
        if (!mediaRecorder || mediaRecorder.state === "inactive") {{
          appState.listening = false;
          appState.micStarting = false;
          updateMicButton();
          return;
        }}

        setVoiceStatus(
          statusMessage || (autoStopped
            ? "Recording limit reached. Transcribing now..."
            : "Processing your recording..."),
          "ok"
        );
        mediaRecorder.stop();
      }}

      async function startRecording() {{
        promptInput.value = "";
        appState.micStarting = true;
        liveSessionId += 1;
        livePreviewTranscript = "";
        livePreviewRequestAt = 0;
        previewTranscriptRequestInFlight = false;
        previewTranscriptQueued = false;
        setVoiceStatus("Starting microphone...");
        updateMicButton();

        try {{
          mediaStream = await requestMicrophoneStream();
          await startAudioMonitor(mediaStream);
          recordedChunks = [];
          micMimeType = pickRecorderMimeType();
          const recorderOptions = micMimeType
            ? {{ mimeType: micMimeType, audioBitsPerSecond: RECORDER_AUDIO_BITS_PER_SECOND }}
            : {{ audioBitsPerSecond: RECORDER_AUDIO_BITS_PER_SECOND }};
          mediaRecorder = new MediaRecorder(mediaStream, recorderOptions);

          mediaRecorder.ondataavailable = (event) => {{
            if (event.data && event.data.size > 0) {{
              recordedChunks.push(event.data);
              if (appState.listening && Date.now() - recordingStartedAt >= MIN_RECORDING_MS) {{
                queueLiveTranscript();
              }}
            }}
          }};

          mediaRecorder.onstart = () => {{
            appState.micStarting = false;
            appState.listening = true;
            setVoiceStatus("Listening live. Speak now and I will keep up with you.", "ok");
            updateMicButton();
            clearRecordingTimer();
            recordingTimer = window.setTimeout(() => {{
              stopRecording(true, "Recording limit reached. Transcribing now...");
            }}, MAX_RECORDING_MS);
          }};

          mediaRecorder.onerror = (event) => {{
            appState.micStarting = false;
            appState.listening = false;
            clearRecordingTimer();
            closeAudioMonitor();
            releaseMicStream();
            mediaRecorder = null;
            const detail = event.error && event.error.message
              ? event.error.message
              : "The browser could not record from your microphone.";
            setVoiceStatus(detail, "warn");
            updateMicButton();
          }};

          mediaRecorder.onstop = async () => {{
            const blob = recordedChunks.length
              ? new Blob(recordedChunks, {{ type: micMimeType || recordedChunks[0].type || "audio/webm" }})
              : null;
            recordedChunks = [];
            clearRecordingTimer();
            closeAudioMonitor();
            releaseMicStream();
            mediaRecorder = null;
            appState.listening = false;
            appState.micStarting = false;
            updateMicButton();

            if (!blob || !blob.size) {{
              setVoiceStatus("I did not capture any audio. Try again and speak closer to the mic.", "warn");
              return;
            }}

            await transcribeRecording(blob);
          }};

          mediaRecorder.start(LIVE_CHUNK_MS);
        }} catch (error) {{
          appState.micStarting = false;
          appState.listening = false;
          clearRecordingTimer();
          closeAudioMonitor();
          releaseMicStream();
          mediaRecorder = null;
          const detail = error instanceof Error && error.message
            ? error.message
            : "The browser could not access your microphone.";
          setVoiceStatus(detail, "warn");
          updateMicButton();
        }}
      }}

      function setupMicrophone() {{
        if (!secureMicContext()) {{
          setVoiceStatus("Mic input needs a secure browser page. Open FRIDAY from localhost or 127.0.0.1.", "warn");
          updateMicButton();
          return;
        }}

        if (!supportsRecordedMic()) {{
          setVoiceStatus("Mic input needs browser recording support. Try Microsoft Edge or Google Chrome, or type your request here.", "warn");
          updateMicButton();
          return;
        }}

        micMimeType = pickRecorderMimeType();
        if (!("speechSynthesis" in window)) {{
          setVoiceStatus("Mic input is ready, but this browser cannot speak replies aloud. Text replies still work.", "warn");
        }} else {{
          setVoiceStatus("Voice idle. Click Start Mic and speak. FRIDAY will stream the words as you talk, then send when you stop.");
        }}

        updateMicButton();
      }}

      document.querySelectorAll("[data-copy]").forEach((button) => {{
        button.addEventListener("click", () => copyText(button.dataset.copy, button));
      }});

      dispatchMode.addEventListener("change", updateComposerMode);
      sendButton.addEventListener("click", () => sendPrompt(promptInput.value));
      promptInput.addEventListener("keydown", (event) => {{
        if (event.key === "Enter" && !event.shiftKey) {{
          event.preventDefault();
          sendPrompt(promptInput.value);
        }}
      }});

      micButton.addEventListener("click", async () => {{
        if (!supportsRecordedMic() || appState.busy || appState.micStarting) {{
          return;
        }}

        if (appState.listening) {{
          stopRecording();
        }} else {{
          await startRecording();
        }}
        updateMicButton();
      }});

      speakToggle.addEventListener("change", () => {{
        appState.speakReplies = speakToggle.checked;
        if (!appState.speakReplies) {{
          setVoiceStatus("Reply speech is muted. Text replies will still appear in the log.");
        }} else if (!("speechSynthesis" in window)) {{
          setVoiceStatus("Reply speech was enabled, but this browser cannot play spoken replies.", "warn");
        }} else if (!appState.listening && !appState.micStarting) {{
          setVoiceStatus("Voice idle. Click Start Mic or type your request.");
        }}
      }});

      stopSpeechButton.addEventListener("click", () => {{
        if ("speechSynthesis" in window) {{
          window.speechSynthesis.cancel();
          setVoiceStatus("Stopped spoken reply.");
        }}
      }});

      setupMicrophone();
      updateComposerMode();
      renderMessages();
      refreshStatus();
      setBusy(false);
      window.setInterval(refreshStatus, 15000);
    </script>
  </body>
</html>
"""


def register_web_routes(mcp) -> None:
    def _needs_browser_redirect(request: Request) -> bool:
        return _canonical_browser_host(request.url.hostname) != (request.url.hostname or "")

    @mcp.custom_route("/", methods=["GET"], include_in_schema=False)
    async def local_console(request: Request) -> Response:
        if _needs_browser_redirect(request):
            return RedirectResponse(f"{_browser_base_url(request)}/", status_code=307)
        return HTMLResponse(_render_page(request))

    @mcp.custom_route("/status", methods=["GET"], include_in_schema=False)
    async def local_status(request: Request) -> Response:
        if _needs_browser_redirect(request):
            return RedirectResponse(f"{_browser_base_url(request)}/status", status_code=307)
        return JSONResponse(_local_status(request))

    @mcp.custom_route("/api/chat", methods=["POST"], include_in_schema=False)
    async def local_chat_api(request: Request) -> Response:
        if _needs_browser_redirect(request):
            return RedirectResponse(f"{_browser_base_url(request)}/", status_code=307)

        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body."}, status_code=400)

        messages = payload.get("messages")
        if not isinstance(messages, list):
            return JSONResponse({"error": "messages must be a list."}, status_code=400)

        try:
            result = await run_local_chat(messages, _mcp_server_url(request))
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:  # pragma: no cover - defensive route guard
            runtime_detail = _nested_runtime_error(exc)
            if runtime_detail:
                return JSONResponse({"error": runtime_detail}, status_code=400)
            logger.exception("Local chat request failed")
            return JSONResponse(
                {"error": f"Local chat failed unexpectedly: {exc}"},
                status_code=500,
            )

        return JSONResponse(
            {
                "reply": result.reply,
                "tool_events": result.tool_events,
            }
        )

    @mcp.custom_route("/api/transcribe", methods=["POST"], include_in_schema=False)
    async def local_transcribe_api(request: Request) -> Response:
        if _needs_browser_redirect(request):
            return RedirectResponse(f"{_browser_base_url(request)}/", status_code=307)

        try:
            form = await request.form()
        except Exception:
            return JSONResponse({"error": "Invalid audio upload."}, status_code=400)

        audio = form.get("audio")
        if audio is None:
            return JSONResponse({"error": "audio file is required."}, status_code=400)

        filename = getattr(audio, "filename", None) or "friday-mic.webm"
        content_type = getattr(audio, "content_type", None) or "audio/webm"

        try:
            audio_bytes = await audio.read()
        except Exception:
            return JSONResponse({"error": "Could not read the uploaded audio."}, status_code=400)

        try:
            transcript = await transcribe_browser_audio(
                audio_bytes,
                filename=filename,
                content_type=content_type,
            )
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:  # pragma: no cover - defensive route guard
            logger.exception("Local transcription failed")
            return JSONResponse(
                {"error": f"Local transcription failed unexpectedly: {exc}"},
                status_code=500,
            )

        return JSONResponse({"text": transcript})

    @mcp.custom_route("/api/codex/relay", methods=["POST"], include_in_schema=False)
    async def codex_relay_api(request: Request) -> Response:
        if _needs_browser_redirect(request):
            return RedirectResponse(f"{_browser_base_url(request)}/", status_code=307)

        try:
            payload = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body."}, status_code=400)

        prompt = str(payload.get("prompt", "")).strip()
        project_path = str(payload.get("project_path", "")).strip()
        if not prompt:
            return JSONResponse({"error": "prompt is required."}, status_code=400)

        try:
            result = dispatch_to_vscode_codex(prompt, project_path=project_path)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:  # pragma: no cover - defensive route guard
            logger.exception("Codex relay request failed")
            return JSONResponse(
                {"error": f"Codex relay failed unexpectedly: {exc}"},
                status_code=500,
            )

        return JSONResponse(result)

    @mcp.custom_route("/connect", methods=["GET"], include_in_schema=False)
    async def legacy_connect_redirect(request: Request) -> Response:
        if _needs_browser_redirect(request):
            return RedirectResponse(f"{_browser_base_url(request)}/", status_code=307)
        return RedirectResponse(f"{_browser_base_url(request)}/#pilot-console", status_code=307)
