"""Question-bound personal evidence contracts; canonical storage retains truth."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, model_validator

from jarvis.personal_learning_scope import SUPPRESSION_KEYS

from .assertions import SemanticAssertionRecord

ScopeKey = Literal[
    "owned_item.vehicle",
    "owned_item.device",
    "owned_item.other",
    "food_preference",
    "response_preference",
    "routine",
    "goal",
]


class PersonalContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    scope_key: ScopeKey
    target_quote: str | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_target(cls, value):
        if isinstance(value, dict) and "target_quote" in value:
            quote = value["target_quote"]
            if (
                type(quote) is not str
                or not quote.strip()
                or len(quote.encode("utf-8")) > 256
                or value.get("scope_key") in ("food_preference", "response_preference")
            ):
                raise ValueError("invalid context target")
        return value


def parse_context_requests(
    requests: object, *, question: str
) -> tuple[PersonalContextRequest, ...]:
    if type(requests) is not list or not 1 <= len(requests) <= 4:
        raise ValueError("invalid context requests")
    if not isinstance(question, str):
        raise ValueError("invalid current question")  # noqa: TRY004 - closed parser contract
    if frozenset(get_args(ScopeKey)) != SUPPRESSION_KEYS:
        raise ValueError("context scope registry mismatch")
    parsed = []
    seen = set()
    for item in requests:
        if isinstance(item, PersonalContextRequest):
            item = item.model_dump(exclude_unset=True)
        request = PersonalContextRequest.model_validate(item, strict=True)
        quote = request.target_quote
        if quote is not None and quote not in question:
            raise ValueError("context target is not current question text")
        key = (request.scope_key, quote)
        if key in seen:
            raise ValueError("duplicate context request")
        seen.add(key)
        parsed.append(request)
    return tuple(parsed)


@dataclass(frozen=True)
class ScopedContextSnapshot:
    entries: tuple[tuple[SemanticAssertionRecord, str], ...]
    suppression: tuple[tuple[str, int, bool], ...]
