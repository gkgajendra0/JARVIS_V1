"""Voice-facing semantic JARVIS Hands tool for native computer capabilities."""

from __future__ import annotations

import asyncio
import logging
import re

from livekit.agents import RunContext, function_tool
from livekit.agents.llm import ToolError

from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.voice.computer_tools import ComputerControlAgentTools

LOGGER = logging.getLogger(__name__)

_OPERATION_MARKERS: dict[str, tuple[str, ...]] = {
    "get_master_volume": ("volume", "sound level", "audio level"),
    "set_master_volume": ("volume", "sound", "audio"),
    "mute_master_volume": ("mute", "silent", "volume off"),
    "unmute_master_volume": ("unmute", "sound on", "volume on"),
    "get_current_media": (
        "what is playing",
        "what's playing",
        "current song",
        "current media",
    ),
    "play_media": ("play", "resume"),
    "pause_media": ("pause",),
    "toggle_media_playback": ("play pause", "toggle playback"),
    "next_media": ("next", "next song", "next track"),
    "previous_media": (
        "previous",
        "previous song",
        "previous track",
        "back track",
    ),
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
}
_APP_ALIASES = {
    "notepad": ("notepad", "note pad"),
    "calculator": ("calculator", "calc"),
    "paint": ("paint", "mspaint", "ms paint"),
}
_CURRENT_WINDOW_MARKERS = (
    "this window",
    "current window",
    "it",
    "this app",
    "that window",
    "isko",
    "ise",
)


class HandsToolGroundingError(ValueError):
    pass


def _normalized(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", value.casefold()).split())


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    normalized = f" {_normalized(text)} "
    return any(f" {_normalized(marker)} " in normalized for marker in markers)


def _named_app(text: str) -> str | None:
    normalized = f" {_normalized(text)} "
    for app, aliases in _APP_ALIASES.items():
        if any(f" {_normalized(alias)} " in normalized for alias in aliases):
            return app
    return None


class HandsAgentTools:
    """Expose semantic native Hands plus the structured/visual app-UI fallback."""

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
        self._app_ui = ComputerControlAgentTools(runtime, conversation)

    @property
    def tools(self) -> list:
        return [self.computer_action, *self._app_ui.tools]

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
            raise HandsToolGroundingError(
                "computer action requires a latest accepted user utterance"
            )
        return turn

    def _recent_named_app(self) -> str | None:
        for turn in reversed(self._conversation.turns[-8:]):
            if turn.role is not ConversationRole.USER:
                continue
            app = _named_app(turn.text)
            if app is not None:
                return app
        return None

    def _ground_parameters(
        self,
        turn: ConversationTurn,
        operation: str,
        *,
        app: str,
        percent: float | None,
        text: str,
    ) -> dict[str, object]:
        markers = _OPERATION_MARKERS.get(operation)
        if markers is None:
            raise HandsToolGroundingError(
                f"operation is not exposed through semantic voice Hands: {operation}"
            )
        if not _contains_marker(turn.text, markers):
            raise HandsToolGroundingError(
                "latest accepted user turn does not explicitly warrant this computer action"
            )

        parameters: dict[str, object] = {}
        if operation == "set_master_volume":
            numbers = [
                float(value)
                for value in re.findall(r"\b\d+(?:\.\d+)?\b", turn.text)
            ]
            if percent is None or not any(
                abs(value - float(percent)) < 0.001 for value in numbers
            ):
                raise HandsToolGroundingError(
                    "volume percentage must come directly from the latest user request"
                )
            parameters["percent"] = float(percent)

        if operation == "set_clipboard_text":
            value = str(text)
            if not value.strip() or _normalized(value) not in _normalized(turn.text):
                raise HandsToolGroundingError(
                    "clipboard text must be explicitly present in the latest user request"
                )
            parameters["text"] = value

        if operation in {
            "focus_window",
            "maximize_window",
            "minimize_window",
            "restore_window",
            "move_window_to_next_monitor",
        }:
            explicit = _named_app(turn.text)
            selected = str(app).strip().casefold() if app else ""
            if explicit is not None:
                if selected and selected != explicit:
                    raise HandsToolGroundingError(
                        "model-selected app differs from the app named by the user"
                    )
                selected = explicit
            elif _contains_marker(turn.text, _CURRENT_WINDOW_MARKERS):
                recent = self._recent_named_app()
                if recent is None:
                    raise HandsToolGroundingError(
                        "current-window request has no recent user-grounded app target"
                    )
                if selected and selected != recent:
                    raise HandsToolGroundingError(
                        "model-selected app differs from recent user-grounded context"
                    )
                selected = recent
            else:
                raise HandsToolGroundingError(
                    "window control requires an explicit or recent user-grounded app target"
                )
            parameters["app"] = selected

        if operation == "open_app":
            explicit = _named_app(turn.text)
            selected = str(app).strip().casefold() if app else ""
            if explicit is None:
                raise HandsToolGroundingError(
                    "application launch requires the latest user request to name the app"
                )
            if selected and selected != explicit:
                raise HandsToolGroundingError(
                    "model-selected app differs from the app named by the user"
                )
            parameters["app"] = explicit

        return parameters

    async def execute(
        self,
        *,
        operation: str,
        app: str = "",
        percent: float | None = None,
        text: str = "",
    ) -> dict[str, object]:
        turn = self._latest_user_turn()
        self._runtime.hands_registry.require(operation)
        parameters = self._ground_parameters(
            turn,
            operation,
            app=app,
            percent=percent,
            text=text,
        )
        result = await asyncio.to_thread(
            self._runtime.execute_operation,
            session_id=self._conversation.session_id,
            operation=operation,
            parameters=parameters,
        )
        LOGGER.info(
            "Semantic JARVIS Hands action completed | turn_id=%s | operation=%s | "
            "status=%s | elapsed_ms=%.1f",
            turn.turn_id,
            operation,
            result.status.value,
            result.elapsed_ms,
        )
        return {
            "ok": result.ok,
            "status": result.status.value,
            "operation": result.operation,
            "capability": result.capability_key,
            "data": result.data,
            "reason": result.reason,
            "provenance": list(result.provenance),
            "canonical_user_turn_id": turn.turn_id,
        }

    @function_tool()
    async def computer_action(
        self,
        context: RunContext,
        operation: str,
        app: str = "",
        percent: float | None = None,
        text: str = "",
    ) -> dict[str, object]:
        """Use a native semantic computer capability for the latest user request.

        Prefer this tool over UI automation whenever it supports the requested outcome.
        Current operations include master volume/mute, current media and playback
        controls, clipboard text, top-level window management, and approved app launch.

        Never invent the target or material parameters. Volume percentages must appear
        in the latest USER utterance. Clipboard text must be present in that utterance.
        App/window targets must be explicitly user-named or, for phrases such as "this
        window", recoverable from recent canonical USER context. The tool revalidates
        these constraints independently of model reasoning.

        Mutations pass through canonical AuthorityService and currently require
        exact-action Windows Hello because T2 owner admission is intentionally disabled.
        Use `control_computer` only when a task genuinely requires application UI
        automation. Browser, shell, security, file-write, install, email/send, and
        credential operations are not exposed by this H1 tool.
        """
        del context
        try:
            return await self.execute(
                operation=operation,
                app=app,
                percent=percent,
                text=text,
            )
        except (HandsToolGroundingError, TypeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
