"""Final Phase-6 source-repair candidate verification and owner-review evidence."""

from __future__ import annotations

import hashlib
import pathlib
from dataclasses import dataclass

from jarvis.engineering_change.models import (
    ChangeArtifact,
    ChangeConflict,
    ChangeStage,
    ChangeState,
    EngineeringChange,
)
from jarvis.engineering_change.store import ChangeStore
from jarvis.work.development import (
    DevelopmentWorkspaceError,
    DevelopmentWorkspaceManager,
)
from jarvis.work.models import WorkItem, WorkState, WorkStep

from .architecture import ensure_incident_repair_architecture_current
from .models import ProtectedSurfaceVerdict, SourceRepairCandidateEvidence
from .process import UNKNOWN_INCIDENT_REPAIR_PROCESS
from .protected_surfaces import (
    ProtectedSurfaceAssessment,
    RepairProtectedSurfacePolicy,
)


class SourceRepairCandidateError(ChangeConflict):
    """Final repair evidence failed a deterministic Phase-6 candidate gate."""

    def __init__(self, reason_code: str, message: str) -> None:
        code = str(reason_code).strip().casefold()
        text = str(message).strip()
        if not code or not text:
            raise ValueError("candidate failure requires reason code and message")
        super().__init__(text)
        self.reason_code = code


@dataclass(frozen=True, slots=True)
class CandidateGitEvidence:
    branch: str
    commit: str
    source_revision: str
    changed_paths: tuple[str, ...]
    diff_digest: str


@dataclass(frozen=True, slots=True)
class CandidateVerification:
    candidate: SourceRepairCandidateEvidence
    candidate_artifact: ChangeArtifact
    acceptance_artifact: ChangeArtifact
    protected_surface: ProtectedSurfaceAssessment


def _normalized_repo_path(value: object) -> str:
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
        or raw.startswith("-")
    ):
        raise SourceRepairCandidateError(
            "invalid_approved_scope",
            "approved repair path is not repository-relative",
        )
    return pure.as_posix().removeprefix("./")


def _scope_covers(path: str, approved: str) -> bool:
    if path == approved:
        return True
    prefix = approved.rstrip("/")
    if not prefix:
        return False
    # Explicit directory-like approval (for example "tests") covers descendants.
    if pathlib.PurePosixPath(prefix).suffix == "":
        return path.startswith(prefix + "/")
    return False


def _split_pytest_target(value: object) -> tuple[str, tuple[str, ...]]:
    text = str(value or "").strip()
    parts = text.split("::")
    path = _normalized_repo_path(parts[0])
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
    steps: tuple[WorkStep, ...], kind: str
) -> list[tuple[int, WorkStep]]:
    return [
        (index, step)
        for index, step in enumerate(steps)
        if step.kind == kind and step.state.value == "completed"
    ]


class SourceRepairCandidateVerifier:
    """Re-derive candidate truth from canonical WorkSteps and committed Git state."""

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

    def _require_phase6_development(
        self,
        change_id: str,
    ) -> tuple[EngineeringChange, ChangeStage, WorkItem, ChangeArtifact]:
        change = self._store.require(change_id)
        if (
            change.process_key != UNKNOWN_INCIDENT_REPAIR_PROCESS.key
            or change.process_version != UNKNOWN_INCIDENT_REPAIR_PROCESS.version
        ):
            raise SourceRepairCandidateError(
                "wrong_process",
                "candidate verifier only accepts unknown_incident_repair.v1",
            )
        architecture = ensure_incident_repair_architecture_current(
            self._store,
            change_id,
        )
        stage = next(
            (
                item
                for item in reversed(self._store.list_stages(change_id))
                if item.stage_key
                == UNKNOWN_INCIDENT_REPAIR_PROCESS.development_stage.stage_key
                and item.plan_artifact_id == architecture.artifact_id
            ),
            None,
        )
        if stage is None:
            raise SourceRepairCandidateError(
                "development_stage_missing",
                "current repair architecture has no development WorkItem",
            )
        work = self._store.work.require(stage.work_id)
        if work.state is not WorkState.COMPLETED:
            raise SourceRepairCandidateError(
                "development_not_completed",
                "candidate verification requires completed development work",
            )
        return change, stage, work, architecture

    def _git_evidence(
        self,
        work: WorkItem,
        architecture: ChangeArtifact,
    ) -> CandidateGitEvidence:
        workspace = self._workspace_manager.workspace_for(work.work_id)
        if not workspace.path.is_dir():
            raise SourceRepairCandidateError(
                "workspace_missing",
                "development worktree is unavailable for candidate verification",
            )
        run = self._workspace_manager._run
        try:
            commit = run(workspace.path, "rev-parse", "HEAD").stdout.strip().lower()
            branch = run(
                workspace.path,
                "branch",
                "--show-current",
            ).stdout.strip()
            status = run(
                workspace.path,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ).stdout
        except DevelopmentWorkspaceError as exc:
            raise SourceRepairCandidateError(
                "git_evidence_unavailable",
                str(exc),
            ) from exc

        if not commit or branch != workspace.branch:
            raise SourceRepairCandidateError(
                "branch_identity_mismatch",
                "candidate Git branch identity is not canonical",
            )
        if status.strip():
            raise SourceRepairCandidateError(
                "worktree_not_clean",
                "candidate worktree is not clean after local commit",
            )
        if work.result.get("commit") != commit or work.result.get("branch") != branch:
            raise SourceRepairCandidateError(
                "work_result_git_mismatch",
                "canonical WorkItem result differs from committed Git state",
            )

        source_revision = (
            str(architecture.payload.get("source_revision") or "").strip().lower()
        )
        if not source_revision:
            raise SourceRepairCandidateError(
                "source_revision_missing",
                "approved repair architecture has no source revision",
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
            raise SourceRepairCandidateError(
                "source_revision_drift",
                "candidate commit is not descended from approved source revision",
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
                raise SourceRepairCandidateError(
                    "git_diff_malformed",
                    "candidate name-status diff is malformed",
                )
            first_path = tokens[index]
            index += 1
            changed.append(self._protected.normalize_path(first_path))
            if status_token.startswith(("R", "C")):
                if index >= len(tokens):
                    raise SourceRepairCandidateError(
                        "git_diff_malformed",
                        "candidate rename/copy diff is malformed",
                    )
                second_path = tokens[index]
                index += 1
                changed.append(self._protected.normalize_path(second_path))

        changed_paths = tuple(dict.fromkeys(changed))
        if not changed_paths:
            raise SourceRepairCandidateError(
                "empty_candidate_diff",
                "completed repair candidate has no changed paths",
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
        diff_digest = hashlib.sha256(diff_text.encode("utf-8")).hexdigest()
        return CandidateGitEvidence(
            branch=branch,
            commit=commit,
            source_revision=source_revision,
            changed_paths=changed_paths,
            diff_digest=diff_digest,
        )

    @staticmethod
    def _verify_workstep_order(
        work: WorkItem,
        steps: tuple[WorkStep, ...],
        verification_targets: tuple[str, ...],
    ) -> tuple[WorkStep, int]:
        writes = _completed_steps(steps, "dev_write_file")
        if not writes:
            raise SourceRepairCandidateError(
                "no_source_edit",
                "repair candidate has no completed source edit",
            )
        last_write_index = writes[-1][0]

        passing = [
            (index, step)
            for index, step in _completed_steps(steps, "dev_run_tests")
            if index > last_write_index and step.observation.get("passed") is True
        ]
        if not passing:
            raise SourceRepairCandidateError(
                "post_edit_tests_missing",
                "repair candidate has no passing sandboxed tests after latest edit",
            )

        covered: set[str] = set()
        for _, step in passing:
            raw_targets = step.input_data.get("targets")
            targets = (
                ["tests"] if raw_targets is None or raw_targets == () else raw_targets
            )
            if not isinstance(targets, list | tuple):
                continue
            for required in verification_targets:
                if any(
                    _test_target_covers(required, str(executed)) for executed in targets
                ):
                    covered.add(required)
        missing = tuple(
            target for target in verification_targets if target not in covered
        )
        if missing:
            raise SourceRepairCandidateError(
                "required_verification_missing",
                "approved verification targets were not exercised after latest edit: "
                + ", ".join(missing),
            )

        last_passing_index, last_passing = passing[-1]
        diffs = [
            (index, step)
            for index, step in _completed_steps(steps, "dev_diff")
            if index > last_passing_index
        ]
        if not diffs:
            raise SourceRepairCandidateError(
                "final_diff_missing",
                "repair candidate requires final diff inspection after passing tests",
            )
        last_diff_index = diffs[-1][0]

        commits = [
            (index, step)
            for index, step in _completed_steps(steps, "dev_commit")
            if index > last_diff_index
            and step.observation.get("committed") is True
            and step.observation.get("clean") is True
        ]
        if not commits:
            raise SourceRepairCandidateError(
                "clean_commit_missing",
                "repair candidate requires a clean local commit after final diff",
            )
        canonical_verification = work.result.get("verification")
        if (
            not isinstance(canonical_verification, dict)
            or canonical_verification.get("passed") is not True
        ):
            raise SourceRepairCandidateError(
                "canonical_verification_missing",
                "canonical development result does not record passing verification",
            )

        profile = last_passing.observation.get("sandbox_profile")
        profile_version = last_passing.observation.get("sandbox_profile_version")
        if (
            not isinstance(profile, str)
            or not profile.strip()
            or isinstance(profile_version, bool)
            or not isinstance(profile_version, int)
            or profile_version < 1
            or last_passing.observation.get("network") != "disabled"
            or last_passing.observation.get("workspace") != "read_only"
        ):
            raise SourceRepairCandidateError(
                "sandbox_verification_invalid",
                "post-edit verification is not bound to an approved read-only offline sandbox",
            )
        return last_passing, commits[-1][0]

    @staticmethod
    def _verify_approved_scope(
        architecture: ChangeArtifact,
        changed_paths: tuple[str, ...],
    ) -> tuple[str, ...]:
        raw_allowed = architecture.payload.get("allowed_paths")
        raw_targets = architecture.payload.get("verification_targets")
        allowed = tuple(
            dict.fromkeys(
                _normalized_repo_path(item)
                for item in (
                    *(raw_allowed if isinstance(raw_allowed, list) else []),
                    *(raw_targets if isinstance(raw_targets, list) else []),
                )
            )
        )
        if not allowed:
            raise SourceRepairCandidateError(
                "approved_path_scope_missing",
                "repair architecture has no path-level approved scope",
            )
        outside = tuple(
            path
            for path in changed_paths
            if not any(_scope_covers(path, scope) for scope in allowed)
        )
        if outside:
            raise SourceRepairCandidateError(
                "changed_path_outside_approved_scope",
                "candidate changed paths outside owner-approved architecture: "
                + ", ".join(outside),
            )
        return allowed

    def verify_and_persist(self, change_id: str) -> CandidateVerification:
        change, stage, work, architecture = self._require_phase6_development(change_id)
        del change, stage
        git = self._git_evidence(work, architecture)
        protected = self._protected.assess(git.changed_paths)
        if protected.verdict is ProtectedSurfaceVerdict.PROTECTED_CHANGE_REQUIRED:
            raise SourceRepairCandidateError(
                "protected_change_required",
                "ordinary Phase-6 repair touched protected governance/security surfaces",
            )
        if protected.verdict is ProtectedSurfaceVerdict.UNKNOWN:
            raise SourceRepairCandidateError(
                "protected_surface_unknown",
                "ordinary Phase-6 repair touched an unclassified repository surface",
            )
        self._verify_approved_scope(architecture, git.changed_paths)

        targets = tuple(
            dict.fromkeys(
                str(item).strip()
                for item in architecture.payload.get("verification_targets", [])
                if str(item).strip()
            )
        )
        if not targets:
            raise SourceRepairCandidateError(
                "verification_targets_missing",
                "repair architecture has no verification targets",
            )
        steps = self._store.work.list_steps(work.work_id)
        last_passing, _ = self._verify_workstep_order(
            work,
            steps,
            targets,
        )

        diagnosis_artifact = self._store.latest_artifact(change_id, "diagnosis")
        if diagnosis_artifact is None:
            raise SourceRepairCandidateError(
                "diagnosis_missing",
                "repair candidate has no current diagnosis artifact",
            )
        diagnosis = diagnosis_artifact.payload.get("diagnosis")
        if not isinstance(diagnosis, dict):
            raise SourceRepairCandidateError(
                "diagnosis_malformed",
                "current diagnosis artifact is malformed",
            )

        candidate = SourceRepairCandidateEvidence.create(
            incident_id=str(diagnosis.get("incident_id") or ""),
            diagnosis_id=str(diagnosis.get("diagnosis_id") or ""),
            diagnosis_digest=str(diagnosis.get("digest") or ""),
            architecture_artifact_id=architecture.artifact_id,
            architecture_digest=architecture.digest,
            development_work_id=work.work_id,
            branch=git.branch,
            commit=git.commit,
            changed_paths=git.changed_paths,
            diff_digest=git.diff_digest,
            verification_targets=targets,
            sandbox_profile=str(last_passing.observation["sandbox_profile"]),
            sandbox_profile_version=int(
                last_passing.observation["sandbox_profile_version"]
            ),
            protected_surface_verdict=protected.verdict,
            now_epoch=work.updated_at.timestamp(),
        )
        candidate_payload: dict[str, object] = {
            "candidate_id": candidate.candidate_id,
            **candidate.canonical_payload(),
            "digest": candidate.digest,
            "source_revision": git.source_revision,
            "protected_surface": protected.to_payload(),
        }
        candidate_artifact = self._persist_if_changed(
            self._store,
            change_id=change_id,
            kind="source_repair_candidate",
            payload=candidate_payload,
        )
        acceptance_payload: dict[str, object] = {
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
        return CandidateVerification(
            candidate=candidate,
            candidate_artifact=candidate_artifact,
            acceptance_artifact=acceptance_artifact,
            protected_surface=protected,
        )


class IncidentRepairDevelopmentCompletionHandler:
    """Fail closed unless completed Phase-6 DEVELOPMENT produces a valid candidate."""

    process_key = UNKNOWN_INCIDENT_REPAIR_PROCESS.key
    process_version = UNKNOWN_INCIDENT_REPAIR_PROCESS.version

    def __init__(
        self,
        store: ChangeStore,
        workspace_manager: DevelopmentWorkspaceManager,
    ) -> None:
        self._store = store
        self._verifier = SourceRepairCandidateVerifier(
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
        except SourceRepairCandidateError as exc:
            payload = {
                "passed": False,
                "reason_code": exc.reason_code,
                "message": str(exc),
            }
            latest = self._store.latest_artifact(
                change.change_id,
                "source_repair_verification",
            )
            if latest is None or latest.payload != payload:
                self._store.add_artifact(
                    change.change_id,
                    kind="source_repair_verification",
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
            "protected_surface_verdict": result.protected_surface.verdict.value,
        }
        latest = self._store.latest_artifact(
            change.change_id,
            "source_repair_verification",
        )
        if latest is None or latest.payload != payload:
            self._store.add_artifact(
                change.change_id,
                kind="source_repair_verification",
                payload=payload,
            )
        return None
