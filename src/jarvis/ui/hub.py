"""Bounded allowlist between internal runtime data and the public local HUD."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

_VOICE = frozenset(
    {
        "offline",
        "standby",
        "activating",
        "listening",
        "thinking",
        "speaking",
        "recovering",
    }
)
_WORK_STATES = frozenset(
    {
        "queued",
        "running",
        "waiting_resource",
        "waiting_dependency",
        "waiting_until",
        "waiting_for_owner",
        "paused",
        "retrying",
        "completed",
        "failed",
        "cancelled",
    }
)
_WORK_TYPES = frozenset(
    {
        "development",
        "research",
        "diagnostics",
        "hands",
        "monitoring",
        "reminder",
        "generic",
        "external_acceptance",
    }
)
_HEALTH_STATES = frozenset(
    {
        "healthy",
        "degraded",
        "unhealthy",
        "unavailable",
        "unknown",
        "ok",
        "warning",
        "critical",
        "stale",
        "starting",
        "failed",
        "recovering",
        "disabled",
    }
)
_COMPONENT = re.compile(r"^[a-zA-Z0-9_.:-]{1,48}$")


def _read(provider: Callable[[], Any] | None) -> Any:
    if provider is None:
        return None
    try:
        return provider()
    except Exception:  # noqa: BLE001 - UI is never a runtime failure domain
        return None


def _value(entry: object, field: str) -> object:
    if not isinstance(entry, Mapping):
        return None
    return entry.get(field)


def _rows(data: object, *, size: int, fields: dict[str, frozenset[str] | None]):
    if not isinstance(data, (list, tuple)):
        return []
    result = []
    for entry in data[:size]:
        projected: dict[str, str] = {}
        for key, allowed in fields.items():
            value = _value(entry, key)
            if not isinstance(value, str):
                continue
            if allowed is None:
                if not _COMPONENT.fullmatch(value):
                    continue
            elif value not in allowed:
                continue
            projected[key] = value
        if len(projected) == len(fields):
            result.append(projected)
    return result


class UISnapshotHub:
    """Read-only pull adapters; no cross-domain user text is ever serialized."""

    def __init__(
        self,
        *,
        voice_provider: Callable[[], Any] | None = None,
        work_provider: Callable[[], Any] | None = None,
        health_provider: Callable[[], Any] | None = None,
        vision_provider: Callable[[], Any] | None = None,
    ) -> None:
        self.voice_provider = voice_provider
        self.work_provider = work_provider
        self.health_provider = health_provider
        self.vision_provider = vision_provider

    def snapshot(self) -> dict[str, object]:
        raw_voice = _read(self.voice_provider)
        state = _value(raw_voice, "state")
        connected = isinstance(state, str) and state in _VOICE and state != "offline"
        vision = _value(_read(self.vision_provider), "state")
        return {
            "schema": 1,
            "connected": connected,
            "voice": {"state": state if connected else "offline"},
            "work": _rows(
                _read(self.work_provider),
                size=6,
                fields={"type": _WORK_TYPES, "state": _WORK_STATES},
            ),
            "health": _rows(
                _read(self.health_provider),
                size=8,
                fields={"component": None, "state": _HEALTH_STATES},
            ),
            "vision": {
                "state": vision
                if vision in {"active", "standby", "offline"}
                else "offline"
            },
        }
