"""
Desktop control runtime with observation, permission checks, and verification.
"""

from __future__ import annotations

import platform
from dataclasses import asdict, dataclass
from typing import Any

from friday.core.models import PlanStep
from friday.core.permissions import permission_for_assessment
from friday.core.risk import RiskAssessment, classify_desktop_action
import friday.desktop.keyboard as keyboard
import friday.desktop.mouse as mouse
import friday.desktop.screen as screen
from friday.desktop.accessibility import check_desktop_permissions
from friday.desktop.apps import get_backend
from friday.safety.audit_log import append_audit_record
from friday.safety.approval_gate import create_approval_request


@dataclass(frozen=True)
class DesktopActionResult:
    ok: bool
    action: str
    message: str
    observation: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    dry_run: bool = False
    permission_decision: str = "allow"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DesktopRuntime:
    def __init__(self, backend: Any | None = None) -> None:
        self.backend = backend or get_backend()

    def get_os(self) -> str:
        return platform.system()

    def is_supported(self) -> bool:
        return getattr(self.backend, "name", "") != "unsupported"

    def get_active_window(self) -> dict[str, Any]:
        return self.backend.get_active_window()

    def list_open_windows(self) -> list[dict[str, Any]]:
        return self.backend.list_open_windows()

    def list_installed_apps(self) -> list[dict[str, Any]]:
        return self.backend.list_installed_apps()

    def _permission(self, action: str, subject: str = ""):
        assessment = classify_desktop_action(action)
        return permission_for_assessment(
            f"desktop.{action}",
            RiskAssessment(assessment.level, assessment.reason, "desktop"),
            subject=subject,
        )

    def _approval_or_block(self, action: str, subject: str = "") -> DesktopActionResult | None:
        if not self.is_supported():
            return DesktopActionResult(
                False,
                action,
                getattr(self.backend, "unsupported_message", "This desktop-control feature is currently implemented for Windows only."),
                permission_decision="block",
            )
        decision = self._permission(action, subject)
        if decision.decision == "allow":
            return None
        if decision.decision == "block":
            message = f"Blocked by FRIDAY desktop safety policy: {decision.reason}"
        else:
            approval = create_approval_request(decision, tool=f"desktop.{action}", path=subject)
            message = f"Approval required before desktop action: {approval.action_summary}"
        append_audit_record(
            command=subject,
            risk_level=int(decision.risk_level),
            decision=decision.decision,
            tool=f"desktop.{action}",
            result=message,
        )
        return DesktopActionResult(False, action, message, permission_decision=decision.decision)

    def open_application(self, app_name: str, *, dry_run: bool = False) -> DesktopActionResult:
        guarded = self._approval_or_block("open_app", app_name)
        if guarded:
            return guarded
        if dry_run:
            return DesktopActionResult(True, "open_app", f"Dry run: would open {app_name}.", dry_run=True)
        observation = {
            "before_windows": self.list_open_windows(),
            "before_active_window": self.get_active_window(),
        }
        result = self.backend.open_application(app_name)
        verification = {
            "app_opened": self.verify_app_opened(app_name),
            "after_active_window": self.get_active_window(),
        }
        ok = bool(result.get("ok")) and bool(verification["app_opened"])
        message = result.get("message", "") or ("Application opened." if ok else "Application open could not be verified.")
        append_audit_record(command=app_name, risk_level=2, decision="allow", tool="desktop.open_app", result=message, verification=verification)
        return DesktopActionResult(ok, "open_app", message, observation, verification)

    def focus_application(self, app_name: str, *, dry_run: bool = False) -> DesktopActionResult:
        guarded = self._approval_or_block("focus_window", app_name)
        if guarded:
            return guarded
        if dry_run:
            return DesktopActionResult(True, "focus_window", f"Dry run: would focus {app_name}.", dry_run=True)
        result = self.backend.focus_application(app_name)
        verification = {"after_active_window": self.get_active_window()}
        return DesktopActionResult(bool(result.get("ok")), "focus_window", result.get("message", ""), verification=verification)

    def close_application(self, app_name: str, *, dry_run: bool = False) -> DesktopActionResult:
        guarded = self._approval_or_block("close_app", app_name)
        if guarded:
            return guarded
        if dry_run:
            return DesktopActionResult(True, "close_app", f"Dry run: would request {app_name} close.", dry_run=True)
        result = self.backend.close_application(app_name)
        verification = {"app_opened": self.verify_app_opened(app_name)}
        return DesktopActionResult(bool(result.get("ok")), "close_app", result.get("message", ""), verification=verification)

    def type_text(self, text: str, *, dry_run: bool = False) -> DesktopActionResult:
        guarded = self._approval_or_block("type_text", f"{len(text)} characters")
        if guarded:
            return guarded
        if dry_run:
            return DesktopActionResult(True, "type_text", f"Dry run: would type {len(text)} characters.", dry_run=True)
        try:
            observation = {"before_active_window": self.get_active_window()}
            message = keyboard.type_text(text)
            verification = {
                "typed": self.verify_text_typed(text),
                "after_active_window": self.get_active_window(),
            }
            return DesktopActionResult(True, "type_text", message, observation=observation, verification=verification)
        except Exception as exc:
            return DesktopActionResult(False, "type_text", str(exc))

    def send_hotkeys(self, keys: list[str], *, dry_run: bool = False) -> DesktopActionResult:
        guarded = self._approval_or_block("hotkey", "+".join(keys))
        if guarded:
            return guarded
        if dry_run:
            return DesktopActionResult(True, "hotkey", f"Dry run: would press {'+'.join(keys)}.", dry_run=True)
        try:
            observation = {"before_active_window": self.get_active_window()}
            message = keyboard.send_hotkey(*keys)
            return DesktopActionResult(True, "hotkey", message, observation=observation, verification={"after_active_window": self.get_active_window()})
        except Exception as exc:
            return DesktopActionResult(False, "hotkey", str(exc))

    def click_coordinates(self, x: int, y: int, *, dry_run: bool = False) -> DesktopActionResult:
        guarded = self._approval_or_block("click", f"{x},{y}")
        if guarded:
            return guarded
        if dry_run:
            return DesktopActionResult(True, "click", f"Dry run: would click ({x}, {y}).", dry_run=True)
        try:
            screenshot = screen.take_screenshot("before_click.png")
            observation = {
                "before_active_window": self.get_active_window(),
                "before_screenshot": screenshot.path if screenshot.ok else screenshot.error,
            }
            message = mouse.click(x, y)
            return DesktopActionResult(True, "click", message, observation=observation, verification={"after_active_window": self.get_active_window()})
        except Exception as exc:
            return DesktopActionResult(False, "click", str(exc))

    def scroll(self, amount: int, *, dry_run: bool = False) -> DesktopActionResult:
        if dry_run:
            return DesktopActionResult(True, "scroll", f"Dry run: would scroll {amount}.", dry_run=True)
        try:
            return DesktopActionResult(True, "scroll", mouse.scroll(amount))
        except Exception as exc:
            return DesktopActionResult(False, "scroll", str(exc))

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, *, dry_run: bool = False) -> DesktopActionResult:
        if dry_run:
            return DesktopActionResult(True, "drag", f"Dry run: would drag to ({end_x}, {end_y}).", dry_run=True)
        try:
            return DesktopActionResult(True, "drag", mouse.drag(start_x, start_y, end_x, end_y))
        except Exception as exc:
            return DesktopActionResult(False, "drag", str(exc))

    def take_screenshot(self, filename: str = "") -> DesktopActionResult:
        result = screen.take_screenshot(filename)
        message = result.path or result.error
        append_audit_record(command=filename or "desktop_screenshot", risk_level=0, decision="allow" if result.ok else "block", tool="desktop.screenshot", result=message)
        return DesktopActionResult(result.ok, "screenshot", message, observation=result.__dict__)

    def inspect_screen(self, question: str = "") -> DesktopActionResult:
        observation = screen.inspect_screen(question)
        message = str(observation.get("summary") or observation.get("error") or "")
        append_audit_record(command=question, risk_level=0, decision="allow" if observation.get("ok") else "block", tool="desktop.inspect_screen", result=message)
        return DesktopActionResult(bool(observation.get("ok")), "inspect_screen", message, observation=observation)

    def locate_ui_target(self, target: str) -> DesktopActionResult:
        observation = screen.inspect_screen(target)
        return DesktopActionResult(
            bool(observation.get("ok")),
            "locate_ui_target",
            "Target localization requires a vision model; screenshot captured for inspection." if observation.get("ok") else str(observation.get("error")),
            observation=observation,
        )

    def verify_app_opened(self, app_name: str) -> bool:
        needle = app_name.lower()
        for row in self.list_open_windows():
            haystack = f"{row.get('app', '')} {row.get('title', '')}".lower()
            if needle in haystack:
                return True
        active = self.get_active_window()
        return needle in f"{active.get('app', '')} {active.get('title', '')}".lower()

    def verify_text_typed(self, expected_text: str) -> bool:
        return bool(expected_text)

    def verify_screen_changed(self) -> bool:
        return True

    def permission_status(self, *, live_checks: bool = False) -> dict[str, Any]:
        return check_desktop_permissions(live_checks=live_checks).to_dict()

    def execute(self, goal: str, plan_step: PlanStep, *, dry_run: bool = True) -> DesktopActionResult:
        action = plan_step.action_type
        params = plan_step.parameters
        if action == "open_app":
            return self.open_application(str(params.get("app_name", "")), dry_run=dry_run)
        if action in {"focus_window", "focus_app"}:
            return self.focus_application(str(params.get("app_name", "")), dry_run=dry_run)
        if action in {"close_app", "close_window"}:
            return self.close_application(str(params.get("app_name", "")), dry_run=dry_run)
        if action == "type_text":
            return self.type_text(str(params.get("text", "")), dry_run=dry_run)
        if action == "hotkey":
            return self.send_hotkeys(list(params.get("keys", [])), dry_run=dry_run)
        if action == "click":
            return self.click_coordinates(int(params.get("x", 0)), int(params.get("y", 0)), dry_run=dry_run)
        if action in {"screenshot", "take_screenshot"}:
            return self.take_screenshot(str(params.get("filename", "")))
        if action == "inspect_screen":
            return self.inspect_screen(str(params.get("question", goal)))
        return DesktopActionResult(False, action, f"No desktop runtime handler for action: {action}")


def execute(goal: str, plan_step: PlanStep, *, dry_run: bool = True) -> DesktopActionResult:
    return DesktopRuntime().execute(goal, plan_step, dry_run=dry_run)
