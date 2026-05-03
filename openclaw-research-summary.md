# OpenClaw GitHub Account Research Summary

Research date: 2026-05-02 local workspace time.

Source account: https://github.com/openclaw

Local clone root: `C:\tmp\openclaw-research`

Generated local notes:

- `C:\tmp\openclaw-research\_analysis\repo-notes.txt`
- `C:\tmp\openclaw-research\_analysis\repo-summary.json`

## Scope

I fetched the live GitHub repository inventory through the GitHub API, shallow-cloned all 36 public repositories, inventoried Git-tracked files through `git ls-tree`, and inspected READMEs, package/module manifests, workflow YAML, source layouts, and architecture/security/plugin docs.

One important limitation: `openclaw/skills` cannot fully check out on Windows because thousands of filenames contain characters invalid on Windows paths, including colons and quotes. The Git clone succeeded, so I inspected it through Git object metadata instead of the working tree.

## Inventory

| Repository | Primary role | Files | Workflows | Main tech |
| --- | --- | ---: | ---: | --- |
| `openclaw/openclaw` | Main product and gateway monorepo | 17271 | 41 | TypeScript, Node, pnpm |
| `openclaw/clawhub` | Skill/plugin registry and website | 701 | 12 | TypeScript, TanStack Start, Convex, Bun |
| `openclaw/docs` | Published docs mirror plus translations | 9290 | 20 | Markdown, Node, Go, Codex CLI |
| `openclaw/skills` | Historical ClawHub skill archive | 429656 | 2 | Markdown, JSON, Python, JS |
| `openclaw/acpx` | Headless Agent Client Protocol CLI | 330 | 3 | TypeScript |
| `openclaw/plugin-inspector` | Offline OpenClaw plugin compatibility checker | 93 | 3 | JavaScript |
| `openclaw/crabpot` | External plugin compatibility fixture suite | 148 | 4 | JavaScript |
| `openclaw/crabbox` | Remote testbox runner and OpenClaw plugin | 155 | 3 | Go, Cloudflare Worker JS |
| `openclaw/clawbench` | Trace-based agent benchmark | 278 | 3 | Python |
| `openclaw/clawsweeper` | Conservative issue/PR/commit review bot | 161 | 10 | TypeScript |
| `openclaw/clawsweeper-state` | Generated ClawSweeper state/dashboard | 12 | 1 | JavaScript |
| `openclaw/clownfish` | Cluster cleanup and repair automation | 2454 | 7 | JavaScript |
| `openclaw/gitcrawl` | Local-first GitHub issue/PR crawler | 64 | 2 | Go |
| `openclaw/openclaw-windows-node` | Windows tray, node, CLI, PowerToys suite | 304 | 3 | C#/.NET |
| `openclaw/casa` | macOS HomeKit bridge app and CLI | 38 | 2 | Swift |
| `openclaw/esp-openclaw-node` | ESP32 node component/examples | 73 | 1 | C |
| `openclaw/clawgo` | Minimal Linux/Raspberry Pi node client | 20 | 0 | Go |
| `openclaw/nix-openclaw` | Declarative Nix deployment | 82 | 2 | Nix |
| `openclaw/nix-steipete-tools` | Nix packaged tools and OpenClaw plugins | 53 | 2 | Nix, Go |
| `openclaw/clawdinators` | NixOS-on-AWS agent fleet infra | 116 | 1 | Nix, OpenTofu |
| `openclaw/openclaw-ansible` | Hardened Debian/Ubuntu installer | 52 | 1 | Ansible, Shell |
| `openclaw/homebrew-tap` | Homebrew tap | 5 | 1 | Ruby |
| `openclaw/openclaw.ai` | Marketing/install site | 100 | 4 | Astro |
| `openclaw/cookbook` | SDK examples and recipes | 60 | 1 | TypeScript |
| `openclaw/kitchen-sink` | Fixture plugin covering public API surface | 42 | 4 | JavaScript |
| `openclaw/lobster` | Typed local workflow shell | 119 | 1 | TypeScript |
| `openclaw/multipass` | Messaging-provider test CLI | 56 | 1 | TypeScript |
| `openclaw/hermit` | Discord bot on Cloudflare Workers | 41 | 0 | TypeScript, D1, Drizzle |
| `openclaw/caclawphony` | Linear/Symphony PR triage pipeline | 104 | 2 | Elixir |
| `openclaw/community` | Discord community policies | 14 | 0 | Markdown |
| `openclaw/trust` | Threat model/security program data | 3 | 0 | YAML, Markdown |
| `openclaw/voice-community` | Voice/community ops docs branch | 2 | 0 | Markdown |
| `openclaw/clawsweeper.bot` | ClawSweeper website | 7 | 0 | HTML/CSS |
| `openclaw/butter.bot` | Small static site | 4 | 0 | HTML |
| `openclaw/flawd-bot` | Placeholder/minimal repo | 1 | 0 | License only |
| `openclaw/.github` | Organization-level GitHub files | 2 | 0 | Markdown/YAML |

## Main Product: `openclaw/openclaw`

`openclaw/openclaw` is the actual product core. It is a TypeScript/Node 22+ monorepo published as the `openclaw` CLI package. The root package version I inspected was `2026.4.30`, commit `c6cb7b48`.

The runtime model is:

1. CLI shim `openclaw.mjs` checks Node compatibility, handles compile-cache behavior, then loads built TypeScript output or source checkout paths.
2. `src/entry.ts` bootstraps process title/env, command/profile/container parsing, CLI respawn behavior, root help/version fast paths, and dispatch into the CLI runner.
3. The Gateway is the local long-lived daemon and control plane. It owns messaging surfaces, model/session execution, nodes, tools, pairing, auth, and HTTP/WebSocket surfaces.
4. Control clients and nodes connect over WebSocket on the configured Gateway port, defaulting to `127.0.0.1:18789`.
5. Agent runs enter through Gateway RPC `agent` / `agent.wait` or the CLI `agent` command. Runs are serialized per session, context/skills are assembled, `pi-agent-core` runs the loop, and lifecycle/tool/assistant streams are bridged back to OpenClaw events.
6. Plugins are discovered from manifests and configured plugin roots. Native plugins register capabilities such as providers, channels, tools, speech, media, web search/fetch, memory, and gateway services.
7. Sandboxing is optional. When enabled, tool execution can run in Docker, SSH, or OpenShell sandboxes. The Gateway itself stays on the host.

Major top-level areas:

- `src/agents`: agent runtime, auth profiles, tool execution, bash/process tools, model transport, session handling.
- `src/gateway`: WebSocket protocol, auth, HTTP endpoints, node registry, Control UI, OpenAI/Responses surfaces, model HTTP APIs, pairing and scopes.
- `src/commands`: CLI command implementations for onboarding, status, doctor, channels, daemon, models, plugins, backup, health, sandbox, sessions, etc.
- `src/cli`: Commander wiring, command registration, plugin command discovery, completion, root help, gateway fast paths.
- `src/plugin-sdk`: broad internal/public plugin API, channel/provider/runtime helpers, approvals, reply pipeline, media, secrets, sandbox, agent harness, hooks, CLI backend helpers.
- `extensions`: 120 bundled plugin manifests; provider plugins, channel plugins, tool plugins, memory plugins, sandbox plugins, speech/media plugins, and QA fixtures.
- `ui`: Vite/Lit/React-style Control UI package.
- `apps`: companion app source, including platform UI pieces.
- `docs`: authoritative English documentation source.

The core repo has 120 `openclaw.plugin.json` manifests and 126 `package.json` files. Bundled extensions cover OpenAI, Anthropic, Google, OpenRouter, Ollama, Discord, Slack, Telegram, WhatsApp, Matrix, Signal, iMessage, Teams, browser tools, search/fetch tools, memory, voice, image/video/music generation, sandbox/runtime helpers, and QA harnesses.

## Security Model

The documented model is a personal assistant trust boundary, not hostile multi-tenant isolation. Important points:

- One trusted operator boundary per Gateway is the expected deployment.
- `gateway.auth` authenticates callers to Gateway APIs.
- `sessionKey` is routing/context selection, not an authorization boundary.
- DM/group policies and allowlists gate who can trigger the bot.
- Exec approvals and tool policy are guardrails, not a full adversarial sandbox.
- Sandboxing can reduce tool blast radius, but the Gateway still runs on the host.
- Stronger isolation means separate gateways, credentials, OS users, hosts, or VMs.

## Plugin System

The plugin system is one of the strongest pieces of the architecture:

- Manifests are read before executing plugin code.
- Config validation and ownership mapping can happen from metadata.
- Runtime loading is separate from metadata snapshots.
- Capability registration is the direction for bundled/native plugins.
- Legacy hook-only plugins remain supported.
- The shared `message` tool is core-owned, while channel plugins own channel-specific discovery/execution.
- `plugin-inspector`, `crabpot`, `kitchen-sink`, and ClawHub package catalog all exist to keep plugin contracts testable.

## Workflow Automation

Total workflows inventoried: 137.

Largest workflow surfaces:

- `openclaw/openclaw`: 41 workflows for CI, CodeQL, release, Docker/macOS/npm releases, docs sync, install smoke, live/e2e checks, plugin publishing, ClawSweeper dispatch, OpenGrep, parity, testboxes, workflow sanity.
- `openclaw/docs`: 20 workflows, mostly per-locale translation runners plus reusable translation workflow.
- `openclaw/clawhub`: 12 workflows for CI, deploy, package publish, npm release, CodeQL, secret scan, stale handling, Convex AI file updates, ClawSweeper dispatch.
- `openclaw/clawsweeper`: 10 workflows for sweep/review/repair lanes and CodeQL.
- `openclaw/clownfish`: 7 workflows for cluster worker, comment router, commit finding intake, publish, finalize PRs, self-heal, validate.

The workflows are not just conventional CI. They form an operations layer: maintainer bots, self-review, repair loops, dashboard publishing, docs localization, external compatibility tracking, and release smoke testing.

## Ecosystem Map

Core product:

- `openclaw/openclaw`

Registry and distribution:

- `clawhub`, `skills`, `docs`, `openclaw.ai`, `homebrew-tap`

Plugin compatibility:

- `plugin-inspector`, `crabpot`, `kitchen-sink`, `cookbook`

Agent/protocol/tooling:

- `acpx`, `lobster`, `multipass`, `clawbench`, `crabbox`

Maintainer automation:

- `clawsweeper`, `clawsweeper-state`, `clownfish`, `gitcrawl`, `caclawphony`

Platform nodes and companion apps:

- `openclaw-windows-node`, `casa`, `esp-openclaw-node`, `clawgo`

Deployment/infra:

- `nix-openclaw`, `nix-steipete-tools`, `clawdinators`, `openclaw-ansible`

Community/security:

- `community`, `trust`, `voice-community`, `.github`

Small/static/placeholder:

- `clawsweeper.bot`, `butter.bot`, `flawd-bot`

## Notable Findings

- The organization is unusually automation-heavy. Much of the work is about keeping a fast-moving AI assistant ecosystem maintainable.
- The core repo has a serious plugin-contract strategy: metadata-first manifests, inspector tooling, compatibility fixture suites, package registry metadata, and release gates.
- The docs are mirrored out of the core repo and translated by workflow. Each generated locale page tracks a source hash to avoid unnecessary translation.
- `skills` is an archive, not a safe install source. Its own README warns that suspicious or malicious skills may exist. It contains 70,572 `SKILL.md` files and 5,542 `package.json` files.
- There is legacy naming drift in some repos and docs (`clawdbot`, `clawd`, `openclaw`). That looks like product history rather than separate systems.
- The Windows checkout issue in `skills` is real: about 5,458 paths include Windows-invalid characters.
- The main risk surface is expected for this kind of product: remote/messaging users can potentially drive host tools if operators configure broad allowlists/tools. The docs call this out explicitly.

## Sources

- OpenClaw GitHub account: https://github.com/openclaw
- Core repo: https://github.com/openclaw/openclaw
- ClawHub: https://github.com/openclaw/clawhub
- Docs mirror: https://github.com/openclaw/docs
- Skills archive: https://github.com/openclaw/skills
- ACPX: https://github.com/openclaw/acpx
- Crabpot: https://github.com/openclaw/crabpot
- Plugin Inspector: https://github.com/openclaw/plugin-inspector
- ClawSweeper: https://github.com/openclaw/clawsweeper
- Clownfish: https://github.com/openclaw/clownfish
- Gitcrawl: https://github.com/openclaw/gitcrawl
- ClawBench: https://github.com/openclaw/clawbench
- Crabbox: https://github.com/openclaw/crabbox
