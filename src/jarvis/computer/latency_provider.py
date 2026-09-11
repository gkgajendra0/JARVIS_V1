"""Latency-tuned provider adapters for interactive JARVIS Computer Use.

The canonical provider implementations remain the compatibility baseline. This module
keeps the same action/safety semantics while tuning OpenAI's visual desktop loop for an
interactive voice path: low reasoning effort, non-stored responses and per-round-trip
latency telemetry. Correctness and containment stay in the local JARVIS executor.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from jarvis.ai_provider import normalize_ai_provider
from jarvis.computer.executor import ComputerExecutor
from jarvis.computer.models import ComputerUseResult, ComputerUseStatus
from jarvis.computer.providers import (
    ComputerUseProvider,
    ComputerUseProviderError,
    OpenAIComputerUseProvider,
    _field,
    _iter_openai_actions,
    _openai_action,
    build_computer_use_provider,
)

LOGGER = logging.getLogger(__name__)


class LowLatencyOpenAIComputerUseProvider(OpenAIComputerUseProvider):
    """OpenAI Computer Use with low reasoning and per-turn latency telemetry."""

    async def _create_response(self, client: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        response = await asyncio.to_thread(
            client.responses.create,
            reasoning={"effort": "low"},
            store=False,
            **kwargs,
        )
        LOGGER.info(
            "Visual computer provider response | provider=openai | model=%s | "
            "reasoning=low | elapsed_ms=%.1f",
            self.model_name,
            (time.perf_counter() - started) * 1000,
        )
        return response

    async def execute(
        self,
        task: str,
        *,
        executor: ComputerExecutor,
        max_steps: int,
    ) -> ComputerUseResult:
        client = self._client_or_create()
        frame = executor.capture_screen()
        response = await self._create_response(
            client,
            model=self.model_name,
            tools=[{"type": "computer"}],
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": task},
                        {"type": "input_image", "image_url": frame.data_url()},
                    ],
                }
            ],
        )

        executed_steps = 0
        for _ in range(max_steps):
            calls = [
                item
                for item in (_field(response, "output", []) or [])
                if _field(item, "type") == "computer_call"
            ]
            if not calls:
                summary = str(_field(response, "output_text", "") or "").strip()
                return ComputerUseResult(
                    status=ComputerUseStatus.COMPLETED,
                    provider=self.provider_name,
                    model=self.model_name,
                    steps=executed_steps,
                    summary=summary,
                )

            output_items = []
            for call in calls:
                pending_checks = list(_field(call, "pending_safety_checks", []) or [])
                if pending_checks:
                    messages = [
                        str(_field(check, "message", "") or "").strip()
                        for check in pending_checks
                    ]
                    return ComputerUseResult(
                        status=ComputerUseStatus.CONFIRMATION_REQUIRED,
                        provider=self.provider_name,
                        model=self.model_name,
                        steps=executed_steps,
                        reason="provider_safety_confirmation_required",
                        safety_message="; ".join(
                            message for message in messages if message
                        ),
                    )

                call_id = str(_field(call, "call_id", "")).strip()
                if not call_id:
                    raise ComputerUseProviderError(
                        "OpenAI returned computer call without call_id"
                    )
                for raw_action in _iter_openai_actions(call):
                    action = _openai_action(raw_action, frame=frame, call_id=call_id)
                    executor.execute(action)
                    executed_steps += 1

                frame = executor.capture_screen()
                output_items.append(
                    {
                        "type": "computer_call_output",
                        "call_id": call_id,
                        "output": {
                            "type": "computer_screenshot",
                            "image_url": frame.data_url(),
                        },
                    }
                )

            response = await self._create_response(
                client,
                model=self.model_name,
                tools=[{"type": "computer"}],
                previous_response_id=_field(response, "id"),
                input=output_items,
            )

        return ComputerUseResult(
            status=ComputerUseStatus.STEP_LIMIT,
            provider=self.provider_name,
            model=self.model_name,
            steps=executed_steps,
            reason="computer_use_step_limit_reached",
        )


def build_latency_computer_use_provider(
    provider: str,
    *,
    model: str | None = None,
    client: Any | None = None,
) -> ComputerUseProvider:
    """Use the latency-tuned OpenAI loop while preserving other provider adapters."""

    normalized = normalize_ai_provider(provider)
    if normalized == "openai":
        return LowLatencyOpenAIComputerUseProvider(model=model, client=client)
    return build_computer_use_provider(
        normalized,
        model=model,
        client=client,
    )
