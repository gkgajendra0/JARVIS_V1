from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from jarvis.capabilities.models import CapabilityCatalog
from jarvis.capability_acquisition.admission import CapabilityAcquisitionCoordinator
from jarvis.capability_acquisition.architecture import (
    CapabilityAcquisitionDevelopmentRevisionResolver,
    CapabilityAcquisitionSourceCompletionHandler,
)
from jarvis.capability_acquisition.artifacts import (
    candidate_payload,
    evaluation_payload,
    plan_payload,
    resolution_payload,
)
from jarvis.capability_acquisition.candidate_actions import (
    CapabilityBindSubstrateExecutor,
    capability_candidate_completion_guard,
)
from jarvis.capability_acquisition.candidate_models import (
    CapabilityAcquisitionCandidateEvidenceV1,
)
from jarvis.capability_acquisition.candidate_verification import (
    CapabilityAcquisitionDevelopmentCompletionHandler,
    CapabilityAcquisitionProtectedSurfacePolicy,
    ensure_capability_acquisition_candidate_current,
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
from jarvis.capability_registry.contracts import (
    CAPABILITY_PACKAGE_SCHEMA_VERSION_V1,
    CAPABILITY_RUNTIME_API_ID,
    CAPABILITY_RUNTIME_API_VERSION_V1,
    CapabilityPackageKind,
    CapabilityPackageV1,
)
from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.engineering_substrate.canonical import canonical_digest, canonical_payload
from jarvis.engineering_substrate.contracts import CapabilityManifest
from jarvis.engineering_substrate.sandbox import default_sandbox_registry
from jarvis.incident_repair.models import ProtectedSurfaceVerdict
from jarvis.work.development import DevelopmentWorkspaceManager
from jarvis.work.models import WorkPriority, WorkState, WorkStep
from jarvis.work.store import SQLiteWorkStore


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
def capability_repo(tmp_path: Path) -> tuple[Path, str]:
    if shutil.which("git") is None:
        pytest.skip("Git is required for Phase-9 capability-candidate tests")
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "jarvis-tests@example.invalid")
    _git(root, "config", "user.name", "JARVIS Tests")
    (root / "README.md").write_text("phase9 fixture\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base revision")
    revision = _git(root, "rev-parse", "HEAD").stdout.strip().lower()
    return root, revision


def _empty_context() -> AcquisitionContextV1:
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


def _build_phase9_change(
    tmp_path: Path,
    repository_root: Path,
    revision: str,
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
    goal = OwnerCapabilityGoalV1.create(
        request="Acquire a local TV state reader",
        requested_capability="TV state reader",
        required_operations=("read_state",),
        source_session_id="owner-session",
        source_turn_id="owner-turn",
        now_epoch=100.0,
    )
    admission = CapabilityAcquisitionCoordinator(
        changes=coordinator,
        context_provider=StaticAcquisitionContextProvider(_empty_context()),
    ).admit(goal, source_revision=revision)
    assert admission.change is not None
    assert admission.acquisition_work_id is not None

    resolution = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry((CustomBuildCapabilitySourceAdapter(),))
    ).resolve(goal, _empty_context())
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
    verification_contracts = (
        "phase5-sandbox-verification",
        "phase6-candidate-verification",
        "verification.tv.read.v1",
    )
    plan = CapabilityAcquisitionPlanV1.create(
        goal,
        candidate,
        evaluation,
        proposed_capability_id="tv.read",
        proposed_package_id="tv.read.local",
        proposed_package_version="1.0.0",
        rollback_summary="Disable the package and restore the prior release.",
        changed_paths=(
            "src/jarvis/capabilities/tv_read.py",
            "tests/test_tv_read.py",
            "capability_manifests/tv.read.local.json",
            "capability_packages/tv.read.local.json",
        ),
        sandbox_profile_ids=("test.offline.v1",),
        verification_contract_ids=verification_contracts,
        development_test_targets=("tests/test_tv_read.py",),
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
    running = acquisition_work.transition(WorkState.RUNNING)
    work_store.save(running, expected_version=acquisition_work.version)
    completed = running.transition(
        WorkState.COMPLETED,
        result={"summary": "acquisition plan complete"},
    )
    work_store.save(completed, expected_version=running.version)
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
    stage = next(
        item
        for item in change_store.list_stages(admission.change.change_id)
        if item.stage_key == "development"
    )
    development_work = work_store.require(stage.work_id)
    return (
        work_store,
        change_store,
        coordinator,
        manager,
        gates,
        admission.change.change_id,
        architecture,
        development_work,
        verification_contracts,
    )


async def _prepare_valid_candidate(
    *,
    work_store: SQLiteWorkStore,
    change_store: ChangeStore,
    manager: DevelopmentWorkspaceManager,
    work,
    verification_contracts: tuple[str, ...],
):
    workspace = manager.ensure(work.work_id)
    source = workspace.path / "src" / "jarvis" / "capabilities"
    source.mkdir(parents=True)
    (source / "tv_read.py").write_text(
        "def read_state():\n    return 'off'\n",
        encoding="utf-8",
    )
    tests = workspace.path / "tests"
    tests.mkdir()
    (tests / "test_tv_read.py").write_text(
        "from src.jarvis.capabilities.tv_read import read_state\n\n"
        "def test_read_state():\n"
        "    assert read_state() == 'off'\n",
        encoding="utf-8",
    )

    sandbox = default_sandbox_registry().require("test.offline.v1", 1)
    manifest = CapabilityManifest(
        manifest_id="manifest.tv.read.local",
        manifest_version=1,
        capability_id="tv.read",
        capability_version="1.0.0",
        purpose="Read a deterministic local TV state fixture.",
        adapter_id="tv.read.adapter.v1",
        executor_id="tv.read.executor.v1",
        operations=("read_state",),
        dependency_resolution_ids=(),
        secret_scope_requirements=(),
        authority_attributes=("private_read",),
        sandbox_profile_ids=("test.offline.v1",),
        discovery_scope_ids=(),
        platform_constraints=(),
        resource_requirements=(),
        health_probe_ids=(),
        verification_contract_ids=verification_contracts,
        hardware_acceptance_contract_ids=(),
        provenance_ids=(),
        disable_rollback_contract_id="rollback.tv.read.v1",
        dependency_resolution_digests=(),
        sandbox_profile_digests=(canonical_digest(sandbox.profile),),
        discovery_scope_digests=(),
        provenance_digests=(),
    )
    manifest_dir = workspace.path / "capability_manifests"
    manifest_dir.mkdir()
    manifest_path = manifest_dir / "tv.read.local.json"
    manifest_path.write_text(
        json.dumps(canonical_payload(manifest), sort_keys=True),
        encoding="utf-8",
    )

    package = CapabilityPackageV1(
        schema_version=CAPABILITY_PACKAGE_SCHEMA_VERSION_V1,
        package_id="tv.read.local",
        package_version="1.0.0",
        capability_id="tv.read",
        package_kind=CapabilityPackageKind.EXTENSION_SOURCE,
        manifest_id=manifest.manifest_id,
        manifest_version=manifest.manifest_version,
        manifest_digest=canonical_digest(manifest),
        runtime_api_id=CAPABILITY_RUNTIME_API_ID,
        runtime_api_version=CAPABILITY_RUNTIME_API_VERSION_V1,
        artifacts=(),
        attestation_refs=(),
        sbom_refs=(),
    )
    package_dir = workspace.path / "capability_packages"
    package_dir.mkdir()
    package_path = package_dir / "tv.read.local.json"
    package_path.write_text(
        json.dumps(package.canonical_payload(), sort_keys=True),
        encoding="utf-8",
    )

    work_store.add_step(
        _completed_step(
            work.work_id,
            "dev_write_file",
            input_data={"path": "src/jarvis/capabilities/tv_read.py"},
            observation={
                "path": "src/jarvis/capabilities/tv_read.py",
                "production_tree_modified": False,
            },
        )
    )
    work_store.add_step(
        _completed_step(
            work.work_id,
            "dev_run_tests",
            input_data={"targets": ["tests/test_tv_read.py"]},
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
            observation={"branch": workspace.branch, "diff": "phase9 bounded diff"},
        )
    )
    _git(workspace.path, "add", "--all")
    _git(workspace.path, "commit", "-m", "add local TV reader capability")
    commit = _git(workspace.path, "rev-parse", "HEAD").stdout.strip().lower()
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
    binder = CapabilityBindSubstrateExecutor(change_store, manager)
    substrate = await binder.execute(
        work=work,
        parameters={
            "manifest_path": "capability_manifests/tv.read.local.json",
            "package_path": "capability_packages/tv.read.local.json",
        },
    )
    assert substrate["substrate_satisfied"] is True
    work_store.add_step(
        _completed_step(
            work.work_id,
            "dev_phase9_bind_substrate",
            observation=substrate,
        )
    )
    running = work.transition(WorkState.RUNNING)
    work_store.save(running, expected_version=work.version)
    completed = running.transition(
        WorkState.COMPLETED,
        result={
            "branch": workspace.branch,
            "commit": commit,
            "verification": {"passed": True, "sandbox": "docker"},
        },
    )
    work_store.save(completed, expected_version=running.version)
    return workspace, package, manifest, commit


def test_candidate_evidence_digest_detects_tampering() -> None:
    candidate = CapabilityAcquisitionCandidateEvidenceV1.create(
        goal_digest="a" * 64,
        plan_digest="b" * 64,
        architecture_artifact_id="artifact-architecture",
        architecture_digest="c" * 64,
        development_work_id="work-1",
        branch="jarvis/work/work-1",
        commit="d" * 40,
        source_revision="e" * 40,
        changed_paths=("src/jarvis/capabilities/tv_read.py",),
        diff_digest="f" * 64,
        verification_targets=("tests/test_tv_read.py",),
        sandbox_profile="test.offline.v1",
        sandbox_profile_version=1,
        package_descriptor_path="capability_packages/tv.read.local.json",
        manifest_descriptor_path="capability_manifests/tv.read.local.json",
        package_id="tv.read.local",
        package_version="1.0.0",
        package_digest="1" * 64,
        capability_id="tv.read",
        manifest_id="manifest.tv.read.local",
        manifest_version=1,
        manifest_digest="2" * 64,
        substrate_verification_artifact_id="artifact-substrate",
        substrate_verification_artifact_digest="3" * 64,
        substrate_binding_digest="4" * 64,
        external_acceptance_contract_ids=(),
        protected_surface_policy_id="phase9.test",
        protected_surface_policy_version=1,
        now_epoch=100.0,
    )
    assert candidate.candidate_evidence_id.startswith("capability_candidate_")


def test_phase9_protected_policy_allows_only_declarative_top_level_metadata() -> None:
    policy = CapabilityAcquisitionProtectedSurfacePolicy()
    assessment = policy.assess(
        (
            "src/jarvis/capabilities/tv_read.py",
            "tests/test_tv_read.py",
            "capability_manifests/tv.read.local.json",
            "capability_packages/tv.read.local.json",
        )
    )
    assert assessment.verdict is ProtectedSurfaceVerdict.CLEAR

    blocked = policy.assess(("src/jarvis/capability_acquisition/models.py",))
    assert blocked.verdict is ProtectedSurfaceVerdict.PROTECTED_CHANGE_REQUIRED

    unknown = policy.assess(("capability_packages/nested/tv.json",))
    assert unknown.verdict is ProtectedSurfaceVerdict.UNKNOWN


def test_phase9_completion_guard_requires_substrate_after_final_commit() -> None:
    work_id = "work-phase9"
    steps = (
        _completed_step(work_id, "dev_write_file"),
        _completed_step(
            work_id,
            "dev_run_tests",
            observation={"passed": True},
        ),
        _completed_step(work_id, "dev_diff"),
        _completed_step(
            work_id,
            "dev_commit",
            observation={"committed": True, "clean": True},
        ),
    )
    from jarvis.work.models import WorkItem, WorkType

    work = WorkItem(
        work_id=work_id,
        request="build capability",
        work_type=WorkType.DEVELOPMENT,
        source_session_id="change:phase9",
        source_turn_id="development:1",
    )
    allowed, reason = capability_candidate_completion_guard(work, steps)
    assert allowed is False
    assert reason is not None and "substrate" in reason

    bound = _completed_step(
        work_id,
        "dev_phase9_bind_substrate",
        observation={"substrate_satisfied": True},
    )
    assert capability_candidate_completion_guard(work, (*steps, bound)) == (
        True,
        None,
    )


@pytest.mark.asyncio
async def test_valid_phase9_candidate_binds_git_substrate_package_and_acceptance(
    tmp_path: Path,
    capability_repo: tuple[Path, str],
) -> None:
    repository_root, revision = capability_repo
    (
        work_store,
        change_store,
        coordinator,
        manager,
        gates,
        change_id,
        architecture,
        development_work,
        verification_contracts,
    ) = _build_phase9_change(tmp_path, repository_root, revision)

    _, package, manifest, commit = await _prepare_valid_candidate(
        work_store=work_store,
        change_store=change_store,
        manager=manager,
        work=development_work,
        verification_contracts=verification_contracts,
    )
    verifying = coordinator.reconcile(change_id)

    assert verifying.state is ChangeState.VERIFYING
    candidate = change_store.latest_artifact(
        change_id,
        "capability_acquisition_candidate",
    )
    acceptance = change_store.latest_artifact(change_id, "acceptance")
    verification = change_store.latest_artifact(
        change_id,
        "capability_acquisition_verification",
    )
    assert candidate is not None
    assert acceptance is not None
    assert verification is not None
    assert verification.payload["passed"] is True
    assert candidate.payload["commit"] == commit
    assert candidate.payload["package_id"] == package.package_id
    assert candidate.payload["package_digest"] == package.digest
    assert candidate.payload["manifest_digest"] == canonical_digest(manifest)
    assert candidate.payload["architecture_artifact_id"] == architecture.artifact_id
    ensure_capability_acquisition_candidate_current(change_store, change_id)

    gate = gates.present(
        change_id,
        GateKind.ACCEPTANCE,
        acceptance.artifact_id,
    )
    assert gate.artifact_digest == acceptance.digest
    assert change_store.require(change_id).state is ChangeState.WAITING_OWNER_ACCEPTANCE
