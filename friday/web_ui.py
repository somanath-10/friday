"""
Simple web UI routes for launching and monitoring the FRIDAY connection flow.
"""

from __future__ import annotations

import html
import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response


PLAYGROUND_URL = "https://agents-playground.livekit.io"


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

    if parts.port:
        netloc = f"{host}:{parts.port}"
    else:
        netloc = host

    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _browser_base_url(request: Request) -> str:
    scheme = request.url.scheme
    host = _canonical_browser_host(request.url.hostname)
    port = request.url.port

    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    if port and not default_port:
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def _required_env_vars() -> list[str]:
    required = [
        "LIVEKIT_URL",
        "LIVEKIT_API_KEY",
        "LIVEKIT_API_SECRET",
    ]

    stt_provider = os.getenv("STT_PROVIDER", "deepgram").strip().lower()
    llm_provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    tts_provider = os.getenv("TTS_PROVIDER", "sarvam").strip().lower()

    if stt_provider == "deepgram":
        required.append("DEEPGRAM_API_KEY")
    elif stt_provider == "sarvam":
        required.append("SARVAM_API_KEY")
    elif stt_provider == "whisper":
        required.append("OPENAI_API_KEY")

    if llm_provider == "gemini":
        required.append("GOOGLE_API_KEY")
    elif llm_provider == "openai":
        required.append("OPENAI_API_KEY")

    if tts_provider == "sarvam":
        required.append("SARVAM_API_KEY")
    elif tts_provider == "openai":
        required.append("OPENAI_API_KEY")

    return sorted(set(required))


def _connection_state(request: Request | None = None) -> dict[str, Any]:
    server_name = os.getenv("SERVER_NAME", "Friday").strip() or "Friday"
    livekit_url = os.getenv("LIVEKIT_URL", "").strip()
    sse_path = os.getenv("MCP_SSE_PATH", "/sse").strip() or "/sse"
    mcp_server_url = _canonicalize_url(os.getenv("MCP_SERVER_URL", "").strip())

    if not mcp_server_url and request is not None:
        base_url = _browser_base_url(request)
        mcp_server_url = f"{base_url}{sse_path}"
    elif not mcp_server_url:
        port = os.getenv("MCP_SERVER_PORT", "8000").strip() or "8000"
        mcp_server_url = f"http://127.0.0.1:{port}{sse_path}"

    missing = [name for name in _required_env_vars() if not os.getenv(name)]
    stt_provider = os.getenv("STT_PROVIDER", "deepgram").strip().lower()
    llm_provider = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
    tts_provider = os.getenv("TTS_PROVIDER", "sarvam").strip().lower()

    return {
        "server_name": server_name,
        "playground_url": PLAYGROUND_URL,
        "mcp_server_url": mcp_server_url,
        "livekit_url": livekit_url,
        "stt_provider": stt_provider,
        "llm_provider": llm_provider,
        "tts_provider": tts_provider,
        "missing_env": missing,
        "ready": not missing,
    }


def _render_page(request: Request) -> str:
    state = _connection_state(request)

    server_name = html.escape(state["server_name"])
    mcp_server_url = html.escape(state["mcp_server_url"])
    livekit_url = html.escape(state["livekit_url"] or "Not configured yet")
    provider_stack = html.escape(
        f"{state['stt_provider']} -> {state['llm_provider']} -> {state['tts_provider']}"
    )
    readiness_label = "Ready To Connect" if state["ready"] else "Needs Configuration"
    readiness_tone = "ready" if state["ready"] else "warn"
    missing_items = "".join(
        f"<li>{html.escape(item)}</li>" for item in state["missing_env"]
    ) or "<li>No missing environment variables detected.</li>"

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{server_name} Connection Deck</title>
    <style>
      :root {{
        --bg: #07111a;
        --bg-soft: #102231;
        --panel: rgba(10, 21, 32, 0.84);
        --panel-strong: rgba(12, 27, 41, 0.96);
        --edge: rgba(115, 144, 171, 0.22);
        --text: #eef6ff;
        --muted: #92a6bd;
        --accent: #ff7a45;
        --accent-2: #29d3c1;
        --success: #52d68b;
        --warning: #ffc857;
        --danger: #ff6f7d;
        --shadow: 0 24px 80px rgba(0, 0, 0, 0.35);
        --radius: 24px;
      }}

      * {{
        box-sizing: border-box;
      }}

      body {{
        margin: 0;
        min-height: 100vh;
        font-family: "Segoe UI Variable Display", "Aptos", "Trebuchet MS", sans-serif;
        color: var(--text);
        background:
          radial-gradient(circle at top left, rgba(255, 122, 69, 0.18), transparent 28%),
          radial-gradient(circle at top right, rgba(41, 211, 193, 0.16), transparent 24%),
          linear-gradient(135deg, #08111a 0%, #0a1823 40%, #111a26 100%);
        overflow-x: hidden;
      }}

      body::before {{
        content: "";
        position: fixed;
        inset: 0;
        background:
          linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px);
        background-size: 28px 28px;
        mask-image: linear-gradient(to bottom, rgba(0,0,0,0.4), transparent 85%);
        pointer-events: none;
      }}

      .shell {{
        width: min(1120px, calc(100% - 32px));
        margin: 32px auto;
        display: grid;
        gap: 20px;
      }}

      .hero {{
        position: relative;
        padding: 32px;
        border: 1px solid var(--edge);
        border-radius: calc(var(--radius) + 8px);
        background: linear-gradient(145deg, rgba(13, 28, 43, 0.9), rgba(8, 18, 29, 0.9));
        box-shadow: var(--shadow);
        overflow: hidden;
      }}

      .hero::after {{
        content: "";
        position: absolute;
        width: 220px;
        height: 220px;
        border-radius: 50%;
        background: radial-gradient(circle, rgba(255, 122, 69, 0.28), transparent 68%);
        top: -70px;
        right: -30px;
      }}

      .eyebrow {{
        display: inline-flex;
        align-items: center;
        gap: 10px;
        padding: 8px 12px;
        border-radius: 999px;
        border: 1px solid rgba(255,255,255,0.12);
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
        background: var(--accent-2);
        box-shadow: 0 0 0 0 rgba(41, 211, 193, 0.5);
        animation: pulse 1.8s infinite;
      }}

      @keyframes pulse {{
        0% {{ box-shadow: 0 0 0 0 rgba(41, 211, 193, 0.55); }}
        70% {{ box-shadow: 0 0 0 14px rgba(41, 211, 193, 0); }}
        100% {{ box-shadow: 0 0 0 0 rgba(41, 211, 193, 0); }}
      }}

      h1 {{
        margin: 18px 0 10px;
        max-width: 12ch;
        font-size: clamp(2.6rem, 7vw, 5rem);
        line-height: 0.95;
        letter-spacing: -0.05em;
      }}

      .hero p {{
        margin: 0;
        max-width: 60ch;
        color: var(--muted);
        font-size: 1.02rem;
        line-height: 1.7;
      }}

      .hero-actions {{
        margin-top: 26px;
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
        cursor: pointer;
        text-decoration: none;
        transition: transform 150ms ease, border-color 150ms ease, background 150ms ease;
      }}

      .button:hover {{
        transform: translateY(-1px);
      }}

      .button-primary {{
        color: #08111a;
        background: linear-gradient(135deg, var(--accent), #ffb347);
      }}

      .button-secondary {{
        color: var(--text);
        background: rgba(255,255,255,0.04);
        border-color: rgba(255,255,255,0.1);
      }}

      .grid {{
        display: grid;
        grid-template-columns: repeat(12, 1fr);
        gap: 20px;
      }}

      .card {{
        grid-column: span 12;
        padding: 24px;
        border-radius: var(--radius);
        border: 1px solid var(--edge);
        background: var(--panel);
        backdrop-filter: blur(12px);
        box-shadow: var(--shadow);
      }}

      .card h2 {{
        margin: 0 0 14px;
        font-size: 1.08rem;
        letter-spacing: 0.02em;
      }}

      .status-card {{
        grid-column: span 4;
      }}

      .stack-card {{
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
        color: #08111a;
        background: var(--success);
      }}

      .status-pill.warn {{
        color: #221b08;
        background: var(--warning);
      }}

      .metric {{
        display: grid;
        gap: 6px;
      }}

      .metric-label {{
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.12em;
        font-size: 0.72rem;
      }}

      .metric-value {{
        font-size: 1.15rem;
        font-weight: 700;
      }}

      .stack-grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 14px;
      }}

      .stack-box {{
        padding: 16px;
        border-radius: 18px;
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.06);
      }}

      .step-grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 16px;
      }}

      .step {{
        position: relative;
        padding: 18px 18px 20px;
        border-radius: 20px;
        background: var(--panel-strong);
        border: 1px solid rgba(255,255,255,0.07);
        min-height: 220px;
      }}

      .step-number {{
        display: inline-flex;
        width: 36px;
        height: 36px;
        align-items: center;
        justify-content: center;
        border-radius: 12px;
        background: linear-gradient(135deg, rgba(255,122,69,0.18), rgba(41,211,193,0.18));
        color: var(--text);
        font-weight: 800;
      }}

      .step h3 {{
        margin: 16px 0 8px;
        font-size: 1.05rem;
      }}

      .step p {{
        margin: 0 0 16px;
        color: var(--muted);
        line-height: 1.6;
      }}

      .terminal {{
        margin: 0 0 16px;
        padding: 14px;
        border-radius: 16px;
        background: #08111a;
        border: 1px solid rgba(255,255,255,0.08);
        font-family: "Cascadia Mono", "Consolas", monospace;
        font-size: 0.95rem;
        color: #d8ecff;
        overflow-x: auto;
      }}

      .meta-list {{
        list-style: none;
        margin: 16px 0 0;
        padding: 0;
        display: grid;
        gap: 12px;
      }}

      .meta-list li {{
        padding: 14px 16px;
        border-radius: 16px;
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.06);
      }}

      .meta-label {{
        display: block;
        color: var(--muted);
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        margin-bottom: 6px;
      }}

      .meta-value {{
        display: block;
        word-break: break-word;
        font-family: "Cascadia Mono", "Consolas", monospace;
        font-size: 0.92rem;
      }}

      .missing-list {{
        margin: 14px 0 0;
        padding-left: 18px;
        color: var(--muted);
      }}

      .status-note {{
        margin-top: 12px;
        color: var(--muted);
        line-height: 1.6;
      }}

      .live-dot {{
        display: inline-block;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: var(--success);
        margin-right: 8px;
      }}

      @media (max-width: 900px) {{
        .status-card,
        .stack-card {{
          grid-column: span 12;
        }}

        .stack-grid,
        .step-grid {{
          grid-template-columns: 1fr;
        }}

        .hero {{
          padding: 24px;
        }}
      }}
    </style>
  </head>
  <body>
    <main class="shell">
      <section class="hero">
        <div class="eyebrow"><span class="pulse"></span>Connection Deck</div>
        <h1>{server_name}</h1>
        <p>
          This page is the launch surface for your first session. Verify the stack,
          start the voice worker, then open the LiveKit playground to begin the connection.
        </p>
        <div class="hero-actions">
          <a class="button button-primary" href="/connect" target="_blank" rel="noreferrer">Start Connection</a>
          <button class="button button-secondary" type="button" data-copy="{mcp_server_url}">Copy MCP URL</button>
          <button class="button button-secondary" type="button" data-copy="uv run friday_voice">Copy Voice Command</button>
        </div>
      </section>

      <section class="grid">
        <article class="card status-card">
          <h2>Connection Status</h2>
          <div class="status-pill {readiness_tone}" id="readiness-pill">{readiness_label}</div>
          <p class="status-note">
            <span class="live-dot"></span>MCP server is online. Voice connection readiness depends on your LiveKit
            and provider keys.
          </p>
          <ul class="missing-list" id="missing-list">
            {missing_items}
          </ul>
        </article>

        <article class="card stack-card">
          <h2>Stack Snapshot</h2>
          <div class="stack-grid">
            <div class="stack-box">
              <div class="metric">
                <span class="metric-label">MCP Endpoint</span>
                <span class="metric-value" id="mcp-url">{mcp_server_url}</span>
              </div>
            </div>
            <div class="stack-box">
              <div class="metric">
                <span class="metric-label">LiveKit Target</span>
                <span class="metric-value" id="livekit-url">{livekit_url}</span>
              </div>
            </div>
            <div class="stack-box">
              <div class="metric">
                <span class="metric-label">Provider Chain</span>
                <span class="metric-value" id="provider-stack">{provider_stack}</span>
              </div>
            </div>
          </div>
        </article>
      </section>

      <section class="card">
        <h2>Launch Sequence</h2>
        <div class="step-grid">
          <article class="step">
            <span class="step-number">01</span>
            <h3>Bring Up The Voice Worker</h3>
            <p>The page is served by the MCP backend already. In a second terminal, start the LiveKit voice agent.</p>
            <pre class="terminal">uv run friday_voice</pre>
            <button class="button button-secondary" type="button" data-copy="uv run friday_voice">Copy Command</button>
          </article>

          <article class="step">
            <span class="step-number">02</span>
            <h3>Open The Connection Surface</h3>
            <p>Launch the LiveKit Agents Playground, join your room, and talk to FRIDAY once the worker is running.</p>
            <a class="button button-primary" href="/connect" target="_blank" rel="noreferrer">Open Playground</a>
          </article>

          <article class="step">
            <span class="step-number">03</span>
            <h3>Confirm The Backend Link</h3>
            <p>Your agent should fetch tools from this MCP endpoint while the session is live.</p>
            <pre class="terminal" id="mcp-url-block">{mcp_server_url}</pre>
            <button class="button button-secondary" type="button" data-copy="{mcp_server_url}">Copy Endpoint</button>
          </article>
        </div>
      </section>

      <section class="card">
        <h2>Session Notes</h2>
        <ul class="meta-list">
          <li>
            <span class="meta-label">What This Page Does</span>
            <span class="meta-value">Verifies connection readiness, exposes the MCP endpoint, and launches the LiveKit playground.</span>
          </li>
          <li>
            <span class="meta-label">What Still Runs Separately</span>
            <span class="meta-value">The voice worker itself. Keep <code>uv run friday_voice</code> active while you connect.</span>
          </li>
          <li>
            <span class="meta-label">Live Status Endpoint</span>
            <span class="meta-value"><a href="/status" style="color: var(--accent-2);">/status</a></span>
          </li>
        </ul>
      </section>
    </main>

    <script>
      async function refreshStatus() {{
        try {{
          const response = await fetch('/status', {{ headers: {{ 'Accept': 'application/json' }} }});
          const status = await response.json();
          const pill = document.getElementById('readiness-pill');
          const missingList = document.getElementById('missing-list');
          document.getElementById('mcp-url').textContent = status.mcp_server_url;
          document.getElementById('livekit-url').textContent = status.livekit_url || 'Not configured yet';
          document.getElementById('provider-stack').textContent = `${{status.stt_provider}} -> ${{status.llm_provider}} -> ${{status.tts_provider}}`;
          document.getElementById('mcp-url-block').textContent = status.mcp_server_url;

          pill.textContent = status.ready ? 'Ready To Connect' : 'Needs Configuration';
          pill.className = `status-pill ${{status.ready ? 'ready' : 'warn'}}`;

          if (status.missing_env.length) {{
            missingList.innerHTML = status.missing_env.map((item) => `<li>${{item}}</li>`).join('');
          }} else {{
            missingList.innerHTML = '<li>No missing environment variables detected.</li>';
          }}

          document.querySelectorAll('[data-copy]').forEach((button) => {{
            const value = button.dataset.copy;
            if (value === '{mcp_server_url}') {{
              button.dataset.copy = status.mcp_server_url;
            }}
          }});
        }} catch (error) {{
          console.error('Status refresh failed', error);
        }}
      }}

      async function copyText(value, button) {{
        try {{
          await navigator.clipboard.writeText(value);
          const original = button.textContent;
          button.textContent = 'Copied';
          window.setTimeout(() => {{
            button.textContent = original;
          }}, 1400);
        }} catch (error) {{
          console.error('Clipboard copy failed', error);
        }}
      }}

      document.querySelectorAll('[data-copy]').forEach((button) => {{
        button.addEventListener('click', () => copyText(button.dataset.copy, button));
      }});

      refreshStatus();
      window.setInterval(refreshStatus, 15000);
    </script>
  </body>
</html>
"""


def register_web_routes(mcp) -> None:
    def _needs_browser_redirect(request: Request) -> bool:
        return _canonical_browser_host(request.url.hostname) != (request.url.hostname or "")

    @mcp.custom_route("/", methods=["GET"], include_in_schema=False)
    async def connection_page(request: Request) -> Response:
        if _needs_browser_redirect(request):
            return RedirectResponse(f"{_browser_base_url(request)}/", status_code=307)
        return HTMLResponse(_render_page(request))

    @mcp.custom_route("/status", methods=["GET"], include_in_schema=False)
    async def connection_status(request: Request) -> Response:
        if _needs_browser_redirect(request):
            return RedirectResponse(f"{_browser_base_url(request)}/status", status_code=307)
        return JSONResponse(_connection_state(request))

    @mcp.custom_route("/connect", methods=["GET"], include_in_schema=False)
    async def connection_redirect(request: Request) -> Response:
        if _needs_browser_redirect(request):
            return RedirectResponse(f"{_browser_base_url(request)}/connect", status_code=307)
        return RedirectResponse(PLAYGROUND_URL, status_code=307)
