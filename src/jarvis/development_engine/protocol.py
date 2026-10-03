"""Execution boundary between the JARVIS control plane and engineering intelligence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .contracts import DevelopmentResultV1, DevelopmentTicketV1


@dataclass(frozen=True, slots=True)
class DevelopmentToolSpecV1:
    """Provider-neutral projection of one governed development operation."""

    name: str
    description: str
    parameter_schema: Mapping[str, Any]


class DevelopmentToolPort(Protocol):
    """Narrow JARVIS-owned development tool surface.

    Implementations enforce workspace, authority, dependency, sandbox and secret
    policy. A DevelopmentEngine is never granted host authority merely because it
    requested an operation.
    """

    @property
    def tool_names(self) -> tuple[str, ...]: ...

    @property
    def tool_specs(self) -> tuple[DevelopmentToolSpecV1, ...]: ...

    def snapshot(self) -> Mapping[str, Any]:
        """Return bounded canonical progress for crash/thread reconstruction."""
        ...

    async def invoke(
        self,
        tool_name: str,
        parameters: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


class DevelopmentEngine(Protocol):
    """Provider-neutral engineering specialist."""

    @property
    def engine_id(self) -> str: ...

    @property
    def engine_version(self) -> str: ...

    async def execute(
        self,
        ticket: DevelopmentTicketV1,
        *,
        tools: DevelopmentToolPort,
    ) -> DevelopmentResultV1: ...
