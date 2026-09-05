"""Deterministic, provider-independent assembly of bounded model context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from jarvis.conversation import ConversationRole, ConversationTurn

from .live_context import LiveContextEntry, LiveContextPriority, LiveContextSnapshot
from .types import Sensitivity


class ContextItemKind(StrEnum):
    CURRENT_TURN = "current_turn"
    UNRESOLVED_WORK = "unresolved_work"
    ACTIVE_GOAL = "active_goal"
    ACTIVE_TOPIC = "active_topic"
    ENTITY = "entity"
    INTERACTION_CONTEXT = "interaction_context"
    RECENT_TURN = "recent_turn"


class ContextBudgetEstimator(Protocol):
    def estimate_text(self, text: str) -> int:
        """Return deterministic local budget units for one framed text item."""


@dataclass(frozen=True, slots=True)
class Utf8ByteBudgetEstimator:
    """Conservative local estimator; units are bytes, not provider billing tokens."""

    framing_overhead_units: int = 32

    def __post_init__(self) -> None:
        if isinstance(self.framing_overhead_units, bool) or not isinstance(
            self.framing_overhead_units, int
        ):
            raise TypeError("framing_overhead_units must be an integer")
        if self.framing_overhead_units < 0:
            raise ValueError("framing_overhead_units must not be negative")

    def estimate_text(self, text: str) -> int:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        return len(text.encode("utf-8")) + self.framing_overhead_units


@dataclass(frozen=True, slots=True)
class ContextItem:
    kind: ContextItemKind
    text: str
    source_turn_id: str | None
    source_ref: str | None
    role: ConversationRole | None
    sensitivity: Sensitivity
    priority: LiveContextPriority
    budget_units: int


@dataclass(frozen=True, slots=True)
class ContextPacket:
    items: tuple[ContextItem, ...]
    used_units: int
    budget_units: int
    dropped_count: int
    snapshot_observed_at_ns: int


class ContextBudgetExceededError(ValueError):
    """Raised when required current context cannot fit the configured local budget."""


class ContextAssembler:
    """Sole Phase-4 release boundary for transient context destined for a model."""

    def __init__(
        self,
        *,
        estimator: ContextBudgetEstimator,
        max_units: int,
    ) -> None:
        if not hasattr(estimator, "estimate_text"):
            raise TypeError("estimator must provide estimate_text(text)")
        if isinstance(max_units, bool) or not isinstance(max_units, int):
            raise TypeError("max_units must be an integer")
        if max_units <= 0:
            raise ValueError("max_units must be greater than zero")
        self._estimator = estimator
        self._max_units = max_units

    @property
    def max_units(self) -> int:
        return self._max_units

    def assemble(
        self,
        snapshot: LiveContextSnapshot,
        *,
        current_turn: ConversationTurn | None = None,
    ) -> ContextPacket:
        if not isinstance(snapshot, LiveContextSnapshot):
            raise TypeError("snapshot must be a LiveContextSnapshot")
        if current_turn is not None and not isinstance(current_turn, ConversationTurn):
            raise TypeError("current_turn must be a ConversationTurn when provided")

        candidates = self._candidates(snapshot, current_turn=current_turn)
        selected: list[ContextItem] = []
        used_units = 0
        dropped_count = 0

        for item, required in candidates:
            if item.sensitivity in {
                Sensitivity.LOCAL_ONLY,
                Sensitivity.SECRET_PROHIBITED,
            }:
                dropped_count += 1
                continue
            if used_units + item.budget_units <= self._max_units:
                selected.append(item)
                used_units += item.budget_units
                continue
            if required:
                raise ContextBudgetExceededError(
                    "required current turn exceeds the configured local context budget"
                )
            dropped_count += 1

        return ContextPacket(
            items=tuple(selected),
            used_units=used_units,
            budget_units=self._max_units,
            dropped_count=dropped_count,
            snapshot_observed_at_ns=snapshot.observed_at_ns,
        )

    def _candidates(
        self,
        snapshot: LiveContextSnapshot,
        *,
        current_turn: ConversationTurn | None,
    ) -> list[tuple[ContextItem, bool]]:
        candidates: list[tuple[ContextItem, bool]] = []
        current_turn_id = current_turn.turn_id if current_turn is not None else None

        if current_turn is not None:
            candidates.append((self._turn_item(current_turn, current=True), True))

        for entry in self._ordered_entries(snapshot.unresolved_work):
            candidates.append(
                (self._entry_item(ContextItemKind.UNRESOLVED_WORK, entry), False)
            )
        if snapshot.active_goal is not None:
            candidates.append(
                (
                    self._entry_item(ContextItemKind.ACTIVE_GOAL, snapshot.active_goal),
                    False,
                )
            )
        if snapshot.active_topic is not None:
            candidates.append(
                (
                    self._entry_item(ContextItemKind.ACTIVE_TOPIC, snapshot.active_topic),
                    False,
                )
            )
        for entry in self._ordered_entries(snapshot.entities):
            candidates.append((self._entry_item(ContextItemKind.ENTITY, entry), False))
        for entry in self._ordered_entries(snapshot.interaction_context):
            candidates.append(
                (self._entry_item(ContextItemKind.INTERACTION_CONTEXT, entry), False)
            )

        for turn in reversed(snapshot.recent_turns):
            if turn.turn_id == current_turn_id:
                continue
            candidates.append((self._turn_item(turn, current=False), False))
        return candidates

    def _entry_item(
        self,
        kind: ContextItemKind,
        entry: LiveContextEntry,
    ) -> ContextItem:
        text = self._entry_text(kind, entry)
        return ContextItem(
            kind=kind,
            text=text,
            source_turn_id=entry.source_turn_id,
            source_ref=entry.source_ref,
            role=None,
            sensitivity=entry.sensitivity,
            priority=entry.priority,
            budget_units=self._estimate(text),
        )

    def _turn_item(self, turn: ConversationTurn, *, current: bool) -> ContextItem:
        kind = ContextItemKind.CURRENT_TURN if current else ContextItemKind.RECENT_TURN
        return ContextItem(
            kind=kind,
            text=turn.text,
            source_turn_id=turn.turn_id,
            source_ref=None,
            role=turn.role,
            sensitivity=Sensitivity.STANDARD,
            priority=(
                LiveContextPriority.CRITICAL if current else LiveContextPriority.NORMAL
            ),
            budget_units=self._estimate(turn.text),
        )

    def _estimate(self, text: str) -> int:
        units = self._estimator.estimate_text(text)
        if isinstance(units, bool) or not isinstance(units, int):
            raise TypeError("context budget estimator must return an integer")
        if units < 0:
            raise ValueError("context budget estimator must not return negative units")
        return units

    @staticmethod
    def _ordered_entries(
        entries: tuple[LiveContextEntry, ...],
    ) -> tuple[LiveContextEntry, ...]:
        return tuple(
            sorted(
                entries,
                key=lambda entry: (
                    -int(entry.priority),
                    -entry.set_at_ns,
                    entry.key,
                ),
            )
        )

    @staticmethod
    def _entry_text(kind: ContextItemKind, entry: LiveContextEntry) -> str:
        if kind is ContextItemKind.ACTIVE_GOAL:
            return f"Active goal: {entry.value}"
        if kind is ContextItemKind.ACTIVE_TOPIC:
            return f"Active topic: {entry.value}"
        if kind is ContextItemKind.UNRESOLVED_WORK:
            return f"Unresolved work [{entry.key}]: {entry.value}"
        if kind is ContextItemKind.ENTITY:
            return f"Entity [{entry.key}]: {entry.value}"
        if kind is ContextItemKind.INTERACTION_CONTEXT:
            return f"Interaction context [{entry.key}]: {entry.value}"
        raise ValueError(f"unsupported live-context entry kind: {kind.value}")
