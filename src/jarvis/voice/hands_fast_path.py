"""Validated zero-extra-planner fast path for obvious single-action voice goals.

The realtime voice model already performed semantic understanding before it invoked
``use_computer``. For a small set of read/reversible local operations it may therefore
supply an optional semantic hint. JARVIS never trusts that hint directly: this module
re-validates the typed parameter contract, canonical USER grounding, entity resolution,
Authority, one-time permit and executor postcondition. Any unsupported or ungrounded hint
falls back to the normal semantic Hands planner before local execution begins.
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

# Realtime providers can express the same bounded scalar using different field names.
# Normalize only known semantic synonyms for known operations; all other keys remain in
# the payload and are rejected by the operation's strict Pydantic contract.
_FAST_PARAMETER_ALIASES: dict[str, dict[str, str]] = {
    "set_master_volume": {
        "level": "percent",
        "percentage": "percent",
        "value": "percent",
        "volume_percent": "percent",
    },
    "set_display_brightness": {
        "level": "percent",
        "percentage": "percent",
        "value": "percent",
        "brightness_percent": "percent",
    },
}


def canonicalize_fast_parameters(
    operation: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    """Canonicalize only operation-bounded provider synonyms, failing on conflicts."""

    aliases = _FAST_PARAMETER_ALIASES.get(str(operation).strip(), {})
    if not aliases:
        return dict(parameters)

    canonical = dict(parameters)
    for alias, target in aliases.items():
        if alias not in canonical:
            continue
        alias_value = canonical.pop(alias)
        if target in canonical and canonical[target] != alias_value:
            raise ValueError(
                f"conflicting fast-path parameters for {target}: {target} and {alias}"
            )
        canonical[target] = alias_value
    return canonical


async def execute_fast_hint(
    orchestrator: VoiceHandsOrchestrator,
    *,
    session_id: str,
    goal: str,
    recent_user_turns: tuple[str, ...],
    operation_hint: str,
    parameters: dict[str, Any],
) -> dict[str, object] | None:
    """Execute one validated fast hint or return ``None`` before any local execution."""

    operation = str(operation_hint).strip()
    if operation not in FAST_PATH_OPERATIONS:
        return None

    latest = str(goal).strip()
    if not latest:
        return None

    try:
        parameter_model = parameter_model_for(operation)
        canonical_parameters = canonicalize_fast_parameters(operation, parameters)
        typed = parameter_model.model_validate(canonical_parameters)
        action = PlannedAction(
            operation=operation,
            parameters=typed.model_dump(exclude_none=True),
            evidence=latest,
        )
        normalized = await asyncio.to_thread(
            orchestrator._normalize_action,
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
        orchestrator._runtime.execute_operation,
        session_id=session_id,
        operation=normalized.operation,
        parameters=normalized.parameters,
        origin=ActionOrigin.DIRECT_USER,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    observation = orchestrator._observation(
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

    success = bool(result.ok and verified)
    reason = result.reason
    if result.ok and not verified and not reason:
        reason = "fast-path execution did not produce a verified postcondition"

    # Once local execution has started, the fast path returns that authoritative result.
    # It never falls through to a second planner-driven execution of the same utterance.
    return {
        "ok": success,
        "status": "succeeded" if success else "failed",
        "goal": latest,
        "completed_steps": 1 if success else 0,
        "failed_operation": None if success else normalized.operation,
        "reason": reason,
        "route_groups": ["voice_fast_path"],
        "results": [orchestrator._result_payload(result)],
        "entity_trace": list(normalized.entity_trace),
        "observations": [observation],
        "completion_mode": "voice_fast_hint",
    }
