from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from jarvis.engineering_substrate import (
    ArtifactStore,
    AttestationStatus,
    DependencyArtifact,
    DependencyResolution,
    DistributionKind,
    VerificationStatus,
    canonical_digest,
)
from jarvis.engineering_substrate.provenance import (
    ArtifactProvenanceResult,
    IntegrityProvenanceResponse,
    ProvenanceService,
    ProvenanceVerificationError,
    PyPIAttestationVerifier,
    VerifiedAttestationSet,
)


def _artifact_evidence(tmp_path: Path):
    store = ArtifactStore(tmp_path / "store")
    wheel = tmp_path / "demo_package-1.2.3-py3-none-any.whl"
    wheel.write_bytes(b"verified-wheel")
    admitted = store.admit_file(wheel)
    artifact = DependencyArtifact(
        artifact_id=admitted.artifact_sha256,
        package_name="demo-package",
        package_version="1.2.3",
        filename=wheel.name,
        distribution_kind=DistributionKind.WHEEL,
        size_bytes=admitted.size_bytes,
        sha256=admitted.artifact_sha256,
        source_id="pypi.public.v1",
    )
    resolution = DependencyResolution(
        resolution_id="resolution-1",
        requirement_id="requirement-1",
        resolver_id="uv",
        resolver_version="0.12.19",
        resolver_digest="b" * 64,
        resolved_packages=("demo-package==1.2.3",),
        artifact_ids=(artifact.artifact_id,),
        dependency_graph_digest="c" * 64,
        lock_format="pylock.toml",
        lock_version="1.0",
        lock_digest="d" * 64,
    )
    return store, artifact, resolution


class FakeIntegrityClient:
    def __init__(self, payload: bytes | None) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str, str]] = []

    def get_provenance(self, *, project: str, version: str, filename: str):
        self.calls.append((project, version, filename))
        return IntegrityProvenanceResponse(
            request_url=(
                "https://pypi.org/integrity/"
                f"{project}/{version}/{filename}/provenance"
            ),
            payload=self.payload,
        )


class AcceptingVerifier:
    def verify(self, *, artifact_path: Path, provenance_payload: bytes):
        assert artifact_path.is_file()
        assert provenance_payload == b'{"provenance":"fixture"}'
        return VerifiedAttestationSet(
            publisher_identities=(
                '{"kind":"GitHub","repository":"example/demo","workflow":"release.yml"}',
            ),
            predicate_types=(
                "https://docs.pypi.org/attestations/publish/v1",
                "https://slsa.dev/provenance/v1",
            ),
            provenance_digest="e" * 64,
        )


class RejectingVerifier:
    def verify(self, *, artifact_path: Path, provenance_payload: bytes):
        del artifact_path, provenance_payload
        raise ProvenanceVerificationError("forged fixture rejected")


def test_missing_attestation_is_explicit_not_available_not_verified_attestation(
    tmp_path: Path,
) -> None:
    store, artifact, resolution = _artifact_evidence(tmp_path)
    client = FakeIntegrityClient(None)
    result = ProvenanceService(
        artifact_store=store,
        integrity_client=client,
        attestation_verifier=AcceptingVerifier(),
    ).verify_pypi_artifact(
        artifact,
        resolution=resolution,
        provenance_id="prov-1",
    )

    assert isinstance(result, ArtifactProvenanceResult)
    assert result.provenance.attestation_status is AttestationStatus.NOT_AVAILABLE
    assert result.provenance.verification_status is VerificationStatus.VERIFIED
    assert result.provenance.attestation_refs == ()
    assert result.integrity_reference is not None
    assert client.calls == [
        ("demo-package", "1.2.3", "demo_package-1.2.3-py3-none-any.whl")
    ]


def test_verified_attestation_records_publisher_and_slsa_reference(
    tmp_path: Path,
) -> None:
    store, artifact, resolution = _artifact_evidence(tmp_path)
    service = ProvenanceService(
        artifact_store=store,
        integrity_client=FakeIntegrityClient(b'{"provenance":"fixture"}'),
        attestation_verifier=AcceptingVerifier(),
    )

    first = service.verify_pypi_artifact(
        artifact,
        resolution=resolution,
        provenance_id="prov-1",
    )
    second = service.verify_pypi_artifact(
        artifact,
        resolution=resolution,
        provenance_id="prov-1",
    )

    assert first.provenance.attestation_status is AttestationStatus.VERIFIED
    assert first.provenance.verification_status is VerificationStatus.VERIFIED
    assert "example/demo" in (first.provenance.publisher_identity or "")
    assert first.provenance.slsa_refs == ("https://slsa.dev/provenance/v1",)
    assert canonical_digest(first.provenance) == canonical_digest(second.provenance)


def test_invalid_attestation_produces_explicit_rejected_evidence(
    tmp_path: Path,
) -> None:
    store, artifact, resolution = _artifact_evidence(tmp_path)
    service = ProvenanceService(
        artifact_store=store,
        integrity_client=FakeIntegrityClient(b'{"provenance":"forged"}'),
        attestation_verifier=RejectingVerifier(),
    )

    with pytest.raises(ProvenanceVerificationError) as caught:
        service.verify_pypi_artifact(
            artifact,
            resolution=resolution,
            provenance_id="prov-rejected",
        )

    rejected = caught.value.rejected_provenance
    assert rejected is not None
    assert rejected.attestation_status is AttestationStatus.REJECTED
    assert rejected.verification_status is VerificationStatus.REJECTED
    assert rejected.artifact_sha256 == artifact.sha256


def test_provenance_rejects_artifact_not_bound_to_resolution(tmp_path: Path) -> None:
    store, artifact, resolution = _artifact_evidence(tmp_path)
    unrelated = DependencyResolution(
        resolution_id="resolution-other",
        requirement_id="requirement-1",
        resolver_id="uv",
        resolver_version="0.12.19",
        resolver_digest="b" * 64,
        resolved_packages=("demo-package==1.2.3",),
        artifact_ids=("f" * 64,),
        dependency_graph_digest="c" * 64,
        lock_format="pylock.toml",
        lock_version="1.0",
        lock_digest="d" * 64,
    )

    with pytest.raises(ProvenanceVerificationError, match="not bound"):
        ProvenanceService(
            artifact_store=store,
            integrity_client=FakeIntegrityClient(None),
        ).verify_pypi_artifact(
            artifact,
            resolution=unrelated,
            provenance_id="prov-1",
        )


def test_real_pypi_attestation_parser_rejects_forged_cryptographic_material(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "demo_package-1.2.3-py3-none-any.whl"
    wheel.write_bytes(b"not-a-real-wheel-but-valid-distribution-name")
    forged = {
        "version": 1,
        "attestation_bundles": [
            {
                "publisher": {
                    "kind": "GitHub",
                    "repository": "example/demo",
                    "workflow": "release.yml",
                },
                "attestations": [
                    {
                        "version": 1,
                        "verification_material": {
                            "certificate": base64.b64encode(b"not-a-certificate").decode(),
                            "transparency_entries": [{}],
                        },
                        "envelope": {
                            "statement": base64.b64encode(b"{}").decode(),
                            "signature": base64.b64encode(b"forged").decode(),
                        },
                    }
                ],
            }
        ],
    }

    with pytest.raises(ProvenanceVerificationError, match="cryptographic"):
        PyPIAttestationVerifier().verify(
            artifact_path=wheel,
            provenance_payload=json.dumps(forged).encode(),
        )


def test_content_hash_remains_mandatory_even_when_attestation_client_is_present(
    tmp_path: Path,
) -> None:
    store, artifact, resolution = _artifact_evidence(tmp_path)
    object_path = store.objects_root / artifact.sha256
    object_path.write_bytes(b"tampered-after-admission")

    with pytest.raises(Exception, match="verify-on-read"):
        ProvenanceService(
            artifact_store=store,
            integrity_client=FakeIntegrityClient(b'{"provenance":"fixture"}'),
            attestation_verifier=AcceptingVerifier(),
        ).verify_pypi_artifact(
            artifact,
            resolution=resolution,
            provenance_id="prov-1",
        )
