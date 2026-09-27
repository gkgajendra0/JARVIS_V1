"""Bounded Phase-9 DEVELOPMENT actions for candidate manifest/substrate evidence."""

from __future__ import annotations

import json
import pathlib
from dataclasses import fields
from typing import Any

from jarvis.authority.risk import RiskClassifier
from jarvis.authority.types import ActionAttributes, ActionScope
from jarvis.capability_acquisition.architecture import (
    ensure_capability_acquisition_architecture_current,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_registry.contracts import (
    CapabilityPackageContractError,
    parse_capability_package_v1,
)
from jarvis.engineering_change import ChangeStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.change_integration import (
    MANIFEST_KIND,
    EngineeringSubstrateChangeService,
)
from jarvis.engineering_substrate.contracts import CapabilityManifest
from jarvis.engineering_substrate.manifest import RegisteredCapabilityManifest
from jarvis.engineering_substrate.sandbox import default_sandbox_registry
from jarvis.work.brain import BrainAction
from jarvis.work.development import DevelopmentWorkspaceManager
from jarvis.work.engine import WorkEngine
from jarvis.work.models import WorkItem, WorkType


class CapabilityCandidateActionError(RuntimeError):
    """Candidate metadata cannot be bound safely."""


_AUTHORITY_FIELDS = frozenset(
    item.name for item in fields(ActionAttributes) if item.name != "scope"
)


def _phase9_development(
    store: ChangeStore,
    work: WorkItem,
):
    stage = store.stage_for_work(work.work_id)
    if stage is None:
        raise CapabilityCandidateActionError(
            "DEVELOPMENT WorkItem is not linked to an EngineeringChange"
        )
    change = store.require(stage.change_id)
    if (
        change.process_key != OWNER_CAPABILITY_ACQUISITION_PROCESS.key
        or change.process_version != OWNER_CAPABILITY_ACQUISITION_PROCESS.version
        or stage.stage_key
        != OWNER_CAPABILITY_ACQUISITION_PROCESS.development_stage.stage_key
    ):
        raise CapabilityCandidateActionError(
            "Phase-9 candidate action is unavailable for this DEVELOPMENT WorkItem"
        )
    architecture = ensure_capability_acquisition_architecture_current(
        store,
        change.change_id,
        artifact_id=stage.plan_artifact_id,
    )
    return change, architecture


def _metadata_path(
    value: object,
    *,
    directory: str,
    label: str,
) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    pure = pathlib.PurePosixPath(raw)
    if (
        not raw
        or pure.is_absolute()
        or len(pure.parts) != 2
        or pure.parts[0].casefold() != directory
        or pure.suffix.casefold() != ".json"
        or pure.name.startswith(".")
        or ".." in pure.parts
    ):
        raise CapabilityCandidateActionError(
            f"{label} must be {directory}/<name>.json"
        )
    return pure.as_posix()


def _read_json_object(
    manager: DevelopmentWorkspaceManager,
    work_id: str,
    relative_path: str,
) -> dict[str, object]:
    target = manager.resolve(work_id, relative_path, require_file=True)
    if target.stat().st_size <= 0 or target.stat().st_size > 1024 * 1024:
        raise CapabilityCandidateActionError("candidate metadata file size is invalid")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CapabilityCandidateActionError(
            "candidate metadata file is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise CapabilityCandidateActionError(
            "candidate metadata JSON must be an object"
        )
    return payload


def _manifest_from_payload(payload: dict[str, object]) -> CapabilityManifest:
    expected = {item.name for item in fields(CapabilityManifest)}
    unknown = set(payload) - expected
    if unknown:
        raise CapabilityCandidateActionError(
            "candidate manifest contains unknown fields: "
            + ", ".join(sorted(unknown))
        )
    try:
        return CapabilityManifest(**payload)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise CapabilityCandidateActionError(
            "candidate capability manifest failed v1 contract validation"
        ) from exc


def _risk_floor(manifest: CapabilityManifest):
    unknown = set(manifest.authority_attributes) - _AUTHORITY_FIELDS
    if unknown:
        raise CapabilityCandidateActionError(
            "candidate manifest has unknown Authority attributes: "
            + ", ".join(sorted(unknown))
        )
    kwargs = {name: True for name in manifest.authority_attributes}
    kwargs["scope"] = ActionScope.SINGLE
    return RiskClassifier().classify(ActionAttributes(**kwargs)).risk_class


def _validate_manifest_alignment(
    architecture,
    manifest: CapabilityManifest,
) -> None:
    checks = (
        (
            manifest.capability_id,
            str(architecture.payload.get("proposed_capability_id") or ""),
            "capability_id",
        ),
        (
            manifest.capability_version,
            str(architecture.payload.get("proposed_package_version") or ""),
            "capability_version",
        ),
    )
    for actual, expected, label in checks:
        if actual != expected:
            raise CapabilityCandidateActionError(
                f"candidate manifest {label} differs from approved architecture"
            )
    requested_operations = set(
        architecture.payload.get("requested_operations") or ()
    )
    if not requested_operations.issubset(set(manifest.operations)):
        raise CapabilityCandidateActionError(
            "candidate manifest does not cover all owner-requested operations"
        )

    exact_sets = (
        (
            set(manifest.secret_scope_requirements),
            set(architecture.payload.get("secret_scopes") or ()),
            "secret_scope_requirements",
        ),
        (
            set(manifest.sandbox_profile_ids),
            set(architecture.payload.get("sandbox_profile_ids") or ()),
            "sandbox_profile_ids",
        ),
        (
            set(manifest.discovery_scope_ids),
            set(architecture.payload.get("discovery_scopes") or ()),
            "discovery_scope_ids",
        ),
        (
            set(manifest.verification_contract_ids),
            set(architecture.payload.get("verification_contract_ids") or ()),
            "verification_contract_ids",
        ),
        (
            set(manifest.hardware_acceptance_contract_ids),
            set(architecture.payload.get("owner_acceptance_contract_ids") or ()),
            "hardware_acceptance_contract_ids",
        ),
    )
    for actual, expected, label in exact_sets:
        if actual != expected:
            raise CapabilityCandidateActionError(
                f"candidate manifest {label} differs from approved architecture"
            )
    if architecture.payload.get("dependency_refs") and not (
        manifest.dependency_resolution_ids
    ):
        raise CapabilityCandidateActionError(
            "approved dependencies require manifest dependency resolutions"
        )


class CapabilityManifestContextExecutor:
    descriptor = BrainAction(
        name="dev_phase9_manifest_context",
        description=(
            "Read exact owner-approved Phase-9 manifest requirements and trusted "
            "sandbox-profile digests. This action is read-only and exposes no secrets."
        ),
        parameter_schema={"type": "object", "additionalProperties": False},
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    def __init__(
        self,
        store: ChangeStore,
    ) -> None:
        self._store = store

    def resource_keys(
        self,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> tuple[str, ...]:
        del work, parameters
        return ()

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        del parameters
        _, architecture = _phase9_development(self._store, work)
        sandbox = default_sandbox_registry()
        profiles: list[dict[str, object]] = []
        for profile_id in architecture.payload.get("sandbox_profile_ids") or ():
            definition = sandbox.require(str(profile_id), 1)
            profiles.append(
                {
                    "profile_id": definition.profile.profile_id,
                    "profile_version": definition.profile.profile_version,
                    "profile_digest": canonical_digest(definition.profile),
                }
            )
        return {
            "architecture_artifact_id": architecture.artifact_id,
            "architecture_digest": architecture.digest,
            "proposed_capability_id": architecture.payload.get(
                "proposed_capability_id"
            ),
            "proposed_package_id": architecture.payload.get("proposed_package_id"),
            "proposed_package_version": architecture.payload.get(
                "proposed_package_version"
            ),
            "requested_operations": architecture.payload.get("requested_operations"),
            "secret_scopes": architecture.payload.get("secret_scopes"),
            "discovery_scopes": architecture.payload.get("discovery_scopes"),
            "network_scopes": architecture.payload.get("network_scopes"),
            "device_scopes": architecture.payload.get("device_scopes"),
            "verification_contract_ids": architecture.payload.get(
                "verification_contract_ids"
            ),
            "owner_acceptance_contract_ids": architecture.payload.get(
                "owner_acceptance_contract_ids"
            ),
            "sandbox_profiles": profiles,
            "secret_values_exposed": False,
        }


class CapabilityBindSubstrateExecutor:
    descriptor = BrainAction(
        name="dev_phase9_bind_substrate",
        description=(
            "After tests, final diff and a clean local commit, bind the committed "
            "declarative capability manifest/package to Phase-5 evidence and record "
            "deterministic substrate verification. This action executes no candidate code."
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "manifest_path": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 1000,
                },
                "package_path": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 1000,
                },
            },
            "required": ["manifest_path", "package_path"],
            "additionalProperties": False,
        },
    )
    work_types = frozenset({WorkType.DEVELOPMENT})

    def __init__(
        self,
        store: ChangeStore,
        workspace_manager: DevelopmentWorkspaceManager,
    ) -> None:
        self._store = store
        self._workspace = workspace_manager

    def resource_keys(
        self,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> tuple[str, ...]:
        del work, parameters
        return ("artifact",)

    async def execute(
        self,
        *,
        work: WorkItem,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        change, architecture = _phase9_development(self._store, work)
        steps = self._store.work.list_steps(work.work_id)
        (
            last_write,
            last_passing_test,
            last_diff,
            last_clean_commit,
        ) = WorkEngine._development_evidence_indices(steps)
        if not (
            last_write >= 0
            and last_passing_test > last_write
            and last_diff > last_passing_test
            and last_clean_commit > last_diff
        ):
            raise CapabilityCandidateActionError(
                "substrate binding requires post-edit tests, final diff and clean commit"
            )
        workspace = self._workspace.workspace_for(work.work_id)
        status = self._workspace._run(
            workspace.path,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ).stdout
        if status.strip():
            raise CapabilityCandidateActionError(
                "substrate binding requires a clean committed worktree"
            )

        manifest_path = _metadata_path(
            parameters.get("manifest_path"),
            directory="capability_manifests",
            label="manifest_path",
        )
        package_path = _metadata_path(
            parameters.get("package_path"),
            directory="capability_packages",
            label="package_path",
        )
        manifest = _manifest_from_payload(
            _read_json_object(self._workspace, work.work_id, manifest_path)
        )
        _validate_manifest_alignment(architecture, manifest)

        package_payload = _read_json_object(
            self._workspace,
            work.work_id,
            package_path,
        )
        try:
            package = parse_capability_package_v1(package_payload)
        except (CapabilityPackageContractError, TypeError, ValueError) as exc:
            raise CapabilityCandidateActionError(
                "candidate package descriptor failed v1 validation"
            ) from exc
        if (
            package.package_id
            != str(architecture.payload.get("proposed_package_id") or "")
            or package.package_version
            != str(architecture.payload.get("proposed_package_version") or "")
            or package.capability_id != manifest.capability_id
            or package.manifest_id != manifest.manifest_id
            or package.manifest_version != manifest.manifest_version
        ):
            raise CapabilityCandidateActionError(
                "candidate package identity differs from approved manifest/architecture"
            )
        manifest_digest = canonical_digest(manifest)
        if package.manifest_digest != manifest_digest:
            raise CapabilityCandidateActionError(
                "candidate package manifest digest differs from committed manifest"
            )

        registered = RegisteredCapabilityManifest(
            manifest=manifest,
            manifest_digest=manifest_digest,
            authority_risk_floor=_risk_floor(manifest),
        )
        service = EngineeringSubstrateChangeService(self._store)
        latest_manifest = self._store.latest_artifact(change.change_id, MANIFEST_KIND)
        if (
            latest_manifest is None
            or latest_manifest.payload.get("manifest_digest") != manifest_digest
            or latest_manifest.payload.get("architecture_artifact_id")
            != architecture.artifact_id
            or latest_manifest.payload.get("architecture_digest")
            != architecture.digest
        ):
            latest_manifest = service.bind_manifest(
                change.change_id,
                registered,
            )

        verification = service.record_verification(
            change.change_id,
            software_security_passed=True,
            automated_evidence={
                "candidate-package-contract": True,
                "committed-development-tests": True,
                "manifest-architecture-binding": True,
            },
        )
        return {
            "manifest_artifact_id": latest_manifest.artifact_id,
            "manifest_artifact_digest": latest_manifest.digest,
            "manifest_digest": manifest_digest,
            "package_id": package.package_id,
            "package_version": package.package_version,
            "package_digest": package.digest,
            "substrate_verification_artifact_id": verification.artifact_id,
            "substrate_verification_artifact_digest": verification.digest,
            "substrate_satisfied": verification.payload.get("satisfied") is True,
            "missing_secret_scopes": verification.payload.get(
                "missing_secret_scopes",
                [],
            ),
            "missing_hardware_contracts": verification.payload.get(
                "missing_hardware_contracts",
                [],
            ),
            "candidate_code_executed": False,
        }


def capability_candidate_completion_guard(
    work: WorkItem,
    steps,
) -> tuple[bool, str | None]:
    base_allowed, base_reason = WorkEngine._completion_guard(work, steps)
    if not base_allowed:
        return base_allowed, base_reason
    last_commit = max(
        (
            index
            for index, step in enumerate(steps)
            if step.kind == "dev_commit"
            and step.state.value == "completed"
            and step.observation.get("committed") is True
            and step.observation.get("clean") is True
        ),
        default=-1,
    )
    last_substrate = max(
        (
            index
            for index, step in enumerate(steps)
            if step.kind == "dev_phase9_bind_substrate"
            and step.state.value == "completed"
            and step.observation.get("substrate_satisfied") is True
        ),
        default=-1,
    )
    if last_substrate <= last_commit:
        return (
            False,
            "Phase-9 development requires current satisfied substrate binding "
            "after the final clean commit",
        )
    return True, None


def build_capability_candidate_executors(
    store: ChangeStore,
    workspace_manager: DevelopmentWorkspaceManager,
) -> tuple[object, ...]:
    return (
        CapabilityManifestContextExecutor(store),
        CapabilityBindSubstrateExecutor(store, workspace_manager),
    )
