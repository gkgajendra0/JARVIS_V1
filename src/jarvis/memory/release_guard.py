"""Same-provider structured semantic verifier for bounded memory release."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from .assertions import SemanticAssertionRecord
from .query_interpreters import build_structured_provider_client


class MemoryReleaseAnswerType(StrEnum):
    CURRENT_VALUE = "current_value"
    CURRENT_VALUE_COMPARISON = "current_value_comparison"
    REASON_EXPLANATION = "reason_explanation"
    PROVENANCE_ACTOR = "provenance_actor"
    REPLACEMENT_SUCCESSOR = "replacement_successor"
    RELATED_RECORD = "related_record"
    HISTORICAL_VALUE = "historical_value"
    EXTERNAL_SOURCE = "external_source"
    BROAD_RECALL = "broad_recall"
    ADVICE_OR_OTHER = "advice_or_other"


_ALLOWED_ANSWER_TYPES = frozenset(
    {
        MemoryReleaseAnswerType.CURRENT_VALUE,
        MemoryReleaseAnswerType.CURRENT_VALUE_COMPARISON,
    }
)


class MemoryReleaseJudgement(BaseModel):
    """Untrusted provider judgement; JARVIS derives the final allow decision."""

    model_config = ConfigDict(extra="forbid")

    answer_type: MemoryReleaseAnswerType
    directly_supported: bool

    @property
    def allows_release(self) -> bool:
        return self.directly_supported and self.answer_type in _ALLOWED_ANSWER_TYPES


class MemoryReleaseGuard(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    async def evaluate(
        self,
        *,
        text: str,
        evidence: SemanticAssertionRecord,
    ) -> MemoryReleaseJudgement: ...


class MemoryReleaseGuardError(RuntimeError):
    """Raised when the configured provider cannot return a validated judgement."""


MEMORY_RELEASE_GUARD_SYSTEM_PROMPT = """You are a conservative semantic verifier for JARVIS personal memory.

You receive exactly one USER question plus exactly one canonical current memory fact that has already passed JARVIS lifecycle, authority, sensitivity, conflict, and exact-facet checks.

Your only job is to classify whether THIS ONE FACT directly and sufficiently answers THIS QUESTION.

Return current_value with directly_supported=true only when the question asks for the current recorded value itself.
Return current_value_comparison with directly_supported=true only when the question asks whether a stated value matches or does not match the current recorded value.

For every other semantic request set directly_supported=false and classify the requested answer type accurately, including:
- why/reason/explanation -> reason_explanation
- who recommended/supplied/selected/originated it -> provenance_actor
- what replaced/succeeded an older value -> replacement_successor
- a linked or separate record -> related_record
- old/previous/former/as-of/past value -> historical_value
- what a web page/email/file/rumor/external source says -> external_source
- multiple memories/list/everything/topic recall -> broad_recall
- advice/recommendation/what should I do/anything else -> advice_or_other

Critical rule: topical relevance is NOT enough. The fact must itself contain the answer requested. Example: current car=Jimny does NOT answer why Jimny was bought, who recommended Jimny, what car came before it, or whether the user should replace it.

Do not answer the user. Do not invent facts. Return only the requested schema.
"""


def _require_text(value: str, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def memory_release_guard_input(
    *,
    text: str,
    evidence: SemanticAssertionRecord,
) -> str:
    query = _require_text(text, name="text")
    if not isinstance(evidence, SemanticAssertionRecord):
        raise TypeError("evidence must be a SemanticAssertionRecord")
    payload = {
        "user_query": query,
        "canonical_current_fact": {
            "subject_scope": evidence.subject_scope,
            "subject": evidence.subject,
            "predicate": evidence.predicate,
            "value_type": evidence.value_type.value,
            "value": evidence.value,
            "freshness": evidence.freshness_class.value,
            "verification": evidence.verification_state.value,
        },
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class OpenAIMemoryReleaseGuard:
    provider_name = "openai"

    def __init__(self, *, client: Any, model: str) -> None:
        responses = getattr(client, "responses", None)
        if responses is None or not callable(getattr(responses, "parse", None)):
            raise TypeError("client must expose responses.parse")
        self._client = client
        self._model = _require_text(model, name="model")

    @property
    def model_name(self) -> str:
        return self._model

    async def evaluate(
        self,
        *,
        text: str,
        evidence: SemanticAssertionRecord,
    ) -> MemoryReleaseJudgement:
        guard_input = memory_release_guard_input(text=text, evidence=evidence)
        response = await self._client.responses.parse(
            model=self._model,
            input=[
                {"role": "system", "content": MEMORY_RELEASE_GUARD_SYSTEM_PROMPT},
                {"role": "user", "content": guard_input},
            ],
            text_format=MemoryReleaseJudgement,
            store=False,
        )
        judgement = getattr(response, "output_parsed", None)
        if not isinstance(judgement, MemoryReleaseJudgement):
            raise MemoryReleaseGuardError(
                "OpenAI returned no validated memory-release judgement"
            )
        return judgement


class GeminiMemoryReleaseGuard:
    provider_name = "gemini"

    def __init__(self, *, client: Any, model: str) -> None:
        aio = getattr(client, "aio", None)
        interactions = getattr(aio, "interactions", None)
        if interactions is None or not callable(getattr(interactions, "create", None)):
            raise TypeError("client must expose aio.interactions.create")
        self._client = client
        self._model = _require_text(model, name="model")

    @property
    def model_name(self) -> str:
        return self._model

    async def evaluate(
        self,
        *,
        text: str,
        evidence: SemanticAssertionRecord,
    ) -> MemoryReleaseJudgement:
        guard_input = memory_release_guard_input(text=text, evidence=evidence)
        response = await self._client.aio.interactions.create(
            model=self._model,
            input=guard_input,
            system_instruction=MEMORY_RELEASE_GUARD_SYSTEM_PROMPT,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": MemoryReleaseJudgement.model_json_schema(),
            },
            store=False,
        )
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise MemoryReleaseGuardError(
                "Gemini returned no structured memory-release output"
            )
        try:
            return MemoryReleaseJudgement.model_validate_json(output_text)
        except ValidationError as exc:
            raise MemoryReleaseGuardError(
                "Gemini returned an invalid memory-release judgement"
            ) from exc


def build_memory_release_guard(
    *,
    provider: str,
    model: str,
) -> MemoryReleaseGuard:
    """Build the verifier under the already-selected production provider family."""

    normalized_model = _require_text(model, name="model")
    normalized_provider, client = build_structured_provider_client(
        provider=provider,
        purpose="semantic memory release verification",
    )

    if normalized_provider == "openai":
        return OpenAIMemoryReleaseGuard(
            client=client,
            model=normalized_model,
        )

    if normalized_provider == "gemini":
        return GeminiMemoryReleaseGuard(
            client=client,
            model=normalized_model,
        )

    raise AssertionError(f"Unhandled AI provider: {normalized_provider}")
