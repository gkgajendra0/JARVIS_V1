"""Latency-optimized voice tool surface for governed JARVIS Hands.

The realtime model has already semantically understood the user's utterance before it
calls ``use_computer``. This tool surface makes that routing decision explicit instead
of optional: every call must choose either one approved single-action fast operation or
``planner`` for the full Hands orchestrator. The selected hint is still only a hint;
JARVIS re-validates the canonical transcript, typed parameters, grounding, Authority,
permit and postcondition before any local execution begins.
"""

from __future__ import annotations

from typing import Literal

from livekit.agents import RunContext, function_tool
from livekit.agents.llm import ToolError

from jarvis.hands.orchestrator import HandsOrchestrationError, HandsOrchestrator
from jarvis.hands.planner import HandsPlanningError
from jarvis.voice.hands_goal_tools import HandsGoalAgentTools, _compact_voice_result
from jarvis.voice.hands_orchestrator import VoiceHandsOrchestrator
from jarvis.voice.hands_transaction import (
    LeaseAwareCapabilityRuntime,
    LeaseAwareHandsPlanner,
)

FastHandsMode = Literal[
    "planner",
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
    "list_displays",
    "get_display_brightness",
    "set_display_brightness",
    "list_bluetooth_devices",
    "search_software",
    "list_installed_software",
    "git_status",
    "git_active_branch",
]


class LatencyOptimizedVoiceHandsOrchestrator(VoiceHandsOrchestrator):
    """Voice orchestrator with deterministic completion for full-goal visual work."""

    @staticmethod
    def _verified_terminal(operation: str, selected: tuple[str, ...]) -> bool:
        # execute_visual_desktop_task always receives the complete canonical USER task,
        # not a planner-created subtask. If its window-scoped Computer Use loop returns
        # a verified success, asking the planner to confirm completion is redundant.
        if operation == "execute_visual_desktop_task":
            return True
        return VoiceHandsOrchestrator._verified_terminal(operation, selected)


class LatencyOptimizedHandsGoalAgentTools(HandsGoalAgentTools):
    """Expose one governed Hands tool with an explicit fast/planner mode decision."""

    def _build_orchestrator(self, is_current) -> HandsOrchestrator:
        if self._orchestrator is not None:
            return self._orchestrator
        planner = self._runtime.hands_planner
        if planner is None:
            raise HandsOrchestrationError(
                "JARVIS Hands semantic planner is not configured"
            )
        return LatencyOptimizedVoiceHandsOrchestrator(
            LeaseAwareCapabilityRuntime(self._runtime, is_current),
            LeaseAwareHandsPlanner(planner, is_current),
        )

    @function_tool()
    async def use_computer(
        self,
        context: RunContext,
        operation_hint: FastHandsMode,
        parameters_json: str,
    ) -> dict[str, object]:
        """Operate or inspect the local computer through governed JARVIS Hands.

        ``operation_hint`` is REQUIRED on every call. Choose the exact approved fast
        operation when the USER's ENTIRE request is one obvious simple local read or
        reversible action. Examples: ``get_master_volume``, ``set_master_volume``,
        ``pause_media``, ``open_app``, ``focus_window`` or ``set_display_brightness``.
        For those fast operations, ``parameters_json`` must be one JSON object containing
        only values explicitly stated in the current USER utterance; use ``{}`` when the
        operation takes no parameters.

        Choose ``planner`` with ``parameters_json='{}'`` for every multi-step request,
        any task inside application content/UI, browser work, file/document writes,
        visual Computer Use, installs/uninstalls, power/session changes, Bluetooth
        pairing, Git mutations, or whenever one single fast operation would not fully
        satisfy the whole USER request. Never use an empty operation hint and never split
        one multi-step USER goal into repeated calls.

        Fast mode does NOT bypass safety. JARVIS independently re-validates the typed
        contract, canonical USER transcript, entity resolution, grounding, Authority,
        one-time permit and execution postcondition. If a fast hint is not grounded, it
        falls back before execution to the full planner. Once any local action starts,
        the request is never replayed through fallback.

        Desktop app/window/screen inspection belongs here, not to Pocket3 physical-camera
        vision. If status is ``superseded``, continue with the newer USER request rather
        than reporting the older goal as a failure. If status is
        ``clarification_required``, ask the returned clarification question. Otherwise
        the tool result is authoritative: never claim success for denied, failed,
        unavailable or unverified work.
        """
        del context
        try:
            mode = str(operation_hint)
            return _compact_voice_result(
                await self.execute_goal(
                    operation_hint="" if mode == "planner" else mode,
                    parameters_json=parameters_json,
                )
            )
        except (
            HandsOrchestrationError,
            HandsPlanningError,
            TypeError,
            ValueError,
        ) as exc:
            raise ToolError(str(exc)) from exc
