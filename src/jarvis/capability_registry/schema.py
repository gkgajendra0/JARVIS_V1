"""JSON Schema projection for the Phase-8 capability-package contract."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from jarvis.capability_registry.contracts import CapabilityPackageV1
from jarvis.engineering_substrate.canonical import canonical_digest


def capability_package_v1_json_schema() -> dict[str, Any]:
    """Return a detached Draft-2020-12 closed schema generated from the contract."""

    return deepcopy(CapabilityPackageV1.model_json_schema())


def capability_package_v1_schema_digest() -> str:
    """Return the canonical digest of the generated interchange schema."""

    return canonical_digest(capability_package_v1_json_schema())
