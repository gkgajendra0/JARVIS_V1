from __future__ import annotations

from jarvis.capabilities.models import CapabilityCatalog
from jarvis.capability_acquisition.models import (
    AcquisitionStrategy,
    AcquisitionTrustClass,
    OwnerCapabilityGoalV1,
)
from jarvis.capability_acquisition.resolver import CapabilityAcquisitionResolver
from jarvis.capability_acquisition.source import (
    AcquisitionContextV1,
    CapabilitySourceRegistry,
)
from jarvis.capability_acquisition.standard_sources import (
    CustomBuildCapabilitySourceAdapter,
    sdk_library_evidence,
)
from jarvis.capability_acquisition.workflow import acquisition_completion_guard
from jarvis.work.models import WorkStep


def _goal() -> OwnerCapabilityGoalV1:
    return OwnerCapabilityGoalV1.create(
        request="Acquire an external-device control capability",
        requested_capability="external device control",
        required_operations=("device.control",),
        source_session_id="session-sdk",
        source_turn_id="turn-sdk",
        now_epoch=100.0,
    )


def _context() -> AcquisitionContextV1:
    return AcquisitionContextV1(
        catalog=CapabilityCatalog(sources=(), capabilities=()),
        inventory=(),
    )


def test_verified_sdk_outranks_custom_build_fallback() -> None:
    goal = _goal()
    context = _context()
    verified = sdk_library_evidence(
        package_identity="example-device-sdk",
        package_version="1.2.3",
        package_digest="a" * 64,
        trust_class=AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE,
        supported_operations=("device.control",),
        evidence_refs=("pypi-source:https://pypi.org/simple",),
        provenance_refs=("pypi-integrity:test",),
        dependency_refs=("pypi:example-device-sdk==1.2.3#lock-sha256=" + "b" * 64,),
        network_scopes=("local-network",),
        device_scopes=("owner-selected-device",),
        discovery_scopes=("ssdp_upnp.v1",),
        external_acceptance_requirements=("physical-effect-observation",),
    ).to_candidate(strategy=AcquisitionStrategy.ADAPT_SDK)
    custom = CustomBuildCapabilitySourceAdapter().discover(goal, context)[0]
    resolver = CapabilityAcquisitionResolver(CapabilitySourceRegistry(()))

    result = resolver.resolve_candidates(goal, (custom, verified), context)

    assert result.selected_candidate_id == verified.candidate_id
    assert result.selected_candidate is not None
    assert result.selected_candidate.strategy is AcquisitionStrategy.ADAPT_SDK
    assert (
        result.selected_candidate.trust_class
        is AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE
    )


def test_verified_sdk_preserves_owner_review_constraints() -> None:
    candidate = sdk_library_evidence(
        package_identity="example-device-sdk",
        package_version="1.2.3",
        package_digest="a" * 64,
        trust_class=AcquisitionTrustClass.VERIFIED_SIGNED_EXTERNAL,
        supported_operations=("device.control",),
        evidence_refs=("pypi-source:https://pypi.org/simple",),
        provenance_refs=("pypi-integrity:test",),
        dependency_refs=("pypi:example-device-sdk==1.2.3",),
        secret_scopes=("device.pair",),
        network_scopes=("local-network",),
        device_scopes=("owner-selected-device",),
        discovery_scopes=("ssdp_upnp.v1",),
        external_acceptance_requirements=("physical-effect-observation",),
    ).to_candidate(strategy=AcquisitionStrategy.ADAPT_SDK)

    assert candidate.secret_scopes == ("device.pair",)
    assert candidate.network_scopes == ("local-network",)
    assert candidate.device_scopes == ("owner-selected-device",)
    assert candidate.discovery_scopes == ("ssdp_upnp.v1",)
    assert candidate.external_acceptance_requirements == (
        "physical-effect-observation",
    )


def _step(kind: str, observation: dict[str, object]) -> WorkStep:
    return (
        WorkStep(work_id="work-sdk", kind=kind, summary=kind)
        .start()
        .complete(observation)
    )


def test_sdk_verification_invalidates_older_finalize_evidence() -> None:
    steps = (
        _step("acq_inspect_goal", {"goal": {"goal_id": "goal"}}),
        _step("acq_resolve", {"resolved": True}),
        _step("acq_finalize", {"finalized": True}),
        _step(
            "acq_verify_pypi_sdk",
            {
                "verified": True,
                "candidate": {
                    "placeholder": "completion guard does not parse candidate payload"
                },
            },
        ),
    )

    allowed, reason = acquisition_completion_guard(steps)

    assert allowed is False
    assert reason is not None and "re-resolve" in reason
