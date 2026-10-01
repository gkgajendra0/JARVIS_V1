"""Structured, secret-safe acceptance telemetry for GICC."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Protocol

from jarvis.observability.redaction import redact_data

LOGGER = logging.getLogger("jarvis.gicc.telemetry")

GICC_EVENTS = frozenset(
    {
        "gicc_goal_admitted",
        "gicc_entity_resolved",
        "gicc_information_need_created",
        "gicc_information_need_resolved",
        "gicc_requirement_graph_created",
        "gicc_capability_gap_created",
        "gicc_phase9_linked",
        "gicc_plan_created",
        "gicc_plan_node_dispatched",
        "gicc_postcondition_verified",
        "gicc_replan",
        "gicc_monitor_triggered",
        "gicc_goal_completed",
    }
)

_SENSITIVE_FIELD = re.compile(
    r"(?i)(?:^|_)(?:"
    r"utterance|text|prompt|password|passwd|secret|token|api_key|"
    r"authorization|credential|pin|otp|parameters|payload|data|"
    r"owner_request|exact_owner_request|raw_request"
    r")(?:$|_)"
)
_SAFE_FIELD = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


class GiccTelemetrySink(Protocol):
    def emit(self, event: str, **fields: object) -> None: ...


def _safe_scalar(value: object) -> str | int | float | bool | None:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        redacted = redact_data(value)
        assert isinstance(redacted, str)
        return redacted[:400]
    raise TypeError("GICC telemetry values must be scalar or sequences of strings")


def _safe_value(value: object) -> object:
    if isinstance(value, Mapping):
        raise TypeError("nested mappings are not allowed in GICC telemetry")
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return [_safe_scalar(item) for item in value]
    return _safe_scalar(value)


class GiccTelemetry:
    """Emit a bounded JSON event line suitable for dev acceptance evidence."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or LOGGER

    def emit(self, event: str, **fields: object) -> None:
        event_name = str(event).strip().casefold()
        if event_name not in GICC_EVENTS:
            raise ValueError(f"unsupported GICC telemetry event: {event_name}")
        normalized: dict[str, object] = {"event": event_name}
        for raw_key, value in sorted(fields.items()):
            key = str(raw_key).strip().casefold()
            if _SAFE_FIELD.fullmatch(key) is None:
                raise ValueError(f"invalid GICC telemetry field: {raw_key!r}")
            if _SENSITIVE_FIELD.search(key):
                raise ValueError(
                    f"sensitive/raw-content field is forbidden in GICC telemetry: {key}"
                )
            normalized[key] = _safe_value(value)
        self._logger.info(
            "GICC_EVENT %s",
            json.dumps(
                normalized,
                sort_keys=True,
                ensure_ascii=True,
                separators=(",", ":"),
            ),
        )


class CapturingGiccTelemetry:
    """Tiny test sink that exercises the same event/field policy."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self._validator = GiccTelemetry(logging.getLogger("jarvis.gicc.telemetry.test"))

    def emit(self, event: str, **fields: object) -> None:
        event_name = str(event).strip().casefold()
        if event_name not in GICC_EVENTS:
            raise ValueError(f"unsupported GICC telemetry event: {event_name}")
        normalized: dict[str, object] = {"event": event_name}
        for raw_key, value in sorted(fields.items()):
            key = str(raw_key).strip().casefold()
            if _SAFE_FIELD.fullmatch(key) is None:
                raise ValueError(f"invalid GICC telemetry field: {raw_key!r}")
            if _SENSITIVE_FIELD.search(key):
                raise ValueError(
                    f"sensitive/raw-content field is forbidden in GICC telemetry: {key}"
                )
            normalized[key] = _safe_value(value)
        self.events.append(normalized)


DEFAULT_GICC_TELEMETRY = GiccTelemetry()
