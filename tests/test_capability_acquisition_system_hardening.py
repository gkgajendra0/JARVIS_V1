from __future__ import annotations

import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from jarvis.autonomy import (
    AutonomyMode,
    SupervisorAction,
    SupervisorCutoverController,
    SupervisorCutoverDisposition,
)
from jarvis.capability_acquisition.external_contract import (
    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT,
)
from jarvis.capability_acquisition.hardening import (
    CapabilitySystemInvariantCode,
    blocking_capability_workspace_invariant_codes,
    _check_external_acceptance_binding,
    _check_gicc_external_acceptance_contract,
    assert_capability_system_invariants,
    inspect_capability_system_invariants,
    inspect_capability_workspace_invariants,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.outcomes import classify_work_system_outcome
from jarvis.goal_intelligence.ledgers import build_progress_ledger
from jarvis.goal_intelligence.models import (
    CapabilityGapState,
    CapabilityGapV1,
    CapabilityRequirementGraphV1,
    CapabilityRequirementV1,
    ContinuationBlockerType,
    GoalContinuationV1,
    GoalKind,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeType,
    PlanNodeV1,
    WorldEntityRefV1,
)
from jarvis.goal_intelligence.monitoring import GICC_MONITOR_EVENT_CONTRACT
from jarvis.goal_intelligence.phase9 import Phase9AcquisitionRequestV2
from jarvis.goal_intelligence.store import GoalStore
from jarvis.goal_intelligence.workspace import ObjectiveWorkspaceProjector
from jarvis.work.models import WorkItem, WorkPriority, WorkState, WorkStep
from jarvis.work.store import SQLiteWorkStore


class _Backend:
    def __init__(self) -> None:
        self.submissions: list[str] = []

    def submit(self, work_id: str, *, priority: WorkPriority) -> str:
        del priority
        self.submissions.append(work_id)
        return work_id


def _now() -> str:
    return datetime.now(UTC).isoformat()


class CapabilityAcquisitionLifecycleMachine(RuleBasedStateMachine):
    """Generate cross-component Phase-9 lifecycle sequences over real stores."""

    def __init__(self) -> None:
        super().__init__()
        self._tmp = tempfile.TemporaryDirectory(prefix="jarvis-phase9-stateful-")
        self._db_path = Path(self._tmp.name) / "work.sqlite3"
        self._bootstrap()

    def teardown(self) -> None:
        self._tmp.cleanup()

    def _attach_runtime(self) -> None:
        self.work = SQLiteWorkStore(self._db_path)
        self.goals = GoalStore(self.work)
        self.changes = ChangeStore(
            self.work,
            processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
        )
        self.backend = _Backend()
        self.coordinator = ChangeCoordinator(self.changes, self.backend)
        self.projector = ObjectiveWorkspaceProjector(
            goal_store=self.goals,
            change_store=self.changes,
        )

        def retry_failed(work_id: str) -> None:
            item = self.work.require(work_id)
            if item.state is not WorkState.FAILED:
                raise AssertionError(
                    "Supervisor attempted RETRY for non-failed canonical work"
                )
            stage = self.changes.stage_for_work(work_id)
            if stage is not None:
                change = self.changes.require(stage.change_id)
                if change.state is ChangeState.FAILED:
                    self.coordinator.prepare_failed_work_retry(work_id)
            current = self.work.require(work_id)
            self.work.save(
                current.transition(
                    WorkState.RETRYING,
                    status_detail="retry requested by global_supervisor",
                ),
                expected_version=current.version,
            )

        self.supervisor = SupervisorCutoverController(
            projector=self.projector,
            change_coordinator=self.coordinator,
            mode=AutonomyMode.ASSISTED,
            retry_failed_work=retry_failed,
        )

    def _bootstrap(self) -> None:
        self._attach_runtime()
        entity = self.goals.put_entity(
            WorldEntityRefV1.create(
                entity_type="television",
                canonical_name="Stateful Test Television",
                provenance_refs=("test:inventory",),
            )
        )
        goal = self.goals.create_goal(
            OwnerGoalV2.create(
                source_session_id="stateful-session",
                source_turn_id="stateful-turn",
                exact_owner_request="Play a movie on the living-room television.",
                goal_kind=GoalKind.ONE_SHOT,
                desired_outcome="The requested movie is playing on the target television.",
                completion_predicates=("media_playing",),
                referenced_entity_ids=(entity.entity_id,),
            )
        )
        requirement = CapabilityRequirementV1.create(
            goal_id=goal.goal_id,
            semantic_capability="media_player.control",
            operation="play_media",
            target_entity_id=entity.entity_id,
            target_entity_type="television",
            reason="Playback requires a reusable media-control capability.",
        )
        graph = self.goals.put_requirement_graph(
            CapabilityRequirementGraphV1.create(
                goal_id=goal.goal_id,
                requirements=(requirement,),
            )
        )
        gap = self.goals.put_gap(
            CapabilityGapV1.create(
                goal_id=goal.goal_id,
                requirement_ids=graph.requirement_ids,
                reusable_capability_family="media_player.control",
                target_entity_type="television",
                target_entity_id=entity.entity_id,
                minimum_required_operations=("play_media",),
                missing_reason_codes=("capability_missing",),
            )
        )
        node = PlanNodeV1.create(
            plan_identity=goal.goal_id,
            ordinal=0,
            node_type=PlanNodeType.ACQUIRE_CAPABILITY,
            summary="Acquire media control and resume playback.",
            gap_id=gap.gap_id,
        )
        plan = self.goals.put_plan(
            PlanGraphV1.create(
                goal_id=goal.goal_id,
                goal_revision=goal.goal_revision,
                nodes=(node,),
                edges=(),
                root_node_ids=(node.node_id,),
                completion_node_ids=(node.node_id,),
            )
        )
        request = Phase9AcquisitionRequestV2.create(gap=gap, goal=goal)
        change = self.coordinator.start(
            "Acquire governed media-player control.",
            request.bridge_source_session_id,
            request.bridge_source_turn_id,
            process_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
            process_version=OWNER_CAPABILITY_ACQUISITION_PROCESS.version,
        )
        source = self.changes.current_stage_attempt(change.change_id, "acquisition")
        assert source is not None
        self.changes.add_artifact(
            change.change_id,
            kind="gicc_capability_gap_link",
            payload={
                "schema": "gicc_phase9_gap_link.v2",
                "request_id": request.request_id,
                "request_digest": request.digest,
                "motivating_goal_id": goal.goal_id,
                "gap_id": gap.gap_id,
                "engineering_change_id": change.change_id,
                "acquisition_work_id": source.work_id,
                "reusable_capability_family": request.reusable_capability_family,
                "minimum_required_operations": list(
                    request.minimum_required_operations
                ),
                "target_entity_type": request.target_entity_type,
                "target_entity_id": request.target_entity_id,
                "monitor_event_contract_required": (
                    request.monitor_event_contract_required
                ),
                "monitor_event_contract": (
                    GICC_MONITOR_EVENT_CONTRACT
                    if request.monitor_event_contract_required
                    else None
                ),
            },
        )
        self.goals.put_continuation(
            GoalContinuationV1.create(
                goal_id=goal.goal_id,
                plan_id=plan.plan_id,
                blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
                blocked_by_id=gap.gap_id,
                resume_node_id=node.node_id,
                work_ids=(source.work_id,),
                goal_revision=goal.goal_revision,
            )
        )
        self.goal_id = goal.goal_id
        self.gap_id = gap.gap_id
        self.change_id = change.change_id

    def _change(self):
        return self.changes.require(self.change_id)

    def _workspace(self):
        return self.projector.project(self.goal_id)

    def _progress(self):
        return build_progress_ledger(self._workspace())

    def _active_work(self) -> WorkItem | None:
        work_id = self._progress().active_work_id
        return None if work_id is None else self.work.require(work_id)

    def _current_source(self):
        stage = self.changes.current_stage_attempt(self.change_id, "acquisition")
        return None if stage is None else self.work.require(stage.work_id)

    def _current_development(self):
        stage = self.changes.current_stage_attempt(self.change_id, "development")
        return None if stage is None else self.work.require(stage.work_id)

    def _approve_current_architecture(self) -> None:
        architecture = self.changes.latest_artifact(self.change_id, "architecture")
        assert architecture is not None
        change = self._change()
        assert change.state is ChangeState.ARCHITECTURE_READY

        waiting = self.changes.transition(
            self.change_id,
            ChangeState.WAITING_OWNER_APPROVAL,
            expected_version=change.version,
        )
        gate_id = "gate_" + uuid.uuid4().hex[:16]
        decided_at = _now()
        with self.work._lock, self.work._connect() as db:
            db.execute(
                """INSERT INTO engineering_change_gates (
                gate_id, change_id, kind, artifact_id, artifact_digest, created_at
                ) VALUES (?, ?, 'architecture', ?, ?, ?)""",
                (
                    gate_id,
                    self.change_id,
                    architecture.artifact_id,
                    architecture.digest,
                    decided_at,
                ),
            )
            db.execute(
                """INSERT INTO engineering_change_decisions (
                gate_id, approved, actor_id, source_session_id, source_turn_id,
                request_key, decided_at
                ) VALUES (?, 1, ?, ?, ?, ?, ?)""",
                (
                    gate_id,
                    "owner",
                    "stateful-session",
                    "stateful-approval",
                    f"stateful:{architecture.artifact_id}",
                    decided_at,
                ),
            )
            db.execute(
                """UPDATE engineering_changes
                SET state=?, version=version+1, updated_at=?
                WHERE change_id=? AND version=?""",
                (
                    ChangeState.APPROVED_FOR_BUILD.value,
                    decided_at,
                    self.change_id,
                    waiting.version,
                ),
            )
            self.changes._event(
                db,
                self.change_id,
                f"decision:{gate_id}",
                "decision",
                {
                    "approved": True,
                    "gate_id": gate_id,
                    "actor_id": "owner",
                    "source_session_id": "stateful-session",
                    "source_turn_id": "stateful-approval",
                },
            )

    @rule()
    def restart_runtime_projection(self) -> None:
        """Simulate process restart against the same durable canonical database."""

        self._attach_runtime()

    @rule()
    def duplicate_reconcile(self) -> None:
        """Replay coordinator work without inventing another stage attempt."""

        state = self._change().state
        if state not in {
            ChangeState.WAITING_OWNER_APPROVAL,
            ChangeState.VERIFYING,
            ChangeState.WAITING_OWNER_ACCEPTANCE,
            ChangeState.READY_FOR_PROMOTION,
            ChangeState.WAITING_PROMOTION_APPROVAL,
            ChangeState.PROMOTED,
            ChangeState.OBSERVING,
            ChangeState.CLOSED,
            ChangeState.REJECTED,
            ChangeState.ROLLED_BACK,
            ChangeState.SUPERSEDED,
        }:
            self.coordinator.reconcile(self.change_id)
            self.coordinator.reconcile(self.change_id)

    @precondition(
        lambda self: (
            (item := self._active_work()) is not None
            and item.state
            in {
                WorkState.QUEUED,
                WorkState.RETRYING,
                WorkState.WAITING_RESOURCE,
            }
        )
    )
    @rule()
    def run_active_work(self) -> None:
        item = self._active_work()
        assert item is not None
        self.work.save(
            item.transition(WorkState.RUNNING),
            expected_version=item.version,
        )

    @precondition(
        lambda self: (
            (item := self._active_work()) is not None
            and item.state is WorkState.RUNNING
        )
    )
    @rule()
    def temporary_provider_pressure(self) -> None:
        item = self._active_work()
        assert item is not None
        self.work.save(
            item.transition(
                WorkState.WAITING_RESOURCE,
                status_detail="provider temporarily unavailable",
            ),
            expected_version=item.version,
        )

    @precondition(
        lambda self: (
            (item := self._active_work()) is not None
            and item.state is WorkState.RUNNING
        )
    )
    @rule()
    def retryable_provider_failure(self) -> None:
        item = self._active_work()
        assert item is not None
        self.work.save(
            item.transition(
                WorkState.FAILED,
                status_detail="provider servers are currently overloaded",
            ),
            expected_version=item.version,
        )
        self.coordinator.reconcile_for_work(item.work_id)

    @precondition(
        lambda self: (
            (item := self._active_work()) is not None
            and item.state is WorkState.FAILED
            and classify_work_system_outcome(
                item,
                steps=self.work.list_steps(item.work_id),
            ).kind.value
            == "retryable"
        )
    )
    @rule()
    def supervisor_retries_failed_work_once(self) -> None:
        result = self.supervisor.coordinate(self.goal_id)
        assert result.action is SupervisorAction.RETRY
        assert result.disposition is SupervisorCutoverDisposition.RETRIED_WORK
        assert result.mutation_performed is True
        retried = self._active_work()
        assert retried is not None
        assert retried.state is WorkState.RETRYING

        second = self.supervisor.coordinate(self.goal_id)
        assert second.action is not SupervisorAction.RETRY

    @precondition(
        lambda self: (
            self._change().state is ChangeState.RESEARCHING
            and (item := self._current_source()) is not None
            and item.state is WorkState.RUNNING
        )
    )
    @rule()
    def complete_current_source(self) -> None:
        source = self.changes.current_stage_attempt(self.change_id, "acquisition")
        assert source is not None
        item = self.work.require(source.work_id)
        architecture = self.changes.add_artifact(
            self.change_id,
            kind="architecture",
            payload={
                "schema": "stateful_architecture.v1",
                "source_attempt": source.attempt,
                "strategy": f"strategy-{source.attempt}",
                "owner_acceptance_contract_ids": [
                    PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT
                ],
            },
        )
        completed = self.work.save(
            item.transition(
                WorkState.COMPLETED,
                status_detail="research evidence accepted",
                result={"architecture_artifact_id": architecture.artifact_id},
            ),
            expected_version=item.version,
        )
        assert completed.state is WorkState.COMPLETED
        reconciled = self.coordinator.reconcile(self.change_id)
        assert reconciled.state is ChangeState.ARCHITECTURE_READY

    @precondition(lambda self: self._change().state is ChangeState.ARCHITECTURE_READY)
    @rule()
    def owner_approves_current_architecture(self) -> None:
        self._approve_current_architecture()
        assert self._change().state is ChangeState.APPROVED_FOR_BUILD

    @precondition(lambda self: self._change().state is ChangeState.APPROVED_FOR_BUILD)
    @rule()
    def start_governed_development(self) -> None:
        change = self.coordinator.reconcile(self.change_id)
        assert change.state is ChangeState.DEVELOPING
        development = self._current_development()
        assert development is not None

    @precondition(
        lambda self: (
            self._change().state is ChangeState.DEVELOPING
            and (item := self._current_development()) is not None
            and item.state is WorkState.RUNNING
        )
    )
    @rule()
    def development_requests_architecture_revision(self) -> None:
        item = self._current_development()
        assert item is not None
        completed = self.work.save(
            item.transition(
                WorkState.COMPLETED,
                status_detail="development requires fresh dependency evidence",
                result={
                    "development_engine": {
                        "disposition": "needs_architecture_revision",
                        "summary": "Fresh dependency evidence is required.",
                        "reason": "approved dependency assumptions changed",
                    }
                },
            ),
            expected_version=item.version,
        )
        reopened = self.changes.request_architecture_revision_for_work(
            completed.work_id,
            reason="approved dependency assumptions changed",
        )
        assert reopened.state is ChangeState.RESEARCHING
        self.coordinator.reconcile(self.change_id)
        source = self.changes.current_stage_attempt(self.change_id, "acquisition")
        assert source is not None
        assert source.attempt >= 2

    @precondition(
        lambda self: (
            self._change().state is ChangeState.RESEARCHING
            and self.changes.latest_artifact(
                self.change_id,
                "architecture_revision_request",
            )
            is not None
            and (
                stage := self.changes.current_stage_attempt(
                    self.change_id,
                    "acquisition",
                )
            )
            is not None
            and stage.attempt > 1
            and self.work.require(stage.work_id).state is WorkState.RUNNING
        )
    )
    @rule()
    def recover_provisional_candidate_identity_collision(self) -> None:
        stage = self.changes.current_stage_attempt(self.change_id, "acquisition")
        assert stage is not None
        item = self.work.require(stage.work_id)
        contradiction = (
            "AcquisitionResolutionError: one immutable source identity produced "
            "contradictory candidate evidence"
        )
        failed_step = WorkStep(
            work_id=item.work_id,
            kind="acq_resolve",
            summary="Resolve acquisition candidates",
        )
        self.work.add_step(failed_step)
        self.work.save_step(failed_step.start().fail(contradiction))
        self.work.save(
            item.transition(
                WorkState.FAILED,
                status_detail=f"step failed: acq_resolve: {contradiction}",
            ),
            expected_version=item.version,
        )
        failed = self.coordinator.reconcile(self.change_id)
        assert failed.state is ChangeState.FAILED

        recovered = (
            self.changes.reopen_recoverable_provisional_candidate_resolution_failures(
                recovery_generation="stateful-provisional-candidate-v1",
            )
        )
        assert recovered == (self.change_id,)
        self.coordinator.reconcile(self.change_id)

        replacement = self.changes.current_stage_attempt(
            self.change_id,
            "acquisition",
        )
        assert replacement is not None
        assert replacement.attempt == stage.attempt + 1
        assert replacement.work_id != stage.work_id
        assert self.work.require(stage.work_id).state is WorkState.FAILED

    @precondition(
        lambda self: (
            self._change().state is ChangeState.DEVELOPING
            and (item := self._current_development()) is not None
            and item.state is WorkState.RUNNING
        )
    )
    @rule()
    def complete_development_successfully(self) -> None:
        item = self._current_development()
        assert item is not None
        self.work.save(
            item.transition(
                WorkState.COMPLETED,
                status_detail="verified development completed",
                result={
                    "commit": "a" * 40,
                    "branch": "stateful/test",
                    "verification": {"passed": True},
                },
            ),
            expected_version=item.version,
        )
        change = self.coordinator.reconcile(self.change_id)
        assert change.state is ChangeState.VERIFYING

    @invariant()
    def canonical_cross_lifecycle_invariants_hold(self) -> None:
        report = assert_capability_system_invariants(
            goal_store=self.goals,
            change_store=self.changes,
            goal_id=self.goal_id,
        )
        assert report.goal_id == self.goal_id
        assert self.goals.get_goal(self.goal_id) is not None
        assert self.goals.get_gap(self.gap_id) is not None
        assert self.changes.require(self.change_id).change_id == self.change_id


TestCapabilityAcquisitionLifecycleStateMachine = (
    CapabilityAcquisitionLifecycleMachine.TestCase
)
TestCapabilityAcquisitionLifecycleStateMachine.settings = settings(
    max_examples=80,
    stateful_step_count=35,
    deadline=None,
    derandomize=True,
)


def test_external_acceptance_invariant_is_architecture_conditional() -> None:
    """Activation alone must not invent a real-world acceptance requirement."""

    architecture = SimpleNamespace(
        kind="architecture",
        artifact_id="artifact_architecture_internal",
        payload={"owner_acceptance_contract_ids": []},
    )
    activation = SimpleNamespace(
        kind="capability_lifecycle_activation",
        artifact_id="artifact_activation_internal",
        digest="a" * 64,
        revision=1,
        payload={},
    )
    change = SimpleNamespace(
        change_id="change_internal_capability",
        current_architecture_artifact_id=architecture.artifact_id,
        artifacts=(architecture, activation),
    )
    findings = []

    _check_external_acceptance_binding(
        change=change,
        work_by_id={},
        findings=findings,
    )

    assert findings == []


def test_gicc_architecture_requires_real_external_acceptance_contract() -> None:
    """Persisted GICC architectures cannot bypass the real-target proof boundary."""

    architecture = SimpleNamespace(
        kind="architecture",
        artifact_id="artifact_architecture_legacy_gicc",
        payload={"owner_acceptance_contract_ids": []},
    )
    link = SimpleNamespace(
        kind="gicc_capability_gap_link",
        artifact_id="artifact_gicc_link",
        payload={
            "motivating_goal_id": "goal-demo",
            "gap_id": "gap-demo",
            "engineering_change_id": "change-legacy-gicc",
        },
    )
    change = SimpleNamespace(
        change_id="change-legacy-gicc",
        current_architecture_artifact_id=architecture.artifact_id,
        artifacts=(link, architecture),
    )
    findings = []

    _check_gicc_external_acceptance_contract(
        change=change,
        findings=findings,
    )

    assert [finding.code for finding in findings] == [
        CapabilitySystemInvariantCode.GICC_ARCHITECTURE_MISSING_EXTERNAL_ACCEPTANCE
    ]


def test_external_acceptance_invariant_requires_binding_when_approved() -> None:
    """Approved real-world acceptance cannot disappear after activation."""

    architecture = SimpleNamespace(
        kind="architecture",
        artifact_id="artifact_architecture_external",
        payload={
            "owner_acceptance_contract_ids": [PHASE9_REAL_EXTERNAL_ACCEPTANCE_CONTRACT]
        },
    )
    activation = SimpleNamespace(
        kind="capability_lifecycle_activation",
        artifact_id="artifact_activation_external",
        digest="b" * 64,
        revision=1,
        payload={},
    )
    change = SimpleNamespace(
        change_id="change_external_capability",
        current_architecture_artifact_id=architecture.artifact_id,
        artifacts=(architecture, activation),
    )
    findings = []

    _check_external_acceptance_binding(
        change=change,
        work_by_id={},
        findings=findings,
    )

    assert [finding.code for finding in findings] == [
        CapabilitySystemInvariantCode.EXTERNAL_ACCEPTANCE_WITHOUT_BINDING
    ]


def test_invariant_checker_detects_completed_retryable_work(tmp_path: Path) -> None:
    """The D8 completed+retryable contradiction is permanently rejected."""

    work = SQLiteWorkStore(tmp_path / "work.sqlite3")
    goals = GoalStore(work)
    changes = ChangeStore(
        work,
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )

    entity = goals.put_entity(
        WorldEntityRefV1.create(
            entity_type="television",
            canonical_name="Invariant Test Television",
        )
    )
    goal = goals.create_goal(
        OwnerGoalV2.create(
            source_session_id="invariant-session",
            source_turn_id="invariant-turn",
            exact_owner_request="Control the television.",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Television is controlled.",
            completion_predicates=("controlled",),
            referenced_entity_ids=(entity.entity_id,),
        )
    )
    requirement = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability="media_player.control",
        operation="play_media",
        target_entity_id=entity.entity_id,
        target_entity_type="television",
        reason="Capability is absent.",
    )
    graph = goals.put_requirement_graph(
        CapabilityRequirementGraphV1.create(
            goal_id=goal.goal_id,
            requirements=(requirement,),
        )
    )
    gap = goals.put_gap(
        CapabilityGapV1.create(
            goal_id=goal.goal_id,
            requirement_ids=graph.requirement_ids,
            reusable_capability_family="media_player.control",
            target_entity_type="television",
            target_entity_id=entity.entity_id,
            minimum_required_operations=("play_media",),
            missing_reason_codes=("capability_missing",),
        )
    )
    request = Phase9AcquisitionRequestV2.create(gap=gap, goal=goal)
    change = changes.create(
        request="Acquire television control.",
        process_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
        process_version=OWNER_CAPABILITY_ACQUISITION_PROCESS.version,
        source_session_id=request.bridge_source_session_id,
        source_turn_id=request.bridge_source_turn_id,
    )
    change = changes.transition(
        change.change_id,
        ChangeState.RESEARCHING,
        expected_version=change.version,
    )
    changes.add_artifact(
        change.change_id,
        kind="gicc_capability_gap_link",
        payload={
            "schema": "gicc_phase9_gap_link.v2",
            "request_id": request.request_id,
            "request_digest": request.digest,
            "motivating_goal_id": goal.goal_id,
            "gap_id": gap.gap_id,
            "engineering_change_id": change.change_id,
        },
    )
    broken = WorkItem(
        request="Broken retryable source result.",
        work_type=OWNER_CAPABILITY_ACQUISITION_PROCESS.research_type,
        source_session_id=f"change:{change.change_id}",
        source_turn_id="acquisition:1",
        state=WorkState.COMPLETED,
        result={
            "development_engine": {
                "disposition": "failed",
                "reason": "response_contract_invalid",
                "blocker_code": "response_contract_invalid",
            }
        },
    )
    changes.link_work(
        change.change_id,
        "acquisition",
        1,
        broken,
    )

    report = inspect_capability_system_invariants(
        goal_store=goals,
        change_store=changes,
        goal_id=goal.goal_id,
    )

    assert CapabilitySystemInvariantCode.RETRYABLE_WORK_NOT_FAILED in {
        item.code for item in report.findings
    }

    backend = _Backend()
    coordinator = ChangeCoordinator(changes, backend)
    projector = ObjectiveWorkspaceProjector(
        goal_store=goals,
        change_store=changes,
    )
    cutover = SupervisorCutoverController(
        projector=projector,
        change_coordinator=coordinator,
        mode=AutonomyMode.ASSISTED,
        invariant_guard=lambda workspace: tuple(
            finding.code.value
            for finding in inspect_capability_workspace_invariants(
                workspace=workspace,
                change_store=changes,
            ).findings
        ),
    ).coordinate(goal.goal_id)

    assert cutover.disposition is SupervisorCutoverDisposition.REJECTED
    assert cutover.accepted is False
    assert cutover.reason_codes == ("system_invariant:retryable_work_not_failed",)
    assert cutover.mutation_performed is False
    assert backend.submissions == []


def test_failed_change_cannot_advertise_resume_development(tmp_path: Path) -> None:
    """A terminal governing change must outrank a child's forward disposition."""

    work = SQLiteWorkStore(tmp_path / "terminal-precedence.sqlite3")
    goals = GoalStore(work)
    changes = ChangeStore(
        work,
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    backend = _Backend()
    coordinator = ChangeCoordinator(changes, backend)

    entity = goals.put_entity(
        WorldEntityRefV1.create(
            entity_type="television",
            canonical_name="Terminal Precedence Television",
        )
    )
    goal = goals.create_goal(
        OwnerGoalV2.create(
            source_session_id="terminal-session",
            source_turn_id="terminal-turn",
            exact_owner_request="Control the television.",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Television is controlled.",
            completion_predicates=("controlled",),
            referenced_entity_ids=(entity.entity_id,),
        )
    )
    requirement = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability="media_player.control",
        operation="play_media",
        target_entity_id=entity.entity_id,
        target_entity_type="television",
        reason="Capability is absent.",
    )
    graph = goals.put_requirement_graph(
        CapabilityRequirementGraphV1.create(
            goal_id=goal.goal_id,
            requirements=(requirement,),
        )
    )
    gap = goals.put_gap(
        CapabilityGapV1.create(
            goal_id=goal.goal_id,
            requirement_ids=graph.requirement_ids,
            reusable_capability_family="media_player.control",
            target_entity_type="television",
            target_entity_id=entity.entity_id,
            minimum_required_operations=("play_media",),
            missing_reason_codes=("capability_missing",),
        )
    )
    node = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=0,
        node_type=PlanNodeType.ACQUIRE_CAPABILITY,
        summary="Acquire television control and resume the owner goal.",
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
        )
    )
    request = Phase9AcquisitionRequestV2.create(gap=gap, goal=goal)
    change = changes.create(
        request="Acquire television control.",
        process_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
        process_version=OWNER_CAPABILITY_ACQUISITION_PROCESS.version,
        source_session_id=request.bridge_source_session_id,
        source_turn_id=request.bridge_source_turn_id,
    )
    change = changes.transition(
        change.change_id,
        ChangeState.RESEARCHING,
        expected_version=change.version,
    )
    changes.add_artifact(
        change.change_id,
        kind="gicc_capability_gap_link",
        payload={
            "schema": "gicc_phase9_gap_link.v2",
            "request_id": request.request_id,
            "request_digest": request.digest,
            "motivating_goal_id": goal.goal_id,
            "gap_id": gap.gap_id,
            "engineering_change_id": change.change_id,
        },
    )
    source = WorkItem(
        request="Completed authoritative source.",
        work_type=OWNER_CAPABILITY_ACQUISITION_PROCESS.research_type,
        source_session_id=f"change:{change.change_id}",
        source_turn_id="acquisition:1",
        state=WorkState.COMPLETED,
    )
    changes.link_work(change.change_id, "acquisition", 1, source)
    goals.put_continuation(
        GoalContinuationV1.create(
            goal_id=goal.goal_id,
            plan_id=plan.plan_id,
            blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
            blocked_by_id=gap.gap_id,
            resume_node_id=node.node_id,
            work_ids=(source.work_id,),
            goal_revision=goal.goal_revision,
        )
    )
    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={"schema": "terminal_precedence_architecture.v1"},
    )

    decided_at = _now()
    gate_id = "gate_" + uuid.uuid4().hex[:16]
    with work._lock, work._connect() as db:
        db.execute(
            """INSERT INTO engineering_change_gates (
            gate_id, change_id, kind, artifact_id, artifact_digest, created_at
            ) VALUES (?, ?, 'architecture', ?, ?, ?)""",
            (
                gate_id,
                change.change_id,
                architecture.artifact_id,
                architecture.digest,
                decided_at,
            ),
        )
        db.execute(
            """INSERT INTO engineering_change_decisions (
            gate_id, approved, actor_id, source_session_id, source_turn_id,
            request_key, decided_at
            ) VALUES (?, 1, 'owner', 'terminal-session', 'approval-turn', ?, ?)""",
            (gate_id, f"terminal:{architecture.artifact_id}", decided_at),
        )
        db.execute(
            """UPDATE engineering_changes
            SET state=?, version=version+1, updated_at=?
            WHERE change_id=?""",
            (
                ChangeState.APPROVED_FOR_BUILD.value,
                decided_at,
                change.change_id,
            ),
        )

    developing = coordinator.reconcile(change.change_id)
    assert developing.state is ChangeState.DEVELOPING
    development = changes.current_stage_attempt(change.change_id, "development")
    assert development is not None
    item = work.require(development.work_id)
    running = work.save(
        item.transition(WorkState.RUNNING),
        expected_version=item.version,
    )
    work.save(
        running.transition(
            WorkState.COMPLETED,
            status_detail="A replacement approved dependency is required.",
            result={
                "development_engine": {
                    "disposition": "needs_dependency",
                    "reason": "The approved dependency changed.",
                }
            },
        ),
        expected_version=running.version,
    )
    current = changes.require(change.change_id)
    failed = changes.transition(
        change.change_id,
        ChangeState.FAILED,
        expected_version=current.version,
    )
    assert failed.state is ChangeState.FAILED

    workspace = ObjectiveWorkspaceProjector(
        goal_store=goals,
        change_store=changes,
    ).project(goal.goal_id)
    progress = build_progress_ledger(workspace)

    assert progress.phase == "terminal"
    assert progress.blocker_kind == "terminal"
    assert progress.current_plan_valid is False
    assert progress.next_legal_actions == ("TERMINAL",)
    assert "RESUME_DEVELOPMENT" not in progress.next_legal_actions

    report = inspect_capability_system_invariants(
        goal_store=goals,
        change_store=changes,
        goal_id=goal.goal_id,
    )
    assert CapabilitySystemInvariantCode.FAILED_CHANGE_EXPOSES_FORWARD_PROGRESS not in {
        finding.code for finding in report.findings
    }


def test_historical_capability_invariant_is_auditable_but_not_live_blocker(
    tmp_path: Path,
) -> None:
    work = SQLiteWorkStore(tmp_path / "historical-isolation.sqlite3")
    goals = GoalStore(work)
    changes = ChangeStore(
        work,
        processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,),
    )
    backend = _Backend()
    coordinator = ChangeCoordinator(changes, backend)

    entity = goals.put_entity(
        WorldEntityRefV1.create(
            entity_type="television",
            canonical_name="Historical Isolation Television",
        )
    )
    goal = goals.create_goal(
        OwnerGoalV2.create(
            source_session_id="historical-isolation-session",
            source_turn_id="historical-isolation-turn",
            exact_owner_request="Acquire the capabilities needed for the current mission.",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="The current capability gap is resolved.",
            completion_predicates=("current_capability_ready",),
            referenced_entity_ids=(entity.entity_id,),
        )
    )
    historical_requirement = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability="legacy.device.control",
        operation="legacy_operation",
        target_entity_id=entity.entity_id,
        target_entity_type="television",
        reason="Historical capability requirement.",
    )
    current_requirement = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability="media_player.control",
        operation="play_media",
        target_entity_id=entity.entity_id,
        target_entity_type="television",
        reason="Current capability requirement.",
    )
    graph = goals.put_requirement_graph(
        CapabilityRequirementGraphV1.create(
            goal_id=goal.goal_id,
            requirements=(historical_requirement, current_requirement),
        )
    )
    historical_gap = goals.put_gap(
        CapabilityGapV1.create(
            goal_id=goal.goal_id,
            requirement_ids=(historical_requirement.requirement_id,),
            reusable_capability_family="legacy.device.control",
            target_entity_type="television",
            target_entity_id=entity.entity_id,
            minimum_required_operations=("legacy_operation",),
            missing_reason_codes=("historical_missing",),
        )
    )
    historical_gap = goals.update_gap_state(
        historical_gap.gap_id,
        CapabilityGapState.SATISFIED,
        expected_revision=historical_gap.revision,
    )
    current_gap = goals.put_gap(
        CapabilityGapV1.create(
            goal_id=goal.goal_id,
            requirement_ids=(current_requirement.requirement_id,),
            reusable_capability_family="media_player.control",
            target_entity_type="television",
            target_entity_id=entity.entity_id,
            minimum_required_operations=("play_media",),
            missing_reason_codes=("current_missing",),
        )
    )
    node = PlanNodeV1.create(
        plan_identity=f"{goal.goal_id}:current-capability",
        ordinal=0,
        node_type=PlanNodeType.ACQUIRE_CAPABILITY,
        summary="Acquire the current media-control capability.",
        gap_id=current_gap.gap_id,
    )
    plan = goals.put_plan(
        PlanGraphV1.create(
            goal_id=goal.goal_id,
            goal_revision=goal.goal_revision,
            nodes=(node,),
            edges=(),
            root_node_ids=(node.node_id,),
            completion_node_ids=(node.node_id,),
        )
    )

    historical_request = Phase9AcquisitionRequestV2.create(
        gap=historical_gap,
        goal=goal,
    )
    historical_change = changes.create(
        request="Historical completed capability lifecycle.",
        process_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
        process_version=OWNER_CAPABILITY_ACQUISITION_PROCESS.version,
        source_session_id=historical_request.bridge_source_session_id,
        source_turn_id=historical_request.bridge_source_turn_id,
    )
    changes.add_artifact(
        historical_change.change_id,
        kind="gicc_capability_gap_link",
        payload={
            "schema": "gicc_phase9_gap_link.v2",
            "request_id": historical_request.request_id,
            "request_digest": historical_request.digest,
            "motivating_goal_id": goal.goal_id,
            "gap_id": historical_gap.gap_id,
            "engineering_change_id": historical_change.change_id,
        },
    )
    changes.add_artifact(
        historical_change.change_id,
        kind="architecture",
        payload={
            "schema": "capability_acquisition_architecture.v1",
            "owner_acceptance_contract_ids": [],
        },
    )

    current_request = Phase9AcquisitionRequestV2.create(gap=current_gap, goal=goal)
    current_change = coordinator.start(
        "Acquire the currently governing capability.",
        current_request.bridge_source_session_id,
        current_request.bridge_source_turn_id,
        process_key=OWNER_CAPABILITY_ACQUISITION_PROCESS.key,
        process_version=OWNER_CAPABILITY_ACQUISITION_PROCESS.version,
    )
    current_source = changes.current_stage_attempt(
        current_change.change_id,
        "acquisition",
    )
    assert current_source is not None
    changes.add_artifact(
        current_change.change_id,
        kind="gicc_capability_gap_link",
        payload={
            "schema": "gicc_phase9_gap_link.v2",
            "request_id": current_request.request_id,
            "request_digest": current_request.digest,
            "motivating_goal_id": goal.goal_id,
            "gap_id": current_gap.gap_id,
            "engineering_change_id": current_change.change_id,
            "acquisition_work_id": current_source.work_id,
        },
    )
    goals.put_continuation(
        GoalContinuationV1.create(
            goal_id=goal.goal_id,
            plan_id=plan.plan_id,
            blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
            blocked_by_id=current_gap.gap_id,
            resume_node_id=node.node_id,
            work_ids=(current_source.work_id,),
            goal_revision=goal.goal_revision,
        )
    )

    workspace = ObjectiveWorkspaceProjector(
        goal_store=goals,
        change_store=changes,
    ).project(goal.goal_id)
    report = inspect_capability_workspace_invariants(
        workspace=workspace,
        change_store=changes,
    )
    historical_findings = [
        finding
        for finding in report.findings
        if finding.change_id == historical_change.change_id
    ]
    assert (
        CapabilitySystemInvariantCode.GICC_ARCHITECTURE_MISSING_EXTERNAL_ACCEPTANCE
        in {finding.code for finding in historical_findings}
    )

    blocking_codes = blocking_capability_workspace_invariant_codes(
        workspace=workspace,
        change_store=changes,
    )

    assert (
        CapabilitySystemInvariantCode.GICC_ARCHITECTURE_MISSING_EXTERNAL_ACCEPTANCE.value
        not in blocking_codes
    )
    assert build_progress_ledger(workspace).active_change_id == current_change.change_id
