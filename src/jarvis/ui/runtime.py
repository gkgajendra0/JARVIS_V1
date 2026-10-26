"""Optional presentation bridge with no authority over canonical JARVIS."""

from __future__ import annotations

import logging
import os
from threading import Thread
from typing import Any

from jarvis.ui.hub import UISnapshotHub
from jarvis.ui.server import create_ui_server

LOGGER = logging.getLogger(__name__)


def _enum_value(raw: object) -> str:
    value = getattr(raw, "value", raw)
    return value if isinstance(value, str) else ""


def project_voice_state(
    state: object, agent_state: object = "", user_is_speaking: bool = False
) -> str:
    """Map the existing LiveKit lifecycle to visuals, never infer fake audio."""
    lifecycle = _enum_value(state)
    if lifecycle == "idle":
        return "standby"
    if lifecycle == "activating":
        return "activating"
    if lifecycle == "recovering":
        return "recovering"
    if lifecycle == "active":
        if _enum_value(agent_state) == "speaking":
            return "speaking"
        if _enum_value(agent_state) == "thinking":
            return "thinking"
        if _enum_value(agent_state) == "listening" or user_is_speaking:
            return "listening"
        return "activating"
    return "offline"


def build_runtime_hub(runtime: Any, self_awareness: Any | None) -> UISnapshotHub:
    """Read small already-canonical records without opening new subscriptions."""

    def voice() -> dict[str, str]:
        explicit = getattr(runtime, "presentation_voice_state", None)
        state = (
            explicit
            if isinstance(explicit, str)
            else project_voice_state(
                runtime.state,
                getattr(runtime, "_agent_state", ""),
                bool(getattr(runtime, "_user_is_speaking", False)),
            )
        )
        return {"state": state}

    def work() -> list[dict[str, str]]:
        work_runtime = getattr(runtime, "_work_runtime", None)
        if work_runtime is None:
            return []
        return [
            {"type": _enum_value(item.work_type), "state": _enum_value(item.state)}
            for item in work_runtime.store.list_recent(limit=6)
        ]

    def health() -> list[dict[str, str]]:
        if self_awareness is None:
            return []
        return [
            {
                "component": item.descriptor.component_id,
                "state": _enum_value(item.health.state),
            }
            for item in self_awareness.system_snapshot(health_surface_only=True)[:8]
        ]

    def vision() -> dict[str, str]:
        service = runtime.vision_service
        return {
            "state": "active" if service is not None and service.running else "offline"
        }

    return UISnapshotHub(
        voice_provider=voice,
        work_provider=work,
        health_provider=health,
        vision_provider=vision,
    )


class UIService:
    """Daemon server that can be stopped independently from voice shutdown."""

    def __init__(self, hub: UISnapshotHub, *, port: int = 8765) -> None:
        self.server = create_ui_server(hub, port=port)
        self.thread = Thread(
            target=self.server.serve_forever,
            daemon=True,
            name="jarvis-ui-readonly",
        )
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server.server_port

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


def start_ui_if_enabled(runtime: Any, self_awareness: Any | None) -> UIService | None:
    """Never turn an optional display failure into a voice startup failure."""
    if os.getenv("JARVIS_UI_ENABLED", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return None
    try:
        port = int(os.getenv("JARVIS_UI_PORT", "8765"))
        if not 1024 <= port <= 65535:
            raise ValueError("invalid port")
        service = UIService(build_runtime_hub(runtime, self_awareness), port=port)
    except Exception as exc:  # noqa: BLE001 - optional UI must never fail voice
        LOGGER.warning(
            "Optional JARVIS HUD unavailable (%s); voice continues", type(exc).__name__
        )
        return None
    LOGGER.info(
        "JARVIS local read-only HUD available at http://127.0.0.1:%s", service.port
    )
    return service
