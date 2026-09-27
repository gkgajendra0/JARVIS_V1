"""Static release-owned inventory for governed acquired capabilities.

Phase-9 DEVELOPMENT may add reviewed capability modules and register their
AcquiredCapabilityDefinition values here. Package descriptors never select or import
Python code; this source-owned inventory is promoted through the normal Phase-7 path.
"""

from __future__ import annotations

from jarvis.capability_registry.runtime_composition import (
    AcquiredCapabilityDefinition,
)


def build_acquired_capability_definitions(
    release_sha: str,
) -> tuple[AcquiredCapabilityDefinition, ...]:
    normalized = str(release_sha).strip().casefold()
    if len(normalized) != 40 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError("release_sha must be an exact lowercase Git SHA")

    # Intentionally empty until a governed Phase-9 candidate adds a source-owned
    # provider definition. Do not add dynamic imports, entry-point scans or package-
    # metadata-directed imports here.
    return ()
