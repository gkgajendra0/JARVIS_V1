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

from jarvis.machine_config import configured_text, load_machine_settings
from jarvis.ui.hub import VOICE_STATES, UIEventHub
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
    """Start only for explicit saved or environment opt-in, not by import."""
    global _active
    value = (
        str(configured_text("JARVIS_UI_ENABLED", load_machine_settings(), "false"))
        .strip()
        .casefold()
    )
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


def attach_diagnostics_projection(
    *, vision_service: object | None, self_awareness: object | None
) -> None:
    """Read only documented diagnostics, with no camera frames/face identities."""
    hub = active_ui_hub()
    if hub is None:
        return
    if vision_service is not None:

        def vision_status() -> dict[str, object]:
            report = vision_service.report(event_limit=1)
            camera = report.get("camera", {})
            if not isinstance(camera, dict):
                camera = {}
            return {
                "running": vision_service.running,
                "active_source": camera.get("active_source"),
                "available_sources": camera.get("available_sources", []),
            }

        hub.attach_vision_provider(vision_status)
    if self_awareness is not None:

        def health_status() -> list[dict[str, str]]:
            snapshots = self_awareness.system_snapshot(health_surface_only=True)
            return [
                {
                    "component": snap.descriptor.component_id,
                    "state": snap.health.state.value,
                }
                for snap in snapshots
            ]

        hub.attach_health_provider(health_status)


def observe_provider_issue(failure: object) -> None:
    """Provider health warning from the existing resilience diagnosis only."""
    hub = active_ui_hub()
    if hub is None:
        return
    kind = getattr(getattr(failure, "kind", None), "value", "")
    if not isinstance(kind, str) or kind not in {
        "quota_exhausted",
        "rate_limited",
        "authentication_failed",
        "permission_denied",
        "model_unavailable",
        "transient_unavailable",
        "unknown",
    }:
        kind = "unavailable"
    hub.show_panel(
        panel_id="provider.latest",
        panel_type="alert",
        title="AI service attention",
        summary=f"Existing provider monitor reported: {kind}. No credentials are displayed.",
        source="health",
        priority=3,
        ttl_seconds=300,
    )


def observe_capability_result(result: object) -> None:
    """Show only capability class/status; never action arguments or output."""
    hub = active_ui_hub()
    if hub is None:
        return
    raw_status = getattr(getattr(result, "status", None), "value", "")
    if raw_status not in {"succeeded", "partial", "failed", "denied", "invalid"}:
        return
    key = getattr(result, "capability_key", "")
    domain = key.split(":", 1)[0] if isinstance(key, str) else "capability"
    if domain not in {
        "windows",
        "browser",
        "files",
        "visual",
        "device",
        "memory",
        "self_awareness",
        "system",
        "local",
    }:
        domain = "capability"
    try:
        hub.show_panel(
            panel_id="action.latest",
            panel_type="alert" if raw_status in {"failed", "denied"} else "info",
            title="Recent Jarvis action",
            summary=(
                f"Governed {domain} operation completed: {raw_status}. "
                "Action arguments, output and private details are not shown."
            ),
            source="runtime",
            priority=2 if raw_status in {"failed", "denied"} else 1,
            ttl_seconds=120,
        )
    except (TypeError, ValueError):
        pass


def observe_research_result(payload: dict[str, object]) -> None:
    hub = active_ui_hub()
    if hub is None:
        return
    try:
        hub.show_research_result(payload)
    except (TypeError, ValueError):
        LOGGER.debug("Research data not eligible for local UI projection")


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


def observe_user_state(event: object) -> None:
    hub = active_ui_hub()
    if hub is None:
        return
    state = str(getattr(event, "new_state", "")).strip().casefold()
    if state == "speaking":
        # "listening" means JARVIS hears incoming speech; do not capture PCM.
        hub.set_voice_state("listening")


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
        session.on("user_state_changed", observe_user_state)
        add_turn_observer(observe_accepted_turn)
        add_close_observer(observe_session_close)
    except Exception:
        LOGGER.exception("Optional UI observer not attached; voice remains active")
