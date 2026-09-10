"""Voice-specific grounding policy for natural multilingual JARVIS Hands requests.

The core Hands orchestrator remains deliberately strict for programmatic callers. Voice
transcripts add one extra problem: a speech provider may render an English loanword in
another script (for example ``thirty`` as Devanagari/Urdu phonetics). For reversible
local controls, the structured planner's bounded typed value is therefore accepted as a
semantic normalization only after the action is tied to the current canonical USER turn.
Persistent, destructive, external-send, software-install, power and development mutation
operations retain the core orchestrator's literal material grounding unchanged.
"""

from __future__ import annotations

from dataclasses import replace

from jarvis.hands.contracts import PlannedAction
from jarvis.hands.orchestrator import (
    GroundingContext,
    HandsOrchestrationError,
    HandsOrchestrator,
)

# These operations are local reads or reversible local interactions. Relaxing only the
# free-form planner evidence quote avoids brittle failures when a multilingual model
# copies/transliterates that quote differently. Target/material fields are still checked
# by the core orchestrator and canonical entity resolver.
_SEMANTIC_EVIDENCE_OPERATIONS = frozenset(
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
        "list_windows",
        "focus_window",
        "maximize_window",
        "minimize_window",
        "restore_window",
        "move_window_to_next_monitor",
        "open_app",
        "close_app",
        "execute_windows_plan",
        "execute_visual_desktop_task",
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

# For these bounded reversible controls, the planner schema itself constrains the value.
# If the speech transcript spelled the spoken number in another script, append the typed
# value only to the *grounding view* of the current utterance. This does not alter the
# canonical transcript and does not apply to persistent/high-consequence operations.
_SEMANTIC_NUMERIC_FIELDS = {
    "set_master_volume": "percent",
    "set_display_brightness": "percent",
}


class VoiceHandsOrchestrator(HandsOrchestrator):
    """Hands orchestrator with risk-aware normalization for realtime speech transcripts."""

    def _normalize_action(
        self,
        action: PlannedAction,
        context: GroundingContext,
    ):
        normalized_action = action
        if action.operation in _SEMANTIC_EVIDENCE_OPERATIONS:
            normalized_action = replace(action, evidence=context.latest_user_text)

        try:
            return super()._normalize_action(normalized_action, context)
        except HandsOrchestrationError as exc:
            field = _SEMANTIC_NUMERIC_FIELDS.get(action.operation)
            if field is None or "percentage is not grounded" not in str(exc):
                raise
            value = action.parameters.get(field)
            if value is None:
                raise
            semantic_context = GroundingContext(
                latest_user_text=f"{context.latest_user_text} {value}",
                recent_user_texts=context.recent_user_texts,
            )
            return super()._normalize_action(normalized_action, semantic_context)
