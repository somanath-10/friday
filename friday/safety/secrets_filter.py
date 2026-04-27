"""
Secret detection and redaction helpers.

These functions are deliberately conservative: they redact recognizable tokens
from logs and block obvious credential files from being read by default.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


REDACTION = "[REDACTED_SECRET]"

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-proj-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bASIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----.*?-----END (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----", re.DOTALL),
    re.compile(r"(?i)\b(password|api[_-]?key|secret|token)\s*[:=]\s*['\"]?[^'\"\s]{8,}"),
)

PROTECTED_FILENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "token.json",
    "secrets.json",
    "known_hosts",
}

PROTECTED_PARTS = {
    ".ssh",
    ".aws",
    ".azure",
    ".config/gcloud",
    "keychains",
    "login.keychain-db",
}


def redact_text(text: str) -> str:
    """Return text with known secret patterns replaced."""
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(REDACTION, redacted)
    return redacted


def redact_value(value: Any) -> Any:
    """Recursively redact strings in nested JSON-like data."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {str(key): redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return value


def contains_secret(text: str) -> bool:
    return redact_text(text) != text


def is_protected_secret_path(path: str | Path) -> bool:
    """Return True for obvious local credential stores and token files."""
    candidate = Path(path).expanduser()
    name = candidate.name.lower()
    if name in PROTECTED_FILENAMES:
        return True

    normalized = str(candidate).replace("\\", "/").lower()
    return any(part in normalized for part in PROTECTED_PARTS)
