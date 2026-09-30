"""Approved cloud-provider adapter boundary for JARVIS Hands structured planning."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from jarvis.ai_provider import normalize_ai_provider, require_provider_api_key
from jarvis.chatgpt_plan import (
    ChatGPTPlanError,
    ChatGPTPlanSessionManager,
)

LOGGER = logging.getLogger(__name__)


class StructuredOutputError(ValueError):
    """Raised when a provider cannot produce validated structured output."""

    response_contract_invalid = True


@dataclass(frozen=True, slots=True)
class StructuredOutputTelemetry:
    """Validated structured output plus provider-observed usage metadata."""

    parsed: BaseModel
    usage: dict[str, int]
    usage_observed: bool
    latency_ms: float

    def __post_init__(self) -> None:
        if not isinstance(self.parsed, BaseModel):
            raise TypeError("parsed must be a Pydantic BaseModel")
        normalized_usage: dict[str, int] = {}
        for key, value in self.usage.items():
            normalized_key = str(key).strip().casefold()
            if not normalized_key:
                raise ValueError("usage keys must not be empty")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("usage values must be non-negative integers")
            normalized_usage[normalized_key] = value
        object.__setattr__(self, "usage", normalized_usage)
        if not isinstance(self.usage_observed, bool):
            raise TypeError("usage_observed must be a bool")
        latency = float(self.latency_ms)
        if latency < 0:
            raise ValueError("latency_ms must not be negative")
        object.__setattr__(self, "latency_ms", latency)


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _usage_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _record_usage(target: dict[str, int], key: str, value: Any) -> None:
    normalized = _usage_int(value)
    if normalized is not None:
        target[key] = normalized


def _openai_usage(response: Any) -> tuple[dict[str, int], bool]:
    usage = _field(response, "usage")
    if usage is None:
        return {}, False
    result: dict[str, int] = {}
    _record_usage(result, "input_tokens", _field(usage, "input_tokens"))
    _record_usage(result, "output_tokens", _field(usage, "output_tokens"))
    _record_usage(result, "total_tokens", _field(usage, "total_tokens"))
    input_details = _field(usage, "input_tokens_details")
    output_details = _field(usage, "output_tokens_details")
    _record_usage(
        result,
        "cached_input_tokens",
        _field(input_details, "cached_tokens"),
    )
    _record_usage(
        result,
        "reasoning_tokens",
        _field(output_details, "reasoning_tokens"),
    )
    return result, True


def _gemini_usage(response: Any) -> tuple[dict[str, int], bool]:
    usage = _field(response, "usage")
    if usage is None:
        return {}, False
    result: dict[str, int] = {}
    _record_usage(result, "input_tokens", _field(usage, "total_input_tokens"))
    _record_usage(result, "output_tokens", _field(usage, "total_output_tokens"))
    _record_usage(result, "total_tokens", _field(usage, "total_tokens"))
    _record_usage(
        result,
        "cached_input_tokens",
        _field(usage, "total_cached_tokens"),
    )
    _record_usage(
        result,
        "reasoning_tokens",
        _field(usage, "total_thought_tokens"),
    )
    _record_usage(
        result,
        "tool_use_tokens",
        _field(usage, "total_tool_use_tokens"),
    )
    return result, True


class StructuredOutputClient(Protocol):
    provider_name: str
    model_name: str

    async def parse(
        self,
        *,
        system_prompt: str,
        input_payload: dict[str, Any],
        response_model: type[BaseModel],
    ) -> BaseModel: ...

    async def parse_with_telemetry(
        self,
        *,
        system_prompt: str,
        input_payload: dict[str, Any],
        response_model: type[BaseModel],
    ) -> StructuredOutputTelemetry: ...


def _openai_reasoning_effort(response_model: type[BaseModel]) -> str:
    """Use classification-grade reasoning for routing, low reasoning for planning."""

    if response_model.__name__ == "HandsRouteSelection":
        return "none"
    return "low"


class OpenAIStructuredOutputClient:
    """OpenAI Responses structured-output adapter for the Hands planner.

    Hands is an interactive voice path. Semantic route selection is a bounded
    classification problem and uses no reasoning; action planning uses low reasoning.
    Correctness remains in JARVIS-owned typed contracts, grounding, Authority, execution
    verification and bounded recovery.
    """

    provider_name = "openai"

    def __init__(self, *, client: Any, model: str) -> None:
        responses = getattr(client, "responses", None)
        if responses is None or not callable(getattr(responses, "parse", None)):
            raise TypeError("client must expose responses.parse")
        self._client = client
        self.model_name = str(model).strip()
        if not self.model_name:
            raise ValueError("Hands planner model must not be empty")

    async def parse(
        self,
        *,
        system_prompt: str,
        input_payload: dict[str, Any],
        response_model: type[BaseModel],
    ) -> BaseModel:
        result = await self.parse_with_telemetry(
            system_prompt=system_prompt,
            input_payload=input_payload,
            response_model=response_model,
        )
        return result.parsed

    async def parse_with_telemetry(
        self,
        *,
        system_prompt: str,
        input_payload: dict[str, Any],
        response_model: type[BaseModel],
    ) -> StructuredOutputTelemetry:
        started = time.perf_counter()
        reasoning_effort = _openai_reasoning_effort(response_model)
        response = await self._client.responses.parse(
            model=self.model_name,
            input=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        input_payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ),
                },
            ],
            reasoning={"effort": reasoning_effort},
            text_format=response_model,
            store=False,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        LOGGER.info(
            "Hands provider parse | provider=openai | model=%s | schema=%s | "
            "reasoning=%s | elapsed_ms=%.1f",
            self.model_name,
            response_model.__name__,
            reasoning_effort,
            elapsed_ms,
        )
        parsed = getattr(response, "output_parsed", None)
        if not isinstance(parsed, response_model):
            raise StructuredOutputError(
                "OpenAI returned no validated Hands planner output"
            )
        usage, usage_observed = _openai_usage(response)
        return StructuredOutputTelemetry(
            parsed=parsed,
            usage=usage,
            usage_observed=usage_observed,
            latency_ms=elapsed_ms,
        )


class ChatGPTPlanStructuredOutputClient:
    """Structured-output client backed by the user's ChatGPT plan allowance."""

    provider_name = "chatgpt_plan"

    def __init__(
        self,
        *,
        session_manager: ChatGPTPlanSessionManager,
        model: str,
    ) -> None:
        self._session_manager = session_manager
        self.model_name = str(model).strip()
        if not self.model_name:
            raise ValueError("ChatGPT plan model must not be empty")

    async def parse(
        self,
        *,
        system_prompt: str,
        input_payload: dict[str, Any],
        response_model: type[BaseModel],
    ) -> BaseModel:
        result = await self.parse_with_telemetry(
            system_prompt=system_prompt,
            input_payload=input_payload,
            response_model=response_model,
        )
        return result.parsed

    async def parse_with_telemetry(
        self,
        *,
        system_prompt: str,
        input_payload: dict[str, Any],
        response_model: type[BaseModel],
    ) -> StructuredOutputTelemetry:
        started = time.perf_counter()
        response = await asyncio.to_thread(
            self._session_manager.invoke_structured,
            model=self.model_name,
            instructions=system_prompt,
            input_payload=input_payload,
            schema_name=response_model.__name__,
            schema=response_model.model_json_schema(),
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        try:
            parsed = response_model.model_validate_json(response.output_text)
        except ValidationError as exc:
            raise StructuredOutputError(
                "ChatGPT plan returned invalid structured output"
            ) from exc
        LOGGER.info(
            "Hands provider parse | provider=chatgpt_plan | model=%s | "
            "schema=%s | elapsed_ms=%.1f",
            self.model_name,
            response_model.__name__,
            elapsed_ms,
        )
        return StructuredOutputTelemetry(
            parsed=parsed,
            usage=response.usage,
            usage_observed=response.usage_observed,
            latency_ms=elapsed_ms,
        )


class FallbackStructuredOutputClient:
    """Prefer ChatGPT-plan inference and use the configured paid provider on failure."""

    provider_name = "chatgpt_plan"

    def __init__(
        self,
        *,
        primary: ChatGPTPlanStructuredOutputClient,
        fallback: StructuredOutputClient,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self.model_name = primary.model_name

    async def parse(
        self,
        *,
        system_prompt: str,
        input_payload: dict[str, Any],
        response_model: type[BaseModel],
    ) -> BaseModel:
        result = await self.parse_with_telemetry(
            system_prompt=system_prompt,
            input_payload=input_payload,
            response_model=response_model,
        )
        return result.parsed

    async def parse_with_telemetry(
        self,
        *,
        system_prompt: str,
        input_payload: dict[str, Any],
        response_model: type[BaseModel],
    ) -> StructuredOutputTelemetry:
        try:
            return await self._primary.parse_with_telemetry(
                system_prompt=system_prompt,
                input_payload=input_payload,
                response_model=response_model,
            )
        except (ChatGPTPlanError, StructuredOutputError) as exc:
            LOGGER.warning(
                "ChatGPT-plan structured inference unavailable; "
                "falling back to provider=%s | error=%s",
                self._fallback.provider_name,
                type(exc).__name__,
            )
            return await self._fallback.parse_with_telemetry(
                system_prompt=system_prompt,
                input_payload=input_payload,
                response_model=response_model,
            )


class GeminiStructuredOutputClient:
    """Gemini Interactions JSON-schema adapter for the Hands planner."""

    provider_name = "gemini"

    def __init__(self, *, client: Any, model: str) -> None:
        aio = getattr(client, "aio", None)
        interactions = getattr(aio, "interactions", None)
        if interactions is None or not callable(getattr(interactions, "create", None)):
            raise TypeError("client must expose aio.interactions.create")
        self._client = client
        self.model_name = str(model).strip()
        if not self.model_name:
            raise ValueError("Hands planner model must not be empty")

    async def parse(
        self,
        *,
        system_prompt: str,
        input_payload: dict[str, Any],
        response_model: type[BaseModel],
    ) -> BaseModel:
        result = await self.parse_with_telemetry(
            system_prompt=system_prompt,
            input_payload=input_payload,
            response_model=response_model,
        )
        return result.parsed

    async def parse_with_telemetry(
        self,
        *,
        system_prompt: str,
        input_payload: dict[str, Any],
        response_model: type[BaseModel],
    ) -> StructuredOutputTelemetry:
        started = time.perf_counter()
        response = await self._client.aio.interactions.create(
            model=self.model_name,
            input=json.dumps(
                input_payload,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ),
            system_instruction=system_prompt,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": response_model.model_json_schema(),
            },
            store=False,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        LOGGER.info(
            "Hands provider parse | provider=gemini | model=%s | schema=%s | elapsed_ms=%.1f",
            self.model_name,
            response_model.__name__,
            elapsed_ms,
        )
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            raise StructuredOutputError(
                "Gemini returned no structured Hands planner output"
            )
        try:
            parsed = response_model.model_validate_json(output_text)
        except ValidationError as exc:
            raise StructuredOutputError(
                "Gemini returned invalid Hands planner output"
            ) from exc
        usage, usage_observed = _gemini_usage(response)
        return StructuredOutputTelemetry(
            parsed=parsed,
            usage=usage,
            usage_observed=usage_observed,
            latency_ms=elapsed_ms,
        )


def build_structured_output_client(
    *,
    provider: str,
    model: str,
    provider_retries: bool = True,
) -> StructuredOutputClient:
    """Build one Hands planner client inside the approved SDK-import boundary."""

    normalized_provider = normalize_ai_provider(provider)
    model_name = str(model).strip()
    if not model_name:
        raise ValueError("Hands planner model must not be empty")
    api_key = require_provider_api_key(
        normalized_provider,
        purpose="Hands semantic planning",
    )

    if not isinstance(provider_retries, bool):
        raise TypeError("provider_retries must be a boolean")

    if normalized_provider == "openai":
        from openai import AsyncOpenAI

        client_kwargs: dict[str, Any] = {"api_key": api_key}
        if not provider_retries:
            client_kwargs["max_retries"] = 0
        return OpenAIStructuredOutputClient(
            client=AsyncOpenAI(**client_kwargs),
            model=model_name,
        )

    if normalized_provider == "gemini":
        from google import genai

        client_kwargs = {"api_key": api_key}
        if not provider_retries:
            client_kwargs["http_options"] = {
                "retry_options": {
                    "attempts": 0,
                }
            }
        return GeminiStructuredOutputClient(
            client=genai.Client(**client_kwargs),
            model=model_name,
        )

    raise AssertionError(f"Unhandled Hands planner provider: {normalized_provider}")


def build_chatgpt_plan_structured_output_client(
    *,
    model: str,
    fallback_provider: str | None = None,
    fallback_model: str | None = None,
    session_manager: ChatGPTPlanSessionManager | None = None,
    provider_retries: bool = True,
) -> StructuredOutputClient:
    """Build ChatGPT-plan primary structured inference with optional paid fallback."""

    model_name = str(model).strip()
    if not model_name:
        raise ValueError("ChatGPT plan model must not be empty")
    primary = ChatGPTPlanStructuredOutputClient(
        session_manager=session_manager or ChatGPTPlanSessionManager(),
        model=model_name,
    )
    if fallback_provider is None:
        return primary
    fallback_name = str(fallback_model or "").strip()
    if not fallback_name:
        raise ValueError("fallback_model is required with fallback_provider")
    fallback = build_structured_output_client(
        provider=fallback_provider,
        model=fallback_name,
        provider_retries=provider_retries,
    )
    return FallbackStructuredOutputClient(primary=primary, fallback=fallback)
