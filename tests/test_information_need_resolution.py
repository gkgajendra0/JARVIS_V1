from pathlib import Path

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.goal_intelligence.information import (
    BoundInformationInteraction,
    InformationProbeResult,
    InformationResolutionState,
    InformationResolutionStrategy,
    InformationResolver,
    restore_bound_information_interaction,
)
from jarvis.goal_intelligence.models import (
    GoalKind,
    InformationNeedCategory,
    InformationNeedState,
    InformationNeedV1,
    OwnerGoalV2,
)
from jarvis.goal_intelligence.store import GoalStore, GoalStoreConflict
from jarvis.work.privacy import ProtectedWorkPayloadCodec
from jarvis.work.store import SQLiteWorkStore


class StaticProbe:
    def __init__(
        self,
        strategy: InformationResolutionStrategy,
        *,
        resolution_ref: str | None = None,
    ) -> None:
        self.strategy = strategy
        self.resolution_ref = resolution_ref
        self.calls = 0

    def resolve(self, need: InformationNeedV1) -> InformationProbeResult:
        self.calls += 1
        return InformationProbeResult(
            resolution_ref=self.resolution_ref,
            evidence_refs=(f"probe:{self.strategy.value}",),
        )


def _store(tmp_path: Path) -> tuple[GoalStore, OwnerGoalV2]:
    work = SQLiteWorkStore(
        tmp_path / "work.sqlite3",
        payload_codec=ProtectedWorkPayloadCodec(b"n" * 32),
    )
    store = GoalStore(work)
    goal = store.create_goal(
        OwnerGoalV2.create(
            source_session_id="session-info",
            source_turn_id="turn-info",
            exact_owner_request="Use my TV.",
            goal_kind=GoalKind.ONE_SHOT,
            desired_outcome="Use the intended TV.",
            created_at="2026-10-01T12:00:00+00:00",
        )
    )
    return store, goal


def _need(goal: OwnerGoalV2) -> InformationNeedV1:
    return InformationNeedV1.create(
        goal_id=goal.goal_id,
        category=InformationNeedCategory.AMBIGUOUS_REFERENCE,
        subject="TV",
        required_fact="which TV is intended",
        why_required="The selected resource changes the target.",
        candidate_values=("entity:tv-a", "entity:tv-b"),
        allowed_resolution_sources=(
            "conversation_context",
            "world_registry",
            "bounded_local_discovery",
            "owner_input",
        ),
        owner_question="Which TV do you mean?",
        answer_schema={"type": "entity_id"},
        created_at="2026-10-01T12:01:00+00:00",
    )


def test_self_resolution_precedes_owner_input(tmp_path: Path) -> None:
    store, goal = _store(tmp_path)
    context = StaticProbe(InformationResolutionStrategy.CONVERSATION_CONTEXT)
    world = StaticProbe(
        InformationResolutionStrategy.WORLD_REGISTRY,
        resolution_ref="entity:tv-a",
    )
    resolver = InformationResolver(store=store, probes=(context, world))

    result = resolver.resolve(_need(goal))

    assert result.state is InformationResolutionState.RESOLVED
    assert result.need.state is InformationNeedState.RESOLVED
    assert result.need.resolution_ref == "entity:tv-a"
    assert context.calls == 1
    assert world.calls == 1
    assert result.interaction is None


def test_owner_input_is_last_and_creates_exact_binding(tmp_path: Path) -> None:
    store, goal = _store(tmp_path)
    context = StaticProbe(InformationResolutionStrategy.CONVERSATION_CONTEXT)
    world = StaticProbe(InformationResolutionStrategy.WORLD_REGISTRY)
    discovery = StaticProbe(InformationResolutionStrategy.BOUNDED_LOCAL_DISCOVERY)
    resolver = InformationResolver(
        store=store,
        probes=(context, world, discovery),
    )

    result = resolver.resolve(
        _need(goal),
        created_at="2026-10-01T12:02:00+00:00",
    )

    assert result.state is InformationResolutionState.NEEDS_OWNER
    assert result.need.state is InformationNeedState.WAITING_FOR_OWNER
    assert result.interaction is not None
    assert result.interaction["goal_id"] == goal.goal_id
    assert result.interaction["information_need_id"] == result.need.information_need_id
    assert result.need.self_resolution_attempts == (
        "bounded_local_discovery",
        "conversation_context",
        "world_registry",
    )


def test_unrelated_or_wrong_bound_reply_cannot_resolve_need(tmp_path: Path) -> None:
    store, goal = _store(tmp_path)
    result = InformationResolver(store=store).resolve(
        _need(goal),
        created_at="2026-10-01T12:02:00+00:00",
    )
    assert result.interaction is not None
    interaction_id = str(result.interaction["interaction_id"])

    with pytest.raises(GoalStoreConflict, match="does not match"):
        store.submit_information_interaction_reply(
            interaction_id=interaction_id,
            goal_id="goal_other",
            need_id=result.need.information_need_id,
            source_turn_id="ambient-turn",
            resolution_ref="entity:tv-a",
            resolved_at="2026-10-01T12:03:00+00:00",
        )

    current = store.get_information_need(result.need.information_need_id)
    assert current is not None
    assert current.state is InformationNeedState.WAITING_FOR_OWNER


def test_exact_bound_reply_resolves_once_and_survives_restart(tmp_path: Path) -> None:
    store, goal = _store(tmp_path)
    result = InformationResolver(store=store).resolve(
        _need(goal),
        created_at="2026-10-01T12:02:00+00:00",
    )
    assert result.interaction is not None
    interaction_id = str(result.interaction["interaction_id"])

    restored = restore_bound_information_interaction(
        store=store,
        interaction_id=interaction_id,
    )
    conversation = ConversationSession(session_id="owner-bound-session")
    conversation.start()
    turn = conversation.accept_turn(ConversationRole.USER, "Use the living room TV")

    resolved = restored.submit(
        turn,
        resolution_ref="entity:tv-a",
        resolved_at="2026-10-01T12:03:00+00:00",
    )
    repeated = restored.submit(
        turn,
        resolution_ref="entity:tv-a",
        resolved_at="2026-10-01T12:03:00+00:00",
    )

    assert resolved.state is InformationNeedState.RESOLVED
    assert repeated == resolved
    snapshot = store.get_information_interaction(interaction_id)
    assert snapshot is not None
    assert snapshot["state"] == "resolved"
    assert snapshot["resolved_turn_id"] == turn.turn_id


def test_another_need_cannot_receive_bound_reply(tmp_path: Path) -> None:
    store, goal = _store(tmp_path)
    first = InformationResolver(store=store).resolve(
        _need(goal),
        created_at="2026-10-01T12:02:00+00:00",
    )
    second_need = InformationNeedV1.create(
        goal_id=goal.goal_id,
        category=InformationNeedCategory.SUCCESS_CRITERIA,
        subject="playback",
        required_fact="what counts as playback started",
        why_required="Success criteria materially affects completion.",
        allowed_resolution_sources=("owner_input",),
        owner_question="What should count as started?",
        answer_schema={"type": "text"},
        created_at="2026-10-01T12:04:00+00:00",
    )
    second = InformationResolver(store=store).resolve(
        second_need,
        created_at="2026-10-01T12:05:00+00:00",
    )
    assert first.interaction is not None
    assert second.interaction is not None

    with pytest.raises(GoalStoreConflict, match="do not match"):
        BoundInformationInteraction(
            store=store,
            interaction_id=str(first.interaction["interaction_id"]),
            goal_id=goal.goal_id,
            information_need_id=second.need.information_need_id,
        )


def test_resolution_merges_repeated_observation_evidence_without_duplicates(
    tmp_path: Path,
) -> None:
    store, goal = _store(tmp_path)
    unresolved = store.create_information_need(
        InformationNeedV1.create(
            goal_id=goal.goal_id,
            category=InformationNeedCategory.AMBIGUOUS_REFERENCE,
            subject="my TV",
            required_fact="independently reviewed TV target",
            why_required="prevent an incorrect device action",
            allowed_resolution_sources=("world_registry", "owner_input"),
            evidence_refs=("owner_inventory:verified_owner_selection",),
        )
    )
    resolved = store.resolve_information_need(
        unresolved.information_need_id,
        resolution_ref="entity:tv-a",
        evidence_refs=(
            "owner_inventory:verified_owner_selection",
            "world_exact:entity:tv-a",
        ),
        expected_revision=unresolved.revision,
        resolved_at="2026-10-01T12:05:00+00:00",
    )
    assert resolved.evidence_refs == (
        "owner_inventory:verified_owner_selection",
        "world_exact:entity:tv-a",
    )
    assert resolved.state is InformationNeedState.RESOLVED
    assert store.get_information_need(unresolved.information_need_id) == resolved


def test_cancelled_need_cannot_restart_probes_or_owner_interactions(
    tmp_path: Path,
) -> None:
    store, goal = _store(tmp_path)
    original = store.create_information_need(_need(goal))
    cancelled = store.update_information_need_state(
        original.information_need_id,
        InformationNeedState.CANCELLED,
        expected_revision=original.revision,
    )
    probe = StaticProbe(
        InformationResolutionStrategy.WORLD_REGISTRY,
        resolution_ref="entity:tv-a",
    )
    result = InformationResolver(store=store, probes=(probe,)).resolve(
        original,
        created_at="2026-10-01T12:10:00+00:00",
    )

    assert result.state is InformationResolutionState.UNRESOLVED
    assert result.need == cancelled
    assert result.interaction is None
    assert result.attempted_strategies == ()
    assert probe.calls == 0
    assert store.get_information_need(original.information_need_id) == cancelled
