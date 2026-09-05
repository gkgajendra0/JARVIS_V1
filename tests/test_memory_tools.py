from __future__ import annotations

import itertools
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.explicit import (
    ExplicitMemoryAuthorizationError,
    MemorySecretRejectedError,
)
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.query import CanonicalMemoryReader
from jarvis.memory.service import MemoryService
from jarvis.memory.worker import SerialConnectionWorker
from jarvis.voice.memory_tools import MemoryAgentTools

BASE = datetime(2026, 9, 5, 10, 30, tzinfo=UTC)


def _ids(prefix: str):
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter)}"


def _service(path: Path) -> tuple[MemoryService, SerialConnectionWorker, SerialConnectionWorker]:
    def factory() -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        MemoryMigrationRunner(clock=lambda: BASE).apply(connection)
        return connection

    writer = SerialConnectionWorker(factory, thread_name="memory-tools-writer")
    reader = SerialConnectionWorker(factory, thread_name="memory-tools-reader")
    lifecycle = MemoryLifecycleService(
        writer,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    return MemoryService(lifecycle, CanonicalMemoryReader(reader)), writer, reader


def _conversation(text: str) -> ConversationSession:
    conversation = ConversationSession(session_id="session-tools")
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, text)
    return conversation


@pytest.mark.asyncio
async def test_explicit_voice_tools_round_trip_only_after_canonical_user_commands(
    tmp_path: Path,
) -> None:
    service, writer, reader = _service(tmp_path / "tools.db")
    conversation = _conversation("Remember that my home city is Sagar.")
    tools = MemoryAgentTools(service, conversation)
    try:
        assert {tool.id for tool in tools.tools} == {
            "remember_memory",
            "correct_memory",
            "forget_memory",
            "inspect_memory",
        }

        remembered = await tools.remember(predicate="home city", value="Sagar")
        assert remembered["ok"] is True
        assert remembered["predicate"] == "home_city"
        assert "value" not in remembered

        conversation.accept_turn(
            ConversationRole.USER,
            "What do you remember about my home city?",
        )
        inspected = await tools.inspect(predicate="home city")
        assert inspected["ok"] is True
        assert inspected["value"] == "Sagar"

        conversation.accept_turn(
            ConversationRole.USER,
            "Correct my home city memory to Indore.",
        )
        corrected = await tools.correct(predicate="home city", value="Indore")
        assert corrected["ok"] is True
        conversation.accept_turn(
            ConversationRole.USER,
            "What do you remember about my home city?",
        )
        assert (await tools.inspect(predicate="home city"))["value"] == "Indore"

        conversation.accept_turn(ConversationRole.USER, "Forget my home city memory.")
        forgotten = await tools.forget(predicate="home city")
        assert forgotten == {
            "ok": True,
            "operation": "forget",
            "predicate": "home_city",
        }
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_voice_tool_mutation_refuses_implicit_or_assistant_only_authority(
    tmp_path: Path,
) -> None:
    service, writer, reader = _service(tmp_path / "authority.db")
    conversation = _conversation("My home city is Sagar.")
    tools = MemoryAgentTools(service, conversation)
    try:
        conversation.accept_turn(
            ConversationRole.ASSISTANT,
            "I think that sounds useful to remember.",
        )
        with pytest.raises(ExplicitMemoryAuthorizationError):
            await tools.remember(predicate="home city", value="Sagar")
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_voice_tool_rejects_credentials_before_durable_write(
    tmp_path: Path,
) -> None:
    service, writer, reader = _service(tmp_path / "secret.db")
    conversation = _conversation(
        "Remember my API key sk-abcdefghijklmnopqrstuvwxyz1234567890."
    )
    tools = MemoryAgentTools(service, conversation)
    try:
        with pytest.raises(MemorySecretRejectedError):
            await tools.remember(
                predicate="api key",
                value="sk-abcdefghijklmnopqrstuvwxyz1234567890",
            )
        count = await reader.run(
            lambda connection: connection.execute(
                "SELECT count(*) FROM semantic_assertion"
            ).fetchone()[0]
        )
        assert count == 0
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_local_only_memory_is_not_released_by_provider_facing_inspect(
    tmp_path: Path,
) -> None:
    service, writer, reader = _service(tmp_path / "local-only.db")
    conversation = _conversation("Remember that my local note is device-only.")
    tools = MemoryAgentTools(service, conversation)
    try:
        await tools.remember(
            predicate="local note",
            value="device-only",
            sensitivity="local_only",
        )
        conversation.accept_turn(
            ConversationRole.USER,
            "What do you remember about my local note?",
        )
        result = await tools.inspect(predicate="local note")
        assert result["ok"] is False
        assert result["predicate"] == "local_note"
        assert "value" not in result
        assert "local_only" in str(result["reason"])
    finally:
        await reader.close()
        await writer.close()
