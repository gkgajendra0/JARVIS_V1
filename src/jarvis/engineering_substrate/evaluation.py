"""Deterministic Phase-5 substrate replay evaluation.

The evaluator is intentionally offline. It reports exact factual outcomes,
mismatches and invariant violations. It does not calculate a trust score,
rank implementations, mutate policy, or authorize any action.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class SubstrateReplayError(ValueError):
    """A replay fixture is malformed or incomplete."""


class SubstrateOutcome(StrEnum):
    ADMITTED = "admitted"
    ADMITTED_ATTESTATION_UNAVAILABLE = "admitted_attestation_unavailable"
    POLICY_DENIED = "policy_denied"
    INTEGRITY_REJECTED = "integrity_rejected"
    RESOURCE_BLOCKED = "resource_blocked"
    NO_RESULT = "no_result"
    STALE_REJECTED = "stale_rejected"
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    RESUMED_SAME_LINEAGE = "resumed_same_lineage"


@dataclass(frozen=True, slots=True)
class SubstrateReplayCase:
    case_id: str
    category: str
    expected_outcome: SubstrateOutcome
    expected_reason_code: str
    observed_outcome: SubstrateOutcome
    observed_reason_code: str
    verifier_reference: str
    security_invariant_preserved: bool
    restart_boundary: bool = False
    lineage_before: str | None = None
    lineage_after: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "case_id",
            "category",
            "expected_reason_code",
            "observed_reason_code",
            "verifier_reference",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise SubstrateReplayError(f"{field_name} must not be empty")
            object.__setattr__(self, field_name, value.casefold())
        if not isinstance(self.expected_outcome, SubstrateOutcome):
            raise TypeError("expected_outcome must be a SubstrateOutcome")
        if not isinstance(self.observed_outcome, SubstrateOutcome):
            raise TypeError("observed_outcome must be a SubstrateOutcome")
        if not isinstance(self.security_invariant_preserved, bool):
            raise TypeError("security_invariant_preserved must be bool")
        if not isinstance(self.restart_boundary, bool):
            raise TypeError("restart_boundary must be bool")
        before = (
            None if self.lineage_before is None else str(self.lineage_before).strip()
        )
        after = None if self.lineage_after is None else str(self.lineage_after).strip()
        if self.restart_boundary and (not before or not after):
            raise SubstrateReplayError(
                "restart boundary requires lineage_before and lineage_after"
            )
        if not self.restart_boundary and (before is not None or after is not None):
            raise SubstrateReplayError(
                "lineage fields are only valid for restart-boundary cases"
            )
        object.__setattr__(self, "lineage_before", before)
        object.__setattr__(self, "lineage_after", after)

    @property
    def outcome_matches(self) -> bool:
        return (
            self.expected_outcome is self.observed_outcome
            and self.expected_reason_code == self.observed_reason_code
        )

    @property
    def restart_lineage_preserved(self) -> bool | None:
        if not self.restart_boundary:
            return None
        return self.lineage_before == self.lineage_after


@dataclass(frozen=True, slots=True)
class SubstrateEvaluationMetrics:
    cases: int
    matched_cases: int
    mismatched_cases: int
    security_invariant_violations: int
    restart_cases: int
    restart_lineage_preserved: int
    restart_lineage_mismatches: int
    outcome_counts: dict[str, int]
    mismatched_case_ids: tuple[str, ...]
    security_violation_case_ids: tuple[str, ...]
    restart_lineage_mismatch_case_ids: tuple[str, ...]

    @property
    def all_cases_match(self) -> bool:
        return self.cases > 0 and self.mismatched_cases == 0

    @property
    def security_invariants_clean(self) -> bool:
        return self.security_invariant_violations == 0

    @property
    def restart_lineage_clean(self) -> bool:
        return self.restart_lineage_mismatches == 0


@dataclass(frozen=True, slots=True)
class SubstrateEvaluationReport:
    fixture_id: str
    fixture_version: int
    fixture_digest: str
    source_revision: str
    cases: tuple[SubstrateReplayCase, ...]
    metrics: SubstrateEvaluationMetrics


def _required_text(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SubstrateReplayError(f"{field} must not be empty")
    return normalized


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value <= 0:
        raise SubstrateReplayError(f"{field} must be positive")
    return value


def _bool(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field} must be a bool")
    return value


def _optional_text(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field=field)


def _case_payload(case: SubstrateReplayCase) -> dict[str, object]:
    return {
        "case_id": case.case_id,
        "category": case.category,
        "expected_outcome": case.expected_outcome.value,
        "expected_reason_code": case.expected_reason_code,
        "observed_outcome": case.observed_outcome.value,
        "observed_reason_code": case.observed_reason_code,
        "verifier_reference": case.verifier_reference,
        "security_invariant_preserved": case.security_invariant_preserved,
        "restart_boundary": case.restart_boundary,
        "lineage_before": case.lineage_before,
        "lineage_after": case.lineage_after,
    }


def substrate_fixture_digest(
    *,
    fixture_id: str,
    fixture_version: int,
    source_revision: str,
    cases: tuple[SubstrateReplayCase, ...],
) -> str:
    payload = {
        "fixture_id": _required_text(fixture_id, field="fixture_id"),
        "fixture_version": _positive_int(fixture_version, field="fixture_version"),
        "source_revision": _required_text(source_revision, field="source_revision"),
        "cases": [
            _case_payload(case) for case in sorted(cases, key=lambda item: item.case_id)
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def evaluate_substrate_replay(
    *,
    fixture_id: str,
    fixture_version: int,
    source_revision: str,
    cases: tuple[SubstrateReplayCase, ...],
) -> SubstrateEvaluationReport:
    if not cases:
        raise SubstrateReplayError("substrate evaluation requires at least one case")
    case_ids = tuple(case.case_id for case in cases)
    if len(case_ids) != len(set(case_ids)):
        raise SubstrateReplayError("substrate evaluation case IDs must be unique")

    mismatched = tuple(case.case_id for case in cases if not case.outcome_matches)
    security_violations = tuple(
        case.case_id for case in cases if not case.security_invariant_preserved
    )
    restart_cases = tuple(case for case in cases if case.restart_boundary)
    restart_mismatches = tuple(
        case.case_id
        for case in restart_cases
        if case.restart_lineage_preserved is not True
    )
    counts = Counter(case.observed_outcome.value for case in cases)
    metrics = SubstrateEvaluationMetrics(
        cases=len(cases),
        matched_cases=len(cases) - len(mismatched),
        mismatched_cases=len(mismatched),
        security_invariant_violations=len(security_violations),
        restart_cases=len(restart_cases),
        restart_lineage_preserved=len(restart_cases) - len(restart_mismatches),
        restart_lineage_mismatches=len(restart_mismatches),
        outcome_counts=dict(sorted(counts.items())),
        mismatched_case_ids=mismatched,
        security_violation_case_ids=security_violations,
        restart_lineage_mismatch_case_ids=restart_mismatches,
    )
    return SubstrateEvaluationReport(
        fixture_id=_required_text(fixture_id, field="fixture_id").casefold(),
        fixture_version=_positive_int(fixture_version, field="fixture_version"),
        fixture_digest=substrate_fixture_digest(
            fixture_id=fixture_id,
            fixture_version=fixture_version,
            source_revision=source_revision,
            cases=cases,
        ),
        source_revision=_required_text(
            source_revision,
            field="source_revision",
        ),
        cases=cases,
        metrics=metrics,
    )


def load_substrate_replay_fixture(
    path: str | Path,
) -> tuple[str, int, str, tuple[SubstrateReplayCase, ...]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SubstrateReplayError("substrate fixture root must be an object")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise SubstrateReplayError("substrate fixture cases must be a list")

    cases: list[SubstrateReplayCase] = []
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise SubstrateReplayError("substrate replay case must be an object")
        cases.append(
            SubstrateReplayCase(
                case_id=_required_text(raw.get("case_id"), field="case_id"),
                category=_required_text(raw.get("category"), field="category"),
                expected_outcome=SubstrateOutcome(
                    _required_text(
                        raw.get("expected_outcome"),
                        field="expected_outcome",
                    )
                ),
                expected_reason_code=_required_text(
                    raw.get("expected_reason_code"),
                    field="expected_reason_code",
                ),
                observed_outcome=SubstrateOutcome(
                    _required_text(
                        raw.get("observed_outcome"),
                        field="observed_outcome",
                    )
                ),
                observed_reason_code=_required_text(
                    raw.get("observed_reason_code"),
                    field="observed_reason_code",
                ),
                verifier_reference=_required_text(
                    raw.get("verifier_reference"),
                    field="verifier_reference",
                ),
                security_invariant_preserved=_bool(
                    raw.get("security_invariant_preserved"),
                    field="security_invariant_preserved",
                ),
                restart_boundary=_bool(
                    raw.get("restart_boundary", False),
                    field="restart_boundary",
                ),
                lineage_before=_optional_text(
                    raw.get("lineage_before"),
                    field="lineage_before",
                ),
                lineage_after=_optional_text(
                    raw.get("lineage_after"),
                    field="lineage_after",
                ),
            )
        )

    return (
        _required_text(payload.get("fixture_id"), field="fixture_id"),
        _positive_int(payload.get("fixture_version"), field="fixture_version"),
        _required_text(payload.get("source_revision"), field="source_revision"),
        tuple(cases),
    )
