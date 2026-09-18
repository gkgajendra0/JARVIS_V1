"""Stable operational event envelope for logs and incident evidence."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from jarvis.observability.context import current_correlation
from jarvis.observability.redaction import redact_data


@dataclass(frozen=True, slots=True)
class OperationalEvent:
    event_id: str
    event_name: str
    occurred_at_epoch: float
    component_id: str
    severity: str
    reason_code: str | None
    result_state: str | None
    elapsed_ms: float | None
    correlation_json: str
    attributes_json: str

    @classmethod
    def create(
        cls,
        *,
        event_name: str,
        component_id: str,
        severity: str = "info",
        reason_code: str | None = None,
        result_state: str | None = None,
        elapsed_ms: float | None = None,
        attributes: dict[str, Any] | None = None,
        occurred_at_epoch: float | None = None,
    ) -> "OperationalEvent":
        if not str(event_name).strip():
            raise ValueError("event_name must not be empty")
        if not str(component_id).strip():
            raise ValueError("component_id must not be empty")
        if elapsed_ms is not None and elapsed_ms < 0:
            raise ValueError("elapsed_ms must not be negative")
        return cls(
            event_id=str(uuid.uuid4()),
            event_name=str(event_name).strip().lower(),
            occurred_at_epoch=(
                time.time() if occurred_at_epoch is None else occurred_at_epoch
            ),
            component_id=str(component_id).strip().lower(),
            severity=str(severity).strip().lower(),
            reason_code=(
                str(reason_code).strip().lower() if reason_code is not None else None
            ),
            result_state=(
                str(result_state).strip().lower() if result_state is not None else None
            ),
            elapsed_ms=elapsed_ms,
            correlation_json=json.dumps(
                current_correlation().as_dict(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
            attributes_json=json.dumps(
                redact_data(attributes or {}),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                default=str,
            ),
        )
