"""
Deterministic intent router for local FRIDAY commands.
"""

from __future__ import annotations

from friday.core.models import Intent, IntentResult, IntentRoute
from friday.core.risk import RiskLevel


KEYWORDS: dict[Intent, tuple[str, ...]] = {
    Intent.DESKTOP: ("open notepad", "open app", "application", "window", "desktop", "click", "type", "hotkey"),
    Intent.BROWSER: ("browser", "chrome", "edge", "website", "url", "login", "tab", "page"),
    Intent.FILES: ("file", "folder", "directory", "save", "write", "copy", "move", "rename", "delete", "downloads"),
    Intent.SHELL: ("shell", "terminal", "command", "bash", "powershell"),
    Intent.CODE: ("test", "pytest", "fix error", "repo", "code", "commit", "push", "diff", "branch"),
    Intent.RESEARCH: ("research", "search", "latest", "news", "summarize", "report"),
    Intent.VOICE: ("microphone", "voice", "speak", "transcribe"),
    Intent.MEMORY: ("remember", "memory", "preference", "forget"),
    Intent.WORKFLOW: ("workflow", "replay", "automation", "routine"),
    Intent.SYSTEM: ("volume", "settings", "system", "shutdown", "restart"),
}


RISK_KEYWORDS: tuple[tuple[RiskLevel, tuple[str, ...]], ...] = (
    (RiskLevel.DANGEROUS_RESTRICTED, ("rm -rf /", "wipe", "format drive", "disable security")),
    (RiskLevel.SENSITIVE_ACTION, ("delete", "overwrite", "push", "commit", "send", "submit", "purchase", "sudo", "admin")),
    (RiskLevel.REVERSIBLE_CHANGE, ("move", "rename", "install", "type", "click", "open", "edit")),
    (RiskLevel.SAFE_WRITE, ("create", "save", "draft", "new file", "new folder")),
)


def _score_intents(text: str) -> dict[Intent, int]:
    scores = {intent: 0 for intent in KEYWORDS}
    for intent, keywords in KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                scores[intent] += 2 if " " in keyword else 1
    return scores


def _likely_risk(text: str) -> RiskLevel:
    for level, keywords in RISK_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return level
    return RiskLevel.READ_ONLY


def route_intent(user_message: str) -> IntentResult:
    text = user_message.strip().lower()
    scores = _score_intents(text)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_intent, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0

    file_like = any(word in text for word in ("file", "folder", "save", "create", "write"))
    web_like = any(word in text for word in ("research", "search", "latest", "news", "website", "browser", "chrome", "edge"))

    if file_like and not web_like and scores.get(Intent.FILES, 0) > 0:
        best_intent = Intent.FILES
        confidence = 0.72
    elif best_score == 0:
        best_intent = Intent.SYSTEM
        confidence = 0.35
    elif second_score and best_score == second_score:
        best_intent = Intent.MIXED
        confidence = 0.55
    else:
        confidence = min(0.95, 0.45 + best_score * 0.12)

    if best_intent == Intent.CODE and any(word in text for word in ("push", "commit", "branch", "diff")):
        required = ["code", "git"]
        executor = "code"
    elif best_intent == Intent.MIXED:
        required = [intent.value for intent, score in scores.items() if score > 0]
        executor = "mixed"
    else:
        required = [best_intent.value]
        executor = best_intent.value

    return IntentResult(
        intent=best_intent,
        confidence=round(confidence, 2),
        required_capabilities=required,
        likely_risk=_likely_risk(text),
        suggested_executor=executor,
    )


def route_user_command(user_message: str) -> IntentRoute:
    """Compatibility wrapper for tests and the local structured chat path."""
    result = route_intent(user_message)
    should_fallback = result.confidence < 0.4 or result.intent == Intent.MIXED
    return IntentRoute(
        intent=result.intent.value,
        confidence=result.confidence,
        required_capabilities=list(result.required_capabilities),
        likely_risk=int(result.likely_risk),
        suggested_executor=result.suggested_executor,
        should_use_legacy_fallback=should_fallback,
    )
