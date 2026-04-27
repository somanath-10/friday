"""Browser form sensitivity helpers."""

from __future__ import annotations

from friday.core.permissions import PermissionDecision, check_tool_permission


SENSITIVE_FORM_MARKERS = (
    "password",
    "payment",
    "card",
    "bank",
    "ssn",
    "otp",
    "2fa",
    "send",
    "submit",
    "purchase",
    "checkout",
    "email",
    "message",
)


def is_sensitive_form_action(label: str = "", url: str = "", fields: list[str] | None = None) -> bool:
    haystack = " ".join([label, url, " ".join(fields or [])]).lower()
    return any(marker in haystack for marker in SENSITIVE_FORM_MARKERS)


def check_form_submit_permission(label: str = "", url: str = "", fields: list[str] | None = None) -> PermissionDecision:
    action = "browser_submit_sensitive_form" if is_sensitive_form_action(label, url, fields) else "browser_submit_form"
    return check_tool_permission(action, {"current_url": url, "element_label": label, "fields": fields or []})
