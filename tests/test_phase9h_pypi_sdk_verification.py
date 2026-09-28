from __future__ import annotations

import asyncio
from types import SimpleNamespace

from jarvis.capability_acquisition.artifacts import (
    candidate_from_payload,
    candidate_payload,
)
from jarvis.capability_acquisition.models import (
    AcquisitionCandidateV1,
    AcquisitionSourceKind,
    AcquisitionStrategy,
    AcquisitionTrustClass,
    OwnerCapabilityGoalV1,
)
from jarvis.capability_acquisition import sdk_verification
from jarvis.capability_acquisition.sdk_verification import (
    AcquisitionVerifyPyPiSdkExecutor,
)
from jarvis.engineering_substrate.artifacts import ArtifactStore
from jarvis.engineering_substrate.contracts import (
    ArtifactProvenance,
    AttestationStatus,
    DependencyArtifact,
    DependencyResolution,
    DistributionKind,
    VerificationStatus,
)
from jarvis.work.models import WorkItem, WorkStep, WorkType


def _goal() -> OwnerCapabilityGoalV1:
    return OwnerCapabilityGoalV1.create(
        request="Acquire external device control",
        requested_capability="external device control",
        required_operations=("device.control",),
        source_session_id="session-pypi",
        source_turn_id="turn-pypi",
        now_epoch=100.0,
    )


def _unverified() -> AcquisitionCandidateV1:
    return AcquisitionCandidateV1.create(
        source_kind=AcquisitionSourceKind.SDK_LIBRARY,
        source_identity="example-device-sdk",
        source_version="1.2.3",
        source_digest=None,
        trust_class=AcquisitionTrustClass.UNVERIFIED_CANDIDATE,
        supported_operations=("device.control",),
        strategy=AcquisitionStrategy.ADAPT_SDK,
        evidence_refs=("research:https://example.invalid/sdk",),
        network_scopes=("local-network",),
        device_scopes=("owner-selected-device",),
        discovery_scopes=("ssdp_upnp.v1",),
        verification_requirements=("sdk-adapter-contract-test",),
        external_acceptance_requirements=("physical-effect-observation",),
        reason_codes=("research_discovered_unverified",),
    )


class FakeResolver:
    def __init__(self, work_id: str, candidate: AcquisitionCandidateV1) -> None:
        self._work_id = work_id
        self._candidate = candidate

    def context_for(self, work_id: str):
        assert work_id == self._work_id
        return SimpleNamespace(
            goal=_goal(),
            change_id="change-pypi",
            work_id=work_id,
        )

    def completed_steps(self, work_id: str):
        assert work_id == self._work_id
        step = WorkStep(
            work_id=work_id,
            kind="acq_record_candidate",
            summary="record SDK",
        ).start().complete({"candidate": candidate_payload(self._candidate)})
        return (step,)


class FakeBroker:
    def __init__(self, root) -> None:
        self.artifact_store = ArtifactStore(root / "artifacts")
        self.artifact = DependencyArtifact(
            artifact_id="d" * 64,
            package_name="example-device-sdk",
            package_version="1.2.3",
            filename="example_device_sdk-1.2.3-py3-none-any.whl",
            distribution_kind=DistributionKind.WHEEL,
            size_bytes=123,
            sha256="d" * 64,
            source_id="pypi.public.v1",
        )

    def resolve_python(self, requirement, *, workspace, environment):
        del workspace, environment
        resolution = DependencyResolution(
            resolution_id="resolution-example",
            requirement_id=requirement.requirement_id,
            resolver_id="uv.v1",
            resolver_version="0.12.19",
            resolver_digest="e" * 64,
            resolved_packages=("example-device-sdk==1.2.3",),
            artifact_ids=(self.artifact.artifact_id,),
            dependency_graph_digest="c" * 64,
            lock_format="pylock.toml",
            lock_version="1.0",
            lock_digest="b" * 64,
            platform_constraints=("python==3.11", "test-platform"),
            change_id=requirement.change_id,
            work_id=requirement.work_id,
        )
        return SimpleNamespace(
            requirement=requirement,
            resolution=resolution,
            lock_path=None,
        )

    def acquire_locked_wheels(self, resolved, *, staging_dir):
        del resolved, staging_dir
        return (self.artifact,)

    def admit_lock(self, resolved):
        return SimpleNamespace(artifact_sha256=resolved.resolution.lock_digest)


class FakeProvenanceService:
    def __init__(self, *, artifact_store) -> None:
        assert isinstance(artifact_store, ArtifactStore)

    def verify_pypi_artifact(self, artifact, *, resolution, provenance_id):
        provenance = ArtifactProvenance(
            provenance_id=provenance_id,
            artifact_id=artifact.artifact_id,
            source_id=artifact.source_id,
            resolver_id=resolution.resolver_id,
            resolver_version=resolution.resolver_version,
            resolver_digest=resolution.resolver_digest,
            artifact_sha256=artifact.sha256,
            attestation_status=AttestationStatus.NOT_AVAILABLE,
            verification_status=VerificationStatus.VERIFIED,
        )
        return SimpleNamespace(
            provenance=provenance,
            integrity_reference=(
                "https://pypi.org/integrity/example-device-sdk/1.2.3/"
                "example_device_sdk-1.2.3-py3-none-any.whl/provenance"
            ),
        )


def test_pypi_verifier_promotes_exact_sdk_without_executing_it(
    tmp_path,
    monkeypatch,
) -> None:
    work = WorkItem(
        request="research reusable SDK",
        work_type=WorkType.RESEARCH,
        source_session_id="session-pypi",
        source_turn_id="turn-pypi-work",
    )
    resolver = FakeResolver(work.work_id, _unverified())
    broker = FakeBroker(tmp_path)
    monkeypatch.setattr(
        sdk_verification,
        "dependency_work_root",
        lambda work_id: tmp_path / work_id,
    )
    monkeypatch.setattr(
        sdk_verification,
        "ProvenanceService",
        FakeProvenanceService,
    )
    executor = AcquisitionVerifyPyPiSdkExecutor(
        resolver,  # type: ignore[arg-type]
        broker_factory=lambda: broker,  # type: ignore[arg-type]
    )

    result = asyncio.run(
        executor.execute(
            work=work,
            parameters={"candidate_id": _unverified().candidate_id},
        )
    )
    candidate = candidate_from_payload(result["candidate"])

    assert result["execution_authorized"] is False
    assert candidate.trust_class is AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE
    assert candidate.strategy is AcquisitionStrategy.ADAPT_SDK
    assert candidate.dependency_refs == (
        "pypi:example-device-sdk==1.2.3#lock-sha256=" + "b" * 64,
    )
    assert candidate.network_scopes == ("local-network",)
    assert candidate.device_scopes == ("owner-selected-device",)
    assert candidate.discovery_scopes == ("ssdp_upnp.v1",)
    assert candidate.external_acceptance_requirements == (
        "physical-effect-observation",
    )
