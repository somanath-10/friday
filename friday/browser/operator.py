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
from friday.core.ui import UIElement, UIObservation, find_target_element, is_sensitive_text, normalize_text
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
        r"\bsearch(?: for)?\s+(.+?)(?:\s+and\s+(?:open|click|play|summarize|save)\b|$)",
        r"\blook up\s+(.+?)(?:\s+and\s+|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            query = match.group(1).strip(" .,:;")
            query = re.sub(r"\bon\s+(youtube|google|wikipedia|github|amazon)\b", "", query, flags=re.IGNORECASE).strip()
            return query
    return ""


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
                metadata={"index": int(item.get("index", index)), "tag": item.get("tag", ""), "type": item.get("type", "")},
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
    if any(action.get("type") == "click_element" and ("first video" in lowered or "play" in lowered) for action in actions):
        return True
    if any(action.get("type") == "type_into_element" for action in actions) and "search" in lowered:
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
                return BrowserAction("type_into_element", element_id=match.element.element_id, text=query, key="Enter", reason="Fill the best search field.", metadata={"confidence": match.confidence})

        if "first video" in lowered or "play" in lowered:
            match = self.find_element_by_goal("first video", observation, {"preferred_roles": {"link", "video", "card"}})
            if match:
                return BrowserAction("click_element", element_id=match.element.element_id, reason="Open the best matching video target.", metadata={"confidence": match.confidence})

        if "draft" in lowered or "email" in lowered:
            match = self.find_element_by_goal("compose draft email", observation)
            if match:
                return BrowserAction("click_element", element_id=match.element.element_id, reason="Open the best drafting control.", metadata={"confidence": match.confidence})

        match = self.find_element_by_goal(goal, observation)
        if match and match.confidence >= 0.25:
            return BrowserAction("click_element", element_id=match.element.element_id, reason="Use highest-confidence browser target.", metadata={"confidence": match.confidence})

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
