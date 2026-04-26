"""
Intent routing for FRIDAY's structured command pipeline.
"""

from __future__ import annotations

from collections import Counter
import re

from friday.core.models import ExecutorFamily, IntentClass, IntentRoute


INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    IntentClass.DESKTOP.value: (
        "open notepad",
        "open chrome",
        "open edge",
        "application",
        "app",
        "desktop",
        "screen",
        "window",
        "type ",
        "click",
        "hotkey",
    ),
    IntentClass.BROWSER.value: (
        "browser",
        "website",
        "web page",
        "url",
        "login",
        "portal",
        "tab",
        "form",
        "open http",
        "https://",
    ),
    IntentClass.FILES.value: (
        "file",
        "folder",
        "directory",
        "read ",
        "write ",
        "save ",
        "report",
        "document",
        "downloads",
        "documents",
        "workspace",
        "move ",
        "copy ",
        "delete ",
        "rename ",
    ),
    IntentClass.SHELL.value: (
        "shell",
        "terminal",
        "powershell",
        "bash",
        "command",
        "cmd",
    ),
    IntentClass.CODE.value: (
        "run tests",
        "pytest",
        "unit test",
        "fix error",
        "fix bug",
        "repo",
        "repository",
        "code",
        "commit",
        "push",
        "pull request",
    ),
    IntentClass.RESEARCH.value: (
        "search",
        "research",
        "latest",
        "news",
        "summarize",
        "summary",
        "sources",
        "compare",
        "report",
    ),
    IntentClass.VOICE.value: (
        "voice",
        "microphone",
        "speech",
        "tts",
        "transcribe",
    ),
    IntentClass.MEMORY.value: (
        "memory",
        "remember",
        "history",
        "trace",
        "conversation",
    ),
    IntentClass.WORKFLOW.value: (
        "workflow",
        "plan",
        "preflight",
        "status",
        "resume",
        "replay",
    ),
    IntentClass.SYSTEM.value: (
        "time",
        "date",
        "volume",
        "hostname",
        "system",
        "running apps",
        "installed apps",
        "telemetry",
    ),
}

INTENT_CAPABILITIES: dict[str, list[str]] = {
    IntentClass.DESKTOP.value: ["desktop_control", "window_management", "keyboard_input"],
    IntentClass.BROWSER.value: ["browser_automation", "page_observation"],
    IntentClass.FILES.value: ["filesystem"],
    IntentClass.SHELL.value: ["shell_access"],
    IntentClass.CODE.value: ["shell_access", "repo_inspection"],
    IntentClass.RESEARCH.value: ["web_search", "report_generation"],
    IntentClass.VOICE.value: ["voice_io"],
    IntentClass.MEMORY.value: ["memory_access"],
    IntentClass.WORKFLOW.value: ["workflow_tracking"],
    IntentClass.SYSTEM.value: ["system_observation"],
    IntentClass.MIXED.value: ["multi_executor"],
}

INTENT_EXECUTORS: dict[str, str] = {
    IntentClass.DESKTOP.value: ExecutorFamily.DESKTOP.value,
    IntentClass.BROWSER.value: ExecutorFamily.BROWSER.value,
    IntentClass.FILES.value: ExecutorFamily.FILES.value,
    IntentClass.SHELL.value: ExecutorFamily.SHELL.value,
    IntentClass.CODE.value: ExecutorFamily.CODE.value,
    IntentClass.RESEARCH.value: ExecutorFamily.RESEARCH.value,
    IntentClass.VOICE.value: ExecutorFamily.SYSTEM.value,
    IntentClass.MEMORY.value: ExecutorFamily.WORKFLOW.value,
    IntentClass.WORKFLOW.value: ExecutorFamily.WORKFLOW.value,
    IntentClass.SYSTEM.value: ExecutorFamily.SYSTEM.value,
    IntentClass.MIXED.value: ExecutorFamily.WORKFLOW.value,
}


def _normalize(message: str) -> str:
    return re.sub(r"\s+", " ", (message or "").strip().lower())


def _score_intents(message: str) -> Counter[str]:
    scores: Counter[str] = Counter()
    normalized = _normalize(message)

    for intent, keywords in INTENT_KEYWORDS.items():
        for keyword in keywords:
            if keyword in normalized:
                scores[intent] += 1

    if re.search(r"\b(open|launch)\b", normalized) and any(
        word in normalized for word in ("notepad", "calculator", "spotify", "code")
    ):
        scores[IntentClass.DESKTOP.value] += 3
    if re.search(r"\b(open|visit|go to)\b", normalized) and (
        "http" in normalized or any(word in normalized for word in ("website", "portal", "login"))
    ):
        scores[IntentClass.BROWSER.value] += 3
    if "run tests" in normalized or "pytest" in normalized:
        scores[IntentClass.CODE.value] += 4
    if "latest" in normalized and any(word in normalized for word in ("news", "ai", "research")):
        scores[IntentClass.RESEARCH.value] += 4
    if any(word in normalized for word in ("delete", "remove", "wipe", "erase")):
        scores[IntentClass.FILES.value] += 2
    if any(word in normalized for word in ("commit", "push")):
        scores[IntentClass.CODE.value] += 2

    return scores


def _likely_risk(message: str) -> int:
    normalized = _normalize(message)
    if any(word in normalized for word in ("wipe", "erase drive", "credential", "password dump")):
        return 4
    if any(word in normalized for word in ("delete", "overwrite", "push", "purchase", "payment", "admin")):
        return 3
    if any(word in normalized for word in ("move", "rename", "install", "commit", "submit")):
        return 2
    if any(word in normalized for word in ("write", "create", "save", "type")):
        return 1
    return 0


def route_user_command(message: str) -> IntentRoute:
    """Route a user command to an intent and executor family."""
    normalized = _normalize(message)
    if not normalized:
        return IntentRoute(
            intent=IntentClass.MIXED.value,
            confidence=0.0,
            required_capabilities=INTENT_CAPABILITIES[IntentClass.MIXED.value],
            likely_risk=0,
            suggested_executor=INTENT_EXECUTORS[IntentClass.MIXED.value],
            rationale="No user command text was provided.",
            should_use_legacy_fallback=True,
        )

    scores = _score_intents(normalized)
    if not scores:
        return IntentRoute(
            intent=IntentClass.MIXED.value,
            confidence=0.25,
            required_capabilities=INTENT_CAPABILITIES[IntentClass.MIXED.value],
            likely_risk=_likely_risk(normalized),
            suggested_executor=INTENT_EXECUTORS[IntentClass.MIXED.value],
            rationale="The command does not match a confident structured intent.",
            should_use_legacy_fallback=True,
        )

    top_two = scores.most_common(2)
    top_intent, top_score = top_two[0]
    runner_up_score = top_two[1][1] if len(top_two) > 1 else 0
    confidence = min(0.98, 0.45 + (top_score * 0.12))
    should_fallback = False
    intent = top_intent
    rationale = f"Matched {top_score} keyword signals for intent '{top_intent}'."

    if len(top_two) > 1 and runner_up_score == top_score and top_score > 1:
        intent = IntentClass.MIXED.value
        confidence = 0.48
        rationale = "Multiple intents scored equally, so the command is treated as mixed."
        should_fallback = True
    elif confidence < 0.58:
        should_fallback = True
        rationale += " Confidence is too low for the structured pipeline."

    return IntentRoute(
        intent=intent,
        confidence=round(confidence, 2),
        required_capabilities=INTENT_CAPABILITIES.get(intent, INTENT_CAPABILITIES[IntentClass.MIXED.value]),
        likely_risk=_likely_risk(normalized),
        suggested_executor=INTENT_EXECUTORS.get(intent, INTENT_EXECUTORS[IntentClass.MIXED.value]),
        rationale=rationale,
        should_use_legacy_fallback=should_fallback,
    )
