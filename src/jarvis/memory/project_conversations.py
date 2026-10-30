"""Immutable contracts shared by project storage, preparation and dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def _identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"invalid {name}")


@dataclass(frozen=True, slots=True)
class ProjectSelection:
    project_id: str
    thread_id: str
    revision: int

    def __post_init__(self) -> None:
        _identifier(self.project_id, "project_id")
        _identifier(self.thread_id, "thread_id")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("invalid selection revision")


@dataclass(frozen=True, slots=True)
class ConversationReceipt:
    event_id: str
    thread_id: str
    sequence: int
    revision: int
    status: str


@dataclass(frozen=True, slots=True)
class PreparedProjectReply:
    request_id: str
    selection: ProjectSelection
    source_ids: tuple[str, ...]
    context: str
    revision: str
    estimated_tokens: int

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request_id")
        _identifier(self.revision, "context revision")
        if not isinstance(self.selection, ProjectSelection):
            raise TypeError("project selection required")
        if type(self.source_ids) is not tuple:
            raise TypeError("immutable source_ids required")
        for source_id in self.source_ids:
            _identifier(source_id, "source_id")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("duplicate context source")
        if not isinstance(self.context, str) or not self.context.strip():
            raise ValueError("nonempty prepared context required")
        if (
            type(self.estimated_tokens) is not int
            or not 0 < self.estimated_tokens <= 6000
        ):
            raise ValueError("external context token budget exceeded")


@dataclass(frozen=True, slots=True)
class ConversationEvent:
    event_id: str
    segment_id: str
    request_id: str
    role: str
    text: str
    accepted_at: datetime
    delivery: str = "complete"

    def __post_init__(self) -> None:
        for name in ("event_id", "segment_id", "request_id"):
            _identifier(getattr(self, name), name)
        if self.role not in {"user", "assistant", "tool"}:
            raise ValueError("invalid history role")
        if self.delivery not in {"complete", "partial", "failed"}:
            raise ValueError("invalid delivery status")
        if self.role == "user" and self.delivery != "complete":
            raise ValueError("only accepted final user turns may be archived")
        if (
            not isinstance(self.text, str)
            or not self.text.strip()
            or len(self.text) > 65536
        ):
            raise ValueError("invalid event text")
        if (
            not isinstance(self.accepted_at, datetime)
            or self.accepted_at.utcoffset() is None
        ):
            raise ValueError("aware accepted timestamp required")
