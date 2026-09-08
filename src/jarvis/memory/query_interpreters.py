"""Provider adapters that propose structured memory queries without release authority."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from jarvis.ai_provider import normalize_ai_provider, require_provider_api_key

from .query_plan import MemoryFacetCatalog, MemoryQueryInterpreter, MemoryQueryProposal

MEMORY_QUERY_INTERPRETATION_SYSTEM_PROMPT = """You translate exactly one USER memory lookup into one structured JARVIS MemoryQueryProposal.

You are a semantic interpreter only. You never answer the user's question, retrieve a memory value, establish truth, or decide whether any memory may be released. JARVIS deterministically validates your proposal after you return it.

The input contains:
- user_query: the exact accepted USER utterance.
- eligible_facets: only canonical memory keys currently eligible for this execution boundary. Facets contain subject_scope, subject, and predicate only; they never contain memory values.

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

For exact_fact only:
- subject_scope, subject, and predicate MUST be copied exactly from one eligible_facets entry. Never invent or rewrite a canonical facet key.
- subject_reference MUST be a short contiguous phrase copied verbatim from user_query that identifies the requested subject. Do not translate or paraphrase it.
- requested_relation MUST be a short contiguous phrase copied verbatim from user_query that identifies the requested relation. Do not translate or paraphrase it.
- If you cannot provide grounded references or cannot safely select exactly one listed facet, use ambiguous instead of exact_fact.

For non-exact intents, canonical facet fields and grounding references may be null when no single facet applies.

Return only the requested schema.
"""


class MemoryQueryInterpretationError(RuntimeError):
    """Raised when a provider cannot return a validated memory-query proposal."""


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
    """Serialize only the user query and eligible canonical facet keys."""

    query = _require_non_empty(text, name="text")
    if not isinstance(catalog, MemoryFacetCatalog):
        raise TypeError("catalog must be a MemoryFacetCatalog")
    payload = {
        "user_query": query,
        "eligible_facets": [
            {
                "subject_scope": facet.subject_scope,
                "subject": facet.subject,
                "predicate": facet.predicate,
            }
            for facet in catalog.facets
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
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
            text_format=MemoryQueryProposal,
            store=False,
        )
        proposal = getattr(response, "output_parsed", None)
        if not isinstance(proposal, MemoryQueryProposal):
            raise MemoryQueryInterpretationError(
                "OpenAI returned no validated memory-query proposal"
            )
        return proposal


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
                "schema": MemoryQueryProposal.model_json_schema(),
            },
            store=False,
        )
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise MemoryQueryInterpretationError(
                "Gemini returned no structured memory-query output"
            )
        try:
            return MemoryQueryProposal.model_validate_json(output_text)
        except ValidationError as exc:
            raise MemoryQueryInterpretationError(
                "Gemini returned an invalid memory-query proposal"
            ) from exc


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

    normalized_model = _require_non_empty(model, name="model")
    normalized_provider, client = build_structured_provider_client(
        provider=provider,
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
