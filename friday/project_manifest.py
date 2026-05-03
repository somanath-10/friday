"""Project manifest helpers for FRIDAY.

The manifest is intentionally metadata-first: callers can understand the
assistant's surfaces and trust model without importing every tool module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MANIFEST_FILENAME = "friday.project.json"


@dataclass(frozen=True)
class ManifestValidation:
    ok: bool
    issues: list[str]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def manifest_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / MANIFEST_FILENAME


def load_project_manifest(root: Path | None = None) -> dict[str, Any]:
    path = manifest_path(root)
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{MANIFEST_FILENAME} must contain a JSON object.")
    return data


def validate_project_manifest(manifest: dict[str, Any] | None = None) -> ManifestValidation:
    data = manifest if manifest is not None else load_project_manifest()
    issues: list[str] = []

    for key in ("schemaVersion", "id", "name", "runtime", "capabilities", "securityModel"):
        if key not in data:
            issues.append(f"Missing required field: {key}")

    if "capabilities" in data:
        capabilities = data["capabilities"]
        if not isinstance(capabilities, list) or not capabilities:
            issues.append("capabilities must be a non-empty list.")
        else:
            seen: set[str] = set()
            for index, item in enumerate(capabilities):
                if not isinstance(item, dict):
                    issues.append(f"capabilities[{index}] must be an object.")
                    continue
                capability_id = str(item.get("id", "")).strip()
                if not capability_id:
                    issues.append(f"capabilities[{index}] is missing id.")
                elif capability_id in seen:
                    issues.append(f"Duplicate capability id: {capability_id}")
                seen.add(capability_id)
                roots = item.get("roots", [])
                if not isinstance(roots, list) or not roots:
                    issues.append(f"capabilities[{capability_id or index}] must declare roots.")

    docs = data.get("docs", {})
    if docs and isinstance(docs, dict):
        for label, relative_path in docs.items():
            if not isinstance(relative_path, str):
                issues.append(f"docs.{label} must be a string path.")
                continue
            if not (repo_root() / relative_path).exists():
                issues.append(f"docs.{label} points to a missing file: {relative_path}")

    return ManifestValidation(ok=not issues, issues=issues)


def project_capability_table(manifest: dict[str, Any] | None = None) -> list[dict[str, str]]:
    data = manifest if manifest is not None else load_project_manifest()
    rows: list[dict[str, str]] = []
    for item in data.get("capabilities", []):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "id": str(item.get("id", "")),
                "name": str(item.get("name", "")),
                "risk": str(item.get("risk", "")),
                "roots": ", ".join(str(root) for root in item.get("roots", [])),
            }
        )
    return rows


def _normalize_manifest_path(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def _tool_module_relative_path(module_name: str) -> str:
    prefix = "friday.tools."
    if not module_name.startswith(prefix):
        return ""
    module_stem = module_name[len(prefix) :].strip()
    if not module_stem or "." in module_stem:
        return ""
    return f"friday/tools/{module_stem}.py"


def _root_matches_tool_path(root: str, tool_path: str) -> bool:
    normalized_root = _normalize_manifest_path(root)
    normalized_tool_path = _normalize_manifest_path(tool_path)
    if not normalized_root or not normalized_tool_path:
        return False
    return normalized_root == normalized_tool_path or normalized_tool_path.startswith(
        f"{normalized_root}/"
    )


def infer_tool_module_metadata(
    module_name: str,
    manifest: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Infer capability metadata for a `friday.tools.*` module from the manifest."""
    data = manifest if manifest is not None else load_project_manifest()
    tool_path = _tool_module_relative_path(module_name)
    for item in data.get("capabilities", []):
        if not isinstance(item, dict):
            continue
        for root in item.get("roots", []):
            if _root_matches_tool_path(str(root), tool_path):
                return {
                    "capability": str(item.get("id", "extension")),
                    "capability_name": str(item.get("name", "Local Extension")),
                    "risk": str(item.get("risk", "medium")),
                    "root": _normalize_manifest_path(str(root)),
                }
    return {
        "capability": "extension",
        "capability_name": "Local Extension",
        "risk": "medium",
        "root": "",
    }


def architecture_snapshot() -> dict[str, Any]:
    manifest = load_project_manifest()
    validation = validate_project_manifest(manifest)
    return {
        "manifest": {
            "id": manifest.get("id"),
            "name": manifest.get("name"),
            "description": manifest.get("description"),
            "schemaVersion": manifest.get("schemaVersion"),
        },
        "runtime": manifest.get("runtime", {}),
        "controlPlane": manifest.get("controlPlane", {}),
        "extensionModel": manifest.get("extensionModel", {}),
        "securityModel": manifest.get("securityModel", {}),
        "capabilities": project_capability_table(manifest),
        "qualityGates": manifest.get("qualityGates", []),
        "validation": {"ok": validation.ok, "issues": validation.issues},
    }
