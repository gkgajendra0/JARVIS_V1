"""SQLCipher-backed topic checkpoints; no independent database or read authority.

Callers must supply a current canonical owner statement AND a trusted existing
capability/Hello permit validation callback. Nothing here grants that permit.
All operations run on the canonical SerialConnectionWorker connections.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from jarvis.conversation import (
    ConversationRole,
    ConversationSession,
    ConversationStatus,
    ConversationTurn,
)

from .conversation_semantics import (
    _FORGET_CUE,
    _FORGET_NEGATION,
    EvidenceStrength,
    GroundedStateValue,
    TopicSnapshot,
)
from .types import Sensitivity
from .worker import SerialConnectionWorker

_SCOPE_OWNER = "owner"
_GENERIC_TOPIC_WORDS = frozenset(
    {"the", "my", "our", "plan", "planning", "trip", "road", "project", "discussion"}
)


class CheckpointRejected(PermissionError):
    """Checkpoint validation, authorization, or freshness failed closed."""


def _key(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 160:
        raise CheckpointRejected("invalid topic")
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _time(turn: ConversationTurn) -> str:
    return turn.accepted_at.astimezone(UTC).isoformat(timespec="microseconds")


def _canonical(
    conversation: ConversationSession,
    turn: ConversationTurn,
    *,
    require_latest: bool = True,
) -> None:
    if (
        not isinstance(conversation, ConversationSession)
        or conversation.status is not ConversationStatus.ACTIVE
        or not isinstance(turn, ConversationTurn)
        or turn.role is not ConversationRole.USER
        or not conversation.turns
        or not any(item is turn for item in conversation.turns)
        or (require_latest and conversation.turns[-1] is not turn)
    ):
        raise CheckpointRejected("accepted canonical owner USER turn required")


def _admit_snapshot(
    validator: Callable[[TopicSnapshot, ConversationTurn], bool],
    snapshot: TopicSnapshot,
    turn: ConversationTurn,
) -> None:
    """Independent non-model privacy, plan-suppression and source eligibility gate."""
    if not callable(validator):
        raise CheckpointRejected("trusted checkpoint admission required")
    try:
        allowed = validator(snapshot, turn)
    except Exception as exc:
        raise CheckpointRejected("checkpoint source admission denied") from exc
    if allowed is not True:
        raise CheckpointRejected("checkpoint source admission denied")


def _permit(validator: Callable[[], bool]) -> None:
    if not callable(validator):
        raise CheckpointRejected("validating permit callback required")
    try:
        result = validator()
    except Exception as exc:
        raise CheckpointRejected("owner capability permit denied") from exc
    if result is not True:
        raise CheckpointRejected("owner capability permit denied")


def _explicit_topic(question: str, title: str) -> bool:
    tokens = set(re.findall(r"\w+", unicodedata.normalize("NFKC", question).casefold()))
    distinctive = [
        part
        for part in re.findall(r"\w+", _key(title))
        if len(part) >= 4 and part not in _GENERIC_TOPIC_WORDS
    ]
    if distinctive:
        return all(part in tokens for part in distinctive)
    return _key(title) in unicodedata.normalize("NFKC", question).casefold()


def _plan_learning_suppressed(connection) -> bool:
    row = connection.execute(
        "SELECT suppressed FROM personal_learning_suppression WHERE category='plan'"
    ).fetchone()
    return row is not None and row[0] == 1


def _snapshot_payload(snapshot: TopicSnapshot) -> str:
    if not isinstance(snapshot, TopicSnapshot):
        raise TypeError("snapshot must be TopicSnapshot")
    _key(snapshot.title)

    def checked_value(value) -> str:
        if value.sensitivity is not Sensitivity.STANDARD:
            raise CheckpointRejected("restricted context cannot be checkpointed")
        if not isinstance(value.value, str) or not 1 <= len(value.value) <= 500:
            raise CheckpointRejected("invalid checkpoint field")
        return value.value

    if len(snapshot.constraints) > 20 or len(snapshot.steps) > 20:
        raise CheckpointRejected("checkpoint field budget exceeded")
    constraints: dict[str, str] = {}
    for name, value in snapshot.constraints:
        key = _key(name)
        if key in constraints:
            raise CheckpointRejected("duplicate constraint")
        constraints[key] = checked_value(value)
    steps: dict[str, dict[str, Any]] = {}
    for name, value in snapshot.steps:
        key = _key(name)
        if key in steps:
            raise CheckpointRejected("duplicate step")
        steps[key] = {"value": checked_value(value), "completed": value.completed}
    payload = {
        "title": snapshot.title,
        "goal": checked_value(snapshot.goal) if snapshot.goal else None,
        "constraints": constraints,
        "steps": steps,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    if len(encoded.encode("utf-8")) > 8192:
        raise CheckpointRejected("checkpoint exceeds 8192 bytes")
    return encoded


class EncryptedTopicCheckpointStore:
    """Internal storage adapter. Caller owns freshness/permission decisions.

    No auto-resume: read requires an actual current USER turn that names the topic.
    Read results must be authorized again before inclusion in a model response.
    """

    def __init__(
        self, *, writer: SerialConnectionWorker, reader: SerialConnectionWorker
    ) -> None:
        if not isinstance(writer, SerialConnectionWorker) or not isinstance(
            reader, SerialConnectionWorker
        ):
            raise TypeError("canonical memory workers are required")
        self._writer = writer
        self._reader = reader

    async def save(
        self,
        conversation: ConversationSession,
        turn: ConversationTurn,
        snapshot: TopicSnapshot,
        *,
        authorize_write: Callable[[], bool],
        admit_snapshot: Callable[[TopicSnapshot, ConversationTurn], bool],
        expected_plan_epoch: int,
    ) -> bool:
        if type(expected_plan_epoch) is not int or expected_plan_epoch < 0:
            raise CheckpointRejected("accepted-turn plan epoch is required")
        _canonical(conversation, turn, require_latest=False)
        _permit(authorize_write)
        _admit_snapshot(admit_snapshot, snapshot, turn)
        state_json = _snapshot_payload(snapshot)
        key, source_at = _key(snapshot.title), _time(turn)

        def write(connection) -> bool:
            _canonical(conversation, turn, require_latest=False)
            _permit(authorize_write)
            _admit_snapshot(admit_snapshot, snapshot, turn)
            connection.execute("BEGIN IMMEDIATE")
            try:
                if _plan_learning_suppressed(connection):
                    raise CheckpointRejected("plan category is suppressed")
                plan_epoch_row = connection.execute(
                    "SELECT epoch FROM personal_learning_suppression "
                    "WHERE category='plan'"
                ).fetchone()
                plan_epoch = plan_epoch_row[0] if plan_epoch_row else 0
                if plan_epoch != expected_plan_epoch:
                    raise CheckpointRejected("accepted-turn plan epoch changed")
                row = connection.execute(
                    "SELECT forgotten_at FROM conversation_topic_tombstone "
                    "WHERE topic_key IN (?, '*') ORDER BY forgotten_at DESC LIMIT 1",
                    (key,),
                ).fetchone()
                if row is not None and source_at <= row[0]:
                    raise CheckpointRejected("checkpoint is older than forget")
                previous = connection.execute(
                    "SELECT source_at, state_json FROM conversation_topic_checkpoint "
                    "WHERE topic_key=?",
                    (key,),
                ).fetchone()
                if previous is not None and source_at <= previous[0]:
                    connection.rollback()
                    return False
                connection.execute(
                    "INSERT INTO conversation_topic_checkpoint "
                    "(topic_key,source_turn_id,source_at,state_json) "
                    "VALUES (?,?,?,?) ON CONFLICT(topic_key) DO UPDATE SET "
                    "source_turn_id=excluded.source_turn_id, "
                    "source_at=excluded.source_at, state_json=excluded.state_json",
                    (key, turn.turn_id, source_at, state_json),
                )
                _canonical(conversation, turn, require_latest=False)
                _admit_snapshot(admit_snapshot, snapshot, turn)
                _permit(authorize_write)
                connection.commit()
                return True
            except BaseException:
                connection.rollback()
                raise

        return await self._writer.run(write)

    async def read_named(
        self,
        conversation: ConversationSession,
        request: ConversationTurn,
        *,
        title: str,
        authorize_read: Callable[[], bool],
    ) -> dict[str, Any] | None:
        _canonical(conversation, request)
        if not _explicit_topic(request.text, title):
            raise CheckpointRejected("resume request does not name the topic")
        _permit(authorize_read)
        key = _key(title)

        def fetch(connection):
            _canonical(conversation, request)
            _permit(authorize_read)
            if _plan_learning_suppressed(connection):
                raise CheckpointRejected("plan category is suppressed")
            row = connection.execute(
                "SELECT source_turn_id,source_at,state_json "
                "FROM conversation_topic_checkpoint WHERE topic_key=?",
                (key,),
            ).fetchone()
            _permit(authorize_read)
            _canonical(conversation, request)
            if row is None:
                return None
            record = json.loads(row[2])
            if not isinstance(record, dict):
                raise CheckpointRejected("checkpoint payload malformed")
            record["_checkpoint_meta"] = {
                "source_turn_id": row[0],
                "source_at": row[1],
            }
            return record

        return await self._reader.run(fetch)

    async def resolve_named_topic(
        self,
        conversation: ConversationSession,
        request: ConversationTurn,
        *,
        topic_hint: str,
        authorize_read: Callable[[], bool],
    ) -> str | None:
        """Return a *unique* explicitly mentioned topic; never list other topics.

        The hint must occur in the canonical owner's current question. All
        candidate titles are evaluated within the encrypted reader worker only
        after consent. Ambiguous matches fail closed rather than guessing.
        """
        _canonical(conversation, request)
        hint_tokens = set(re.findall(r"\w+", _key(topic_hint)))
        if not any(
            len(word) >= 4 and word not in _GENERIC_TOPIC_WORDS for word in hint_tokens
        ):
            raise CheckpointRejected("topic hint is not distinctive")
        request_tokens = set(
            re.findall(r"\w+", unicodedata.normalize("NFKC", request.text).casefold())
        )
        if not hint_tokens.issubset(request_tokens):
            raise CheckpointRejected("topic hint is absent from current question")
        _permit(authorize_read)

        def resolve(connection):
            _canonical(conversation, request)
            _permit(authorize_read)
            if _plan_learning_suppressed(connection):
                raise CheckpointRejected("plan category is suppressed")
            rows = connection.execute(
                "SELECT topic_key,source_turn_id,source_at "
                "FROM conversation_topic_checkpoint ORDER BY topic_key LIMIT 33"
            ).fetchall()
            if len(rows) > 32:
                raise CheckpointRejected("too many stored topics for safe matching")
            matches = [
                key
                for key, _source_turn_id, _source_at in rows
                if hint_tokens.issubset(set(re.findall(r"\w+", key)))
            ]
            _permit(authorize_read)
            _canonical(conversation, request)
            if len(matches) > 1:
                raise CheckpointRejected("ambiguous named topic")
            return matches[0] if matches else None

        return await self._reader.run(resolve)

    async def current_fingerprint(self, title: str) -> str | None:
        """Internal revision check for protected-response retirement.

        This returns only a revision digest, not facts. It does not grant model
        release or replace an authorized named read.
        """
        key = _key(title)

        def query(connection):
            if _plan_learning_suppressed(connection):
                return None
            row = connection.execute(
                "SELECT source_turn_id,source_at,state_json "
                "FROM conversation_topic_checkpoint WHERE topic_key=?",
                (key,),
            ).fetchone()
            if row is None:
                return None
            material = json.dumps(
                list(row), ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            return hashlib.sha256(material).hexdigest()

        return await self._reader.run(query)

    async def read_named_snapshot(
        self,
        conversation: ConversationSession,
        request: ConversationTurn,
        *,
        title: str,
        authorize_read: Callable[[], bool],
    ) -> TopicSnapshot | None:
        """Restore provenance-aware transient state after an authorized topic read.

        Stored topic-level source metadata is retained; this does not claim each
        field came from the current question or recover lost per-field citations.
        """
        record = await self.read_named(
            conversation, request, title=title, authorize_read=authorize_read
        )
        if record is None:
            return None
        expected = {"title", "goal", "constraints", "steps", "_checkpoint_meta"}
        if not isinstance(record, dict) or set(record) != expected:
            raise CheckpointRejected("checkpoint payload malformed")
        if not isinstance(record["title"], str) or (
            _key(record["title"]) != _key(title)
        ):
            raise CheckpointRejected("checkpoint topic mismatch")
        meta = record["_checkpoint_meta"]
        if not isinstance(meta, dict) or set(meta) != {"source_turn_id", "source_at"}:
            raise CheckpointRejected("checkpoint source metadata missing")
        source_id, raw_time = meta["source_turn_id"], meta["source_at"]
        if not isinstance(source_id, str) or not source_id:
            raise CheckpointRejected("checkpoint source missing")
        try:
            source_time = datetime.fromisoformat(raw_time)
        except (TypeError, ValueError) as exc:
            raise CheckpointRejected("checkpoint time malformed") from exc
        if source_time.tzinfo is None or source_time.utcoffset() is None:
            raise CheckpointRejected("checkpoint time not UTC")
        source_time = source_time.astimezone(UTC)

        def grounded(value: str) -> GroundedStateValue:
            if not isinstance(value, str) or not 1 <= len(value) <= 500:
                raise CheckpointRejected("checkpoint field malformed")
            return GroundedStateValue(
                value=value,
                evidence="",
                source_turn_id=source_id,
                accepted_at=source_time,
                sensitivity=Sensitivity.STANDARD,
                evidence_strength=EvidenceStrength.INTERPRETED,
            )

        goal_raw = record["goal"]
        goal = grounded(goal_raw) if goal_raw is not None else None
        raw_constraints = record["constraints"]
        raw_steps = record["steps"]
        if (
            not isinstance(raw_constraints, dict)
            or not isinstance(raw_steps, dict)
            or len(raw_constraints) > 20
            or len(raw_steps) > 20
        ):
            raise CheckpointRejected("checkpoint field shape malformed")
        constraints = []
        for key, value in sorted(raw_constraints.items()):
            constraints.append((_key(key), grounded(value)))
        steps = []
        for key, field in sorted(raw_steps.items()):
            if (
                not isinstance(field, dict)
                or set(field) != {"value", "completed"}
                or type(field["completed"]) is not bool
            ):
                raise CheckpointRejected("checkpoint step malformed")
            step = grounded(field["value"])
            steps.append((_key(key), replace(step, completed=field["completed"])))
        _canonical(conversation, request)
        _permit(authorize_read)
        return TopicSnapshot(
            title=record["title"],
            goal=goal,
            constraints=tuple(constraints),
            steps=tuple(steps),
        )

    async def forget(
        self,
        conversation: ConversationSession,
        turn: ConversationTurn,
        *,
        title: str,
        authorize_forget: Callable[[], bool],
    ) -> bool:
        _canonical(conversation, turn, require_latest=False)
        key = _key(title)
        if (
            not _explicit_topic(turn.text, title)
            or _FORGET_CUE.search(turn.text) is None
            or _FORGET_NEGATION.search(turn.text)
        ):
            raise CheckpointRejected("explicit positive topic forget required")
        _permit(authorize_forget)
        timestamp = _time(turn)

        def erase(connection) -> bool:
            _canonical(conversation, turn, require_latest=False)
            _permit(authorize_forget)
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT source_at FROM conversation_topic_checkpoint "
                    "WHERE topic_key=?",
                    (key,),
                ).fetchone()
                if row is not None and row[0] > timestamp:
                    connection.rollback()
                    return False
                connection.execute(
                    "DELETE FROM conversation_topic_checkpoint WHERE topic_key=?",
                    (key,),
                )
                connection.execute(
                    "INSERT INTO conversation_topic_tombstone "
                    "(topic_key,forgotten_at,source_turn_id) VALUES (?,?,?) "
                    "ON CONFLICT(topic_key) DO UPDATE SET "
                    "forgotten_at=excluded.forgotten_at, "
                    "source_turn_id=excluded.source_turn_id "
                    "WHERE excluded.forgotten_at > forgotten_at",
                    (key, timestamp, turn.turn_id),
                )
                _canonical(conversation, turn, require_latest=False)
                _permit(authorize_forget)
                connection.commit()
                return row is not None
            except BaseException:
                connection.rollback()
                raise

        return await self._writer.run(erase)

    async def purge_for_suppression(
        self,
        conversation: ConversationSession,
        turn: ConversationTurn,
        *,
        authorize_suppression: Callable[[], bool],
    ) -> None:
        """Tombstone all older plans when owner disables plan learning."""
        _canonical(conversation, turn)
        _permit(authorize_suppression)
        timestamp = _time(turn)

        def purge(connection) -> None:
            _canonical(conversation, turn)
            _permit(authorize_suppression)
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute("DELETE FROM conversation_topic_checkpoint")
                connection.execute(
                    "INSERT INTO conversation_topic_tombstone "
                    "(topic_key,forgotten_at,source_turn_id) VALUES ('*',?,?) "
                    "ON CONFLICT(topic_key) DO UPDATE SET "
                    "forgotten_at=excluded.forgotten_at, "
                    "source_turn_id=excluded.source_turn_id "
                    "WHERE excluded.forgotten_at > forgotten_at",
                    (timestamp, turn.turn_id),
                )
                _canonical(conversation, turn)
                _permit(authorize_suppression)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

        await self._writer.run(purge)
