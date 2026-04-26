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

from friday.config import build_runtime_status
from friday.codex_bridge import codex_relay_status, dispatch_to_vscode_codex
from friday.local_chat import (
    local_greeting,
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
    if request is not None:
        return f"{_browser_base_url(request)}{sse_path}"

    configured = _canonicalize_url(os.getenv("MCP_SERVER_URL", "").strip())
    if configured:
        return configured

    port = os.getenv("MCP_SERVER_PORT", "8000").strip() or "8000"
    return f"http://127.0.0.1:{port}{sse_path}"


def _local_status(request: Request | None = None) -> dict[str, Any]:
    status = build_runtime_status(mode="local-browser")
    codex_status = codex_relay_status()

    status.update(
        {
        "mcp_server_url": _mcp_server_url(request),
        "browser_voice_input": "MediaRecorder microphone capture with backend transcription",
        "browser_voice_output": "speechSynthesis",
        "greeting": local_greeting(),
        "codex_relay": codex_status,
        }
    )
    return status


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

      body {{
        font-family: "Bahnschrift SemiCondensed", "Segoe UI Variable Display", "Aptos", sans-serif;
        letter-spacing: 0.01em;
        background:
          radial-gradient(circle at 18% 16%, rgba(255, 134, 52, 0.24), transparent 22%),
          radial-gradient(circle at 82% 8%, rgba(88, 223, 255, 0.16), transparent 18%),
          radial-gradient(circle at 52% 112%, rgba(255, 110, 30, 0.18), transparent 28%),
          linear-gradient(180deg, #02060b 0%, #07111a 38%, #03080d 100%);
      }}

      body::before {{
        background:
          linear-gradient(rgba(78, 170, 219, 0.07) 1px, transparent 1px),
          linear-gradient(90deg, rgba(78, 170, 219, 0.06) 1px, transparent 1px),
          radial-gradient(circle at 50% 0%, rgba(255, 140, 60, 0.08), transparent 40%);
        background-size: 34px 34px, 34px 34px, auto;
        mask-image: linear-gradient(to bottom, rgba(0,0,0,0.72), transparent 92%);
      }}

      body::after {{
        content: "";
        position: fixed;
        inset: 0;
        pointer-events: none;
        background: linear-gradient(180deg, transparent 0%, rgba(97, 224, 255, 0.05) 48%, transparent 100%);
        transform: translateY(-100%);
        animation: hud-sweep 9s linear infinite;
        opacity: 0.7;
      }}

      @keyframes hud-sweep {{
        0% {{ transform: translateY(-110%); }}
        100% {{ transform: translateY(120%); }}
      }}

      @keyframes orbit-spin {{
        from {{ transform: rotate(0deg); }}
        to {{ transform: rotate(360deg); }}
      }}

      @keyframes orbit-pulse {{
        0%, 100% {{ opacity: 0.55; transform: scale(0.985); }}
        50% {{ opacity: 1; transform: scale(1.015); }}
      }}

      .shell {{
        position: relative;
        width: min(1320px, calc(100% - 28px));
        gap: 24px;
      }}

      .hero {{
        padding: 32px;
        border-radius: 32px;
        background:
          linear-gradient(140deg, rgba(10, 24, 36, 0.97), rgba(5, 12, 19, 0.98)),
          radial-gradient(circle at top right, rgba(92, 214, 255, 0.12), transparent 32%);
        border-color: rgba(93, 199, 255, 0.16);
        box-shadow:
          0 34px 110px rgba(0, 0, 0, 0.42),
          inset 0 1px 0 rgba(255, 255, 255, 0.05),
          inset 0 0 0 1px rgba(255, 170, 104, 0.04);
      }}

      .hero::before {{
        content: "";
        position: absolute;
        inset: 14px;
        border-radius: 24px;
        border: 1px solid rgba(92, 196, 255, 0.08);
        pointer-events: none;
      }}

      .hero::after {{
        width: 420px;
        height: 420px;
        top: -160px;
        right: -130px;
        background: radial-gradient(circle, rgba(91, 219, 255, 0.2), transparent 68%);
      }}

      .hero-grid {{
        position: relative;
        z-index: 1;
        display: grid;
        grid-template-columns: minmax(0, 1.25fr) minmax(280px, 360px);
        gap: 30px;
        align-items: center;
      }}

      .hero-copy {{
        display: grid;
        gap: 18px;
      }}

      .eyebrow {{
        width: fit-content;
        background: linear-gradient(135deg, rgba(255, 139, 64, 0.12), rgba(76, 212, 255, 0.08));
        border-color: rgba(255, 170, 96, 0.24);
        color: #8fb3cd;
        box-shadow: inset 0 0 0 1px rgba(255,255,255,0.03);
      }}

      .pulse {{
        background: var(--accent);
        box-shadow: 0 0 0 0 rgba(255, 124, 44, 0.45);
      }}

      @keyframes pulse {{
        0% {{ box-shadow: 0 0 0 0 rgba(255, 124, 44, 0.48); }}
        70% {{ box-shadow: 0 0 0 16px rgba(255, 124, 44, 0); }}
        100% {{ box-shadow: 0 0 0 0 rgba(255, 124, 44, 0); }}
      }}

      h1 {{
        max-width: 10ch;
        margin: 0;
        font-family: "Bahnschrift", "Segoe UI Variable Display", sans-serif;
        font-size: clamp(3.4rem, 8vw, 6.2rem);
        line-height: 0.9;
        letter-spacing: -0.085em;
        text-transform: uppercase;
      }}

      .hero p {{
        max-width: 58ch;
        color: #8eaabf;
        font-size: 1.06rem;
        line-height: 1.82;
      }}

      .status-ribbon {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 12px;
      }}

      .status-node {{
        padding: 14px 16px;
        border-radius: 18px;
        background: linear-gradient(180deg, rgba(6, 18, 29, 0.88), rgba(4, 12, 20, 0.96));
        border: 1px solid rgba(88, 193, 255, 0.14);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
      }}

      .status-node-label {{
        display: block;
        margin-bottom: 8px;
        color: #6e8ca2;
        font-size: 0.68rem;
        letter-spacing: 0.18em;
        text-transform: uppercase;
      }}

      .status-node-value {{
        display: flex;
        align-items: center;
        gap: 8px;
        color: #f0f7ff;
        font-size: 0.96rem;
        font-weight: 700;
      }}

      .status-dot {{
        width: 9px;
        height: 9px;
        border-radius: 50%;
        background: var(--cool);
        box-shadow: 0 0 18px rgba(42, 209, 190, 0.42);
      }}

      .status-dot.warn {{
        background: var(--warn);
        box-shadow: 0 0 18px rgba(255, 200, 87, 0.4);
      }}

      .hero-actions {{
        margin-top: 2px;
      }}

      .button {{
        position: relative;
        overflow: hidden;
        border-radius: 14px;
        padding: 14px 18px;
        font-family: "Bahnschrift SemiCondensed", "Segoe UI Variable Display", sans-serif;
        letter-spacing: 0.09em;
        text-transform: uppercase;
      }}

      .button::before {{
        content: "";
        position: absolute;
        inset: 0;
        background: linear-gradient(120deg, transparent, rgba(255,255,255,0.16), transparent);
        transform: translateX(-140%);
        transition: transform 220ms ease;
      }}

      .button:hover::before {{
        transform: translateX(130%);
      }}

      .button-primary {{
        color: #1b0e06;
        background: linear-gradient(135deg, #ffbe6a 0%, #ff7c2c 54%, #ff5e1f 100%);
        box-shadow: 0 0 28px rgba(255, 123, 44, 0.22);
      }}

      .button-secondary {{
        border-color: rgba(94, 203, 255, 0.18);
        background: linear-gradient(180deg, rgba(9, 25, 39, 0.84), rgba(6, 15, 24, 0.96));
        color: #d9f2ff;
      }}

      .hero-visual {{
        display: grid;
        gap: 18px;
        justify-items: center;
      }}

      .sphere-panel {{
        width: min(100%, 360px);
        display: grid;
        gap: 14px;
      }}

      .sphere-stage {{
        position: relative;
        width: 100%;
        aspect-ratio: 1;
        overflow: hidden;
        border-radius: 50%;
        border: 1px solid rgba(95, 204, 255, 0.16);
        background:
          radial-gradient(circle at 50% 50%, rgba(86, 216, 255, 0.12), transparent 32%),
          radial-gradient(circle at 50% 50%, rgba(255, 126, 44, 0.09), transparent 52%),
          linear-gradient(180deg, rgba(6, 17, 27, 0.94), rgba(3, 10, 16, 0.98));
        box-shadow:
          0 0 0 1px rgba(255,255,255,0.03) inset,
          0 0 42px rgba(74, 201, 255, 0.09),
          0 0 90px rgba(255, 124, 44, 0.08);
        cursor: default;
      }}

      .sphere-stage::before {{
        content: "";
        position: absolute;
        inset: 10%;
        border-radius: 50%;
        border: 1px solid rgba(84, 210, 255, 0.16);
        box-shadow:
          0 0 38px rgba(72, 197, 255, 0.08),
          inset 0 0 28px rgba(255, 119, 39, 0.05);
        animation: orbit-pulse 4.8s ease-in-out infinite;
        pointer-events: none;
      }}

      .sphere-stage::after {{
        position: absolute;
        content: "";
        inset: 20%;
        border-radius: 50%;
        border: 1px dashed rgba(96, 211, 255, 0.18);
        opacity: 0.46;
        animation: orbit-spin 26s linear infinite;
        pointer-events: none;
      }}

      .sphere-stage[data-state="arming"] {{
        border-color: rgba(255, 210, 102, 0.34);
        box-shadow:
          0 0 0 1px rgba(255,255,255,0.03) inset,
          0 0 48px rgba(255, 208, 102, 0.14),
          0 0 92px rgba(255, 167, 83, 0.12);
      }}

      .sphere-stage[data-state="thinking"] {{
        border-color: rgba(112, 222, 255, 0.28);
        box-shadow:
          0 0 0 1px rgba(255,255,255,0.03) inset,
          0 0 52px rgba(83, 214, 255, 0.12),
          0 0 102px rgba(129, 229, 255, 0.12);
      }}

      .sphere-stage[data-state="listening"] {{
        border-color: rgba(104, 239, 235, 0.34);
        box-shadow:
          0 0 0 1px rgba(255,255,255,0.03) inset,
          0 0 56px rgba(84, 238, 214, 0.18),
          0 0 118px rgba(70, 214, 255, 0.14);
      }}

      .sphere-stage[data-state="speaking"] {{
        border-color: rgba(255, 154, 86, 0.34);
        box-shadow:
          0 0 0 1px rgba(255,255,255,0.03) inset,
          0 0 56px rgba(255, 146, 88, 0.18),
          0 0 118px rgba(255, 118, 53, 0.15);
      }}

      .sphere-stage[data-state="arming"]::before,
      .sphere-stage[data-state="thinking"]::before,
      .sphere-stage[data-state="listening"]::before,
      .sphere-stage[data-state="speaking"]::before {{
        animation-duration: 2.2s;
      }}

      .sphere-stage[data-state="listening"]::before {{
        border-color: rgba(104, 239, 235, 0.32);
        animation-duration: 1.35s;
      }}

      .sphere-stage[data-state="speaking"]::before {{
        border-color: rgba(255, 171, 108, 0.34);
        animation-duration: 1.55s;
      }}

      .sphere-stage[data-state="listening"]::after,
      .sphere-stage[data-state="speaking"]::after {{
        opacity: 0.72;
      }}

      .sphere-stage[data-state="thinking"] .sphere-badge strong {{
        color: #cdefff;
      }}

      .sphere-stage[data-state="listening"] .sphere-badge strong {{
        color: #96fff1;
      }}

      .sphere-stage[data-state="speaking"] .sphere-badge strong {{
        color: #ffd1b1;
      }}

      .sphere-canvas {{
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
      }}

      .sphere-orbit {{
        position: absolute;
        inset: 0;
        border-radius: 50%;
        border: 1px solid rgba(96, 211, 255, 0.12);
        pointer-events: none;
      }}

      .sphere-orbit.orbit-a {{
        inset: 6%;
        border-top-color: rgba(255, 146, 70, 0.8);
        border-right-color: rgba(88, 223, 255, 0.42);
        animation: orbit-spin 16s linear infinite;
      }}

      .sphere-orbit.orbit-b {{
        inset: 18%;
        border-bottom-color: rgba(255, 183, 102, 0.72);
        border-left-color: rgba(90, 206, 255, 0.38);
        animation: orbit-spin 10s linear infinite reverse;
      }}

      .sphere-orbit.orbit-c {{
        inset: 31%;
        border-top-color: rgba(255, 139, 64, 0.7);
        border-left-color: rgba(97, 224, 255, 0.34);
        animation: orbit-spin 7.5s linear infinite;
      }}

      .sphere-glow {{
        position: absolute;
        border-radius: 50%;
        filter: blur(32px);
        pointer-events: none;
      }}

      .sphere-glow.glow-a {{
        position: relative;
        width: 34%;
        height: 34%;
        left: 33%;
        top: 33%;
        background: radial-gradient(circle, rgba(88, 223, 255, 0.38), transparent 72%);
      }}

      .sphere-stage[data-state="listening"] .sphere-glow.glow-a {{
        background: radial-gradient(circle, rgba(90, 255, 226, 0.42), transparent 72%);
      }}

      .sphere-stage[data-state="speaking"] .sphere-glow.glow-a {{
        background: radial-gradient(circle, rgba(255, 160, 98, 0.42), transparent 72%);
      }}

      .sphere-glow.glow-b {{
        width: 28%;
        height: 28%;
        left: 40%;
        top: 40%;
        background: radial-gradient(circle, rgba(255, 129, 47, 0.18), transparent 72%);
      }}

      .sphere-badge {{
        position: absolute;
        left: 50%;
        bottom: 8%;
        transform: translateX(-50%);
        min-width: 180px;
        padding: 12px 14px;
        border-radius: 18px;
        border: 1px solid rgba(90, 207, 255, 0.18);
        background: rgba(4, 11, 19, 0.7);
        backdrop-filter: blur(14px);
        text-align: center;
        pointer-events: none;
        box-shadow: 0 14px 36px rgba(0,0,0,0.22);
      }}

      .sphere-badge span {{
        display: block;
        color: #7391a8;
        font-size: 0.66rem;
        letter-spacing: 0.2em;
        text-transform: uppercase;
      }}

      .sphere-badge strong {{
        display: block;
        margin-top: 6px;
        color: #f1f8ff;
        font-size: 1rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }}

      .sphere-readouts {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 12px;
      }}

      .sphere-readout {{
        padding: 14px 16px;
        border-radius: 50%;
        border-radius: 18px;
        border: 1px solid rgba(90, 198, 255, 0.14);
        background: linear-gradient(180deg, rgba(7, 18, 29, 0.88), rgba(4, 11, 18, 0.96));
      }}

      .sphere-readout span {{
        display: block;
        color: #7496ae;
        font-size: 0.68rem;
        letter-spacing: 0.2em;
        text-transform: uppercase;
      }}

      .sphere-readout strong {{
        display: block;
        color: #f4f8ff;
        font-size: 0.96rem;
        margin-top: 8px;
      }}

      .grid {{
        gap: 24px;
      }}

      .card,
      .side-card,
      .composer,
      .message-log {{
        position: relative;
        background: linear-gradient(180deg, rgba(6, 17, 27, 0.92), rgba(3, 9, 15, 0.97));
        border-color: rgba(86, 188, 245, 0.14);
        box-shadow:
          0 26px 86px rgba(0, 0, 0, 0.38),
          inset 0 1px 0 rgba(255,255,255,0.03);
      }}

      .card::before,
      .side-card::before,
      .composer::before,
      .message-log::before {{
        content: "";
        position: absolute;
        inset: 12px;
        border-radius: inherit;
        border: 1px solid rgba(92, 196, 255, 0.08);
        pointer-events: none;
      }}

      .card-inner {{
        position: relative;
        z-index: 1;
      }}

      .card h2 {{
        margin: 0 0 14px;
        font-family: "Bahnschrift", "Segoe UI Variable Display", sans-serif;
        font-size: 1.18rem;
        letter-spacing: 0.1em;
        text-transform: uppercase;
      }}

      .status-pill.ready {{
        background: linear-gradient(135deg, #8cf0cb, #47d5a9);
        color: #07261c;
      }}

      .status-pill.warn {{
        background: linear-gradient(135deg, #ffd982, #ffb84d);
        color: #2a1905;
      }}

      .status-note,
      .issue-list,
      .metric-label,
      .footer-note,
      .mini {{
        color: #87a6bb;
      }}

      .issue-list {{
        list-style: none;
        padding-left: 0;
        display: grid;
        gap: 10px;
      }}

      .issue-list li {{
        position: relative;
        padding-left: 18px;
      }}

      .issue-list li::before {{
        content: "";
        position: absolute;
        left: 0;
        top: 0.72em;
        width: 8px;
        height: 1px;
        background: var(--accent);
      }}

      .metric-box {{
        background: linear-gradient(180deg, rgba(5, 18, 29, 0.88), rgba(4, 12, 20, 0.98));
        border-color: rgba(92, 196, 255, 0.1);
      }}

      .metric-label {{
        letter-spacing: 0.16em;
      }}

      .metric-value {{
        font-family: "Bahnschrift SemiCondensed", "Segoe UI Variable Display", sans-serif;
      }}

      .command-block {{
        background:
          linear-gradient(180deg, rgba(5, 12, 19, 0.94), rgba(3, 8, 13, 0.98)),
          radial-gradient(circle at 0 50%, rgba(255, 125, 44, 0.08), transparent 30%);
        border-color: rgba(92, 196, 255, 0.12);
        color: #dff5ff;
      }}

      .console {{
        gap: 22px;
      }}

      .chat-shell {{
        gap: 18px;
      }}

      .chat-frame-head {{
        display: flex;
        flex-wrap: wrap;
        align-items: flex-end;
        justify-content: space-between;
        gap: 14px;
        padding: 18px 20px;
        border-radius: 20px;
        border: 1px solid rgba(87, 190, 247, 0.14);
        background: linear-gradient(180deg, rgba(6, 18, 29, 0.76), rgba(4, 10, 18, 0.92));
      }}

      .chat-frame-head h2 {{
        margin: 8px 0 0;
        font-family: "Bahnschrift", "Segoe UI Variable Display", sans-serif;
        font-size: 1.22rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }}

      .frame-tag {{
        color: #6e8ca2;
        font-size: 0.7rem;
        letter-spacing: 0.2em;
        text-transform: uppercase;
      }}

      .frame-readout {{
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 10px;
      }}

      .frame-pill {{
        padding: 8px 12px;
        border-radius: 999px;
        border: 1px solid rgba(95, 201, 255, 0.14);
        background: rgba(255,255,255,0.03);
        color: #d8efff;
        font-size: 0.78rem;
        letter-spacing: 0.14em;
        text-transform: uppercase;
      }}

      .message-log {{
        min-height: 520px;
        background:
          linear-gradient(180deg, rgba(6, 17, 27, 0.94), rgba(3, 8, 13, 0.98)),
          radial-gradient(circle at top right, rgba(90, 208, 255, 0.05), transparent 32%);
      }}

      .message {{
        position: relative;
        padding-left: 18px;
        backdrop-filter: blur(8px);
      }}

      .message::before {{
        content: "";
        position: absolute;
        left: 8px;
        top: 14px;
        bottom: 14px;
        width: 2px;
        border-radius: 999px;
        opacity: 0.4;
      }}

      .message.user {{
        color: #ffe2c2;
        background: linear-gradient(135deg, rgba(255, 138, 57, 0.18), rgba(255, 89, 32, 0.08));
        border-color: rgba(255, 147, 73, 0.24);
      }}

      .message.user::before {{
        background: linear-gradient(180deg, rgba(255, 189, 113, 0.9), rgba(255, 104, 39, 0.8));
      }}

      .message.assistant {{
        color: #dff6ff;
        background: linear-gradient(135deg, rgba(65, 217, 255, 0.14), rgba(31, 109, 196, 0.08));
        border-color: rgba(89, 215, 255, 0.18);
      }}

      .message.assistant::before {{
        background: linear-gradient(180deg, rgba(91, 223, 255, 0.95), rgba(66, 167, 255, 0.74));
      }}

      .message.system {{
        color: #d2dce6;
        background: linear-gradient(135deg, rgba(255,255,255,0.04), rgba(117, 143, 169, 0.06));
        border-color: rgba(124, 152, 181, 0.16);
      }}

      .message.system::before {{
        background: linear-gradient(180deg, rgba(201, 215, 229, 0.75), rgba(113, 136, 161, 0.72));
      }}

      .message-label {{
        color: #7a9ab2;
      }}

      .tool-chip {{
        background: rgba(255,255,255,0.04);
        border-color: rgba(92, 196, 255, 0.14);
        color: #a3c4d9;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }}

      .tool-chip.error {{
        color: #ffd08d;
        background: rgba(255, 159, 72, 0.14);
        border-color: rgba(255, 159, 72, 0.28);
      }}

      .composer {{
        padding: 20px;
      }}

      .mode-select,
      .path-input {{
        border-color: rgba(92, 196, 255, 0.14);
        background: rgba(255,255,255,0.03);
        font-family: "Bahnschrift SemiCondensed", "Segoe UI Variable Display", sans-serif;
      }}

      .codex-banner {{
        background: linear-gradient(180deg, rgba(75, 217, 255, 0.09), rgba(49, 156, 255, 0.05));
        border-color: rgba(75, 217, 255, 0.18);
      }}

      .composer textarea {{
        min-height: 140px;
        font-family: "Bahnschrift SemiCondensed", "Segoe UI Variable Display", sans-serif;
        font-size: 1.02rem;
      }}

      .composer textarea::placeholder {{
        color: rgba(138, 170, 193, 0.72);
      }}

      .composer-footer {{
        border-top-color: rgba(92, 196, 255, 0.12);
      }}

      .voice-status {{
        font-size: 0.8rem;
        letter-spacing: 0.14em;
        text-transform: uppercase;
      }}

      .toggle {{
        color: #88a9bf;
        font-size: 0.78rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }}

      .toggle input {{
        accent-color: #ff7c2c;
      }}

      .side-card {{
        padding: 20px;
      }}

      .side-card h3 {{
        font-family: "Bahnschrift", "Segoe UI Variable Display", sans-serif;
        letter-spacing: 0.09em;
        text-transform: uppercase;
        color: #ebf5ff;
      }}

      .side-card p,
      .side-card li {{
        color: #89a8bf;
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

      @media (max-width: 1100px) {{
        .hero-grid,
        .console {{
          grid-template-columns: 1fr;
        }}

        .status-ribbon {{
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }}
      }}

      @media (max-width: 720px) {{
        .hero {{
          padding: 24px;
        }}

        .status-ribbon {{
          grid-template-columns: 1fr;
        }}

        .chat-frame-head {{
          align-items: flex-start;
        }}
      }}

      body {{
        overflow: hidden;
      }}

      body.history-open {{
        overflow: hidden;
      }}

      .shell {{
        width: 100%;
        margin: 0;
      }}

      .hero {{
        min-height: 100vh;
        padding: 0;
        border: 0;
        border-radius: 0;
        background: transparent;
        box-shadow: none;
        overflow: hidden;
      }}

      .hero::before,
      .hero::after {{
        display: none;
      }}

      .topbar {{
        position: absolute;
        top: 22px;
        left: 22px;
        right: 22px;
        z-index: 4;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
      }}

      .topbar-brand {{
        display: inline-flex;
        align-items: center;
        gap: 12px;
        padding: 10px 14px;
        border-radius: 999px;
        border: 1px solid rgba(95, 202, 255, 0.14);
        background: rgba(5, 14, 23, 0.62);
        backdrop-filter: blur(18px);
        box-shadow: 0 12px 34px rgba(0, 0, 0, 0.24);
      }}

      .topbar-brand strong {{
        font-size: 0.94rem;
        letter-spacing: 0.16em;
        text-transform: uppercase;
      }}

      .topbar-actions {{
        display: flex;
        align-items: center;
        justify-content: flex-end;
        flex-wrap: wrap;
        gap: 10px;
      }}

      .top-pill {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 42px;
        padding: 10px 14px;
        border-radius: 999px;
        border: 1px solid rgba(95, 202, 255, 0.14);
        background: rgba(5, 14, 23, 0.62);
        color: #dff4ff;
        font-size: 0.8rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        backdrop-filter: blur(18px);
        box-shadow: 0 12px 34px rgba(0, 0, 0, 0.24);
      }}

      .top-pill.status-pill {{
        padding-inline: 14px;
      }}

      .history-toggle,
      .history-close {{
        min-height: 42px;
        padding-block: 10px;
      }}

      .hero-stage {{
        position: fixed;
        inset: 0;
        width: 100vw;
        height: 100vh;
        min-height: 100vh;
        display: grid;
        place-items: center;
        padding: 0;
      }}

      .sphere-panel {{
        width: 100vw;
        height: 100vh;
        display: grid;
        place-items: center;
      }}

      .sphere-stage {{
        position: absolute;
        inset: 0;
        width: 100vw;
        height: 100vh;
        max-width: none;
        aspect-ratio: auto;
        border: 0;
        border-radius: 0;
        background: transparent;
        box-shadow: none;
        pointer-events: auto;
      }}

      .sphere-stage::before,
      .sphere-stage::after,
      .sphere-orbit {{
        display: none;
      }}

      .sphere-badge {{
        bottom: 128px;
        min-width: 210px;
        padding: 14px 16px;
      }}

      .sphere-badge span {{
        font-size: 0.62rem;
      }}

      .sphere-badge strong {{
        font-size: 0.92rem;
      }}

      .command-dock {{
        position: fixed;
        left: 50%;
        bottom: 18px;
        z-index: 4;
        width: min(860px, calc(100% - 36px));
        transform: translateX(-50%);
        display: grid;
        gap: 12px;
        padding: 14px;
        border-radius: 24px;
        border: 1px solid rgba(92, 196, 255, 0.14);
        background:
          linear-gradient(180deg, rgba(6, 17, 27, 0.82), rgba(4, 11, 18, 0.94)),
          radial-gradient(circle at top right, rgba(92, 215, 255, 0.08), transparent 34%);
        box-shadow:
          0 26px 78px rgba(0, 0, 0, 0.36),
          inset 0 1px 0 rgba(255,255,255,0.04);
        backdrop-filter: blur(22px);
        max-height: none;
        overflow: hidden;
      }}

      .command-dock::before {{
        content: "";
        position: absolute;
        inset: 10px;
        border-radius: 20px;
        border: 1px solid rgba(92, 196, 255, 0.08);
        pointer-events: none;
      }}

      .command-dock > * {{
        position: relative;
        z-index: 1;
      }}

      .dock-row {{
        display: flex;
        align-items: center;
        gap: 12px;
      }}

      .dock-row-bottom {{
        justify-content: space-between;
      }}

      .command-dock .mode-select,
      .command-dock .path-input {{
        width: 100%;
        min-width: 0;
        min-height: 48px;
        padding: 12px 14px;
        border-radius: 16px;
      }}

      .command-dock textarea {{
        width: 100%;
        min-height: 86px;
        max-height: none;
        resize: none;
        padding: 12px 14px;
        border: 1px solid rgba(92, 196, 255, 0.12);
        border-radius: 18px;
        outline: 0;
        background: rgba(6, 17, 27, 0.55);
        color: var(--text);
        font: inherit;
        line-height: 1.55;
      }}

      .command-dock textarea::placeholder {{
        color: rgba(138, 170, 193, 0.7);
      }}

      .command-dock .codex-banner {{
        margin: 0;
        padding: 10px 12px;
        border-radius: 14px;
        font-size: 0.82rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }}

      .command-dock .composer-actions {{
        justify-content: flex-end;
      }}

      .command-dock .button {{
        min-height: 44px;
        padding: 10px 14px;
      }}

      .hidden-control {{
        display: none !important;
      }}

      .voice-status {{
        margin: 0;
        min-height: 1.2em;
        font-size: 0.78rem;
        letter-spacing: 0.14em;
        text-transform: uppercase;
      }}

      .toggle {{
        min-height: 48px;
        padding: 0 14px;
        border-radius: 999px;
        border: 1px solid rgba(95, 202, 255, 0.14);
        background: rgba(255,255,255,0.03);
      }}

      .history-modal[hidden] {{
        display: none !important;
      }}

      .history-modal {{
        position: fixed;
        inset: 0;
        z-index: 30;
        display: grid;
        place-items: center;
        padding: 20px;
        background: rgba(2, 8, 14, 0.66);
        backdrop-filter: blur(18px);
      }}

      .history-panel {{
        width: min(980px, 100%);
        max-height: min(78vh, 920px);
        display: grid;
        grid-template-rows: auto minmax(0, 1fr);
        gap: 14px;
        padding: 18px;
        border-radius: 28px;
        border: 1px solid rgba(92, 196, 255, 0.16);
        background:
          linear-gradient(180deg, rgba(6, 17, 27, 0.92), rgba(3, 9, 15, 0.97)),
          radial-gradient(circle at top right, rgba(92, 215, 255, 0.08), transparent 34%);
        box-shadow: 0 30px 90px rgba(0, 0, 0, 0.42);
      }}

      .history-head {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
      }}

      .history-head h2 {{
        margin: 0;
        font-family: "Bahnschrift", "Segoe UI Variable Display", sans-serif;
        font-size: 1rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }}

      .history-panel .message-log {{
        min-height: 0;
        height: min(62vh, 720px);
        max-height: none;
        margin: 0;
      }}

      @media (max-width: 900px) {{
        .topbar {{
          top: 16px;
          left: 16px;
          right: 16px;
          align-items: flex-start;
          flex-direction: column;
        }}

        .topbar-actions {{
          width: 100%;
          justify-content: flex-start;
        }}

        .hero-stage {{
          padding: 0;
        }}

        .sphere-stage {{
          width: 100vw;
          height: 100vh;
        }}

        .command-dock {{
          bottom: 12px;
          width: calc(100% - 20px);
          padding: 12px;
        }}

        .dock-row-bottom {{
          align-items: flex-start;
          flex-direction: column;
        }}
      }}

      @media (max-width: 640px) {{
        .top-pill {{
          font-size: 0.72rem;
          letter-spacing: 0.08em;
        }}

        .history-panel {{
          padding: 14px;
        }}

        .history-head {{
          align-items: flex-start;
          flex-direction: column;
        }}

        .command-dock .composer-actions {{
          width: 100%;
          justify-content: flex-start;
          flex-wrap: wrap;
        }}
      }}
    </style>
  </head>
  <body>
    <main class="shell">
      <section class="hero">
        <div class="topbar">
          <div class="topbar-brand">
            <span class="pulse"></span>
            <strong>{server_name}</strong>
          </div>
          <div class="topbar-actions">
            <div class="top-pill status-pill {readiness_class}" id="readiness-pill">{readiness}</div>
            <div class="top-pill" id="sphere-voice-label">Idle</div>
            <div class="top-pill" id="hud-clock">--:--:--</div>
            <button class="button button-secondary history-toggle" id="history-button" type="button">History</button>
          </div>
        </div>

        <div class="hero-stage" aria-hidden="true">
          <div class="sphere-panel">
            <div class="sphere-stage" id="sphere-stage" data-state="idle">
              <canvas class="sphere-canvas" id="hud-sphere" aria-hidden="true"></canvas>
              <div class="sphere-glow glow-a"></div>
              <div class="sphere-glow glow-b"></div>
              <div class="sphere-orbit orbit-a"></div>
              <div class="sphere-orbit orbit-b"></div>
              <div class="sphere-orbit orbit-c"></div>
              <div class="sphere-badge">
                <span>Neural Lattice</span>
                <strong id="sphere-state-label">Awaiting command</strong>
              </div>
            </div>
          </div>
        </div>

        <div class="command-dock" id="pilot-console">
          <input class="hidden-control" id="dispatch-mode" type="hidden" value="friday">
          <input class="hidden-control" id="project-path-input" type="hidden" value="{codex_project_path}">
          <div class="hidden-control codex-banner" id="codex-banner" hidden>Project-aware relay</div>
          <textarea id="prompt-input" placeholder="Ask FRIDAY anything."></textarea>
          <div class="dock-row dock-row-bottom">
            <p class="voice-status" id="voice-status">Idle</p>
            <div class="composer-actions">
              <label class="toggle">
                <input id="speak-toggle" type="checkbox" checked>
                Voice
              </label>
              <button class="button button-primary" id="send-button" type="button">Send</button>
              <button class="button button-secondary button-mic" id="mic-button" type="button">Mic</button>
              <button class="button button-secondary" id="stop-speech" type="button">Stop</button>
            </div>
          </div>
        </div>
      </section>
    </main>

    <div class="history-modal" id="history-modal" hidden>
      <div class="history-panel" role="dialog" aria-modal="true" aria-labelledby="history-title">
        <div class="history-head">
          <h2 id="history-title">Conversation History</h2>
          <button class="button button-secondary history-close" id="history-close" type="button">Close</button>
        </div>
        <div class="message-log" id="message-log"></div>
      </div>
    </div>

    <script>
      const initialGreeting = {json.dumps(state["greeting"])};
      const initialCodexStatus = {json.dumps(codex_state)};
      const assistantDisplayName = {json.dumps(state["server_name"].upper())};
      const appState = {{
        ready: {str(state["ready"]).lower()},
        codexReady: {str(codex_state["ready"]).lower()},
        busy: false,
        listening: false,
        micStarting: false,
        speaking: false,
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
      const historyButton = document.getElementById("history-button");
      const historyModal = document.getElementById("history-modal");
      const historyCloseButton = document.getElementById("history-close");
      const speakToggle = document.getElementById("speak-toggle");
      const dispatchMode = document.getElementById("dispatch-mode");
      const projectPathInput = document.getElementById("project-path-input");
      const voiceStatus = document.getElementById("voice-status");
      const codexBanner = document.getElementById("codex-banner");
      const codexStatusNote = document.getElementById("codex-status-note");
      const codexStatusLabel = document.getElementById("codex-status-label");
      const issueList = document.getElementById("issue-list");
      const readinessPill = document.getElementById("readiness-pill");
      const hudClock = document.getElementById("hud-clock");
      const sphereStage = document.getElementById("sphere-stage");
      const sphereCanvas = document.getElementById("hud-sphere");
      const sphereStateLabel = document.getElementById("sphere-state-label");
      const sphereVoiceLabel = document.getElementById("sphere-voice-label");
      const sphereContext = sphereCanvas ? sphereCanvas.getContext("2d") : null;
      const llmLabel = document.getElementById("llm-label");
      const mcpUrlLabel = document.getElementById("mcp-url");

      let mediaRecorder = null;
      let mediaStream = null;
      let recordedChunks = [];
      let recordingTimer = null;
      let silenceMonitor = null;
      let audioContext = null;
      let analyserNode = null;
      let analyserSamples = null;
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
      const prefersReducedMotion = Boolean(
        window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches
      );

      function clamp(value, min, max) {{
        return Math.min(max, Math.max(min, value));
      }}

      function lerp(start, end, amount) {{
        return start + (end - start) * amount;
      }}

      function mixColor(fromColor, toColor, amount) {{
        return [
          Math.round(lerp(fromColor[0], toColor[0], amount)),
          Math.round(lerp(fromColor[1], toColor[1], amount)),
          Math.round(lerp(fromColor[2], toColor[2], amount)),
        ];
      }}

      function rgbaColor(color, alpha) {{
        return "rgba(" + color[0] + ", " + color[1] + ", " + color[2] + ", " + alpha.toFixed(3) + ")";
      }}

      function buildSpherePoints(count) {{
        const points = [];
        const goldenAngle = Math.PI * (3 - Math.sqrt(5));

        for (let index = 0; index < count; index += 1) {{
          const progress = count === 1 ? 0 : index / (count - 1);
          const y = 1 - progress * 2;
          const radius = Math.sqrt(Math.max(0, 1 - y * y));
          const theta = goldenAngle * index;
          points.push({{
            x: Math.cos(theta) * radius,
            y,
            z: Math.sin(theta) * radius,
            phase: Math.random() * Math.PI * 2,
            pulse: 0.8 + Math.random() * 0.9,
            spin: (Math.random() - 0.5) * 0.5,
            tilt: (Math.random() - 0.5) * 0.35,
          }});
        }}

        return points;
      }}

      function rotatePoint(x, y, z, rotationX, rotationY, rotationZ) {{
        const cosY = Math.cos(rotationY);
        const sinY = Math.sin(rotationY);
        const rotatedX = x * cosY - z * sinY;
        const rotatedZ = x * sinY + z * cosY;

        const cosX = Math.cos(rotationX);
        const sinX = Math.sin(rotationX);
        const tiltedY = y * cosX - rotatedZ * sinX;
        const liftedZ = y * sinX + rotatedZ * cosX;

        const cosZ = Math.cos(rotationZ);
        const sinZ = Math.sin(rotationZ);
        return {{
          x: rotatedX * cosZ - tiltedY * sinZ,
          y: rotatedX * sinZ + tiltedY * cosZ,
          z: liftedZ,
        }};
      }}

      const spherePalette = {{
        cool: [92, 226, 255],
        warm: [255, 150, 86],
        halo: [58, 145, 214],
      }};
      const spherePoints = buildSpherePoints(540);
      const sphereMotion = {{
        width: 0,
        height: 0,
        dpr: 1,
        pointerX: 0,
        pointerY: 0,
        targetPointerX: 0,
        targetPointerY: 0,
        pointerPx: 0,
        pointerPy: 0,
        targetPointerPx: 0,
        targetPointerPy: 0,
        active: false,
        energy: 0.24,
        audio: 0,
        rotation: 0,
        lastFrame: 0,
      }};
      let sphereAnimationFrame = 0;

      function sphereVisualState() {{
        if (appState.listening) {{
          return "listening";
        }}
        if (appState.speaking) {{
          return "speaking";
        }}
        if (appState.busy) {{
          return "thinking";
        }}
        if (appState.micStarting) {{
          return "arming";
        }}
        return "idle";
      }}

      function updateSphereStatus() {{
        const state = sphereVisualState();
        let label = "Awaiting command";
        const canSpeak = "speechSynthesis" in window;
        let voiceLabel = appState.speakReplies && canSpeak ? "Idle" : "Text only";

        if (state === "arming") {{
          label = "Priming microphone";
          voiceLabel = "Mic starting";
        }} else if (state === "listening") {{
          label = "Listening live";
          voiceLabel = "Live input";
        }} else if (state === "speaking") {{
          label = "Speaking reply";
          voiceLabel = "Reply active";
        }} else if (state === "thinking") {{
          label = "Resolving task";
          voiceLabel = appState.speakReplies && canSpeak ? "Processing" : "Text only";
        }}

        if (sphereStage) {{
          sphereStage.dataset.state = state;
        }}
        if (sphereStateLabel) {{
          sphereStateLabel.textContent = label;
        }}
        if (sphereVoiceLabel) {{
          sphereVoiceLabel.textContent = voiceLabel;
        }}
      }}

      function setSpeaking(isSpeaking) {{
        appState.speaking = isSpeaking;
        updateSphereStatus();
      }}

      function resizeSphereCanvas() {{
        if (!sphereCanvas || !sphereStage || !sphereContext) {{
          return;
        }}

        const rect = sphereStage.getBoundingClientRect();
        if (!rect.width || !rect.height) {{
          return;
        }}

        const nextDpr = Math.min(window.devicePixelRatio || 1, 2);
        const nextWidth = Math.round(rect.width * nextDpr);
        const nextHeight = Math.round(rect.height * nextDpr);
        if (sphereCanvas.width !== nextWidth || sphereCanvas.height !== nextHeight) {{
          sphereCanvas.width = nextWidth;
          sphereCanvas.height = nextHeight;
        }}

        sphereMotion.width = rect.width;
        sphereMotion.height = rect.height;
        sphereMotion.dpr = nextDpr;
        sphereContext.setTransform(nextDpr, 0, 0, nextDpr, 0, 0);

        if (!sphereMotion.active) {{
          sphereMotion.pointerPx = rect.width * 0.5;
          sphereMotion.pointerPy = rect.height * 0.5;
          sphereMotion.targetPointerPx = sphereMotion.pointerPx;
          sphereMotion.targetPointerPy = sphereMotion.pointerPy;
        }}
      }}

      function updateSpherePointer(event) {{
        if (!sphereStage) {{
          return;
        }}

        const rect = sphereStage.getBoundingClientRect();
        const pointerPx = clamp(event.clientX - rect.left, 0, rect.width);
        const pointerPy = clamp(event.clientY - rect.top, 0, rect.height);
        sphereMotion.active = true;
        sphereMotion.targetPointerPx = pointerPx;
        sphereMotion.targetPointerPy = pointerPy;
        sphereMotion.targetPointerX = rect.width ? pointerPx / rect.width * 2 - 1 : 0;
        sphereMotion.targetPointerY = rect.height ? pointerPy / rect.height * 2 - 1 : 0;
      }}

      function resetSpherePointer() {{
        sphereMotion.active = false;
        sphereMotion.targetPointerX = 0;
        sphereMotion.targetPointerY = 0;
        sphereMotion.targetPointerPx = sphereMotion.width * 0.5;
        sphereMotion.targetPointerPy = sphereMotion.height * 0.5;
      }}

      function renderSphereFrame(now = performance.now()) {{
        if (!sphereCanvas || !sphereContext || !sphereStage) {{
          return;
        }}

        if (!sphereMotion.width || !sphereMotion.height) {{
          resizeSphereCanvas();
        }}

        const width = sphereMotion.width;
        const height = sphereMotion.height;
        if (!width || !height) {{
          sphereAnimationFrame = window.requestAnimationFrame(renderSphereFrame);
          return;
        }}

        const delta = sphereMotion.lastFrame ? Math.min(32, now - sphereMotion.lastFrame) : 16;
        sphereMotion.lastFrame = now;

        const state = sphereVisualState();
        const stateEnergy = state === "listening"
          ? 0.94
          : (state === "speaking"
            ? 0.86
            : (state === "thinking"
              ? 0.62
              : (state === "arming" ? 0.72 : 0.24)));
        const inputLevel = clamp(currentInputLevel() * 26, 0, 1);
        const motionScale = prefersReducedMotion ? 0.4 : 1;
        sphereMotion.audio = lerp(sphereMotion.audio, inputLevel, 0.16);
        sphereMotion.energy = lerp(
          sphereMotion.energy,
          stateEnergy + sphereMotion.audio * 0.72 + (sphereMotion.active ? 0.08 : 0),
          0.08
        );
        sphereMotion.pointerX = lerp(sphereMotion.pointerX, sphereMotion.active ? sphereMotion.targetPointerX : 0, 0.08);
        sphereMotion.pointerY = lerp(sphereMotion.pointerY, sphereMotion.active ? sphereMotion.targetPointerY : 0, 0.08);
        sphereMotion.pointerPx = lerp(
          sphereMotion.pointerPx,
          sphereMotion.active ? sphereMotion.targetPointerPx : width * 0.5,
          0.16
        );
        sphereMotion.pointerPy = lerp(
          sphereMotion.pointerPy,
          sphereMotion.active ? sphereMotion.targetPointerPy : height * 0.5,
          0.16
        );
        sphereMotion.rotation += delta * (0.00026 + sphereMotion.energy * 0.00096 * motionScale);

        const centerX = width * 0.5;
        const centerY = height * 0.5;
        const radius = Math.min(width, height) * 0.5;
        const pointerCenterDistance = Math.hypot(
          sphereMotion.pointerPx - centerX,
          sphereMotion.pointerPy - centerY
        );
        const pointerFieldRadius = radius * 1.06;
        const pointerFieldInfluence = sphereMotion.active && pointerCenterDistance < pointerFieldRadius
          ? 1 - pointerCenterDistance / pointerFieldRadius
          : 0;
        const rotationY = sphereMotion.rotation;
        const rotationX = Math.sin(now * 0.00042 * motionScale) * 0.26 + sphereMotion.pointerY * (0.42 + pointerFieldInfluence * 0.14);
        const rotationZ = Math.cos(now * 0.0002 * motionScale) * 0.12 + sphereMotion.pointerX * (0.24 + pointerFieldInfluence * 0.12);
        const pulse = Math.sin(now * 0.0018 * motionScale) * 0.5 + 0.5;
        const pointerRadius = radius * 0.52;

        sphereContext.clearRect(0, 0, width, height);

        const halo = sphereContext.createRadialGradient(
          centerX,
          centerY,
          radius * 0.08,
          centerX,
          centerY,
          radius * 1.62
        );
        halo.addColorStop(0, rgbaColor(spherePalette.cool, 0.07 + sphereMotion.energy * 0.12));
        halo.addColorStop(0.48, rgbaColor(spherePalette.halo, 0.06 + sphereMotion.energy * 0.06));
        halo.addColorStop(1, "rgba(0, 0, 0, 0)");
        sphereContext.fillStyle = halo;
        sphereContext.fillRect(0, 0, width, height);

        if (pointerFieldInfluence > 0) {{
          const interactionGlow = sphereContext.createRadialGradient(
            sphereMotion.pointerPx,
            sphereMotion.pointerPy,
            radius * 0.04,
            sphereMotion.pointerPx,
            sphereMotion.pointerPy,
            radius * 0.34
          );
          interactionGlow.addColorStop(0, rgbaColor(mixColor(spherePalette.cool, spherePalette.warm, 0.28), 0.22 * pointerFieldInfluence));
          interactionGlow.addColorStop(0.34, rgbaColor(spherePalette.cool, 0.12 * pointerFieldInfluence));
          interactionGlow.addColorStop(1, "rgba(0, 0, 0, 0)");
          sphereContext.fillStyle = interactionGlow;
          sphereContext.fillRect(0, 0, width, height);
        }}

        sphereContext.save();
        sphereContext.lineWidth = 1;
        sphereContext.strokeStyle = rgbaColor(spherePalette.cool, 0.08 + sphereMotion.energy * 0.08);
        sphereContext.beginPath();
        sphereContext.arc(centerX, centerY, radius * (1.08 + pulse * 0.015), 0, Math.PI * 2);
        sphereContext.stroke();
        sphereContext.restore();

        const dots = [];
        for (const point of spherePoints) {{
          const wave = 1 + Math.sin(now * 0.0011 * motionScale + point.phase) * (0.028 + sphereMotion.energy * 0.04);
          const rotated = rotatePoint(
            point.x * wave,
            point.y * wave,
            point.z * (wave + pointerFieldInfluence * 0.04),
            rotationX + point.tilt,
            rotationY + point.spin,
            rotationZ
          );
          const perspective = 1.16 / (2.4 - rotated.z);
          let screenX = centerX + rotated.x * radius * perspective;
          let screenY = centerY + rotated.y * radius * perspective;
          const depth = clamp((rotated.z + 1) * 0.5, 0, 1);
          let pointerBoost = 0;

          if (sphereMotion.active) {{
            const dx = screenX - sphereMotion.pointerPx;
            const dy = screenY - sphereMotion.pointerPy;
            const distance = Math.hypot(dx, dy);
            if (distance < pointerRadius) {{
              pointerBoost = (1 - distance / pointerRadius) * (0.65 + pointerFieldInfluence * 0.75);
            }}
          }}

          dots.push({{
            x: screenX,
            y: screenY,
            depth,
            pointerBoost,
            size: 0.65 + depth * 1.95 + sphereMotion.energy * 1.1 + pointerBoost * 4.1 + point.pulse * 0.06,
          }});
        }}

        dots.sort((left, right) => left.depth - right.depth);

        sphereContext.save();
        sphereContext.globalCompositeOperation = "lighter";
        for (const dot of dots) {{
          const warmBlend = clamp(dot.pointerBoost * 1.08 + dot.depth * 0.38 + sphereMotion.audio * 0.18, 0, 1);
          const color = mixColor(spherePalette.cool, spherePalette.warm, warmBlend);
          const alpha = clamp(0.14 + dot.depth * 0.5 + dot.pointerBoost * 0.34 + sphereMotion.energy * 0.12, 0.08, 0.96);
          sphereContext.fillStyle = rgbaColor(color, alpha);
          sphereContext.beginPath();
          sphereContext.arc(dot.x, dot.y, dot.size, 0, Math.PI * 2);
          sphereContext.fill();
        }}
        sphereContext.restore();

        const coreGlow = sphereContext.createRadialGradient(
          centerX,
          centerY,
          radius * 0.04,
          centerX,
          centerY,
          radius * 0.58
        );
        coreGlow.addColorStop(0, rgbaColor(mixColor(spherePalette.cool, spherePalette.warm, sphereMotion.audio * 0.4), 0.18));
        coreGlow.addColorStop(0.4, rgbaColor(spherePalette.cool, 0.08 + sphereMotion.energy * 0.08));
        coreGlow.addColorStop(1, "rgba(0, 0, 0, 0)");
        sphereContext.fillStyle = coreGlow;
        sphereContext.fillRect(0, 0, width, height);

        sphereAnimationFrame = window.requestAnimationFrame(renderSphereFrame);
      }}

      function setupSphere() {{
        if (!sphereCanvas || !sphereStage || !sphereContext) {{
          return;
        }}

        resizeSphereCanvas();
        updateSphereStatus();
        sphereStage.addEventListener("pointerenter", updateSpherePointer);
        sphereStage.addEventListener("pointermove", updateSpherePointer);
        sphereStage.addEventListener("pointerdown", updateSpherePointer);
        sphereStage.addEventListener("pointerleave", resetSpherePointer);
        window.addEventListener("resize", resizeSphereCanvas);

        if (!sphereAnimationFrame) {{
          sphereAnimationFrame = window.requestAnimationFrame(renderSphereFrame);
        }}
      }}

      function escapeHtml(value) {{
        return value
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;")
          .replaceAll("'", "&#39;");
      }}

      function updateHudClock() {{
        if (!hudClock) {{
          return;
        }}

        hudClock.textContent = new Date().toLocaleTimeString([], {{
          hour12: false,
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }});
      }}

      function renderMessages() {{
        messageLog.innerHTML = appState.messages.map((message) => {{
          const label = message.role === "user" ? "Operator" : (message.role === "assistant" ? assistantDisplayName : "System");
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

      function setHistoryOpen(isOpen) {{
        if (!historyModal) {{
          return;
        }}

        historyModal.hidden = !isOpen;
        document.body.classList.toggle("history-open", isOpen);
        if (isOpen) {{
          renderMessages();
          if (historyCloseButton) {{
            historyCloseButton.focus();
          }}
        }} else if (promptInput) {{
          promptInput.focus();
        }}
      }}

      function setBusy(isBusy) {{
        appState.busy = isBusy;
        sendButton.disabled = isBusy || !activeModeReady();
        updateMicButton();
        updateSphereStatus();
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
          setSpeaking(false);
          if (appState.speakReplies && !("speechSynthesis" in window)) {{
            setVoiceStatus("Reply ready. Text only.", "warn");
          }}
          return;
        }}

        window.speechSynthesis.cancel();
        setSpeaking(false);
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1;
        utterance.pitch = 1;
        utterance.onstart = () => {{
          setSpeaking(true);
          setVoiceStatus("Speaking reply.", "ok");
        }};
        utterance.onend = () => {{
          setSpeaking(false);
          if (!appState.listening && !appState.micStarting) {{
            setVoiceStatus("Idle");
          }}
        }};
        utterance.onerror = () => {{
          setSpeaking(false);
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
          if (readinessPill) {{
            readinessPill.textContent = status.ready ? "Ready" : "Needs Config";
            readinessPill.className = `top-pill status-pill ${{status.ready ? "ready" : "warn"}}`;
          }}
          if (issueList) {{
            issueList.innerHTML = (status.issues.length ? status.issues : ["Local browser mode is ready."])
              .map((item) => `<li>${{escapeHtml(item)}}</li>`)
              .join("");
          }}
          if (codexStatusLabel) {{
            codexStatusLabel.textContent = codex.ready ? "Ready" : "Needs Setup";
          }}
          if (codexStatusNote) {{
            codexStatusNote.textContent = codex.ready
              ? "VS Code launcher and the Codex extension are available. Relay mode can open the sidebar, start a thread, and paste a project-aware prompt."
              : (Array.isArray(codex.issues) && codex.issues.length
                ? codex.issues.join("; ")
                : "Codex relay is not configured yet.");
          }}

          if (!projectPathInput.value.trim() || projectPathInput.value.trim() === initialCodexStatus.project_path) {{
            projectPathInput.value = codex.project_path || initialCodexStatus.project_path;
          }}

          if (mcpUrlLabel) {{
            mcpUrlLabel.textContent = status.mcp_server_url;
          }}
          if (llmLabel) {{
            llmLabel.textContent = `${{status.llm_provider}} / ${{status.llm_model}}`;
          }}

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
        analyserSamples = null;
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

        if (!analyserSamples || analyserSamples.length !== analyserNode.fftSize) {{
          analyserSamples = new Uint8Array(analyserNode.fftSize);
        }}
        analyserNode.getByteTimeDomainData(analyserSamples);

        let sumSquares = 0;
        for (let index = 0; index < analyserSamples.length; index += 1) {{
          const normalized = (analyserSamples[index] - 128) / 128;
          sumSquares += normalized * normalized;
        }}

        return Math.sqrt(sumSquares / analyserSamples.length);
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
          setVoiceStatus("Listening...", "ok");
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
          updateSphereStatus();
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
        if ("speechSynthesis" in window) {{
          window.speechSynthesis.cancel();
        }}
        setSpeaking(false);
        liveSessionId += 1;
        livePreviewTranscript = "";
        livePreviewRequestAt = 0;
        previewTranscriptRequestInFlight = false;
        previewTranscriptQueued = false;
        setVoiceStatus("Starting mic...");
        updateMicButton();
        updateSphereStatus();

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
            setVoiceStatus("Listening...", "ok");
            updateMicButton();
            updateSphereStatus();
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
            updateSphereStatus();
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
            updateSphereStatus();

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
          updateSphereStatus();
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
          setVoiceStatus("Idle");
        }}

        updateMicButton();
        updateSphereStatus();
      }}

      document.querySelectorAll("[data-copy]").forEach((button) => {{
        button.addEventListener("click", () => copyText(button.dataset.copy, button));
      }});

      if (historyButton) {{
        historyButton.addEventListener("click", () => setHistoryOpen(true));
      }}

      if (historyCloseButton) {{
        historyCloseButton.addEventListener("click", () => setHistoryOpen(false));
      }}

      if (historyModal) {{
        historyModal.addEventListener("click", (event) => {{
          if (event.target === historyModal) {{
            setHistoryOpen(false);
          }}
        }});
      }}

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
          setSpeaking(false);
          setVoiceStatus("Voice muted.");
        }} else if (!("speechSynthesis" in window)) {{
          setVoiceStatus("Reply speech was enabled, but this browser cannot play spoken replies.", "warn");
        }} else if (!appState.listening && !appState.micStarting) {{
          setVoiceStatus("Idle");
        }}
        updateSphereStatus();
      }});

      stopSpeechButton.addEventListener("click", () => {{
        if ("speechSynthesis" in window) {{
          window.speechSynthesis.cancel();
          setSpeaking(false);
          setVoiceStatus("Stopped.");
        }}
      }});

      window.addEventListener("keydown", (event) => {{
        if (event.key === "Escape" && historyModal && !historyModal.hidden) {{
          setHistoryOpen(false);
        }}
      }});

      setupSphere();
      setupMicrophone();
      updateComposerMode();
      renderMessages();
      updateHudClock();
      refreshStatus();
      setBusy(false);
      window.setInterval(updateHudClock, 1000);
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
                "pipeline_events": result.pipeline_events,
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
        return RedirectResponse(f"{_browser_base_url(request)}/", status_code=307)
