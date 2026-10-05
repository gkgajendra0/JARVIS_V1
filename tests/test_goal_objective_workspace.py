from dataclasses import replace
from pathlib import Path

import pytest

from jarvis.autonomy import (
    GlobalSupervisor,
    SupervisorAction,
    SupervisorProposalV1,
    supervisor_context_from_workspace,
)

from jarvis.capability_acquisition.process import OWNER_CAPABILITY_ACQUISITION_PROCESS
from jarvis.engineering_change import ChangeState, ChangeStore
from jarvis.engineering_substrate.canonical import canonical_digest
from jarvis.goal_intelligence.ledgers import (
    build_progress_ledger,
    build_task_ledger,
)
from jarvis.goal_intelligence.models import (
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

    stale = SupervisorProposalV1(
        schema=illegal.schema,
        goal_id=illegal.goal_id,
        action=SupervisorAction.WAIT_RESOURCE,
        rationale="Wait for the provider.",
        workspace_digest="0" * 64,
        task_ledger_digest=illegal.task_ledger_digest,
        progress_ledger_digest=illegal.progress_ledger_digest,
        target_change_id="change_stale",
        target_work_id="work_stale",
        bounded_question=None,
        evidence_refs=(),
        digest="pending",
    )
    stale = replace(
        stale,
        digest=canonical_digest(stale.canonical_payload()),
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
