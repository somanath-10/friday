"""Shared UI observation and semantic target selection helpers."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


SENSITIVE_TERMS = {
    "password",
    "passcode",
    "otp",
    "mfa",
    "login",
    "sign in",
    "bank",
    "card",
    "credit",
    "payment",
    "checkout",
    "purchase",
    "send",
    "submit",
    "upload",
    "delete",
    "remove",
}


ROLE_SYNONYMS: dict[str, set[str]] = {
    "search": {"search", "searchbox", "textbox", "input", "edit"},
    "searchbox": {"search", "searchbox", "textbox", "input", "edit"},
    "type": {"textbox", "input", "textarea", "edit", "document"},
    "input": {"textbox", "input", "textarea", "edit", "searchbox", "document"},
    "button": {"button", "menuitem", "tab"},
    "link": {"link", "a"},
    "video": {"link", "article", "card", "video"},
    "editable": {"edit", "textbox", "document", "textarea", "input"},
}


@dataclass(frozen=True)
class UIElement:
    element_id: str
    role: str
    label: str
    source: str = ""
    text: str = ""
    placeholder: str = ""
    value: str = ""
    href: str = ""
    selector: str = ""
    automation_id: str = ""
    class_name: str = ""
    bounding_box: dict[str, Any] = field(default_factory=dict)
    visible: bool = True
    enabled: bool = True
    focused: bool = False
    sensitive: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def searchable_text(self) -> str:
        return normalize_text(
            " ".join(
                str(value)
                for value in (
                    self.role,
                    self.label,
                    self.text,
                    self.placeholder,
                    self.value,
                    self.href,
                    self.selector,
                    self.automation_id,
                    self.class_name,
                )
                if value
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ElementMatch:
    element: UIElement
    confidence: float
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "element": self.element.to_dict(),
            "confidence": self.confidence,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class UIObservation:
    source: str
    title: str = ""
    url: str = ""
    active_app: str = ""
    active_window: str = ""
    visible_text: str = ""
    elements: list[UIElement] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "title": self.title,
            "url": self.url,
            "active_app": self.active_app,
            "active_window": self.active_window,
            "visible_text": self.visible_text,
            "elements": [element.to_dict() for element in self.elements],
            "metadata": dict(self.metadata),
        }


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def tokenize(value: str) -> list[str]:
    return [item for item in re.findall(r"[a-z0-9]+", normalize_text(value)) if item]


def is_sensitive_text(*values: str) -> bool:
    text = normalize_text(" ".join(values))
    return any(term in text for term in SENSITIVE_TERMS)


def infer_goal_constraints(goal: str) -> dict[str, Any]:
    lowered = normalize_text(goal)
    constraints: dict[str, Any] = {
        "preferred_roles": set(),
        "target_terms": tokenize(goal),
        "ordinal": 1 if "first" in lowered or "1st" in lowered else 0,
    }
    if any(term in lowered for term in ("search", "find", "look up")):
        constraints["preferred_roles"].update(ROLE_SYNONYMS["search"])
        constraints["action"] = "type"
    if any(term in lowered for term in ("type", "write", "draft", "enter")):
        constraints["preferred_roles"].update(ROLE_SYNONYMS["input"])
        constraints["action"] = "type"
    if any(term in lowered for term in ("click", "open", "press", "select", "play")):
        constraints["preferred_roles"].update(ROLE_SYNONYMS["button"])
        constraints["preferred_roles"].update(ROLE_SYNONYMS["link"])
        constraints["action"] = "click"
    if "video" in lowered or "play" in lowered:
        constraints["preferred_roles"].update(ROLE_SYNONYMS["video"])
        constraints["target_terms"].extend(["video", "watch"])
    if "channel" in lowered:
        constraints["target_terms"].append("channel")
    if "editable" in lowered or "notepad" in lowered:
        constraints["preferred_roles"].update(ROLE_SYNONYMS["editable"])
    return constraints


def _role_matches(role: str, preferred_roles: Iterable[str]) -> bool:
    normalized_role = normalize_text(role)
    preferred = {normalize_text(item) for item in preferred_roles if str(item).strip()}
    if not preferred:
        return False
    return normalized_role in preferred or any(item in normalized_role for item in preferred)


def score_element(goal: str, element: UIElement, constraints: dict[str, Any] | None = None) -> ElementMatch:
    rules = {**infer_goal_constraints(goal), **(constraints or {})}
    goal_text = normalize_text(goal)
    goal_tokens = set(tokenize(goal))
    haystack = element.searchable_text()
    label = normalize_text(element.label or element.text or element.placeholder)
    role = normalize_text(element.role)
    reasons: list[str] = []
    score = 0.0

    if not element.visible:
        score -= 0.3
        reasons.append("not visible")
    if not element.enabled:
        score -= 0.5
        reasons.append("disabled")

    if label and label == goal_text:
        score += 0.65
        reasons.append("exact label match")
    elif label and label in goal_text:
        score += 0.28
        reasons.append("label appears in goal")
    elif label and goal_text in label:
        score += 0.32
        reasons.append("goal appears in label")

    matching_tokens = goal_tokens.intersection(set(tokenize(haystack)))
    if matching_tokens:
        score += min(0.35, 0.07 * len(matching_tokens))
        reasons.append("token match: " + ", ".join(sorted(matching_tokens)[:5]))

    if _role_matches(role, rules.get("preferred_roles", set())):
        score += 0.3
        reasons.append(f"role match: {element.role}")

    if "search" in goal_text and any(term in haystack for term in ("search", "q", "query")):
        score += 0.35
        reasons.append("search field signal")

    if "first" in goal_text:
        index = int(element.metadata.get("index", 9999) or 9999)
        if index == 1:
            score += 0.18
            reasons.append("first candidate")
        elif index < 6:
            score += max(0.02, 0.12 - (index * 0.015))
            reasons.append("early candidate")

    if "video" in goal_text or "play" in goal_text:
        if any(term in haystack for term in ("watch", "video", "play", "/watch", "youtu")):
            score += 0.28
            reasons.append("video-like target")

    if element.sensitive:
        score -= 0.08
        reasons.append("sensitive target")

    return ElementMatch(element=element, confidence=max(0.0, min(score, 1.0)), reasons=reasons)


def find_target_element(
    goal: str,
    observation: UIObservation | dict[str, Any] | list[UIElement],
    constraints: dict[str, Any] | None = None,
) -> ElementMatch | None:
    if isinstance(observation, UIObservation):
        elements = observation.elements
    elif isinstance(observation, dict):
        elements = [
            item if isinstance(item, UIElement) else UIElement(**item)
            for item in observation.get("elements", [])
            if isinstance(item, (dict, UIElement))
        ]
    else:
        elements = list(observation)

    candidates = [score_element(goal, element, constraints) for element in elements]
    candidates = [match for match in candidates if match.confidence > 0]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item.confidence, reverse=True)[0]


def rank_target_elements(
    goal: str,
    observation: UIObservation | dict[str, Any] | list[UIElement],
    constraints: dict[str, Any] | None = None,
    *,
    limit: int = 10,
) -> list[ElementMatch]:
    if isinstance(observation, UIObservation):
        elements = observation.elements
    elif isinstance(observation, dict):
        elements = [
            item if isinstance(item, UIElement) else UIElement(**item)
            for item in observation.get("elements", [])
            if isinstance(item, (dict, UIElement))
        ]
    else:
        elements = list(observation)
    matches = [score_element(goal, element, constraints) for element in elements]
    return sorted(matches, key=lambda item: item.confidence, reverse=True)[: max(1, limit)]
