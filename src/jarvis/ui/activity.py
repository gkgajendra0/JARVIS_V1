"""Thread-safe, bounded presentation events; never retain content from tool outputs.

This is an ephemeral projection, not conversation, authority or audit truth.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from threading import RLock


_CAPABILITY_STATUSES = frozenset(
    {"succeeded", "partial", "denied", "invalid", "unavailable", "failed"}
)
_RESEARCH_STATUSES = frozenset(
    {
        "web_researched", "multi_source_researched", "authoritative_source_present",
        "insufficient_evidence", "research_unavailable",
    }
)


def _name(raw: object) -> str:
    value = getattr(raw, "value", raw)
    return value if isinstance(value, str) else ""


class HUDActivityFeed:
    """Only fixed category/state labels; no arbitrary user or provider text."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._sequence = 0
        self._events: deque[dict[str, object]] = deque(maxlen=16)

    def _record(self, kind: str, state: str, label: str) -> None:
        with self._lock:
            self._sequence += 1
            self._events.appendleft(
                {
                    "id": self._sequence,
                    "at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "kind": kind,
                    "state": state,
                    "label": label,
                }
            )

    def observe_turn(self, turn: object) -> None:
        role = _name(getattr(turn, "role", None))
        if role == "user":
            self._record("voice", "accepted", "USER TURN")
        elif role == "assistant":
            interrupted = getattr(turn, "interrupted", False) is True
            self._record(
                "voice",
                "interrupted" if interrupted else "accepted",
                "ASSISTANT REPLY",
            )

    def record_research(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        status = payload.get("status")
        if isinstance(status, str) and status in _RESEARCH_STATUSES:
            self._record("research", status, "WEB RESEARCH")

    def record_capability(self, result: object) -> None:
        status = _name(getattr(result, "status", None))
        if status not in _CAPABILITY_STATUSES:
            return
        key = getattr(result, "capability_key", None)
        if not isinstance(key, str):
            return
        if key.startswith("browser:"):
            label = "BROWSER ACTION"
        elif key.startswith(("local:files", "local:documents")):
            label = "FILE ACTION"
        elif key.startswith(("system:", "device:", "window:", "app:", "media:")):
            label = "SYSTEM ACTION"
        else:
            label = "CAPABILITY ACTION"
        self._record("capability", status, label)

    def snapshot(self) -> list[dict[str, object]]:
        with self._lock:
            return [dict(item) for item in list(self._events)[:12]]
