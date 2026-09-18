"""Context-local identifiers for correlating JARVIS operational evidence."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CorrelationContext:
    session_id: str | None = None
    turn_id: str | None = None
    goal_id: str | None = None
    capability_id: str | None = None
    component_id: str | None = None
    proposal_id: str | None = None
    incident_id: str | None = None

    def as_dict(self) -> dict[str, str]:
        pairs = (
            ("session_id", self.session_id),
            ("turn_id", self.turn_id),
            ("goal_id", self.goal_id),
            ("capability_id", self.capability_id),
            ("component_id", self.component_id),
            ("proposal_id", self.proposal_id),
            ("incident_id", self.incident_id),
        )
        return {key: value for key, value in pairs if value is not None}


_CONTEXT: ContextVar[CorrelationContext] = ContextVar(
    "jarvis_correlation_context",
    default=CorrelationContext(),
)


def current_correlation() -> CorrelationContext:
    return _CONTEXT.get()


def set_correlation(context: CorrelationContext) -> Token[CorrelationContext]:
    return _CONTEXT.set(context)


def reset_correlation(token: Token[CorrelationContext]) -> None:
    _CONTEXT.reset(token)
