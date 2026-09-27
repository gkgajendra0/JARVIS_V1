"""Deterministic Phase-9 capability-candidate verification."""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

from jarvis.capability_acquisition.architecture import (
    ensure_capability_acquisition_architecture_current,
)
from jarvis.capability_acquisition.candidate_models import (
    CapabilityAcquisitionCandidateEvidenceV1,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_registry.contracts import (
    CapabilityPackageContractError,
    CapabilityPackageV1,
    parse_capability_package_v1,
)
from jarvis.engineering_change.models import (
    ChangeArtifact,
    ChangeConflict,
    ChangeStage,
    ChangeState,
    EngineeringChange,
)
from jarvis.engineering_change.store import ChangeStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.change_integration import (
    MANIFEST_KIND,
    VERIFICATION_KIND,
    EngineeringSubstrateChangeService,
)
from jarvis.engineering_substrate.contracts import CapabilityManifest
from jarvis.incident_repair.models import ProtectedSurfaceVerdict
from jarvis.incident_repair.protected_surfaces import (
    ProtectedSurfaceAssessment,
    RepairProtectedSurfacePolicy,
)
from jarvis.incident_repair.verification import (
    SourceRepairCandidateError,
    SourceRepairCandidateVerifier,
)
from jarvis.work.development import DevelopmentWorkspaceManager
from jarvis.work.models import WorkItem, WorkState


class CapabilityAcquisitionCandidateError(ChangeConflict):
    """Phase-9 DEVELOPMENT failed deterministic candidate verification."""

    def __init__(self, reason_code: str, message: str) -> None:
        code = str(reason_code).strip().casefold()
        text = str(message).strip()
        if not code or not text:
            raise ValueError("candidate failure requires reason code and message")
        super().__init__(text)
        self.reason_code = code


class CapabilityAcquisitionProtectedSurfacePolicy(RepairProtectedSurfacePolicy):
    """Phase-6 protections plus declarative Phase-8 descriptor files."""

    policy_id = "capability_acquisition.protected_surfaces"
    policy_version = 1

    @staticmethod
    def _is_metadata_descriptor(path: str, directory: str) -> bool:
        pure = pathlib.PurePosixPath(path)
        return (
            len(pure.parts) == 2
            and pure.parts[0].casefold() == directory
            and pure.suffix.casefold() == ".json"
            and not pure.name.startswith(".")
        )

    @classmethod
    def _is_package_descriptor(cls, path: str) -> bool:
        return cls._is_metadata_descriptor(path, "capability_packages")

    @classmethod
    def _is_manifest_descriptor(cls, path: str) -> bool:
        return cls._is_metadata_descriptor(path, "capability_manifests")

    def assess(
        self,
        changed_paths: tuple[str, ...] | list[str],
    ) -> ProtectedSurfaceAssessment:
        normalized = tuple(
            dict.fromkeys(self.normalize_path(item) for item in changed_paths)
        )
        descriptors = tuple(
            path
            for path in normalized
            if self._is_package_descriptor(path)
            or self._is_manifest_descriptor(path)
        )
        ordinary = tuple(path for path in normalized if path not in descriptors)
        if ordinary:
            base = super().assess(ordinary)
            protected = base.protected
            unknown = base.unknown_paths
            clear = (*base.clear_paths, *descriptors)
        else:
            protected = ()
            unknown = ()
            clear = descriptors
        verdict = (
            ProtectedSurfaceVerdict.PROTECTED_CHANGE_REQUIRED
            if protected
            else (
                ProtectedSurfaceVerdict.UNKNOWN
                if unknown
                else ProtectedSurfaceVerdict.CLEAR
            )
        )
        return ProtectedSurfaceAssessment(
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            verdict=verdict,
            protected=tuple(protected),
            unknown_paths=tuple(unknown),
            clear_paths=tuple(sorted(clear)),
        )


@dataclass(frozen=True, slots=True)
class CapabilityCandidateVerification:
    candidate: CapabilityAcquisitionCandidateEvidenceV1
    candidate_artifact: ChangeArtifact
    acceptance_artifact: ChangeArtifact
    protected_surface: ProtectedSurfaceAssessment
    package: CapabilityPackageV1


class CapabilityAcquisitionCandidateVerifier:
    """Re-derive candidate truth from Git, tests, Phase-5 evidence and package JSON."""

    def __init__(
        self,
        store: ChangeStore,
        workspace_manager: DevelopmentWorkspaceManager,
    ) -> None:
        if not isinstance(store, ChangeStore):
            raise TypeError("store must be ChangeStore")
        if not isinstance(workspace_manager, DevelopmentWorkspaceManager):
            raise TypeError("workspace_manager must be DevelopmentWorkspaceManager")
        self._store = store
        self._workspace = workspace_manager
        self._protected = CapabilityAcquisitionProtectedSurfacePolicy()
        self._generic = SourceRepairCandidateVerifier(
            store,
            workspace_manager,
            protected_surface_policy=self._protected,
        )

    @staticmethod
    def _persist_if_changed(
        store: ChangeStore,
        *,
        change_id: str,
        kind: str,
        payload: dict[str, object],
    ) -> ChangeArtifact:
        latest = store.latest_artifact(change_id, kind)
        if latest is not None and latest.payload == payload:
            return latest
        return store.add_artifact(change_id, kind=kind, payload=payload)

    def _require_development(
        self,
        change_id: str,
    ) -> tuple[EngineeringChange, ChangeStage, WorkItem, ChangeArtifact]:
        change = self._store.require(change_id)
        if (
            change.process_key != OWNER_CAPABILITY_ACQUISITION_PROCESS.key
            or change.process_version != OWNER_CAPABILITY_ACQUISITION_PROCESS.version
        ):
            raise CapabilityAcquisitionCandidateError(
                "wrong_process",
                "candidate verifier only accepts owner_capability_acquisition.v1",
            )
        architecture = ensure_capability_acquisition_architecture_current(
            self._store,
            change_id,
        )
        stage = next(
            (
                item
                for item in reversed(self._store.list_stages(change_id))
                if item.stage_key
                == OWNER_CAPABILITY_ACQUISITION_PROCESS.development_stage.stage_key
                and item.plan_artifact_id == architecture.artifact_id
            ),
            None,
        )
        if stage is None:
            raise CapabilityAcquisitionCandidateError(
                "development_stage_missing",
                "current acquisition architecture has no development WorkItem",
            )
        work = self._store.work.require(stage.work_id)
        if work.state is not WorkState.COMPLETED:
            raise CapabilityAcquisitionCandidateError(
                "development_not_completed",
                "candidate verification requires completed DEVELOPMENT work",
            )
        return change, stage, work, architecture

    def _verify_scope(
        self,
        architecture: ChangeArtifact,
        changed_paths: tuple[str, ...],
    ) -> None:
        raw = architecture.payload.get("allowed_paths")
        allowed = tuple(
            dict.fromkeys(
                self._protected.normalize_path(item)
                for item in (raw if isinstance(raw, list) else [])
            )
        )
        if not allowed:
            raise CapabilityAcquisitionCandidateError(
                "approved_path_scope_missing",
                "capability acquisition architecture has no path-level scope",
            )
        outside = tuple(
            path
            for path in changed_paths
            if not any(
                path == scope
                or (
                    pathlib.PurePosixPath(scope).suffix == ""
                    and path.startswith(scope.rstrip("/") + "/")
                )
                for scope in allowed
            )
        )
        if outside:
            raise CapabilityAcquisitionCandidateError(
                "changed_path_outside_approved_scope",
                "candidate changed paths outside owner-approved architecture: "
                + ", ".join(outside),
            )

    def _package(
        self,
        *,
        work: WorkItem,
        architecture: ChangeArtifact,
        changed_paths: tuple[str, ...],
    ) -> tuple[CapabilityPackageV1, str]:
        expected_id = str(architecture.payload.get("proposed_package_id") or "")
        expected_version = str(
            architecture.payload.get("proposed_package_version") or ""
        )
        package_paths = tuple(
            path
            for path in changed_paths
            if self._protected._is_package_descriptor(path)
        )
        if not package_paths:
            raise CapabilityAcquisitionCandidateError(
                "package_descriptor_missing",
                "Phase-9 candidate must change a capability_packages/*.json descriptor",
            )
        matches: list[tuple[CapabilityPackageV1, str]] = []
        for relative in package_paths:
            target = self._workspace.resolve(
                work.work_id,
                relative,
                require_file=True,
            )
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("package descriptor must be an object")
                package = parse_capability_package_v1(raw)
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValueError,
                CapabilityPackageContractError,
            ) as exc:
                raise CapabilityAcquisitionCandidateError(
                    "package_descriptor_invalid",
                    f"invalid capability package descriptor: {relative}",
                ) from exc
            if (
                package.package_id == expected_id
                and package.package_version == expected_version
            ):
                matches.append((package, relative))
        if len(matches) != 1:
            raise CapabilityAcquisitionCandidateError(
                "package_descriptor_identity_mismatch",
                "candidate must contain exactly one approved package identity/version",
            )
        package, relative = matches[0]
        expected_capability = str(
            architecture.payload.get("proposed_capability_id") or ""
        )
        if package.capability_id != expected_capability:
            raise CapabilityAcquisitionCandidateError(
                "package_capability_mismatch",
                "package capability ID differs from approved architecture",
            )
        return package, relative

    def _manifest(
        self,
        *,
        work: WorkItem,
        package: CapabilityPackageV1,
        changed_paths: tuple[str, ...],
    ) -> tuple[CapabilityManifest, str]:
        manifest_paths = tuple(
            path
            for path in changed_paths
            if self._protected._is_manifest_descriptor(path)
        )
        if not manifest_paths:
            raise CapabilityAcquisitionCandidateError(
                "manifest_descriptor_missing",
                "Phase-9 candidate must change a capability_manifests/*.json descriptor",
            )
        matches: list[tuple[CapabilityManifest, str]] = []
        for relative in manifest_paths:
            target = self._workspace.resolve(
                work.work_id,
                relative,
                require_file=True,
            )
            try:
                raw = json.loads(target.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise ValueError("manifest descriptor must be an object")
                manifest = CapabilityManifest(**raw)  # type: ignore[arg-type]
            except (
                OSError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                TypeError,
                ValueError,
            ) as exc:
                raise CapabilityAcquisitionCandidateError(
                    "manifest_descriptor_invalid",
                    f"invalid capability manifest descriptor: {relative}",
                ) from exc
            digest = canonical_digest(manifest)
            if (
                manifest.manifest_id == package.manifest_id
                and manifest.manifest_version == package.manifest_version
                and digest == package.manifest_digest
            ):
                matches.append((manifest, relative))
        if len(matches) != 1:
            raise CapabilityAcquisitionCandidateError(
                "manifest_descriptor_identity_mismatch",
                "candidate must contain exactly one manifest matching the package digest",
            )
        manifest, relative = matches[0]
        if (
            manifest.capability_id != package.capability_id
            or manifest.capability_version != package.package_version
        ):
            raise CapabilityAcquisitionCandidateError(
                "manifest_package_capability_mismatch",
                "candidate manifest capability/version differs from package",
            )
        return manifest, relative

    def _substrate(
        self,
        *,
        change_id: str,
        package: CapabilityPackageV1,
        architecture: ChangeArtifact,
    ) -> tuple[ChangeArtifact, str]:
        service = EngineeringSubstrateChangeService(self._store)
        if not service.verification_current(change_id):
            raise CapabilityAcquisitionCandidateError(
                "substrate_verification_missing",
                "candidate requires current satisfied Phase-5 substrate verification",
            )
        manifest = self._store.latest_artifact(change_id, MANIFEST_KIND)
        verification = self._store.latest_artifact(change_id, VERIFICATION_KIND)
        if manifest is None or verification is None:
            raise CapabilityAcquisitionCandidateError(
                "substrate_evidence_missing",
                "current Phase-5 manifest/verification artifacts are missing",
            )
        if (
            manifest.payload.get("manifest_id") != package.manifest_id
            or manifest.payload.get("manifest_version") != package.manifest_version
            or manifest.payload.get("manifest_digest") != package.manifest_digest
        ):
            raise CapabilityAcquisitionCandidateError(
                "package_manifest_mismatch",
                "package descriptor differs from current Phase-5 manifest evidence",
            )
        for architecture_key, manifest_key in (
            ("secret_scopes", "secret_scope_requirements"),
            ("sandbox_profile_ids", "sandbox_profile_ids"),
            ("discovery_scopes", "discovery_scope_ids"),
            ("verification_contract_ids", "verification_contract_ids"),
            ("owner_acceptance_contract_ids", "hardware_acceptance_contract_ids"),
        ):
            approved = set(architecture.payload.get(architecture_key) or ())
            bound = set(manifest.payload.get(manifest_key) or ())
            if approved != bound:
                raise CapabilityAcquisitionCandidateError(
                    "substrate_scope_mismatch",
                    f"Phase-5 manifest {manifest_key} differs from approved architecture",
                )
        if architecture.payload.get("dependency_refs") and not manifest.payload.get(
            "dependency_resolution_ids"
        ):
            raise CapabilityAcquisitionCandidateError(
                "dependency_evidence_missing",
                "approved dependencies require bound Phase-5 dependency resolutions",
            )
        snapshot = service.binding_snapshot(change_id)
        if verification.payload.get("binding_digest") != snapshot.binding_digest:
            raise CapabilityAcquisitionCandidateError(
                "substrate_binding_stale",
                "Phase-5 verification is not bound to current substrate evidence",
            )
        return verification, snapshot.binding_digest

    def verify_and_persist(self, change_id: str) -> CapabilityCandidateVerification:
        _, _, work, architecture = self._require_development(change_id)
        try:
            git = self._generic._git_evidence(work, architecture)
        except SourceRepairCandidateError as exc:
            raise CapabilityAcquisitionCandidateError(
                exc.reason_code,
                str(exc),
            ) from exc
        protected = self._protected.assess(git.changed_paths)
        if protected.verdict is not ProtectedSurfaceVerdict.CLEAR:
            raise CapabilityAcquisitionCandidateError(
                "protected_surface_blocked",
                "ordinary Phase-9 capability build touched protected/unknown surfaces",
            )
        self._verify_scope(architecture, git.changed_paths)

        targets = tuple(
            str(item).strip()
            for item in architecture.payload.get("verification_targets", ())
            if str(item).strip()
        )
        if not targets:
            raise CapabilityAcquisitionCandidateError(
                "verification_targets_missing",
                "approved capability architecture has no development test targets",
            )
        try:
            passing, _ = self._generic._verify_workstep_order(
                work,
                self._store.work.list_steps(work.work_id),
                targets,
            )
        except SourceRepairCandidateError as exc:
            raise CapabilityAcquisitionCandidateError(
                exc.reason_code,
                str(exc),
            ) from exc

        package, package_path = self._package(
            work=work,
            architecture=architecture,
            changed_paths=git.changed_paths,
        )
        manifest, manifest_path = self._manifest(
            work=work,
            package=package,
            changed_paths=git.changed_paths,
        )
        substrate, binding_digest = self._substrate(
            change_id=change_id,
            package=package,
            architecture=architecture,
        )

        candidate = CapabilityAcquisitionCandidateEvidenceV1.create(
            goal_digest=str(architecture.payload.get("goal_digest") or ""),
            plan_digest=str(architecture.payload.get("plan_digest") or ""),
            architecture_artifact_id=architecture.artifact_id,
            architecture_digest=architecture.digest,
            development_work_id=work.work_id,
            branch=git.branch,
            commit=git.commit,
            source_revision=git.source_revision,
            changed_paths=git.changed_paths,
            diff_digest=git.diff_digest,
            verification_targets=targets,
            sandbox_profile=str(passing.observation.get("sandbox_profile") or ""),
            sandbox_profile_version=int(
                passing.observation.get("sandbox_profile_version") or 0
            ),
            package_descriptor_path=package_path,
            manifest_descriptor_path=manifest_path,
            package_id=package.package_id,
            package_version=package.package_version,
            package_digest=package.digest,
            capability_id=package.capability_id,
            manifest_id=package.manifest_id,
            manifest_version=package.manifest_version,
            manifest_digest=canonical_digest(manifest),
            substrate_verification_artifact_id=substrate.artifact_id,
            substrate_verification_artifact_digest=substrate.digest,
            substrate_binding_digest=binding_digest,
            external_acceptance_contract_ids=tuple(
                architecture.payload.get("owner_acceptance_contract_ids") or ()
            ),
            protected_surface_policy_id=protected.policy_id,
            protected_surface_policy_version=protected.policy_version,
            now_epoch=work.updated_at.timestamp(),
        )
        candidate_payload: dict[str, object] = {
            "schema": "capability_acquisition_candidate.v1",
            "candidate_evidence_id": candidate.candidate_evidence_id,
            **candidate.canonical_payload(),
            "digest": candidate.digest,
            "protected_surface": protected.to_payload(),
        }
        candidate_artifact = self._persist_if_changed(
            self._store,
            change_id=change_id,
            kind="capability_acquisition_candidate",
            payload=candidate_payload,
        )
        acceptance = self._persist_if_changed(
            self._store,
            change_id=change_id,
            kind="acceptance",
            payload={
                "work_id": work.work_id,
                "result": work.result,
                "candidate_artifact_id": candidate_artifact.artifact_id,
                "candidate_artifact_digest": candidate_artifact.digest,
                "candidate": candidate_payload,
                "substrate_verification_artifact_id": substrate.artifact_id,
                "substrate_verification_artifact_digest": substrate.digest,
            },
        )
        return CapabilityCandidateVerification(
            candidate=candidate,
            candidate_artifact=candidate_artifact,
            acceptance_artifact=acceptance,
            protected_surface=protected,
            package=package,
        )


def ensure_capability_acquisition_candidate_current(
    store: ChangeStore,
    change_id: str,
) -> ChangeArtifact:
    candidate = store.latest_artifact(change_id, "capability_acquisition_candidate")
    acceptance = store.latest_artifact(change_id, "acceptance")
    if candidate is None or acceptance is None:
        raise CapabilityAcquisitionCandidateError(
            "candidate_missing",
            "Phase-9 acceptance requires current capability candidate evidence",
        )
    if (
        acceptance.payload.get("candidate_artifact_id") != candidate.artifact_id
        or acceptance.payload.get("candidate_artifact_digest") != candidate.digest
    ):
        raise CapabilityAcquisitionCandidateError(
            "candidate_acceptance_stale",
            "Phase-9 acceptance is not bound to current candidate evidence",
        )
    architecture = ensure_capability_acquisition_architecture_current(store, change_id)
    if (
        candidate.payload.get("architecture_artifact_id") != architecture.artifact_id
        or candidate.payload.get("architecture_digest") != architecture.digest
        or candidate.payload.get("goal_digest")
        != architecture.payload.get("goal_digest")
        or candidate.payload.get("plan_digest")
        != architecture.payload.get("plan_digest")
    ):
        raise CapabilityAcquisitionCandidateError(
            "candidate_architecture_stale",
            "Phase-9 candidate belongs to stale acquisition architecture",
        )
    service = EngineeringSubstrateChangeService(store)
    if not service.verification_current(change_id):
        raise CapabilityAcquisitionCandidateError(
            "candidate_substrate_stale",
            "Phase-9 candidate Phase-5 verification is no longer current",
        )
    verification = store.latest_artifact(change_id, VERIFICATION_KIND)
    if (
        verification is None
        or candidate.payload.get("substrate_verification_artifact_id")
        != verification.artifact_id
        or candidate.payload.get("substrate_verification_artifact_digest")
        != verification.digest
    ):
        raise CapabilityAcquisitionCandidateError(
            "candidate_substrate_revision_stale",
            "Phase-9 candidate references stale Phase-5 verification",
        )
    return candidate


class CapabilityAcquisitionDevelopmentCompletionHandler:
    """Fail closed unless Phase-9 DEVELOPMENT produces a verified package candidate."""

    process_key = OWNER_CAPABILITY_ACQUISITION_PROCESS.key
    process_version = OWNER_CAPABILITY_ACQUISITION_PROCESS.version

    def __init__(
        self,
        store: ChangeStore,
        workspace_manager: DevelopmentWorkspaceManager,
    ) -> None:
        self._store = store
        self._verifier = CapabilityAcquisitionCandidateVerifier(
            store,
            workspace_manager,
        )

    def complete(
        self,
        *,
        change: EngineeringChange,
        stage: ChangeStage,
        work: WorkItem,
    ) -> ChangeState | None:
        del stage, work
        try:
            result = self._verifier.verify_and_persist(change.change_id)
        except CapabilityAcquisitionCandidateError as exc:
            payload = {
                "passed": False,
                "reason_code": exc.reason_code,
                "message": str(exc),
            }
            latest = self._store.latest_artifact(
                change.change_id,
                "capability_acquisition_verification",
            )
            if latest is None or latest.payload != payload:
                self._store.add_artifact(
                    change.change_id,
                    kind="capability_acquisition_verification",
                    payload=payload,
                )
            return ChangeState.FAILED

        payload = {
            "passed": True,
            "candidate_artifact_id": result.candidate_artifact.artifact_id,
            "candidate_artifact_digest": result.candidate_artifact.digest,
            "acceptance_artifact_id": result.acceptance_artifact.artifact_id,
            "acceptance_artifact_digest": result.acceptance_artifact.digest,
            "candidate_digest": result.candidate.digest,
            "package_digest": result.package.digest,
        }
        latest = self._store.latest_artifact(
            change.change_id,
            "capability_acquisition_verification",
        )
        if latest is None or latest.payload != payload:
            self._store.add_artifact(
                change.change_id,
                kind="capability_acquisition_verification",
                payload=payload,
            )
        return None
