"""Bounded executor contract behind the governed capability runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from jarvis.authority.types import ActionAttributes
from jarvis.capabilities.models import CapabilityRequest, CapabilityResult


class CapabilityExecutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedCapability:
    request: CapabilityRequest
    target: dict[str, Any]
    parameters: dict[str, Any]
    material_summary: str
    attributes: ActionAttributes
    execution_payload: dict[str, Any]


class CapabilityExecutor(Protocol):
    capability_key: str
    operations: tuple[str, ...]

    def prepare(self, request: CapabilityRequest) -> PreparedCapability: ...

    def execute(self, prepared: PreparedCapability) -> CapabilityResult: ...
