"""
High-level safety policy checks that sit above tool-specific permission rules.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from friday.safety.secrets_filter import contains_secret


@dataclass(frozen=True)
class SafetyPolicyDecision:
    decision: str
    reason: str
    policy: str = "default"

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


BLOCKED_ACTION_MARKERS = (
    "disable security",
    "bypass authentication",
    "credential theft",
    "extract passwords",
    "hidden surveillance",
    "malware persistence",
    "autostart without approval",
)


def evaluate_safety_policy(action: str, context: dict[str, Any] | None = None) -> SafetyPolicyDecision:
    """Block policy-violating actions before normal permission logic runs."""
    text = action.lower()
    context = context or {}
    context_text = " ".join(str(value) for value in context.values()).lower()
    haystack = f"{text} {context_text}"

    if any(marker in haystack for marker in BLOCKED_ACTION_MARKERS):
        return SafetyPolicyDecision("block", "Action violates FRIDAY's local safety policy.", "restricted_action")

    outgoing_payload = str(context.get("outgoing_payload", ""))
    if outgoing_payload and contains_secret(outgoing_payload):
        return SafetyPolicyDecision("block", "Refusing to send apparent secrets to an external destination.", "secret_exfiltration")

    if context.get("background") and not context.get("user_started"):
        return SafetyPolicyDecision("block", "Hidden background actions require explicit user initiation.", "background_action")

    return SafetyPolicyDecision("allow", "Policy check passed.", "default")
