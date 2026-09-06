from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from jarvis.memory.query_interpreters import (
    GeminiMemoryQueryInterpreter,
    MemoryQueryInterpretationError,
    OpenAIMemoryQueryInterpreter,
    build_memory_query_interpreter,
    memory_query_interpreter_input,
)
from jarvis.memory.query_plan import (
    MemoryFacetCatalog,
    MemoryFacetKey,
    MemoryQueryIntent,
    MemoryQueryProposal,
    MemoryTemporalScope,
)


def _catalog() -> MemoryFacetCatalog:
    return MemoryFacetCatalog(
        (
            MemoryFacetKey("profile", "Aquila", "archive_destination"),
            MemoryFacetKey("profile", "Aquila", "signin_method"),
        )
    )


def _proposal() -> MemoryQueryProposal:
    return MemoryQueryProposal(
        intent=MemoryQueryIntent.EXACT_FACT,
        subject_scope="profile",
        subject="Aquila",
        predicate="archive_destination",
        subject_reference="Aquila",
        requested_relation="archive destination",
        temporal_scope=MemoryTemporalScope.CURRENT,
    )


class FakeOpenAIResponses:
    def __init__(self, output_parsed: Any) -> None:
        self.output_parsed = output_parsed
        self.calls: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.output_parsed)


class FakeOpenAIClient:
    def __init__(self, output_parsed: Any) -> None:
        self.responses = FakeOpenAIResponses(output_parsed)


class FakeGeminiInteractions:
    def __init__(self, output_text: Any) -> None:
        self.output_text = output_text
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.output_text)


class FakeGeminiClient:
    def __init__(self, output_text: Any) -> None:
        interactions = FakeGeminiInteractions(output_text)
        self.aio = SimpleNamespace(interactions=interactions)
        self.interactions = interactions


def test_interpreter_input_contains_only_user_query_and_facet_keys() -> None:
    payload = json.loads(
        memory_query_interpreter_input(
            text="Aquila archive destination?",
            catalog=_catalog(),
        )
    )

    assert payload == {
        "user_query": "Aquila archive destination?",
        "eligible_facets": [
            {
                "subject_scope": "profile",
                "subject": "Aquila",
                "predicate": "archive_destination",
            },
            {
                "subject_scope": "profile",
                "subject": "Aquila",
                "predicate": "signin_method",
            },
        ],
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "value" not in serialized.casefold()
    assert "normalized_text" not in serialized
    assert "source_id" not in serialized


@pytest.mark.asyncio
async def test_openai_interpreter_uses_native_schema_without_storage() -> None:
    proposal = _proposal()
    client = FakeOpenAIClient(proposal)
    interpreter = OpenAIMemoryQueryInterpreter(client=client, model="gpt-test")

    result = await interpreter.interpret(
        text="Aquila archive destination?",
        catalog=_catalog(),
    )

    assert result is proposal
    assert interpreter.provider_name == "openai"
    assert interpreter.model_name == "gpt-test"
    assert len(client.responses.calls) == 1
    call = client.responses.calls[0]
    assert call["model"] == "gpt-test"
    assert call["store"] is False
    assert call["text_format"] is MemoryQueryProposal
    assert len(call["input"]) == 2
    payload = json.loads(call["input"][-1]["content"])
    assert payload["user_query"] == "Aquila archive destination?"
    assert set(payload) == {"user_query", "eligible_facets"}


@pytest.mark.asyncio
async def test_openai_interpreter_fails_closed_without_validated_proposal() -> None:
    client = FakeOpenAIClient(None)
    interpreter = OpenAIMemoryQueryInterpreter(client=client, model="gpt-test")

    with pytest.raises(MemoryQueryInterpretationError, match="no validated"):
        await interpreter.interpret(
            text="Aquila archive destination?",
            catalog=_catalog(),
        )


@pytest.mark.asyncio
async def test_gemini_interpreter_uses_json_schema_without_storage() -> None:
    proposal = _proposal()
    client = FakeGeminiClient(proposal.model_dump_json())
    interpreter = GeminiMemoryQueryInterpreter(client=client, model="gemini-test")

    result = await interpreter.interpret(
        text="Aquila archive destination?",
        catalog=_catalog(),
    )

    assert result == proposal
    assert interpreter.provider_name == "gemini"
    assert interpreter.model_name == "gemini-test"
    assert len(client.interactions.calls) == 1
    call = client.interactions.calls[0]
    assert call["model"] == "gemini-test"
    assert call["store"] is False
    assert call["response_format"] == {
        "type": "text",
        "mime_type": "application/json",
        "schema": MemoryQueryProposal.model_json_schema(),
    }
    payload = json.loads(call["input"])
    assert payload["user_query"] == "Aquila archive destination?"
    assert set(payload) == {"user_query", "eligible_facets"}
    assert "decide whether any memory may be released" in call["system_instruction"]


@pytest.mark.asyncio
async def test_schema_valid_but_incomplete_exact_proposal_is_returned_for_policy_abstain() -> None:
    incomplete = MemoryQueryProposal(intent=MemoryQueryIntent.EXACT_FACT)
    client = FakeGeminiClient(incomplete.model_dump_json())
    interpreter = GeminiMemoryQueryInterpreter(client=client, model="gemini-test")

    result = await interpreter.interpret(
        text="Aquila archive destination?",
        catalog=_catalog(),
    )

    assert result == incomplete
    assert result.subject is None
    assert result.predicate is None


@pytest.mark.asyncio
@pytest.mark.parametrize("output", (None, "", "not-json", '{"intent":"not-an-intent"}'))
async def test_gemini_interpreter_fails_closed_on_missing_or_invalid_output(
    output: Any,
) -> None:
    client = FakeGeminiClient(output)
    interpreter = GeminiMemoryQueryInterpreter(client=client, model="gemini-test")

    with pytest.raises(MemoryQueryInterpretationError):
        await interpreter.interpret(
            text="Aquila archive destination?",
            catalog=_catalog(),
        )


def test_query_interpreters_reject_missing_client_capabilities() -> None:
    with pytest.raises(TypeError, match="responses.parse"):
        OpenAIMemoryQueryInterpreter(client=object(), model="gpt-test")
    with pytest.raises(TypeError, match="aio.interactions.create"):
        GeminiMemoryQueryInterpreter(client=object(), model="gemini-test")


def test_query_interpreter_factory_requires_selected_provider_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        build_memory_query_interpreter(provider="openai", model="gpt-test")
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        build_memory_query_interpreter(provider="gemini", model="gemini-test")


def test_query_interpreter_factory_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        build_memory_query_interpreter(provider="unknown", model="model-x")
