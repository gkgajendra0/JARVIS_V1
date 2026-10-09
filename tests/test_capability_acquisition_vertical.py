"""One production acquisition lineage, with explicitly controlled external ports.

Research/engineering decisions, resumed goal replanning, and owner authentication
are deterministic fixtures.
GitHub and runtime process switching are controlled ports; no real remote merge is
performed. Candidate pytest really executes. Set JARVIS_E2E_REQUIRE_DOCKER=1 and
JARVIS_DEVELOPMENT_TEST_IMAGE to require the production Docker runner (CI gate).
The local runner models sandbox metadata ONLY in disposable test stores.
"""

from __future__ import annotations

import asyncio
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from test_capability_registry_runtime_composition import FakeLifecycleAuthority
from test_capability_runtime import FakeAuthority

from jarvis.authority.approval import ApprovalService
from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.models import (
    CapabilityCatalog,
)
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.capability_acquisition.activation import (
    CapabilityAcquisitionLifecycleCoordinator,
)
from jarvis.capability_acquisition.admission import CapabilityAcquisitionCoordinator
from jarvis.capability_acquisition.architecture import (
    CapabilityAcquisitionDevelopmentRevisionResolver,
    CapabilityAcquisitionSourceCompletionHandler,
)
from jarvis.capability_acquisition.external_acceptance import (
    ExternalAcceptanceContextResolver,
    ExternalAcceptanceCoordinator,
    ExternalAcceptanceInspectExecutor,
    ExternalAcceptanceInvokeExecutor,
    ExternalAcceptancePrepareExecutor,
    ExternalAcceptanceRecordExecutor,
    external_acceptance_completion_guard,
)
from jarvis.capability_acquisition.external_contract import (
    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.capability_acquisition.promotion import CapabilityAcquisitionReleaseBridge
from jarvis.capability_acquisition.resolver import CapabilityAcquisitionResolver
from jarvis.capability_acquisition.runtime_context import (
    StaticAcquisitionContextProvider,
)
from jarvis.capability_acquisition.source import (
    AcquisitionContextV1,
    CapabilitySourceRegistry,
    ExistingCapabilitySourceAdapter,
)
from jarvis.capability_acquisition.standard_sources import (
    CustomBuildCapabilitySourceAdapter,
)
from jarvis.capability_acquisition.substrate_workflow import (
    CapabilityDevelopmentContextResolver,
    CapabilityManifestBindExecutor,
    CapabilitySubstrateVerifyExecutor,
)
from jarvis.capability_acquisition.verification import (
    CapabilityAcquisitionDevelopmentCompletionHandler,
)
from jarvis.capability_acquisition.workflow import (
    AcquisitionFinalizeExecutor,
    AcquisitionInspectGoalExecutor,
    AcquisitionResolveExecutor,
    AcquisitionWorkContextResolver,
    acquisition_completion_guard,
)
from jarvis.capability_registry.runtime_composition import (
    build_package_managed_runtime_stack,
)
from jarvis.capability_registry.store import CapabilityRegistryStore
from jarvis.development_engine.contracts import DevelopmentTicketV1
from jarvis.development_engine.phase9 import Phase9DevelopmentTicketBuilder
from jarvis.development_engine.tools import (
    DevelopmentToolDenied,
    WorkExecutorDevelopmentToolPort,
)
from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.gates import GateKind, GateService
from jarvis.engineering_substrate.artifacts import ArtifactStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.engineering_substrate.contracts import CapabilityManifest
from jarvis.engineering_substrate.manifest import (
    DigestRegistration,
    ManifestReferenceCatalog,
    TrustedAdapterRegistration,
    TrustedExecutorRegistration,
)
from jarvis.engineering_substrate.sandbox import default_sandbox_registry
from jarvis.goal_intelligence.capability_graph import CapabilityGraphResolver
from jarvis.goal_intelligence.execution import GoalPlanDispatcher
from jarvis.goal_intelligence.models import (
    CapabilityRequirementGraphV1,
    CapabilityRequirementV1,
    ContinuationBlockerType,
    ContinuationState,
    GoalContinuationV1,
    GoalKind,
    GoalState,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeType,
    PlanNodeV1,
)
from jarvis.goal_intelligence.phase9 import (
    Phase9GoalBridge,
    Phase9GoalContinuationVerifier,
)
from jarvis.goal_intelligence.runtime import GiccApplyRuntime
from jarvis.goal_intelligence.service import GoalOrchestrator, VerificationRegistry
from jarvis.goal_intelligence.store import GoalStore
from jarvis.goal_intelligence.telemetry import CapturingGiccTelemetry
from jarvis.promotion.authority import PromotionAuthorityBridge
from jarvis.promotion.coordinator import PromotionCoordinator
from jarvis.promotion.deployment import DeploymentCoordinator
from jarvis.promotion.evaluation import _Authority, _checks, _Runtime, _Verifier
from jarvis.promotion.github import (
    GitHubPromotionPolicy,
    GitHubPullRequestSnapshot,
    GitHubWorkflowSnapshot,
)
from jarvis.promotion.merge import PromotionMerger
from jarvis.promotion.observation import ObservationController
from jarvis.promotion.release import DeploymentMetadataStore, GitReleaseStager
from jarvis.promotion.store import PromotionStore
from jarvis.self_model.health import HealthRegistry
from jarvis.work.development import (
    DevelopmentWorkspaceManager,
    DockerDevelopmentTestRunner,
    build_development_executors,
)
from jarvis.work.engine import WorkActionRegistry
from jarvis.work.models import WorkState, WorkStep
from jarvis.work.privacy import ProtectedWorkPayloadCodec
from jarvis.work.resources import ResourceLeaseManager, engineering_resource_capacities
from jarvis.work.store import SQLiteWorkStore

CAPABILITY = "example.utility"
PACKAGE = "example.utility.package"
STAMP = "2026-10-09T05:30:00+00:00"


def test_substrate_verifier_uses_runtime_registered_resource_capacity():
    resources = ResourceLeaseManager(engineering_resource_capacities())
    executor = CapabilitySubstrateVerifyExecutor(None)
    assert resources.normalize(executor.resource_keys(None, {})) == ("artifact",)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


class _Backend:
    def submit(self, work_id, *, priority):
        return work_id


async def _action(store, executor, work, parameters):
    step = WorkStep(
        work_id=work.work_id,
        kind=executor.descriptor.name,
        summary=executor.descriptor.name,
        input_data=parameters,
    )
    store.add_step(step)
    store.save_step(step.start())
    result = await executor.execute(
        work=store.require(work.work_id), parameters=parameters
    )
    store.save_step(step.start().complete(result))
    return result


class _LocalControlledSandbox:
    async def run(self, workspace, *, targets, timeout_seconds):
        completed = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                "-B",
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                *targets,
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return {
            "passed": completed.returncode == 0,
            "returncode": completed.returncode,
            "output": completed.stdout + completed.stderr,
            "sandbox": "docker",
            "network": "disabled",
            "workspace": "read_only",
            "sandbox_profile": "test.offline.v1",
            "sandbox_profile_version": 1,
            "test_boundary": "controlled_sandbox_metadata_not_real_docker",
        }


class _ControlledGitHub:
    """Fixture CI transport with real local Git object IDs, never remote writes."""

    def __init__(self, root, base):
        self.root, self.base, self.main = root, base, base
        self.head = None
        self.pr = None
        self.merge_calls = 0

    def publish_candidate(self, candidate, *, workspace_root):
        assert _git(workspace_root, "rev-parse", "HEAD") == candidate.head_sha
        self.head = candidate.head_sha

    def ensure_pull_request(self, candidate, *, title, body):
        self.pr = GitHubPullRequestSnapshot(1, self.base, self.head, False, "open")
        return self.pr

    def read_workflow(self, number):
        return GitHubWorkflowSnapshot(
            "controlled-ci",
            "pull_request",
            self.head,
            self.head,
            "completed",
            "success",
            _checks(),
        )

    def read_protected_main_sha(self):
        return self.main

    def read_pull_request(self, number):
        return self.pr

    def squash_merge(self, number, *, expected_head_sha):
        assert expected_head_sha == self.head
        self.merge_calls += 1
        self.main = self.head
        self.pr = GitHubPullRequestSnapshot(
            1, self.base, self.head, False, "closed", merged=True, merge_sha=self.head
        )
        return self.head


def _candidate_source(manifest, references, executor, adapter):
    return f"""from jarvis.capabilities.models import CapabilityDescriptor, CapabilityKind, CapabilityResult, CapabilityStatus
from jarvis.capabilities.execution import PreparedCapability
from jarvis.authority.types import ActionAttributes
from jarvis.capability_acquisition.external_contract import acceptance_readback
from jarvis.capability_registry.provider import CapabilityProviderRegistration
from jarvis.capability_registry.runtime_composition import AcquiredCapabilityDefinition
from jarvis.engineering_substrate.contracts import CapabilityManifest
from jarvis.engineering_substrate.manifest import DigestRegistration, ManifestReferenceCatalog, TrustedExecutorRegistration, TrustedAdapterRegistration

def transform(value):
    return value * 2

def definition(release_sha):
    descriptor = CapabilityDescriptor.create(capability_id={CAPABILITY!r}, source_id="acquired.utility", kind=CapabilityKind.NATIVE_API, name="Double a number", description="Deterministic acquired utility.", operations=("transform",), execution_enabled=True, metadata={{"semantic_capability_family": {CAPABILITY!r}, "target_entity_types": ["software"], "acquisition_target_hints": ["entity_type:software"]}})
    class Executor:
        capability_key = descriptor.key
        operations = descriptor.operations
        def __init__(self):
            self.descriptor = descriptor
        def prepare(self, request):
            return PreparedCapability(request=request, target={{}}, parameters=request.parameters, material_summary="Double input", attributes=ActionAttributes(), execution_payload=request.parameters)
        def execute(self, prepared):
            value = transform(prepared.parameters.get("value", 21))
            return CapabilityResult(status=CapabilityStatus.SUCCEEDED, capability_key=descriptor.key, operation=prepared.request.operation, data={{"value": value, "acceptance_observation": acceptance_readback(method="external_system_readback", summary=f"Computed {{value}}", evidence_refs=("controlled-utility-readback",))}})
    return AcquiredCapabilityDefinition(provider=CapabilityProviderRegistration(capability_id={CAPABILITY!r}, executor_id={executor.executor_id!r}, adapter_id={adapter.adapter_id!r}, descriptor=descriptor, executor=Executor(), release_sha=release_sha), executor_registration={executor!r}, adapter_registration={adapter!r}, manifests=({manifest!r},), references={references!r})
"""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "inject_test_failure", [False, True], ids=["normal", "test-failure-recovery"]
)
async def test_production_acquisition_vertical_develop_verify_promote_activate_resume_reuse(
    tmp_path,
    inject_test_failure,
):
    root = tmp_path / "repo"
    root.mkdir()
    source_root = Path(__file__).resolve().parents[1]
    shutil.copytree(
        source_root / "src",
        root / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
    )
    (root / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\npythonpath = ["src"]\n'
    )
    _git(root, "init")
    _git(root, "config", "user.name", "Acquisition Test")
    _git(root, "config", "user.email", "acquisition@example.invalid")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "isolated base")
    base = _git(root, "rev-parse", "HEAD")

    work = SQLiteWorkStore(
        tmp_path / "work.sqlite3", payload_codec=ProtectedWorkPayloadCodec(b"v" * 32)
    )
    changes = ChangeStore(work, processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,))
    goals = GoalStore(work)
    backend = _Backend()
    manager = DevelopmentWorkspaceManager(
        repository_root=root,
        workspace_root=tmp_path / "worktrees",
        base_revision_resolver=CapabilityAcquisitionDevelopmentRevisionResolver(
            changes
        ),
    )
    coordinator = ChangeCoordinator(
        changes,
        backend,
        source_completion_handlers=(
            CapabilityAcquisitionSourceCompletionHandler(changes),
        ),
        development_completion_handlers=(
            CapabilityAcquisitionDevelopmentCompletionHandler(changes, manager),
        ),
    )
    context = StaticAcquisitionContextProvider(
        AcquisitionContextV1(
            catalog=CapabilityCatalog(sources=(), capabilities=()), inventory=()
        )
    )
    goal = goals.create_goal(
        OwnerGoalV2.create(
            source_session_id="owner",
            source_turn_id="original",
            exact_owner_request="Double 21 using a reusable utility",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="42",
            created_at=STAMP,
        )
    )
    requirement = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability=CAPABILITY,
        operation="transform",
        target_entity_type="software",
        expected_postconditions=("42",),
        reason="Compute result",
    )
    graph = goals.put_requirement_graph(
        CapabilityRequirementGraphV1.create(
            goal_id=goal.goal_id, requirements=(requirement,)
        )
    )
    gap = (
        CapabilityGraphResolver(store=goals)
        .analyze(graph, context.current(), persist_gaps=True)
        .gaps[0]
    )
    node = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=0,
        node_type=PlanNodeType.ACQUIRE_CAPABILITY,
        summary="Acquire utility",
        gap_id=gap.gap_id,
    )
    plan = goals.put_plan(
        PlanGraphV1.create(
            goal_id=goal.goal_id,
            goal_revision=goal.goal_revision,
            nodes=(node,),
            edges=(),
            root_node_ids=(node.node_id,),
            completion_node_ids=(node.node_id,),
            created_at=STAMP,
        )
    )
    continuation = goals.put_continuation(
        GoalContinuationV1.create(
            goal_id=goal.goal_id,
            plan_id=plan.plan_id,
            blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
            blocked_by_id=gap.gap_id,
            resume_node_id=node.node_id,
            goal_revision=goal.goal_revision,
            created_at=STAMP,
        )
    )
    bridge = Phase9GoalBridge(
        coordinator=CapabilityAcquisitionCoordinator(
            changes=coordinator, context_provider=context
        ),
        change_store=changes,
        goal_store=goals,
        source_revision_provider=lambda: base,
    )
    admitted = bridge.admit_gap(gap, goal)
    change_id = admitted.admission.change.change_id
    research = work.require(admitted.admission.acquisition_work_id)
    research = work.save(
        research.transition(WorkState.RUNNING), expected_version=research.version
    )
    work.add_step(
        WorkStep(
            work_id=research.work_id,
            kind="research_web",
            summary="Controlled research boundary",
        )
        .start()
        .complete({"ok": True, "test_boundary": "fixed_research_evidence"})
    )
    resolver = AcquisitionWorkContextResolver(changes)
    await _action(work, AcquisitionInspectGoalExecutor(resolver), research, {})
    await _action(
        work,
        AcquisitionResolveExecutor(
            resolver,
            context_provider=context,
            sources=CapabilitySourceRegistry((CustomBuildCapabilitySourceAdapter(),)),
        ),
        research,
        {},
    )
    paths = [
        "src/jarvis/acquired_capabilities/utility.py",
        "src/jarvis/acquired_capabilities/registry.py",
        "tests/test_utility.py",
        f"capability_packages/{PACKAGE}.json",
    ]
    from jarvis.capability_acquisition.architecture import (
        CapabilityAcquisitionArchitectureError,
    )

    before = changes.require(change_id)
    with pytest.raises(
        CapabilityAcquisitionArchitectureError, match="registered sandbox"
    ):
        await AcquisitionFinalizeExecutor(resolver).execute(
            work=research,
            parameters={
                "changed_paths": paths,
                "sandbox_profile_ids": ["local_device_control"],
            },
        )
    assert changes.latest_artifact(change_id, "acquisition_plan") is None
    assert changes.latest_artifact(change_id, "architecture") is None
    assert changes.require(change_id) == before
    await _action(
        work,
        AcquisitionFinalizeExecutor(resolver),
        research,
        {
            "proposed_capability_id": CAPABILITY,
            "proposed_package_id": PACKAGE,
            "proposed_package_version": "1.0.0",
            "rollback_summary": "Disable package",
            "changed_paths": paths,
            "sandbox_profile_ids": ["test.offline.v1"],
            "verification_contract_ids": ["utility.verify.v1"],
            "development_test_targets": ["tests/test_utility.py"],
            "owner_acceptance_contract_ids": [PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT],
        },
    )
    assert acquisition_completion_guard(work.list_steps(research.work_id))[0]
    work.save(
        research.transition(
            WorkState.COMPLETED, result={"summary": "Research complete"}
        ),
        expected_version=research.version,
    )
    assert (
        coordinator.reconcile_for_work(research.work_id).state
        is ChangeState.ARCHITECTURE_READY
    )
    gates = GateService(
        changes, verify_owner=lambda *_: True
    )  # Test authentication only.
    architecture = changes.latest_artifact(change_id, "architecture")
    architecture_gate = gates.present(
        change_id, GateKind.ARCHITECTURE, architecture.artifact_id
    )
    gates.decide(
        architecture_gate.gate_id,
        approved=True,
        artifact_digest=architecture.digest,
        actor_id="owner",
        source_session_id="owner",
        source_turn_id="approve-architecture",
        request_key="vertical-architecture",
    )
    coordinator.reconcile(change_id)
    development = work.require(
        next(
            stage.work_id
            for stage in changes.list_stages(change_id)
            if stage.stage_key == "development"
        )
    )
    development = work.save(
        development.transition(WorkState.RUNNING), expected_version=development.version
    )
    ticket = Phase9DevelopmentTicketBuilder(changes).build(
        development,
        available_tools=(
            "prepare_workspace",
            "write_file",
            "run_tests",
            "inspect_diff",
            "commit_candidate",
            "bind_capability_manifest",
            "record_substrate_verification",
            "status",
        ),
    )
    ticket = DevelopmentTicketV1.from_payload(
        ticket.canonical_payload(), expected_digest=ticket.digest
    )
    assert ticket.verification_targets == ("tests/test_utility.py",)
    assert not any(item.startswith("pytest:") for item in ticket.acceptance_criteria)
    require_docker = os.getenv("JARVIS_E2E_REQUIRE_DOCKER") == "1"
    runner = (
        DockerDevelopmentTestRunner(os.environ["JARVIS_DEVELOPMENT_TEST_IMAGE"])
        if require_docker
        else _LocalControlledSandbox()
    )
    substrate = CapabilityDevelopmentContextResolver(changes)
    actions = WorkActionRegistry(
        (
            *build_development_executors(manager, test_runner=runner),
            CapabilityManifestBindExecutor(substrate),
            CapabilitySubstrateVerifyExecutor(substrate),
        )
    )
    port = WorkExecutorDevelopmentToolPort(
        ticket=ticket,
        store=work,
        actions=actions,
        resources=ResourceLeaseManager(
            {"cpu": 2, "git": 1, **engineering_resource_capacities()}
        ),
    )
    await port.invoke("prepare_workspace", {})
    bound = await port.invoke("bind_capability_manifest", {})
    sandbox = default_sandbox_registry().require("test.offline.v1", 1).profile
    manifest = CapabilityManifest(
        manifest_id=f"phase9.manifest.{CAPABILITY}",
        manifest_version=1,
        capability_id=CAPABILITY,
        capability_version="1.0.0",
        purpose="Owner-approved Phase-9 acquired capability",
        adapter_id=f"phase9.adapter.{CAPABILITY}",
        executor_id=f"phase9.executor.{CAPABILITY}",
        operations=("transform",),
        dependency_resolution_ids=(),
        secret_scope_requirements=(),
        authority_attributes=(),
        sandbox_profile_ids=(sandbox.profile_id,),
        discovery_scope_ids=(),
        platform_constraints=(),
        resource_requirements=(),
        health_probe_ids=(),
        verification_contract_ids=tuple(
            architecture.payload["verification_contract_ids"]
        ),
        hardware_acceptance_contract_ids=(),
        provenance_ids=(),
        disable_rollback_contract_id="phase9.disable-rollback.v1",
        sandbox_profile_digests=(canonical_digest(sandbox),),
    )
    assert bound["manifest_digest"] == canonical_digest(manifest)
    executor = TrustedExecutorRegistration(
        executor_id=manifest.executor_id,
        adapter_ids=(manifest.adapter_id,),
        operations=manifest.operations,
        authority_attribute_floor=(),
        allowed_secret_scopes=(),
        sandbox_profile_ids=manifest.sandbox_profile_ids,
    )
    adapter = TrustedAdapterRegistration(
        adapter_id=manifest.adapter_id, operations=manifest.operations
    )
    refs = ManifestReferenceCatalog(
        sandbox_profiles=(
            DigestRegistration(
                reference_id=sandbox.profile_id, digest=canonical_digest(sandbox)
            ),
        ),
        verification_contract_ids=manifest.verification_contract_ids,
        disable_rollback_contract_ids=(manifest.disable_rollback_contract_id,),
    )
    source = _candidate_source(manifest, refs, executor, adapter)
    package = {
        "schema_version": 1,
        "package_id": PACKAGE,
        "package_version": "1.0.0",
        "capability_id": CAPABILITY,
        "package_kind": "extension_source",
        "manifest_id": manifest.manifest_id,
        "manifest_version": 1,
        "manifest_digest": canonical_digest(manifest),
        "runtime_api_id": "jarvis.capability_runtime",
        "runtime_api_version": 1,
        "artifacts": [],
        "attestation_refs": [],
        "sbom_refs": [],
    }
    files = {
        paths[0]: source,
        paths[
            1
        ]: "from jarvis.acquired_capabilities.utility import definition\ndef build_acquired_capability_definitions(release_sha):\n    return (definition(release_sha),)\n",
        paths[
            2
        ]: 'from jarvis.acquired_capabilities.utility import transform\nfrom jarvis.acquired_capabilities.registry import build_acquired_capability_definitions\ndef test_transform():\n    assert transform(21) == 42\ndef test_release_owned_registration():\n    definitions = build_acquired_capability_definitions("a" * 40)\n    assert definitions[0].provider.capability_id == "example.utility"\n',
        paths[3]: json.dumps(package),
    }
    for path, text in files.items():
        await port.invoke("write_file", {"path": path, "text": text})
    if inject_test_failure:
        await port.invoke(
            "write_file",
            {
                "path": paths[0],
                "text": source.replace("return value * 2", "return value * 3"),
            },
        )
        failed = await port.invoke("run_tests", {})
        assert failed["passed"] is False
        assert failed["returncode"] != 0
        with pytest.raises(DevelopmentToolDenied, match="passing sandboxed tests"):
            await port.invoke("commit_candidate", {"message": "Must be denied"})
        await port.invoke("write_file", {"path": paths[0], "text": source})
    with pytest.raises(DevelopmentToolDenied):
        await port.invoke("run_tests", {"targets": ["tests"]})
    tested = await port.invoke("run_tests", {})
    assert tested["passed"], tested["output"]
    assert tested["returncode"] == 0
    await port.invoke("record_substrate_verification", {})
    await port.invoke("inspect_diff", {})
    committed = await port.invoke(
        "commit_candidate", {"message": "Add reusable utility"}
    )
    work.save(
        development.transition(
            WorkState.COMPLETED,
            result={
                "branch": committed["branch"],
                "commit": committed["commit"],
                "verification": tested,
            },
        ),
        expected_version=development.version,
    )
    assert coordinator.reconcile(change_id).state is ChangeState.VERIFYING
    acceptance = changes.latest_artifact(change_id, "acceptance")
    gate = gates.present(change_id, GateKind.ACCEPTANCE, acceptance.artifact_id)
    gates.decide(
        gate.gate_id,
        approved=True,
        artifact_digest=acceptance.digest,
        actor_id="owner",
        source_session_id="owner",
        source_turn_id="accept-candidate",
        request_key="vertical-candidate",
    )
    coordinator.reconcile(change_id)
    promotions = PromotionStore(changes)
    metadata = DeploymentMetadataStore(tmp_path / "deployment")
    deployment = DeploymentCoordinator(
        changes,
        promotions,
        stager=GitReleaseStager(root, tmp_path / "releases"),
        metadata=metadata,
        runtime=_Runtime(),
    )
    deployment.bootstrap_lkg(release_sha=base, config_digest="a" * 64, verified=True)
    github = _ControlledGitHub(root, base)
    prepared = PromotionCoordinator(
        changes,
        promotions,
        github=github,
        workspace_manager=manager,
        deployment_metadata=metadata,
    ).prepare_review(
        change_id,
        config_digest="a" * 64,
        deployment_environment="controlled-test",
        title="utility",
        body="test",
    )
    authority = PromotionAuthorityBridge(
        changes,
        promotions,
        approvals=ApprovalService(),
        authority=_Authority(),
        verifier=_Verifier(),
    )
    authorized = authority.authorize(
        gate_id=prepared.gate.gate_id,
        evidence=prepared.evidence,
        attempt=prepared.attempt,
        session_id="owner",
        source_turn_id="approve-promotion",
        request_key="vertical-promotion",
        repository_full_name="test/disposable",
    )
    merger = PromotionMerger(
        changes,
        promotions,
        github=github,
        authority=authority,
        policy=GitHubPromotionPolicy(),
    )
    merger.execute(
        evidence=prepared.evidence,
        attempt=promotions.require(prepared.attempt.attempt_id),
        authorized=authorized,
    )
    merger.execute(
        evidence=prepared.evidence,
        attempt=promotions.require(prepared.attempt.attempt_id),
        authorized=authorized,
    )
    assert github.merge_calls == 1
    deployed = deployment.deploy(
        evidence=prepared.evidence,
        attempt=promotions.require(prepared.attempt.attempt_id),
    )
    release = deployed.release
    definitions = runpy.run_path(str(Path(release.release_root) / paths[0]))[
        "definition"
    ](release.release_sha)
    stack = build_package_managed_runtime_stack(
        release,
        definitions=(definitions,),
        registry_store=CapabilityRegistryStore(tmp_path / "registry.sqlite3"),
        artifact_store=ArtifactStore(tmp_path / "artifacts"),
        health_registry=HealthRegistry(),
        start_periodic=False,
    )
    stack.lifecycle.authority = (
        FakeLifecycleAuthority()
    )  # Owner verifier boundary only.
    release_bridge = CapabilityAcquisitionReleaseBridge(
        changes,
        promotions,
        metadata,
        admission=stack.admission,
        reconciler=stack.reconciler,
    )
    admitted_package = release_bridge.reconcile(
        change_id, attempt_id=prepared.attempt.attempt_id
    )
    assert not stack.projection.allows(definitions.provider.descriptor.key)
    activation = CapabilityAcquisitionLifecycleCoordinator(
        changes, metadata, stack.lifecycle
    ).activate(change_id, authority_session_id="owner", source_turn_id="activate")
    assert activation.artifact.payload["effective_enabled"] is True
    assert stack.projection.allows(definitions.provider.descriptor.key)
    assert not bridge.completion_verified(gap=gap, goal=goal)
    # External execution and observation remain explicitly controlled test ports.
    external = ExternalAcceptanceCoordinator(changes, backend).start(
        change_id,
        activation_artifact_id=activation.artifact.artifact_id,
        authority_session_id="owner",
        source_turn_id="activate",
    )
    assert external is not None
    external = work.save(
        external.transition(WorkState.RUNNING), expected_version=external.version
    )
    external_resolver = ExternalAcceptanceContextResolver(changes)
    await _action(
        work, ExternalAcceptanceInspectExecutor(external_resolver), external, {}
    )
    prepared_external = await _action(
        work,
        ExternalAcceptancePrepareExecutor(external_resolver),
        external,
        {"operation": "transform", "expected_observation": "42"},
    )
    work.add_step(
        WorkStep(
            work_id=external.work_id,
            kind="owner_input",
            summary="Controlled owner authorization",
        )
        .start()
        .complete(
            {
                "input_key": f"external_acceptance_authorize:{prepared_external['request_id']}",
                "response": "yes",
                "source_session_id": "owner",
                "source_turn_id": "authorize-external",
            }
        )
    )
    capability_runtime = CapabilityRuntime(
        executors=(definitions.provider.executor,),
        resolver=CapabilityResolver((), builtins=(definitions.provider.descriptor,)),
        authority=FakeAuthority(),
        catalog_projection=stack.projection,
    )

    await _action(
        work,
        ExternalAcceptanceInvokeExecutor(external_resolver, runtime=capability_runtime),
        external,
        {"operation": "transform", "parameters": {"value": 21}},
    )
    await _action(
        work, ExternalAcceptanceRecordExecutor(external_resolver), external, {}
    )
    assert external_acceptance_completion_guard(work.list_steps(external.work_id))[0]
    work.save(
        external.transition(
            WorkState.COMPLETED, result={"summary": "Controlled external acceptance"}
        ),
        expected_version=external.version,
    )
    assert bridge.completion_verified(gap=gap, goal=goal)
    catalog = CapabilityCatalog(
        sources=(), capabilities=(definitions.provider.descriptor,)
    )
    ready_context = AcquisitionContextV1(
        catalog=stack.projection.project(catalog),
        inventory=stack.projection.inventory(catalog),
        effective_snapshot=stack.projection.snapshot,
    )
    resumed = Phase9GoalContinuationVerifier(
        goal_store=goals,
        graph_resolver=CapabilityGraphResolver(),
        context_provider=StaticAcquisitionContextProvider(ready_context),
        refresh_capability_catalog=lambda: None,
    ).recheck(
        request=admitted.request,
        graph=graph,
        continuation_id=continuation.continuation_id,
    )
    assert resumed.gap_satisfied
    assert resumed.continuation.state is ContinuationState.RESUMED
    from test_gicc_composition import QueueStructuredClient

    from jarvis.goal_intelligence.composition import GoalIntelligenceCoordinator
    from jarvis.goal_intelligence.interpretation import GoalInterpreter
    from jarvis.goal_intelligence.models import GoalInterpretationCandidateV1
    from jarvis.goal_intelligence.planning import (
        GoalPlanner,
        PlanNodeCandidate,
        PlanProposalV1,
    )
    from jarvis.goal_intelligence.requirements import RequirementDeriver
    from jarvis.goal_intelligence.world import EntityResolver, WorldRegistry

    goals.put_goal_interpretation_evidence(
        goal.goal_id,
        GoalInterpretationCandidateV1.create(
            desired_outcome="42",
            goal_kind=GoalKind.ONE_SHOT,
            candidate_completion_predicates=("42",),
            reasoning_evidence_refs=("controlled-owner-interpretation",),
        ),
    )
    current_goal = goals.get_goal(goal.goal_id)
    goals.update_goal_state(
        goal.goal_id,
        GoalState.WAITING_CAPABILITY,
        expected_revision=current_goal.goal_revision,
    )
    planner_client = QueueStructuredClient(
        PlanProposalV1(
            nodes=[
                PlanNodeCandidate(
                    node_type="action",
                    summary="Double 21",
                    capability_key=definitions.provider.descriptor.key,
                    operation="transform",
                    parameters={"value": 21},
                    postcondition_ref="42",
                ),
                PlanNodeCandidate(
                    node_type="verify",
                    summary="Verify 42",
                    postcondition_ref="42",
                    depends_on_indexes=[0],
                ),
            ]
        )
    )
    goal_coordinator = GoalIntelligenceCoordinator(
        store=goals,
        interpreter=GoalInterpreter(client=QueueStructuredClient()),
        entity_resolver=EntityResolver(WorldRegistry(goals)),
        requirement_deriver=RequirementDeriver(client=QueueStructuredClient()),
        capability_context=StaticAcquisitionContextProvider(ready_context),
        capability_graph_resolver=CapabilityGraphResolver(store=goals),
        phase9_bridge=bridge,
        planner=GoalPlanner(client=planner_client),
    )
    predicates = VerificationRegistry()
    predicates.register(
        "42",
        lambda evidence: any(
            result.get("status") == "succeeded"
            and result.get("payload", {}).get("data", {}).get("value") == 42
            for result in evidence.get("results", ())
        ),
    )
    goal_runtime = GiccApplyRuntime(
        store=goals,
        world=None,
        coordinator=goal_coordinator,
        dispatcher=GoalPlanDispatcher(
            store=goals,
            orchestrator=GoalOrchestrator(
                goal_store=goals,
                capability_runtime=capability_runtime,
                verification_registry=predicates,
            ),
        ),
        telemetry=CapturingGiccTelemetry(),
        capability_runtime=capability_runtime,
    )
    intake = await goal_runtime.continue_goal(goal.goal_id)
    assert planner_client.calls == 1
    completed_goal = intake.goal
    assert completed_goal.state is GoalState.COMPLETED
    assert completed_goal.goal_id == goal.goal_id
    reuse = CapabilityAcquisitionResolver(
        CapabilitySourceRegistry((ExistingCapabilitySourceAdapter(),))
    ).resolve(admitted.phase9_goal, ready_context)
    assert reuse.selected_candidate is not None
    assert reuse.selected_candidate.strategy.value == "reuse"
    observations = ObservationController(
        changes, promotions, metadata, required_healthy_samples=1
    )
    attempt = promotions.require(prepared.attempt.attempt_id)
    observations.record_healthy(attempt, evidence=("controlled-runtime-ready",))
    observations.close_success(promotions.require(attempt.attempt_id))
    assert changes.require(change_id).state is ChangeState.CLOSED
    report = {
        "schema": "capability_acquisition_vertical_test.v1",
        "injected_test_failure_recovered": inject_test_failure,
        "goal_id": goal.goal_id,
        "change_id": change_id,
        "base_revision": base,
        "candidate_revision": committed["commit"],
        "ticket_digest": ticket.digest,
        "architecture_digest": architecture.digest,
        "package_digest": admitted_package.admission_artifact.payload.get(
            "package_digest"
        ),
        "sandbox_boundary": "real_docker"
        if require_docker
        else "controlled_metadata_real_pytest",
        "controlled_boundaries": [
            "research_service",
            "engineering_decisions",
            "goal_replanning",
            "owner_authentication",
            "github_ci_and_merge",
            "runtime_process_switch",
            "external_effect",
        ],
        "physical_acceptance": "NOT_TESTED",
        "original_goal_state": completed_goal.state.value,
        "continuation": resumed.continuation.state.value,
        "reuse": reuse.selected_candidate.strategy.value,
        "stages": [
            "gap",
            "research",
            "architecture",
            "approval",
            "governed_development",
            "actual_pytest",
            "manifest",
            "candidate_verification",
            "acceptance",
            "promotion",
            "deployment",
            "package_admission",
            "activation",
            "controlled_external_acceptance",
            "original_goal_resumption",
            "original_goal_verified_completion",
            "reuse",
        ],
    }
    (tmp_path / "vertical-evidence.json").write_text(json.dumps(report, indent=2))
    report_root = os.getenv("JARVIS_E2E_REPORT_DIR")
    if report_root:
        output = Path(report_root)
        output.mkdir(parents=True, exist_ok=True)
        filename = (
            "vertical-recovery-evidence.json"
            if inject_test_failure
            else "vertical-evidence.json"
        )
        (output / filename).write_text(json.dumps(report, indent=2))
    stack.close()
