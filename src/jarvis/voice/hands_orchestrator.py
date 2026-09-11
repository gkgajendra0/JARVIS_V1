"""Voice-specific grounding and latency policy for natural JARVIS Hands requests.

The core Hands orchestrator remains deliberately strict for programmatic callers. Voice
transcripts add two production concerns: speech providers may transliterate values across
scripts, and interactive computer control must avoid unnecessary cloud round trips. This
module therefore keeps the same canonical grounding/Authority path while adding risk-aware
speech normalization, deterministic completion for verified single-step goals, per-stage
latency telemetry, and earlier escalation when structured UIA repeatedly fails to verify.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from typing import Any

from jarvis.authority.types import ActionOrigin
from jarvis.capabilities.models import CapabilityStatus
from jarvis.hands.contracts import PlannedAction
from jarvis.hands.orchestrator import (
    GroundingContext,
    HandsOrchestrationError,
    HandsOrchestrator,
)

LOGGER = logging.getLogger(__name__)

_VOICE_MAX_ACTIONS = 8
_UIA_UNVERIFIED_BEFORE_VISUAL = 2

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

_SEMANTIC_NUMERIC_FIELDS = {
    "set_master_volume": "percent",
    "set_display_brightness": "percent",
}

_TERMINAL_OPERATIONS_BY_GROUP: dict[str, frozenset[str]] = {
    "system_status": frozenset({"system_status", "list_processes"}),
    "audio": frozenset(
        {
            "get_master_volume",
            "set_master_volume",
            "mute_master_volume",
            "unmute_master_volume",
        }
    ),
    "media": frozenset(
        {
            "get_current_media",
            "play_media",
            "pause_media",
            "toggle_media_playback",
            "next_media",
            "previous_media",
            "stop_media",
        }
    ),
    "clipboard": frozenset(
        {"get_clipboard_text", "set_clipboard_text", "clear_clipboard"}
    ),
    "app_lifecycle": frozenset({"open_app", "close_app"}),
    "windows": frozenset(
        {
            "list_windows",
            "focus_window",
            "maximize_window",
            "minimize_window",
            "restore_window",
            "move_window_to_next_monitor",
        }
    ),
    "files_read": frozenset(
        {
            "file_info",
            "list_directory",
            "list_project_files",
            "read_file",
            "read_document",
            "search_project",
        }
    ),
    "display": frozenset(
        {"list_displays", "get_display_brightness", "set_display_brightness"}
    ),
    "bluetooth": frozenset(
        {"list_bluetooth_devices", "pair_bluetooth_device", "unpair_bluetooth_device"}
    ),
    "software_discovery": frozenset({"search_software", "list_installed_software"}),
    "development_read": frozenset({"git_status", "git_active_branch"}),
}


class VoiceHandsOrchestrator(HandsOrchestrator):
    """Hands orchestrator optimized for realtime speech while preserving Authority."""

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

    @staticmethod
    def _verified_terminal(operation: str, selected: tuple[str, ...]) -> bool:
        if len(selected) != 1:
            return False
        allowed = _TERMINAL_OPERATIONS_BY_GROUP.get(selected[0])
        return allowed is not None and operation in allowed

    @staticmethod
    def _with_visual_candidate(candidates, route_groups):
        if any(item.operation == "execute_visual_desktop_task" for item in candidates):
            return candidates
        visual = next(
            (group for group in route_groups if group.key == "visual_fallback"),
            None,
        )
        return (*candidates, *visual.operations) if visual is not None else candidates

    def _success_payload(
        self,
        *,
        goal: str,
        selected: tuple[str, ...],
        results,
        entity_trace: list[dict[str, str]],
        observations: list[dict[str, Any]],
        completion_mode: str,
    ) -> dict[str, object]:
        return {
            "ok": True,
            "status": "succeeded",
            "goal": goal,
            "completed_steps": len(results),
            "route_groups": list(selected),
            "results": [self._result_payload(item) for item in results],
            "entity_trace": entity_trace,
            "observations": observations,
            "completion_mode": completion_mode,
        }

    async def execute_goal(
        self,
        *,
        session_id: str,
        goal: str,
        recent_user_turns: tuple[str, ...] = (),
    ) -> dict[str, object]:
        """Execute one voice goal with fewer serial planner calls on verified fast cases."""

        total_started = time.perf_counter()
        latest = str(goal).strip()
        if not latest:
            raise HandsOrchestrationError(
                "Hands requires a non-empty accepted USER goal"
            )
        context = GroundingContext(latest, recent_user_turns)
        available = self._available_operations()
        route_groups = self._route_groups(available)
        if not route_groups:
            raise HandsOrchestrationError(
                "no executable Hands capabilities are available"
            )

        route_started = time.perf_counter()
        selected = await self._planner.route(
            goal=latest,
            recent_user_turns=recent_user_turns,
            route_groups=route_groups,
        )
        route_ms = (time.perf_counter() - route_started) * 1000
        candidates = self._candidate_operations(selected, route_groups)
        if not candidates:
            raise HandsOrchestrationError(
                "Hands routing produced no executable operations"
            )

        LOGGER.info(
            "Hands semantic route | provider=%s | model=%s | groups=%s | candidates=%s | "
            "route_ms=%.1f",
            self._planner.provider_name,
            self._planner.model_name,
            ",".join(selected),
            ",".join(item.operation for item in candidates),
            route_ms,
        )

        observations: list[dict[str, Any]] = []
        results = []
        entity_trace: list[dict[str, str]] = []
        attempted: set[str] = set()
        unverified_uia = 0

        for step_number in range(1, _VOICE_MAX_ACTIONS + 1):
            plan_started = time.perf_counter()
            decision = await self._planner.next_action(
                goal=latest,
                recent_user_turns=recent_user_turns,
                candidate_operations=candidates,
                observations=tuple(observations),
            )
            plan_ms = (time.perf_counter() - plan_started) * 1000
            LOGGER.info(
                "Hands planning latency | step=%s | elapsed_ms=%.1f",
                step_number,
                plan_ms,
            )

            if decision.clarification_question is not None:
                return {
                    "ok": False,
                    "status": "clarification_required",
                    "goal": latest,
                    "clarification_question": decision.clarification_question,
                    "completed_steps": len(results),
                    "route_groups": list(selected),
                    "observations": observations,
                }
            if decision.goal_complete:
                if not results:
                    raise HandsOrchestrationError(
                        "planner claimed goal completion without any verified execution"
                    )
                latest_result = results[-1]
                latest_observation = observations[-1]
                if not latest_result.ok or not bool(latest_observation.get("verified")):
                    raise HandsOrchestrationError(
                        "planner claimed goal completion without a successful latest execution"
                    )
                payload = self._success_payload(
                    goal=latest,
                    selected=selected,
                    results=results,
                    entity_trace=entity_trace,
                    observations=observations,
                    completion_mode="planner_confirmed",
                )
                LOGGER.info(
                    "Hands goal latency | completion=planner_confirmed | steps=%s | total_ms=%.1f",
                    len(results),
                    (time.perf_counter() - total_started) * 1000,
                )
                return payload

            action = decision.action
            if action is None:
                raise HandsOrchestrationError(
                    "planner returned neither an action, clarification, nor completion"
                )

            normalized = await asyncio.to_thread(
                self._normalize_action,
                action,
                context,
            )
            action_fingerprint = self._action_fingerprint(
                normalized.operation, normalized.parameters
            )
            if action_fingerprint in attempted:
                raise HandsOrchestrationError(
                    "planner repeated an identical action instead of making progress"
                )
            attempted.add(action_fingerprint)
            entity_trace.extend(normalized.entity_trace)
            LOGGER.info(
                "Hands planned action | step=%s | operation=%s | parameter_keys=%s | "
                "entity_refs=%s",
                step_number,
                normalized.operation,
                ",".join(sorted(normalized.parameters)),
                len(normalized.entity_trace),
            )

            execute_started = time.perf_counter()
            result = await asyncio.to_thread(
                self._runtime.execute_operation,
                session_id=session_id,
                operation=normalized.operation,
                parameters=normalized.parameters,
                origin=ActionOrigin.DIRECT_USER,
            )
            execute_ms = (time.perf_counter() - execute_started) * 1000
            results.append(result)
            observation = self._observation(
                normalized,
                result,
                step_number=step_number,
            )
            observations.append(observation)
            verified = bool(observation["verified"])
            LOGGER.info(
                "Hands execution observation | step=%s | operation=%s | status=%s | "
                "ok=%s | verified=%s | execution_ms=%.1f",
                step_number,
                normalized.operation,
                result.status.value,
                result.ok,
                verified,
                execute_ms,
            )

            if (
                result.ok
                and verified
                and self._verified_terminal(normalized.operation, selected)
            ):
                payload = self._success_payload(
                    goal=latest,
                    selected=selected,
                    results=results,
                    entity_trace=entity_trace,
                    observations=observations,
                    completion_mode="deterministic_verified_terminal",
                )
                LOGGER.info(
                    "Hands goal latency | completion=deterministic_verified_terminal | "
                    "steps=%s | total_ms=%.1f",
                    len(results),
                    (time.perf_counter() - total_started) * 1000,
                )
                return payload

            if normalized.operation == "execute_windows_plan":
                if verified:
                    unverified_uia = 0
                else:
                    unverified_uia += 1
                    if unverified_uia >= _UIA_UNVERIFIED_BEFORE_VISUAL:
                        candidates = self._with_visual_candidate(
                            candidates, route_groups
                        )
                        visual_available = any(
                            item.operation == "execute_visual_desktop_task"
                            for item in candidates
                        )
                        if visual_available:
                            candidates = tuple(
                                item
                                for item in candidates
                                if item.operation != "execute_windows_plan"
                            )
                            LOGGER.info(
                                "Hands UIA escalation | unverified_attempts=%s | "
                                "structured_ui_removed=True | visual_fallback=True",
                                unverified_uia,
                            )

            if result.ok:
                continue
            if result.status in {
                CapabilityStatus.INVALID,
                CapabilityStatus.UNAVAILABLE,
            }:
                if "app_ui" in selected:
                    candidates = self._with_visual_candidate(candidates, route_groups)
                continue
            return {
                "ok": False,
                "status": "failed",
                "goal": latest,
                "completed_steps": sum(item.ok for item in results),
                "failed_operation": normalized.operation,
                "reason": result.reason or result.status.value,
                "route_groups": list(selected),
                "results": [self._result_payload(item) for item in results],
                "entity_trace": entity_trace,
                "observations": observations,
            }

        return {
            "ok": False,
            "status": "max_steps_exceeded",
            "goal": latest,
            "completed_steps": sum(item.ok for item in results),
            "reason": f"Hands exceeded the bounded {_VOICE_MAX_ACTIONS}-action goal loop",
            "route_groups": list(selected),
            "results": [self._result_payload(item) for item in results],
            "entity_trace": entity_trace,
            "observations": observations,
        }

    @staticmethod
    def _action_fingerprint(operation: str, parameters: dict[str, Any]) -> str:
        from jarvis.hands.orchestrator import _fingerprint

        return _fingerprint(operation, parameters)
