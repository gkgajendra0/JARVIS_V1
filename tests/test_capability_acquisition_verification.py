from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from jarvis.capabilities.models import CapabilityCatalog
from jarvis.capability_acquisition.admission import CapabilityAcquisitionCoordinator
from jarvis.capability_acquisition.architecture import (
    CapabilityAcquisitionArchitectureError,
    CapabilityAcquisitionDevelopmentRevisionResolver,
    CapabilityAcquisitionSourceCompletionHandler,
)
from jarvis.capability_acquisition.artifacts import (
    candidate_payload,
    evaluation_payload,
    plan_payload,
    resolution_payload,
)
from jarvis.capability_acquisition.models import (
    CapabilityAcquisitionPlanV1,
    OwnerCapabilityGoalV1,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_acquisition.resolver import CapabilityAcquisitionResolver
from jarvis.capability_acquisition.runtime_context import (
    StaticAcquisitionContextProvider,
)
from jarvis.capability_acquisition.source import (
    AcquisitionContextV1,
    CapabilitySourceRegistry,
)
from jarvis.capability_acquisition.standard_sources import (
    CustomBuildCapabilitySourceAdapter,
)
from jarvis.capability_acquisition.verification import (
    CapabilityAcquisitionDevelopmentCompletionHandler,
    CapabilityCandidateError,
    CapabilityCandidateVerifier,
)
from jarvis.engineering_change import ChangeConflict, ChangeState, ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.work.development import DevelopmentWorkspaceManager
from jarvis.work.models import WorkItem, WorkPriority, WorkState, WorkStep, WorkType
from jarvis.work.store import SQLiteWorkStore

PACKAGE_ID = "tv.control.custom"
CAPABILITY_ID = "tv.control"
PACKAGE_VERSION = "1.0.0"


class Backend:
    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        del priority
        self.submitted.append(work_id)
        return work_id


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [shutil.which("git") or "git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


@pytest.fixture()
def acquisition_repo(tmp_path: Path) -> tuple[Path, str]:
    if shutil.which("git") is None:
        pytest.skip("Git is required for capability candidate tests")
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "jarvis-tests@example.invalid")
    _git(root, "config", "user.name", "JARVIS Tests")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base release")
    revision = _git(root, "rev-parse", "HEAD").stdout.strip().lower()
    return root, revision


def _goal() -> OwnerCapabilityGoalV1:
    return OwnerCapabilityGoalV1.create(
        request="Get TV power control capability",
        requested_capability="TV control",
        required_operations=("power",),
        target_hints=("living-room",),
        source_session_id="owner-session",
        source_turn_id="owner-turn",
        now_epoch=100.0,
    )


def _context() -> AcquisitionContextV1:
    return AcquisitionContextV1(
        catalog=CapabilityCatalog(sources=(), capabilities=()),
        inventory=(),
    )


def _completed_step(
    work_id: str,
    kind: str,
    *,
    input_data: dict | None = None,
    observation: dict | None = None,
) -> WorkStep:
    return (
        WorkStep(
            work_id=work_id,
            kind=kind,
            summary=kind,
            input_data=input_data or {},
        )
        .start()
        .complete(observation or {})
    )


def _build_change(
    tmp_path: Path,
    repository_root: Path,
    revision: str,
    *,
    owner_goal: OwnerCapabilityGoalV1 | None = None,
    gicc_link: dict[str, object] | None = None,
):
    work_store = SQLiteWorkStore(tmp_path / "work.sqlite3")
    change_store = ChangeStore(
        work_store,
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    backend = Backend()
    manager = DevelopmentWorkspaceManager(
        repository_root=repository_root,
        workspace_root=tmp_path / "worktrees",
        base_revision_resolver=CapabilityAcquisitionDevelopmentRevisionResolver(
            change_store
        ),
    )
    coordinator = ChangeCoordinator(
        change_store,
        backend,
        source_completion_handlers=(
            CapabilityAcquisitionSourceCompletionHandler(change_store),
        ),
        development_completion_handlers=(
            CapabilityAcquisitionDevelopmentCompletionHandler(
                change_store,
                manager,
            ),
        ),
    )
    goal = owner_goal or _goal()
    admission = CapabilityAcquisitionCoordinator(
        changes=coordinator,
        context_provider=StaticAcquisitionContextProvider(_context()),
    ).admit(goal, source_revision=revision)
    assert admission.change is not None
    assert admission.acquisition_work_id is not None
    if gicc_link is not None:
        change_store.add_artifact(
            admission.change.change_id,
            kind="gicc_capability_gap_link",
            payload=gicc_link,
        )

    resolver = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry((CustomBuildCapabilitySourceAdapter(),))
    )
    resolution = resolver.resolve(goal, _context())
    candidate = resolution.selected_candidate
    assert candidate is not None
    evaluation = resolution.evaluation(candidate.candidate_id)
    resolution_artifact = change_store.add_artifact(
        admission.change.change_id,
        kind="acquisition_resolution",
        payload=resolution_payload(
            candidates=resolution.candidates,
            evaluations=resolution.evaluations,
            selected_candidate_id=resolution.selected_candidate_id,
        ),
    )
    plan = CapabilityAcquisitionPlanV1.create(
        goal,
        candidate,
        evaluation,
        proposed_capability_id=CAPABILITY_ID,
        proposed_package_id=PACKAGE_ID,
        proposed_package_version=PACKAGE_VERSION,
        rollback_summary="Disable package and revert promoted release.",
        changed_paths=(
            "src/jarvis/tv_control.py",
            "tests/test_tv_control.py",
            "capability_packages/tv.control.custom.json",
        ),
        sandbox_profile_ids=("test.offline.v1",),
        verification_contract_ids=("tv-control-contract-v1",),
        development_test_targets=("tests/test_tv_control.py",),
        evidence_refs=("owner-goal",),
    )
    plan_artifact = change_store.add_artifact(
        admission.change.change_id,
        kind="acquisition_plan",
        payload={
            **plan_payload(plan),
            "resolution_artifact_id": resolution_artifact.artifact_id,
            "resolution_artifact_digest": resolution_artifact.digest,
            "selected_candidate": candidate_payload(candidate),
            "selected_evaluation": evaluation_payload(evaluation),
        },
    )

    acquisition_work = work_store.require(admission.acquisition_work_id)
    work_store.add_step(
        _completed_step(
            acquisition_work.work_id,
            "acq_finalize",
            observation={
                "finalized": True,
                "plan_id": plan.plan_id,
                "plan_digest": plan.digest,
                "plan_artifact_id": plan_artifact.artifact_id,
                "plan_artifact_digest": plan_artifact.digest,
            },
        )
    )
    running = work_store.save(
        acquisition_work.transition(WorkState.RUNNING),
        expected_version=acquisition_work.version,
    )
    work_store.save(
        running.transition(WorkState.COMPLETED, result={"summary": "acquired plan"}),
        expected_version=running.version,
    )
    ready = coordinator.reconcile_for_work(acquisition_work.work_id)
    assert ready is not None
    assert ready.state is ChangeState.ARCHITECTURE_READY
    architecture = change_store.latest_artifact(
        admission.change.change_id,
        "architecture",
    )
    assert architecture is not None

    gates = GateService(change_store, verify_owner=lambda *_: True)
    gate = gates.present(
        admission.change.change_id,
        GateKind.ARCHITECTURE,
        architecture.artifact_id,
    )
    gates.decide(
        gate.gate_id,
        approved=True,
        artifact_digest=architecture.digest,
        actor_id="owner",
        source_session_id="owner-session",
        source_turn_id="approve-architecture",
        request_key="phase9e:architecture",
    )
    developing = coordinator.reconcile(admission.change.change_id)
    assert developing.state is ChangeState.DEVELOPING
    development_stage = next(
        item
        for item in change_store.list_stages(admission.change.change_id)
        if item.stage_key == "development"
    )
    development_work = work_store.require(development_stage.work_id)
    return (
        work_store,
        change_store,
        coordinator,
        manager,
        gates,
        admission.change.change_id,
        architecture,
        development_work,
    )


def _package_payload(*, package_kind: str = "extension_source") -> dict[str, object]:
    return {
        "schema_version": 1,
        "package_id": PACKAGE_ID,
        "package_version": PACKAGE_VERSION,
        "capability_id": CAPABILITY_ID,
        "package_kind": package_kind,
        "manifest_id": "tv.control.manifest",
        "manifest_version": 1,
        "manifest_digest": "b" * 64,
        "runtime_api_id": "jarvis.capability_runtime",
        "runtime_api_version": 1,
        "artifacts": [],
        "attestation_refs": [],
        "sbom_refs": [],
    }


def _complete_candidate(
    work_store: SQLiteWorkStore,
    manager: DevelopmentWorkspaceManager,
    work: WorkItem,
    *,
    package_kind: str = "extension_source",
) -> tuple[str, str]:
    workspace = manager.ensure(work.work_id)
    source = workspace.path / "src" / "jarvis"
    source.mkdir(parents=True, exist_ok=True)
    (source / "tv_control.py").write_text(
        "def power() -> str:\n    return 'ok'\n",
        encoding="utf-8",
    )
    tests = workspace.path / "tests"
    tests.mkdir(exist_ok=True)
    (tests / "test_tv_control.py").write_text(
        "from jarvis.tv_control import power\n\n"
        "def test_power():\n"
        "    assert power() == 'ok'\n",
        encoding="utf-8",
    )
    packages = workspace.path / "capability_packages"
    packages.mkdir(exist_ok=True)
    (packages / "tv.control.custom.json").write_text(
        json.dumps(_package_payload(package_kind=package_kind), sort_keys=True),
        encoding="utf-8",
    )

    work_store.add_step(
        _completed_step(
            work.work_id,
            "dev_write_file",
            input_data={"path": "capability_packages/tv.control.custom.json"},
            observation={
                "path": "capability_packages/tv.control.custom.json",
                "production_tree_modified": False,
            },
        )
    )
    work_store.add_step(
        _completed_step(
            work.work_id,
            "dev_run_tests",
            input_data={"targets": ["tests/test_tv_control.py"]},
            observation={
                "passed": True,
                "returncode": 0,
                "sandbox": "docker",
                "network": "disabled",
                "workspace": "read_only",
                "sandbox_profile": "test.offline.v1",
                "sandbox_profile_version": 1,
            },
        )
    )
    work_store.add_step(
        _completed_step(
            work.work_id,
            "dev_diff",
            observation={"branch": workspace.branch, "diff": "bounded diff"},
        )
    )

    _git(workspace.path, "add", "--all")
    _git(workspace.path, "commit", "-m", "add TV capability")
    commit = _git(workspace.path, "rev-parse", "HEAD").stdout.strip().lower()
    assert _git(workspace.path, "status", "--porcelain=v1").stdout == ""
    work_store.add_step(
        _completed_step(
            work.work_id,
            "dev_commit",
            observation={
                "committed": True,
                "commit": commit,
                "branch": workspace.branch,
                "clean": True,
                "pushed": False,
                "merged": False,
                "production_tree_modified": False,
            },
        )
    )
    running = work_store.save(
        work.transition(WorkState.RUNNING),
        expected_version=work.version,
    )
    work_store.save(
        running.transition(
            WorkState.COMPLETED,
            result={
                "branch": workspace.branch,
                "commit": commit,
                "verification": {"passed": True, "sandbox": "docker"},
            },
        ),
        expected_version=running.version,
    )
    return workspace.branch, commit


def test_verification_requires_exact_approved_test_targets() -> None:
    work = WorkItem(
        request="build capability",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="change:1",
        source_turn_id="development:1",
        result={"verification": {"passed": True}},
    )
    steps = (
        _completed_step(work.work_id, "dev_write_file"),
        _completed_step(
            work.work_id,
            "dev_run_tests",
            input_data={"targets": ["tests/test_other.py"]},
            observation={"passed": True},
        ),
        _completed_step(work.work_id, "dev_diff"),
        _completed_step(
            work.work_id,
            "dev_commit",
            observation={"committed": True, "clean": True},
        ),
    )
    with pytest.raises(
        CapabilityCandidateError,
        match="approved development test targets",
    ):
        CapabilityCandidateVerifier._verification_step(
            work,
            steps,
            ("tests/test_tv_control.py",),
        )


def _gicc_owner_goal() -> OwnerCapabilityGoalV1:
    return OwnerCapabilityGoalV1.create(
        request="Acquire reusable media-player control.",
        requested_capability="media_player.control",
        required_operations=("power",),
        target_hints=("entity_type:media_player", "entity_id:entity_tv"),
        source_session_id="gicc:goal-tv",
        source_turn_id="gap:gap-tv",
        now_epoch=100.0,
    )


def _gicc_link(*, family: str = "media_player.control") -> dict[str, object]:
    return {
        "schema": "gicc_phase9_gap_link.v1",
        "request_id": "phase9_gicc_test",
        "request_digest": "a" * 64,
        "motivating_goal_id": "goal-tv",
        "gap_id": "gap-tv",
        "reusable_capability_family": family,
        "minimum_required_operations": ["power"],
        "target_entity_type": "media_player",
        "target_entity_id": "entity_tv",
        "owner_source_session_id": "owner-session",
        "owner_source_turn_id": "owner-turn",
    }


def test_gicc_semantic_identity_flows_into_phase9_development_architecture(
    tmp_path: Path,
    acquisition_repo: tuple[Path, str],
) -> None:
    repository_root, revision = acquisition_repo
    (
        _,
        _,
        _,
        _,
        _,
        _,
        architecture,
        development_work,
    ) = _build_change(
        tmp_path,
        repository_root,
        revision,
        owner_goal=_gicc_owner_goal(),
        gicc_link=_gicc_link(),
    )

    assert architecture.payload["semantic_capability_contract"] == {
        "schema": "semantic_capability_build_contract.v1",
        "semantic_capability_family": "media_player.control",
        "target_entity_type": "media_player",
        "target_entity_id": "entity_tv",
        "required_operations": ["power"],
        "descriptor_requirements": {
            "semantic_capability_family": "media_player.control",
            "target_entity_types": ["media_player"],
        },
    }
    assert "semantic_capability_contract" in development_work.request
    assert "media_player.control" in development_work.request


def test_gicc_semantic_identity_drift_blocks_phase9_architecture(
    tmp_path: Path,
    acquisition_repo: tuple[Path, str],
) -> None:
    repository_root, revision = acquisition_repo

    with pytest.raises(
        CapabilityAcquisitionArchitectureError,
        match="semantic family differs",
    ):
        _build_change(
            tmp_path,
            repository_root,
            revision,
            owner_goal=_gicc_owner_goal(),
            gicc_link=_gicc_link(family="unrelated.control"),
        )


def test_protected_acquisition_governance_path_is_rejected(
    tmp_path: Path,
    acquisition_repo: tuple[Path, str],
) -> None:
    repository_root, revision = acquisition_repo
    (
        _,
        store,
        _,
        manager,
        _,
        change_id,
        _,
        _,
    ) = _build_change(tmp_path, repository_root, revision)
    verifier = CapabilityCandidateVerifier(store, manager)
    with pytest.raises(CapabilityCandidateError, match="governance/security"):
        verifier._protected_surface(("src/jarvis/capability_acquisition/models.py",))
    assert store.require(change_id).state is ChangeState.DEVELOPING


def test_valid_candidate_binds_package_git_architecture_and_acceptance(
    tmp_path: Path,
    acquisition_repo: tuple[Path, str],
) -> None:
    repository_root, revision = acquisition_repo
    (
        work_store,
        store,
        coordinator,
        manager,
        gates,
        change_id,
        architecture,
        development_work,
    ) = _build_change(tmp_path, repository_root, revision)
    branch, commit = _complete_candidate(work_store, manager, development_work)

    verifying = coordinator.reconcile(change_id)

    assert verifying.state is ChangeState.VERIFYING
    candidate = store.latest_artifact(change_id, "capability_candidate")
    acceptance = store.latest_artifact(change_id, "acceptance")
    verification = store.latest_artifact(
        change_id,
        "capability_candidate_verification",
    )
    assert candidate is not None
    assert acceptance is not None
    assert verification is not None
    assert verification.payload["passed"] is True
    assert candidate.payload["commit"] == commit
    assert candidate.payload["branch"] == branch
    assert candidate.payload["source_revision"] == revision
    assert candidate.payload["architecture_artifact_id"] == architecture.artifact_id
    assert candidate.payload["architecture_digest"] == architecture.digest
    assert candidate.payload["package_id"] == PACKAGE_ID
    assert candidate.payload["package_version"] == PACKAGE_VERSION
    assert candidate.payload["capability_id"] == CAPABILITY_ID
    assert candidate.payload["package_path"] == (
        "capability_packages/tv.control.custom.json"
    )
    assert candidate.payload["protected_surface"]["verdict"] == "clear"

    gate = gates.present(change_id, GateKind.ACCEPTANCE, acceptance.artifact_id)
    assert gate.artifact_digest == acceptance.digest
    assert store.require(change_id).state is ChangeState.WAITING_OWNER_ACCEPTANCE


def test_core_source_package_fails_candidate_verification(
    tmp_path: Path,
    acquisition_repo: tuple[Path, str],
) -> None:
    repository_root, revision = acquisition_repo
    (
        work_store,
        store,
        coordinator,
        manager,
        _,
        change_id,
        _,
        development_work,
    ) = _build_change(tmp_path, repository_root, revision)
    _complete_candidate(
        work_store,
        manager,
        development_work,
        package_kind="core_source",
    )

    failed = coordinator.reconcile(change_id)

    assert failed.state is ChangeState.FAILED
    verification = store.latest_artifact(
        change_id,
        "capability_candidate_verification",
    )
    assert verification is not None
    assert verification.payload["passed"] is False
    assert verification.payload["reason_code"] == "package_kind_invalid"


def test_stale_architecture_blocks_acceptance_gate(
    tmp_path: Path,
    acquisition_repo: tuple[Path, str],
) -> None:
    repository_root, revision = acquisition_repo
    (
        work_store,
        store,
        coordinator,
        manager,
        gates,
        change_id,
        architecture,
        development_work,
    ) = _build_change(tmp_path, repository_root, revision)
    _complete_candidate(work_store, manager, development_work)
    assert coordinator.reconcile(change_id).state is ChangeState.VERIFYING
    acceptance = store.latest_artifact(change_id, "acceptance")
    assert acceptance is not None

    store.add_artifact(
        change_id,
        kind="architecture",
        payload={**architecture.payload, "rollback_strategy": "superseded"},
    )

    with pytest.raises(ChangeConflict):
        gates.present(change_id, GateKind.ACCEPTANCE, acceptance.artifact_id)
