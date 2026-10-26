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
_MODEL_TOKEN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,79}$")
_WORK_ID = re.compile(r"^work_[0-9a-f]{16}$")
_FEATURE_NAMES = frozenset({"work", "vision", "memory", "learning", "hands", "research", "personal_context"})
_FEATURE_STATES = frozenset({"ready", "disabled", "unavailable", "degraded"})
_MODEL_ROLES = frozenset({"voice", "research", "work"})
_VISION_TARGET = frozenset({"unknown", "searching", "visible", "following"})
_MILESTONES = frozenset(
    {
        "evidence_gathered", "gathering_evidence", "provider_pressure_before_evidence",
        "queued", "preparing_evidence", "isolated_commit_ready", "diff_verified",
        "tests_passed", "implementation_written", "repository_inspected",
        "workspace_prepared", "preparing_workspace", "advancing_recorded_steps",
        "completed", "failed", "cancelled",
    }
)
_EVENT_AT = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
_EVENT_LABELS = frozenset(
    {"USER TURN", "ASSISTANT REPLY", "WEB RESEARCH", "BROWSER ACTION", "FILE ACTION", "SYSTEM ACTION", "CAPABILITY ACTION"}
)
_EVENT_STATES = frozenset(
    {
        "accepted", "interrupted", "succeeded", "partial", "denied", "invalid",
        "unavailable", "failed", "web_researched", "multi_source_researched",
        "authoritative_source_present", "insufficient_evidence", "research_unavailable",
    }
)


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


def _bounded_work(data: object) -> list[dict[str, object]]:
    if not isinstance(data, (tuple, list)):
        return []
    result: list[dict[str, object]] = []
    for entry in data[:6]:
        work_type = _value(entry, "type")
        state = _value(entry, "state")
        if not isinstance(work_type, str) or not isinstance(state, str):
            continue
        if work_type not in _WORK_TYPES or state not in _WORK_STATES:
            continue
        projected: dict[str, object] = {"type": work_type, "state": state}
        work_id = _value(entry, "id")
        if isinstance(work_id, str) and _WORK_ID.fullmatch(work_id):
            projected["id"] = work_id
        progress = _value(entry, "progress")
        approximate = _value(entry, "approximate")
        if type(progress) is int and 0 <= progress <= 100 and type(approximate) is bool:
            projected["progress"] = progress
            projected["approximate"] = approximate
        milestone = _value(entry, "milestone")
        if isinstance(milestone, str) and milestone in _MILESTONES:
            projected["milestone"] = milestone
        target = _value(entry, "model_target")
        if isinstance(target, str) and _MODEL_TOKEN.fullmatch(target):
            projected["model_target"] = target
        for eta_key in ("eta_low_seconds", "eta_high_seconds"):
            eta = _value(entry, eta_key)
            if type(eta) is int and 0 <= eta <= 604800:
                projected[eta_key] = eta
        result.append(projected)
    return result


def _features(data: object) -> dict[str, str]:
    if not isinstance(data, Mapping):
        return {}
    return {
        name: value
        for name, value in data.items()
        if name in _FEATURE_NAMES and isinstance(value, str) and value in _FEATURE_STATES
    }


def _models(data: object) -> dict[str, dict[str, str]]:
    if not isinstance(data, Mapping):
        return {}
    result: dict[str, dict[str, str]] = {}
    for role in _MODEL_ROLES:
        entry = data.get(role)
        name = _value(entry, "name")
        model = _value(entry, "model")
        if isinstance(name, str) and _MODEL_TOKEN.fullmatch(name):
            item = {"name": name}
            if isinstance(model, str) and _MODEL_TOKEN.fullmatch(model):
                item["model"] = model
            result[role] = item
    return result


def _vision(data: object) -> dict[str, object]:
    state = _value(data, "state")
    result: dict[str, object] = {
        "state": state if isinstance(state, str) and state in {"active", "standby", "offline"} else "offline"
    }
    frame = _value(data, "frame")
    if isinstance(frame, str) and frame in {"fresh", "stale", "pending"}:
        result["frame"] = frame
    if isinstance(frame, str) and frame in {"stale", "pending"}:
        return result
    people = _value(data, "people")
    if type(people) is int and 0 <= people <= 99:
        result["people"] = people
    target = _value(data, "target")
    if isinstance(target, str) and target in _VISION_TARGET:
        result["target"] = target
    return result


def _activity(data: object) -> list[dict[str, object]]:
    if not isinstance(data, (list, tuple)):
        return []
    result = []
    for raw in data[:12]:
        event_id = _value(raw, "id")
        at = _value(raw, "at")
        kind = _value(raw, "kind")
        state = _value(raw, "state")
        label = _value(raw, "label")
        if (
            type(event_id) is int and 0 < event_id <= 2**53
            and isinstance(at, str) and _EVENT_AT.fullmatch(at)
            and isinstance(kind, str) and kind in {"voice", "research", "capability"}
            and isinstance(state, str) and state in _EVENT_STATES
            and isinstance(label, str) and label in _EVENT_LABELS
        ):
            result.append({"id": event_id, "at": at, "kind": kind, "state": state, "label": label})
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
        feature_provider: Callable[[], Any] | None = None,
        model_provider: Callable[[], Any] | None = None,
        activity_provider: Callable[[], Any] | None = None,
    ) -> None:
        self.voice_provider = voice_provider
        self.work_provider = work_provider
        self.health_provider = health_provider
        self.vision_provider = vision_provider
        self.feature_provider = feature_provider
        self.model_provider = model_provider
        self.activity_provider = activity_provider

    def snapshot(self) -> dict[str, object]:
        raw_voice = _read(self.voice_provider)
        state = _value(raw_voice, "state")
        raw_work = _read(self.work_provider)
        raw_health = _read(self.health_provider)
        raw_vision = _read(self.vision_provider)
        raw_features = _read(self.feature_provider)
        raw_models = _read(self.model_provider)
        features = _features(raw_features)
        if self.work_provider is not None and raw_work is None and features.get("work") == "ready":
            features["work"] = "degraded"
        if self.vision_provider is not None and raw_vision is None and features.get("vision") == "ready":
            features["vision"] = "degraded"
        work = _bounded_work(raw_work)
        # Voice can be stopped while other canonical subsystems keep running.
        connected = (isinstance(state, str) and state in _VOICE) or any(
            value is not None
            for value in (raw_work, raw_health, raw_vision, raw_features, raw_models)
        )
        return {
            "schema": 2,
            "connected": connected,
            "voice": {"state": state if isinstance(state, str) and state in _VOICE else "offline"},
            "work": work,
            "health": _rows(
                raw_health,
                size=8,
                fields={"component": None, "state": _HEALTH_STATES},
            ),
            "vision": _vision(raw_vision),
            "features": features,
            "models": _models(raw_models),
            "attention_count": sum(
                1 for item in work if item["state"] == "waiting_for_owner"
            ),
            "activity": _activity(_read(self.activity_provider)),
        }
