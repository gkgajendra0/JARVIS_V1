"""Explicit runtime-lane and GICC-mode contracts.

Runtime lane is process identity, not a persisted machine preference.  Development
supervision injects it into the child process; direct voice execution therefore
fails safe to production.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import Enum

RUNTIME_LANE_ENV = "JARVIS_RUNTIME_LANE"
GICC_MODE_ENV = "JARVIS_GICC_MODE"


class RuntimeLane(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"


class GiccMode(str, Enum):
    OFF = "off"
    SHADOW = "shadow"
    APPLY = "apply"


def _environment_value(
    name: str,
    environment: Mapping[str, str] | None,
) -> str | None:
    source = os.environ if environment is None else environment
    value = source.get(name)
    if value is None:
        return None
    normalized = value.strip().casefold()
    return normalized or None


def configured_runtime_lane(
    environment: Mapping[str, str] | None = None,
) -> RuntimeLane:
    """Return explicit process lane, defaulting fail-closed to production."""

    value = _environment_value(RUNTIME_LANE_ENV, environment)
    if value is None:
        return RuntimeLane.PRODUCTION
    try:
        return RuntimeLane(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported {RUNTIME_LANE_ENV}: {value!r}") from exc


def configured_gicc_mode(
    runtime_lane: RuntimeLane,
    environment: Mapping[str, str] | None = None,
) -> GiccMode:
    """Resolve GICC mode without making it a persisted machine preference."""

    if not isinstance(runtime_lane, RuntimeLane):
        raise TypeError("runtime_lane must be RuntimeLane")
    value = _environment_value(GICC_MODE_ENV, environment)
    if value is None:
        return (
            GiccMode.SHADOW if runtime_lane is RuntimeLane.DEVELOPMENT else GiccMode.OFF
        )
    try:
        return GiccMode(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported {GICC_MODE_ENV}: {value!r}") from exc


def validate_gicc_runtime_policy(
    runtime_lane: RuntimeLane,
    gicc_mode: GiccMode,
) -> None:
    """Reject production APPLY until a separate owner-approved activation exists."""

    if not isinstance(runtime_lane, RuntimeLane):
        raise TypeError("runtime_lane must be RuntimeLane")
    if not isinstance(gicc_mode, GiccMode):
        raise TypeError("gicc_mode must be GiccMode")
    if runtime_lane is RuntimeLane.PRODUCTION and gicc_mode is GiccMode.APPLY:
        raise ValueError(
            "GICC APPLY is disabled in the production runtime lane until "
            "owner-approved production activation"
        )
