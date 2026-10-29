"""SQLCipher-backed topic checkpoints; no independent database or read authority.

Callers must supply a current canonical owner statement AND a trusted existing
capability/Hello permit validation callback. Nothing here grants that permit.
All operations run on the canonical SerialConnectionWorker connections.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Callable
from datetime import UTC
from typing import Any

from jarvis.conversation import (
    ConversationRole,
    ConversationSession,
    ConversationStatus,
    ConversationTurn,
)

from .conversation_semantics import (
    TopicSnapshot,
    _FORGET_CUE,
    _FORGET_NEGATION,
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


def _canonical(conversation: ConversationSession, turn: ConversationTurn) -> None:
    if (
        not isinstance(conversation, ConversationSession)
        or conversation.status is not ConversationStatus.ACTIVE
        or not isinstance(turn, ConversationTurn)
        or turn.role is not ConversationRole.USER
        or not conversation.turns
        or conversation.turns[-1] is not turn
    ):
        raise CheckpointRejected("latest canonical owner USER turn required")


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


def _snapshot_payload(snapshot: TopicSnapshot) -> str:
    if not isinstance(snapshot, TopicSnapshot):
        raise TypeError("snapshot must be TopicSnapshot")
    _key(snapshot.title)

    def checked_value(value) -> str:
        if value.sensitivity in {
            Sensitivity.LOCAL_ONLY,
            Sensitivity.SECRET_PROHIBITED,
        }:
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
    ) -> bool:
        _canonical(conversation, turn)
        _permit(authorize_write)
        _admit_snapshot(admit_snapshot, snapshot, turn)
        state_json = _snapshot_payload(snapshot)
        key, source_at = _key(snapshot.title), _time(turn)

        def write(connection) -> bool:
            _canonical(conversation, turn)
            _permit(authorize_write)
            _admit_snapshot(admit_snapshot, snapshot, turn)
            connection.execute("BEGIN IMMEDIATE")
            try:
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
                _canonical(conversation, turn)
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
            row = connection.execute(
                "SELECT state_json FROM conversation_topic_checkpoint "
                "WHERE topic_key=?",
                (key,),
            ).fetchone()
            _permit(authorize_read)
            _canonical(conversation, request)
            return json.loads(row[0]) if row else None

        return await self._reader.run(fetch)

    async def forget(
        self,
        conversation: ConversationSession,
        turn: ConversationTurn,
        *,
        title: str,
        authorize_forget: Callable[[], bool],
    ) -> bool:
        _canonical(conversation, turn)
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
            _canonical(conversation, turn)
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
                _canonical(conversation, turn)
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
                connection.execute(
                    "DELETE FROM conversation_topic_checkpoint WHERE source_at<=?",
                    (timestamp,),
                )
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
