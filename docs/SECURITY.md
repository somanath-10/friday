# FRIDAY Security Model

FRIDAY is a single-user, local-first assistant. It can control real local tools:
files, shell commands, browser automation, desktop input, and memory. Treat it
as trusted personal automation, not as a hostile multi-tenant service.

## Trust Boundary

Supported boundary:

- one local operator
- one OS user context
- local browser/MCP access
- explicit configuration for any remote or voice surfaces

Not supported as a hard boundary:

- mutually untrusted users sharing one FRIDAY instance
- public internet exposure of the MCP server
- giving broad shell/desktop tools to strangers over chat

If you need adversarial separation, run separate OS users, machines, VMs, or
assistant instances.

## Risky Surfaces

High-risk capabilities:

- `shell`: can execute host commands
- `filesystem`: can create, edit, move, and delete files
- `desktop`: can click, type, hotkey, and inspect visible UI
- `browser`: can interact with websites and forms

Medium-risk capabilities:

- `memory`: may persist user facts and task traces
- `research`: may fetch remote content
- `workflow`: may coordinate multi-step actions
- `voice`: may capture or synthesize spoken content when enabled

## Guardrails

FRIDAY's guardrails live in:

- `config/permissions.yaml`
- `friday/core/permissions.py`
- `friday/core/risk.py`
- `friday/safety/approval_gate.py`
- `friday/safety/audit_log.py`
- `friday/safety/emergency_stop.py`
- `friday/files/safe_paths.py`

The default mode is `safe`, which keeps dangerous actions blocked and asks for
approval on sensitive actions.

## Hardening Checklist

- Keep `MCP_SERVER_HOST` bound to loopback for local use.
- Keep `FRIDAY_ACCESS_MODE=safe` unless you are actively supervising.
- Keep secrets out of prompts, workspace files, and screenshots.
- Do not add broad filesystem roots unless you understand the blast radius.
- Prefer isolated browser profiles for automation.
- Run `uv run friday_healthcheck` after changing permissions or tool modules.
- Review audit logs after sensitive shell, file, or desktop work.

## Reporting A Problem

For local development, start with:

```bash
uv run friday_healthcheck
uv run pytest tests -q
```

When reporting a security issue, include the tool name, permission mode,
sanitized config, and the exact action that crossed a boundary.
