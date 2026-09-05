"""Provider-independent, process-local working context for JARVIS sessions."""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum, StrEnum

from jarvis.conversation import ConversationTurn

from .types import Sensitivity


class LiveContextKind(StrEnum):
    ACTIVE_GOAL = "active_goal"
    ACTIVE_TOPIC = "active_topic"
    ENTITY = "entity"
    UNRESOLVED_WORK = "unresolved_work"
    INTERACTION_CONTEXT = "interaction_context"


class LiveContextPriority(IntEnum):
    LOW = 10
    NORMAL = 20
    HIGH = 30
    CRITICAL = 40


@dataclass(frozen=True, slots=True)
class LiveContextEntry:
    """One deterministic, transient piece of session context."""

    kind: LiveContextKind
    key: str
    value: str
    source_turn_id: str | None
    source_ref: str | None
    set_at_ns: int
    expires_at_ns: int | None
    priority: LiveContextPriority
    sensitivity: Sensitivity

    def is_expired(self, now_ns: int) -> bool:
        return self.expires_at_ns is not None and now_ns >= self.expires_at_ns


@dataclass(frozen=True, slots=True)
class LiveContextSnapshot:
    """Immutable view of non-expired live state at one monotonic instant."""

    recent_turns: tuple[ConversationTurn, ...]
    active_goal: LiveContextEntry | None
    active_topic: LiveContextEntry | None
    entities: tuple[LiveContextEntry, ...]
    unresolved_work: tuple[LiveContextEntry, ...]
    interaction_context: tuple[LiveContextEntry, ...]
    observed_at_ns: int


class LiveContext:
    """Own transient working context for exactly one conversation session."""

    def __init__(
        self,
        *,
        max_recent_turns: int,
        clock_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        if isinstance(max_recent_turns, bool) or not isinstance(max_recent_turns, int):
            raise TypeError("max_recent_turns must be an integer")
        if max_recent_turns <= 0:
            raise ValueError("max_recent_turns must be greater than zero")
        if not callable(clock_ns):
            raise TypeError("clock_ns must be callable")

        self._clock_ns = clock_ns
        self._recent_turns: deque[ConversationTurn] = deque(maxlen=max_recent_turns)
        self._seen_turn_ids: set[str] = set()
        self._active_goal: LiveContextEntry | None = None
        self._active_topic: LiveContextEntry | None = None
        self._entities: dict[str, LiveContextEntry] = {}
        self._unresolved_work: dict[str, LiveContextEntry] = {}
        self._interaction_context: dict[str, LiveContextEntry] = {}

    @property
    def max_recent_turns(self) -> int:
        maxlen = self._recent_turns.maxlen
        assert maxlen is not None
        return maxlen

    @property
    def recent_turns(self) -> tuple[ConversationTurn, ...]:
        return tuple(self._recent_turns)

    def observe_turn(self, turn: ConversationTurn) -> bool:
        """Record one canonical accepted turn; return False for a duplicate ID."""

        if not isinstance(turn, ConversationTurn):
            raise TypeError("turn must be a ConversationTurn")
        if turn.turn_id in self._seen_turn_ids:
            return False
        self._seen_turn_ids.add(turn.turn_id)
        self._recent_turns.append(turn)
        return True

    def set_active_goal(
        self,
        value: str,
        *,
        source_turn_id: str | None = None,
        source_ref: str | None = None,
        ttl_seconds: float | None = None,
        priority: LiveContextPriority = LiveContextPriority.HIGH,
        sensitivity: Sensitivity = Sensitivity.STANDARD,
    ) -> LiveContextEntry:
        entry = self._entry(
            LiveContextKind.ACTIVE_GOAL,
            "active_goal",
            value,
            source_turn_id=source_turn_id,
            source_ref=source_ref,
            ttl_seconds=ttl_seconds,
            priority=priority,
            sensitivity=sensitivity,
        )
        self._active_goal = entry
        return entry

    def remove_active_goal(self) -> None:
        self._active_goal = None

    def set_active_topic(
        self,
        value: str,
        *,
        source_turn_id: str | None = None,
        source_ref: str | None = None,
        ttl_seconds: float | None = None,
        priority: LiveContextPriority = LiveContextPriority.NORMAL,
        sensitivity: Sensitivity = Sensitivity.STANDARD,
    ) -> LiveContextEntry:
        entry = self._entry(
            LiveContextKind.ACTIVE_TOPIC,
            "active_topic",
            value,
            source_turn_id=source_turn_id,
            source_ref=source_ref,
            ttl_seconds=ttl_seconds,
            priority=priority,
            sensitivity=sensitivity,
        )
        self._active_topic = entry
        return entry

    def remove_active_topic(self) -> None:
        self._active_topic = None

    def set_entity(
        self,
        key: str,
        value: str,
        *,
        source_turn_id: str | None = None,
        source_ref: str | None = None,
        ttl_seconds: float | None = None,
        priority: LiveContextPriority = LiveContextPriority.NORMAL,
        sensitivity: Sensitivity = Sensitivity.STANDARD,
    ) -> LiveContextEntry:
        entry = self._entry(
            LiveContextKind.ENTITY,
            key,
            value,
            source_turn_id=source_turn_id,
            source_ref=source_ref,
            ttl_seconds=ttl_seconds,
            priority=priority,
            sensitivity=sensitivity,
        )
        self._entities[entry.key] = entry
        return entry

    def remove_entity(self, key: str) -> None:
        self._entities.pop(self._text(key, name="key"), None)

    def set_unresolved_work(
        self,
        key: str,
        value: str,
        *,
        source_turn_id: str | None = None,
        source_ref: str | None = None,
        ttl_seconds: float | None = None,
        priority: LiveContextPriority = LiveContextPriority.HIGH,
        sensitivity: Sensitivity = Sensitivity.STANDARD,
    ) -> LiveContextEntry:
        entry = self._entry(
            LiveContextKind.UNRESOLVED_WORK,
            key,
            value,
            source_turn_id=source_turn_id,
            source_ref=source_ref,
            ttl_seconds=ttl_seconds,
            priority=priority,
            sensitivity=sensitivity,
        )
        self._unresolved_work[entry.key] = entry
        return entry

    def remove_unresolved_work(self, key: str) -> None:
        self._unresolved_work.pop(self._text(key, name="key"), None)

    def set_interaction_context(
        self,
        key: str,
        value: str,
        *,
        source_turn_id: str | None = None,
        source_ref: str | None = None,
        ttl_seconds: float | None = None,
        priority: LiveContextPriority = LiveContextPriority.LOW,
        sensitivity: Sensitivity = Sensitivity.STANDARD,
    ) -> LiveContextEntry:
        entry = self._entry(
            LiveContextKind.INTERACTION_CONTEXT,
            key,
            value,
            source_turn_id=source_turn_id,
            source_ref=source_ref,
            ttl_seconds=ttl_seconds,
            priority=priority,
            sensitivity=sensitivity,
        )
        self._interaction_context[entry.key] = entry
        return entry

    def remove_interaction_context(self, key: str) -> None:
        self._interaction_context.pop(self._text(key, name="key"), None)

    def prune_expired(self) -> int:
        now_ns = self._now_ns()
        removed = 0

        if self._active_goal is not None and self._active_goal.is_expired(now_ns):
            self._active_goal = None
            removed += 1
        if self._active_topic is not None and self._active_topic.is_expired(now_ns):
            self._active_topic = None
            removed += 1

        for entries in (
            self._entities,
            self._unresolved_work,
            self._interaction_context,
        ):
            expired_keys = [
                key for key, entry in entries.items() if entry.is_expired(now_ns)
            ]
            for key in expired_keys:
                del entries[key]
            removed += len(expired_keys)
        return removed

    def snapshot(self) -> LiveContextSnapshot:
        now_ns = self._now_ns()
        self._prune_at(now_ns)
        return LiveContextSnapshot(
            recent_turns=tuple(self._recent_turns),
            active_goal=self._active_goal,
            active_topic=self._active_topic,
            entities=tuple(self._sorted_entries(self._entities)),
            unresolved_work=tuple(self._sorted_entries(self._unresolved_work)),
            interaction_context=tuple(self._sorted_entries(self._interaction_context)),
            observed_at_ns=now_ns,
        )

    def clear(self) -> None:
        """Dispose all session state, including duplicate-turn tracking."""

        self._recent_turns.clear()
        self._seen_turn_ids.clear()
        self._active_goal = None
        self._active_topic = None
        self._entities.clear()
        self._unresolved_work.clear()
        self._interaction_context.clear()

    def _entry(
        self,
        kind: LiveContextKind,
        key: str,
        value: str,
        *,
        source_turn_id: str | None,
        source_ref: str | None,
        ttl_seconds: float | None,
        priority: LiveContextPriority,
        sensitivity: Sensitivity,
    ) -> LiveContextEntry:
        if not isinstance(kind, LiveContextKind):
            raise TypeError("kind must be a LiveContextKind")
        normalized_key = self._text(key, name="key")
        normalized_value = self._text(value, name="value")
        normalized_turn_id = self._optional_text(source_turn_id, name="source_turn_id")
        normalized_source_ref = self._optional_text(source_ref, name="source_ref")
        if not isinstance(priority, LiveContextPriority):
            raise TypeError("priority must be a LiveContextPriority")
        if not isinstance(sensitivity, Sensitivity):
            raise TypeError("sensitivity must be a Sensitivity")

        set_at_ns = self._now_ns()
        expires_at_ns = self._expiry_ns(set_at_ns, ttl_seconds)
        return LiveContextEntry(
            kind=kind,
            key=normalized_key,
            value=normalized_value,
            source_turn_id=normalized_turn_id,
            source_ref=normalized_source_ref,
            set_at_ns=set_at_ns,
            expires_at_ns=expires_at_ns,
            priority=priority,
            sensitivity=sensitivity,
        )

    def _expiry_ns(self, set_at_ns: int, ttl_seconds: float | None) -> int | None:
        if ttl_seconds is None:
            return None
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int | float):
            raise TypeError("ttl_seconds must be numeric when provided")
        ttl = float(ttl_seconds)
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("ttl_seconds must be finite and greater than zero")
        ttl_ns = max(1, int(ttl * 1_000_000_000))
        return set_at_ns + ttl_ns

    def _now_ns(self) -> int:
        value = self._clock_ns()
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("clock_ns must return an integer nanosecond value")
        if value < 0:
            raise ValueError("clock_ns must not return a negative value")
        return value

    def _prune_at(self, now_ns: int) -> None:
        if self._active_goal is not None and self._active_goal.is_expired(now_ns):
            self._active_goal = None
        if self._active_topic is not None and self._active_topic.is_expired(now_ns):
            self._active_topic = None
        for entries in (
            self._entities,
            self._unresolved_work,
            self._interaction_context,
        ):
            for key in [
                key for key, entry in entries.items() if entry.is_expired(now_ns)
            ]:
                del entries[key]

    @staticmethod
    def _sorted_entries(entries: dict[str, LiveContextEntry]) -> list[LiveContextEntry]:
        return [entries[key] for key in sorted(entries)]

    @staticmethod
    def _text(value: str, *, name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"{name} must not be empty")
        return normalized

    @classmethod
    def _optional_text(cls, value: str | None, *, name: str) -> str | None:
        if value is None:
            return None
        return cls._text(value, name=name)
