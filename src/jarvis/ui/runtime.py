"""Optional in-process JARVIS UI adapter for the normal voice runtime.

Opt-in only; failure never prevents voice or durable Work operation. The UI
remains a read-only projection, not a second authority or session store.
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING

from jarvis.ui.hub import UIEventHub, VOICE_STATES
from jarvis.ui.server import create_ui_server

if TYPE_CHECKING:
    from jarvis.conversation import ConversationTurn
    from jarvis.work.runtime import WorkRuntime

LOGGER = logging.getLogger(__name__)
_active: UIService | None = None


@dataclass(slots=True)
class UIService:
    hub: UIEventHub
    server: ThreadingHTTPServer
    thread: threading.Thread

    def close(self) -> None:
        self.hub.set_runtime_connected(False)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3.0)


def active_ui_hub() -> UIEventHub | None:
    return None if _active is None else _active.hub


def start_opt_in_ui() -> UIService | None:
    """Start only for explicit local environment opt-in, not by import."""
    global _active
    value = os.environ.get("JARVIS_UI_ENABLED", "").strip().casefold()
    if value not in {"1", "true", "yes", "on"}:
        return None
    if _active is not None:
        return _active
    raw_port = os.environ.get("JARVIS_UI_PORT", "8765")
    try:
        port = int(raw_port)
        hub = UIEventHub()
        server = create_ui_server(hub, port=port)
        thread = threading.Thread(
            target=server.serve_forever,
            name="jarvis-ui-loopback",
            daemon=True,
            kwargs={"poll_interval": 0.25},
        )
        thread.start()
        hub.set_runtime_connected(True)
        _active = UIService(hub=hub, server=server, thread=thread)
        LOGGER.info(
            "Opt-in JARVIS UI active at http://127.0.0.1:%s/ (read-only)",
            server.server_port,
        )
        return _active
    except (OSError, ValueError) as exc:
        LOGGER.warning(
            "Optional UI unavailable, voice will continue: %s", type(exc).__name__
        )
        return None


def stop_opt_in_ui() -> None:
    global _active
    service = _active
    _active = None
    if service is not None:
        service.close()


def attach_work_projection(runtime: WorkRuntime | None) -> None:
    hub = active_ui_hub()
    if hub is None or runtime is None:
        return

    def public_work() -> list[dict[str, str]]:
        # No work.request, steps, customer details, credentials or payloads.
        return [
            {
                "id": item.work_id,
                "kind": item.work_type.value,
                "state": item.state.value,
            }
            for item in runtime.store.list_recent(limit=8)
        ]

    hub.attach_work_provider(public_work)


def observe_accepted_turn(turn: ConversationTurn) -> None:
    hub = active_ui_hub()
    if hub is None:
        return
    from jarvis.conversation import ConversationRole

    if turn.role is not ConversationRole.USER:
        return
    try:
        hub.observe_accepted_user_text(turn.text)
    except (ValueError, TypeError):
        # UI topic hints are optional, not a reason to reject a canonical turn.
        pass


def observe_agent_state(event: object) -> None:
    hub = active_ui_hub()
    if hub is None:
        return
    state = str(getattr(event, "new_state", "")).strip().casefold()
    if state in VOICE_STATES:
        hub.set_voice_state(state)


def observe_session_close() -> None:
    hub = active_ui_hub()
    if hub is not None:
        hub.set_voice_state("idle")


def safely_attach_voice_observers(
    session: object,
    add_turn_observer: Callable[[Callable[[ConversationTurn], None]], None],
    add_close_observer: Callable[[Callable[[], None]], None],
) -> None:
    hub = active_ui_hub()
    if hub is None:
        return
    hub.set_voice_state("activating")
    try:
        session.on("agent_state_changed", observe_agent_state)
        add_turn_observer(observe_accepted_turn)
        add_close_observer(observe_session_close)
    except Exception:
        LOGGER.exception("Optional UI observer not attached; voice remains active")
