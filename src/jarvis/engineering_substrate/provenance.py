"""Dependency provenance verification using PyPI PEP-740 attestations."""

from __future__ import annotations

import hashlib
import json
import pathlib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError
from pypi_attestations import (
    AttestationError,
    Distribution,
    Provenance,
)

from jarvis.engineering_substrate.artifacts import ArtifactStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.contracts import (
    ArtifactProvenance,
    AttestationStatus,
    DependencyArtifact,
    DependencyResolution,
    VerificationStatus,
)


class ProvenanceVerificationError(RuntimeError):
    """Provenance exists but cannot be accepted as verified evidence."""

    def __init__(
        self,
        message: str,
        *,
        rejected_provenance: ArtifactProvenance | None = None,
    ) -> None:
        super().__init__(message)
        self.rejected_provenance = rejected_provenance


class ProvenanceResourceUnavailable(RuntimeError):
    """The authoritative provenance service is unavailable for this attempt."""


@dataclass(frozen=True, slots=True)
class ProvenancePolicy:
    policy_id: str = "pypi.pep740.v1"
    require_sha256: bool = True
    verify_available_attestations: bool = True
    integrity_api_media_type: str = "application/vnd.pypi.integrity.v1+json"

    def __post_init__(self) -> None:
        policy_id = str(self.policy_id).strip().casefold()
        media_type = str(self.integrity_api_media_type).strip().casefold()
        if not policy_id:
            raise ValueError("policy_id must not be empty")
        if media_type != "application/vnd.pypi.integrity.v1+json":
            raise ValueError("unexpected PyPI Integrity API media type")
        if not self.require_sha256 or not self.verify_available_attestations:
            raise ValueError("Phase-5D provenance policy cannot weaken verification")
        object.__setattr__(self, "policy_id", policy_id)
        object.__setattr__(self, "integrity_api_media_type", media_type)

    @property
    def policy_digest(self) -> str:
        return canonical_digest(
            {
                "policy_id": self.policy_id,
                "require_sha256": self.require_sha256,
                "verify_available_attestations": self.verify_available_attestations,
                "integrity_api_media_type": self.integrity_api_media_type,
            }
        )


@dataclass(frozen=True, slots=True)
class IntegrityProvenanceResponse:
    request_url: str
    payload: bytes | None


class IntegrityClient(Protocol):
    def get_provenance(
        self,
        *,
        project: str,
        version: str,
        filename: str,
    ) -> IntegrityProvenanceResponse: ...


class PyPIIntegrityClient:
    """HTTPS-only client for PyPI's official Integrity API."""

    base_url = "https://pypi.org/integrity"

    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        timeout = float(timeout_seconds)
        if timeout <= 0 or timeout > 60:
            raise ValueError("timeout_seconds must be within (0, 60]")
        self._timeout_seconds = timeout

    @staticmethod
    def _component(value: str, *, field: str) -> str:
        text = str(value).strip()
        if not text or any(char in text for char in ("/", "\\", "\x00")):
            raise ProvenanceVerificationError(
                f"{field} cannot form a PyPI Integrity API path"
            )
        return urllib.parse.quote(text, safe="._-+")

    def get_provenance(
        self,
        *,
        project: str,
        version: str,
        filename: str,
    ) -> IntegrityProvenanceResponse:
        encoded_project = self._component(project, field="project")
        encoded_version = self._component(version, field="version")
        encoded_filename = self._component(filename, field="filename")
        url = (
            f"{self.base_url}/{encoded_project}/{encoded_version}/"
            f"{encoded_filename}/provenance"
        )
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.pypi.integrity.v1+json",
                "User-Agent": "JARVIS-ProvenanceVerifier/1",
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self._timeout_seconds,
            ) as response:
                final_url = response.geturl()
                parsed = urllib.parse.urlparse(final_url)
                if (
                    parsed.scheme.casefold() != "https"
                    or parsed.hostname is None
                    or parsed.hostname.casefold() != "pypi.org"
                ):
                    raise ProvenanceVerificationError(
                        "PyPI Integrity API redirected outside pypi.org HTTPS"
                    )
                payload = response.read(2 * 1024 * 1024 + 1)
                if len(payload) > 2 * 1024 * 1024:
                    raise ProvenanceVerificationError(
                        "PyPI provenance response exceeds size bound"
                    )
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return IntegrityProvenanceResponse(request_url=url, payload=None)
            raise ProvenanceResourceUnavailable(
                f"PyPI Integrity API returned HTTP {exc.code}"
            ) from exc
        except (OSError, urllib.error.URLError) as exc:
            raise ProvenanceResourceUnavailable(
                "PyPI Integrity API request failed"
            ) from exc
        return IntegrityProvenanceResponse(request_url=url, payload=payload)


@dataclass(frozen=True, slots=True)
class VerifiedAttestationSet:
    publisher_identities: tuple[str, ...]
    predicate_types: tuple[str, ...]
    provenance_digest: str


class AttestationVerifier(Protocol):
    def verify(
        self,
        *,
        artifact_path: pathlib.Path,
        distribution_filename: str,
        expected_sha256: str,
        provenance_payload: bytes,
    ) -> VerifiedAttestationSet: ...


class PyPIAttestationVerifier:
    """Use pypi-attestations/Sigstore; do not implement crypto inside JARVIS."""

    @staticmethod
    def _publisher_identity(bundle) -> str:
        publisher = bundle.publisher
        payload = publisher.model_dump(mode="json", exclude_none=True)
        return json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def verify(
        self,
        *,
        artifact_path: pathlib.Path,
        distribution_filename: str,
        expected_sha256: str,
        provenance_payload: bytes,
    ) -> VerifiedAttestationSet:
        filename = str(distribution_filename).strip()
        expected_digest = str(expected_sha256).strip().casefold()
        if not filename:
            raise ProvenanceVerificationError(
                "artifact distribution filename is missing"
            )
        if len(expected_digest) != 64 or any(
            char not in "0123456789abcdef" for char in expected_digest
        ):
            raise ProvenanceVerificationError("artifact expected SHA-256 is invalid")
        try:
            digest = hashlib.sha256()
            with artifact_path.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            observed_digest = digest.hexdigest()
        except OSError as exc:
            raise ProvenanceVerificationError(
                "artifact content could not be read for provenance verification"
            ) from exc
        if observed_digest != expected_digest:
            raise ProvenanceVerificationError(
                "artifact content digest changed before provenance verification"
            )
        try:
            distribution = Distribution(
                name=filename,
                digest=observed_digest,
            )
        except (ValidationError, ValueError) as exc:
            raise ProvenanceVerificationError(
                "artifact cannot form a valid Python distribution identity"
            ) from exc

        try:
            provenance = Provenance.model_validate_json(provenance_payload)
        except ValidationError as exc:
            raise ProvenanceVerificationError(
                "PyPI provenance payload violates the PEP-740 model"
            ) from exc

        if not provenance.attestation_bundles:
            raise ProvenanceVerificationError(
                "PyPI provenance contains no attestation bundles"
            )

        publisher_identities: list[str] = []
        predicate_types: list[str] = []
        attestation_count = 0
        for bundle in provenance.attestation_bundles:
            publisher_identity = self._publisher_identity(bundle)
            if not bundle.attestations:
                raise ProvenanceVerificationError(
                    "PyPI provenance bundle contains no attestations"
                )
            for attestation in bundle.attestations:
                attestation_count += 1
                try:
                    predicate_type, _ = attestation.verify(
                        bundle.publisher,
                        distribution,
                        offline=True,
                    )
                except AttestationError as exc:
                    raise ProvenanceVerificationError(
                        "PyPI attestation cryptographic/identity verification failed"
                    ) from exc
                publisher_identities.append(publisher_identity)
                predicate_types.append(str(predicate_type))

        if attestation_count == 0:
            raise ProvenanceVerificationError(
                "PyPI provenance did not provide a verifiable attestation"
            )
        return VerifiedAttestationSet(
            publisher_identities=tuple(sorted(dict.fromkeys(publisher_identities))),
            predicate_types=tuple(sorted(dict.fromkeys(predicate_types))),
            provenance_digest=canonical_digest(
                json.loads(provenance.model_dump_json(exclude_none=True))
            ),
        )


@dataclass(frozen=True, slots=True)
class ArtifactProvenanceResult:
    provenance: ArtifactProvenance
    policy_digest: str
    integrity_reference: str | None
    provenance_payload_digest: str | None


class ProvenanceService:
    """Bind lock/index SHA evidence to optional cryptographically verified PEP-740."""

    def __init__(
        self,
        *,
        artifact_store: ArtifactStore,
        integrity_client: IntegrityClient | None = None,
        attestation_verifier: AttestationVerifier | None = None,
        policy: ProvenancePolicy | None = None,
    ) -> None:
        if not isinstance(artifact_store, ArtifactStore):
            raise TypeError("artifact_store must be an ArtifactStore")
        self._artifact_store = artifact_store
        self._integrity_client = integrity_client or PyPIIntegrityClient()
        self._attestation_verifier = attestation_verifier or PyPIAttestationVerifier()
        self._policy = policy or ProvenancePolicy()

    def verify_pypi_artifact(
        self,
        artifact: DependencyArtifact,
        *,
        resolution: DependencyResolution,
        provenance_id: str,
    ) -> ArtifactProvenanceResult:
        if not isinstance(artifact, DependencyArtifact):
            raise TypeError("artifact must be a DependencyArtifact")
        if not isinstance(resolution, DependencyResolution):
            raise TypeError("resolution must be a DependencyResolution")
        if artifact.artifact_id not in resolution.artifact_ids:
            raise ProvenanceVerificationError(
                "artifact is not bound to the supplied dependency resolution"
            )
        if artifact.source_id != "pypi.public.v1":
            raise ProvenanceVerificationError(
                "PyPI provenance verification requires pypi.public.v1"
            )
        object_path = self._artifact_store.verify(artifact.sha256)
        if object_path.stat().st_size != artifact.size_bytes:
            raise ProvenanceVerificationError(
                "artifact size changed after content-addressed admission"
            )

        response = self._integrity_client.get_provenance(
            project=artifact.package_name,
            version=artifact.package_version,
            filename=artifact.filename,
        )
        if response.payload is None:
            provenance = ArtifactProvenance(
                provenance_id=provenance_id,
                artifact_id=artifact.artifact_id,
                source_id=artifact.source_id,
                resolver_id="uv",
                resolver_version=resolution.resolver_version,
                resolver_digest=resolution.resolver_digest,
                artifact_sha256=artifact.sha256,
                attestation_status=AttestationStatus.NOT_AVAILABLE,
                verification_status=VerificationStatus.VERIFIED,
                attestation_refs=(),
                publisher_identity=None,
                slsa_refs=(),
                sbom_refs=(),
            )
            return ArtifactProvenanceResult(
                provenance=provenance,
                policy_digest=self._policy.policy_digest,
                integrity_reference=response.request_url,
                provenance_payload_digest=None,
            )

        try:
            verified = self._attestation_verifier.verify(
                artifact_path=object_path,
                distribution_filename=artifact.filename,
                expected_sha256=artifact.sha256,
                provenance_payload=response.payload,
            )
        except ProvenanceVerificationError:
            rejected_payload_digest = hashlib.sha256(response.payload).hexdigest()
            rejected_reference = (
                f"{response.request_url}#sha256={rejected_payload_digest}"
            )
            rejected = ArtifactProvenance(
                provenance_id=provenance_id,
                artifact_id=artifact.artifact_id,
                source_id=artifact.source_id,
                resolver_id="uv",
                resolver_version=resolution.resolver_version,
                resolver_digest=resolution.resolver_digest,
                artifact_sha256=artifact.sha256,
                attestation_status=AttestationStatus.REJECTED,
                verification_status=VerificationStatus.REJECTED,
                attestation_refs=(rejected_reference,),
                publisher_identity=None,
                slsa_refs=(),
                sbom_refs=(),
            )
            raise ProvenanceVerificationError(
                "artifact provenance was rejected; "
                f"rejected evidence digest={canonical_digest(rejected)}",
                rejected_provenance=rejected,
            )

        verified_reference = (
            f"{response.request_url}#sha256={verified.provenance_digest}"
        )
        publisher_identity = ";".join(verified.publisher_identities)
        slsa_refs = tuple(
            predicate
            for predicate in verified.predicate_types
            if predicate == "https://slsa.dev/provenance/v1"
        )
        provenance = ArtifactProvenance(
            provenance_id=provenance_id,
            artifact_id=artifact.artifact_id,
            source_id=artifact.source_id,
            resolver_id="uv",
            resolver_version=resolution.resolver_version,
            resolver_digest=resolution.resolver_digest,
            artifact_sha256=artifact.sha256,
            attestation_status=AttestationStatus.VERIFIED,
            verification_status=VerificationStatus.VERIFIED,
            attestation_refs=(verified_reference,),
            publisher_identity=publisher_identity,
            slsa_refs=slsa_refs,
            sbom_refs=(),
        )
        return ArtifactProvenanceResult(
            provenance=provenance,
            policy_digest=self._policy.policy_digest,
            integrity_reference=verified_reference,
            provenance_payload_digest=verified.provenance_digest,
        )
