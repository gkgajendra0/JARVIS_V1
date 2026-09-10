"""Single voice-facing goal boundary for provider-neutral JARVIS Hands."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from livekit.agents import RunContext, function_tool
from livekit.agents.llm import ToolError

from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.hands.models import HandsWorkflowStep
from jarvis.hands.workflow import HandsWorkflowRunner

_MAX_PLAN_JSON_CHARS = 20_000
_MAX_APP_CHARS = 160
_CURRENT_TARGET_MARKERS = (
    "it",
    "this app",
    "that app",
    "this window",
    "that window",
    "current window",
    "already open",
    "already running",
)
_MEDIA_CONTEXT_MARKERS = (
    "music",
    "song",
    "track",
    "media",
    "playing",
    "play",
    "pause",
    "resume",
    "next",
    "previous",
    "stop",
)
_OPERATION_INTENT_MARKERS: dict[str, tuple[str, ...]] = {
    "get_master_volume": ("volume", "sound level", "audio level"),
    "set_master_volume": ("volume", "sound", "audio"),
    "mute_master_volume": ("mute", "silent", "volume off"),
    "unmute_master_volume": ("unmute", "sound on", "volume on"),
    "get_current_media": _MEDIA_CONTEXT_MARKERS,
    "play_media": ("resume", "continue", "play it", "play again"),
    "pause_media": ("pause",),
    "toggle_media_playback": ("play pause", "toggle playback"),
    "next_media": ("next", "next song", "next track"),
    "previous_media": ("previous", "previous song", "previous track", "back track"),
    "stop_media": ("stop", "stop music", "stop playback"),
    "get_clipboard_text": ("clipboard", "what did i copy", "what's copied"),
    "set_clipboard_text": ("clipboard", "copy"),
    "clear_clipboard": ("clear clipboard", "empty clipboard"),
    "list_windows": ("windows", "open apps", "open windows"),
    "focus_window": ("focus", "bring", "switch to", "go to"),
    "maximize_window": ("maximize", "maximise", "full screen"),
    "minimize_window": ("minimize", "minimise"),
    "restore_window": ("restore",),
    "move_window_to_next_monitor": (
        "other monitor",
        "second monitor",
        "next monitor",
        "other screen",
    ),
    "open_app": ("open", "launch", "start"),
    "execute_windows_plan": (
        "open",
        "play",
        "search",
        "find",
        "type",
        "write",
        "enter",
        "click",
        "press",
        "choose",
        "select",
        "control",
        "use",
    ),
    "execute_visual_desktop_task": ("visual", "screen", "look at", "computer use"),
}
_APP_OPERATIONS = {
    "open_app",
    "focus_window",
    "maximize_window",
    "minimize_window",
    "restore_window",
    "move_window_to_next_monitor",
    "execute_windows_plan",
    "execute_visual_desktop_task",
}
_WINDOW_OPERATIONS = {
    "focus_window",
    "maximize_window",
    "minimize_window",
    "restore_window",
    "move_window_to_next_monitor",
}


class HandsGoalGroundingError(ValueError):
    pass


def _normalized(value: object) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(value).casefold()).split())


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    padded = f" {_normalized(text)} "
    return any(f" {_normalized(marker)} " in padded for marker in markers)


def _material_in_text(value: object, text: str) -> bool:
    material = _normalized(value)
    return bool(material) and material in _normalized(text)


def _bounded_app(value: object) -> str:
    app = " ".join(str(value).split())
    if not app or len(app) > _MAX_APP_CHARS:
        raise HandsGoalGroundingError("app target must be a bounded non-empty name")
    return app


class HandsGoalAgentTools:
    """Expose one goal-oriented computer tool while keeping executors internal."""

    def __init__(
        self,
        runtime: CapabilityRuntime,
        conversation: ConversationSession,
    ) -> None:
        if not isinstance(runtime, CapabilityRuntime):
            raise TypeError("runtime must be a CapabilityRuntime")
        if not isinstance(conversation, ConversationSession):
            raise TypeError("conversation must be a ConversationSession")
        self._runtime = runtime
        self._conversation = conversation
        self._runner = HandsWorkflowRunner(runtime, registry=runtime.hands_registry)

    @property
    def tools(self) -> list:
        return [self.use_computer]

    def _latest_user_turn(self) -> ConversationTurn:
        turn = next(
            (
                candidate
                for candidate in reversed(self._conversation.turns)
                if candidate.role is ConversationRole.USER
            ),
            None,
        )
        if turn is None:
            raise HandsGoalGroundingError(
                "JARVIS Hands requires a latest accepted user utterance"
            )
        return turn

    def _recently_grounded_app(self, app: str) -> bool:
        normalized_app = _normalized(app)
        if not normalized_app:
            return False
        for turn in reversed(self._conversation.turns[-8:]):
            if turn.role is ConversationRole.USER and normalized_app in _normalized(turn.text):
                return True
        return False

    def _validate_app_target(
        self,
        *,
        app: str,
        user_text: str,
        apps_opened_in_plan: set[str],
        allow_context: bool,
    ) -> None:
        normalized_app = _normalized(app)
        if normalized_app in _normalized(user_text):
            return
        if normalized_app in apps_opened_in_plan:
            return
        if allow_context and _contains_marker(user_text, _CURRENT_TARGET_MARKERS):
            if self._recently_grounded_app(app):
                return
        raise HandsGoalGroundingError(
            "model-selected app target is not grounded in the current or recent user request"
        )

    def _normalize_step(
        self,
        raw: object,
        *,
        user_text: str,
        apps_opened_in_plan: set[str],
    ) -> HandsWorkflowStep:
        if not isinstance(raw, dict):
            raise HandsGoalGroundingError("each Hands plan step must be an object")
        operation = str(raw.get("operation", "")).strip()
        semantic = self._runtime.hands_registry.require(operation)
        markers = _OPERATION_INTENT_MARKERS.get(operation)
        if markers is None:
            raise HandsGoalGroundingError(
                f"operation is not yet exposed through goal-oriented Hands: {operation}"
            )
        if not _contains_marker(user_text, markers):
            if operation != "get_current_media" or not _contains_marker(
                user_text, _MEDIA_CONTEXT_MARKERS
            ):
                raise HandsGoalGroundingError(
                    f"latest user request does not warrant Hands operation: {operation}"
                )

        raw_parameters = raw.get("parameters", {})
        if not isinstance(raw_parameters, dict):
            raise HandsGoalGroundingError("Hands step parameters must be an object")
        parameters: dict[str, Any] = dict(raw_parameters)

        if operation == "set_master_volume":
            percent = float(parameters.get("percent"))
            requested_numbers = [
                float(value)
                for value in re.findall(r"\b\d+(?:\.\d+)?\b", user_text)
            ]
            if not any(abs(percent - value) < 0.001 for value in requested_numbers):
                raise HandsGoalGroundingError(
                    "volume percentage must come directly from the latest user request"
                )
            parameters = {"percent": percent}
        elif operation == "set_clipboard_text":
            text = str(parameters.get("text", ""))
            if not _material_in_text(text, user_text):
                raise HandsGoalGroundingError(
                    "clipboard text must be explicitly present in the latest user request"
                )
            parameters = {"text": text}
        elif operation in _APP_OPERATIONS:
            app = _bounded_app(parameters.get("app"))
            self._validate_app_target(
                app=app,
                user_text=user_text,
                apps_opened_in_plan=apps_opened_in_plan,
                allow_context=operation in _WINDOW_OPERATIONS,
            )
            if operation == "open_app":
                parameters = {"app": app}
                apps_opened_in_plan.add(_normalized(app))
            elif operation == "execute_windows_plan":
                plan = parameters.get("plan")
                if not isinstance(plan, list) or not plan:
                    raise HandsGoalGroundingError(
                        "structured app UI step requires a non-empty plan"
                    )
                if any(
                    isinstance(item, dict)
                    and str(item.get("action", "")).strip().casefold() == "launch"
                    for item in plan
                ):
                    raise HandsGoalGroundingError(
                        "goal plans must launch apps through app.lifecycle, not app UI"
                    )
                parameters = {
                    "app": app,
                    "task": user_text,
                    "plan": plan,
                    "allow_existing_app": True,
                }
            elif operation == "execute_visual_desktop_task":
                parameters = {"app": app, "task": user_text}
            else:
                parameters = {"app": app}
        else:
            parameters = {}

        if semantic.operation != operation:
            raise HandsGoalGroundingError("Hands registry returned an inconsistent operation")
        return HandsWorkflowStep(operation=operation, parameters=parameters)

    def _parse_plan(self, plan_json: str, user_text: str) -> tuple[HandsWorkflowStep, ...]:
        if not isinstance(plan_json, str) or not plan_json.strip():
            raise HandsGoalGroundingError("Hands goal plan must be non-empty JSON")
        if len(plan_json) > _MAX_PLAN_JSON_CHARS:
            raise HandsGoalGroundingError("Hands goal plan exceeds the bounded input limit")
        try:
            decoded = json.loads(plan_json)
        except json.JSONDecodeError as exc:
            raise HandsGoalGroundingError("Hands goal plan is invalid JSON") from exc
        if not isinstance(decoded, list) or not decoded:
            raise HandsGoalGroundingError("Hands goal plan must be a non-empty JSON array")
        if len(decoded) > self._runner.MAX_STEPS:
            raise HandsGoalGroundingError(
                f"Hands goal plan exceeds {self._runner.MAX_STEPS} semantic steps"
            )
        opened: set[str] = set()
        return tuple(
            self._normalize_step(
                item,
                user_text=user_text,
                apps_opened_in_plan=opened,
            )
            for item in decoded
        )

    async def execute_goal(self, *, plan_json: str) -> dict[str, object]:
        turn = self._latest_user_turn()
        steps = self._parse_plan(plan_json, turn.text)
        workflow = await asyncio.to_thread(
            self._runner.execute,
            session_id=self._conversation.session_id,
            steps=steps,
        )
        results = [
            {
                "ok": result.ok,
                "status": result.status.value,
                "operation": result.operation,
                "capability": result.capability_key,
                "data": result.data,
                "reason": result.reason,
                "provenance": list(result.provenance),
            }
            for result in workflow.results
        ]
        return {
            "ok": workflow.ok,
            "status": "succeeded" if workflow.ok else "failed",
            "goal": turn.text,
            "completed_steps": workflow.completed_steps,
            "failed_operation": workflow.failed_operation,
            "reason": workflow.reason,
            "results": results,
            "canonical_user_turn_id": turn.turn_id,
        }

    @function_tool()
    async def use_computer(
        self,
        context: RunContext,
        plan_json: str,
    ) -> dict[str, object]:
        """Accomplish the latest USER computer goal through JARVIS Hands.

        This is the single computer-action boundary. The USER states an outcome; never
        ask them to choose a capability or executor. Build a short semantic JSON-array
        plan and let JARVIS route each step to the best available governed executor.

        Each item is {"operation": "...", "parameters": {...}}. Current semantic
        operations cover application launch, app UI, window management, system audio,
        current Windows media playback, and clipboard. Application names are not a
        hard-coded tool list: use the app name from the USER request and app.lifecycle
        resolves it against the Windows installed-app catalogue. To operate app UI,
        use `execute_windows_plan` with an `app` plus a bounded `plan`; do not include
        a nested `launch` action because launch belongs to app.lifecycle.

        Prefer native semantic operations over UI. Use app UI only for interaction that
        has no better native capability. UI intermediate selectors may be inferred as
        implementation details, but material text/values must remain grounded in the
        USER goal and high-consequence/persistent UI actions remain blocked by the
        executor. Visual computer use is only an owner-enabled fallback.

        Every semantic step independently passes through CapabilityRuntime,
        AuthorityService, one-time permit revalidation, execution and verification.
        Tool results, not attempted actions, are the only basis for claiming success.
        """
        del context
        try:
            return await self.execute_goal(plan_json=plan_json)
        except (HandsGoalGroundingError, TypeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
