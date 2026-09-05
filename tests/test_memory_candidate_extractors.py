from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from jarvis.memory.candidates import (
    MemoryCandidateType,
    MemoryExtractionIntent,
    MemoryExtractionProposal,
    MemoryExtractionSensitivity,
)
from jarvis.memory.extractors import (
    GeminiMemoryCandidateExtractor,
    MemoryCandidateExtractionError,
    OpenAIMemoryCandidateExtractor,
)


def _proposal() -> MemoryExtractionProposal:
    return MemoryExtractionProposal(
        intent=MemoryExtractionIntent.CANDIDATE,
        candidate_type=MemoryCandidateType.FACT,
        durable_candidate=True,
        subject="owner",
        predicate="home_city",
        value="Indore",
        temporal_hint=None,
        sensitivity=MemoryExtractionSensitivity.NORMAL,
        confidence=0.9,
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


@pytest.mark.asyncio
async def test_openai_adapter_uses_native_pydantic_parse_without_storage() -> None:
    proposal = _proposal()
    client = FakeOpenAIClient(proposal)
    extractor = OpenAIMemoryCandidateExtractor(client=client, model="gpt-test")

    result = await extractor.extract(text="My home city is Indore.")

    assert result is proposal
    assert extractor.provider_name == "openai"
    assert extractor.model_name == "gpt-test"
    assert len(client.responses.calls) == 1
    call = client.responses.calls[0]
    assert call["model"] == "gpt-test"
    assert call["store"] is False
    assert call["text_format"] is MemoryExtractionProposal
    assert call["input"][-1] == {
        "role": "user",
        "content": "My home city is Indore.",
    }
    assert len(call["input"]) == 2


@pytest.mark.asyncio
async def test_openai_adapter_fails_closed_without_validated_proposal() -> None:
    client = FakeOpenAIClient(None)
    extractor = OpenAIMemoryCandidateExtractor(client=client, model="gpt-test")

    with pytest.raises(MemoryCandidateExtractionError, match="no validated"):
        await extractor.extract(text="My home city is Indore.")


@pytest.mark.asyncio
async def test_gemini_adapter_uses_interactions_json_schema_without_storage() -> None:
    proposal = _proposal()
    client = FakeGeminiClient(proposal.model_dump_json())
    extractor = GeminiMemoryCandidateExtractor(client=client, model="gemini-test")

    result = await extractor.extract(text="My home city is Indore.")

    assert result == proposal
    assert extractor.provider_name == "gemini"
    assert extractor.model_name == "gemini-test"
    assert len(client.interactions.calls) == 1
    call = client.interactions.calls[0]
    assert call["model"] == "gemini-test"
    assert call["input"] == "My home city is Indore."
    assert call["store"] is False
    assert call["response_format"] == {
        "type": "text",
        "mime_type": "application/json",
        "schema": MemoryExtractionProposal.model_json_schema(),
    }
    assert "canonical truth" in call["system_instruction"]


@pytest.mark.asyncio
async def test_gemini_adapter_fails_closed_on_invalid_structured_output() -> None:
    client = FakeGeminiClient('{"intent":"candidate"}')
    extractor = GeminiMemoryCandidateExtractor(client=client, model="gemini-test")

    with pytest.raises(MemoryCandidateExtractionError, match="invalid"):
        await extractor.extract(text="My home city is Indore.")


def test_provider_adapters_reject_missing_client_capabilities() -> None:
    with pytest.raises(TypeError, match="responses.parse"):
        OpenAIMemoryCandidateExtractor(client=object(), model="gpt-test")
    with pytest.raises(TypeError, match="aio.interactions.create"):
        GeminiMemoryCandidateExtractor(client=object(), model="gemini-test")
