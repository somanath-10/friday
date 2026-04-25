"""
Configuration helpers and app-wide settings.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_csv(name: str) -> set[str]:
    raw = os.getenv(name, "")
    return {
        item.strip().lower()
        for item in raw.split(",")
        if item.strip()
    }


def disabled_tool_modules() -> set[str]:
    disabled = env_csv("FRIDAY_DISABLED_TOOL_MODULES")
    if not env_bool("FRIDAY_ENABLE_CALENDAR_TOOL", False):
        disabled.add("calendar_tool")
    return disabled


def tool_module_enabled(module_name: str) -> bool:
    return module_name.strip().lower() not in disabled_tool_modules()


class Config:
    SERVER_NAME: str = os.getenv("SERVER_NAME", "Friday")
    DEBUG: bool = env_bool("DEBUG", False)
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")


config = Config()
