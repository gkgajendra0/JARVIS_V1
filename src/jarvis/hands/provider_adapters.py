"""Approved cloud-provider adapter boundary for JARVIS Hands structured planning."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from jarvis.ai_provider import normalize_ai_provider, require_provider_api_key

LOGGER = logging.getLogger(__name__)


class StructuredOutputError(ValueError):
    """Raised when a provider cannot produce validated structured Hands output."""


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


class OpenAIStructuredOutputClient:
    """OpenAI Responses structured-output adapter for the Hands planner.

    Hands is an interactive voice path, so planning explicitly uses low reasoning effort
    instead of inheriting the model's medium default. Correctness remains in JARVIS-owned
    typed contracts, grounding, Authority, execution verification and bounded recovery.
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
        started = time.perf_counter()
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
            reasoning={"effort": "low"},
            text_format=response_model,
            store=False,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        LOGGER.info(
            "Hands provider parse | provider=openai | model=%s | schema=%s | elapsed_ms=%.1f",
            self.model_name,
            response_model.__name__,
            elapsed_ms,
        )
        parsed = getattr(response, "output_parsed", None)
        if not isinstance(parsed, response_model):
            raise StructuredOutputError(
                "OpenAI returned no validated Hands planner output"
            )
        return parsed


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
            return response_model.model_validate_json(output_text)
        except ValidationError as exc:
            raise StructuredOutputError(
                "Gemini returned invalid Hands planner output"
            ) from exc


def build_structured_output_client(
    *,
    provider: str,
    model: str,
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

    if normalized_provider == "openai":
        from openai import AsyncOpenAI

        return OpenAIStructuredOutputClient(
            client=AsyncOpenAI(api_key=api_key),
            model=model_name,
        )

    if normalized_provider == "gemini":
        from google import genai

        return GeminiStructuredOutputClient(
            client=genai.Client(api_key=api_key),
            model=model_name,
        )

    raise AssertionError(f"Unhandled Hands planner provider: {normalized_provider}")
