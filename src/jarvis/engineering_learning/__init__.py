"""Phase-10 closed-loop engineering-learning facade with cycle-safe lazy exports."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "jarvis.engineering_learning.facets",
        (
            "ENGINEERING_COMPATIBILITY_FACET_TYPE",
            "ENGINEERING_COMPATIBILITY_V1_SCHEMA",
            "ENGINEERING_COMPATIBILITY_V1_SCHEMA_DIGEST",
            "ENGINEERING_COMPATIBILITY_V1_SCHEMA_ID",
            "ENGINEERING_COMPATIBILITY_V1_SCHEMA_VERSION",
            "ENGINEERING_OUTCOME_FACET_TYPE",
            "ENGINEERING_OUTCOME_V1_SCHEMA",
            "ENGINEERING_OUTCOME_V1_SCHEMA_DIGEST",
            "ENGINEERING_OUTCOME_V1_SCHEMA_ID",
            "ENGINEERING_OUTCOME_V1_SCHEMA_VERSION",
            "ENGINEERING_REGRESSION_FACET_TYPE",
            "ENGINEERING_REGRESSION_V1_SCHEMA",
            "ENGINEERING_REGRESSION_V1_SCHEMA_DIGEST",
            "ENGINEERING_REGRESSION_V1_SCHEMA_ID",
            "ENGINEERING_REGRESSION_V1_SCHEMA_VERSION",
            "EngineeringCompatibilityV1Handler",
            "EngineeringOutcomeV1Handler",
            "EngineeringRegressionV1Handler",
        ),
    ),
    (
        "jarvis.engineering_learning.models",
        (
            "ENGINEERING_OUTCOME_SCHEMA_VERSION",
            "EngineeringOutcomeAttribution",
            "EngineeringOutcomeResult",
            "EngineeringOutcomeSourceKind",
            "EngineeringOutcomeV1",
            "OutcomeApplicability",
        ),
    ),
)

_EXPORTS = {
    name: module_name
    for module_name, names in _EXPORT_GROUPS
    for name in names
}

__all__ = [
    "ENGINEERING_COMPATIBILITY_FACET_TYPE",
    "ENGINEERING_COMPATIBILITY_V1_SCHEMA",
    "ENGINEERING_COMPATIBILITY_V1_SCHEMA_DIGEST",
    "ENGINEERING_COMPATIBILITY_V1_SCHEMA_ID",
    "ENGINEERING_COMPATIBILITY_V1_SCHEMA_VERSION",
    "ENGINEERING_OUTCOME_FACET_TYPE",
    "ENGINEERING_OUTCOME_SCHEMA_VERSION",
    "ENGINEERING_OUTCOME_V1_SCHEMA",
    "ENGINEERING_OUTCOME_V1_SCHEMA_DIGEST",
    "ENGINEERING_OUTCOME_V1_SCHEMA_ID",
    "ENGINEERING_OUTCOME_V1_SCHEMA_VERSION",
    "ENGINEERING_REGRESSION_FACET_TYPE",
    "ENGINEERING_REGRESSION_V1_SCHEMA",
    "ENGINEERING_REGRESSION_V1_SCHEMA_DIGEST",
    "ENGINEERING_REGRESSION_V1_SCHEMA_ID",
    "ENGINEERING_REGRESSION_V1_SCHEMA_VERSION",
    "EngineeringCompatibilityV1Handler",
    "EngineeringOutcomeAttribution",
    "EngineeringOutcomeResult",
    "EngineeringOutcomeSourceKind",
    "EngineeringOutcomeV1",
    "EngineeringOutcomeV1Handler",
    "EngineeringRegressionV1Handler",
    "OutcomeApplicability",
]


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
