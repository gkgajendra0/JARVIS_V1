"""Validated zero-extra-planner fast path for obvious single-action voice goals.

The realtime voice model already performed semantic understanding before it invoked
``use_computer``. For a small set of read/reversible local operations it may therefore
supply an optional semantic hint. JARVIS never trusts that hint directly: this module
re-validates the typed parameter contract, canonical USER grounding, entity resolution,
Authority, one-time permit and executor postcondition. Any unsupported or ungrounded hint
falls back to the normal semantic Hands planner.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from jarvis.authority.types import ActionOrigin
from jarvis.hands.contracts import PlannedAction, parameter_model_for
from jarvis.hands.orchestrator import GroundingContext, HandsOrchestrationError
from jarvis.voice.hands_orchestrator import VoiceHandsOrchestrator

LOGGER = logging.getLogger(__name__)

# Intentionally excludes persistent writes, browser/UI plans, visual Computer Use,
# software mutation, power/session changes, Bluetooth pairing and development mutation.
# Those always retain the full dedicated Hands planning/Authority path.
FAST_PATH_OPERATIONS = frozenset(
    {
        "system_status",
        "list_processes",
        "get_master_volume",
        "set_master_volume",
        "mute_master_volume",
        "unmute_master_volume",
        "get_current_media",
        "play_media",
        "pause_media",
        "toggle_media_playback",
        "next_media",
        "previous_media",
        "stop_media",
        "get_clipboard_text",
        "set_clipboard_text",
        "clear_clipboard",
        "list_windows",
        "focus_window",
        "maximize_window",
        "minimize_window",
        "restore_window",
        "move_window_to_next_monitor",
        "open_app",
        "close_app",
        "file_info",
        "list_directory",
        "list_project_files",
        "read_file",
        "read_document",
        "search_project",
        "list_displays",
        "get_display_brightness",
        "set_display_brightness",
        "list_bluetooth_devices",
        "search_software",
        "list_installed_software",
        "git_status",
        "git_active_branch",
    }
)


async def execute_fast_hint(
    orchestrator: VoiceHandsOrchestrator,
    *,
    session_id: str,
    goal: str,
    recent_user_turns: tuple[str, ...],
    operation_hint: str,
    parameters: dict[str, Any],
) -> dict[str, object] | None:
    """Execute one validated fast hint or return ``None`` for normal planner fallback."""

    operation = str(operation_hint).strip()
    if operation not in FAST_PATH_OPERATIONS:
        return None

    latest = str(goal).strip()
    if not latest:
        return None

    try:
        parameter_model = parameter_model_for(operation)
        typed = parameter_model.model_validate(parameters)
        action = PlannedAction(
            operation=operation,
            parameters=typed.model_dump(exclude_none=True),
            evidence=latest,
        )
        normalized = await asyncio.to_thread(
            orchestrator._normalize_action,  # noqa: SLF001 - intentional friend boundary
            action,
            GroundingContext(latest, recent_user_turns),
        )
    except (HandsOrchestrationError, TypeError, ValueError) as exc:
        LOGGER.info(
            "Hands fast hint rejected before execution | operation=%s | reason=%s",
            operation,
            exc,
        )
        return None

    started = time.perf_counter()
    result = await asyncio.to_thread(
        orchestrator._runtime.execute_operation,  # noqa: SLF001 - same governed runtime
        session_id=session_id,
        operation=normalized.operation,
        parameters=normalized.parameters,
        origin=ActionOrigin.DIRECT_USER,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    observation = orchestrator._observation(  # noqa: SLF001 - canonical observation contract
        normalized,
        result,
        step_number=1,
    )
    verified = bool(observation["verified"])
    LOGGER.info(
        "Hands fast path | operation=%s | status=%s | ok=%s | verified=%s | "
        "execution_ms=%.1f",
        normalized.operation,
        result.status.value,
        result.ok,
        verified,
        elapsed_ms,
    )

    if not result.ok or not verified:
        # The hint never bypasses recovery. A failed or unverified attempt returns to the
        # mature planner, which can re-observe or choose another bounded strategy.
        return None

    return {
        "ok": True,
        "status": "succeeded",
        "goal": latest,
        "completed_steps": 1,
        "route_groups": ["voice_fast_path"],
        "results": [orchestrator._result_payload(result)],  # noqa: SLF001
        "entity_trace": list(normalized.entity_trace),
        "observations": [observation],
        "completion_mode": "voice_fast_hint",
    }
