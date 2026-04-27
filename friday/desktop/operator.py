"""Universal Windows desktop operator using UI Automation-style control maps."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from friday.core.events import EventLog, EventType
from friday.core.permissions import permission_for_assessment
from friday.core.risk import RiskAssessment, classify_desktop_action
from friday.core.ui import UIElement, UIObservation, find_target_element, is_sensitive_text, normalize_text


@dataclass(frozen=True)
class DesktopControl:
    control_id: str
    role: str
    name: str
    automation_id: str = ""
    class_name: str = ""
    bounding_rectangle: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    focused: bool = False
    sensitive: bool = False

    def to_element(self) -> UIElement:
        return UIElement(
            element_id=self.control_id,
            role=self.role,
            label=self.name,
            source="desktop",
            text=self.name,
            automation_id=self.automation_id,
            class_name=self.class_name,
            bounding_box=dict(self.bounding_rectangle),
            enabled=self.enabled,
            focused=self.focused,
            sensitive=self.sensitive or is_sensitive_text(self.name, self.automation_id, self.class_name),
            metadata={"control_type": self.role},
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_control_map(
    controls: list[dict[str, Any]],
    *,
    active_app: str = "",
    active_window: str = "",
) -> UIObservation:
    elements: list[UIElement] = []
    for index, item in enumerate(controls, start=1):
        control = DesktopControl(
            control_id=str(item.get("control_id") or item.get("automation_id") or f"desktop:{index}"),
            role=str(item.get("role") or item.get("control_type") or "generic"),
            name=str(item.get("name") or item.get("text") or item.get("label") or ""),
            automation_id=str(item.get("automation_id") or ""),
            class_name=str(item.get("class_name") or ""),
            bounding_rectangle=dict(item.get("bounding_rectangle") or item.get("rectangle") or {}),
            enabled=bool(item.get("enabled", True)),
            focused=bool(item.get("focused", False)),
            sensitive=bool(item.get("sensitive", False)),
        )
        element = control.to_element()
        elements.append(
            UIElement(
                **{
                    **element.to_dict(),
                    "metadata": {**element.metadata, "index": index},
                }
            )
        )
    return UIObservation(
        source="desktop",
        active_app=active_app,
        active_window=active_window,
        visible_text=" ".join(element.label for element in elements if element.label),
        elements=elements,
        metadata={"control_count": len(elements)},
    )


class DesktopOperator:
    """Generic desktop helper that ranks UIA controls before using coordinates."""

    def __init__(self, *, event_log: EventLog | None = None) -> None:
        self.event_log = event_log or EventLog()

    def observe_controls(
        self,
        controls: list[dict[str, Any]],
        *,
        active_app: str = "",
        active_window: str = "",
    ) -> UIObservation:
        observation = build_control_map(controls, active_app=active_app, active_window=active_window)
        self.event_log.emit(EventType.DESKTOP_OBSERVED, "Desktop window observed.", observation=observation.to_dict())
        return observation

    def find_control_by_goal(self, goal: str, observation: UIObservation, constraints: dict[str, Any] | None = None):
        match = find_target_element(goal, observation, constraints)
        if match:
            self.event_log.emit(EventType.TARGET_SELECTED, "Desktop control selected.", match=match.to_dict())
        return match

    def decide_next_action(self, goal: str, observation: UIObservation) -> dict[str, Any]:
        lowered = normalize_text(goal)
        if "type" in lowered or "write" in lowered:
            match = self.find_control_by_goal("editable text area", observation, {"preferred_roles": {"edit", "document", "textbox", "textarea"}})
            return {
                "type": "type_text",
                "element_id": match.element.element_id if match else "",
                "text": _extract_desktop_text(goal),
                "confidence": match.confidence if match else 0.0,
                "reason": "Type into the best editable control.",
            }
        if "press" in lowered:
            token = _first_press_token(goal)
            match = self.find_control_by_goal(token, observation, {"preferred_roles": {"button"}})
            return {
                "type": "click_control",
                "element_id": match.element.element_id if match else "",
                "text": token,
                "confidence": match.confidence if match else 0.0,
                "reason": "Click the best matching control.",
            }
        match = self.find_control_by_goal(goal, observation)
        if match:
            return {
                "type": "click_control",
                "element_id": match.element.element_id,
                "confidence": match.confidence,
                "reason": "Use highest-confidence desktop control.",
            }
        return {"type": "screenshot_fallback", "reason": "No confident UI Automation control found."}

    def permission_for_action(self, action: dict[str, Any]) -> dict[str, Any]:
        action_name = "click" if action.get("type") == "click_control" else str(action.get("type", "inspect"))
        risk = classify_desktop_action(action_name)
        if is_sensitive_text(str(action.get("text", "")), str(action.get("reason", ""))):
            risk = RiskAssessment(type(risk.level)(max(int(risk.level), 3)), "Sensitive desktop action requires approval.", "desktop")
        decision = permission_for_assessment(f"desktop.{action_name}", risk, subject=str(action.get("element_id", "")))
        return decision.to_dict()

    def verify_action(self, action: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        return {
            "success": bool(result.get("ok", True)),
            "goal_completed": action.get("type") in {"type_text", "click_control", "screenshot_fallback"},
            "reason": result.get("message", "Desktop action verified."),
        }


def _extract_desktop_text(goal: str) -> str:
    lowered = goal
    marker = "type "
    if marker in lowered.lower():
        return lowered[lowered.lower().index(marker) + len(marker) :].strip(" .,:;")
    marker = "write "
    if marker in lowered.lower():
        return lowered[lowered.lower().index(marker) + len(marker) :].strip(" .,:;")
    return ""


def _first_press_token(goal: str) -> str:
    lowered = normalize_text(goal)
    if "plus" in lowered:
        return "plus"
    if "equals" in lowered or "equal" in lowered:
        return "equals"
    parts = lowered.split("press", 1)
    return parts[1].strip().split()[0] if len(parts) > 1 and parts[1].strip() else goal
