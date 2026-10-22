"""Bounded, thread-safe, non-authoritative UI state projection.

This module never executes a capability, queries a model, or grants permission.
Only confirmed runtime adapters may publish operational context. Browser state
is entirely a disposable projection of the canonical JARVIS subsystems.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any

VOICE_STATES = frozenset(
    {"offline", "idle", "activating", "listening", "thinking", "speaking", "error"}
)
PANEL_TYPES = frozenset(
    {"work", "research", "document", "vision", "system", "alert", "info"}
)
VALID_SOURCES = frozenset({"runtime", "canonical_work", "health", "local_ui"})
_TOPIC_MATCHES = (
    ("vision", ("camera", "webcam", "pocket 3", "lens", "what do you see")),
    ("work", ("background work", "running task", "task progress", "project work")),
    ("research", ("research", "search the web", "latest news", "sources")),
    ("document", ("document", "pdf", "project file", "repository", "code")),
    ("system", ("system status", "health", "diagnostic", "cpu", "gpu")),
)
_EXPLICIT = re.compile(r"\b(show|display|open|bring up|pull up)\b", re.IGNORECASE)


def _short_text(value: object, *, maximum: int = 200) -> str:
    if not isinstance(value, str):
        raise TypeError("UI text must be a string")
    text = "".join(ch for ch in value.strip() if ch >= " " and ch != "\x7f")
    if len(text) > maximum:
        raise ValueError("UI text exceeds bounded projection limit")
    return text


class UIEventHub:
    """In-memory presentation state, never canonical memory or a secret store."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        event_limit: int = 100,
    ) -> None:
        if event_limit < 4 or event_limit > 1000:
            raise ValueError("event_limit must be between 4 and 1000")
        self._lock = threading.RLock()
        self._clock = clock
        self._events: deque[dict[str, Any]] = deque(maxlen=event_limit)
        self._sequence = 0
        self._voice_state = "offline"
        self._runtime_connected = False
        self._panels: dict[str, dict[str, Any]] = {}
        self._work_provider: Callable[[], list[dict[str, str]]] | None = None

    def attach_work_provider(
        self, provider: Callable[[], list[dict[str, str]]]
    ) -> None:
        if not callable(provider):
            raise TypeError("work provider must be callable")
        with self._lock:
            self._work_provider = provider

    def _record(self, event_type: str, detail: dict[str, Any]) -> None:
        self._sequence += 1
        self._events.append(
            {"seq": self._sequence, "type": event_type, "at": self._clock(), **detail}
        )

    def set_runtime_connected(self, connected: bool) -> None:
        if not isinstance(connected, bool):
            raise TypeError("runtime connection must be boolean")
        with self._lock:
            self._runtime_connected = connected
            self._voice_state = "idle" if connected else "offline"
            self._record("runtime.connection", {"connected": connected})

    def set_voice_state(self, state: str) -> None:
        normalized = _short_text(state, maximum=32).casefold()
        if normalized not in VOICE_STATES:
            raise ValueError("unknown voice state")
        with self._lock:
            if not self._runtime_connected:
                return
            if normalized == self._voice_state:
                return
            self._voice_state = normalized
            self._record("voice.state", {"state": normalized})

    def show_panel(
        self,
        *,
        panel_id: str,
        panel_type: str,
        title: str,
        summary: str,
        source: str = "runtime",
        priority: int = 1,
        ttl_seconds: float = 180.0,
    ) -> None:
        identity = _short_text(panel_id, maximum=64)
        kind = _short_text(panel_type, maximum=24).casefold()
        origin = _short_text(source, maximum=24).casefold()
        if not re.fullmatch(r"[a-zA-Z0-9_.:-]+", identity):
            raise ValueError("panel id must be a bounded opaque token")
        if kind not in PANEL_TYPES or origin not in VALID_SOURCES:
            raise ValueError("unsupported UI panel type/source")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise TypeError("priority must be an integer")
        if not 0 <= priority <= 3:
            raise ValueError("priority out of range")
        if (
            not isinstance(ttl_seconds, (float, int))
            or isinstance(ttl_seconds, bool)
            or not 1 <= ttl_seconds <= 3600
        ):
            raise ValueError("panel TTL out of range")
        now = self._clock()
        with self._lock:
            self._panels[identity] = {
                "id": identity,
                "type": kind,
                "title": _short_text(title, maximum=100),
                "summary": _short_text(summary, maximum=500),
                "source": origin,
                "priority": priority,
                "observed_at": now,
                "expires_at": now + ttl_seconds,
            }
            self._record("panel.show", {"id": identity, "panel_type": kind})

    def dismiss_panel(self, panel_id: str) -> None:
        with self._lock:
            if self._panels.pop(panel_id, None) is not None:
                self._record("panel.dismiss", {"id": panel_id})

    def observe_accepted_user_text(self, text: str) -> None:
        """Show only bounded topical hints, never expose or store transcript text.

        In particular a spoken request for memories, camera or private files does
        NOT release that content; the real governed tool must supply authorized data.
        """
        normalized = _short_text(text, maximum=8000).casefold()
        for kind, phrases in _TOPIC_MATCHES:
            if any(phrase in normalized for phrase in phrases):
                explicit = bool(_EXPLICIT.search(normalized))
                self.show_panel(
                    panel_id=f"topic.{kind}",
                    panel_type=kind,
                    title={
                        "work": "Background work",
                        "research": "Research context",
                        "document": "Project and documents",
                        "vision": "Vision",
                        "system": "System health",
                    }[kind],
                    summary=(
                        "Relevant topic detected. Open a grounded source to see details; "
                        "the visual layer does not invent results or bypass permissions."
                    ),
                    source="runtime",
                    priority=2 if explicit else 1,
                    ttl_seconds=150,
                )
                break

    def snapshot(self) -> dict[str, Any]:
        """Copy data without holding the lock while querying canonical Work."""
        with self._lock:
            now = self._clock()
            for key in tuple(self._panels):
                if self._panels[key]["expires_at"] <= now:
                    del self._panels[key]
            panels = [dict(panel) for panel in self._panels.values()]
            panels.sort(key=lambda p: (-p["priority"], -p["observed_at"]))
            connected = self._runtime_connected
            voice_state = self._voice_state
            sequence = self._sequence
            provider = self._work_provider
        work: list[dict[str, str]] = []
        if connected and provider is not None:
            try:
                candidate = provider()
                if isinstance(candidate, list):
                    work = [
                        {
                            "id": _short_text(row["id"], maximum=80),
                            "kind": _short_text(row["kind"], maximum=50),
                            "state": _short_text(row["state"], maximum=50),
                        }
                        for row in candidate[:8]
                    ]
            except (KeyError, TypeError, ValueError):
                work = []
            except Exception:  # noqa: BLE001 - UI must not break live Work
                # UI telemetry must not be able to bring down the voice runtime.
                work = []
        return {
            "schema": 1,
            "seq": sequence,
            "runtime_connected": connected,
            "voice_state": voice_state,
            "panels": panels[:16],
            "work": work,
            "server_time": self._clock(),
        }

    def events_after(self, after: int) -> dict[str, Any]:
        if isinstance(after, bool) or not isinstance(after, int) or after < 0:
            raise ValueError("after must be a non-negative integer")
        with self._lock:
            return {
                "seq": self._sequence,
                "events": [
                    dict(event) for event in self._events if event["seq"] > after
                ],
                "requires_snapshot": bool(
                    self._events and after < self._events[0]["seq"] - 1
                ),
            }
