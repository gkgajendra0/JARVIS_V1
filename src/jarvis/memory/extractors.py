"""Provider-native structured-output adapters for memory candidate extraction."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from jarvis.ai_provider import normalize_ai_provider, require_provider_api_key

from .candidates import MemoryCandidateExtractor, MemoryExtractionProposal

MEMORY_EXTRACTION_SYSTEM_PROMPT = """You extract one structured JARVIS memory proposal from exactly one accepted USER utterance.

You only propose evidence. You never establish canonical truth, mutate memory, or decide authority.

Pipeline facts you MUST account for:
- Explicit Phase-4.3 remember/inspect/correct/forget commands are handled before this extractor.
- Non-USER sources are blocked before this extractor.
- Locally recognizable credentials/secrets are blocked before this extractor.

Intent meanings for utterances that reach this Phase-4.4 extractor:
- candidate: an ordinary direct-user stable fact, durable preference/rule, meaningful decision, or incident that may be useful later. Use candidate for implicit durable information; do NOT use remember merely because the information is durable.
- historical_change: a real-world state changed from an earlier state that was previously true.
- correction: the user says an earlier statement/fact was wrong and supplies the corrected value.
- retraction: the user withdraws or denies an earlier claim without merely describing a normal real-world change.
- transient: current-session instructions, temporary state/mood, or other short-lived context.
- sensitive_reject_or_secret_store: secret/credential material that escaped the local prefilter; never durable.
- none: no useful memory proposal.
- remember, forget, and untrusted are pipeline-owned intents and should not be emitted for ordinary direct-user Phase-4.4 inputs that reach this extractor.

Classify conservatively:
- Stable direct facts, durable preferences/rules, meaningful decisions/incidents may be durable candidates.
- Current-session instructions, temporary state/mood, weak likes, uncertain future plans, speculation, quoted/untrusted claims, or test/meta statements are not durable candidates.
- Distinguish a real-world change from a correction of an earlier false statement and from a retraction.
- Credential/authentication secrets are SECRET and never durable candidates.
- Never invent facts not supported by the utterance.

Example: "I live in Sagar." is intent=candidate, candidate_type=fact, durable_candidate=true.

Return only the requested schema. JARVIS supplies provenance, authority, session IDs, turn IDs, and admission policy separately.
"""


class MemoryCandidateExtractionError(RuntimeError):
    """Raised when a provider cannot return a validated extraction proposal."""


def _require_non_empty(value: str, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


class OpenAIMemoryCandidateExtractor:
    """OpenAI Responses API adapter using native Pydantic structured output."""

    provider_name = "openai"

    def __init__(self, *, client: Any, model: str) -> None:
        responses = getattr(client, "responses", None)
        if responses is None or not callable(getattr(responses, "parse", None)):
            raise TypeError("client must expose responses.parse")
        self._client = client
        self._model = _require_non_empty(model, name="model")

    @property
    def model_name(self) -> str:
        return self._model

    async def extract(self, *, text: str) -> MemoryExtractionProposal:
        source_text = _require_non_empty(text, name="text")
        response = await self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": MEMORY_EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": source_text},
            ],
            text_format=MemoryExtractionProposal,
            store=False,
        )
        proposal = getattr(response, "output_parsed", None)
        if not isinstance(proposal, MemoryExtractionProposal):
            raise MemoryCandidateExtractionError(
                "OpenAI returned no validated memory extraction proposal"
            )
        return proposal


class GeminiMemoryCandidateExtractor:
    """Gemini Interactions API adapter using JSON Schema structured output."""

    provider_name = "gemini"

    def __init__(self, *, client: Any, model: str) -> None:
        aio = getattr(client, "aio", None)
        interactions = getattr(aio, "interactions", None)
        if interactions is None or not callable(getattr(interactions, "create", None)):
            raise TypeError("client must expose aio.interactions.create")
        self._client = client
        self._model = _require_non_empty(model, name="model")

    @property
    def model_name(self) -> str:
        return self._model

    async def extract(self, *, text: str) -> MemoryExtractionProposal:
        source_text = _require_non_empty(text, name="text")
        response = await self._client.aio.interactions.create(
            model=self._model,
            input=source_text,
            system_instruction=MEMORY_EXTRACTION_SYSTEM_PROMPT,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": MemoryExtractionProposal.model_json_schema(),
            },
            store=False,
        )
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise MemoryCandidateExtractionError(
                "Gemini returned no structured memory extraction output"
            )
        try:
            return MemoryExtractionProposal.model_validate_json(output_text)
        except ValidationError as exc:
            raise MemoryCandidateExtractionError(
                "Gemini returned an invalid memory extraction proposal"
            ) from exc


def build_memory_candidate_extractor(
    *,
    provider: str,
    model: str,
) -> MemoryCandidateExtractor:
    """Build an adapter for the already-selected active production AI provider."""

    normalized_provider = normalize_ai_provider(provider)
    normalized_model = _require_non_empty(model, name="model")
    api_key = require_provider_api_key(
        normalized_provider,
        purpose="memory candidate extraction",
    )

    if normalized_provider == "openai":
        from openai import AsyncOpenAI

        return OpenAIMemoryCandidateExtractor(
            client=AsyncOpenAI(api_key=api_key),
            model=normalized_model,
        )

    if normalized_provider == "gemini":
        from google import genai

        return GeminiMemoryCandidateExtractor(
            client=genai.Client(api_key=api_key),
            model=normalized_model,
        )

    raise AssertionError(f"Unhandled AI provider: {normalized_provider}")