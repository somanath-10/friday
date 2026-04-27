"""Local integration manifests for FRIDAY input and automation channels."""

from .registry import (
    IntegrationManifest,
    integration_manifest_dir,
    list_integrations,
    resolve_input_source,
)

__all__ = [
    "IntegrationManifest",
    "integration_manifest_dir",
    "list_integrations",
    "resolve_input_source",
]
