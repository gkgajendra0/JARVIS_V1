import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.autonomy import SupervisorAction, SupervisorCutoverDisposition
from jarvis.capabilities.models import (
    CapabilityCatalog,
    CapabilityDescriptor,
    CapabilityKind,
    CapabilityResult,
    CapabilityStatus,
    DiscoverySnapshot,
    DiscoveryState,
)
from jarvis.capability_acquisition.external_acceptance import (
    EXTERNAL_ACCEPTANCE_BINDING_KIND,
)
from jarvis.capability_acquisition.external_contract import (
    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
)
from jarvis.engineering_substrate.change_integration import MANIFEST_KIND
from jarvis.goal_intelligence.composition import (
    GoalIntakeDisposition,
    GoalIntakeResult,
)
from jarvis.goal_intelligence.execution import GoalPlanDispatcher
from jarvis.goal_intelligence.models import (
    ContinuationBlockerType,
    GoalContinuationV1,
    GoalKind,
    GoalState,
    MonitorPredicateV1,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeState,
    PlanNodeType,
    PlanNodeV1,
    PlanState,
)
from jarvis.goal_intelligence.monitoring import (
    GICC_MONITOR_EVENT_CONTRACT,
    MonitorEventProcessor,
    MonitorObservationBus,
    VerifiedMonitorObservationV1,
)
from jarvis.goal_intelligence.runtime import GiccApplyRuntime
from jarvis.goal_intelligence.service import GoalOrchestrator
from jarvis.goal_intelligence.store import GoalStore
from jarvis.goal_intelligence.telemetry import CapturingGiccTelemetry
from jarvis.work.models import WorkItem, WorkState, WorkType
from jarvis.work.privacy import ProtectedWorkPayloadCodec
from jarvis.work.store import SQLiteWorkStore


class FakeCapabilityRuntime:
    def __init__(self) -> None:
        self.requests = []
        self.refreshes = 0

    def refresh_catalog(self):
        self.refreshes += 1

    def execute(self, request):
        self.requests.append(request)
        return CapabilityResult(
            status=CapabilityStatus.SUCCEEDED,
            capability_key=request.capability_key,
            operation=request.operation,
            data={
                "opened": True,
                "verification_passed": True,
            },
            provenance=("fake-runtime",),
        )


class StaticCoordinator:
    def __init__(self, result: GoalIntakeResult) -> None:
        self.result = result

    async def pursue(self, *, conversation, turn):
        del conversation, turn
        return self.result

    async def continue_goal(self, goal_id: str):
        del goal_id
        return self.result

    def current_plan_validation_context(self, goal_id: str):
        del goal_id
        return object()


class CapabilityContinuationCoordinator:
    def __init__(self, store: GoalStore) -> None:
        self.store = store
        self.calls = 0

    async def pursue(self, *, conversation, turn):
        del conversation, turn
        raise AssertionError("pursue is not used in this test")

    async def continue_goal(self, goal_id: str) -> GoalIntakeResult:
        self.calls += 1
        current = self.store.get_goal(goal_id)
        assert current is not None
        planned = self.store.update_goal_state(
            current.goal_id,
            GoalState.PLANNED,
            expected_revision=current.goal_revision,
        )
        plan = _put_plan(self.store, planned)
        return GoalIntakeResult(
            disposition=GoalIntakeDisposition.PLAN_READY,
            goal=planned,
            plan=plan,
        )


def _store(tmp_path: Path) -> GoalStore:
    return GoalStore(
        SQLiteWorkStore(
            tmp_path / "work.sqlite3",
            payload_codec=ProtectedWorkPayloadCodec(b"r" * 32),
        )
    )


def _goal(store: GoalStore, *, state: GoalState) -> OwnerGoalV2:
    return store.create_goal(
        OwnerGoalV2.create(
            source_session_id="runtime-session",
            source_turn_id="runtime-turn",
            exact_owner_request="Open Calculator.",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Calculator is open.",
            completion_predicates=("app_open",),
            state=state,
            created_at="2026-10-01T18:10:00+00:00",
        )
    )


def _put_plan(
    store: GoalStore,
    goal: OwnerGoalV2,
    *,
    plan_revision: int = 1,
) -> PlanGraphV1:
    action = PlanNodeV1.create(
        plan_identity=f"{goal.goal_id}:{goal.goal_revision}",
        ordinal=0,
        node_type=PlanNodeType.ACTION,
        summary="Open Calculator.",
        capability_key="app:lifecycle",
        operation="open_app",
        parameters={"app": "Calculator"},
        postcondition_ref="app_open",
    )
    verify = PlanNodeV1.create(
        plan_identity=f"{goal.goal_id}:{goal.goal_revision}",
        ordinal=1,
        node_type=PlanNodeType.VERIFY,
        summary="Verify Calculator opened.",
        postcondition_ref="app_open",
    )
    return store.put_plan(
        PlanGraphV1.create(
            goal_id=goal.goal_id,
            goal_revision=goal.goal_revision,
            plan_revision=plan_revision,
            nodes=(action, verify),
            edges=((action.node_id, verify.node_id),),
            root_node_ids=(action.node_id,),
            completion_node_ids=(verify.node_id,),
            created_at="2026-10-01T18:11:00+00:00",
        )
    )


def _runtime(
    store: GoalStore,
    coordinator,
    capability_runtime: FakeCapabilityRuntime,
    *,
    replan_controller=None,
    change_store=None,
    supervisor_cutover=None,
) -> GiccApplyRuntime:
    dispatcher = GoalPlanDispatcher(
        store=store,
        orchestrator=GoalOrchestrator(
            goal_store=store,
            capability_runtime=capability_runtime,
        ),
    )
    return GiccApplyRuntime(
        store=store,
        world=object(),  # type: ignore[arg-type]
        coordinator=coordinator,  # type: ignore[arg-type]
        dispatcher=dispatcher,
        telemetry=CapturingGiccTelemetry(),
        replan_controller=replan_controller,
        change_store=change_store,
        capability_runtime=capability_runtime,  # type: ignore[arg-type]
        supervisor_cutover=supervisor_cutover,
    )


@pytest.mark.asyncio
async def test_foreground_plan_ready_goal_reaches_verified_completion(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    goal = _goal(store, state=GoalState.PLANNED)
    plan = _put_plan(store, goal)
    capability_runtime = FakeCapabilityRuntime()
    runtime = _runtime(
        store,
        StaticCoordinator(
            GoalIntakeResult(
                disposition=GoalIntakeDisposition.PLAN_READY,
                goal=goal,
                plan=plan,
            )
        ),
        capability_runtime,
    )

    result = await runtime.pursue(conversation=object(), turn=object())

    assert result.goal is not None
    assert result.goal.state is GoalState.COMPLETED
    assert result.plan is not None
    assert result.plan.state is PlanState.SUCCEEDED
    assert len(capability_runtime.requests) == 1


class FakeMonitorCapabilityRuntime(FakeCapabilityRuntime):
    def __init__(self) -> None:
        super().__init__()
        descriptor = CapabilityDescriptor.create(
            capability_id="scene",
            source_id="vision",
            kind=CapabilityKind.LOCAL_READ,
            name="Verified scene observer",
            description="Publishes verified monitor observations.",
            operations=("verify_scene_condition",),
            metadata={
                "semantic_capability_family": "vision.perceive",
                "target_entity_types": ["camera"],
                "observation_operations": ["verify_scene_condition"],
                "monitor_event_contract": GICC_MONITOR_EVENT_CONTRACT,
            },
            execution_enabled=True,
        )
        self._catalog = CapabilityCatalog(
            sources=(
                DiscoverySnapshot(
                    source_id="vision",
                    state=DiscoveryState.AVAILABLE,
                    capabilities=(descriptor,),
                ),
            ),
            capabilities=(descriptor,),
        )

    @property
    def catalog(self):
        return self._catalog


@pytest.mark.asyncio
async def test_verified_monitor_event_completes_goal_and_notifies_once(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    goal = store.create_goal(
        OwnerGoalV2.create(
            source_session_id="monitor-session",
            source_turn_id="monitor-turn",
            exact_owner_request="Tell me when a delivery agent is at the main gate.",
            goal_kind=GoalKind.MONITORING,
            desired_outcome="A delivery agent is verified at the main gate.",
            completion_predicates=("delivery_agent_verified",),
            state=GoalState.MONITORING,
            created_at="2026-10-01T18:20:00+00:00",
        )
    )
    predicate = store.put_monitor_predicate(
        MonitorPredicateV1.create(
            goal_id=goal.goal_id,
            source_entity_ids=("main_gate_camera",),
            observation_capabilities=("vision.perceive",),
            semantic_condition="delivery agent is verified at the main gate",
            candidate_trigger_strategy="event_first",
            stability_window=0.0,
            cooldown=60.0,
            timeout=None,
            completion_policy="complete_once",
            notification_policy="owner",
            verification_requirement="delivery_agent_verified",
        )
    )
    node = PlanNodeV1.create(
        plan_identity=f"{goal.goal_id}:{goal.goal_revision}",
        ordinal=0,
        node_type=PlanNodeType.MONITOR,
        summary="Monitor the verified gate condition.",
        monitor_predicate_id=predicate.predicate_id,
    )
    proposed = PlanGraphV1.create(
        goal_id=goal.goal_id,
        goal_revision=goal.goal_revision,
        nodes=(node,),
        edges=(),
        root_node_ids=(node.node_id,),
        completion_node_ids=(node.node_id,),
        created_at="2026-10-01T18:21:00+00:00",
    )
    waiting = proposed.with_node_state(
        node.node_id,
        PlanNodeState.WAITING,
        plan_state=PlanState.WAITING,
    )
    waiting = store.put_plan(waiting)
    work = store.work.create(
        WorkItem(
            request="Monitor verified gate condition.",
            work_type=WorkType.MONITORING,
            source_session_id=f"gicc-monitor:{goal.goal_id}",
            source_turn_id=f"predicate:{predicate.predicate_id}",
            state=WorkState.WAITING_RESOURCE,
            status_detail="waiting for monitored event",
        )
    )
    store.create_monitor_runtime_state(
        predicate_id=predicate.predicate_id,
        goal_id=goal.goal_id,
        work_id=work.work_id,
        payload={
            "strategy": "native_event",
            "continuation_id": None,
            "plan_id": waiting.plan_id,
            "node_id": node.node_id,
            "source_entity_ids": list(predicate.source_entity_ids),
            "started_at_epoch": 100.0,
            "last_observation_digest": None,
            "stable_since_epoch": None,
            "last_trigger_epoch": None,
            "notification_event_key": None,
            "notified": False,
        },
        updated_at="2026-10-01T18:22:00+00:00",
    )

    capability_runtime = FakeMonitorCapabilityRuntime()
    bus = MonitorObservationBus()
    telemetry = CapturingGiccTelemetry()
    dispatcher = GoalPlanDispatcher(
        store=store,
        orchestrator=GoalOrchestrator(
            goal_store=store,
            capability_runtime=capability_runtime,
        ),
    )
    runtime = GiccApplyRuntime(
        store=store,
        world=object(),  # type: ignore[arg-type]
        coordinator=StaticCoordinator(
            GoalIntakeResult(
                disposition=GoalIntakeDisposition.PLAN_READY,
                goal=goal,
                plan=waiting,
            )
        ),  # type: ignore[arg-type]
        dispatcher=dispatcher,
        telemetry=telemetry,
        capability_runtime=capability_runtime,  # type: ignore[arg-type]
        monitor_processor=MonitorEventProcessor(
            goal_store=store,
            work_store=store.work,
            telemetry=telemetry,
        ),
        monitor_bus=bus,
        reconcile_interval_seconds=60.0,
    )
    runtime.start()
    try:
        event = VerifiedMonitorObservationV1(
            predicate_id=predicate.predicate_id,
            source_capability_key="vision:scene",
            source_operation="verify_scene_condition",
            observation_digest="observation-1",
            condition_met=True,
            observed_at_epoch=101.0,
            evidence_refs=("verifier:gate:1",),
        )
        bus.publish(event)
        await asyncio.sleep(0.1)
        bus.publish(event)
        await asyncio.sleep(0.1)
    finally:
        await runtime.close()

    latest_goal = store.get_goal(goal.goal_id)
    latest_plan = store.get_plan(waiting.plan_id)
    latest_work = store.work.require(work.work_id)
    assert latest_goal is not None
    assert latest_goal.state is GoalState.COMPLETED
    assert latest_plan is not None
    assert latest_plan.state is PlanState.SUCCEEDED
    assert latest_work.state is WorkState.COMPLETED
    assert latest_work.result["evidence_refs"] == ["verifier:gate:1"]
    deliveries = [
        item
        for item in store.work.list_pending_deliveries(limit=20)
        if item.event_key == f"gicc-monitor:{predicate.predicate_id}:complete"
    ]
    assert len(deliveries) == 1


class SequencedVerificationRuntime(FakeCapabilityRuntime):
    def __init__(self, values: list[bool]) -> None:
        super().__init__()
        self.values = list(values)

    def execute(self, request):
        self.requests.append(request)
        verified = self.values.pop(0)
        return CapabilityResult(
            status=CapabilityStatus.SUCCEEDED,
            capability_key=request.capability_key,
            operation=request.operation,
            data={
                "opened": verified,
                "verification_passed": verified,
            },
            provenance=("fake-runtime",),
        )


class FakeVerificationReplanController:
    def __init__(self, store: GoalStore) -> None:
        self.store = store
        self.calls = 0

    async def replan(
        self,
        *,
        goal,
        failed_plan,
        context,
        prior_evidence,
    ):
        del context
        assert prior_evidence
        self.calls += 1
        current = self.store.get_goal(goal.goal_id)
        assert current is not None
        replacement = _put_plan(
            self.store,
            current,
            plan_revision=failed_plan.plan_revision + 1,
        )
        return SimpleNamespace(replacement=replacement)


@pytest.mark.asyncio
async def test_failed_verification_replans_once_and_completes(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    goal = _goal(store, state=GoalState.PLANNED)
    plan = _put_plan(store, goal)
    capability_runtime = SequencedVerificationRuntime([False, True])
    coordinator = StaticCoordinator(
        GoalIntakeResult(
            disposition=GoalIntakeDisposition.PLAN_READY,
            goal=goal,
            plan=plan,
        )
    )
    replan = FakeVerificationReplanController(store)
    runtime = _runtime(
        store,
        coordinator,
        capability_runtime,
        replan_controller=replan,
    )

    result = await runtime.pursue(conversation=object(), turn=object())

    assert result.goal is not None
    assert result.goal.state is GoalState.COMPLETED
    assert result.plan is not None
    assert result.plan.state is PlanState.SUCCEEDED
    assert result.plan.plan_revision == 2
    assert replan.calls == 1
    assert len(capability_runtime.requests) == 2


class FakePhase9WorkStore:
    def __init__(self) -> None:
        self.items = {}
        self.steps = {}

    def get(self, work_id: str):
        return self.items.get(work_id)

    def list_steps(self, work_id: str):
        return tuple(self.steps.get(work_id, ()))


def _completed_external_step(kind: str, observation: dict[str, object]):
    return SimpleNamespace(
        kind=kind,
        state=SimpleNamespace(value="completed"),
        observation=observation,
    )


class FakePhase9ChangeStore:
    def __init__(self) -> None:
        self.acceptance = None
        self.binding = None
        self.work = FakePhase9WorkStore()
        self.candidate = SimpleNamespace(
            artifact_id="candidate-tv",
            digest="c" * 64,
            payload={
                "package_id": "tv.control.package",
                "package_version": "1.0.0",
                "package_digest": "p" * 64,
                "development_work_id": "work-development",
            },
        )
        self.admission = SimpleNamespace(
            artifact_id="admission-tv",
            digest="d" * 64,
            payload={
                "candidate_artifact_id": self.candidate.artifact_id,
                "candidate_artifact_digest": self.candidate.digest,
                "package_id": "tv.control.package",
                "package_version": "1.0.0",
                "package_digest": "p" * 64,
            },
        )
        self.activation = SimpleNamespace(
            artifact_id="activation-tv",
            digest="a" * 64,
            payload={
                "candidate_artifact_id": self.candidate.artifact_id,
                "candidate_artifact_digest": self.candidate.digest,
                "admission_artifact_id": self.admission.artifact_id,
                "admission_artifact_digest": self.admission.digest,
                "package_id": "tv.control.package",
                "package_version": "1.0.0",
                "package_digest": "p" * 64,
                "effective_enabled": True,
                "authority_session_id": "owner-session",
                "source_turn_id": "activation-turn",
            },
        )
        self.architecture = SimpleNamespace(
            artifact_id="architecture-tv",
            digest="h" * 64,
            payload={
                "owner_acceptance_contract_ids": [
                    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT
                ]
            },
        )
        self.goal_artifact = SimpleNamespace(
            artifact_id="goal-tv-artifact",
            digest="g" * 64,
            payload={"schema": "owner_capability_goal.v1"},
        )
        self.manifest = SimpleNamespace(
            artifact_id="manifest-tv",
            digest="m" * 64,
            payload={"schema": "substrate_manifest.v1"},
        )
        self.link = SimpleNamespace(
            payload={
                "schema": "gicc_phase9_gap_link.v2",
                "motivating_goal_id": None,
                "gap_id": "gap-tv-control",
                "engineering_change_id": "change-tv",
                "request_id": "phase9-test",
                "request_digest": "r" * 64,
                "acquisition_work_id": "phase9-work",
            }
        )

    def bind_goal(self, goal_id: str) -> None:
        self.link.payload["motivating_goal_id"] = goal_id

    def stage_for_work(self, work_id: str):
        if work_id != "phase9-work":
            return None
        return SimpleNamespace(change_id="change-tv")

    def latest_artifact(self, change_id: str, kind: str):
        assert change_id == "change-tv"
        return {
            "gicc_capability_gap_link": self.link,
            "architecture": self.architecture,
            "capability_candidate": self.candidate,
            "capability_package_admission": self.admission,
            "capability_lifecycle_activation": self.activation,
            EXTERNAL_ACCEPTANCE_BINDING_KIND: self.binding,
            "capability_external_acceptance": self.acceptance,
            "capability_goal": self.goal_artifact,
            MANIFEST_KIND: self.manifest,
        }.get(kind)

    def pass_current_acceptance(self) -> None:
        work_id = "work-external-tv"
        self.binding = SimpleNamespace(
            artifact_id="external-binding-tv",
            digest="i" * 64,
            payload={
                "schema": "capability_external_acceptance_binding.v1",
                "work_id": work_id,
                "candidate_artifact_id": self.candidate.artifact_id,
                "candidate_artifact_digest": self.candidate.digest,
                "activation_artifact_id": self.activation.artifact_id,
                "activation_artifact_digest": self.activation.digest,
                "architecture_artifact_id": self.architecture.artifact_id,
                "architecture_artifact_digest": self.architecture.digest,
                "manifest_artifact_id": self.manifest.artifact_id,
                "manifest_artifact_digest": self.manifest.digest,
                "goal_artifact_id": self.goal_artifact.artifact_id,
                "goal_artifact_digest": self.goal_artifact.digest,
                "acceptance_contract_id": PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
                "authority_session_id": self.activation.payload["authority_session_id"],
                "source_turn_id": self.activation.payload["source_turn_id"],
            },
        )
        self.work.items[work_id] = SimpleNamespace(
            work_type=WorkType.EXTERNAL_ACCEPTANCE,
            source_session_id="phase9-external:change-tv",
            source_turn_id=self.activation.artifact_id,
            dependencies=(self.candidate.payload["development_work_id"],),
            state=WorkState.COMPLETED,
        )
        self.work.steps[work_id] = (
            _completed_external_step(
                "external_acceptance_inspect", {"inspected": True}
            ),
            _completed_external_step("external_acceptance_prepare", {"prepared": True}),
            _completed_external_step("external_acceptance_invoke", {"invoked": True}),
            _completed_external_step(
                "external_acceptance_record",
                {"acceptance_recorded": True},
            ),
        )
        self.acceptance = SimpleNamespace(
            artifact_id="external-acceptance-tv",
            digest="e" * 64,
            payload={
                "schema": "capability_external_acceptance.v1",
                "work_id": work_id,
                "binding_artifact_id": self.binding.artifact_id,
                "binding_artifact_digest": self.binding.digest,
                "verdict": "pass",
                "candidate_artifact_id": self.candidate.artifact_id,
                "candidate_artifact_digest": self.candidate.digest,
                "activation_artifact_id": self.activation.artifact_id,
                "activation_artifact_digest": self.activation.digest,
            },
        )


@pytest.mark.asyncio
async def test_external_acceptance_fences_capability_continuation(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    goal = _goal(store, state=GoalState.WAITING_CAPABILITY)
    store.put_continuation(
        GoalContinuationV1.create(
            goal_id=goal.goal_id,
            plan_id="phase9-acquisition-plan",
            blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
            blocked_by_id="gap-tv-control",
            resume_node_id="resume-tv-control",
            work_ids=("phase9-work",),
            goal_revision=goal.goal_revision,
            created_at="2026-10-01T18:13:00+00:00",
        )
    )
    capability_runtime = FakeCapabilityRuntime()
    coordinator = CapabilityContinuationCoordinator(store)
    changes = FakePhase9ChangeStore()
    changes.bind_goal(goal.goal_id)
    runtime = _runtime(
        store,
        coordinator,
        capability_runtime,
        change_store=changes,
    )

    blocked = await runtime.reconcile_once()

    assert blocked == 0
    assert coordinator.calls == 0
    assert store.get_goal(goal.goal_id).state is GoalState.WAITING_CAPABILITY

    changes.pass_current_acceptance()
    advanced = await runtime.reconcile_once()

    latest = store.get_goal(goal.goal_id)
    assert advanced == 1
    assert coordinator.calls == 1
    assert latest is not None
    assert latest.state is GoalState.COMPLETED


@pytest.mark.asyncio
async def test_legacy_gicc_activation_cannot_resume_without_external_acceptance_contract(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    goal = _goal(store, state=GoalState.WAITING_CAPABILITY)
    store.put_continuation(
        GoalContinuationV1.create(
            goal_id=goal.goal_id,
            plan_id="phase9-legacy-plan",
            blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
            blocked_by_id="gap-tv-control",
            resume_node_id="resume-tv-control",
            work_ids=("phase9-work",),
            goal_revision=goal.goal_revision,
            created_at="2026-10-01T18:13:30+00:00",
        )
    )
    changes = FakePhase9ChangeStore()
    changes.bind_goal(goal.goal_id)
    changes.architecture.payload["owner_acceptance_contract_ids"] = ()
    coordinator = CapabilityContinuationCoordinator(store)
    runtime = _runtime(
        store,
        coordinator,
        FakeCapabilityRuntime(),
        change_store=changes,
    )

    advanced = await runtime.reconcile_once()

    latest = store.get_goal(goal.goal_id)
    assert advanced == 0
    assert coordinator.calls == 0
    assert latest is not None
    assert latest.state is GoalState.WAITING_CAPABILITY


@pytest.mark.asyncio
async def test_background_existing_capability_reuse_needs_no_engineering_work(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    goal = _goal(store, state=GoalState.WAITING_CAPABILITY)
    store.put_continuation(
        GoalContinuationV1.create(
            goal_id=goal.goal_id,
            plan_id="phase9-reuse-plan",
            blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
            blocked_by_id="gap-existing-capability",
            resume_node_id="resume-existing-capability",
            work_ids=(),
            goal_revision=goal.goal_revision,
            created_at="2026-10-01T18:11:30+00:00",
        )
    )
    capability_runtime = FakeCapabilityRuntime()
    coordinator = CapabilityContinuationCoordinator(store)
    runtime = _runtime(
        store,
        coordinator,
        capability_runtime,
        change_store=FakePhase9ChangeStore(),
    )

    advanced = await runtime.reconcile_once()

    latest = store.get_goal(goal.goal_id)
    assert advanced == 1
    assert coordinator.calls == 1
    assert latest is not None
    assert latest.state is GoalState.COMPLETED


@pytest.mark.asyncio
async def test_background_capability_continuation_uses_same_dispatcher(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    goal = _goal(store, state=GoalState.WAITING_CAPABILITY)
    capability_runtime = FakeCapabilityRuntime()
    coordinator = CapabilityContinuationCoordinator(store)
    runtime = _runtime(store, coordinator, capability_runtime)
    anchor = store.work.create(
        WorkItem(
            request="Acquire TV control capability.",
            work_type=WorkType.RESEARCH,
            source_session_id="phase9-session",
            source_turn_id="phase9-turn",
            state=WorkState.COMPLETED,
        )
    )
    store.put_continuation(
        GoalContinuationV1.create(
            goal_id=goal.goal_id,
            plan_id="phase9-acquisition-plan",
            blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
            blocked_by_id="gap-tv-control",
            resume_node_id="resume-tv-control",
            work_ids=(anchor.work_id,),
            goal_revision=goal.goal_revision,
            created_at="2026-10-01T18:12:00+00:00",
        )
    )

    advanced = await runtime.reconcile_once()

    latest_goal = store.get_goal(goal.goal_id)
    latest_plan = store.latest_plan_for_goal(goal.goal_id)
    assert advanced == 1
    assert coordinator.calls == 1
    assert capability_runtime.refreshes == 1
    assert latest_goal is not None
    assert latest_goal.state is GoalState.COMPLETED
    assert latest_plan is not None
    assert latest_plan.state is PlanState.SUCCEEDED
    assert len(capability_runtime.requests) == 1
    deliveries = store.work.list_pending_deliveries(limit=10)
    goal_deliveries = [
        item
        for item in deliveries
        if item.event_key == f"gicc-goal:{goal.goal_id}:completed"
    ]
    assert len(goal_deliveries) == 1
    assert "Open Calculator." in goal_deliveries[0].message


class TerminalSupervisorCutover:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def coordinate(self, goal_id: str):
        self.calls.append(goal_id)
        return SimpleNamespace(
            action=SupervisorAction.TERMINAL,
            disposition=SupervisorCutoverDisposition.TERMINAL_OBSERVED,
            accepted=True,
            mutation_performed=False,
            decision_digest="terminal-decision-digest",
            change_id="change-terminal",
        )


@pytest.mark.asyncio
async def test_terminal_capability_outcome_fails_goal_instead_of_looping(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    goal = _goal(store, state=GoalState.WAITING_CAPABILITY)
    anchor = store.work.create(
        WorkItem(
            request="Terminal capability acquisition.",
            work_type=WorkType.RESEARCH,
            source_session_id="phase9-terminal-session",
            source_turn_id="phase9-terminal-turn",
            state=WorkState.FAILED,
            status_detail="terminal capability failure",
        )
    )
    store.put_continuation(
        GoalContinuationV1.create(
            goal_id=goal.goal_id,
            plan_id="phase9-terminal-plan",
            blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
            blocked_by_id="gap-terminal",
            resume_node_id="resume-terminal",
            work_ids=(anchor.work_id,),
            goal_revision=goal.goal_revision,
            created_at="2026-10-01T18:12:30+00:00",
        )
    )
    coordinator = CapabilityContinuationCoordinator(store)
    cutover = TerminalSupervisorCutover()
    runtime = _runtime(
        store,
        coordinator,
        FakeCapabilityRuntime(),
        supervisor_cutover=cutover,
    )

    advanced = await runtime.reconcile_once()

    latest = store.get_goal(goal.goal_id)
    assert advanced == 1
    assert cutover.calls == [goal.goal_id]
    assert coordinator.calls == 0
    assert latest is not None
    assert latest.state is GoalState.FAILED
    deliveries = store.work.list_pending_deliveries(limit=20)
    terminal = [
        item
        for item in deliveries
        if item.event_key == f"gicc-goal:{goal.goal_id}:failed"
    ]
    assert len(terminal) == 1


class RecordingSupervisorCutover:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def coordinate(self, goal_id: str):
        self.calls.append(goal_id)
        return SimpleNamespace(
            action=SupervisorAction.WAIT_RESOURCE,
            disposition=SupervisorCutoverDisposition.AWAIT_RUNTIME,
            accepted=True,
            mutation_performed=False,
            decision_digest="shadow-decision-digest",
        )


class RejectingSupervisorCutover:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def coordinate(self, goal_id: str):
        self.calls.append(goal_id)
        return SimpleNamespace(
            action=None,
            disposition=SupervisorCutoverDisposition.REJECTED,
            accepted=False,
            mutation_performed=False,
            decision_digest=None,
        )


@pytest.mark.asyncio
async def test_waiting_capability_runs_supervisor_before_legacy_continuation(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    goal = _goal(store, state=GoalState.WAITING_CAPABILITY)
    store.put_continuation(
        GoalContinuationV1.create(
            goal_id=goal.goal_id,
            plan_id="phase9-supervisor-plan",
            blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
            blocked_by_id="gap-tv-control",
            resume_node_id="resume-tv-control",
            work_ids=("phase9-work",),
            goal_revision=goal.goal_revision,
            created_at="2026-10-01T18:13:00+00:00",
        )
    )
    changes = FakePhase9ChangeStore()
    changes.bind_goal(goal.goal_id)
    coordinator = CapabilityContinuationCoordinator(store)
    cutover = RecordingSupervisorCutover()
    runtime = _runtime(
        store,
        coordinator,
        FakeCapabilityRuntime(),
        change_store=changes,
        supervisor_cutover=cutover,
    )

    advanced = await runtime.reconcile_once()

    assert advanced == 0
    assert cutover.calls == [goal.goal_id]
    assert coordinator.calls == 0
    latest = store.get_goal(goal.goal_id)
    assert latest is not None
    assert latest.state is GoalState.WAITING_CAPABILITY


@pytest.mark.asyncio
async def test_rejected_supervisor_cutover_fences_ready_capability_continuation(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    goal = _goal(store, state=GoalState.WAITING_CAPABILITY)
    store.put_continuation(
        GoalContinuationV1.create(
            goal_id=goal.goal_id,
            plan_id="phase9-supervisor-rejected-plan",
            blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
            blocked_by_id="gap-tv-control",
            resume_node_id="resume-tv-control",
            work_ids=("phase9-work",),
            goal_revision=goal.goal_revision,
            created_at="2026-10-01T18:14:00+00:00",
        )
    )
    changes = FakePhase9ChangeStore()
    changes.bind_goal(goal.goal_id)
    changes.pass_current_acceptance()
    coordinator = CapabilityContinuationCoordinator(store)
    cutover = RejectingSupervisorCutover()
    runtime = _runtime(
        store,
        coordinator,
        FakeCapabilityRuntime(),
        change_store=changes,
        supervisor_cutover=cutover,
    )

    advanced = await runtime.reconcile_once()

    latest = store.get_goal(goal.goal_id)
    assert advanced == 0
    assert cutover.calls == [goal.goal_id]
    assert coordinator.calls == 0
    assert latest is not None
    assert latest.state is GoalState.WAITING_CAPABILITY
