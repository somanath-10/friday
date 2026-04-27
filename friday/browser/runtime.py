"""Local browser automation runtime with permission-aware actions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from friday.browser.dom_snapshot import DomSnapshot, format_indexed_elements, parse_html_snapshot
from friday.browser.downloads import check_download_permission, download_target_path
from friday.browser.forms import check_form_submit_permission
from friday.browser.operator import BrowserOperator, build_element_map_from_html, infer_site_url
from friday.browser.profile_manager import BrowserProfilePolicy, ensure_isolated_profile, load_profile_policy
from friday.browser.playwright_controller import playwright_readiness
from friday.core.models import PlanStep
from friday.core.permissions import PermissionDecision, permission_for_assessment
from friday.core.risk import RiskAssessment, classify_browser_action
from friday.safety.audit_log import append_audit_record
from friday.safety.approval_gate import create_approval_request


@dataclass(frozen=True)
class BrowserResult:
    ok: bool
    action: str
    message: str
    observation: dict[str, Any] = field(default_factory=dict)
    verification: dict[str, Any] = field(default_factory=dict)
    permission_decision: str = "allow"
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BrowserRuntime:
    def __init__(self, profile_policy: BrowserProfilePolicy | None = None) -> None:
        self.profile_policy = profile_policy or load_profile_policy()
        self.current_url = ""
        self.snapshot: DomSnapshot | None = None

    def readiness(self) -> dict[str, Any]:
        readiness = playwright_readiness().to_dict()
        readiness["profile_policy"] = self.profile_policy.to_dict()
        return readiness

    def _permission(self, action: str, subject: str = "") -> PermissionDecision:
        assessment = classify_browser_action(action)
        return permission_for_assessment(
            f"browser.{action}",
            RiskAssessment(assessment.level, assessment.reason, "browser"),
            subject=subject,
        )

    def _guard(self, action: str, subject: str = "") -> BrowserResult | None:
        decision = self._permission(action, subject)
        if decision.decision == "allow":
            return None
        if decision.decision == "block":
            message = f"Blocked by FRIDAY browser safety policy: {decision.reason}"
        else:
            approval = create_approval_request(decision, tool=f"browser.{action}", domain=subject)
            message = f"Approval required before browser action: {approval.action_summary}"
        append_audit_record(command=subject, risk_level=int(decision.risk_level), decision=decision.decision, tool=f"browser.{action}", result=message)
        return BrowserResult(False, action, message, permission_decision=decision.decision)

    def launch(self, browser_name: str = "edge", *, dry_run: bool = False) -> BrowserResult:
        profile = ensure_isolated_profile(self.profile_policy)
        readiness = self.readiness()
        message = (
            f"Dry run: would launch {browser_name} with FRIDAY's isolated profile at {profile}"
            if dry_run
            else f"Browser profile ready for {browser_name}: {profile}"
        )
        return BrowserResult(True, "launch", message, observation=readiness, dry_run=dry_run)

    def navigate(self, url: str, *, dry_run: bool = False) -> BrowserResult:
        guarded = self._guard("navigate", url)
        if guarded:
            return guarded
        if dry_run:
            return BrowserResult(True, "navigate", f"Dry run: would navigate to {url}.", dry_run=True)
        self.current_url = url
        self.snapshot = DomSnapshot(title=url, text="", elements=[], url=url)
        append_audit_record(command=url, risk_level=0, decision="allow", tool="browser.navigate", result="navigation recorded")
        return BrowserResult(True, "navigate", f"Navigation target recorded: {url}", verification={"url": url})

    def observe_html(self, html: str, *, url: str = "") -> BrowserResult:
        self.current_url = url or self.current_url
        self.snapshot = parse_html_snapshot(html, base_url=self.current_url)
        text = format_indexed_elements(self.snapshot)
        return BrowserResult(True, "observe", text, observation=self.snapshot.to_dict(), verification={"elements": len(self.snapshot.elements)})

    def click_element(self, index: int, *, dry_run: bool = False) -> BrowserResult:
        guarded = self._guard("click", self.current_url)
        if guarded:
            return guarded
        if not self.snapshot:
            return BrowserResult(False, "click", "No browser snapshot is available; observe before clicking.")
        element = next((item for item in self.snapshot.elements if item.index == index), None)
        if element is None:
            return BrowserResult(False, "click", f"No indexed element at {index}.")
        if dry_run:
            return BrowserResult(True, "click", f"Dry run: would click [{index}] {element.label}.", dry_run=True)
        return BrowserResult(True, "click", f"Clicked [{index}] {element.label}.", verification={"clicked_index": index})

    def type_into_field(self, index: int, text: str, *, dry_run: bool = False) -> BrowserResult:
        guarded = self._guard("type", self.current_url)
        if guarded:
            return guarded
        if dry_run:
            return BrowserResult(True, "type", f"Dry run: would type {len(text)} characters into [{index}].", dry_run=True)
        return BrowserResult(True, "type", f"Typed {len(text)} characters into [{index}].", verification={"typed": bool(text)})

    def submit_form(self, label: str = "", *, fields: list[str] | None = None, dry_run: bool = False) -> BrowserResult:
        decision = check_form_submit_permission(label, self.current_url, fields)
        if decision.decision != "allow":
            approval = create_approval_request(decision, tool="browser.submit_form", domain=self.current_url)
            message = f"Approval required before browser form submit: {approval.action_summary}" if decision.decision == "ask" else decision.reason
            append_audit_record(command=self.current_url, risk_level=int(decision.risk_level), decision=decision.decision, tool="browser.submit_form", result=message)
            return BrowserResult(False, "submit_form", message, permission_decision=decision.decision, dry_run=dry_run)
        return BrowserResult(True, "submit_form", "Dry run: would submit form." if dry_run else "Submitted form.", dry_run=dry_run)

    def plan_download(self, filename: str) -> BrowserResult:
        target = download_target_path(filename)
        decision = check_download_permission(target)
        ok = decision.decision == "allow"
        return BrowserResult(ok, "download", f"Download target: {target}" if ok else decision.reason, permission_decision=decision.decision)

    def dynamic_task(self, goal: str, *, html: str = "", dry_run: bool = False) -> BrowserResult:
        operator = BrowserOperator()
        if html:
            observation = build_element_map_from_html(html, url=self.current_url)
        elif self.snapshot:
            from friday.browser.operator import build_element_map_from_dom

            observation = build_element_map_from_dom(self.snapshot)
        else:
            observation = build_element_map_from_html("<title>Blank</title>", url=infer_site_url(goal))
        loop = operator.run_dry_loop(goal, observation, max_steps=4)
        append_audit_record(
            command=goal,
            risk_level=0,
            decision="allow" if loop.status != "approval_required" else "ask",
            tool="browser.dynamic_operator",
            result=loop.message,
            verification={"status": loop.status},
        )
        return BrowserResult(
            loop.completed or dry_run,
            "dynamic_browser_task",
            loop.message,
            observation=observation.to_dict(),
            verification=loop.to_dict(),
            permission_decision="ask" if loop.status == "approval_required" else "allow",
            dry_run=dry_run,
        )

    def execute(self, goal: str, plan_step: PlanStep, *, dry_run: bool = True) -> BrowserResult:
        action = plan_step.action_type
        params = plan_step.parameters
        if action in {"launch", "browser.launch"}:
            return self.launch(str(params.get("browser", "edge")), dry_run=dry_run)
        if action in {"browser_observe", "observe"}:
            return BrowserResult(True, "observe", f"Dry run: would observe browser for {goal}.", dry_run=True)
        if action in {"navigate", "browser.navigate"}:
            return self.navigate(str(params.get("url", "")), dry_run=dry_run)
        if action in {"click", "browser.click"}:
            return self.click_element(int(params.get("index", 1)), dry_run=dry_run)
        if action in {"type", "browser.type"}:
            return self.type_into_field(int(params.get("index", 1)), str(params.get("text", "")), dry_run=dry_run)
        if action in {"submit", "browser.submit"}:
            return self.submit_form(str(params.get("label", "")), fields=list(params.get("fields", [])), dry_run=dry_run)
        if action in {"dynamic_browser_task", "browser_dynamic_loop"}:
            return self.dynamic_task(str(params.get("goal", goal)), html=str(params.get("html", "")), dry_run=dry_run)
        return BrowserResult(False, action, f"No browser runtime handler for action: {action}")
