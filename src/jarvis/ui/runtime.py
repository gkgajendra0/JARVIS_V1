"""Optional presentation bridge with no authority over canonical JARVIS."""

from __future__ import annotations

import logging
import math
import os
import time
from threading import Thread
from typing import Any

from jarvis.ui.hub import UISnapshotHub
from jarvis.ui.server import create_ui_server

LOGGER = logging.getLogger(__name__)
_HANDS_KEYS = frozenset({
    "windows:desktop.control", "visual:desktop.control", "browser:playwright",
    "window:management", "app:lifecycle", "local:files.write",
    "local:documents.edit", "device:bluetooth", "system:display",
    "system:audio", "media:playback", "system:clipboard",
    "software:winget", "development:git",
})


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


def build_runtime_hub(
    runtime: Any, self_awareness: Any | None, *, activity_feed: Any | None = None
) -> UISnapshotHub:
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

    def work() -> list[dict[str, object]]:
        work_runtime = getattr(runtime, "_work_runtime", None)
        if work_runtime is None:
            return []
        from jarvis.work.estimates import estimate_work

        result = []
        for item in work_runtime.store.list_recent(limit=6):
            projected: dict[str, object] = {
                "id": getattr(item, "work_id", None),
                "type": _enum_value(item.work_type),
                "state": _enum_value(item.state),
            }
            try:
                estimate = estimate_work(work_runtime.store, item)
            except Exception:  # noqa: BLE001 - one incomplete Work estimate is not a HUD outage
                LOGGER.debug("HUD work estimate unavailable", exc_info=True)
            else:
                projected.update(
                    progress=estimate.progress_percent,
                    approximate=estimate.progress_is_approximate,
                    milestone=estimate.milestone,
                    eta_low_seconds=estimate.eta_low_seconds,
                    eta_high_seconds=estimate.eta_high_seconds,
                )
            routing_store = getattr(work_runtime, "routing_store", None)
            if routing_store is not None:
                try:
                    decisions = routing_store.list_decisions_for_work(item.work_id, limit=1)
                    if decisions:
                        projected["model_target"] = decisions[0].decision.selected_target_id
                except Exception:  # noqa: BLE001 - optional model routing display
                    LOGGER.debug("HUD routing decision unavailable", exc_info=True)
            result.append(projected)
        return result

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

    def vision() -> dict[str, object]:
        service = getattr(runtime, "vision_service", None)
        status = getattr(getattr(service, "diagnostics", None), "status", None)
        result: dict[str, object] = {
            "state": "active" if service is not None and service.running else "offline"
        }
        if result["state"] == "active" and status is not None:
            captured_at = getattr(status, "captured_at", None)
            if captured_at is None:
                result["frame"] = "pending"
                return result
            if (
                type(captured_at) not in (int, float)
                or not math.isfinite(captured_at)
                or not 0 <= time.monotonic() - captured_at <= 5
            ):
                result["frame"] = "stale"
                return result
            result["frame"] = "fresh"
            result["people"] = getattr(status, "visible_people", None)
            if getattr(status, "target_id", None) is None:
                result["target"] = "searching"
            elif bool(getattr(status, "target_visible", False)):
                # An armed camera target is not trusted OWNER native LOCKED evidence.
                result["target"] = "following" if getattr(status, "armed", False) else "visible"
            else:
                result["target"] = "searching"
        return result

    def features() -> dict[str, str]:
        config = getattr(runtime, "config", None)
        work_ready = getattr(runtime, "_work_runtime", None) is not None
        memory_ready = getattr(runtime, "_memory_runtime", None) is not None
        context_mode = getattr(config, "personal_context_mode", "off")
        learning_mode = getattr(config, "personal_learning_mode", "off")
        vision_present = getattr(runtime, "vision_service", None) is not None
        hands_ready = False
        capability_runtime = getattr(runtime, "_capability_runtime", None)
        if capability_runtime is not None:
            try:
                hands_ready = any(
                    getattr(descriptor, "key", None) in _HANDS_KEYS
                    and getattr(descriptor, "execution_enabled", False) is True
                    for descriptor in capability_runtime.catalog.capabilities
                )
            except Exception:  # noqa: BLE001 - capability discovery may be transient
                hands_ready = False
        return {
            "work": "ready" if work_ready else "disabled",
            "vision": "ready" if vision_present else "disabled",
            "memory": "ready" if memory_ready else "disabled",
            "personal_context": (
                "ready" if context_mode == "apply" and memory_ready else
                "unavailable" if context_mode == "apply" else "disabled"
            ),
            "learning": (
                "ready" if learning_mode == "apply" and memory_ready else
                "unavailable" if learning_mode == "apply" else "disabled"
            ),
            "research": "ready" if getattr(runtime, "_research_service", None) is not None else "unavailable",
            "hands": "ready" if hands_ready else "unavailable",
        }

    def models() -> dict[str, dict[str, str]]:
        config = getattr(runtime, "config", None)
        if config is None:
            return {}
        provider = getattr(config, "ai_provider", "")
        realtime_model = (
            getattr(config, "gemini_realtime_model", "")
            if provider == "gemini" else getattr(config, "realtime_model", "")
        )
        result = {"voice": {"name": provider, "model": realtime_model}}
        research = getattr(runtime, "_research_service", None)
        if research is not None:
            result["research"] = {
                "name": getattr(research, "provider_name", ""),
                "model": getattr(research, "model_name", ""),
            }
        if getattr(runtime, "_work_runtime", None) is not None:
            result["work"] = {
                "name": "chatgpt_plan" if getattr(config, "chatgpt_plan_enabled", False) else provider,
                "model": (
                    getattr(config, "chatgpt_plan_model", "")
                    if getattr(config, "chatgpt_plan_enabled", False)
                    else getattr(config, "work_orchestration_model", "")
                ),
            }
        return result

    return UISnapshotHub(
        voice_provider=voice,
        work_provider=work,
        health_provider=health,
        vision_provider=vision,
        feature_provider=features,
        model_provider=models,
        activity_provider=(None if activity_feed is None else activity_feed.snapshot),
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
        service = UIService(
            build_runtime_hub(
                runtime,
                self_awareness,
                activity_feed=getattr(runtime, "_hud_activity_feed", None),
            ),
            port=port,
        )
    except Exception as exc:  # noqa: BLE001 - optional UI must never fail voice
        LOGGER.warning(
            "Optional JARVIS HUD unavailable (%s); voice continues", type(exc).__name__
        )
        return None
    LOGGER.info(
        "JARVIS local read-only HUD available at http://127.0.0.1:%s", service.port
    )
    return service
