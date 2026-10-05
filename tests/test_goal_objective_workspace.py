from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.autonomy import (
    AutonomyMode,
    ExistingObjectiveLineageError,
    ExistingObjectiveLineageV1,
    ExistingObjectiveResumeController,
    GlobalSupervisor,
    ShadowAgreement,
    ShadowFaultKind,
    SupervisorAction,
    SupervisorCutoverController,
    SupervisorCutoverDisposition,
    SupervisorProposalV1,
    SupervisorShadowRunner,
    supervisor_context_from_workspace,
)
from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.engineering_change.coordinator import ChangeCoordinator
from jarvis.engineering_change.delivery import reconcile_owner_change_gates
from jarvis.engineering_change.gates import GateService
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.goal_intelligence.ledgers import (
    build_progress_ledger,
    build_task_ledger,
)
from jarvis.goal_intelligence.models import (
    CapabilityGapState,
    CapabilityGapV1,
    CapabilityRequirementGraphV1,
    CapabilityRequirementV1,
    ContinuationBlockerType,
    GoalContinuationV1,
    GoalKind,
    InformationNeedCategory,
    InformationNeedV1,
    OwnerGoalV2,
    PlanGraphV1,
    PlanNodeType,
    PlanNodeV1,
    WorldEntityRefV1,
)
from jarvis.goal_intelligence.phase9 import Phase9AcquisitionRequestV2
from jarvis.goal_intelligence.role_contexts import (
    build_architecture_context,
    build_development_context,
    build_research_context,
    build_verification_context,
)
from jarvis.goal_intelligence.store import GoalStore, GoalStoreError
from jarvis.goal_intelligence.workspace import ObjectiveWorkspaceProjector
from jarvis.work.models import WorkItem, WorkState, WorkType
from jarvis.work.store import SQLiteWorkStore


def _stores(path: Path) -> tuple[SQLiteWorkStore, GoalStore, ChangeStore]:
    work = SQLiteWorkStore(path)
    return (
        work,
        GoalStore(work),
        ChangeStore(work, processes=(OWNER_CAPABILITY_ACQUISITION_PROCESS,)),
    )


def _scenario(path: Path):
    work, goals, changes = _stores(path)
    entity = goals.put_entity(
        WorldEntityRefV1.create(
            entity_type="television",
            canonical_name="Hisense U7N",
            provenance_refs=("owner_inventory:living_room_tv",),
        )
    )
    goal = goals.create_goal(
        OwnerGoalV2.create(
            source_session_id="owner-session",
            source_turn_id="owner-tv-turn",
            exact_owner_request="Open Hotstar, search The Martian and play it.",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Play The Martian on the owner's Hisense television.",
            completion_predicates=("movie_playing_on_target_tv",),
            referenced_entity_ids=(entity.entity_id,),
            created_at="2026-10-05T10:00:00+00:00",
        )
    )
    requirement = CapabilityRequirementV1.create(
        goal_id=goal.goal_id,
        semantic_capability="media_player.control",
        operation="play_media",
        target_entity_id=entity.entity_id,
        target_entity_type="television",
        reason="The owner requested playback on the target television.",
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
    need = goals.create_information_need(
        InformationNeedV1.create(
            goal_id=goal.goal_id,
            category=InformationNeedCategory.MISSING_VALUE,
            subject="VIDAA pairing evidence",
            required_fact="exact VIDAA pairing handshake",
            why_required="Development must not guess the device pairing contract.",
            allowed_resolution_sources=("research",),
            owner_question=None,
            created_at="2026-10-05T10:01:00+00:00",
        )
    )
    node = PlanNodeV1.create(
        plan_identity=goal.goal_id,
        ordinal=0,
        node_type=PlanNodeType.ACQUIRE_CAPABILITY,
        summary="Acquire and use TV control.",
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
            created_at="2026-10-05T10:02:00+00:00",
        )
    )

    request = Phase9AcquisitionRequestV2.create(gap=gap, goal=goal)
    change = changes.create(
        request="Acquire governed TV control capability.",
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
    architecture = changes.add_artifact(
        change.change_id,
        kind="architecture",
        payload={
            "schema": "test_architecture.v1",
            "strategy": "vidaa_mqtt_tls",
            "target_entity_id": entity.entity_id,
        },
    )
    research = WorkItem(
        request="Research exact VIDAA pairing evidence.",
        work_type=WorkType.RESEARCH,
        source_session_id=f"change:{change.change_id}",
        source_turn_id="acquisition:1",
        state=WorkState.WAITING_RESOURCE,
        status_detail="provider temporarily unavailable",
    )
    stage = changes.link_work(change.change_id, "acquisition", 1, research)
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
            "acquisition_work_id": research.work_id,
        },
    )
    continuation = goals.put_continuation(
        GoalContinuationV1.create(
            goal_id=goal.goal_id,
            plan_id=plan.plan_id,
            blocked_by_type=ContinuationBlockerType.CAPABILITY_ACQUISITION,
            blocked_by_id=gap.gap_id,
            resume_node_id=node.node_id,
            work_ids=(research.work_id,),
            goal_revision=goal.goal_revision,
            created_at="2026-10-05T10:03:00+00:00",
        )
    )
    return {
        "work": work,
        "goals": goals,
        "changes": changes,
        "goal": goal,
        "entity": entity,
        "graph": graph,
        "gap": gap,
        "need": need,
        "plan": plan,
        "change": change,
        "architecture": architecture,
        "research": research,
        "stage": stage,
        "continuation": continuation,
    }


def test_objective_workspace_projects_one_canonical_goal_reality(
    tmp_path: Path,
) -> None:
    state = _scenario(tmp_path / "work.sqlite3")

    workspace = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    ).project(state["goal"].goal_id)

    assert workspace.schema == "objective_workspace.v1"
    assert workspace.goal.record_id == state["goal"].goal_id
    assert workspace.goal.payload["exact_owner_request"] == (
        "Open Hotstar, search The Martian and play it."
    )
    assert workspace.requirement_graph is not None
    assert workspace.requirement_graph.record_id == state["graph"].graph_id
    assert workspace.plan is not None
    assert workspace.plan.record_id == state["plan"].plan_id

    assert len(workspace.targets) == 1
    target = workspace.targets[0]
    assert target.entity_id == state["entity"].entity_id
    assert target.entity_type == "television"
    assert target.canonical_name == "Hisense U7N"
    assert set(target.source_refs) == {
        f"goal:{state['goal'].goal_id}",
        f"capability_gap:{state['gap'].gap_id}",
    }

    assert [item.record_id for item in workspace.capability_gaps] == [
        state["gap"].gap_id
    ]
    assert [item.record_id for item in workspace.information_needs] == [
        state["need"].information_need_id
    ]
    assert [item.record_id for item in workspace.continuations] == [
        state["continuation"].continuation_id
    ]

    assert len(workspace.changes) == 1
    projected_change = workspace.changes[0]
    assert projected_change.change_id == state["change"].change_id
    assert projected_change.current_architecture_artifact_id == (
        state["architecture"].artifact_id
    )
    assert [
        (item.stage_key, item.attempt, item.work_id) for item in projected_change.stages
    ] == [("acquisition", 1, state["research"].work_id)]
    assert "created" in {item.kind for item in projected_change.events}
    assert "artifact" in {item.kind for item in projected_change.events}

    assert [item.work_id for item in workspace.work_items] == [
        state["research"].work_id
    ]
    projected_work = workspace.work_items[0]
    assert projected_work.state == WorkState.WAITING_RESOURCE.value
    assert projected_work.status_detail == "provider temporarily unavailable"
    assert projected_work.system_outcome.kind == "temporary_resource"
    assert projected_work.system_outcome.terminal is False
    assert projected_work.system_outcome.owner_action_required is False

    assert workspace.current_architecture_refs == (state["architecture"].artifact_id,)
    assert f"capability_gap:{state['gap'].gap_id}:open" in workspace.observed_blockers
    assert (
        f"work:{state['research'].work_id}:waiting_resource"
        in workspace.observed_blockers
    )
    assert "exact VIDAA pairing handshake" in workspace.open_questions
    assert len(workspace.digest) == 64


def test_objective_workspace_is_read_only_and_restart_deterministic(
    tmp_path: Path,
) -> None:
    path = tmp_path / "work.sqlite3"
    state = _scenario(path)
    first = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    ).project(state["goal"].goal_id)

    work, goals, changes = _stores(path)
    second = ObjectiveWorkspaceProjector(
        goal_store=goals,
        change_store=changes,
        work_store=work,
    ).project(state["goal"].goal_id)

    assert second == first
    assert second.digest == first.digest
    assert changes.require(state["change"].change_id).version == state["change"].version
    assert work.require(state["research"].work_id).version == state["research"].version


def test_objective_workspace_rejects_unknown_goal_and_split_truth(
    tmp_path: Path,
) -> None:
    first_work, goals, changes = _stores(tmp_path / "first.sqlite3")
    projector = ObjectiveWorkspaceProjector(
        goal_store=goals,
        change_store=changes,
        work_store=first_work,
    )

    with pytest.raises(GoalStoreError, match="unknown owner goal"):
        projector.project("goal_missing")

    other_work = SQLiteWorkStore(tmp_path / "other.sqlite3")
    with pytest.raises(ValueError, match="share canonical Work storage"):
        ObjectiveWorkspaceProjector(
            goal_store=goals,
            change_store=changes,
            work_store=other_work,
        )


def test_task_and_progress_ledgers_derive_from_same_workspace(tmp_path: Path) -> None:
    state = _scenario(tmp_path / "ledger-work.sqlite3")
    workspace = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    ).project(state["goal"].goal_id)

    task = build_task_ledger(workspace)
    progress = build_progress_ledger(workspace)

    assert task.goal_id == state["goal"].goal_id
    assert task.objective == "Open Hotstar, search The Martian and play it."
    assert task.desired_outcome == (
        "Play The Martian on the owner's Hisense television."
    )
    assert task.success_criteria == ("movie_playing_on_target_tv",)
    assert task.targets[0]["canonical_name"] == "Hisense U7N"
    assert "strategy:vidaa_mqtt_tls" in task.current_strategy
    assert "exact VIDAA pairing handshake" in task.assumptions
    assert "architecture approvals remain artifact-bound" in task.authority_boundaries
    assert task.source_workspace_digest == workspace.digest
    assert len(task.digest) == 64

    assert progress.goal_id == state["goal"].goal_id
    assert progress.phase == "research"
    assert progress.active_specialist == "Research"
    assert progress.active_work_id == state["research"].work_id
    assert progress.blocker_kind == "temporary_resource"
    assert progress.owner_action_required is False
    assert progress.current_plan_valid is True
    assert progress.next_legal_actions == ("WAIT_RESOURCE", "RETRY")
    assert progress.source_workspace_digest == workspace.digest
    assert len(progress.digest) == 64


def test_ledgers_are_restart_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "ledger-restart.sqlite3"
    state = _scenario(path)
    first_workspace = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    ).project(state["goal"].goal_id)
    first = (
        build_task_ledger(first_workspace),
        build_progress_ledger(first_workspace),
    )

    work, goals, changes = _stores(path)
    reopened_workspace = ObjectiveWorkspaceProjector(
        goal_store=goals,
        change_store=changes,
        work_store=work,
    ).project(state["goal"].goal_id)
    reopened = (
        build_task_ledger(reopened_workspace),
        build_progress_ledger(reopened_workspace),
    )

    assert reopened == first


def test_global_supervisor_accepts_only_current_legal_action(tmp_path: Path) -> None:
    state = _scenario(tmp_path / "supervisor-legal.sqlite3")
    workspace = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    ).project(state["goal"].goal_id)

    context = supervisor_context_from_workspace(workspace)
    decision = GlobalSupervisor().evaluate(workspace)

    assert context.goal_id == state["goal"].goal_id
    assert context.workspace_digest == workspace.digest
    assert context.task_ledger.source_workspace_digest == workspace.digest
    assert context.progress_ledger.source_workspace_digest == workspace.digest
    assert context.allowed_actions == (
        SupervisorAction.WAIT_RESOURCE,
        SupervisorAction.RETRY,
    )
    assert decision.accepted is True
    assert decision.rejection_codes == ()
    assert decision.proposal.action is SupervisorAction.WAIT_RESOURCE
    assert decision.proposal.target_change_id == state["change"].change_id
    assert decision.proposal.target_work_id == state["research"].work_id


def test_global_supervisor_rejects_illegal_and_stale_proposals(tmp_path: Path) -> None:
    state = _scenario(tmp_path / "supervisor-reject.sqlite3")
    workspace = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    ).project(state["goal"].goal_id)
    context = supervisor_context_from_workspace(workspace)

    illegal = SupervisorProposalV1.create(
        context,
        action=SupervisorAction.TERMINAL,
        rationale="Stop the objective because the research provider is unavailable.",
        target_change_id=state["change"].change_id,
        target_work_id=state["research"].work_id,
    )
    illegal_decision = GlobalSupervisor.validate(context, illegal)

    assert illegal_decision.accepted is False
    assert "action_not_legal" in illegal_decision.rejection_codes
    assert "terminal_not_proven" in illegal_decision.rejection_codes

    valid_wait = SupervisorProposalV1.create(
        context,
        action=SupervisorAction.WAIT_RESOURCE,
        rationale="Wait for the provider.",
        target_change_id=state["change"].change_id,
        target_work_id=state["research"].work_id,
    )
    stale_payload = valid_wait.canonical_payload()
    stale_payload["workspace_digest"] = "0" * 64
    stale_payload["target_change_id"] = "change_stale"
    stale_payload["target_work_id"] = "work_stale"
    stale = replace(
        valid_wait,
        workspace_digest="0" * 64,
        target_change_id="change_stale",
        target_work_id="work_stale",
        digest=canonical_digest(stale_payload),
    )
    stale_decision = GlobalSupervisor.validate(context, stale)

    assert stale_decision.accepted is False
    assert "workspace_digest_mismatch" in stale_decision.rejection_codes
    assert "change_binding_mismatch" in stale_decision.rejection_codes
    assert "work_binding_mismatch" in stale_decision.rejection_codes


def test_global_supervisor_cannot_ask_owner_for_internal_resource_pressure(
    tmp_path: Path,
) -> None:
    state = _scenario(tmp_path / "supervisor-owner.sqlite3")
    workspace = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    ).project(state["goal"].goal_id)
    context = supervisor_context_from_workspace(workspace)

    proposal = SupervisorProposalV1.create(
        context,
        action=SupervisorAction.ASK_OWNER,
        rationale="Ask the owner what to do about temporary provider pressure.",
        target_change_id=state["change"].change_id,
        target_work_id=state["research"].work_id,
    )
    decision = GlobalSupervisor.validate(context, proposal)

    assert decision.accepted is False
    assert "action_not_legal" in decision.rejection_codes
    assert "owner_attention_not_required" in decision.rejection_codes


def test_global_supervisor_decision_is_restart_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "supervisor-restart.sqlite3"
    state = _scenario(path)
    first_workspace = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    ).project(state["goal"].goal_id)
    first = GlobalSupervisor().evaluate(first_workspace)

    work, goals, changes = _stores(path)
    reopened_workspace = ObjectiveWorkspaceProjector(
        goal_store=goals,
        change_store=changes,
        work_store=work,
    ).project(state["goal"].goal_id)
    reopened = GlobalSupervisor().evaluate(reopened_workspace)

    assert reopened == first


def test_role_contexts_share_workspace_but_remain_role_bounded(tmp_path: Path) -> None:
    state = _scenario(tmp_path / "role-contexts.sqlite3")
    workspace = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    ).project(state["goal"].goal_id)

    research = build_research_context(workspace)
    architecture = build_architecture_context(workspace)
    development = build_development_context(workspace)
    verification = build_verification_context(workspace)

    contexts = (research, architecture, development, verification)
    assert {item.source_workspace_digest for item in contexts} == {workspace.digest}
    assert {item.task_ledger_digest for item in contexts} == {
        build_task_ledger(workspace).digest
    }
    assert {item.progress_ledger_digest for item in contexts} == {
        build_progress_ledger(workspace).digest
    }

    assert research.current_assignment is not None
    assert research.current_assignment.work_id == state["research"].work_id
    assert "exact VIDAA pairing handshake" in research.bounded_questions
    assert research.current_architecture is not None
    assert (
        research.current_architecture.artifact_id == state["architecture"].artifact_id
    )

    assert architecture.research_assignment is not None
    assert architecture.research_assignment.work_id == state["research"].work_id
    assert architecture.current_architecture is not None

    # An architecture artifact can exist during research, but build/verification roles
    # must not see it as approved until the governed approval state proves that.
    assert development.approved_architecture is None
    assert verification.approved_architecture is None
    assert development.current_assignment is None
    assert verification.development_assignment is None


def test_role_contexts_exclude_superseded_research_from_current_truth(
    tmp_path: Path,
) -> None:
    state = _scenario(tmp_path / "role-supersession.sqlite3")
    old = state["work"].require(state["research"].work_id)
    failed = state["work"].save(
        old.transition(
            WorkState.FAILED,
            status_detail="Historical provider overload.",
        ),
        expected_version=old.version,
    )
    replacement = WorkItem(
        request="Research exact VIDAA pairing evidence with recovered provider.",
        work_type=WorkType.RESEARCH,
        source_session_id=f"change:{state['change'].change_id}",
        source_turn_id="acquisition:2",
    )
    replacement_stage = state["changes"].link_work(
        state["change"].change_id,
        "acquisition",
        2,
        replacement,
    )

    workspace = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    ).project(state["goal"].goal_id)

    research = build_research_context(workspace)
    architecture = build_architecture_context(workspace)
    development = build_development_context(workspace)
    verification = build_verification_context(workspace)

    assert failed.work_id in research.superseded_work_ids
    assert failed.work_id in architecture.superseded_work_ids
    assert failed.work_id in development.superseded_work_ids
    assert failed.work_id in verification.superseded_work_ids

    assert research.current_assignment is not None
    assert research.current_assignment.work_id == replacement_stage.work_id
    assert architecture.research_assignment is not None
    assert architecture.research_assignment.work_id == replacement_stage.work_id
    assert research.current_assignment.work_id != failed.work_id
    assert architecture.research_assignment.work_id != failed.work_id


def test_role_contexts_are_restart_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "role-restart.sqlite3"
    state = _scenario(path)
    first_workspace = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    ).project(state["goal"].goal_id)
    first = (
        build_research_context(first_workspace),
        build_architecture_context(first_workspace),
        build_development_context(first_workspace),
        build_verification_context(first_workspace),
    )

    work, goals, changes = _stores(path)
    reopened_workspace = ObjectiveWorkspaceProjector(
        goal_store=goals,
        change_store=changes,
        work_store=work,
    ).project(state["goal"].goal_id)
    reopened = (
        build_research_context(reopened_workspace),
        build_architecture_context(reopened_workspace),
        build_development_context(reopened_workspace),
        build_verification_context(reopened_workspace),
    )

    assert reopened == first


def test_supervisor_shadow_matches_provider_outage_action_without_writes(
    tmp_path: Path,
) -> None:
    state = _scenario(tmp_path / "shadow-provider.sqlite3")
    projector = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    )
    before_change_version = state["changes"].require(state["change"].change_id).version
    before_work_version = state["work"].require(state["research"].work_id).version

    observation = SupervisorShadowRunner().project_and_evaluate(
        projector,
        state["goal"].goal_id,
        fault_kind=ShadowFaultKind.PROVIDER_OUTAGE,
    )

    assert observation.mutation_authority is False
    assert observation.accepted is True
    assert observation.agreement is ShadowAgreement.PRIMARY_MATCH
    assert observation.primary_expected_action is SupervisorAction.WAIT_RESOURCE
    assert observation.proposed_action is SupervisorAction.WAIT_RESOURCE
    assert observation.expected_actions == (
        SupervisorAction.WAIT_RESOURCE,
        SupervisorAction.RETRY,
    )
    assert state["changes"].require(state["change"].change_id).version == (
        before_change_version
    )
    assert state["work"].require(state["research"].work_id).version == (
        before_work_version
    )


def test_supervisor_shadow_contains_malformed_advisor_output(tmp_path: Path) -> None:
    class MalformedAdvisor:
        def propose(self, context):
            del context
            return {"action": "WAIT_RESOURCE"}

    state = _scenario(tmp_path / "shadow-malformed.sqlite3")
    workspace = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    ).project(state["goal"].goal_id)

    observation = SupervisorShadowRunner(MalformedAdvisor()).evaluate(
        workspace,
        fault_kind=ShadowFaultKind.MALFORMED_RESPONSE,
    )

    assert observation.mutation_authority is False
    assert observation.accepted is False
    assert observation.agreement is ShadowAgreement.ADVISOR_ERROR
    assert observation.rejection_codes == ("advisor_error",)
    assert observation.error_type == "TypeError"
    assert observation.proposal_digest is None
    assert state["work"].require(state["research"].work_id).version == (
        state["research"].version
    )


def test_supervisor_shadow_rejects_stale_proposal_without_writes(
    tmp_path: Path,
) -> None:
    state = _scenario(tmp_path / "shadow-stale.sqlite3")
    workspace = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    ).project(state["goal"].goal_id)

    observation = SupervisorShadowRunner().evaluate_stale_proposal(workspace)

    assert observation.mutation_authority is False
    assert observation.fault_kind is ShadowFaultKind.STALE_ARTIFACT
    assert observation.accepted is False
    assert observation.agreement is ShadowAgreement.REJECTED
    assert "workspace_digest_mismatch" in observation.rejection_codes
    assert state["changes"].require(state["change"].change_id).version == (
        state["change"].version
    )


def test_supervisor_shadow_detects_duplicate_state_and_restart_consistency(
    tmp_path: Path,
) -> None:
    state = _scenario(tmp_path / "shadow-restart.sqlite3")
    workspace = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    ).project(state["goal"].goal_id)
    runner = SupervisorShadowRunner()

    first = runner.evaluate(workspace)
    duplicate = runner.evaluate(
        workspace,
        history=(first,),
        fault_kind=ShadowFaultKind.DUPLICATE_EVENT,
    )
    restarted = SupervisorShadowRunner().evaluate(
        workspace,
        fault_kind=ShadowFaultKind.PROCESS_CRASH,
    )

    assert first.duplicate_state is False
    assert duplicate.duplicate_state is True
    assert duplicate.proposal_digest == first.proposal_digest
    assert duplicate.decision_digest == first.decision_digest
    assert restarted.proposal_digest == first.proposal_digest
    assert restarted.decision_digest == first.decision_digest
    assert restarted.workspace_digest == first.workspace_digest
    assert restarted.mutation_authority is False


def test_supervisor_shadow_detects_specialist_loop_without_acting(
    tmp_path: Path,
) -> None:
    state = _scenario(tmp_path / "shadow-loop.sqlite3")
    workspace = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    ).project(state["goal"].goal_id)
    runner = SupervisorShadowRunner()

    first = runner.evaluate(workspace)
    second = runner.evaluate(workspace, history=(first,))
    third = runner.evaluate(
        workspace,
        history=(first, second),
        fault_kind=ShadowFaultKind.SPECIALIST_LOOP,
    )

    assert first.loop_detected is False
    assert second.loop_detected is False
    assert third.loop_detected is True
    assert third.accepted is True
    assert third.proposed_action is SupervisorAction.WAIT_RESOURCE
    assert third.mutation_authority is False
    assert state["work"].require(state["research"].work_id).version == (
        state["research"].version
    )


class _SupervisorCutoverBackend:
    def __init__(self) -> None:
        self.submissions: list[str] = []

    def submit(self, work_id, *, priority):
        del priority
        self.submissions.append(work_id)
        return work_id


def _direct_goal_change_ready_for_architecture(state):
    state["goals"].update_gap_state(
        state["gap"].gap_id,
        CapabilityGapState.SATISFIED,
        expected_revision=state["gap"].revision,
    )
    state["goals"].resume_continuation(
        state["continuation"].continuation_id,
        expected_revision=state["continuation"].revision,
        resumed_at="2026-10-05T10:04:00+00:00",
    )
    backend = _SupervisorCutoverBackend()
    coordinator = ChangeCoordinator(state["changes"], backend)
    change = coordinator.start(
        "Implement the exact owner objective through governed engineering.",
        state["goal"].source_session_id,
        state["goal"].source_turn_id,
    )
    source = next(
        stage
        for stage in state["changes"].list_stages(change.change_id)
        if stage.stage_key == "research"
    )
    queued = state["work"].require(source.work_id)
    running = state["work"].save(
        queued.transition(WorkState.RUNNING),
        expected_version=queued.version,
    )
    state["work"].save(
        running.transition(
            WorkState.COMPLETED,
            status_detail="Research evidence accepted.",
        ),
        expected_version=running.version,
    )
    architecture = state["changes"].add_artifact(
        change.change_id,
        kind="architecture",
        payload={
            "schema": "supervisor_cutover_test_architecture.v1",
            "strategy": "existing_governed_coordinator",
            "allowed_paths": ["src/jarvis/"],
        },
    )
    ready = coordinator.reconcile(change.change_id)
    assert ready.state is ChangeState.ARCHITECTURE_READY
    return backend, coordinator, ready, architecture, source


def test_supervisor_cutover_defaults_to_shadow_without_mutation(tmp_path: Path) -> None:
    state = _scenario(tmp_path / "cutover-shadow.sqlite3")
    backend = _SupervisorCutoverBackend()
    coordinator = ChangeCoordinator(state["changes"], backend)
    projector = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    )
    before = projector.project(state["goal"].goal_id)

    result = SupervisorCutoverController(
        projector=projector,
        change_coordinator=coordinator,
    ).coordinate(state["goal"].goal_id)

    assert result.mode is AutonomyMode.SHADOW
    assert result.disposition is SupervisorCutoverDisposition.SHADOW_ONLY
    assert result.action is SupervisorAction.WAIT_RESOURCE
    assert result.accepted is True
    assert result.mutation_performed is False
    assert result.before_workspace_digest == before.digest
    assert result.after_workspace_digest == before.digest
    assert backend.submissions == []


def test_supervisor_cutover_assisted_waits_for_runtime_without_mutation(
    tmp_path: Path,
) -> None:
    state = _scenario(tmp_path / "cutover-wait.sqlite3")
    backend = _SupervisorCutoverBackend()
    coordinator = ChangeCoordinator(state["changes"], backend)
    projector = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    )

    result = SupervisorCutoverController(
        projector=projector,
        change_coordinator=coordinator,
        mode=AutonomyMode.ASSISTED,
    ).coordinate(state["goal"].goal_id)

    assert result.disposition is SupervisorCutoverDisposition.AWAIT_RUNTIME
    assert result.action is SupervisorAction.WAIT_RESOURCE
    assert result.mutation_performed is False
    assert state["changes"].require(state["change"].change_id).state is (
        ChangeState.RESEARCHING
    )
    assert backend.submissions == []


def test_supervisor_cutover_surfaces_gate_but_cannot_approve_it(
    tmp_path: Path,
) -> None:
    state = _scenario(tmp_path / "cutover-gate.sqlite3")
    backend, coordinator, change, architecture, source = (
        _direct_goal_change_ready_for_architecture(state)
    )
    projector = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    )
    controller = SupervisorCutoverController(
        projector=projector,
        change_coordinator=coordinator,
        mode=AutonomyMode.ASSISTED,
    )

    result = controller.coordinate(state["goal"].goal_id)

    persisted = state["changes"].require(change.change_id)
    assert result.action is SupervisorAction.CONTINUE
    assert result.disposition is SupervisorCutoverDisposition.RECONCILED_CHANGE
    assert persisted.state is ChangeState.WAITING_OWNER_APPROVAL
    assert len(result.surfaced_gate_ids) == 1
    gate_id = result.surfaced_gate_ids[0]
    gate = GateService(state["changes"], verify_owner=lambda *_: False).get(gate_id)
    assert gate is not None
    assert gate.artifact_digest == architecture.digest
    assert state["changes"].list_stages(change.change_id) == (source,)
    assert all(
        stage.stage_key != "development"
        for stage in state["changes"].list_stages(change.change_id)
    )
    assert backend.submissions == [source.work_id]


def test_supervisor_cutover_starts_development_only_after_existing_owner_gate(
    tmp_path: Path,
) -> None:
    state = _scenario(tmp_path / "cutover-development.sqlite3")
    backend, coordinator, change, architecture, source = (
        _direct_goal_change_ready_for_architecture(state)
    )
    gate_id = reconcile_owner_change_gates(
        coordinator,
        change_ids=(change.change_id,),
    )[0]
    gates = GateService(state["changes"], verify_owner=lambda *_: True)
    gates.decide(
        gate_id,
        approved=True,
        artifact_digest=architecture.digest,
        actor_id="owner",
        source_session_id="owner-verified-session",
        source_turn_id="owner-verified-turn",
        request_key="owner-verified-request",
    )
    assert state["changes"].require(change.change_id).state is (
        ChangeState.APPROVED_FOR_BUILD
    )

    projector = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    )
    result = SupervisorCutoverController(
        projector=projector,
        change_coordinator=coordinator,
        mode=AutonomyMode.ASSISTED,
    ).coordinate(state["goal"].goal_id)

    persisted = state["changes"].require(change.change_id)
    development = [
        stage
        for stage in state["changes"].list_stages(change.change_id)
        if stage.stage_key == "development"
    ]
    assert result.action is SupervisorAction.RESUME_DEVELOPMENT
    assert result.disposition is SupervisorCutoverDisposition.RECONCILED_CHANGE
    assert result.mutation_performed is True
    assert persisted.state is ChangeState.DEVELOPING
    assert len(development) == 1
    assert development[0].plan_artifact_id == architecture.artifact_id
    assert development[0].work_id in backend.submissions
    assert source.work_id in backend.submissions


def test_supervisor_cutover_revalidates_and_rejects_stale_decision(
    tmp_path: Path,
) -> None:
    state = _scenario(tmp_path / "cutover-stale.sqlite3")
    _backend, coordinator, change, architecture, _ = (
        _direct_goal_change_ready_for_architecture(state)
    )
    gate_id = reconcile_owner_change_gates(
        coordinator,
        change_ids=(change.change_id,),
    )[0]
    GateService(state["changes"], verify_owner=lambda *_: True).decide(
        gate_id,
        approved=True,
        artifact_digest=architecture.digest,
        actor_id="owner",
        source_session_id="owner-stale-session",
        source_turn_id="owner-stale-turn",
        request_key="owner-stale-request",
    )
    projector = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    )
    old_workspace = projector.project(state["goal"].goal_id)
    old_decision = GlobalSupervisor().evaluate(old_workspace)
    assert old_decision.proposal.action is SupervisorAction.RESUME_DEVELOPMENT

    state["changes"].add_artifact(
        change.change_id,
        kind="cutover_test_observation",
        payload={
            "schema": "cutover_test_observation.v1",
            "value": "new canonical fact",
        },
    )
    before_stage_count = len(state["changes"].list_stages(change.change_id))

    result = SupervisorCutoverController(
        projector=projector,
        change_coordinator=coordinator,
        mode=AutonomyMode.ASSISTED,
    ).coordinate(
        state["goal"].goal_id,
        decision=old_decision,
    )

    assert result.disposition is SupervisorCutoverDisposition.REJECTED
    assert result.accepted is False
    assert "workspace_digest_mismatch" in result.reason_codes
    assert result.mutation_performed is False
    assert len(state["changes"].list_stages(change.change_id)) == before_stage_count
    assert state["changes"].require(change.change_id).state is (
        ChangeState.APPROVED_FOR_BUILD
    )


def test_supervisor_cutover_rejects_active_bounded_mode(tmp_path: Path) -> None:
    state = _scenario(tmp_path / "cutover-active.sqlite3")
    coordinator = ChangeCoordinator(
        state["changes"],
        _SupervisorCutoverBackend(),
    )
    projector = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    )

    with pytest.raises(ValueError, match="ACTIVE_BOUNDED"):
        SupervisorCutoverController(
            projector=projector,
            change_coordinator=coordinator,
            mode=AutonomyMode.ACTIVE_BOUNDED,
        )


def _existing_resume_controller(state, *, mode=AutonomyMode.SHADOW):
    backend = _SupervisorCutoverBackend()
    coordinator = ChangeCoordinator(state["changes"], backend)
    projector = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    )
    cutover = SupervisorCutoverController(
        projector=projector,
        change_coordinator=coordinator,
        mode=mode,
    )
    return (
        backend,
        ExistingObjectiveResumeController(
            projector=projector,
            change_store=state["changes"],
            cutover=cutover,
        ),
    )


def test_existing_objective_resume_inspects_exact_canonical_lineage(
    tmp_path: Path,
) -> None:
    state = _scenario(tmp_path / "existing-resume.sqlite3")
    _, controller = _existing_resume_controller(state)
    lineage = ExistingObjectiveLineageV1(
        goal_id=state["goal"].goal_id,
        gap_id=state["gap"].gap_id,
        change_id=state["change"].change_id,
        historical_architecture_artifact_id=state["architecture"].artifact_id,
    )

    snapshot = controller.inspect(lineage)

    assert snapshot.goal_id == state["goal"].goal_id
    assert snapshot.gap_id == state["gap"].gap_id
    assert snapshot.change_id == state["change"].change_id
    assert snapshot.change_state == ChangeState.RESEARCHING.value
    assert (
        snapshot.current_architecture_artifact_id == state["architecture"].artifact_id
    )
    assert snapshot.current_architecture_digest == state["architecture"].digest
    assert snapshot.current_phase == "research"
    assert snapshot.next_legal_actions == ("WAIT_RESOURCE", "RETRY")
    assert snapshot.active_work_id == state["research"].work_id
    assert snapshot.target_names == ("Hisense U7N",)
    assert snapshot.capability_families == ("media_player.control",)
    assert snapshot.historical_architecture_verified is True
    assert snapshot.historical_gate_verified is True


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("goal_id", "goal_not_this_objective"),
        ("gap_id", "gap_not_this_objective"),
        ("change_id", "change_not_this_objective"),
    ),
)
def test_existing_objective_resume_refuses_identity_drift(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    state = _scenario(tmp_path / f"existing-resume-drift-{field}.sqlite3")
    _, controller = _existing_resume_controller(state)
    payload = {
        "goal_id": state["goal"].goal_id,
        "gap_id": state["gap"].gap_id,
        "change_id": state["change"].change_id,
    }
    payload[field] = replacement

    with pytest.raises((ExistingObjectiveLineageError, GoalStoreError)):
        controller.inspect(ExistingObjectiveLineageV1(**payload))


def test_existing_objective_resume_has_no_creation_fallback(tmp_path: Path) -> None:
    state = _scenario(tmp_path / "existing-resume-no-create.sqlite3")
    backend, controller = _existing_resume_controller(state)
    lineage = ExistingObjectiveLineageV1(
        goal_id=state["goal"].goal_id,
        gap_id=state["gap"].gap_id,
        change_id=state["change"].change_id,
    )
    before_goals = tuple(
        item.goal_id for item in state["goals"].list_active_goals(limit=100)
    )
    before_changes = state["changes"].active_ids()
    before_work = tuple(item.work_id for item in state["work"].list(limit=100))

    snapshot, result = controller.coordinate_once(lineage)

    assert snapshot.goal_id == lineage.goal_id
    assert result.disposition is SupervisorCutoverDisposition.SHADOW_ONLY
    assert result.mutation_performed is False
    assert (
        tuple(item.goal_id for item in state["goals"].list_active_goals(limit=100))
        == before_goals
    )
    assert state["changes"].active_ids() == before_changes
    assert tuple(item.work_id for item in state["work"].list(limit=100)) == before_work
    assert backend.submissions == []


def test_existing_objective_resume_rejects_wrong_historical_architecture(
    tmp_path: Path,
) -> None:
    state = _scenario(tmp_path / "existing-resume-architecture.sqlite3")
    _, controller = _existing_resume_controller(state)

    with pytest.raises(
        ExistingObjectiveLineageError,
        match="historical architecture anchor",
    ):
        controller.inspect(
            ExistingObjectiveLineageV1(
                goal_id=state["goal"].goal_id,
                gap_id=state["gap"].gap_id,
                change_id=state["change"].change_id,
                historical_architecture_artifact_id="artifact_not_in_change",
            )
        )


def test_blocked_capability_continuation_outranks_newer_direct_change(
    tmp_path: Path,
) -> None:
    state = _scenario(tmp_path / "continuation-authority.sqlite3")
    competing = state["changes"].create(
        request="A newer direct change must not steal capability-continuation authority.",
        process_key=state["changes"].DEFAULT_PROCESS.key,
        process_version=state["changes"].DEFAULT_PROCESS.version,
        source_session_id=state["goal"].source_session_id,
        source_turn_id=state["goal"].source_turn_id,
    )

    workspace = ObjectiveWorkspaceProjector(
        goal_store=state["goals"],
        change_store=state["changes"],
    ).project(state["goal"].goal_id)
    progress = build_progress_ledger(workspace)

    assert competing.change_id != state["change"].change_id
    assert progress.active_change_id == state["change"].change_id
    assert progress.phase == "research"
    assert progress.active_work_id == state["research"].work_id

    _, controller = _existing_resume_controller(state)
    snapshot = controller.inspect(
        ExistingObjectiveLineageV1(
            goal_id=state["goal"].goal_id,
            gap_id=state["gap"].gap_id,
            change_id=state["change"].change_id,
            historical_architecture_artifact_id=state["architecture"].artifact_id,
        )
    )
    assert snapshot.change_id == state["change"].change_id
    assert snapshot.current_phase == "research"
