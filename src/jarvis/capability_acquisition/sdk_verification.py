"""Promote research-discovered Python SDKs only after Phase-5 PyPI verification."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from jarvis.capability_acquisition.artifacts import candidate_payload
from jarvis.capability_acquisition.models import (
    AcquisitionSourceKind,
    AcquisitionTrustClass,
)
from jarvis.capability_acquisition.standard_sources import sdk_library_evidence
from jarvis.capability_acquisition.workflow import (
    AcquisitionProtocolError,
    AcquisitionWorkContextResolver,
    recorded_unverified_candidates,
)
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.contracts import (
    AttestationStatus,
    DependencyEcosystem,
    DependencyRequirement,
)
from jarvis.engineering_substrate.dependency import DependencyBroker
from jarvis.engineering_substrate.dependency.runtime import (
    current_python_resolution_environment,
    dependency_work_root,
)
from jarvis.engineering_substrate.provenance import ProvenanceService
from jarvis.work.brain import BrainAction
from jarvis.work.models import WorkItem, WorkType


def _exact_version(value: object) -> str:
    version = str(value or "").strip()
    if version.startswith("=="):
        version = version[2:].strip()
    if (
        not version
        or len(version) > 80
        or any(token in version for token in ("<", ">", "~", "*", ",", ";", "@"))
        or any(character.isspace() for character in version)
    ):
        raise AcquisitionProtocolError(
            "PyPI SDK verification requires one exact package version"
        )
    return version


class AcquisitionVerifyPyPiSdkExecutor:
    descriptor = BrainAction(
        name="acq_verify_pypi_sdk",
        description=(
            "Verify a previously recorded unverified Python SDK candidate through the "
            "registered public PyPI/Phase-5 dependency path without executing it. "
            "Use this before acq_resolve when research finds a promising reusable "
            "Python package with an exact version. The action resolves wheel-only "
            "artifacts, seals their hashes/lock, verifies PyPI provenance, and emits "
            "a trusted SDK candidate. It cannot verify MCP/OpenAPI/AsyncAPI sources."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "candidate_id": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 160,
                }
            },
            "required": ["candidate_id"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.RESEARCH})

    def __init__(
        self,
        resolver: AcquisitionWorkContextResolver,
        *,
        broker_factory: Callable[[], DependencyBroker],
    ) -> None:
        self._resolver = resolver
        self._broker_factory = broker_factory

    def resource_keys(
        self,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> tuple[str, ...]:
        del work, parameters
        return ("network", "resolver", "artifact")

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        context = self._resolver.context_for(work.work_id)
        candidate_id = str(parameters.get("candidate_id") or "").strip()
        candidates = recorded_unverified_candidates(
            self._resolver.completed_steps(work.work_id)
        )
        candidate = next(
            (item for item in candidates if item.candidate_id == candidate_id),
            None,
        )
        if candidate is None:
            raise AcquisitionProtocolError(
                "PyPI SDK verification requires a recorded unverified candidate"
            )
        if candidate.source_kind is not AcquisitionSourceKind.SDK_LIBRARY:
            raise AcquisitionProtocolError(
                "PyPI SDK verification accepts only sdk_library candidates"
            )
        version = _exact_version(candidate.source_version)
        package = candidate.source_identity.strip().casefold()
        requirement_id = (
            "phase9:research-sdk:"
            + canonical_digest(
                {
                    "goal_digest": context.goal.digest,
                    "candidate_id": candidate.candidate_id,
                    "package_name": package,
                    "version": version,
                }
            )[:24]
        )
        requirement = DependencyRequirement(
            requirement_id=requirement_id,
            ecosystem=DependencyEcosystem.PYTHON,
            package_name=package,
            version_constraint="==" + version,
            purpose="Verify reusable SDK candidate before Phase-9 source selection",
            registered_source_ids=("pypi.public.v1",),
            change_id=context.change_id,
            work_id=context.work_id,
        )

        workspace = dependency_work_root(context.work_id) / (
            "research-sdk-"
            + canonical_digest({"candidate_id": candidate.candidate_id})[:16]
        )
        workspace.mkdir(parents=True, exist_ok=True)
        broker = self._broker_factory()
        resolved = await asyncio.to_thread(
            broker.resolve_python,
            requirement,
            workspace=workspace,
            environment=current_python_resolution_environment(),
        )
        artifacts = await asyncio.to_thread(
            broker.acquire_locked_wheels,
            resolved,
            staging_dir=workspace / "wheels",
        )
        lock = await asyncio.to_thread(broker.admit_lock, resolved)
        if tuple(item.sha256 for item in artifacts) != resolved.resolution.artifact_ids:
            raise AcquisitionProtocolError(
                "verified SDK wheel set differs from canonical PyPI resolution"
            )

        provenance = ProvenanceService(artifact_store=broker.artifact_store)
        provenance_results = []
        for artifact in artifacts:
            provenance_id = (
                "phase9-pypi:"
                + canonical_digest(
                    {
                        "candidate_id": candidate.candidate_id,
                        "artifact_id": artifact.artifact_id,
                    }
                )[:24]
            )
            result = await asyncio.to_thread(
                provenance.verify_pypi_artifact,
                artifact,
                resolution=resolved.resolution,
                provenance_id=provenance_id,
            )
            provenance_results.append(result)

        all_signed = bool(provenance_results) and all(
            item.provenance.attestation_status is AttestationStatus.VERIFIED
            for item in provenance_results
        )
        trust_class = (
            AcquisitionTrustClass.VERIFIED_SIGNED_EXTERNAL
            if all_signed
            else AcquisitionTrustClass.VERIFIED_OFFICIAL_REMOTE
        )
        source_digest = canonical_digest(
            {
                "source_id": "pypi.public.v1",
                "package_name": resolved.requirement.package_name,
                "package_version": version,
                "lock_digest": resolved.resolution.lock_digest,
                "artifact_ids": list(resolved.resolution.artifact_ids),
                "provenance": [
                    canonical_digest(item.provenance) for item in provenance_results
                ],
            }
        )
        provenance_refs = tuple(
            sorted(
                {
                    (
                        item.integrity_reference
                        or "pypi-provenance-sha256:" + canonical_digest(item.provenance)
                    )
                    for item in provenance_results
                }
            )
        )
        exact_dependency_ref = (
            f"pypi:{resolved.requirement.package_name}=={version}"
            f"#lock-sha256={resolved.resolution.lock_digest}"
        )
        verified = sdk_library_evidence(
            package_identity=resolved.requirement.package_name,
            package_version=version,
            package_digest=source_digest,
            trust_class=trust_class,
            supported_operations=candidate.supported_operations,
            evidence_refs=(
                *candidate.evidence_refs,
                "pypi-source:https://pypi.org/simple",
                f"pypi-lock-sha256:{lock.artifact_sha256}",
                *(f"pypi-wheel-sha256:{artifact.sha256}" for artifact in artifacts),
            ),
            provenance_refs=provenance_refs,
            license_id=candidate.license_id,
            dependency_refs=(exact_dependency_ref,),
            secret_scopes=candidate.secret_scopes,
            network_scopes=candidate.network_scopes,
            device_scopes=candidate.device_scopes,
            discovery_scopes=candidate.discovery_scopes,
            external_acceptance_requirements=(
                candidate.external_acceptance_requirements
            ),
        ).to_candidate(strategy=candidate.strategy)
        return {
            "verified": True,
            "source_candidate_id": candidate.candidate_id,
            "candidate": candidate_payload(verified),
            "trust_assignment": trust_class.value,
            "source_digest": source_digest,
            "lock_digest": resolved.resolution.lock_digest,
            "lock_artifact_id": lock.artifact_sha256,
            "artifact_ids": list(resolved.resolution.artifact_ids),
            "provenance_refs": list(provenance_refs),
            "execution_authorized": False,
        }


def build_acquisition_sdk_verification_executors(
    resolver: AcquisitionWorkContextResolver,
    *,
    broker_factory: Callable[[], DependencyBroker],
) -> tuple[object, ...]:
    return (
        AcquisitionVerifyPyPiSdkExecutor(
            resolver,
            broker_factory=broker_factory,
        ),
    )
