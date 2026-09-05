from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from jarvis.conversation import ConversationRole, ConversationTurn
from jarvis.memory.live_context import (
    LiveContext,
    LiveContextKind,
    LiveContextPriority,
)
from jarvis.memory.types import Sensitivity


@dataclass
class FakeClock:
    now_ns: int = 1_000_000_000

    def __call__(self) -> int:
        return self.now_ns

    def advance(self, seconds: float) -> None:
        self.now_ns += int(seconds * 1_000_000_000)


def _turn(
    turn_id: str,
    role: ConversationRole,
    text: str,
    *,
    interrupted: bool = False,
    external_item_id: str | None = None,
) -> ConversationTurn:
    return ConversationTurn(
        role=role,
        text=text,
        interrupted=interrupted,
        turn_id=turn_id,
        accepted_at=datetime(2026, 9, 5, 6, 0, tzinfo=UTC),
        external_item_id=external_item_id,
    )


def test_recent_turns_are_bounded_ordered_and_duplicate_safe() -> None:
    context = LiveContext(max_recent_turns=2)
    first = _turn("turn-1", ConversationRole.USER, "first")
    second = _turn(
        "turn-2",
        ConversationRole.ASSISTANT,
        "second",
        interrupted=True,
        external_item_id="provider-2",
    )
    third = _turn("turn-3", ConversationRole.USER, "third")

    assert context.observe_turn(first) is True
    assert context.observe_turn(second) is True
    assert context.observe_turn(third) is True
    assert context.observe_turn(first) is False

    assert [turn.turn_id for turn in context.recent_turns] == ["turn-2", "turn-3"]
    assert context.recent_turns[0].interrupted is True
    assert context.recent_turns[0].external_item_id == "provider-2"


def test_transient_entries_use_monotonic_ttl_and_snapshot_prunes_expired() -> None:
    clock = FakeClock()
    context = LiveContext(max_recent_turns=4, clock_ns=clock)

    goal = context.set_active_goal(
        "finish Phase 4.2",
        source_turn_id="turn-goal",
        ttl_seconds=2,
    )
    context.set_active_topic("live context")
    context.set_entity("zeta", "last", ttl_seconds=1)
    context.set_entity("alpha", "first", ttl_seconds=3)
    context.set_unresolved_work(
        "provider-sync",
        "measure update_chat_ctx before enabling",
        priority=LiveContextPriority.CRITICAL,
    )
    context.set_interaction_context(
        "language",
        "Hinglish",
        sensitivity=Sensitivity.PRIVATE,
        ttl_seconds=0.5,
    )

    assert goal.kind is LiveContextKind.ACTIVE_GOAL
    assert goal.source_turn_id == "turn-goal"
    assert goal.expires_at_ns == goal.set_at_ns + 2_000_000_000

    initial = context.snapshot()
    assert [entry.key for entry in initial.entities] == ["alpha", "zeta"]
    assert initial.interaction_context[0].sensitivity is Sensitivity.PRIVATE

    clock.advance(1)
    after_one_second = context.snapshot()
    assert after_one_second.active_goal is not None
    assert [entry.key for entry in after_one_second.entities] == ["alpha"]
    assert after_one_second.interaction_context == ()

    clock.advance(1)
    after_two_seconds = context.snapshot()
    assert after_two_seconds.active_goal is None
    assert after_two_seconds.active_topic is not None
    assert after_two_seconds.unresolved_work[0].priority is LiveContextPriority.CRITICAL


def test_explicit_removal_and_clear_dispose_session_state() -> None:
    clock = FakeClock()
    context = LiveContext(max_recent_turns=3, clock_ns=clock)
    turn = _turn("turn-1", ConversationRole.USER, "hello")
    context.observe_turn(turn)
    context.set_active_goal("goal")
    context.set_active_topic("topic")
    context.set_entity("device", "Pocket 3")
    context.set_unresolved_work("next", "run test")
    context.set_interaction_context("style", "brief")

    context.remove_active_goal()
    context.remove_active_topic()
    context.remove_entity("device")
    context.remove_unresolved_work("next")
    context.remove_interaction_context("style")

    snapshot = context.snapshot()
    assert snapshot.active_goal is None
    assert snapshot.active_topic is None
    assert snapshot.entities == ()
    assert snapshot.unresolved_work == ()
    assert snapshot.interaction_context == ()
    assert len(snapshot.recent_turns) == 1

    context.clear()
    assert context.snapshot().recent_turns == ()
    assert context.observe_turn(turn) is True


def test_prune_expired_reports_removed_entry_count() -> None:
    clock = FakeClock()
    context = LiveContext(max_recent_turns=1, clock_ns=clock)
    context.set_active_goal("goal", ttl_seconds=1)
    context.set_active_topic("topic", ttl_seconds=1)
    context.set_entity("entity", "value", ttl_seconds=1)
    context.set_unresolved_work("work", "value", ttl_seconds=1)
    context.set_interaction_context("style", "value", ttl_seconds=1)

    clock.advance(1)
    assert context.prune_expired() == 5
    assert context.prune_expired() == 0


def test_live_context_validates_bounds_ttl_and_clock() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        LiveContext(max_recent_turns=0)
    with pytest.raises(TypeError, match="integer"):
        LiveContext(max_recent_turns=True)

    context = LiveContext(max_recent_turns=1)
    with pytest.raises(ValueError, match="greater than zero"):
        context.set_entity("entity", "value", ttl_seconds=0)
    with pytest.raises(TypeError, match="numeric"):
        context.set_entity("entity", "value", ttl_seconds=True)
    with pytest.raises(TypeError, match="LiveContextPriority"):
        context.set_entity("entity", "value", priority=20)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Sensitivity"):
        context.set_entity("entity", "value", sensitivity="standard")  # type: ignore[arg-type]

    bad_clock_context = LiveContext(max_recent_turns=1, clock_ns=lambda: -1)
    with pytest.raises(ValueError, match="negative"):
        bad_clock_context.set_active_goal("goal")
