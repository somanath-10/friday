# Computer-Use And Voice-Agent Repo Survey

This note captures a practical survey of open-source repos related to:

- desktop computer use
- browser-use / web agents
- voice-driven assistants
- multimodal GUI grounding
- workflow replay and agent infrastructure

The goal is not to clone every design. The goal is to extract recurring patterns
that improve FRIDAY without turning it into an incompatible patchwork.

## Surveyed repositories

### Desktop and computer-use agents

1. `openinterpreter/open-interpreter`
   Link: <https://github.com/openinterpreter/open-interpreter>
2. `openinterpreter/01`
   Link: <https://github.com/openinterpreter/01>
3. `simular-ai/Agent-S`
   Link: <https://github.com/simular-ai/Agent-S>
4. `microsoft/UFO`
   Link: <https://github.com/microsoft/UFO>
5. `microsoft/WindowsAgentArena`
   Link: <https://github.com/microsoft/WindowsAgentArena>
6. `microsoft/OmniParser`
   Link: <https://github.com/microsoft/OmniParser>
7. `bytedance/UI-TARS-desktop`
   Link: <https://github.com/bytedance/UI-TARS-desktop>
8. `showlab/ShowUI`
   Link: <https://github.com/showlab/ShowUI>
9. `showlab/computer_use_ootb`
   Link: <https://github.com/showlab/computer_use_ootb>
10. `zai-org/CogAgent`
    Link: <https://github.com/zai-org/CogAgent>
11. `OpenAdaptAI/OpenAdapt`
    Link: <https://github.com/OpenAdaptAI/OpenAdapt>
12. `coasty-ai/open-computer-use`
    Link: <https://github.com/coasty-ai/open-computer-use>
13. `e2b-dev/open-computer-use`
    Link: <https://github.com/e2b-dev/open-computer-use>
14. `bytebot-ai/bytebot`
    Link: <https://github.com/bytebot-ai/bytebot>
15. `777genius/os-ai-computer-use`
    Link: <https://github.com/777genius/os-ai-computer-use>

### Browser agents and web automation

16. `browser-use/browser-use`
    Link: <https://github.com/browser-use/browser-use>
17. `browser-use/workflow-use`
    Link: <https://github.com/browser-use/workflow-use>
18. `browserbase/stagehand`
    Link: <https://github.com/browserbase/stagehand>
19. `browserbase/stagehand-python`
    Link: <https://github.com/browserbase/stagehand-python>
20. `browserbase/stagehand-go`
    Link: <https://github.com/browserbase/stagehand-go>
21. `browserbase/mcp-server-browserbase`
    Link: <https://github.com/browserbase/mcp-server-browserbase>
22. `browserbase/open-operator`
    Link: <https://github.com/browserbase/open-operator>
23. `Skyvern-AI/skyvern`
    Link: <https://github.com/Skyvern-AI/skyvern>
24. `premsagar4us/clawbird`
    Link: <https://github.com/premsagar4us/clawbird>
25. `ServiceNow/AgentLab`
    Link: <https://github.com/ServiceNow/AgentLab>
26. `ServiceNow/WorkArena`
    Link: <https://github.com/ServiceNow/WorkArena>

### Voice-agent and multimodal orchestration stacks

27. `livekit/agents`
    Link: <https://github.com/livekit/agents>
28. `pipecat-ai/pipecat`
    Link: <https://github.com/pipecat-ai/pipecat>
29. `pipecat-ai/pipecat-flows`
    Link: <https://github.com/pipecat-ai/pipecat-flows>
30. `pipecat-ai/pipecat-cli`
    Link: <https://github.com/pipecat-ai/pipecat-cli>
31. `MycroftAI/mycroft-core`
    Link: <https://github.com/MycroftAI/mycroft-core>
32. `MycroftAI/mycroft-skills`
    Link: <https://github.com/MycroftAI/mycroft-skills>
33. `OpenVoiceOS/OpenVoiceOS`
    Link: <https://github.com/OpenVoiceOS/OpenVoiceOS>
34. `OpenVoiceOS/ovos-core`
    Link: <https://github.com/OpenVoiceOS/ovos-core>
35. `OpenVoiceOS/ovos-installer`
    Link: <https://github.com/OpenVoiceOS/ovos-installer>

### Agent infrastructure and reusable SDKs

36. `OpenHands/OpenHands`
    Link: <https://github.com/OpenHands/OpenHands>
37. `OpenHands/software-agent-sdk`
    Link: <https://github.com/OpenHands/software-agent-sdk>
38. `OpenHands/OpenHands-CLI`
    Link: <https://github.com/OpenHands/OpenHands-CLI>
39. `All-Hands-AI/openhands-aci`
    Link: <https://github.com/All-Hands-AI/openhands-aci>

## Repeating design patterns across these repos

### 1. Separate planner and executor roles

Most mature projects split work into:

- goal understanding / planning
- environment inspection
- action execution
- reflection / retry

Implication for FRIDAY:

- keep raw tools separate from high-level orchestration
- prefer explicit screen and browser state snapshots before action

### 2. Ground actions in environment state

The stronger computer-use repos do not blindly click. They ground actions using:

- screenshots
- visible window state
- indexed interactive elements
- OCR / VLM / grounding models

Implication for FRIDAY:

- inspect current desktop before GUI action
- inspect current page before browser action
- use target grounding instead of guessing coordinates

### 3. Preserve trajectories and memory

Many strong repos keep:

- chat history
- action traces
- step-by-step execution logs
- reusable successful workflows

Implication for FRIDAY:

- automatically persist conversation turns
- automatically persist action traces
- make successful sequences inspectable later

### 4. Mix deterministic execution with agent fallback

Browser and desktop agents become much more reliable when they combine:

- deterministic workflow replay
- selector/index-based actions
- fallback to a model when state changes

Implication for FRIDAY:

- keep direct selectors and indexed actions
- avoid CSS-only dependence
- support workflow-like re-execution over time

### 5. Show state to the user

Many repos expose:

- visible event streams
- state panels
- screenshots
- tool traces
- costs or timing

Implication for FRIDAY:

- return structured tool events
- keep action traces persistent
- prefer inspectable artifacts over opaque runs

### 6. Put safety and permissions up front

The best repos are explicit about:

- sandboxing
- approval boundaries
- local vs remote execution
- destructive action risk

Implication for FRIDAY:

- check host control status early
- surface Windows elevation limits clearly
- keep browser automation separate from the user's personal browser tabs unless explicitly requested

## What was added to FRIDAY because of this survey

### Already present or strengthened

- screen-aware desktop inspection and target grounding
- browser page state with indexed interactive elements
- more tool budget for local chat
- Chrome profile-aware launching
- stronger app and terminal automation

### Added from the trajectory / memory pattern

- conversation turns are now automatically persisted
- action traces are now automatically persisted
- the new memory trail can be queried later

Related files:

- `friday/tools/operator.py`
- `friday/tools/browser.py`
- `friday/tools/memory.py`
- `friday/local_chat.py`

## Patterns not copied directly

Some patterns were intentionally not copied into FRIDAY as-is:

- container-first remote desktops
- cloud-only VM orchestration
- benchmark-only frameworks
- heavyweight Electron or Flutter desktop shells
- project-specific agent protocols that would replace MCP entirely

Those are valid designs, but they would turn this project into a different product.

## Recommended next upgrades

1. Add reusable recorded workflows for desktop tasks, similar to workflow replay.
2. Add a richer browser artifact trail: screenshots, DOM snapshots, and extracted structured state.
3. Add a visible action timeline in the local web UI.
4. Add retry / recovery policies per tool family.
5. Add optional model adapters beyond the current local chat path.
