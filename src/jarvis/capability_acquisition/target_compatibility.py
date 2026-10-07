"""Deterministic candidate-to-target compatibility for capability acquisition."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from jarvis.capability_acquisition.models import (
    AcquisitionCandidateV1,
    AcquisitionSourceKind,
    AcquisitionStrategy,
    OwnerCapabilityGoalV1,
)
from jarvis.engineering_substrate.canonical import canonical_digest


class TargetCompatibilityVerdict(StrEnum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNPROVEN = "unproven"
    NOT_REQUIRED = "not_required"


_TARGET_DIMENSIONS = frozenset(
    {
        "entity_type",
        "entity_name",
        "vendor",
        "platform",
        "protocol",
        "model",
    }
)


def _hint(value: object) -> tuple[str, str] | None:
    normalized = " ".join(str(value or "").split()).strip().casefold()
    if ":" not in normalized:
        return None
    key, raw_value = normalized.split(":", 1)
    key = key.strip().replace("-", "_")
    target_value = raw_value.strip()
    if key not in _TARGET_DIMENSIONS or not target_value:
        return None
    return key, target_value


def _hint_map(values: tuple[str, ...]) -> dict[str, frozenset[str]]:
    output: dict[str, set[str]] = {}
    for value in values:
        parsed = _hint(value)
        if parsed is None:
            continue
        key, target_value = parsed
        output.setdefault(key, set()).add(target_value)
    return {key: frozenset(items) for key, items in output.items()}


@dataclass(frozen=True, slots=True)
class CandidateTargetCompatibilityV1:
    verdict: TargetCompatibilityVerdict
    required_hints: tuple[str, ...]
    declared_hints: tuple[str, ...]
    matched_dimensions: tuple[str, ...]
    missing_dimensions: tuple[str, ...]
    conflicting_dimensions: tuple[str, ...]
    reason_codes: tuple[str, ...]
    digest: str

    @property
    def compatible(self) -> bool:
        return self.verdict in {
            TargetCompatibilityVerdict.COMPATIBLE,
            TargetCompatibilityVerdict.NOT_REQUIRED,
        }

    def canonical_payload(self) -> dict[str, object]:
        return {
            "verdict": self.verdict.value,
            "required_hints": list(self.required_hints),
            "declared_hints": list(self.declared_hints),
            "matched_dimensions": list(self.matched_dimensions),
            "missing_dimensions": list(self.missing_dimensions),
            "conflicting_dimensions": list(self.conflicting_dimensions),
            "reason_codes": list(self.reason_codes),
        }

    def __post_init__(self) -> None:
        if canonical_digest(self.canonical_payload()) != self.digest:
            raise ValueError("candidate target compatibility digest mismatch")


def evaluate_candidate_target_compatibility(
    goal: OwnerCapabilityGoalV1,
    candidate: AcquisitionCandidateV1,
    *,
    canonical_target_hints: tuple[str, ...] = (),
) -> CandidateTargetCompatibilityV1:
    """Compare trusted candidate target declarations with canonical goal target facts.

    device_scopes is the existing governed candidate field used for concrete target
    declarations. Opaque device scopes remain valid for execution policy but do not count
    as compatibility proof unless they use a recognized dimension:value contract.
    """

    if not isinstance(goal, OwnerCapabilityGoalV1):
        raise TypeError("goal must be OwnerCapabilityGoalV1")
    if not isinstance(candidate, AcquisitionCandidateV1):
        raise TypeError("candidate must be AcquisitionCandidateV1")

    required_values = tuple(
        sorted(
            {
                " ".join(str(item).split()).strip().casefold()
                for item in (*goal.target_hints, *canonical_target_hints)
                if _hint(item) is not None
            }
        )
    )
    required = _hint_map(required_values)

    # A custom build is generated from this exact immutable owner goal. Existing
    # capabilities have already passed descriptor target filtering before evaluation.
    intrinsically_bound = (
        candidate.strategy is AcquisitionStrategy.BUILD_CUSTOM
        and candidate.source_kind is AcquisitionSourceKind.CUSTOM_BUILD
        and candidate.source_identity == f"owner-goal:{goal.goal_id}"
    ) or candidate.source_kind is AcquisitionSourceKind.EXISTING_CAPABILITY

    declared_values = tuple(
        sorted(
            {
                " ".join(str(item).split()).strip().casefold()
                for item in candidate.device_scopes
                if _hint(item) is not None
            }
        )
    )
    declared = _hint_map(declared_values)

    matched: list[str] = []
    missing: list[str] = []
    conflicting: list[str] = []

    if not required:
        verdict = TargetCompatibilityVerdict.NOT_REQUIRED
        reasons = ("target_compatibility_not_required",)
    elif intrinsically_bound:
        verdict = TargetCompatibilityVerdict.COMPATIBLE
        reasons = ("target_compatibility_intrinsic",)
        matched = sorted(required)
    else:
        for dimension, expected in required.items():
            actual = declared.get(dimension)
            if actual is None:
                missing.append(dimension)
                continue
            if expected.isdisjoint(actual):
                conflicting.append(dimension)
            else:
                matched.append(dimension)

        if conflicting:
            verdict = TargetCompatibilityVerdict.INCOMPATIBLE
            reasons = (
                "target_incompatible",
                *(f"target_conflict_{dimension}" for dimension in sorted(conflicting)),
            )
        elif missing:
            verdict = TargetCompatibilityVerdict.UNPROVEN
            reasons = (
                "target_compatibility_unproven",
                *(f"target_unproven_{dimension}" for dimension in sorted(missing)),
            )
        else:
            verdict = TargetCompatibilityVerdict.COMPATIBLE
            reasons = ("target_compatible",)

    payload = {
        "verdict": verdict.value,
        "required_hints": list(required_values),
        "declared_hints": list(declared_values),
        "matched_dimensions": sorted(matched),
        "missing_dimensions": sorted(missing),
        "conflicting_dimensions": sorted(conflicting),
        "reason_codes": list(reasons),
    }
    return CandidateTargetCompatibilityV1(
        verdict=verdict,
        required_hints=required_values,
        declared_hints=declared_values,
        matched_dimensions=tuple(payload["matched_dimensions"]),
        missing_dimensions=tuple(payload["missing_dimensions"]),
        conflicting_dimensions=tuple(payload["conflicting_dimensions"]),
        reason_codes=tuple(reasons),
        digest=canonical_digest(payload),
    )
