from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from jarvis.memory.query_interpreters import (
    GeminiMemoryQueryInterpreter,
    MemoryQueryInterpretationError,
    MemoryQuerySelection,
    OpenAIMemoryQueryInterpreter,
    build_memory_query_interpreter,
    materialize_memory_query_selection,
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


def _selection(*, facet_index: int = 0) -> MemoryQuerySelection:
    return MemoryQuerySelection(
        intent=MemoryQueryIntent.EXACT_FACT,
        facet_index=facet_index,
        subject_reference="Aquila",
        requested_relation="archive destination",
        temporal_scope=MemoryTemporalScope.CURRENT,
        as_of_text=None,
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


def test_interpreter_input_numbers_facet_keys_without_values() -> None:
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
                "facet_index": 0,
                "subject_scope": "profile",
                "subject": "Aquila",
                "predicate": "archive_destination",
            },
            {
                "facet_index": 1,
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


def test_materialize_selection_reconstructs_canonical_facet_from_index() -> None:
    proposal = materialize_memory_query_selection(_selection(), catalog=_catalog())

    assert proposal == _proposal()


def test_materialize_exact_selection_with_no_facet_stays_incomplete_for_abstain() -> (
    None
):
    proposal = materialize_memory_query_selection(
        _selection(facet_index=-1),
        catalog=_catalog(),
    )

    assert proposal.intent is MemoryQueryIntent.EXACT_FACT
    assert proposal.subject_scope is None
    assert proposal.subject is None
    assert proposal.predicate is None
    assert proposal.subject_reference == "Aquila"
    assert proposal.requested_relation == "archive destination"


def test_materialize_selection_rejects_out_of_range_facet_index() -> None:
    with pytest.raises(MemoryQueryInterpretationError, match="outside"):
        materialize_memory_query_selection(
            _selection(facet_index=99),
            catalog=_catalog(),
        )


def test_selection_schema_requires_explicit_facet_index_and_nullable_fields() -> None:
    schema = MemoryQuerySelection.model_json_schema()

    assert {
        "intent",
        "facet_index",
        "subject_reference",
        "requested_relation",
        "temporal_scope",
        "as_of_text",
    }.issubset(set(schema["required"]))
    assert schema["properties"]["facet_index"]["minimum"] == -1


@pytest.mark.asyncio
async def test_openai_interpreter_uses_selection_schema_without_storage() -> None:
    selection = _selection()
    client = FakeOpenAIClient(selection)
    interpreter = OpenAIMemoryQueryInterpreter(client=client, model="gpt-test")

    result = await interpreter.interpret(
        text="Aquila archive destination?",
        catalog=_catalog(),
    )

    assert result == _proposal()
    assert interpreter.provider_name == "openai"
    assert interpreter.model_name == "gpt-test"
    assert len(client.responses.calls) == 1
    call = client.responses.calls[0]
    assert call["model"] == "gpt-test"
    assert call["store"] is False
    assert call["text_format"] is MemoryQuerySelection
    assert len(call["input"]) == 2
    payload = json.loads(call["input"][-1]["content"])
    assert payload["user_query"] == "Aquila archive destination?"
    assert payload["eligible_facets"][0]["facet_index"] == 0


@pytest.mark.asyncio
async def test_openai_interpreter_fails_closed_without_validated_selection() -> None:
    client = FakeOpenAIClient(None)
    interpreter = OpenAIMemoryQueryInterpreter(client=client, model="gpt-test")

    with pytest.raises(MemoryQueryInterpretationError, match="no validated"):
        await interpreter.interpret(
            text="Aquila archive destination?",
            catalog=_catalog(),
        )


@pytest.mark.asyncio
async def test_gemini_interpreter_uses_selection_schema_without_storage() -> None:
    selection = _selection()
    client = FakeGeminiClient(selection.model_dump_json())
    interpreter = GeminiMemoryQueryInterpreter(client=client, model="gemini-test")

    result = await interpreter.interpret(
        text="Aquila archive destination?",
        catalog=_catalog(),
    )

    assert result == _proposal()
    assert interpreter.provider_name == "gemini"
    assert interpreter.model_name == "gemini-test"
    assert len(client.interactions.calls) == 1
    call = client.interactions.calls[0]
    assert call["model"] == "gemini-test"
    assert call["store"] is False
    assert call["response_format"] == {
        "type": "text",
        "mime_type": "application/json",
        "schema": MemoryQuerySelection.model_json_schema(),
    }
    payload = json.loads(call["input"])
    assert payload["user_query"] == "Aquila archive destination?"
    assert payload["eligible_facets"][0]["facet_index"] == 0
    assert "decide whether any memory may be released" in call["system_instruction"]


@pytest.mark.asyncio
async def test_gemini_exact_selection_minus_one_returns_policy_abstain_shape() -> None:
    selection = _selection(facet_index=-1)
    client = FakeGeminiClient(selection.model_dump_json())
    interpreter = GeminiMemoryQueryInterpreter(client=client, model="gemini-test")

    result = await interpreter.interpret(
        text="Aquila archive destination?",
        catalog=_catalog(),
    )

    assert result.intent is MemoryQueryIntent.EXACT_FACT
    assert result.subject_scope is None
    assert result.subject is None
    assert result.predicate is None


@pytest.mark.asyncio
@pytest.mark.parametrize("output", (None, "", "not-json", '{"intent":"exact_fact"}'))
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
