from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from jarvis.memory.assertions import SemanticAssertionRecord
from jarvis.memory.release_guard import (
    GeminiMemoryReleaseGuard,
    MemoryReleaseAnswerType,
    MemoryReleaseGuardError,
    MemoryReleaseJudgement,
    OpenAIMemoryReleaseGuard,
    memory_release_guard_input,
)
from jarvis.memory.types import (
    AssertionState,
    FreshnessClass,
    Sensitivity,
    ValueType,
    VerificationState,
)


def _record(
    *, sensitivity: Sensitivity = Sensitivity.STANDARD
) -> SemanticAssertionRecord:
    now = datetime.now(UTC)
    return SemanticAssertionRecord(
        assertion_id="a1",
        subject_scope="owner",
        subject="self",
        predicate="current car",
        value_type=ValueType.TEXT,
        value="Jimny",
        normalized_text="current car Jimny",
        source_id="s1",
        valid_from=now,
        valid_to=None,
        system_from=now,
        system_to=None,
        last_verified_at=None,
        state=AssertionState.ACTIVE,
        supersedes_id=None,
        verification_state=VerificationState.UNVERIFIED,
        confidence=None,
        freshness_class=FreshnessClass.CHANGEABLE,
        sensitivity=sensitivity,
        created_at=now,
        updated_at=now,
    )


def test_release_judgement_only_allows_direct_current_shapes() -> None:
    assert MemoryReleaseJudgement(
        answer_type=MemoryReleaseAnswerType.CURRENT_VALUE,
        directly_supported=True,
    ).allows_release
    assert MemoryReleaseJudgement(
        answer_type=MemoryReleaseAnswerType.CURRENT_VALUE_COMPARISON,
        directly_supported=True,
    ).allows_release
    assert not MemoryReleaseJudgement(
        answer_type=MemoryReleaseAnswerType.REASON_EXPLANATION,
        directly_supported=True,
    ).allows_release
    assert not MemoryReleaseJudgement(
        answer_type=MemoryReleaseAnswerType.CURRENT_VALUE,
        directly_supported=False,
    ).allows_release


def test_guard_input_contains_only_query_and_bounded_fact_fields() -> None:
    payload = json.loads(
        memory_release_guard_input(text="What car do I have?", evidence=_record())
    )
    assert payload["user_query"] == "What car do I have?"
    fact = payload["canonical_current_fact"]
    assert fact["predicate"] == "current car"
    assert fact["value"] == "Jimny"
    assert "source_id" not in fact
    assert "assertion_id" not in fact


class _FakeResponses:
    def __init__(self, judgement):
        self.judgement = judgement
        self.kwargs = None

    async def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_parsed=self.judgement)


@pytest.mark.asyncio
async def test_openai_guard_uses_structured_parse_and_store_false() -> None:
    responses = _FakeResponses(
        MemoryReleaseJudgement(
            answer_type=MemoryReleaseAnswerType.CURRENT_VALUE,
            directly_supported=True,
        )
    )
    guard = OpenAIMemoryReleaseGuard(
        client=SimpleNamespace(responses=responses),
        model="gpt-test",
    )
    result = await guard.evaluate(text="What car do I have?", evidence=_record())
    assert result.allows_release
    assert responses.kwargs["text_format"] is MemoryReleaseJudgement
    assert responses.kwargs["store"] is False


class _FakeInteractions:
    def __init__(self, output_text: str):
        self.output_text = output_text
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_text=self.output_text)


@pytest.mark.asyncio
async def test_gemini_guard_uses_json_schema_and_store_false() -> None:
    interactions = _FakeInteractions(
        MemoryReleaseJudgement(
            answer_type=MemoryReleaseAnswerType.CURRENT_VALUE_COMPARISON,
            directly_supported=True,
        ).model_dump_json()
    )
    client = SimpleNamespace(aio=SimpleNamespace(interactions=interactions))
    guard = GeminiMemoryReleaseGuard(client=client, model="gemini-test")
    result = await guard.evaluate(text="Is my car Jimny?", evidence=_record())
    assert result.allows_release
    assert interactions.kwargs["response_format"]["mime_type"] == "application/json"
    assert interactions.kwargs["store"] is False


@pytest.mark.asyncio
async def test_gemini_guard_rejects_invalid_structured_output() -> None:
    interactions = _FakeInteractions(
        '{"answer_type":"not-a-role","directly_supported":true}'
    )
    client = SimpleNamespace(aio=SimpleNamespace(interactions=interactions))
    guard = GeminiMemoryReleaseGuard(client=client, model="gemini-test")
    with pytest.raises(MemoryReleaseGuardError):
        await guard.evaluate(text="What car do I have?", evidence=_record())
