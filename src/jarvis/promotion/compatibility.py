"""Deterministic compatibility classification for ordinary Phase-7 promotion."""

from __future__ import annotations

from dataclasses import dataclass

from .models import CompatibilityEvidence, CompatibilityVerdict


@dataclass(frozen=True, slots=True)
class CompatibilityAssessment:
    evidence: CompatibilityEvidence
    reason_codes: tuple[str, ...]


_SCHEMA_PREFIXES = (
    "src/jarvis/incidents/migrations/",
    "src/jarvis/memory/migrations/",
)
_SCHEMA_EXACT = {
    "src/jarvis/work/store.py",
    "src/jarvis/incidents/migration_runner.py",
    "src/jarvis/memory/migration_runner.py",
}
_DBOS_EXACT = {
    "src/jarvis/work/dbos_backend.py",
}
_DEPENDENCY_PREFIXES = ("src/jarvis/engineering_substrate/dependency/",)
_DEPENDENCY_EXACT = {
    "pyproject.toml",
}


def assess_ordinary_compatibility(
    changed_paths: tuple[str, ...] | list[str],
) -> CompatibilityAssessment:
    paths = tuple(
        dict.fromkeys(str(item).replace("\\", "/").strip() for item in changed_paths)
    )
    if not paths or any(not item for item in paths):
        raise ValueError("compatibility assessment requires changed paths")

    schema = CompatibilityVerdict.SAFE
    dbos = CompatibilityVerdict.SAFE
    dependencies = CompatibilityVerdict.SAFE
    reasons: list[str] = []

    for path in paths:
        folded = path.casefold()
        if folded in _SCHEMA_EXACT or any(
            folded.startswith(prefix) for prefix in _SCHEMA_PREFIXES
        ):
            schema = CompatibilityVerdict.REVIEW_REQUIRED
            reasons.append("durable_schema_change")
        if folded in _DBOS_EXACT:
            dbos = CompatibilityVerdict.REVIEW_REQUIRED
            reasons.append("dbos_workflow_or_persistence_change")
        if folded in _DEPENDENCY_EXACT or any(
            folded.startswith(prefix) for prefix in _DEPENDENCY_PREFIXES
        ):
            dependencies = CompatibilityVerdict.REVIEW_REQUIRED
            reasons.append("runtime_dependency_change")

    return CompatibilityAssessment(
        evidence=CompatibilityEvidence(
            schema=schema,
            dbos=dbos,
            dependencies=dependencies,
        ),
        reason_codes=tuple(dict.fromkeys(reasons)),
    )
