"""Fail-closed registries for Phase-4 model-routing contracts."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from jarvis.model_routing.models import (
    ModelTarget,
    RoutingRequest,
    RoutingStrategyResult,
)


def _token(value: object, *, field: str) -> str:
    normalized = str(value).strip().casefold()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


class RoutingRegistryError(RuntimeError):
    """Base fail-closed registry error."""


class DuplicateRegistrationError(RoutingRegistryError):
    """Raised when a stable registry key is registered twice."""


class UnknownModelTargetError(RoutingRegistryError):
    """Raised when a target ID is not explicitly registered."""


class UnknownModelAdapterError(RoutingRegistryError):
    """Raised when an adapter ID is not explicitly registered."""


class UnknownRoutingStrategyError(RoutingRegistryError):
    """Raised when an exact strategy key/version is not registered."""


class ModelAdapter(Protocol):
    adapter_id: str

    async def invoke_structured(
        self,
        *,
        target: ModelTarget,
        system_prompt: str,
        input_payload: dict[str, Any],
        response_model: type[Any],
        request_context: Any,
    ) -> Any: ...


class RoutingStrategy(Protocol):
    strategy_key: str
    strategy_version: int

    def rank(
        self,
        *,
        request: RoutingRequest,
        eligible_targets: tuple[ModelTarget, ...],
        history: object | None,
    ) -> RoutingStrategyResult: ...


class ModelAdapterRegistry:
    """Registry of invocation adapters; unknown adapter IDs fail closed."""

    def __init__(
        self,
        adapters: Iterable[ModelAdapter] = (),
    ) -> None:
        self._adapters: dict[str, ModelAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: ModelAdapter) -> None:
        adapter_id = _token(
            getattr(adapter, "adapter_id", ""),
            field="adapter_id",
        )
        if adapter_id in self._adapters:
            raise DuplicateRegistrationError(
                f"model adapter already registered: {adapter_id}"
            )
        self._adapters[adapter_id] = adapter

    def require(self, adapter_id: str) -> ModelAdapter:
        key = _token(adapter_id, field="adapter_id")
        try:
            return self._adapters[key]
        except KeyError as exc:
            raise UnknownModelAdapterError(
                f"unknown model adapter: {key}"
            ) from exc

    def contains(self, adapter_id: str) -> bool:
        key = _token(adapter_id, field="adapter_id")
        return key in self._adapters

    def all(self) -> tuple[ModelAdapter, ...]:
        return tuple(
            self._adapters[key]
            for key in sorted(self._adapters)
        )


class RoutingStrategyRegistry:
    """Exact key/version registry; version drift never silently falls back."""

    def __init__(
        self,
        strategies: Iterable[RoutingStrategy] = (),
    ) -> None:
        self._strategies: dict[
            tuple[str, int],
            RoutingStrategy,
        ] = {}
        for strategy in strategies:
            self.register(strategy)

    def register(self, strategy: RoutingStrategy) -> None:
        key = _token(
            getattr(strategy, "strategy_key", ""),
            field="strategy_key",
        )
        version = _positive_int(
            getattr(strategy, "strategy_version", None),
            field="strategy_version",
        )
        registry_key = (key, version)
        if registry_key in self._strategies:
            raise DuplicateRegistrationError(
                f"routing strategy already registered: {key}.v{version}"
            )
        self._strategies[registry_key] = strategy

    def require(
        self,
        strategy_key: str,
        strategy_version: int,
    ) -> RoutingStrategy:
        key = _token(
            strategy_key,
            field="strategy_key",
        )
        version = _positive_int(
            strategy_version,
            field="strategy_version",
        )
        try:
            return self._strategies[(key, version)]
        except KeyError as exc:
            raise UnknownRoutingStrategyError(
                f"unknown routing strategy: {key}.v{version}"
            ) from exc

    def all(self) -> tuple[RoutingStrategy, ...]:
        return tuple(
            self._strategies[key]
            for key in sorted(
                self._strategies,
                key=lambda item: (item[0], item[1]),
            )
        )


class ModelTargetRegistry:
    """Version-controlled approved targets backed by known adapters."""

    def __init__(
        self,
        adapter_registry: ModelAdapterRegistry,
        targets: Iterable[ModelTarget] = (),
    ) -> None:
        if not isinstance(
            adapter_registry,
            ModelAdapterRegistry,
        ):
            raise TypeError(
                "adapter_registry must be a ModelAdapterRegistry"
            )
        self._adapter_registry = adapter_registry
        self._targets: dict[str, ModelTarget] = {}
        for target in targets:
            self.register(target)

    def register(self, target: ModelTarget) -> None:
        if not isinstance(target, ModelTarget):
            raise TypeError("target must be a ModelTarget")
        self._adapter_registry.require(target.adapter_id)
        if target.target_id in self._targets:
            raise DuplicateRegistrationError(
                f"model target already registered: {target.target_id}"
            )
        self._targets[target.target_id] = target

    def require(self, target_id: str) -> ModelTarget:
        key = _token(
            target_id,
            field="target_id",
        )
        try:
            return self._targets[key]
        except KeyError as exc:
            raise UnknownModelTargetError(
                f"unknown model target: {key}"
            ) from exc

    def all(self) -> tuple[ModelTarget, ...]:
        return tuple(
            self._targets[key]
            for key in sorted(self._targets)
        )

    def for_role(
        self,
        role: str,
    ) -> tuple[ModelTarget, ...]:
        normalized = _token(
            role,
            field="role",
        )
        return tuple(
            target
            for target in self.all()
            if normalized in target.roles
        )

    def for_capability(
        self,
        capability: str,
    ) -> tuple[ModelTarget, ...]:
        normalized = _token(
            capability,
            field="capability",
        )
        return tuple(
            target
            for target in self.all()
            if normalized in target.capabilities
        )
