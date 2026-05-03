import json

from friday.project_manifest import (
    architecture_snapshot,
    infer_tool_module_metadata,
    load_project_manifest,
    project_capability_table,
    validate_project_manifest,
)


def test_project_manifest_is_valid():
    manifest = load_project_manifest()
    validation = validate_project_manifest(manifest)

    assert validation.ok is True
    assert validation.issues == []
    assert manifest["id"] == "friday-local-assistant"


def test_project_manifest_capabilities_cover_core_surfaces():
    rows = project_capability_table()
    capability_ids = {row["id"] for row in rows}

    assert {"browser", "desktop", "filesystem", "shell", "memory", "workflow"}.issubset(
        capability_ids
    )


def test_architecture_snapshot_is_json_serializable():
    snapshot = architecture_snapshot()
    encoded = json.dumps(snapshot)

    assert "FRIDAY" in encoded
    assert snapshot["validation"]["ok"] is True


def test_tool_module_metadata_is_inferred_from_manifest_roots():
    browser = infer_tool_module_metadata("friday.tools.browser")
    unknown = infer_tool_module_metadata("friday.tools.not_declared")

    assert browser["capability"] == "browser"
    assert browser["risk"] == "medium"
    assert unknown["capability"] == "extension"
