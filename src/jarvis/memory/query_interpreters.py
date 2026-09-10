"""Provider adapters that propose structured memory queries without release authority."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jarvis.ai_provider import (
    normalize_ai_provider,
    require_provider_api_key,
    resolve_ai_role_model,
)

from .query_plan import (
    MemoryFacetCatalog,
    MemoryQueryIntent,
    MemoryQueryInterpreter,
    MemoryQueryProposal,
    MemoryTemporalScope,
)

MEMORY_QUERY_INTERPRETATION_SYSTEM_PROMPT = """You translate exactly one USER memory lookup into one structured JARVIS memory-query selection.

You are a semantic interpreter only. You never answer the user's question, retrieve a memory value, establish truth, or decide whether any memory may be released. JARVIS deterministically validates your selection after you return it.

The input contains:
- user_query: the exact accepted USER utterance.
- eligible_facets: numbered canonical memory keys currently eligible for this execution boundary. Facets never contain memory values.

Intent rules:
- exact_fact: the user asks for one ordinary current canonical fact and exactly one eligible facet matches the requested subject/relation.
- qualified_fact: the user asks for a secondary, alternate, backup, other, special, negated, or otherwise qualified variant rather than the ordinary canonical relation.
- external_source_fact: the user asks what a rumor, web page, email, file, external source, or other non-canonical source says.
- broad_recall: the user asks for multiple memories, a list, a broad topic recall, or everything known about something.
- ambiguous: no single eligible facet can be selected safely or the requested subject/relation is unclear.
- unsupported: the utterance is not a memory lookup that this schema can represent.

Temporal rules:
- current: the user asks for the present/current fact or gives no historical qualifier.
- historical: the user asks for old, previous, former, past, earlier, superseded, forgotten, deleted, or no-longer-current information.
- as_of: the user asks for the fact at a specific past date/time or other explicit as-of point; copy that phrase to as_of_text.
- unspecified: use only when temporal intent truly cannot be determined.

Facet-selection rules:
- For exact_fact, facet_index MUST be the integer facet_index of exactly one eligible_facets entry.
- For every non-exact intent, facet_index MUST be -1.
- Never invent an index and never reproduce or rewrite canonical subject_scope, subject, or predicate strings in the response.
- For exact_fact, subject_reference MUST be a short contiguous phrase copied verbatim from user_query that identifies the requested subject.
- For exact_fact, requested_relation MUST be a short contiguous phrase copied verbatim from user_query that identifies the requested relation.
- If you cannot provide grounded references or cannot safely select exactly one listed facet, use ambiguous with facet_index=-1 instead of exact_fact.
- For non-exact intents, subject_reference and requested_relation must be null.
- as_of_text must be null unless temporal_scope is as_of.

Return only the requested schema.
"""


class MemoryQueryInterpretationError(RuntimeError):
    """Raised when a provider cannot return a validated memory-query proposal."""


class MemoryQuerySelection(BaseModel):
    """Provider-facing selection that cannot invent canonical memory keys."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    intent: MemoryQueryIntent
    facet_index: int = Field(
        ge=-1,
        description=(
            "Eligible facet index for exact_fact; use -1 for every non-exact intent."
        ),
    )
    subject_reference: str | None = Field(
        description=(
            "Verbatim user-query phrase identifying the subject for exact_fact; "
            "otherwise null."
        ),
        min_length=1,
        max_length=240,
    )
    requested_relation: str | None = Field(
        description=(
            "Verbatim user-query phrase identifying the requested relation for "
            "exact_fact; otherwise null."
        ),
        min_length=1,
        max_length=240,
    )
    temporal_scope: MemoryTemporalScope
    as_of_text: str | None = Field(
        description=(
            "Verbatim as-of phrase only when temporal_scope is as_of; otherwise null."
        ),
        min_length=1,
        max_length=240,
    )


def _require_non_empty(value: str, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def memory_query_interpreter_input(
    *,
    text: str,
    catalog: MemoryFacetCatalog,
) -> str:
    """Serialize the user query plus numbered eligible facet keys, never values."""

    query = _require_non_empty(text, name="text")
    if not isinstance(catalog, MemoryFacetCatalog):
        raise TypeError("catalog must be a MemoryFacetCatalog")
    payload = {
        "user_query": query,
        "eligible_facets": [
            {
                "facet_index": index,
                "subject_scope": facet.subject_scope,
                "subject": facet.subject,
                "predicate": facet.predicate,
            }
            for index, facet in enumerate(catalog.facets)
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def materialize_memory_query_selection(
    selection: MemoryQuerySelection,
    *,
    catalog: MemoryFacetCatalog,
) -> MemoryQueryProposal:
    """Resolve a provider-selected index back to JARVIS-owned canonical facet keys."""

    if not isinstance(selection, MemoryQuerySelection):
        raise TypeError("selection must be a MemoryQuerySelection")
    if not isinstance(catalog, MemoryFacetCatalog):
        raise TypeError("catalog must be a MemoryFacetCatalog")

    subject_scope: str | None = None
    subject: str | None = None
    predicate: str | None = None

    if selection.intent is MemoryQueryIntent.EXACT_FACT:
        if selection.facet_index == -1:
            return MemoryQueryProposal(
                intent=selection.intent,
                subject_reference=selection.subject_reference,
                requested_relation=selection.requested_relation,
                temporal_scope=selection.temporal_scope,
                as_of_text=selection.as_of_text,
            )
        if selection.facet_index >= len(catalog.facets):
            raise MemoryQueryInterpretationError(
                "provider selected a facet index outside the eligible catalog"
            )
        facet = catalog.facets[selection.facet_index]
        subject_scope = facet.subject_scope
        subject = facet.subject
        predicate = facet.predicate

    return MemoryQueryProposal(
        intent=selection.intent,
        subject_scope=subject_scope,
        subject=subject,
        predicate=predicate,
        subject_reference=selection.subject_reference,
        requested_relation=selection.requested_relation,
        temporal_scope=selection.temporal_scope,
        as_of_text=selection.as_of_text,
    )


class OpenAIMemoryQueryInterpreter:
    """OpenAI Responses adapter using native Pydantic structured output."""

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

    async def interpret(
        self,
        *,
        text: str,
        catalog: MemoryFacetCatalog,
    ) -> MemoryQueryProposal:
        interpreter_input = memory_query_interpreter_input(text=text, catalog=catalog)
        response = await self._client.responses.parse(
            model=self._model,
            input=[
                {
                    "role": "system",
                    "content": MEMORY_QUERY_INTERPRETATION_SYSTEM_PROMPT,
                },
                {"role": "user", "content": interpreter_input},
            ],
            text_format=MemoryQuerySelection,
            store=False,
        )
        selection = getattr(response, "output_parsed", None)
        if not isinstance(selection, MemoryQuerySelection):
            raise MemoryQueryInterpretationError(
                "OpenAI returned no validated memory-query selection"
            )
        return materialize_memory_query_selection(selection, catalog=catalog)


class GeminiMemoryQueryInterpreter:
    """Gemini Interactions adapter using JSON Schema structured output."""

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

    async def interpret(
        self,
        *,
        text: str,
        catalog: MemoryFacetCatalog,
    ) -> MemoryQueryProposal:
        interpreter_input = memory_query_interpreter_input(text=text, catalog=catalog)
        response = await self._client.aio.interactions.create(
            model=self._model,
            input=interpreter_input,
            system_instruction=MEMORY_QUERY_INTERPRETATION_SYSTEM_PROMPT,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": MemoryQuerySelection.model_json_schema(),
            },
            store=False,
        )
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise MemoryQueryInterpretationError(
                "Gemini returned no structured memory-query output"
            )
        try:
            selection = MemoryQuerySelection.model_validate_json(output_text)
        except ValidationError as exc:
            raise MemoryQueryInterpretationError(
                "Gemini returned an invalid memory-query selection"
            ) from exc
        return materialize_memory_query_selection(selection, catalog=catalog)


def build_structured_provider_client(
    *,
    provider: str,
    purpose: str,
) -> tuple[str, Any]:
    """Construct one cloud SDK client inside the approved memory adapter boundary."""

    normalized_provider = normalize_ai_provider(provider)
    normalized_purpose = _require_non_empty(purpose, name="purpose")
    api_key = require_provider_api_key(
        normalized_provider,
        purpose=normalized_purpose,
    )

    if normalized_provider == "openai":
        from openai import AsyncOpenAI

        return normalized_provider, AsyncOpenAI(api_key=api_key)

    if normalized_provider == "gemini":
        from google import genai

        return normalized_provider, genai.Client(api_key=api_key)

    raise AssertionError(f"Unhandled AI provider: {normalized_provider}")


def build_memory_query_interpreter(
    *,
    provider: str,
    model: str,
) -> MemoryQueryInterpreter:
    """Build an adapter for the already-selected active production AI provider."""

    configured_model = _require_non_empty(model, name="model")
    normalized_provider = normalize_ai_provider(provider)
    normalized_model = resolve_ai_role_model(
        normalized_provider,
        "memory_semantic_recall",
        configured_model=configured_model,
    )
    normalized_provider, client = build_structured_provider_client(
        provider=normalized_provider,
        purpose="memory query interpretation",
    )

    if normalized_provider == "openai":
        return OpenAIMemoryQueryInterpreter(
            client=client,
            model=normalized_model,
        )

    if normalized_provider == "gemini":
        return GeminiMemoryQueryInterpreter(
            client=client,
            model=normalized_model,
        )

    raise AssertionError(f"Unhandled AI provider: {normalized_provider}")
