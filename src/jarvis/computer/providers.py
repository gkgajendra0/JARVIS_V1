"""Mature provider adapters for local desktop computer use."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from jarvis.ai_provider import normalize_ai_provider, require_provider_api_key

from .executor import ComputerExecutor
from .models import (
    ComputerAction,
    ComputerUseResult,
    ComputerUseStatus,
    ScreenFrame,
)


class ComputerUseProviderError(RuntimeError):
    pass


class ComputerUseProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    async def execute(
        self,
        task: str,
        *,
        executor: ComputerExecutor,
        max_steps: int,
    ) -> ComputerUseResult: ...


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        payload = model_dump(exclude_none=True)
        if isinstance(payload, Mapping):
            return dict(payload)
    as_dict = getattr(value, "to_dict", None)
    if callable(as_dict):
        payload = as_dict()
        if isinstance(payload, Mapping):
            return dict(payload)
    raw = getattr(value, "__dict__", None)
    if isinstance(raw, Mapping):
        return {key: item for key, item in raw.items() if not key.startswith("_")}
    raise TypeError(f"expected mapping-like value, got {type(value).__name__}")


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _text_from_gemini_interaction(interaction: Any) -> str:
    text: list[str] = []
    for step in _field(interaction, "steps", []) or []:
        if _field(step, "type") != "model_output":
            continue
        for block in _field(step, "content", []) or []:
            if _field(block, "type") == "text":
                value = _field(block, "text", "")
                if value:
                    text.append(str(value))
    return " ".join(text).strip()


def _gemini_safety(arguments: dict[str, Any]) -> tuple[str | None, str | None]:
    raw = arguments.get("safety_decision")
    if raw is None:
        return None, None
    decision = _field(raw, "decision")
    explanation = _field(raw, "explanation")
    normalized = str(decision).strip().casefold() if decision is not None else None
    return normalized, str(explanation).strip() if explanation else None


def _gemini_action(
    *,
    name: str,
    raw_arguments: dict[str, Any],
    call_id: str | None,
    frame: ScreenFrame,
) -> ComputerAction:
    arguments = dict(raw_arguments)
    intent = arguments.pop("intent", None)
    arguments.pop("safety_decision", None)

    coordinate_pairs = [
        ("x", "y"),
        ("start_x", "start_y"),
        ("end_x", "end_y"),
    ]
    for x_name, y_name in coordinate_pairs:
        if x_name in arguments or y_name in arguments:
            if x_name not in arguments or y_name not in arguments:
                raise ComputerUseProviderError(
                    f"{name} supplied an incomplete coordinate pair"
                )
            x, y = frame.normalized_to_desktop(
                int(arguments[x_name]),
                int(arguments[y_name]),
            )
            arguments[x_name] = x
            arguments[y_name] = y

    return ComputerAction(
        name=name,
        arguments=arguments,
        call_id=call_id,
        intent=str(intent) if intent is not None else None,
    )


class GeminiComputerUseProvider:
    """Google Interactions API computer-use adapter for desktop environment."""

    DEFAULT_MODEL = "gemini-3.6-flash"

    def __init__(self, *, model: str | None = None, client: Any | None = None) -> None:
        self._model = (model or self.DEFAULT_MODEL).strip()
        if not self._model:
            raise ValueError("Gemini computer-use model must not be empty")
        self._client = client

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    def _client_or_create(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from google import genai
        except ImportError as exc:
            raise ComputerUseProviderError("google-genai is unavailable") from exc
        api_key = require_provider_api_key("gemini", purpose="computer use")
        self._client = genai.Client(api_key=api_key)
        return self._client

    @staticmethod
    def _tool() -> dict[str, object]:
        return {
            "type": "computer_use",
            "environment": "desktop",
            "enable_prompt_injection_detection": True,
        }

    async def execute(
        self,
        task: str,
        *,
        executor: ComputerExecutor,
        max_steps: int,
    ) -> ComputerUseResult:
        client = self._client_or_create()
        frame = executor.capture_screen()
        interaction = await asyncio.to_thread(
            client.interactions.create,
            model=self._model,
            input=[
                {"type": "text", "text": task},
                {
                    "type": "image",
                    "data": frame.data_url().split(",", 1)[1],
                    "mime_type": "image/png",
                },
            ],
            tools=[self._tool()],
        )

        executed_steps = 0
        for _ in range(max_steps):
            calls = [
                step
                for step in (_field(interaction, "steps", []) or [])
                if _field(step, "type") == "function_call"
            ]
            if not calls:
                return ComputerUseResult(
                    status=ComputerUseStatus.COMPLETED,
                    provider=self.provider_name,
                    model=self.model_name,
                    steps=executed_steps,
                    summary=_text_from_gemini_interaction(interaction),
                )

            results: list[tuple[str, str | None, dict[str, object]]] = []
            for call in calls:
                name = str(_field(call, "name", "")).strip()
                call_id_value = _field(call, "id")
                call_id = str(call_id_value) if call_id_value is not None else None
                arguments = _as_mapping(_field(call, "arguments", {}))
                safety_decision, safety_message = _gemini_safety(arguments)
                if safety_decision in {"require_confirmation", "confirmation_required"}:
                    return ComputerUseResult(
                        status=ComputerUseStatus.CONFIRMATION_REQUIRED,
                        provider=self.provider_name,
                        model=self.model_name,
                        steps=executed_steps,
                        reason="provider_safety_confirmation_required",
                        safety_message=safety_message,
                    )
                if safety_decision in {"blocked", "block", "deny", "denied"}:
                    return ComputerUseResult(
                        status=ComputerUseStatus.BLOCKED,
                        provider=self.provider_name,
                        model=self.model_name,
                        steps=executed_steps,
                        reason="provider_safety_blocked",
                        safety_message=safety_message,
                    )
                if not name:
                    raise ComputerUseProviderError(
                        "Gemini returned unnamed function call"
                    )
                action = _gemini_action(
                    name=name,
                    raw_arguments=arguments,
                    call_id=call_id,
                    frame=frame,
                )
                execution = executor.execute(action)
                executed_steps += 1
                results.append((name, call_id, execution.to_payload()))

            frame = executor.capture_screen()
            screenshot_b64 = frame.data_url().split(",", 1)[1]
            function_responses = []
            for name, call_id, result in results:
                payload: dict[str, object] = {
                    "type": "function_result",
                    "name": name,
                    "result": [
                        {"type": "text", "text": json.dumps(result)},
                        {
                            "type": "image",
                            "data": screenshot_b64,
                            "mime_type": "image/png",
                        },
                    ],
                }
                if call_id is not None:
                    payload["call_id"] = call_id
                function_responses.append(payload)

            interaction = await asyncio.to_thread(
                client.interactions.create,
                model=self._model,
                previous_interaction_id=_field(interaction, "id"),
                input=function_responses,
                tools=[self._tool()],
            )

        return ComputerUseResult(
            status=ComputerUseStatus.STEP_LIMIT,
            provider=self.provider_name,
            model=self.model_name,
            steps=executed_steps,
            reason="computer_use_step_limit_reached",
        )


def _openai_action(
    raw_action: Any,
    *,
    frame: ScreenFrame,
    call_id: str,
) -> ComputerAction:
    payload = _as_mapping(raw_action)
    action_type = str(payload.pop("type", "")).strip()
    if not action_type:
        raise ComputerUseProviderError("OpenAI returned action without type")

    if action_type in {"click", "double_click", "move", "scroll"}:
        x, y = frame.pixel_to_desktop(int(payload["x"]), int(payload["y"]))
        payload["x"] = x
        payload["y"] = y

    if action_type == "click":
        button = str(payload.pop("button", "left")).casefold()
        if button == "right":
            action_type = "right_click"
        elif button == "wheel":
            action_type = "middle_click"
        elif button not in {"left"}:
            raise ComputerUseProviderError(
                f"unsupported OpenAI click button: {button}"
            )
    elif action_type == "drag":
        resolved_path = []
        for point in payload.get("path", []):
            point_payload = _as_mapping(point)
            x, y = frame.pixel_to_desktop(
                int(point_payload["x"]),
                int(point_payload["y"]),
            )
            resolved_path.append({"x": x, "y": y})
        payload = {"path": resolved_path}
        action_type = "drag_path"
    elif action_type == "keypress":
        keys = [str(key) for key in payload.get("keys", [])]
        if not keys:
            raise ComputerUseProviderError("OpenAI keypress action has no keys")
        if len(keys) == 1:
            action_type = "press_key"
            payload = {"key": keys[0]}
        else:
            action_type = "hotkey"
            payload = {"keys": keys}
    elif action_type == "screenshot":
        action_type = "take_screenshot"
        payload = {}
    elif action_type == "scroll":
        payload = {
            "x": payload["x"],
            "y": payload["y"],
            "scroll_x": int(payload.get("scroll_x", 0)),
            "scroll_y": int(payload.get("scroll_y", 0)),
        }
        action_type = "scroll_delta"

    return ComputerAction(
        name=action_type,
        arguments=payload,
        call_id=call_id,
    )


def _iter_openai_actions(call: Any) -> Iterable[Any]:
    batched = _field(call, "actions")
    if batched:
        yield from batched
        return
    action = _field(call, "action")
    if action is not None:
        yield action


class OpenAIComputerUseProvider:
    """OpenAI Responses API computer tool adapter."""

    DEFAULT_MODEL = "gpt-5.6-terra"

    def __init__(self, *, model: str | None = None, client: Any | None = None) -> None:
        self._model = (model or self.DEFAULT_MODEL).strip()
        if not self._model:
            raise ValueError("OpenAI computer-use model must not be empty")
        self._client = client

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    def _client_or_create(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ComputerUseProviderError("openai SDK is unavailable") from exc
        api_key = require_provider_api_key("openai", purpose="computer use")
        self._client = OpenAI(api_key=api_key)
        return self._client

    async def execute(
        self,
        task: str,
        *,
        executor: ComputerExecutor,
        max_steps: int,
    ) -> ComputerUseResult:
        client = self._client_or_create()
        frame = executor.capture_screen()
        response = await asyncio.to_thread(
            client.responses.create,
            model=self._model,
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

            response = await asyncio.to_thread(
                client.responses.create,
                model=self._model,
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


def build_computer_use_provider(
    provider: str,
    *,
    model: str | None = None,
    client: Any | None = None,
) -> ComputerUseProvider:
    normalized = normalize_ai_provider(provider)
    if normalized == "gemini":
        return GeminiComputerUseProvider(model=model, client=client)
    return OpenAIComputerUseProvider(model=model, client=client)
