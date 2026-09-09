"""Voice-facing governed computer-control tool for JARVIS hands."""

from __future__ import annotations

import asyncio
import json
import logging
import re

from livekit.agents import RunContext, function_tool
from livekit.agents.llm import ToolError

from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn

LOGGER = logging.getLogger(__name__)

_CONTROL_VERBS = (
    "open",
    "launch",
    "start",
    "type",
    "write",
    "enter",
    "click",
    "press",
    "select",
    "choose",
    "focus",
    "control",
    "operate",
    "use",
    "khol",
    "kholo",
    "likh",
    "likho",
    "click karo",
    "press karo",
)
_APPROVED_APP_ALIASES = {
    "notepad": ("notepad", "note pad"),
    "calculator": ("calculator", "calc"),
    "paint": ("paint", "mspaint", "ms paint"),
}
_EXISTING_APP_MARKERS = (
    "already open",
    "already running",
    "currently open",
    "current window",
    "open window",
    "is already open",
    "jo open hai",
    "already khula",
)
_BLOCKED_UI_INTENT_TERMS = (
    "save",
    "save as",
    "print",
    "share",
    "send",
    "delete",
    "remove",
    "open file",
    "open dialog",
    "install",
    "uninstall",
    "download",
    "upload",
    "security",
    "permission",
    "settings",
    "password",
    "credential",
    "api key",
    "token",
)


class ComputerControlGroundingError(ValueError):
    pass


def _normalized(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", value.casefold()).split())


def _latest_app_is_named(text: str, app: str) -> bool:
    normalized = f" {_normalized(text)} "
    aliases = _APPROVED_APP_ALIASES.get(app, (app,))
    return any(f" {_normalized(alias)} " in normalized for alias in aliases)


def _control_warranted(text: str, app: str) -> bool:
    normalized = f" {_normalized(text)} "
    verb_present = any(
        f" {_normalized(marker)} " in normalized for marker in _CONTROL_VERBS
    )
    return verb_present and _latest_app_is_named(text, app)


def _existing_app_authorized(text: str) -> bool:
    normalized = _normalized(text)
    return any(_normalized(marker) in normalized for marker in _EXISTING_APP_MARKERS)


def _material_is_grounded(material: object, user_text: str) -> bool:
    normalized_material = _normalized(str(material))
    return bool(normalized_material) and normalized_material in _normalized(user_text)


def _validate_structured_plan(plan: object, user_text: str) -> list[dict[str, object]]:
    if not isinstance(plan, list) or not plan:
        raise ComputerControlGroundingError(
            "structured computer-control plan must be a non-empty JSON array"
        )
    normalized_user = _normalized(user_text)
    validated: list[dict[str, object]] = []
    for index, item in enumerate(plan, start=1):
        if not isinstance(item, dict):
            raise ComputerControlGroundingError(
                f"structured plan step {index} must be an object"
            )
        action = str(item.get("action", "")).strip().casefold()
        for field in ("selector", "query"):
            value = str(item.get(field, "")).strip()
            normalized_value = _normalized(value)
            if normalized_value and any(
                _normalized(term) in normalized_value
                for term in _BLOCKED_UI_INTENT_TERMS
            ):
                raise ComputerControlGroundingError(
                    "structured plan contains an action outside the bounded app UI scope"
                )
        if action in {"send_text", "set_value"} and not _material_is_grounded(
            item.get("text", ""), user_text
        ):
            raise ComputerControlGroundingError(
                "structured plan typed text is not grounded in the latest user request"
            )
        if action == "verify_value" and not _material_is_grounded(
            item.get("expected", ""), user_text
        ):
            raise ComputerControlGroundingError(
                "structured plan verification value is not grounded in the latest user request"
            )
        if action in {"click", "invoke"}:
            selector = _normalized(str(item.get("selector", "")))
            if not selector or selector not in normalized_user:
                raise ComputerControlGroundingError(
                    "structured plan UI mutation selector is not grounded in the latest user request"
                )
        validated.append(dict(item))
    return validated


class ComputerControlAgentTools:
    """Expose one high-level hands tool while canonical user intent stays authoritative."""

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

    @property
    def tools(self) -> list:
        return [self.control_computer]

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
            raise ComputerControlGroundingError(
                "computer control requires a latest accepted user utterance"
            )
        return turn

    async def control(
        self,
        *,
        app: str,
        strategy: str = "structured",
        plan_json: str = "",
    ) -> dict[str, object]:
        turn = self._latest_user_turn()
        normalized_app = str(app).strip().casefold()
        if normalized_app not in _APPROVED_APP_ALIASES:
            return {
                "ok": False,
                "status": "app_not_approved",
                "reason": "current hands slice approves notepad, calculator, and paint",
                "canonical_user_turn_id": turn.turn_id,
            }
        if not _control_warranted(turn.text, normalized_app):
            return {
                "ok": False,
                "status": "computer_control_not_warranted",
                "reason": (
                    "latest user turn must explicitly request a control action and name "
                    "the approved target application"
                ),
                "canonical_user_turn_id": turn.turn_id,
            }

        selected = str(strategy).strip().casefold()
        if selected == "structured":
            if not plan_json.strip():
                raise ComputerControlGroundingError(
                    "structured computer control requires a bounded JSON action plan"
                )
            try:
                plan = json.loads(plan_json)
            except json.JSONDecodeError as exc:
                raise ComputerControlGroundingError(
                    "structured computer-control plan is invalid JSON"
                ) from exc
            plan = _validate_structured_plan(plan, turn.text)
            operation = "execute_windows_plan"
            parameters = {
                "app": normalized_app,
                "task": turn.text,
                "plan": plan,
                "allow_existing_app": _existing_app_authorized(turn.text),
            }
        elif selected == "visual":
            operation = "execute_visual_desktop_task"
            parameters = {
                "app": normalized_app,
                "task": turn.text,
            }
        else:
            raise ComputerControlGroundingError(
                "computer-control strategy must be structured or visual"
            )

        result = await asyncio.to_thread(
            self._runtime.execute_operation,
            session_id=self._conversation.session_id,
            operation=operation,
            parameters=parameters,
        )
        LOGGER.info(
            "Governed computer control completed | turn_id=%s | app=%s | "
            "strategy=%s | status=%s | elapsed_ms=%.1f",
            turn.turn_id,
            normalized_app,
            selected,
            result.status.value,
            result.elapsed_ms,
        )
        return {
            "ok": result.ok,
            "status": result.status.value,
            "operation": result.operation,
            "capability": result.capability_key,
            "strategy": selected,
            "data": result.data,
            "reason": result.reason,
            "provenance": list(result.provenance),
            "canonical_user_turn_id": turn.turn_id,
        }

    @function_tool()
    async def control_computer(
        self,
        context: RunContext,
        app: str,
        strategy: str = "structured",
        plan_json: str = "",
    ) -> dict[str, object]:
        """Control one approved local Windows app for the latest explicit user request.

        Prefer `strategy="structured"`. Approved apps in the current bounded hands
        slice are `notepad`, `calculator`, and `paint`. The task itself is NEVER taken
        from tool arguments: JARVIS binds execution to the latest accepted USER turn.

        For structured execution, provide `plan_json` as a JSON array of bounded UI
        actions. Supported actions are:
        `launch`, `wait_until_running`, `inspect`, `search`, `get_value`,
        `verify_value`, `focus`, `click`, `invoke`, `send_text`, `set_value`, and
        `wait_for`.

        Common examples:
        `[{'action':'launch'},{'action':'wait_until_running'},
          {'action':'send_text','selector':'Text editor','text':'hello'},
          {'action':'verify_value','selector':'Text editor','expected':'hello'}]`

        JSON must use double quotes. Use plain UI text selectors when a stable selector
        is not known; Microsoft winapp resolves text/AutomationId selectors. Include a
        `verify_value` step whenever the requested final state exposes a readable value.

        Use `strategy="visual"` only when structured UI automation genuinely cannot
        complete the bounded local-app task and visual fallback is explicitly enabled
        by the owner. Browser/web interaction, terminals/PowerShell, File Explorer
        mutation, security settings, save/send/delete/install/download actions, coding
        mutation, credentials, and arbitrary commands are outside this hands slice.

        Any non-routine control request goes through canonical JARVIS authority and
        exact-action Windows Hello verification before execution. Never claim success
        unless this tool returns `ok: true`.
        """
        del context
        try:
            return await self.control(
                app=app,
                strategy=strategy,
                plan_json=plan_json,
            )
        except (ComputerControlGroundingError, TypeError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
