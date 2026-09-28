from __future__ import annotations

from dataclasses import dataclass

import pytest

from jarvis.capabilities.models import (
    CapabilityCatalog,
    CapabilityDescriptor,
    CapabilityKind,
)
from jarvis.capability_acquisition import (
    AcquisitionCandidateV1,
    AcquisitionContextV1,
    AcquisitionResolutionError,
    AcquisitionSourceKind,
    AcquisitionStrategy,
    AcquisitionTrustClass,
    CapabilityAcquisitionResolver,
    CapabilitySourceRegistry,
    ExistingCapabilitySourceAdapter,
    OwnerCapabilityGoalV1,
)
from jarvis.capability_registry.compatibility import CompatibilityVerdict
from jarvis.capability_registry.models import (
    DesiredActivationState,
    PackageDisposition,
)
from jarvis.capability_registry.projection import (
    CapabilityEffectiveSnapshot,
    CapabilityInventoryEntry,
    CapabilityManagementMode,
    EffectiveCapabilityState,
)
from jarvis.self_model.health import HealthState


def _goal(*operations: str) -> OwnerCapabilityGoalV1:
    return OwnerCapabilityGoalV1.create(
        request="Get TV control capability",
        requested_capability="TV control",
        required_operations=operations or ("power", "volume"),
        source_session_id="session-1",
        source_turn_id="turn-1",
        now_epoch=100.0,
    )


def _descriptor(*, enabled: bool = True) -> CapabilityDescriptor:
    return CapabilityDescriptor.create(
        capability_id="tv.control",
        source_id="local",
        kind=CapabilityKind.NATIVE_API,
        name="TV control",
        description="Control the living-room television.",
        operations=("power", "volume"),
        execution_enabled=enabled,
    )


def _core_context(*, enabled: bool = True) -> AcquisitionContextV1:
    descriptor = _descriptor(enabled=enabled)
    catalog = CapabilityCatalog(sources=(), capabilities=(descriptor,))
    inventory = (
        CapabilityInventoryEntry(
            capability_id=descriptor.capability_id,
            capability_key=descriptor.key,
            management_mode=CapabilityManagementMode.CORE_PINNED,
        ),
    )
    return AcquisitionContextV1(catalog=catalog, inventory=inventory)


def _managed_context(
    *,
    effective_enabled: bool = False,
    desired_state: DesiredActivationState = DesiredActivationState.DISABLED,
    compatibility: CompatibilityVerdict = CompatibilityVerdict.READY,
    disposition: PackageDisposition = PackageDisposition.AVAILABLE,
    fenced: bool = False,
    generation: int = 3,
    applied_generation: int = 3,
) -> AcquisitionContextV1:
    descriptor = _descriptor(enabled=effective_enabled)
    catalog = CapabilityCatalog(sources=(), capabilities=(descriptor,))
    inventory = (
        CapabilityInventoryEntry(
            capability_id=descriptor.capability_id,
            capability_key=descriptor.key,
            management_mode=CapabilityManagementMode.PACKAGE_MANAGED,
        ),
    )
    state = EffectiveCapabilityState(
        capability_id=descriptor.capability_id,
        capability_key=descriptor.key,
        component_id="capability.package:tv.control",
        management_mode=CapabilityManagementMode.PACKAGE_MANAGED,
        registry_generation=generation,
        applied_generation=applied_generation,
        desired_state=desired_state,
        selected_package_id="tv.control.package",
        selected_package_version="1.2.0",
        selected_package_digest="a" * 64,
        package_disposition=disposition,
        compatibility_verdict=compatibility,
        compatibility_digest="b" * 64,
        health_state=HealthState.DISABLED,
        transition_fenced=fenced,
        effective_enabled=effective_enabled,
        reason_codes=("desired_disabled",) if not effective_enabled else ("ready",),
    )
    snapshot = CapabilityEffectiveSnapshot(
        release_sha="c" * 40,
        states=(state,),
        reconciled_at_epoch=100.0,
        trigger="test",
    )
    return AcquisitionContextV1(
        catalog=catalog,
        inventory=inventory,
        effective_snapshot=snapshot,
    )


def _resolver(*adapters) -> CapabilityAcquisitionResolver:
    return CapabilityAcquisitionResolver(
        CapabilitySourceRegistry(
            tuple(adapters) or (ExistingCapabilitySourceAdapter(),)
        )
    )


def test_context_requires_inventory_to_exactly_cover_catalog() -> None:
    descriptor = _descriptor()
    with pytest.raises(ValueError, match="exactly cover"):
        AcquisitionContextV1(
            catalog=CapabilityCatalog(sources=(), capabilities=(descriptor,)),
            inventory=(),
        )


def test_existing_core_capability_is_reused_without_build() -> None:
    result = _resolver().resolve(_goal("power", "volume"), _core_context())

    assert len(result.candidates) == 1
    assert result.selected_candidate is not None
    assert result.selected_candidate.strategy is AcquisitionStrategy.REUSE
    assert (
        result.selected_candidate.trust_class is AcquisitionTrustClass.ACCEPTED_RELEASE
    )
    evaluation = result.evaluation(result.selected_candidate.candidate_id)
    assert evaluation.disposition.value == "selectable"
    assert "existing_core_ready" in evaluation.reason_codes


def test_disabled_core_capability_is_detected_but_not_selected() -> None:
    result = _resolver().resolve(_goal("power"), _core_context(enabled=False))

    assert len(result.candidates) == 1
    assert result.selected_candidate is None
    evaluation = result.evaluations[0]
    assert evaluation.disposition.value == "blocked"
    assert "existing_core_execution_disabled" in evaluation.reason_codes


def test_compatible_disabled_package_routes_to_lifecycle_reuse() -> None:
    result = _resolver().resolve(_goal("power", "volume"), _managed_context())

    assert result.selected_candidate is not None
    candidate = result.selected_candidate
    assert candidate.strategy is AcquisitionStrategy.REUSE
    assert candidate.source_version == "1.2.0"
    assert candidate.source_digest == "a" * 64
    evaluation = result.evaluation(candidate.candidate_id)
    assert evaluation.disposition.value == "selectable"
    assert "existing_package_lifecycle_reuse" in evaluation.reason_codes


@pytest.mark.parametrize(
    ("context", "reason"),
    [
        (
            _managed_context(compatibility=CompatibilityVerdict.BLOCKED),
            "package_compatibility_blocked",
        ),
        (
            _managed_context(disposition=PackageDisposition.QUARANTINED),
            "package_not_available",
        ),
        (
            _managed_context(fenced=True),
            "package_transition_fenced",
        ),
        (
            _managed_context(generation=4, applied_generation=3),
            "package_generation_stale",
        ),
    ],
)
def test_unsafe_package_state_cannot_be_selected(
    context: AcquisitionContextV1,
    reason: str,
) -> None:
    result = _resolver().resolve(_goal("power"), context)

    assert result.selected_candidate is None
    assert reason in result.evaluations[0].reason_codes


def test_existing_source_skips_capability_that_does_not_cover_owner_operations() -> (
    None
):
    result = _resolver().resolve(
        _goal("power", "input.change"),
        _core_context(),
    )

    assert result.candidates == ()
    assert result.evaluations == ()
    assert result.selected_candidate is None


def test_duplicate_source_registration_fails_closed() -> None:
    sources = CapabilitySourceRegistry((ExistingCapabilitySourceAdapter(),))
    with pytest.raises(ValueError, match="duplicate"):
        sources.register(ExistingCapabilitySourceAdapter())


@dataclass
class DuplicateAdapter:
    source_kind: AcquisitionSourceKind
    candidate: AcquisitionCandidateV1

    def discover(self, goal, context):
        return (self.candidate,)


def test_exact_duplicate_candidates_are_deduplicated() -> None:
    context = _core_context()
    original = ExistingCapabilitySourceAdapter().discover(_goal("power"), context)[0]
    first = DuplicateAdapter(AcquisitionSourceKind.EXISTING_CAPABILITY, original)

    class OtherKindDuplicate:
        source_kind = AcquisitionSourceKind.MCP

        def discover(self, goal, context):
            return ()

    resolver = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry((first, OtherKindDuplicate()))
    )
    result = resolver.resolve(_goal("power"), context)

    assert len(result.candidates) == 1


def test_same_immutable_source_identity_with_conflicting_semantics_fails_closed() -> (
    None
):
    context = _core_context()
    candidate = ExistingCapabilitySourceAdapter().discover(_goal("power"), context)[0]
    conflicting = AcquisitionCandidateV1.create(
        source_kind=candidate.source_kind,
        source_identity=candidate.source_identity,
        source_version=candidate.source_version,
        source_digest=candidate.source_digest,
        trust_class=candidate.trust_class,
        supported_operations=("power", "volume", "mute"),
        strategy=candidate.strategy,
        evidence_refs=candidate.evidence_refs,
        verification_requirements=candidate.verification_requirements,
    )

    class ContradictoryAdapter:
        source_kind = AcquisitionSourceKind.EXISTING_CAPABILITY

        def discover(self, goal, context):
            return (candidate, conflicting)

    with pytest.raises(AcquisitionResolutionError, match="contradictory"):
        _resolver(ContradictoryAdapter()).resolve(_goal("power"), context)


def test_unverified_candidate_cannot_win_even_when_operation_matches() -> None:
    context = _core_context()
    unverified = AcquisitionCandidateV1.create(
        source_kind=AcquisitionSourceKind.MCP,
        source_identity="registry:unknown",
        source_digest=None,
        trust_class=AcquisitionTrustClass.UNVERIFIED_CANDIDATE,
        supported_operations=("power",),
        strategy=AcquisitionStrategy.WRAP,
        evidence_refs=("registry:unknown",),
        verification_requirements=("sandbox-contract-test",),
    )

    class UnverifiedAdapter:
        source_kind = AcquisitionSourceKind.MCP

        def discover(self, goal, context):
            return (unverified,)

    result = _resolver(UnverifiedAdapter()).resolve(_goal("power"), context)

    assert result.selected_candidate is None
    assert "trust_not_allowed" in result.evaluations[0].reason_codes


def test_reuse_beats_verified_wrap_deterministically() -> None:
    context = _core_context()
    wrap = AcquisitionCandidateV1.create(
        source_kind=AcquisitionSourceKind.MCP,
        source_identity="https://example.test/mcp",
        source_digest="d" * 64,
        trust_class=AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
        supported_operations=("power", "volume"),
        strategy=AcquisitionStrategy.WRAP,
        evidence_refs=("vendor:mcp",),
        verification_requirements=("contract-test",),
    )

    class WrapAdapter:
        source_kind = AcquisitionSourceKind.MCP

        def discover(self, goal, context):
            return (wrap,)

    resolver = _resolver(ExistingCapabilitySourceAdapter(), WrapAdapter())
    result = resolver.resolve(_goal("power", "volume"), context)

    assert result.selected_candidate is not None
    assert (
        result.selected_candidate.source_kind
        is AcquisitionSourceKind.EXISTING_CAPABILITY
    )
    assert result.selected_candidate.strategy is AcquisitionStrategy.REUSE


def test_target_specific_goal_does_not_reuse_unscoped_operation_match() -> None:
    descriptor = CapabilityDescriptor.create(
        capability_id="audio",
        source_id="system",
        kind=CapabilityKind.NATIVE_API,
        name="Windows master audio",
        description="Control the local Windows master audio endpoint.",
        operations=("mute_master_volume", "unmute_master_volume"),
        execution_enabled=True,
    )
    context = AcquisitionContextV1(
        catalog=CapabilityCatalog(sources=(), capabilities=(descriptor,)),
        inventory=(
            CapabilityInventoryEntry(
                capability_id=descriptor.capability_id,
                capability_key=descriptor.key,
                management_mode=CapabilityManagementMode.CORE_PINNED,
            ),
        ),
    )
    goal = OwnerCapabilityGoalV1.create(
        request="Acquire network mute control for my television",
        requested_capability="television network audio control",
        required_operations=("mute_master_volume", "unmute_master_volume"),
        target_hints=("Hisense TV", "local network"),
        source_session_id="session-target",
        source_turn_id="turn-target",
        now_epoch=100.0,
    )

    result = _resolver().resolve(goal, context)

    assert result.candidates == ()
    assert result.selected_candidate is None


def test_target_specific_goal_reuses_only_explicitly_scoped_capability() -> None:
    descriptor = CapabilityDescriptor.create(
        capability_id="tv.control",
        source_id="local",
        kind=CapabilityKind.NATIVE_API,
        name="Hisense TV control",
        description="Control the explicitly configured television over the local network.",
        operations=("mute", "unmute"),
        metadata={
            "acquisition_target_hints": ["Hisense TV", "local network"],
        },
        execution_enabled=True,
    )
    context = AcquisitionContextV1(
        catalog=CapabilityCatalog(sources=(), capabilities=(descriptor,)),
        inventory=(
            CapabilityInventoryEntry(
                capability_id=descriptor.capability_id,
                capability_key=descriptor.key,
                management_mode=CapabilityManagementMode.CORE_PINNED,
            ),
        ),
    )
    goal = OwnerCapabilityGoalV1.create(
        request="Acquire mute control for my Hisense TV over the local network",
        requested_capability="Hisense TV control",
        required_operations=("mute", "unmute"),
        target_hints=("Hisense TV", "local network"),
        source_session_id="session-target",
        source_turn_id="turn-target",
        now_epoch=100.0,
    )

    result = _resolver().resolve(goal, context)

    assert result.selected_candidate is not None
    assert result.selected_candidate.source_identity == descriptor.key
    assert result.selected_candidate.strategy is AcquisitionStrategy.REUSE
