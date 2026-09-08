from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from jarvis.conversation import ConversationRole, ConversationTurn
from jarvis.memory.context import (
    ContextAssembler,
    ContextBudgetExceededError,
    ContextItemKind,
    Utf8ByteBudgetEstimator,
)
from jarvis.memory.live_context import LiveContext, LiveContextPriority
from jarvis.memory.types import Sensitivity


@dataclass
class FakeClock:
    now_ns: int = 1_000_000_000

    def __call__(self) -> int:
        return self.now_ns

    def advance(self, nanoseconds: int = 1) -> None:
        self.now_ns += nanoseconds


def _turn(
    turn_id: str,
    role: ConversationRole,
    text: str,
    *,
    external_item_id: str | None = None,
) -> ConversationTurn:
    return ConversationTurn(
        role=role,
        text=text,
        turn_id=turn_id,
        accepted_at=datetime(2026, 9, 5, 7, 0, tzinfo=UTC),
        external_item_id=external_item_id,
    )


def test_context_assembler_applies_precedence_and_keeps_canonical_refs_only() -> None:
    clock = FakeClock()
    live = LiveContext(max_recent_turns=4, clock_ns=clock)
    old_turn = _turn(
        "turn-old",
        ConversationRole.USER,
        "older user turn",
        external_item_id="provider-old",
    )
    assistant_turn = _turn(
        "turn-assistant",
        ConversationRole.ASSISTANT,
        "recent assistant turn",
        external_item_id="provider-assistant",
    )
    current_turn = _turn(
        "turn-current",
        ConversationRole.USER,
        "current request",
        external_item_id="provider-current",
    )
    for turn in (old_turn, assistant_turn, current_turn):
        assert live.observe_turn(turn) is True

    live.set_unresolved_work(
        "low",
        "low priority unresolved",
        source_turn_id="turn-old",
        priority=LiveContextPriority.LOW,
    )
    clock.advance()
    live.set_unresolved_work(
        "high",
        "high priority unresolved",
        source_turn_id="turn-current",
        priority=LiveContextPriority.CRITICAL,
    )
    live.set_active_goal("finish 4.2", source_turn_id="turn-current")
    live.set_active_topic("context assembly", source_turn_id="turn-current")
    live.set_entity("device", "Pocket 3", source_turn_id="turn-old")
    live.set_interaction_context("style", "brief", source_ref="runtime:style")

    packet = ContextAssembler(
        estimator=Utf8ByteBudgetEstimator(framing_overhead_units=0),
        max_units=10_000,
    ).assemble(live.snapshot(), current_turn=current_turn)

    assert [item.kind for item in packet.items] == [
        ContextItemKind.CURRENT_TURN,
        ContextItemKind.UNRESOLVED_WORK,
        ContextItemKind.UNRESOLVED_WORK,
        ContextItemKind.ACTIVE_GOAL,
        ContextItemKind.ACTIVE_TOPIC,
        ContextItemKind.ENTITY,
        ContextItemKind.INTERACTION_CONTEXT,
        ContextItemKind.RECENT_TURN,
        ContextItemKind.RECENT_TURN,
    ]
    assert packet.items[1].text.startswith("Unresolved work [high]")
    assert packet.items[2].text.startswith("Unresolved work [low]")
    assert [item.source_turn_id for item in packet.items[-2:]] == [
        "turn-assistant",
        "turn-old",
    ]
    assert all("provider-" not in (item.source_ref or "") for item in packet.items)
    assert sum(item.budget_units for item in packet.items) == packet.used_units
    assert packet.used_units <= packet.budget_units


def test_budget_keeps_high_precedence_context_and_drops_lower_items() -> None:
    live = LiveContext(max_recent_turns=3)
    older = _turn("turn-old", ConversationRole.USER, "old")
    current = _turn("turn-current", ConversationRole.USER, "now")
    live.observe_turn(older)
    live.observe_turn(current)
    unresolved = live.set_unresolved_work("next", "must do")
    live.set_active_goal("lower priority goal")
    live.set_active_topic("lower priority topic")

    estimator = Utf8ByteBudgetEstimator(framing_overhead_units=0)
    unresolved_text = f"Unresolved work [{unresolved.key}]: {unresolved.value}"
    exact_budget = estimator.estimate_text(current.text) + estimator.estimate_text(
        unresolved_text
    )
    packet = ContextAssembler(estimator=estimator, max_units=exact_budget).assemble(
        live.snapshot(),
        current_turn=current,
    )

    assert [item.kind for item in packet.items] == [
        ContextItemKind.CURRENT_TURN,
        ContextItemKind.UNRESOLVED_WORK,
    ]
    assert packet.used_units == exact_budget
    assert packet.dropped_count == 3


def test_required_current_turn_never_gets_silently_displaced() -> None:
    current = _turn("turn-current", ConversationRole.USER, "too large")
    live = LiveContext(max_recent_turns=1)
    live.observe_turn(current)

    with pytest.raises(ContextBudgetExceededError, match="current turn"):
        ContextAssembler(
            estimator=Utf8ByteBudgetEstimator(framing_overhead_units=0),
            max_units=1,
        ).assemble(live.snapshot(), current_turn=current)


def test_local_only_and_secret_prohibited_entries_never_leave_assembler() -> None:
    live = LiveContext(max_recent_turns=1)
    live.set_entity(
        "local",
        "local-only value",
        priority=LiveContextPriority.CRITICAL,
        sensitivity=Sensitivity.LOCAL_ONLY,
    )
    live.set_unresolved_work(
        "secret",
        "secret value",
        priority=LiveContextPriority.CRITICAL,
        sensitivity=Sensitivity.SECRET_PROHIBITED,
    )
    live.set_active_goal("allowed private value", sensitivity=Sensitivity.PRIVATE)

    packet = ContextAssembler(
        estimator=Utf8ByteBudgetEstimator(framing_overhead_units=0),
        max_units=1_000,
    ).assemble(live.snapshot())

    assert [item.kind for item in packet.items] == [ContextItemKind.ACTIVE_GOAL]
    assert packet.items[0].sensitivity is Sensitivity.PRIVATE
    assert packet.dropped_count == 2


def test_utf8_budget_estimator_is_deterministic_and_multilingual() -> None:
    estimator = Utf8ByteBudgetEstimator(framing_overhead_units=7)
    text = "याद रखो"
    assert estimator.estimate_text(text) == len(text.encode("utf-8")) + 7
    assert estimator.estimate_text(text) == estimator.estimate_text(text)


class BadEstimator:
    def __init__(self, result: object) -> None:
        self.result = result

    def estimate_text(self, text: str) -> int:
        del text
        return self.result  # type: ignore[return-value]


def test_context_assembler_validates_budget_and_estimator_results() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        ContextAssembler(estimator=Utf8ByteBudgetEstimator(), max_units=0)
    with pytest.raises(TypeError, match="integer"):
        ContextAssembler(estimator=Utf8ByteBudgetEstimator(), max_units=True)

    live = LiveContext(max_recent_turns=1)
    live.set_active_goal("goal")
    with pytest.raises(TypeError, match="return an integer"):
        ContextAssembler(estimator=BadEstimator("1"), max_units=10).assemble(
            live.snapshot()
        )
    with pytest.raises(ValueError, match="negative"):
        ContextAssembler(estimator=BadEstimator(-1), max_units=10).assemble(
            live.snapshot()
        )
