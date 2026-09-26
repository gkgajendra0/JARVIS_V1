"""Phase-5 evidence integration with canonical EngineeringChange/WorkItem truth.

This module adds no approval authority and no parallel lifecycle. It records bounded
digest/ID evidence under the existing EngineeringChange store, derives a current
lineage digest, and lets the canonical acceptance gate reject stale Phase-5 evidence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from jarvis.engineering_change.models import ChangeArtifact, ChangeConflict, ChangeState
from jarvis.engineering_change.store import ChangeStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.contracts import DependencyResolution, SecretLease
from jarvis.engineering_substrate.hardware_acceptance import HardwareAcceptanceService
from jarvis.engineering_substrate.manifest import RegisteredCapabilityManifest
from jarvis.work.models import WorkDeliveryKind, WorkState

DEPENDENCY_PLAN_KIND = "substrate_dependency_plan"
DEPENDENCY_RESOLUTION_KIND = "substrate_dependency_resolution"
MANIFEST_KIND = "substrate_manifest"
SECRET_LEASE_KIND = "substrate_secret_lease"
HARDWARE_EVIDENCE_KIND = "substrate_hardware_evidence"
VERIFICATION_KIND = "substrate_verification"

_ALLOWED_BIND_STATES = frozenset(
    {
        ChangeState.APPROVED_FOR_BUILD,
        ChangeState.DEVELOPING,
        ChangeState.VERIFYING,
        ChangeState.WAITING_OWNER_ACCEPTANCE,
        ChangeState.READY_FOR_PROMOTION,
        ChangeState.WAITING_PROMOTION_APPROVAL,
    }
)


@dataclass(frozen=True, slots=True)
class SubstrateBindingSnapshot:
    change_id: str
    architecture_artifact_id: str
    architecture_digest: str
    manifest_artifact_id: str
    manifest_artifact_digest: str
    manifest_digest: str
    dependency_artifact_ids: tuple[str, ...]
    dependency_artifact_digests: tuple[str, ...]
    secret_scope_digest: str
    secret_lease_artifact_ids: tuple[str, ...]
    hardware_evidence_artifact_ids: tuple[str, ...]
    binding_digest: str


class EngineeringSubstrateChangeService:
    """Record and validate Phase-5 evidence under one EngineeringChange."""

    def __init__(self, store: ChangeStore) -> None:
        if not isinstance(store, ChangeStore):
            raise TypeError("store must be a ChangeStore")
        self.store = store

    def _require_bind_state(self, change_id: str) -> None:
        change = self.store.require(change_id)
        if change.state not in _ALLOWED_BIND_STATES:
            raise ChangeConflict(
                "Phase-5 evidence requires an approved/downstream EngineeringChange"
            )

    def _approved_architecture(self, change_id: str) -> ChangeArtifact:
        architecture = self.store.latest_artifact(change_id, "architecture")
        if architecture is None:
            raise ChangeConflict("Phase-5 evidence requires current architecture")
        work = self.store.work
        with work._lock, work._connect() as db:
            approved = db.execute(
                """SELECT 1
                FROM engineering_change_gates AS gate
                JOIN engineering_change_decisions AS decision USING (gate_id)
                WHERE gate.change_id=?
                  AND gate.kind='architecture'
                  AND gate.artifact_id=?
                  AND gate.artifact_digest=?
                  AND decision.approved=1""",
                (
                    change_id,
                    architecture.artifact_id,
                    architecture.digest,
                ),
            ).fetchone()
        if approved is None:
            raise ChangeConflict(
                "Phase-5 evidence requires owner-approved current architecture"
            )
        return architecture

    def _artifacts(self, change_id: str, kind: str) -> tuple[ChangeArtifact, ...]:
        work = self.store.work
        with work._lock, work._connect() as db:
            rows = db.execute(
                """SELECT artifact_id FROM engineering_change_artifacts
                WHERE change_id=? AND kind=?
                ORDER BY revision DESC""",
                (change_id, kind),
            ).fetchall()
        result: list[ChangeArtifact] = []
        for row in rows:
            artifact = self.store.get_artifact(row["artifact_id"])
            if artifact is None:
                raise ChangeConflict("Phase-5 artifact disappeared during inspection")
            result.append(artifact)
        return tuple(result)

    def _operational_event(
        self,
        *,
        change_id: str,
        component: str,
        status: str,
        reference_id: str,
        digest: str,
    ) -> None:
        """Persist self-awareness evidence with IDs/digests only."""

        component_token = str(component).strip().casefold()
        status_token = str(status).strip().casefold()
        reference = str(reference_id).strip()
        if not component_token or not status_token or not reference:
            raise ValueError("operational event identity/status must not be empty")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("operational event digest must be SHA-256")
        event_digest = canonical_digest(
            {
                "component": component_token,
                "status": status_token,
                "reference_id": reference,
                "digest": digest,
            }
        )
        work = self.store.work
        with work._lock, work._connect() as db:
            self.store._event(
                db,
                change_id,
                f"substrate:{component_token}:{event_digest[:24]}",
                "substrate_operational",
                {
                    "component": component_token,
                    "status": status_token,
                    "reference_id": reference,
                    "digest": digest,
                },
            )

    def bind_dependency_plan(
        self,
        change_id: str,
        *,
        plan_id: str,
        plan_digest: str,
        requirement_ids: Sequence[str],
    ) -> ChangeArtifact:
        self._require_bind_state(change_id)
        architecture = self._approved_architecture(change_id)
        requirements = tuple(
            dict.fromkeys(
                str(item).strip() for item in requirement_ids if str(item).strip()
            )
        )
        if not str(plan_id).strip() or not requirements:
            raise ChangeConflict("dependency plan requires identity and requirements")
        if len(plan_digest) != 64 or any(
            ch not in "0123456789abcdef" for ch in plan_digest
        ):
            raise ChangeConflict("dependency plan digest must be SHA-256")
        artifact = self.store.add_artifact(
            change_id,
            kind=DEPENDENCY_PLAN_KIND,
            payload={
                "architecture_artifact_id": architecture.artifact_id,
                "architecture_digest": architecture.digest,
                "plan_id": str(plan_id).strip(),
                "plan_digest": plan_digest,
                "requirement_ids": list(requirements),
            },
        )
        self._operational_event(
            change_id=change_id,
            component="dependency_plan",
            status="bound",
            reference_id=artifact.artifact_id,
            digest=artifact.digest,
        )
        return artifact

    def bind_dependency_resolution(
        self,
        change_id: str,
        resolution: DependencyResolution,
    ) -> ChangeArtifact:
        self._require_bind_state(change_id)
        architecture = self._approved_architecture(change_id)
        if not isinstance(resolution, DependencyResolution):
            raise TypeError("resolution must be a DependencyResolution")
        if resolution.change_id is not None and resolution.change_id != change_id:
            raise ChangeConflict("dependency resolution belongs to another change")
        resolution_digest = canonical_digest(resolution)
        artifact = self.store.add_artifact(
            change_id,
            kind=DEPENDENCY_RESOLUTION_KIND,
            payload={
                "architecture_artifact_id": architecture.artifact_id,
                "architecture_digest": architecture.digest,
                "resolution_id": resolution.resolution_id,
                "resolution_digest": resolution_digest,
                "requirement_id": resolution.requirement_id,
                "artifact_ids": list(resolution.artifact_ids),
                "lock_digest": resolution.lock_digest,
            },
        )
        self._operational_event(
            change_id=change_id,
            component="dependency_resolution",
            status="bound",
            reference_id=artifact.artifact_id,
            digest=artifact.digest,
        )
        return artifact

    def _current_resolution_artifact(
        self,
        change_id: str,
        resolution_id: str,
    ) -> ChangeArtifact:
        for artifact in self._artifacts(change_id, DEPENDENCY_RESOLUTION_KIND):
            if artifact.payload.get("resolution_id") == resolution_id:
                return artifact
        raise ChangeConflict(
            f"manifest dependency resolution is not bound: {resolution_id}"
        )

    def bind_manifest(
        self,
        change_id: str,
        registered: RegisteredCapabilityManifest,
    ) -> ChangeArtifact:
        self._require_bind_state(change_id)
        architecture = self._approved_architecture(change_id)
        if not isinstance(registered, RegisteredCapabilityManifest):
            raise TypeError("registered must be a RegisteredCapabilityManifest")
        if canonical_digest(registered.manifest) != registered.manifest_digest:
            raise ChangeConflict("registered manifest digest no longer matches content")

        resolution_artifact_ids: list[str] = []
        resolution_artifact_digests: list[str] = []
        for resolution_id, expected_digest in zip(
            registered.manifest.dependency_resolution_ids,
            registered.manifest.dependency_resolution_digests,
            strict=True,
        ):
            artifact = self._current_resolution_artifact(change_id, resolution_id)
            if artifact.payload.get("resolution_digest") != expected_digest:
                raise ChangeConflict(
                    "dependency resolution changed before manifest bind: "
                    f"{resolution_id}"
                )
            if (
                artifact.payload.get("architecture_artifact_id")
                != architecture.artifact_id
                or artifact.payload.get("architecture_digest") != architecture.digest
            ):
                raise ChangeConflict(
                    "dependency resolution belongs to stale architecture"
                )
            resolution_artifact_ids.append(artifact.artifact_id)
            resolution_artifact_digests.append(artifact.digest)

        secret_scope_digest = canonical_digest(
            list(registered.manifest.secret_scope_requirements)
        )
        artifact = self.store.add_artifact(
            change_id,
            kind=MANIFEST_KIND,
            payload={
                "architecture_artifact_id": architecture.artifact_id,
                "architecture_digest": architecture.digest,
                "manifest_id": registered.manifest.manifest_id,
                "manifest_version": registered.manifest.manifest_version,
                "manifest_digest": registered.manifest_digest,
                "dependency_resolution_ids": list(
                    registered.manifest.dependency_resolution_ids
                ),
                "dependency_resolution_digests": list(
                    registered.manifest.dependency_resolution_digests
                ),
                "dependency_artifact_ids": resolution_artifact_ids,
                "dependency_artifact_digests": resolution_artifact_digests,
                "sandbox_profile_ids": list(registered.manifest.sandbox_profile_ids),
                "sandbox_profile_digests": list(
                    registered.manifest.sandbox_profile_digests
                ),
                "discovery_scope_ids": list(registered.manifest.discovery_scope_ids),
                "discovery_scope_digests": list(
                    registered.manifest.discovery_scope_digests
                ),
                "secret_scope_requirements": list(
                    registered.manifest.secret_scope_requirements
                ),
                "secret_scope_digest": secret_scope_digest,
                "verification_contract_ids": list(
                    registered.manifest.verification_contract_ids
                ),
                "hardware_acceptance_contract_ids": list(
                    registered.manifest.hardware_acceptance_contract_ids
                ),
            },
        )
        self._operational_event(
            change_id=change_id,
            component="capability_manifest",
            status="bound",
            reference_id=artifact.artifact_id,
            digest=artifact.digest,
        )
        return artifact

    def bind_secret_lease(
        self,
        change_id: str,
        lease: SecretLease,
    ) -> ChangeArtifact:
        self._require_bind_state(change_id)
        self._approved_architecture(change_id)
        if not isinstance(lease, SecretLease):
            raise TypeError("lease must be a SecretLease")
        if lease.change_id != change_id:
            raise ChangeConflict("secret lease is not bound to this EngineeringChange")
        manifest = self.store.latest_artifact(change_id, MANIFEST_KIND)
        if manifest is None:
            raise ChangeConflict("secret lease binding requires current manifest")
        required_scopes = set(manifest.payload.get("secret_scope_requirements", ()))
        if not set(lease.scopes).issubset(required_scopes):
            raise ChangeConflict("secret lease scopes exceed current manifest")
        artifact = self.store.add_artifact(
            change_id,
            kind=SECRET_LEASE_KIND,
            payload={
                "manifest_artifact_id": manifest.artifact_id,
                "manifest_artifact_digest": manifest.digest,
                "manifest_digest": manifest.payload.get("manifest_digest"),
                "secret_scope_digest": manifest.payload.get("secret_scope_digest"),
                "lease_id": lease.lease_id,
                "secret_id": lease.secret_id,
                "secret_version": lease.secret_version,
                "consumer_id": lease.consumer_id,
                "scopes": list(lease.scopes),
                "policy_digest": lease.policy_digest,
                "work_id": lease.work_id,
            },
        )
        self._operational_event(
            change_id=change_id,
            component="secret_lease",
            status="bound",
            reference_id=artifact.artifact_id,
            digest=artifact.digest,
        )
        return artifact

    def bind_hardware_evidence(
        self,
        change_id: str,
        *,
        request_id: str,
        hardware_contract_id: str,
    ) -> ChangeArtifact:
        self._require_bind_state(change_id)
        self._approved_architecture(change_id)
        contract_id = str(hardware_contract_id).strip().casefold()
        if not contract_id:
            raise ChangeConflict("hardware contract ID must not be empty")
        manifest = self.store.latest_artifact(change_id, MANIFEST_KIND)
        if manifest is None:
            raise ChangeConflict("hardware evidence binding requires current manifest")
        contracts = set(manifest.payload.get("hardware_acceptance_contract_ids", ()))
        if contract_id not in contracts:
            raise ChangeConflict(
                "hardware evidence contract is not declared by current manifest"
            )

        hardware = HardwareAcceptanceService(self.store)
        request = hardware.get_request(request_id)
        evidence = hardware.get_evidence(request_id)
        if request.change_id != change_id:
            raise ChangeConflict(
                "hardware request belongs to another EngineeringChange"
            )
        if request.manifest_digest != manifest.payload.get("manifest_digest"):
            raise ChangeConflict("hardware request belongs to stale manifest")
        if evidence is None:
            raise ChangeConflict("hardware request has no resolved evidence")

        artifact = self.store.add_artifact(
            change_id,
            kind=HARDWARE_EVIDENCE_KIND,
            payload={
                "manifest_artifact_id": manifest.artifact_id,
                "manifest_artifact_digest": manifest.digest,
                "manifest_digest": request.manifest_digest,
                "hardware_contract_id": contract_id,
                "request_id": request.request_id,
                "request_digest": canonical_digest(request),
                "evidence_id": evidence.evidence_id,
                "verdict": evidence.verdict.value,
            },
        )
        self._operational_event(
            change_id=change_id,
            component="hardware_acceptance",
            status="bound",
            reference_id=artifact.artifact_id,
            digest=artifact.digest,
        )
        return artifact

    def _current_secret_lease_artifacts(
        self,
        change_id: str,
        manifest: ChangeArtifact,
    ) -> tuple[ChangeArtifact, ...]:
        return tuple(
            artifact
            for artifact in self._artifacts(change_id, SECRET_LEASE_KIND)
            if artifact.payload.get("manifest_artifact_id") == manifest.artifact_id
            and artifact.payload.get("manifest_artifact_digest") == manifest.digest
            and artifact.payload.get("secret_scope_digest")
            == manifest.payload.get("secret_scope_digest")
        )

    def _current_hardware_artifacts(
        self,
        change_id: str,
        manifest: ChangeArtifact,
    ) -> tuple[ChangeArtifact, ...]:
        return tuple(
            artifact
            for artifact in self._artifacts(change_id, HARDWARE_EVIDENCE_KIND)
            if artifact.payload.get("manifest_artifact_id") == manifest.artifact_id
            and artifact.payload.get("manifest_artifact_digest") == manifest.digest
            and artifact.payload.get("manifest_digest")
            == manifest.payload.get("manifest_digest")
        )

    def binding_snapshot(self, change_id: str) -> SubstrateBindingSnapshot:
        self._require_bind_state(change_id)
        architecture = self._approved_architecture(change_id)
        manifest = self.store.latest_artifact(change_id, MANIFEST_KIND)
        if manifest is None:
            raise ChangeConflict("Phase-5 verification requires current manifest")
        if (
            manifest.payload.get("architecture_artifact_id") != architecture.artifact_id
            or manifest.payload.get("architecture_digest") != architecture.digest
        ):
            raise ChangeConflict("current manifest belongs to stale architecture")

        resolution_ids = tuple(manifest.payload.get("dependency_resolution_ids", ()))
        expected_resolution_digests = tuple(
            manifest.payload.get("dependency_resolution_digests", ())
        )
        bound_artifact_ids = tuple(manifest.payload.get("dependency_artifact_ids", ()))
        bound_artifact_digests = tuple(
            manifest.payload.get("dependency_artifact_digests", ())
        )
        if not (
            len(resolution_ids)
            == len(expected_resolution_digests)
            == len(bound_artifact_ids)
            == len(bound_artifact_digests)
        ):
            raise ChangeConflict("manifest dependency lineage is malformed")

        current_ids: list[str] = []
        current_digests: list[str] = []
        for (
            resolution_id,
            expected_resolution_digest,
            bound_artifact_id,
            bound_artifact_digest,
        ) in zip(
            resolution_ids,
            expected_resolution_digests,
            bound_artifact_ids,
            bound_artifact_digests,
            strict=True,
        ):
            artifact = self._current_resolution_artifact(change_id, str(resolution_id))
            if (
                artifact.artifact_id != bound_artifact_id
                or artifact.digest != bound_artifact_digest
                or artifact.payload.get("resolution_digest")
                != expected_resolution_digest
            ):
                raise ChangeConflict(
                    f"dependency resolution lineage is stale: {resolution_id}"
                )
            current_ids.append(artifact.artifact_id)
            current_digests.append(artifact.digest)

        secret_artifacts = self._current_secret_lease_artifacts(change_id, manifest)
        hardware_artifacts = self._current_hardware_artifacts(change_id, manifest)
        binding_payload = {
            "change_id": change_id,
            "architecture_artifact_id": architecture.artifact_id,
            "architecture_digest": architecture.digest,
            "manifest_artifact_id": manifest.artifact_id,
            "manifest_artifact_digest": manifest.digest,
            "manifest_digest": manifest.payload.get("manifest_digest"),
            "dependency_artifact_ids": current_ids,
            "dependency_artifact_digests": current_digests,
            "secret_scope_digest": manifest.payload.get("secret_scope_digest"),
            "secret_lease_artifact_ids": sorted(
                artifact.artifact_id for artifact in secret_artifacts
            ),
            "hardware_evidence_artifact_ids": sorted(
                artifact.artifact_id for artifact in hardware_artifacts
            ),
        }
        return SubstrateBindingSnapshot(
            change_id=change_id,
            architecture_artifact_id=architecture.artifact_id,
            architecture_digest=architecture.digest,
            manifest_artifact_id=manifest.artifact_id,
            manifest_artifact_digest=manifest.digest,
            manifest_digest=str(manifest.payload.get("manifest_digest")),
            dependency_artifact_ids=tuple(current_ids),
            dependency_artifact_digests=tuple(current_digests),
            secret_scope_digest=str(manifest.payload.get("secret_scope_digest")),
            secret_lease_artifact_ids=tuple(
                sorted(artifact.artifact_id for artifact in secret_artifacts)
            ),
            hardware_evidence_artifact_ids=tuple(
                sorted(artifact.artifact_id for artifact in hardware_artifacts)
            ),
            binding_digest=canonical_digest(binding_payload),
        )

    def secret_lease_binding_current(
        self,
        change_id: str,
        lease_id: str,
    ) -> bool:
        manifest = self.store.latest_artifact(change_id, MANIFEST_KIND)
        if manifest is None:
            return False
        return any(
            artifact.payload.get("lease_id") == lease_id
            for artifact in self._current_secret_lease_artifacts(change_id, manifest)
        )

    def record_verification(
        self,
        change_id: str,
        *,
        software_security_passed: bool,
        automated_evidence: Mapping[str, bool],
        hardware_contract_requests: Mapping[str, str] | None = None,
    ) -> ChangeArtifact:
        snapshot = self.binding_snapshot(change_id)
        manifest = self.store.latest_artifact(change_id, MANIFEST_KIND)
        if manifest is None:
            raise ChangeConflict("Phase-5 verification requires current manifest")

        automated = {
            str(key).strip(): bool(value) for key, value in automated_evidence.items()
        }
        if any(not key for key in automated):
            raise ValueError("automated evidence IDs must not be empty")

        required_secret_scopes = set(
            manifest.payload.get("secret_scope_requirements", ())
        )
        covered_secret_scopes: set[str] = set()
        for artifact in self._current_secret_lease_artifacts(change_id, manifest):
            covered_secret_scopes.update(
                str(item) for item in artifact.payload.get("scopes", ())
            )
        missing_secret_scopes = tuple(
            sorted(required_secret_scopes - covered_secret_scopes)
        )

        required_hardware = tuple(
            str(item)
            for item in manifest.payload.get("hardware_acceptance_contract_ids", ())
        )
        request_map = {
            str(key).strip().casefold(): str(value).strip()
            for key, value in (hardware_contract_requests or {}).items()
            if str(key).strip() and str(value).strip()
        }
        hardware_results: dict[str, bool] = {}
        missing_hardware: list[str] = []
        hardware = HardwareAcceptanceService(self.store)
        for contract_id in required_hardware:
            request_id = request_map.get(contract_id)
            if not request_id:
                missing_hardware.append(contract_id)
                hardware_results[contract_id] = False
                continue
            bound = next(
                (
                    artifact
                    for artifact in self._current_hardware_artifacts(
                        change_id,
                        manifest,
                    )
                    if artifact.payload.get("hardware_contract_id") == contract_id
                    and artifact.payload.get("request_id") == request_id
                ),
                None,
            )
            if bound is None:
                missing_hardware.append(contract_id)
                hardware_results[contract_id] = False
                continue
            assessment = hardware.assess(
                request_id,
                automated_evidence=automated,
            )
            hardware_results[contract_id] = assessment.satisfied

        automated_passed = all(automated.values())
        hardware_passed = all(hardware_results.values()) if required_hardware else True
        satisfied = (
            bool(software_security_passed)
            and automated_passed
            and not missing_secret_scopes
            and hardware_passed
            and not missing_hardware
        )
        artifact = self.store.add_artifact(
            change_id,
            kind=VERIFICATION_KIND,
            payload={
                "binding_digest": snapshot.binding_digest,
                "architecture_artifact_id": snapshot.architecture_artifact_id,
                "architecture_digest": snapshot.architecture_digest,
                "manifest_artifact_id": snapshot.manifest_artifact_id,
                "manifest_artifact_digest": snapshot.manifest_artifact_digest,
                "manifest_digest": snapshot.manifest_digest,
                "secret_scope_digest": snapshot.secret_scope_digest,
                "software_security_passed": bool(software_security_passed),
                "automated_evidence": dict(sorted(automated.items())),
                "missing_secret_scopes": list(missing_secret_scopes),
                "hardware_results": dict(sorted(hardware_results.items())),
                "missing_hardware_contracts": sorted(missing_hardware),
                "satisfied": satisfied,
            },
        )
        self._operational_event(
            change_id=change_id,
            component="substrate_verification",
            status="passed" if satisfied else "failed",
            reference_id=artifact.artifact_id,
            digest=artifact.digest,
        )
        return artifact

    def verification_current(self, change_id: str) -> bool:
        verification = self.store.latest_artifact(change_id, VERIFICATION_KIND)
        if verification is None or verification.payload.get("satisfied") is not True:
            return False
        try:
            snapshot = self.binding_snapshot(change_id)
        except ChangeConflict:
            return False
        return (
            verification.payload.get("binding_digest") == snapshot.binding_digest
            and verification.payload.get("architecture_artifact_id")
            == snapshot.architecture_artifact_id
            and verification.payload.get("architecture_digest")
            == snapshot.architecture_digest
            and verification.payload.get("manifest_artifact_id")
            == snapshot.manifest_artifact_id
            and verification.payload.get("manifest_artifact_digest")
            == snapshot.manifest_artifact_digest
            and verification.payload.get("secret_scope_digest")
            == snapshot.secret_scope_digest
        )

    def block_work_resource(
        self,
        work_id: str,
        *,
        component: str,
        reason_code: str,
        message: str,
    ):
        """Move one active WorkItem to WAITING_RESOURCE with stable reason de-dupe."""

        component_token = str(component).strip().casefold()
        reason_token = str(reason_code).strip().casefold()
        bounded_message = " ".join(str(message).split())
        if not component_token or not reason_token or not bounded_message:
            raise ValueError("resource blocker component/reason/message are required")
        if len(bounded_message) > 500:
            bounded_message = bounded_message[:497] + "..."

        work = self.store.work.require(work_id)
        if work.state.terminal or work.state is WorkState.PAUSED:
            raise ChangeConflict("terminal/paused work cannot receive resource blocker")
        if work.state is WorkState.WAITING_RESOURCE:
            waiting = work.with_progress(status_detail=bounded_message)
            waiting = self.store.work.save(waiting, expected_version=work.version)
        elif work.state in {WorkState.QUEUED, WorkState.RUNNING, WorkState.RETRYING}:
            waiting = work.transition(
                WorkState.WAITING_RESOURCE,
                status_detail=bounded_message,
                current_step_id=work.current_step_id,
            )
            waiting = self.store.work.save(waiting, expected_version=work.version)
        else:
            raise ChangeConflict(
                f"work state cannot receive resource blocker: {work.state.value}"
            )

        stable = hashlib.sha256(
            f"{component_token}|{reason_token}".encode("utf-8")
        ).hexdigest()[:24]
        return self.store.work.enqueue_delivery(
            work=waiting,
            kind=WorkDeliveryKind.RESOURCE_BLOCKER,
            message=bounded_message,
            event_key=f"substrate-resource:{component_token}:{stable}",
        )


def ensure_substrate_acceptance_current(
    store: ChangeStore,
    change_id: str,
) -> None:
    """Canonical acceptance guard; no-op for non-Phase-5 EngineeringChanges."""

    manifest = store.latest_artifact(change_id, MANIFEST_KIND)
    if manifest is None:
        return
    if not EngineeringSubstrateChangeService(store).verification_current(change_id):
        raise ChangeConflict(
            "acceptance requires current satisfied Phase-5 substrate verification"
        )
