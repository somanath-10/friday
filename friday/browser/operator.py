"""Universal browser operator built around observation and element maps."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import quote_plus

from friday.browser.dom_snapshot import DomSnapshot, parse_html_snapshot
from friday.core.events import EventLog, EventType
from friday.core.operator_loop import OperatorLoop, OperatorLoopConfig, OperatorLoopResult
from friday.core.permissions import permission_for_assessment
from friday.core.risk import RiskAssessment, classify_browser_action
from friday.core.ui import (
    HIGH_CONFIDENCE_THRESHOLD,
    MEDIUM_CONFIDENCE_THRESHOLD,
    UIElement,
    UIObservation,
    find_target_element,
    is_sensitive_text,
    normalize_text,
)
from friday.safety.audit_log import append_audit_record


SITE_URLS: dict[str, str] = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "wikipedia": "https://www.wikipedia.org",
    "github": "https://github.com",
    "gmail": "https://mail.google.com",
    "amazon": "https://www.amazon.com",
}


@dataclass(frozen=True)
class BrowserAction:
    type: str
    element_id: str = ""
    text: str = ""
    url: str = ""
    key: str = ""
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def infer_site_url(goal: str) -> str:
    lowered = normalize_text(goal)
    explicit = re.search(r"https?://[^\s]+", goal)
    if explicit:
        return explicit.group(0).strip(".,;)")
    for site, url in SITE_URLS.items():
        if site in lowered:
            return url
    domain = re.search(r"\b([a-z0-9-]+\.(?:com|org|net|io|dev|ai|co))\b", lowered)
    if domain:
        return "https://" + domain.group(1)
    return ""


def extract_search_query(goal: str) -> str:
    text = goal.strip()
    patterns = (
        r"\bsearch\s+(?:youtube|google|wikipedia|github|amazon)\s+for\s+(.+?)(?:\s+and\s+(?:open|click|play|summarize|save)\b|$)",
        r"\bsearch(?: for)?\s+(.+?)(?:\s+and\s+(?:open|click|play|summarize|save)\b|$)",
        r"\blook up\s+(.+?)(?:\s+and\s+|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            query = match.group(1).strip(" .,:;")
            query = re.sub(r"\bon\s+(youtube|google|wikipedia|github|amazon)\b", "", query, flags=re.IGNORECASE).strip()
            query = re.sub(r"^(youtube|google|wikipedia|github|amazon)\s+for\s+", "", query, flags=re.IGNORECASE).strip()
            return query
    return ""


def wants_first_result_click(goal: str) -> bool:
    lowered = normalize_text(goal)
    first_target = any(
        phrase in lowered
        for phrase in (
            "first video",
            "first result",
            "first one",
            "1st video",
            "1st result",
        )
    )
    click_target = any(word in lowered for word in ("open", "click", "play", "select"))
    only_video = ("only click" in lowered or "u only click" in lowered or "you only click" in lowered) and "video" in lowered
    return (first_target and click_target) or only_video


def _has_action(history: list[dict[str, Any]], action_type: str) -> bool:
    return any(action.get("type") == action_type for action in history)


def _first_relevant_result(observation: UIObservation, *, target_type: str = "result") -> tuple[UIElement, float] | None:
    target_type = normalize_text(target_type)
    candidates = [element for element in observation.elements if element.visible and element.enabled]
    if not candidates:
        return None

    def score(element: UIElement) -> tuple[int, int]:
        haystack = element.searchable_text()
        role = normalize_text(element.role)
        index = int(element.metadata.get("index", 9999) or 9999)
        value = 0
        if role in {"link", "a", "card", "article", "video"}:
            value += 20
        if element.href:
            value += 15
        if target_type == "video":
            if "/watch" in haystack or "watch?v=" in haystack:
                value += 80
            if any(marker in haystack for marker in ("video", "views", "duration", "play", "youtu")):
                value += 25
            if any(marker in haystack for marker in ("shorts", "playlist", "channel", "ad", "sponsored")):
                value -= 25
        else:
            if role in {"link", "a", "card", "article"}:
                value += 35
            if any(marker in haystack for marker in ("ad", "sponsored")):
                value -= 20
        return value, -index

    ranked = sorted(candidates, key=score, reverse=True)
    best = ranked[0]
    raw_score = score(best)[0]
    if raw_score <= 0:
        return None
    confidence = min(0.95, max(0.45, raw_score / 100.0))
    return best, confidence


def _low_confidence_action(goal: str, confidence: float, *, target: str = "target") -> BrowserAction:
    return BrowserAction(
        "needs_clarification",
        reason=(
            f"I found a possible browser {target}, but confidence was {confidence:.2f}. "
            "Please clarify the target before I click."
        ),
        metadata={"confidence": confidence, "goal": goal, "target": target},
    )


def _extract_named_target(goal: str) -> str:
    patterns = (
        r"\b(?:click|open|select)\s+(?:the\s+)?(?:named\s+)?(?:result|link|button)\s+(.+)$",
        r"\b(?:click|open|select)\s+(.+?)\s+(?:result|link|button)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, goal, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .,:;\"'")
    quoted = re.search(r"['\"]([^'\"]+)['\"]", goal)
    return quoted.group(1).strip() if quoted else ""


def _extract_fill_text(goal: str) -> str:
    patterns = (
        r"\b(?:type|enter|fill)\s+['\"]([^'\"]+)['\"]",
        r"\b(?:type|enter|fill)\s+(.+?)(?:\s+into|\s+in\s+the|\s+in\s+|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, goal, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" .,:;")
    return ""


def _extract_fill_target(goal: str) -> str:
    match = re.search(r"\b(?:into|in the|in)\s+([a-zA-Z0-9 _-]+)$", goal, flags=re.IGNORECASE)
    if not match:
        return ""
    target = match.group(1).strip(" .,:;")
    return "" if target.lower() in {"field", "input", "box"} else target


def build_element_map_from_dom(snapshot: DomSnapshot) -> UIObservation:
    elements: list[UIElement] = []
    for index, item in enumerate(snapshot.elements, start=1):
        label = item.label or item.name or item.href or f"{item.tag} {index}"
        role = item.role or _role_from_tag(item.tag, item.input_type, label)
        metadata = {
            "index": index,
            "tag": item.tag,
            "input_type": item.input_type,
            "name": item.name,
            "locator_strategy": f"indexed:{index}",
            "confidence": 1.0,
        }
        elements.append(
            UIElement(
                element_id=f"browser:{index}",
                role=role,
                label=label,
                source="browser",
                text=label,
                placeholder=label if item.tag in {"input", "textarea"} else "",
                href=item.href,
                selector=f"indexed:{index}",
                visible=True,
                enabled=not item.disabled,
                sensitive=is_sensitive_text(label, item.input_type, item.href),
                metadata=metadata,
            )
        )
    return UIObservation(
        source="browser",
        title=snapshot.title,
        url=snapshot.url,
        visible_text=snapshot.text,
        elements=elements,
        metadata={"element_count": len(elements)},
    )


def build_element_map_from_records(
    records: list[dict[str, Any]],
    *,
    title: str = "",
    url: str = "",
    visible_text: str = "",
) -> UIObservation:
    elements: list[UIElement] = []
    for index, item in enumerate(records, start=1):
        role = str(item.get("role") or _role_from_tag(str(item.get("tag", "")), str(item.get("type", ""))))
        label = str(
            item.get("text")
            or item.get("ariaLabel")
            or item.get("placeholder")
            or item.get("title")
            or item.get("name")
            or item.get("href")
            or f"{role} {index}"
        )
        bbox = {
            "x": item.get("x"),
            "y": item.get("y"),
            "width": item.get("width"),
            "height": item.get("height"),
        }
        elements.append(
            UIElement(
                element_id=f"browser:{item.get('index', index)}",
                role=role,
                label=label,
                source="browser",
                text=str(item.get("text") or label),
                placeholder=str(item.get("placeholder") or ""),
                value=str(item.get("value") or ""),
                href=str(item.get("href") or ""),
                selector=str(item.get("selector") or f"indexed:{item.get('index', index)}"),
                bounding_box={key: value for key, value in bbox.items() if value is not None},
                enabled=not bool(item.get("disabled")),
                sensitive=is_sensitive_text(label, str(item.get("type", "")), str(item.get("href", ""))),
                metadata={
                    "index": int(item.get("index", index)),
                    "tag": item.get("tag", ""),
                    "type": item.get("type", ""),
                    "locator_strategy": str(item.get("selector") or f"indexed:{item.get('index', index)}"),
                    "confidence": float(item.get("confidence", 1.0) or 1.0),
                },
            )
        )
    return UIObservation("browser", title=title, url=url, visible_text=visible_text, elements=elements, metadata={"element_count": len(elements)})


def build_element_map_from_html(html: str, *, url: str = "") -> UIObservation:
    return build_element_map_from_dom(parse_html_snapshot(html, base_url=url))


def _role_from_tag(tag: str, input_type: str = "", label: str = "") -> str:
    lowered_tag = tag.lower()
    lowered_type = input_type.lower()
    lowered_label = normalize_text(label)
    if lowered_tag == "a":
        return "link"
    if lowered_tag == "button":
        return "button"
    if lowered_tag == "textarea":
        return "textarea"
    if lowered_tag == "select":
        return "combobox"
    if lowered_tag == "input":
        if "search" in lowered_label:
            return "searchbox"
        if lowered_type in {"search", "text", "email", "url", ""}:
            return "searchbox" if lowered_type == "search" else "textbox"
        return lowered_type
    return lowered_tag or "generic"


def _goal_completed(goal: str, observation: UIObservation, actions: list[dict[str, Any]]) -> bool:
    lowered = normalize_text(goal)
    if "summarize" in lowered and observation.visible_text:
        return True
    if wants_first_result_click(goal) and _has_action(actions, "click_element"):
        return True
    if any(action.get("type") == "type_into_element" for action in actions) and "search" in lowered and not wants_first_result_click(goal):
        return True
    return False


class BrowserOperator:
    """Generic browser task helper that works from page observations, not site-specific selectors."""

    def __init__(self, *, event_log: EventLog | None = None) -> None:
        self.event_log = event_log or EventLog()

    def observe_html(self, html: str, *, url: str = "") -> UIObservation:
        observation = build_element_map_from_html(html, url=url)
        self.event_log.emit(EventType.BROWSER_OBSERVED, "Browser page observed.", observation=observation.to_dict())
        return observation

    def find_element_by_goal(self, goal: str, observation: UIObservation, constraints: dict[str, Any] | None = None):
        match = find_target_element(goal, observation, constraints)
        if match:
            self.event_log.emit(EventType.TARGET_SELECTED, "Browser target selected.", match=match.to_dict())
        return match

    def decide_next_action(self, goal: str, observation: UIObservation, history: list[dict[str, Any]] | None = None) -> BrowserAction:
        history = history or []
        lowered = normalize_text(goal)
        if _goal_completed(goal, observation, history):
            return BrowserAction("complete", reason="Browser goal appears complete.")

        if not observation.url:
            target_url = infer_site_url(goal)
            if not target_url and extract_search_query(goal):
                target_url = "https://www.google.com/search?q=" + quote_plus(extract_search_query(goal))
            if target_url:
                return BrowserAction("navigate", url=target_url, reason="Navigate to requested site.")

        query = extract_search_query(goal)
        if query and not any(action.get("type") == "type_into_element" for action in history):
            match = self.find_element_by_goal("search input", observation, {"preferred_roles": {"searchbox", "textbox", "input"}})
            if match:
                if match.confidence < MEDIUM_CONFIDENCE_THRESHOLD:
                    return _low_confidence_action(goal, match.confidence, target="search field")
                return BrowserAction("type_into_element", element_id=match.element.element_id, text=query, key="Enter", reason="Fill the best search field.", metadata={"confidence": match.confidence})

        fill_text = _extract_fill_text(goal)
        if fill_text and not any(action.get("type") == "type_into_element" for action in history):
            fill_target = _extract_fill_target(goal)
            target_goal = f"{fill_target} input" if fill_target else "editable input"
            match = self.find_element_by_goal(target_goal, observation, {"preferred_roles": {"searchbox", "textbox", "textarea", "input"}})
            if match:
                if match.confidence < MEDIUM_CONFIDENCE_THRESHOLD and not match.element.focused:
                    return _low_confidence_action(goal, match.confidence, target="editable field")
                return BrowserAction("type_into_element", element_id=match.element.element_id, text=fill_text, reason="Type into the best matching input.", metadata={"confidence": match.confidence})

        if "submit" in lowered or "send form" in lowered:
            match = self.find_element_by_goal("submit button", observation, {"preferred_roles": {"button"}})
            if match:
                confidence = match.confidence
                if "submit" in match.element.searchable_text() and "button" in normalize_text(match.element.role):
                    confidence = max(confidence, 0.82)
                if confidence < HIGH_CONFIDENCE_THRESHOLD:
                    return _low_confidence_action(goal, confidence, target="submit control")
                return BrowserAction("submit_form", element_id=match.element.element_id, reason="Submit the best matching form control.", metadata={"confidence": confidence})

        if wants_first_result_click(goal):
            target_type = "video" if "video" in lowered or "youtube" in lowered or "play" in lowered else "result"
            first_match = _first_relevant_result(observation, target_type=target_type)
            if first_match:
                element, confidence = first_match
                if confidence < MEDIUM_CONFIDENCE_THRESHOLD:
                    return _low_confidence_action(goal, confidence, target=target_type)
                return BrowserAction(
                    "click_element",
                    element_id=element.element_id,
                    reason=f"Open the first visible {target_type} target.",
                    metadata={"target_type": target_type, "index": element.metadata.get("index"), "confidence": confidence},
                )
            match = self.find_element_by_goal("first video" if target_type == "video" else "first result", observation, {"preferred_roles": {"link", "video", "card", "article"}})
            if match:
                if match.confidence < MEDIUM_CONFIDENCE_THRESHOLD:
                    return _low_confidence_action(goal, match.confidence, target=target_type)
                return BrowserAction("click_element", element_id=match.element.element_id, reason=f"Open the best matching {target_type} target.", metadata={"confidence": match.confidence, "target_type": target_type})

        named_target = _extract_named_target(goal)
        if named_target:
            match = self.find_element_by_goal(named_target, observation, {"preferred_roles": {"link", "button", "card", "article"}})
            if match:
                if match.confidence < HIGH_CONFIDENCE_THRESHOLD:
                    return _low_confidence_action(goal, match.confidence, target=named_target)
                return BrowserAction("click_element", element_id=match.element.element_id, reason="Open the named browser target.", metadata={"confidence": match.confidence, "target": named_target})

        if "draft" in lowered or "email" in lowered:
            match = self.find_element_by_goal("compose draft email", observation)
            if match:
                if match.confidence < HIGH_CONFIDENCE_THRESHOLD:
                    return _low_confidence_action(goal, match.confidence, target="drafting control")
                return BrowserAction("click_element", element_id=match.element.element_id, reason="Open the best drafting control.", metadata={"confidence": match.confidence})

        match = self.find_element_by_goal(goal, observation)
        if match and match.confidence >= HIGH_CONFIDENCE_THRESHOLD:
            return BrowserAction("click_element", element_id=match.element.element_id, reason="Use highest-confidence browser target.", metadata={"confidence": match.confidence})
        if match and match.confidence >= MEDIUM_CONFIDENCE_THRESHOLD:
            return _low_confidence_action(goal, match.confidence, target=match.element.label or match.element.role)

        return BrowserAction("screenshot_fallback", reason="No confident DOM/accessibility target found.")

    def permission_for_action(self, action: BrowserAction, observation: UIObservation | None = None) -> dict[str, Any]:
        subject = action.url or action.element_id or action.reason
        action_name = "submit" if action.type in {"submit_form", "purchase", "send_message"} else action.type
        risk = classify_browser_action(action_name)
        if is_sensitive_text(action.reason, action.text, subject, observation.url if observation else ""):
            risk = RiskAssessment(type(risk.level)(max(int(risk.level), 3)), "Sensitive browser workflow requires approval.", "browser")
        decision = permission_for_assessment(f"browser.{action_name}", risk, subject=subject)
        return decision.to_dict()

    def execute_dry_action(self, action: BrowserAction) -> dict[str, Any]:
        return {"ok": True, "dry_run": True, "action": action.to_dict(), "message": f"Dry run: would {action.type}."}

    def verify_action(self, observation: UIObservation, action: BrowserAction, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "success": bool(result.get("ok")),
            "goal_completed": action.type in {"complete", "screenshot_fallback"},
            "reason": result.get("message", "Browser action verified."),
        }

    def recover_from_error(self, observation: UIObservation, action: BrowserAction, result: dict[str, Any]) -> dict[str, Any]:
        if action.type == "screenshot_fallback":
            return {"retryable": False, "reason": "Screenshot fallback required user/model visual inspection."}
        return {"retryable": True, "reason": "Retry after re-observing page or using alternate locator."}

    def run_dry_loop(self, goal: str, observation: UIObservation, *, max_steps: int = 4) -> OperatorLoopResult:
        actions: list[dict[str, Any]] = []

        def observe() -> dict[str, Any]:
            return observation.to_dict()

        def decide(raw_observation: dict[str, Any], _steps) -> dict[str, Any]:
            state = UIObservation(
                source=raw_observation["source"],
                title=raw_observation.get("title", ""),
                url=raw_observation.get("url", ""),
                visible_text=raw_observation.get("visible_text", ""),
                elements=[UIElement(**item) for item in raw_observation.get("elements", [])],
                metadata=dict(raw_observation.get("metadata", {})),
            )
            action = self.decide_next_action(goal, state, actions)
            payload = action.to_dict()
            actions.append(payload)
            return payload

        def permission(action: dict[str, Any]) -> dict[str, Any]:
            browser_action = BrowserAction(**{key: action.get(key) for key in BrowserAction.__dataclass_fields__.keys() if key in action})
            return self.permission_for_action(browser_action, observation)

        def execute(action: dict[str, Any]) -> dict[str, Any]:
            browser_action = BrowserAction(**{key: action.get(key) for key in BrowserAction.__dataclass_fields__.keys() if key in action})
            return self.execute_dry_action(browser_action)

        def verify(_observation: dict[str, Any], action: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
            browser_action = BrowserAction(**{key: action.get(key) for key in BrowserAction.__dataclass_fields__.keys() if key in action})
            verification = self.verify_action(observation, browser_action, result)
            verification["goal_completed"] = browser_action.type in {"complete", "screenshot_fallback"} or _goal_completed(goal, observation, actions)
            return verification

        def recover(_observation: dict[str, Any], action: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
            browser_action = BrowserAction(**{key: action.get(key) for key in BrowserAction.__dataclass_fields__.keys() if key in action})
            return self.recover_from_error(observation, browser_action, result)

        return OperatorLoop(event_log=self.event_log, config=OperatorLoopConfig(max_steps=max_steps, dry_run=True)).run(
            observe=observe,
            decide=decide,
            permission=permission,
            execute=execute,
            verify=verify,
            recover=recover,
        )


def summarize_browser_observation(observation: UIObservation, limit: int = 12) -> str:
    lines = [
        f"Title: {observation.title}",
        f"URL: {observation.url}",
        f"Elements: {len(observation.elements)}",
    ]
    for element in observation.elements[: max(1, limit)]:
        sensitivity = " sensitive" if element.sensitive else ""
        lines.append(f"- {element.element_id} {element.role}{sensitivity}: {element.label}")
    return "\n".join(lines)
