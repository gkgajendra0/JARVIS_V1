"""Phase-9 capability candidate verification before owner acceptance."""

from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass

from jarvis.capability_acquisition.architecture import (
    ensure_capability_acquisition_architecture_current,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_registry.contracts import (
    CAPABILITY_RUNTIME_API_ID,
    CAPABILITY_RUNTIME_API_VERSION_V1,
    CapabilityPackageKind,
    CapabilityPackageV1,
    parse_capability_package_v1,
)
from jarvis.development_engine.contracts import DevelopmentDisposition
from jarvis.development_engine.phase9 import (
    PHASE9_DEVELOPMENT_ENGINE_ACTION,
    development_result_from_work,
    phase9_revision_disposition,
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
    EngineeringSubstrateChangeService,
)
from jarvis.incident_repair.models import ProtectedSurfaceVerdict
from jarvis.incident_repair.protected_surfaces import (
    ProtectedSurfaceAssessment,
    RepairProtectedSurfacePolicy,
)
from jarvis.work.development import (
    DevelopmentWorkspaceError,
    DevelopmentWorkspaceManager,
)
from jarvis.work.models import WorkItem, WorkState, WorkStep

_PACKAGE_ROOT = "capability_packages"
_MAX_PACKAGE_FILES = 128
_MAX_PACKAGE_BYTES = 1024 * 1024


class CapabilityCandidateError(ChangeConflict):
    """A Phase-9 DEVELOPMENT candidate failed deterministic verification."""

    def __init__(self, reason_code: str, message: str) -> None:
        code = str(reason_code).strip().casefold()
        text = str(message).strip()
        if not code or not text:
            raise ValueError("candidate failure requires reason code and message")
        super().__init__(text)
        self.reason_code = code


@dataclass(frozen=True, slots=True)
class CapabilityCandidateGitEvidence:
    branch: str
    commit: str
    source_revision: str
    changed_paths: tuple[str, ...]
    diff_digest: str


@dataclass(frozen=True, slots=True)
class CapabilityCandidateEvidenceV1:
    architecture_artifact_id: str
    architecture_digest: str
    plan_id: str
    plan_digest: str
    development_work_id: str
    branch: str
    commit: str
    source_revision: str
    changed_paths: tuple[str, ...]
    diff_digest: str
    package_path: str
    package_id: str
    package_version: str
    package_digest: str
    capability_id: str
    manifest_id: str
    manifest_version: int
    manifest_digest: str
    sandbox_profile: str
    sandbox_profile_version: int
    protected_surface_policy_id: str
    protected_surface_policy_version: int
    verification_contract_ids: tuple[str, ...]
    owner_acceptance_contract_ids: tuple[str, ...]

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": "capability_candidate_evidence.v1",
            "architecture_artifact_id": self.architecture_artifact_id,
            "architecture_digest": self.architecture_digest,
            "plan_id": self.plan_id,
            "plan_digest": self.plan_digest,
            "development_work_id": self.development_work_id,
            "branch": self.branch,
            "commit": self.commit,
            "source_revision": self.source_revision,
            "changed_paths": list(self.changed_paths),
            "diff_digest": self.diff_digest,
            "package_path": self.package_path,
            "package_id": self.package_id,
            "package_version": self.package_version,
            "package_digest": self.package_digest,
            "capability_id": self.capability_id,
            "manifest_id": self.manifest_id,
            "manifest_version": self.manifest_version,
            "manifest_digest": self.manifest_digest,
            "sandbox_profile": self.sandbox_profile,
            "sandbox_profile_version": self.sandbox_profile_version,
            "protected_surface_policy_id": self.protected_surface_policy_id,
            "protected_surface_policy_version": self.protected_surface_policy_version,
            "verification_contract_ids": list(self.verification_contract_ids),
            "owner_acceptance_contract_ids": list(self.owner_acceptance_contract_ids),
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.canonical_payload())

    @property
    def candidate_id(self) -> str:
        return "capcand_" + self.digest[:24]


@dataclass(frozen=True, slots=True)
class CapabilityCandidateVerification:
    candidate: CapabilityCandidateEvidenceV1
    candidate_artifact: ChangeArtifact
    acceptance_artifact: ChangeArtifact
    protected_surface: ProtectedSurfaceAssessment


def _normalize_repo_path(value: object) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    raw = raw.split("::", 1)[0]
    pure = pathlib.PurePosixPath(raw)
    windows = pathlib.PureWindowsPath(raw)
    if (
        not raw
        or pure.is_absolute()
        or windows.is_absolute()
        or bool(windows.root)
        or bool(windows.drive)
        or ".." in pure.parts
        or "." in pure.parts
        or raw.startswith("-")
    ):
        raise CapabilityCandidateError(
            "invalid_approved_scope",
            "approved capability path is not normalized repository-relative",
        )
    return pure.as_posix()


def _scope_covers(path: str, approved: str) -> bool:
    if path == approved:
        return True
    prefix = approved.rstrip("/")
    if not prefix:
        return False
    if pathlib.PurePosixPath(prefix).suffix == "":
        return path.startswith(prefix + "/")
    return False


def _split_pytest_target(value: object) -> tuple[str, tuple[str, ...]]:
    text = str(value or "").strip()
    parts = text.split("::")
    path = _normalize_repo_path(parts[0])
    selectors = tuple(part.strip() for part in parts[1:] if part.strip())
    return path, selectors


def _test_target_covers(required: str, executed: str) -> bool:
    required_path, required_selectors = _split_pytest_target(required)
    executed_path, executed_selectors = _split_pytest_target(executed)
    if required_path == executed_path:
        if not executed_selectors:
            return True
        if not required_selectors:
            return False
        return required_selectors[: len(executed_selectors)] == executed_selectors
    if executed_selectors:
        return False
    return _scope_covers(required_path, executed_path)


def _completed_steps(
    steps: tuple[WorkStep, ...],
    kind: str,
) -> list[tuple[int, WorkStep]]:
    return [
        (index, step)
        for index, step in enumerate(steps)
        if step.kind == kind and step.state.value == "completed"
    ]


def validate_development_engine_completion_evidence(
    work: WorkItem,
    steps: tuple[WorkStep, ...],
    engine_result: dict[str, object],
) -> None:
    """Bind a COMPLETED specialist claim to canonical WorkStep evidence."""

    ticket_id = str(engine_result.get("ticket_id") or "").strip()
    ticket_digest = str(engine_result.get("ticket_digest") or "").strip().casefold()
    if (
        not ticket_id
        or work.result.get("development_ticket_id") != ticket_id
        or work.result.get("development_ticket_digest") != ticket_digest
    ):
        raise CapabilityCandidateError(
            "development_engine_ticket_drift",
            "DevelopmentEngine completion is not bound to the canonical ticket.",
        )

    candidate_revision = (
        str(engine_result.get("candidate_revision") or "").strip().casefold()
    )
    canonical_commit = str(work.result.get("commit") or "").strip().casefold()
    if not candidate_revision or candidate_revision != canonical_commit:
        raise CapabilityCandidateError(
            "development_engine_candidate_drift",
            "DevelopmentEngine completion does not match the canonical candidate commit.",
        )

    raw_refs = engine_result.get("test_evidence_refs")
    if not isinstance(raw_refs, list) or not raw_refs:
        raise CapabilityCandidateError(
            "development_engine_test_evidence_missing",
            "DevelopmentEngine completion has no canonical test evidence references.",
        )
    valid_test_refs = {
        f"workstep:{step.step_id}"
        for step in steps
        if step.kind == "dev_run_tests"
        and step.state.value == "completed"
        and step.observation.get("passed") is True
    }
    requested_refs = {str(item).strip() for item in raw_refs if str(item).strip()}
    if not requested_refs or not requested_refs.issubset(valid_test_refs):
        raise CapabilityCandidateError(
            "development_engine_test_evidence_drift",
            "DevelopmentEngine completion references non-canonical passing tests.",
        )


def ensure_capability_substrate_requirements_current(
    store: ChangeStore,
    change_id: str,
    architecture: ChangeArtifact,
) -> None:
    dependency_refs = tuple(
        str(item).strip()
        for item in architecture.payload.get("dependency_refs", [])
        if str(item).strip()
    )
    secret_scopes = {
        str(item).strip().casefold()
        for item in architecture.payload.get("secret_scopes", [])
        if str(item).strip()
    }
    discovery_scopes = {
        str(item).strip().casefold()
        for item in architecture.payload.get("discovery_scopes", [])
        if str(item).strip()
    }
    if not (dependency_refs or secret_scopes or discovery_scopes):
        return

    manifest = store.latest_artifact(change_id, MANIFEST_KIND)
    if manifest is None:
        raise CapabilityCandidateError(
            "substrate_manifest_missing",
            "approved dependency/secret/discovery requirements require "
            "Phase-5 manifest evidence",
        )
    substrate = EngineeringSubstrateChangeService(store)
    if not substrate.verification_current(change_id):
        raise CapabilityCandidateError(
            "substrate_verification_missing",
            "approved dependency/secret/discovery requirements require "
            "current satisfied Phase-5 substrate verification",
        )

    if dependency_refs and not tuple(
        manifest.payload.get("dependency_resolution_ids", ())
    ):
        raise CapabilityCandidateError(
            "dependency_provenance_missing",
            "approved dependency requirements have no bound Phase-5 "
            "dependency/provenance lineage",
        )
    manifest_secret_scopes = {
        str(item).strip().casefold()
        for item in manifest.payload.get("secret_scope_requirements", ())
        if str(item).strip()
    }
    if not secret_scopes.issubset(manifest_secret_scopes):
        raise CapabilityCandidateError(
            "secret_scope_evidence_mismatch",
            "Phase-5 manifest does not cover approved secret scopes",
        )
    manifest_discovery_scopes = {
        str(item).strip().casefold()
        for item in manifest.payload.get("discovery_scope_ids", ())
        if str(item).strip()
    }
    if not discovery_scopes.issubset(manifest_discovery_scopes):
        raise CapabilityCandidateError(
            "discovery_scope_evidence_mismatch",
            "Phase-5 manifest does not cover approved discovery scopes",
        )


class CapabilityCandidateVerifier:
    """Re-derive Phase-9 candidate truth from Git, package schema and WorkSteps."""

    def __init__(
        self,
        store: ChangeStore,
        workspace_manager: DevelopmentWorkspaceManager,
        *,
        protected_surface_policy: RepairProtectedSurfacePolicy | None = None,
    ) -> None:
        if not isinstance(store, ChangeStore):
            raise TypeError("store must be ChangeStore")
        if not isinstance(workspace_manager, DevelopmentWorkspaceManager):
            raise TypeError("workspace_manager must be DevelopmentWorkspaceManager")
        self._store = store
        self._workspace_manager = workspace_manager
        self._protected = protected_surface_policy or RepairProtectedSurfacePolicy()

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
            raise CapabilityCandidateError(
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
            raise CapabilityCandidateError(
                "development_stage_missing",
                "current acquisition architecture has no DEVELOPMENT WorkItem",
            )
        work = self._store.work.require(stage.work_id)
        if work.state is not WorkState.COMPLETED:
            raise CapabilityCandidateError(
                "development_not_completed",
                "candidate verification requires completed DEVELOPMENT",
            )
        return change, stage, work, architecture

    def _git_evidence(
        self,
        work: WorkItem,
        architecture: ChangeArtifact,
    ) -> CapabilityCandidateGitEvidence:
        workspace = self._workspace_manager.workspace_for(work.work_id)
        if not workspace.path.is_dir():
            raise CapabilityCandidateError(
                "workspace_missing",
                "capability candidate worktree is unavailable",
            )
        run = self._workspace_manager._run
        try:
            commit = run(workspace.path, "rev-parse", "HEAD").stdout.strip().lower()
            branch = run(workspace.path, "branch", "--show-current").stdout.strip()
            status = run(
                workspace.path,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ).stdout
        except DevelopmentWorkspaceError as exc:
            raise CapabilityCandidateError(
                "git_evidence_unavailable",
                str(exc),
            ) from exc

        if not commit or branch != workspace.branch:
            raise CapabilityCandidateError(
                "branch_identity_mismatch",
                "candidate Git branch identity is not canonical",
            )
        if status.strip():
            raise CapabilityCandidateError(
                "worktree_not_clean",
                "candidate worktree is not clean after local commit",
            )
        if work.result.get("commit") != commit or work.result.get("branch") != branch:
            raise CapabilityCandidateError(
                "work_result_git_mismatch",
                "canonical DEVELOPMENT result differs from committed Git state",
            )

        source_revision = (
            str(architecture.payload.get("source_revision") or "").strip().lower()
        )
        if not source_revision:
            raise CapabilityCandidateError(
                "source_revision_missing",
                "approved acquisition architecture has no source revision",
            )
        ancestor = run(
            workspace.path,
            "merge-base",
            "--is-ancestor",
            source_revision,
            commit,
            check=False,
        )
        if ancestor.returncode != 0:
            raise CapabilityCandidateError(
                "source_revision_drift",
                "candidate is not descended from approved source revision",
            )

        names = run(
            workspace.path,
            "diff",
            "--name-status",
            "-z",
            "--find-renames",
            source_revision,
            commit,
            "--",
        ).stdout
        tokens = names.split("\x00")
        changed: list[str] = []
        index = 0
        while index < len(tokens):
            status_token = tokens[index]
            index += 1
            if not status_token:
                continue
            if index >= len(tokens):
                raise CapabilityCandidateError(
                    "git_diff_malformed",
                    "candidate name-status diff is malformed",
                )
            first_path = tokens[index]
            index += 1
            changed.append(_normalize_repo_path(first_path))
            if status_token.startswith(("R", "C")):
                if index >= len(tokens):
                    raise CapabilityCandidateError(
                        "git_diff_malformed",
                        "candidate rename/copy diff is malformed",
                    )
                changed.append(_normalize_repo_path(tokens[index]))
                index += 1

        changed_paths = tuple(dict.fromkeys(changed))
        if not changed_paths:
            raise CapabilityCandidateError(
                "empty_candidate_diff",
                "completed capability candidate has no changed paths",
            )
        diff_text = run(
            workspace.path,
            "diff",
            "--binary",
            "--no-ext-diff",
            "--no-textconv",
            source_revision,
            commit,
            "--",
        ).stdout
        return CapabilityCandidateGitEvidence(
            branch=branch,
            commit=commit,
            source_revision=source_revision,
            changed_paths=changed_paths,
            diff_digest=hashlib.sha256(diff_text.encode("utf-8")).hexdigest(),
        )

    @staticmethod
    def _approved_scope(
        architecture: ChangeArtifact,
        changed_paths: tuple[str, ...],
    ) -> tuple[str, ...]:
        raw = architecture.payload.get("allowed_paths")
        allowed = tuple(
            dict.fromkeys(
                _normalize_repo_path(item)
                for item in (raw if isinstance(raw, list) else [])
            )
        )
        if not allowed:
            raise CapabilityCandidateError(
                "approved_path_scope_missing",
                "acquisition architecture has no path-level build scope",
            )
        outside = tuple(
            path
            for path in changed_paths
            if not any(_scope_covers(path, scope) for scope in allowed)
        )
        if outside:
            raise CapabilityCandidateError(
                "changed_path_outside_approved_scope",
                "candidate changed paths outside owner-approved acquisition scope: "
                + ", ".join(outside),
            )
        return allowed

    def _protected_surface(
        self,
        changed_paths: tuple[str, ...],
    ) -> ProtectedSurfaceAssessment:
        package_paths = tuple(
            path for path in changed_paths if path.startswith(_PACKAGE_ROOT + "/")
        )
        for path in package_paths:
            pure = pathlib.PurePosixPath(path)
            if (
                len(pure.parts) != 2
                or pure.parts[0] != _PACKAGE_ROOT
                or pure.suffix.casefold() != ".json"
            ):
                raise CapabilityCandidateError(
                    "unsafe_package_descriptor_path",
                    "capability package descriptors must be direct JSON files under "
                    "capability_packages/",
                )
        ordinary = tuple(path for path in changed_paths if path not in package_paths)
        if not ordinary:
            return ProtectedSurfaceAssessment(
                policy_id=self._protected.policy_id,
                policy_version=self._protected.policy_version,
                verdict=ProtectedSurfaceVerdict.CLEAR,
                protected=(),
                unknown_paths=(),
                clear_paths=package_paths,
            )
        assessment = self._protected.assess(ordinary)
        if assessment.verdict is ProtectedSurfaceVerdict.PROTECTED_CHANGE_REQUIRED:
            raise CapabilityCandidateError(
                "protected_change_required",
                "Phase-9 capability candidate touched governance/security surfaces",
            )
        if assessment.verdict is ProtectedSurfaceVerdict.UNKNOWN:
            raise CapabilityCandidateError(
                "protected_surface_unknown",
                "Phase-9 capability candidate touched an unclassified repository surface",
            )
        return ProtectedSurfaceAssessment(
            policy_id=assessment.policy_id,
            policy_version=assessment.policy_version,
            verdict=ProtectedSurfaceVerdict.CLEAR,
            protected=(),
            unknown_paths=(),
            clear_paths=tuple(sorted((*assessment.clear_paths, *package_paths))),
        )

    @staticmethod
    def _verification_step(
        work: WorkItem,
        steps: tuple[WorkStep, ...],
        required_targets: tuple[str, ...],
    ) -> WorkStep:
        writes = _completed_steps(steps, "dev_write_file")
        if not writes:
            raise CapabilityCandidateError(
                "no_source_edit",
                "capability candidate has no completed source edit",
            )
        last_write = writes[-1][0]
        passing = [
            (index, step)
            for index, step in _completed_steps(steps, "dev_run_tests")
            if index > last_write and step.observation.get("passed") is True
        ]
        if not passing:
            raise CapabilityCandidateError(
                "post_edit_tests_missing",
                "capability candidate lacks passing sandbox tests after latest edit",
            )
        if not required_targets:
            raise CapabilityCandidateError(
                "development_test_targets_missing",
                "approved acquisition architecture has no development test targets",
            )
        covered: set[str] = set()
        for _, step in passing:
            raw_targets = step.input_data.get("targets")
            executed_targets = (
                ("tests",)
                if raw_targets is None or raw_targets == ()
                else tuple(raw_targets)
            )
            for required in required_targets:
                if any(
                    _test_target_covers(required, str(executed))
                    for executed in executed_targets
                ):
                    covered.add(required)
        missing = tuple(target for target in required_targets if target not in covered)
        if missing:
            raise CapabilityCandidateError(
                "required_development_tests_missing",
                "approved development test targets were not exercised after latest edit: "
                + ", ".join(missing),
            )
        test_index, test_step = passing[-1]
        if (
            test_step.observation.get("network") != "disabled"
            or test_step.observation.get("workspace") != "read_only"
            or test_step.observation.get("sandbox") != "docker"
            or not str(test_step.observation.get("sandbox_profile") or "").strip()
            or isinstance(test_step.observation.get("sandbox_profile_version"), bool)
            or not isinstance(test_step.observation.get("sandbox_profile_version"), int)
            or int(test_step.observation["sandbox_profile_version"]) < 1
        ):
            raise CapabilityCandidateError(
                "sandbox_verification_invalid",
                "candidate tests were not bound to approved read-only offline sandbox",
            )
        diffs = [
            (index, step)
            for index, step in _completed_steps(steps, "dev_diff")
            if index > test_index
        ]
        if not diffs:
            raise CapabilityCandidateError(
                "final_diff_missing",
                "candidate requires final diff inspection after sandbox tests",
            )
        commits = [
            step
            for index, step in _completed_steps(steps, "dev_commit")
            if index > diffs[-1][0]
            and step.observation.get("committed") is True
            and step.observation.get("clean") is True
        ]
        if not commits:
            raise CapabilityCandidateError(
                "clean_commit_missing",
                "candidate requires a clean local commit after final diff",
            )
        verification = work.result.get("verification")
        if not isinstance(verification, dict) or verification.get("passed") is not True:
            raise CapabilityCandidateError(
                "canonical_verification_missing",
                "canonical DEVELOPMENT result does not record passing verification",
            )
        return test_step

    def _require_substrate_evidence(
        self,
        change_id: str,
        architecture: ChangeArtifact,
    ) -> None:
        ensure_capability_substrate_requirements_current(
            self._store,
            change_id,
            architecture,
        )

    def _package(
        self,
        work: WorkItem,
        architecture: ChangeArtifact,
    ) -> tuple[str, CapabilityPackageV1]:
        workspace = self._workspace_manager.workspace_for(work.work_id)
        root = workspace.path / _PACKAGE_ROOT
        if root.is_symlink() or not root.is_dir():
            raise CapabilityCandidateError(
                "package_descriptor_missing",
                "candidate has no safe capability_packages directory",
            )
        files = tuple(
            path
            for path in sorted(root.iterdir(), key=lambda item: item.name)
            if not path.name.startswith(".") and path.suffix.casefold() == ".json"
        )
        if len(files) > _MAX_PACKAGE_FILES:
            raise CapabilityCandidateError(
                "package_descriptor_limit",
                "candidate exceeds package descriptor scan limit",
            )
        expected_id = str(architecture.payload.get("proposed_package_id") or "").strip()
        expected_version = str(
            architecture.payload.get("proposed_package_version") or ""
        ).strip()
        expected_capability = str(
            architecture.payload.get("proposed_capability_id") or ""
        ).strip()
        matches: list[tuple[str, CapabilityPackageV1]] = []
        for path in files:
            if path.is_symlink() or not path.is_file():
                raise CapabilityCandidateError(
                    "unsafe_package_descriptor",
                    "candidate package descriptor is not a regular file",
                )
            size = path.stat().st_size
            if size <= 0 or size > _MAX_PACKAGE_BYTES:
                raise CapabilityCandidateError(
                    "package_descriptor_size",
                    "candidate package descriptor has invalid size",
                )
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise TypeError("descriptor is not an object")
                package = parse_capability_package_v1(raw)
            except (OSError, UnicodeError, ValueError, TypeError) as exc:
                raise CapabilityCandidateError(
                    "package_descriptor_invalid",
                    f"candidate package descriptor failed v1 contract: {path.name}",
                ) from exc
            if (
                package.package_id == expected_id
                and package.package_version == expected_version
            ):
                matches.append(
                    (
                        path.relative_to(workspace.path).as_posix(),
                        package,
                    )
                )
        if len(matches) != 1:
            raise CapabilityCandidateError(
                "package_identity_ambiguous",
                "candidate must contain exactly one descriptor for approved package "
                f"{expected_id}@{expected_version}",
            )
        package_path, package = matches[0]
        if package.capability_id != expected_capability:
            raise CapabilityCandidateError(
                "package_capability_mismatch",
                "candidate package capability does not match approved architecture",
            )
        if package.package_kind is not CapabilityPackageKind.EXTENSION_SOURCE:
            raise CapabilityCandidateError(
                "package_kind_invalid",
                "owner-acquired capabilities must use extension_source packages",
            )
        if (
            package.runtime_api_id != CAPABILITY_RUNTIME_API_ID
            or package.runtime_api_version != CAPABILITY_RUNTIME_API_VERSION_V1
        ):
            raise CapabilityCandidateError(
                "runtime_api_mismatch",
                "candidate package does not target the accepted capability runtime API",
            )
        return package_path, package

    def verify_and_persist(self, change_id: str) -> CapabilityCandidateVerification:
        change, stage, work, architecture = self._require_development(change_id)
        del change, stage
        git = self._git_evidence(work, architecture)
        self._approved_scope(architecture, git.changed_paths)
        protected = self._protected_surface(git.changed_paths)
        self._require_substrate_evidence(change_id, architecture)
        raw_targets = architecture.payload.get("verification_targets")
        required_targets = tuple(
            str(item).strip()
            for item in (raw_targets if isinstance(raw_targets, list) else [])
            if str(item).strip()
        )
        test_step = self._verification_step(
            work,
            self._store.work.list_steps(work.work_id),
            required_targets,
        )
        package_path, package = self._package(work, architecture)
        if package_path not in git.changed_paths:
            raise CapabilityCandidateError(
                "package_descriptor_not_changed",
                "approved capability package descriptor is absent from candidate diff",
            )

        plan_id = str(architecture.payload.get("plan_id") or "").strip()
        plan_digest = str(architecture.payload.get("plan_digest") or "").strip()
        if not plan_id or len(plan_digest) != 64:
            raise CapabilityCandidateError(
                "plan_binding_missing",
                "approved acquisition plan identity/digest is missing",
            )
        verification_contracts = tuple(
            sorted(
                {
                    str(item).strip().casefold()
                    for item in architecture.payload.get(
                        "verification_contract_ids",
                        [],
                    )
                    if str(item).strip()
                }
            )
        )
        if not verification_contracts:
            raise CapabilityCandidateError(
                "verification_contracts_missing",
                "approved capability candidate has no verification contracts",
            )
        owner_acceptance = tuple(
            sorted(
                {
                    str(item).strip().casefold()
                    for item in architecture.payload.get(
                        "owner_acceptance_contract_ids",
                        [],
                    )
                    if str(item).strip()
                }
            )
        )

        candidate = CapabilityCandidateEvidenceV1(
            architecture_artifact_id=architecture.artifact_id,
            architecture_digest=architecture.digest,
            plan_id=plan_id,
            plan_digest=plan_digest,
            development_work_id=work.work_id,
            branch=git.branch,
            commit=git.commit,
            source_revision=git.source_revision,
            changed_paths=git.changed_paths,
            diff_digest=git.diff_digest,
            package_path=package_path,
            package_id=package.package_id,
            package_version=package.package_version,
            package_digest=package.digest,
            capability_id=package.capability_id,
            manifest_id=package.manifest_id,
            manifest_version=package.manifest_version,
            manifest_digest=package.manifest_digest,
            sandbox_profile=str(test_step.observation["sandbox_profile"]),
            sandbox_profile_version=int(
                test_step.observation["sandbox_profile_version"]
            ),
            protected_surface_policy_id=protected.policy_id,
            protected_surface_policy_version=protected.policy_version,
            verification_contract_ids=verification_contracts,
            owner_acceptance_contract_ids=owner_acceptance,
        )
        candidate_payload = {
            "candidate_id": candidate.candidate_id,
            **candidate.canonical_payload(),
            "digest": candidate.digest,
            "protected_surface": protected.to_payload(),
        }
        candidate_artifact = self._persist_if_changed(
            self._store,
            change_id=change_id,
            kind="capability_candidate",
            payload=candidate_payload,
        )
        acceptance_payload = {
            "work_id": work.work_id,
            "result": work.result,
            "candidate_artifact_id": candidate_artifact.artifact_id,
            "candidate_artifact_digest": candidate_artifact.digest,
            "candidate": candidate_payload,
            "protected_surface": protected.to_payload(),
        }
        acceptance_artifact = self._persist_if_changed(
            self._store,
            change_id=change_id,
            kind="acceptance",
            payload=acceptance_payload,
        )
        return CapabilityCandidateVerification(
            candidate=candidate,
            candidate_artifact=candidate_artifact,
            acceptance_artifact=acceptance_artifact,
            protected_surface=protected,
        )


def ensure_capability_candidate_acceptance_current(
    store: ChangeStore,
    change_id: str,
) -> ChangeArtifact:
    change = store.require(change_id)
    if (
        change.process_key != OWNER_CAPABILITY_ACQUISITION_PROCESS.key
        or change.process_version != OWNER_CAPABILITY_ACQUISITION_PROCESS.version
    ):
        raise CapabilityCandidateError(
            "wrong_process",
            "change is not Phase-9 capability acquisition",
        )
    architecture = ensure_capability_acquisition_architecture_current(store, change_id)
    candidate = store.latest_artifact(change_id, "capability_candidate")
    acceptance = store.latest_artifact(change_id, "acceptance")
    verification = store.latest_artifact(
        change_id,
        "capability_candidate_verification",
    )
    if candidate is None or acceptance is None or verification is None:
        raise CapabilityCandidateError(
            "candidate_evidence_missing",
            "Phase-9 acceptance requires current candidate verification evidence",
        )
    if verification.payload.get("passed") is not True:
        raise CapabilityCandidateError(
            "candidate_verification_failed",
            "latest Phase-9 candidate verification did not pass",
        )
    if (
        verification.payload.get("candidate_artifact_id") != candidate.artifact_id
        or verification.payload.get("candidate_artifact_digest") != candidate.digest
        or verification.payload.get("acceptance_artifact_id") != acceptance.artifact_id
        or verification.payload.get("acceptance_artifact_digest") != acceptance.digest
    ):
        raise CapabilityCandidateError(
            "candidate_evidence_stale",
            "Phase-9 candidate verification references stale artifacts",
        )
    payload = candidate.payload
    candidate_verification_contracts = tuple(
        sorted(
            str(item).strip().casefold()
            for item in payload.get("verification_contract_ids", ())
            if str(item).strip()
        )
    )
    architecture_verification_contracts = tuple(
        sorted(
            str(item).strip().casefold()
            for item in architecture.payload.get("verification_contract_ids", ())
            if str(item).strip()
        )
    )
    candidate_owner_acceptance = tuple(
        sorted(
            str(item).strip().casefold()
            for item in payload.get("owner_acceptance_contract_ids", ())
            if str(item).strip()
        )
    )
    architecture_owner_acceptance = tuple(
        sorted(
            str(item).strip().casefold()
            for item in architecture.payload.get("owner_acceptance_contract_ids", ())
            if str(item).strip()
        )
    )
    if (
        payload.get("architecture_artifact_id") != architecture.artifact_id
        or payload.get("architecture_digest") != architecture.digest
        or payload.get("plan_id") != architecture.payload.get("plan_id")
        or payload.get("plan_digest") != architecture.payload.get("plan_digest")
        or payload.get("package_id") != architecture.payload.get("proposed_package_id")
        or payload.get("package_version")
        != architecture.payload.get("proposed_package_version")
        or payload.get("capability_id")
        != architecture.payload.get("proposed_capability_id")
        or candidate_verification_contracts != architecture_verification_contracts
        or candidate_owner_acceptance != architecture_owner_acceptance
    ):
        raise CapabilityCandidateError(
            "candidate_architecture_drift",
            "Phase-9 candidate no longer matches approved acquisition architecture",
        )
    work_id = str(acceptance.payload.get("work_id") or "").strip()
    stage = store.stage_for_work(work_id)
    if (
        stage is None
        or stage.change_id != change_id
        or stage.stage_key
        != OWNER_CAPABILITY_ACQUISITION_PROCESS.development_stage.stage_key
        or stage.plan_artifact_id != architecture.artifact_id
    ):
        raise CapabilityCandidateError(
            "candidate_development_binding_invalid",
            "Phase-9 acceptance is not bound to current DEVELOPMENT stage",
        )
    work = store.work.require(work_id)
    if (
        work.state is not WorkState.COMPLETED
        or acceptance.payload.get("result") != work.result
        or work.result.get("commit") != payload.get("commit")
        or work.result.get("branch") != payload.get("branch")
        or not isinstance(work.result.get("verification"), dict)
        or work.result["verification"].get("passed") is not True
    ):
        raise CapabilityCandidateError(
            "candidate_work_result_drift",
            "Phase-9 acceptance no longer matches canonical DEVELOPMENT result",
        )
    return acceptance


class CapabilityAcquisitionDevelopmentCompletionHandler:
    """Fail closed unless Phase-9 DEVELOPMENT produces a valid package candidate."""

    process_key = OWNER_CAPABILITY_ACQUISITION_PROCESS.key
    process_version = OWNER_CAPABILITY_ACQUISITION_PROCESS.version

    def __init__(
        self,
        store: ChangeStore,
        workspace_manager: DevelopmentWorkspaceManager,
    ) -> None:
        self._store = store
        self._verifier = CapabilityCandidateVerifier(store, workspace_manager)

    def complete(
        self,
        *,
        change: EngineeringChange,
        stage: ChangeStage,
        work: WorkItem,
    ) -> ChangeState | None:
        engine_result = development_result_from_work(work)
        if engine_result is not None:
            engine_step = next(
                (
                    item
                    for item in reversed(self._store.work.list_steps(work.work_id))
                    if item.kind == PHASE9_DEVELOPMENT_ENGINE_ACTION
                    and item.state.value == "completed"
                    and item.observation.get("development_result") == engine_result
                ),
                None,
            )
            if engine_step is None:
                payload = {
                    "passed": False,
                    "reason_code": "development_engine_result_drift",
                    "message": (
                        "canonical DEVELOPMENT result is not bound to an exact "
                        "DevelopmentEngine WorkStep"
                    ),
                }
                latest = self._store.latest_artifact(
                    change.change_id,
                    "capability_candidate_verification",
                )
                if latest is None or latest.payload != payload:
                    self._store.add_artifact(
                        change.change_id,
                        kind="capability_candidate_verification",
                        payload=payload,
                    )
                return ChangeState.FAILED

            outcome_payload: dict[str, object] = {
                "schema": "phase9_development_engine_outcome.v1",
                "development_work_id": work.work_id,
                "development_attempt": stage.attempt,
                "architecture_artifact_id": stage.plan_artifact_id,
                "engine_result": engine_result,
                "engine_step_id": engine_step.step_id,
            }
            latest_outcome = self._store.latest_artifact(
                change.change_id,
                "development_engine_outcome",
            )
            if latest_outcome is None or latest_outcome.payload != outcome_payload:
                self._store.add_artifact(
                    change.change_id,
                    kind="development_engine_outcome",
                    payload=outcome_payload,
                )

            revision_disposition = phase9_revision_disposition(engine_result)
            if revision_disposition is not None:
                reason = " ".join(
                    str(
                        engine_result.get("reason")
                        or engine_result.get("summary")
                        or "approved architecture requires revision"
                    ).split()
                )
                if revision_disposition is DevelopmentDisposition.NEEDS_DEPENDENCY:
                    requested = tuple(
                        str(item).strip()
                        for item in engine_result.get("requested_dependencies", ())
                        if str(item).strip()
                    )
                    if requested:
                        reason += "; requested dependencies: " + ", ".join(requested)
                self._store.request_architecture_revision_for_work(
                    work.work_id,
                    reason=reason,
                )
                return ChangeState.RESEARCHING

            try:
                disposition = DevelopmentDisposition(
                    str(engine_result.get("disposition"))
                )
            except ValueError:
                return ChangeState.FAILED
            if disposition is DevelopmentDisposition.FAILED:
                return ChangeState.FAILED
            if disposition is DevelopmentDisposition.BLOCKED_RESOURCE:
                # Resource blockers must remain on the WorkItem and never complete
                # the governed development stage.
                return ChangeState.FAILED
            if disposition is not DevelopmentDisposition.COMPLETED:
                return ChangeState.FAILED

        try:
            if engine_result is not None:
                disposition = DevelopmentDisposition(
                    str(engine_result.get("disposition"))
                )
                if disposition is DevelopmentDisposition.COMPLETED:
                    validate_development_engine_completion_evidence(
                        work,
                        self._store.work.list_steps(work.work_id),
                        engine_result,
                    )
            result = self._verifier.verify_and_persist(change.change_id)
        except CapabilityCandidateError as exc:
            payload = {
                "passed": False,
                "reason_code": exc.reason_code,
                "message": str(exc),
            }
            latest = self._store.latest_artifact(
                change.change_id,
                "capability_candidate_verification",
            )
            if latest is None or latest.payload != payload:
                self._store.add_artifact(
                    change.change_id,
                    kind="capability_candidate_verification",
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
            "package_id": result.candidate.package_id,
            "package_version": result.candidate.package_version,
            "package_digest": result.candidate.package_digest,
            "protected_surface_verdict": result.protected_surface.verdict.value,
        }
        latest = self._store.latest_artifact(
            change.change_id,
            "capability_candidate_verification",
        )
        if latest is None or latest.payload != payload:
            self._store.add_artifact(
                change.change_id,
                kind="capability_candidate_verification",
                payload=payload,
            )
        return None
