"""Provider-neutral model invocation boundary for routed background reasoning."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from jarvis.hands.provider_adapters import (
    StructuredOutputClient,
    build_structured_output_client,
)
from jarvis.model_routing.models import ModelTarget
from jarvis.model_routing.registry import ModelAdapterRegistry


def _required_text(value: object, *, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


@dataclass(frozen=True, slots=True)
class ModelInvocationContext:
    work_id: str
    routing_request_id: str
    decision_id: str
    attempt_id: str
    correlation_key: str

    def __post_init__(self) -> None:
        for field_name in (
            "work_id",
            "routing_request_id",
            "decision_id",
            "attempt_id",
            "correlation_key",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field=field_name),
            )


StructuredClientFactory = Callable[[str, str], StructuredOutputClient]


def _default_client_factory(provider: str, model: str) -> StructuredOutputClient:
    return build_structured_output_client(provider=provider, model=model)


class StructuredOutputModelAdapter:
    """Invoke one provider family; routing remains entirely outside this adapter."""

    def __init__(
        self,
        *,
        adapter_id: str,
        provider_id: str,
        client_factory: StructuredClientFactory = _default_client_factory,
    ) -> None:
        self.adapter_id = _required_text(adapter_id, field="adapter_id").casefold()
        self.provider_id = _required_text(provider_id, field="provider_id").casefold()
        self._client_factory = client_factory
        self._clients: dict[str, StructuredOutputClient] = {}

    def _client_for(self, target: ModelTarget) -> StructuredOutputClient:
        if target.adapter_id != self.adapter_id:
            raise ValueError("target adapter_id does not match invocation adapter")
        if target.provider_id != self.provider_id:
            raise ValueError("target provider_id does not match invocation adapter")
        client = self._clients.get(target.target_id)
        if client is None:
            client = self._client_factory(target.provider_id, target.model_id)
            self._clients[target.target_id] = client
        if client.provider_name.strip().casefold() != target.provider_id:
            raise ValueError("structured client provider does not match target")
        if client.model_name.strip() != target.model_id:
            raise ValueError("structured client model does not match target")
        return client

    async def invoke_structured(
        self,
        *,
        target: ModelTarget,
        system_prompt: str,
        input_payload: dict[str, Any],
        response_model: type[BaseModel],
        request_context: ModelInvocationContext,
    ) -> BaseModel:
        if not isinstance(target, ModelTarget):
            raise TypeError("target must be a ModelTarget")
        if not isinstance(request_context, ModelInvocationContext):
            raise TypeError("request_context must be a ModelInvocationContext")
        client = self._client_for(target)
        return await client.parse(
            system_prompt=system_prompt,
            input_payload=input_payload,
            response_model=response_model,
        )


class ModelInvoker:
    """Dispatch to the adapter for an already-selected target."""

    def __init__(self, adapter_registry: ModelAdapterRegistry) -> None:
        if not isinstance(adapter_registry, ModelAdapterRegistry):
            raise TypeError("adapter_registry must be a ModelAdapterRegistry")
        self._adapters = adapter_registry

    async def invoke_structured(
        self,
        *,
        target: ModelTarget,
        system_prompt: str,
        input_payload: dict[str, Any],
        response_model: type[BaseModel],
        request_context: ModelInvocationContext,
    ) -> BaseModel:
        adapter = self._adapters.require(target.adapter_id)
        return await adapter.invoke_structured(
            target=target,
            system_prompt=system_prompt,
            input_payload=input_payload,
            response_model=response_model,
            request_context=request_context,
        )
