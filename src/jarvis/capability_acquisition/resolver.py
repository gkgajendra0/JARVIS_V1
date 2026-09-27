"""Deterministic Phase-9 acquisition candidate evaluation and selection."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.capability_acquisition.models import (
    AcquisitionCandidateEvaluationV1,
    AcquisitionCandidateV1,
    AcquisitionDisposition,
    AcquisitionSourceKind,
    AcquisitionStrategy,
    AcquisitionTrustClass,
    OwnerCapabilityGoalV1,
)
from jarvis.capability_acquisition.source import (
    AcquisitionContextV1,
    CapabilitySourceRegistry,
)
from jarvis.capability_registry.compatibility import CompatibilityVerdict
from jarvis.capability_registry.models import PackageDisposition
from jarvis.capability_registry.projection import CapabilityManagementMode


class AcquisitionResolutionError(RuntimeError):
    """Candidate evidence is contradictory or cannot be resolved safely."""


_STRATEGY_RANK = {
    AcquisitionStrategy.REUSE: 0,
    AcquisitionStrategy.WRAP: 1,
    AcquisitionStrategy.GENERATE_CONTRACT_CLIENT: 2,
    AcquisitionStrategy.ADAPT_SDK: 3,
    AcquisitionStrategy.BUILD_CUSTOM: 4,
}

_TRUST_RANK = {
    AcquisitionTrustClass.ACCEPTED_RELEASE: 0,
    AcquisitionTrustClass.OWNER_CONFIGURED: 1,
    AcquisitionTrustClass.VERIFIED_SIGNED_EXTERNAL: 2,
    AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE: 3,
    AcquisitionTrustClass.UNVERIFIED_CANDIDATE: 99,
}

_SOURCE_RANK = {
    AcquisitionSourceKind.EXISTING_CAPABILITY: 0,
    AcquisitionSourceKind.OWNER_CONFIGURED_LOCAL: 1,
    AcquisitionSourceKind.MCP: 2,
    AcquisitionSourceKind.OPENAPI: 3,
    AcquisitionSourceKind.ASYNCAPI: 4,
    AcquisitionSourceKind.SDK_LIBRARY: 5,
    AcquisitionSourceKind.CUSTOM_BUILD: 6,
}


@dataclass(frozen=True, slots=True)
class AcquisitionResolutionResult:
    candidates: tuple[AcquisitionCandidateV1, ...]
    evaluations: tuple[AcquisitionCandidateEvaluationV1, ...]
    selected_candidate_id: str | None

    def __post_init__(self) -> None:
        candidate_ids = tuple(item.candidate_id for item in self.candidates)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("resolution candidates must be unique")
        evaluation_ids = tuple(item.candidate_id for item in self.evaluations)
        if len(evaluation_ids) != len(set(evaluation_ids)):
            raise ValueError("resolution evaluations must be unique by candidate")
        if set(candidate_ids) != set(evaluation_ids):
            raise ValueError("every candidate requires exactly one evaluation")
        if self.selected_candidate_id is not None:
            if self.selected_candidate_id not in set(candidate_ids):
                raise ValueError("selected candidate is absent from resolution")
            selected = self.evaluation(self.selected_candidate_id)
            if selected.disposition is not AcquisitionDisposition.SELECTABLE:
                raise ValueError("selected candidate must be selectable")

    def candidate(self, candidate_id: str) -> AcquisitionCandidateV1:
        normalized = str(candidate_id).strip()
        return next(item for item in self.candidates if item.candidate_id == normalized)

    def evaluation(
        self,
        candidate_id: str,
    ) -> AcquisitionCandidateEvaluationV1:
        normalized = str(candidate_id).strip()
        return next(
            item for item in self.evaluations if item.candidate_id == normalized
        )

    @property
    def selected_candidate(self) -> AcquisitionCandidateV1 | None:
        if self.selected_candidate_id is None:
            return None
        return self.candidate(self.selected_candidate_id)


class CapabilityAcquisitionResolver:
    """Discover, evaluate and choose candidates without creating execution Authority."""

    def __init__(self, sources: CapabilitySourceRegistry) -> None:
        if not isinstance(sources, CapabilitySourceRegistry):
            raise TypeError("sources must be CapabilitySourceRegistry")
        self.sources = sources

    @staticmethod
    def _deduplicate(
        candidates: tuple[AcquisitionCandidateV1, ...],
    ) -> tuple[AcquisitionCandidateV1, ...]:
        by_identity: dict[
            tuple[AcquisitionSourceKind, str, str | None, str | None],
            AcquisitionCandidateV1,
        ] = {}
        for candidate in candidates:
            key = (
                candidate.source_kind,
                candidate.source_identity,
                candidate.source_version,
                candidate.source_digest,
            )
            existing = by_identity.get(key)
            if existing is None:
                by_identity[key] = candidate
                continue
            if existing.digest != candidate.digest:
                raise AcquisitionResolutionError(
                    "one immutable source identity produced contradictory candidate evidence"
                )
        return tuple(
            sorted(
                by_identity.values(),
                key=lambda item: (
                    _STRATEGY_RANK[item.strategy],
                    _TRUST_RANK[item.trust_class],
                    _SOURCE_RANK[item.source_kind],
                    item.candidate_id,
                ),
            )
        )

    @staticmethod
    def _existing_requirements_compatible(
        candidate: AcquisitionCandidateV1,
        context: AcquisitionContextV1,
    ) -> tuple[bool, tuple[str, ...]]:
        descriptor = context.descriptor(candidate.source_identity)
        inventory = context.inventory_entry(candidate.source_identity)
        if descriptor is None or inventory is None:
            return False, ("existing_capability_missing",)

        if inventory.management_mode is CapabilityManagementMode.CORE_PINNED:
            return (
                (True, ("existing_core_ready",))
                if descriptor.execution_enabled
                else (False, ("existing_core_execution_disabled",))
            )

        snapshot = context.effective_snapshot
        state = (
            None
            if snapshot is None
            else snapshot.state_for_key(candidate.source_identity)
        )
        if state is None:
            return False, ("phase8_effective_state_missing",)
        reasons: list[str] = []
        compatible = True
        if state.selected_package_digest != candidate.source_digest:
            compatible = False
            reasons.append("selected_package_digest_mismatch")
        if state.package_disposition is not PackageDisposition.AVAILABLE:
            compatible = False
            reasons.append("package_not_available")
        if state.compatibility_verdict not in {
            CompatibilityVerdict.READY,
            CompatibilityVerdict.RESTART_REQUIRED,
        }:
            compatible = False
            reasons.append("package_compatibility_blocked")
        if state.transition_fenced:
            compatible = False
            reasons.append("package_transition_fenced")
        if state.applied_generation != state.registry_generation:
            compatible = False
            reasons.append("package_generation_stale")
        if compatible:
            reasons.append(
                "existing_package_effectively_enabled"
                if state.effective_enabled
                else "existing_package_lifecycle_reuse"
            )
        return compatible, tuple(sorted(reasons))

    def evaluate(
        self,
        goal: OwnerCapabilityGoalV1,
        candidate: AcquisitionCandidateV1,
        context: AcquisitionContextV1,
    ) -> AcquisitionCandidateEvaluationV1:
        evidence_complete = bool(candidate.evidence_refs) and (
            candidate.source_digest is not None
            or candidate.trust_class is AcquisitionTrustClass.UNVERIFIED_CANDIDATE
        )
        trust_allowed = (
            candidate.trust_class is not AcquisitionTrustClass.UNVERIFIED_CANDIDATE
        )
        requirements_compatible = True
        reason_codes = list(candidate.reason_codes)
        if candidate.source_kind is AcquisitionSourceKind.EXISTING_CAPABILITY:
            requirements_compatible, existing_reasons = (
                self._existing_requirements_compatible(candidate, context)
            )
            reason_codes.extend(existing_reasons)

        return AcquisitionCandidateEvaluationV1.create(
            candidate,
            requested_operations=goal.required_operations,
            evidence_complete=evidence_complete,
            trust_allowed=trust_allowed,
            requirements_compatible=requirements_compatible,
            reason_codes=tuple(reason_codes),
        )

    def resolve(
        self,
        goal: OwnerCapabilityGoalV1,
        context: AcquisitionContextV1,
    ) -> AcquisitionResolutionResult:
        if not isinstance(goal, OwnerCapabilityGoalV1):
            raise TypeError("goal must be OwnerCapabilityGoalV1")
        if not isinstance(context, AcquisitionContextV1):
            raise TypeError("context must be AcquisitionContextV1")

        discovered: list[AcquisitionCandidateV1] = []
        for adapter in self.sources.adapters():
            results = adapter.discover(goal, context)
            if any(not isinstance(item, AcquisitionCandidateV1) for item in results):
                raise AcquisitionResolutionError(
                    "source adapter returned an invalid candidate"
                )
            discovered.extend(results)

        candidates = self._deduplicate(tuple(discovered))
        evaluations = tuple(
            self.evaluate(goal, candidate, context) for candidate in candidates
        )
        selectable = [
            (candidate, evaluation)
            for candidate, evaluation in zip(candidates, evaluations, strict=True)
            if evaluation.disposition is AcquisitionDisposition.SELECTABLE
        ]
        selected = (
            None
            if not selectable
            else min(
                selectable,
                key=lambda pair: (
                    _STRATEGY_RANK[pair[0].strategy],
                    _TRUST_RANK[pair[0].trust_class],
                    _SOURCE_RANK[pair[0].source_kind],
                    pair[0].candidate_id,
                ),
            )[0].candidate_id
        )
        return AcquisitionResolutionResult(
            candidates=candidates,
            evaluations=evaluations,
            selected_candidate_id=selected,
        )
