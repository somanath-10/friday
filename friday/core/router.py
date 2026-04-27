"""
Deterministic intent router for local FRIDAY commands.
"""

from __future__ import annotations

from friday.core.models import Intent, IntentResult, IntentRoute
from friday.core.risk import RiskLevel


KEYWORDS: dict[Intent, tuple[str, ...]] = {
    Intent.DESKTOP: ("open notepad", "open app", "application", "window", "click", "type", "hotkey", "screenshot"),
    Intent.BROWSER: ("browser", "chrome", "edge", "website", "url", "login", "tab", "page", "youtube", "google", "wikipedia", "github", "gmail", "amazon", "email"),
    Intent.FILES: ("file", "folder", "directory", "save", "write", "copy", "move", "rename", "delete", "downloads", "documents", "desktop"),
    Intent.SHELL: ("shell", "terminal", "command", "bash", "powershell", "command prompt", "cmd"),
    Intent.CODE: ("test", "pytest", "fix error", "repo", "code", "commit", "push", "diff", "branch"),
    Intent.RESEARCH: ("research", "search", "latest", "news", "summarize", "report"),
    Intent.VOICE: ("microphone", "voice", "speak", "transcribe"),
    Intent.MEMORY: ("remember", "memory", "preference", "forget"),
    Intent.WORKFLOW: ("workflow", "replay", "automation", "routine"),
    Intent.SYSTEM: ("volume", "settings", "system", "shutdown", "restart"),
}


RISK_KEYWORDS: tuple[tuple[RiskLevel, tuple[str, ...]], ...] = (
    (RiskLevel.DANGEROUS_RESTRICTED, ("rm -rf /", "del /s /q c:\\", "remove-item -recurse -force c:\\", "wipe", "format drive", "disable security", "disable defender", "format c drive")),
    (RiskLevel.SENSITIVE_ACTION, ("delete", "overwrite", "push", "commit", "send", "submit", "purchase", "sudo", "admin", "login", "password")),
    (RiskLevel.REVERSIBLE_CHANGE, ("move", "rename", "install", "type", "click", "open", "edit")),
    (RiskLevel.SAFE_WRITE, ("create", "save", "draft", "new file", "new folder")),
)

WINDOWS_FOLDER_NAMES = ("desktop", "downloads", "documents", "pictures", "videos", "music", "home", "workspace")
DESKTOP_APP_NAMES = (
    "notepad",
    "calculator",
    "file explorer",
    "explorer",
    "powershell",
    "command prompt",
    "cmd",
    "terminal",
    "vscode",
    "visual studio code",
    "chrome",
    "edge",
)
WEB_ACTION_MARKERS = ("search", "go to", "visit", "website", "url", "login", "bank", "google.com", "youtube", "wikipedia", "github", "gmail", "amazon", "email", "http://", "https://")


def _is_folder_open_request(text: str) -> bool:
    if not any(folder in text for folder in WINDOWS_FOLDER_NAMES):
        return False
    if "file explorer" in text or " in explorer" in text or " folder" in text:
        return True
    return text.startswith("show ") or text.startswith("open my workspace") or text.startswith("reveal ")


def _is_desktop_app_open_request(text: str) -> bool:
    if not text.startswith(("open ", "focus ", "close ")):
        return False
    if any(marker in text for marker in WEB_ACTION_MARKERS):
        return False
    return any(name in text for name in DESKTOP_APP_NAMES)


def _is_browser_workflow(text: str) -> bool:
    has_browser = "chrome" in text or "edge" in text or "browser" in text
    has_site = any(site in text for site in ("youtube", "google", "wikipedia", "github", "gmail", "amazon"))
    return (has_browser or has_site) and any(marker in text for marker in WEB_ACTION_MARKERS)


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
    if _is_folder_open_request(text):
        return IntentResult(
            intent=Intent.FILES,
            confidence=0.9,
            required_capabilities=["files"],
            likely_risk=_likely_risk(text),
            suggested_executor="files",
        )
    if _is_desktop_app_open_request(text):
        return IntentResult(
            intent=Intent.DESKTOP,
            confidence=0.88,
            required_capabilities=["desktop"],
            likely_risk=_likely_risk(text),
            suggested_executor="desktop",
        )
    if _is_browser_workflow(text):
        return IntentResult(
            intent=Intent.BROWSER,
            confidence=0.86,
            required_capabilities=["browser"],
            likely_risk=_likely_risk(text),
            suggested_executor="browser",
        )

    scores = _score_intents(text)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_intent, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0

    file_like = any(word in text for word in ("file", "folder", "save", "create", "write", "downloads", "documents", "desktop"))
    web_like = any(word in text for word in ("research", "search", "latest", "news", "website", "browser", "chrome", "edge", "youtube", "google", "wikipedia", "github", "gmail", "amazon"))

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
