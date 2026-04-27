"""Browser profile policy for FRIDAY automation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from friday.core.permissions import load_permissions_config
from friday.path_utils import workspace_dir


@dataclass(frozen=True)
class BrowserProfilePolicy:
    use_isolated_profile: bool
    allow_main_profile: bool
    profile_path: Path
    downloads_path: Path

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["profile_path"] = str(self.profile_path)
        data["downloads_path"] = str(self.downloads_path)
        return data


def friday_profile_path(base: Path | None = None) -> Path:
    root = base or workspace_dir()
    path = root / "browser" / "profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def friday_downloads_path(base: Path | None = None) -> Path:
    root = base or workspace_dir()
    path = root / "browser" / "downloads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_profile_policy(config: dict[str, Any] | None = None, *, base: Path | None = None) -> BrowserProfilePolicy:
    permissions = config or load_permissions_config()
    browser = permissions.get("browser", {})
    return BrowserProfilePolicy(
        use_isolated_profile=bool(browser.get("use_isolated_profile", True)),
        allow_main_profile=bool(browser.get("allow_main_profile", False)),
        profile_path=friday_profile_path(base),
        downloads_path=friday_downloads_path(base),
    )


def ensure_isolated_profile(policy: BrowserProfilePolicy | None = None) -> Path:
    selected = policy or load_profile_policy()
    if not selected.use_isolated_profile and not selected.allow_main_profile:
        raise RuntimeError("Browser profile config is invalid: main profile is disabled and isolated profile is off.")
    selected.profile_path.mkdir(parents=True, exist_ok=True)
    return selected.profile_path
