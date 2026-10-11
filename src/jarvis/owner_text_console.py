"""Text-only owner ingress into the existing durable GICC/Work runtime.

This is a local goal-oriented owner console, not a simulated capability engine
or a second permission system. It does not start microphone or speaker I/O.
Protected approvals retain their existing Authority/Windows Hello requirements.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import threading
from typing import Any

from jarvis.conversation import ConversationRole, ConversationSession

LOGGER = logging.getLogger(__name__)
_GOAL_ID = re.compile(r"\bgoal_[a-zA-Z0-9]+\b")
_CANCEL = re.compile(
    r"^(?:jarvis[,:\s]+)?(?:please\s+)?(?:cancel|stop|withdraw)\b",
    re.IGNORECASE,
)
_LIST = re.compile(
    r"^(?:/)?(?:goals|list (?:my )?(?:active )?(?:goals|objectives)|show (?:my )?(?:active )?(?:goals|objectives))\??$",
    re.IGNORECASE,
)
_STATUS = re.compile(
    r"^(?:/)?(?:status|show status|goal status)\b", re.IGNORECASE
)
_TOPICS = (
    ("tv", "television", "hisense", "vidaa"),
    ("camera", "webcam", "doorbell"),
    ("gate", "entrance"),
    ("monitoring", "monitor"),
    ("music", "speaker", "audio"),
)
_HELP = {
    "ok": True,
    "status": "help",
    "commands": (
        "goals - list active canonical owner goals",
        "status goal_... - inspect a canonical goal",
        "cancel goal_... - cancel a previously listed goal",
        "Cancel my previous TV-control request - unique topic-matched cancellation",
        "goal <your requested outcome> - submit a NEW typed owner goal",
        "quit - exit text console",
    ),
    "warning": (
        "Text approvals for protected change gates are not bypassed. "
        "Never create a second TV goal while the original is still active."
    ),
}


class OwnerTextConversation:
    """Transport-independent deterministic routing for typed owner turns."""

    def __init__(self, tools: Any, conversation: ConversationSession) -> None:
        self._tools = tools
        self._conversation = conversation
        if not conversation.status.value == "active":
            raise ValueError("text conversation must be active")

    @staticmethod
    def _mentioned_topics(text: str) -> tuple[tuple[str, ...], ...]:
        return tuple(
            aliases
            for aliases in _TOPICS
            if any(
                re.search(r"\b" + re.escape(alias) + r"\b", text, re.IGNORECASE)
                for alias in aliases
            )
        )

    @classmethod
    def _select_cancel_target(
        cls, text: str, objectives: list[dict[str, object]]
    ) -> str | None:
        active = [
            item
            for item in objectives
            if item.get("terminal") is not True
            and isinstance(item.get("goal_id"), str)
        ]
        ids = set(_GOAL_ID.findall(text))
        if ids:
            matches = [item for item in active if item["goal_id"] in ids]
            return str(matches[0]["goal_id"]) if len(matches) == 1 else None

        topics = cls._mentioned_topics(text)
        if not topics:
            return str(active[0]["goal_id"]) if len(active) == 1 else None
        candidates = active
        for aliases in topics:
            candidates = [
                item
                for item in candidates
                if any(
                    re.search(
                        r"\b" + re.escape(alias) + r"\b",
                        str(item.get("owner_request") or "")
                        + " "
                        + str(item.get("desired_outcome") or ""),
                        re.IGNORECASE,
                    )
                    for alias in aliases
                )
            ]
        return (
            str(candidates[0]["goal_id"]) if len(candidates) == 1 else None
        )

    async def submit(self, raw_text: str) -> dict[str, object]:
        text = raw_text.strip()
        if not text:
            return {"ok": False, "status": "empty_input"}
        if len(text) > 2048:
            return {"ok": False, "status": "input_too_long"}
        if text.casefold() in {"/help", "help", "?"}:
            return _HELP
        if text.casefold() in {"/quit", "quit", "exit"}:
            return {"ok": True, "status": "exit"}

        # The canonical conversation is shared with GICC voice tools but
        # contains actual typed turns. Never synthesize owner approval speech.
        if text.casefold().startswith("/goal "):
            text = text[6:].strip()
            if not text:
                return {"ok": False, "status": "empty_goal"}
        self._conversation.accept_turn(ConversationRole.USER, text)

        if _LIST.fullmatch(text):
            return await self._tools.list_owner_objectives(None)

        if _STATUS.match(text):
            matches = _GOAL_ID.findall(text)
            if len(matches) != 1:
                return {
                    "ok": False,
                    "status": "exact_goal_id_required",
                    "truth_note": "List goals first and give one exact goal ID.",
                }
            return await self._tools.get_owner_objective_status(None, matches[0])

        if _CANCEL.match(text):
            listed = await self._tools.list_owner_objectives(None)
            if listed.get("ok") is not True:
                return listed
            objectives = listed.get("objectives")
            if not isinstance(objectives, list):
                return {"ok": False, "status": "goal_list_unavailable"}
            target = self._select_cancel_target(text, objectives)
            if target is None:
                return {
                    "ok": False,
                    "status": "ambiguous_cancel_target",
                    "truth_note": (
                        "No goal was cancelled. List goals and use an exact ID "
                        "or a unique matching device/request."
                    ),
                }
            # Reuse the existing audited cancellation, its exact-match guard,
            # and its durable linked-work cleanup. No direct database edits.
            return await self._tools.cancel_owner_goal(None, target)

        # Generic "yes" and other protected approvals must not become goals
        # or silently bypass the dedicated canonical Authority gate.
        if re.fullmatch(r"(?:yes|no|approve|approved|confirm|confirmed)[.!]?", text, re.I):
            return {
                "ok": False,
                "status": "approval_requires_bound_context",
                "truth_note": (
                    "Protected approvals require the existing offer, exact gate "
                    "and Authority verification; generic text cannot approve."
                ),
            }

        # This is the existing real GICC goal-admission pipeline; it may
        # create WorkItems and engineering changes after canonical admission.
        return await self._tools.pursue_owner_goal(None)


def _render(result: dict[str, object]) -> str:
    if result.get("status") == "listed" and isinstance(
        result.get("objectives"), list
    ):
        objectives = result["objectives"]
        if not objectives:
            return "No active owner goals."
        lines = ["Active owner goals:"]
        for item in objectives:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"  {item.get('goal_id')} | {item.get('goal_state')} | "
                f"{item.get('phase')}\n    {item.get('owner_request')}"
            )
        return "\n".join(lines)
    return json.dumps(result, indent=2, ensure_ascii=False, default=str)


async def _run() -> None:
    # The existing production composer is reused to obtain EXACTLY the same
    # capability runtime and GICC/Work stores as voice. Crucially, we never
    # call VoiceRuntimeController.run(), so audio.start() is never invoked.
    from jarvis.config import JarvisConfig
    from jarvis.voice.gicc_tools import GiccAgentTools
    from jarvis.voice.production_runtime import build_production_voice_runtime

    config = JarvisConfig.from_environment()
    if config.gicc_mode.value != "apply" or not config.work_orchestration_enabled:
        raise RuntimeError(
            "Text acquisition requires GICC APPLY and work orchestration enabled."
        )
    controller = build_production_voice_runtime(config)
    gicc = controller._gicc_runtime
    work = controller._work_runtime
    if gicc is None or work is None:
        raise RuntimeError("Canonical GICC/Work runtime unavailable")

    conversation = ConversationSession()
    conversation.start()
    tools = GiccAgentTools(
        gicc.coordinator,
        conversation,
        gicc.store,
        execution_runtime=gicc,
        objective_status=gicc.objective_status,
        telemetry=gicc.telemetry,
    )
    console = OwnerTextConversation(tools, conversation)
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def read_input() -> None:
        while True:
            try:
                line = input("YOU> ")
            except (EOFError, KeyboardInterrupt):
                line = None
            if loop.is_closed():
                return
            loop.call_soon_threadsafe(queue.put_nowait, line)
            if line is None:
                return

    reader = threading.Thread(
        target=read_input, name="jarvis-local-text-input", daemon=True
    )
    gicc.start()
    reader.start()
    print("JARVIS TEXT CONSOLE - same GICC and Work runtime; microphone OFF")
    print("Type 'goals', 'status goal_...', 'cancel goal_...', or 'help'.")
    try:
        while True:
            line = await queue.get()
            if line is None:
                return
            try:
                result = await console.submit(line)
            except Exception:
                LOGGER.exception("Text owner command failed")
                print("JARVIS> Command failed; no completion is being claimed.")
                continue
            print("JARVIS> " + _render(result), flush=True)
            if result.get("status") == "exit":
                return
    finally:
        await gicc.close()
        await work.aclose()
        capability = controller._capability_runtime
        if capability is not None:
            capability.close()
        research = controller._research_service
        if research is not None:
            await research.close()
        memory = controller._memory_runtime
        if memory is not None:
            await memory.close()


def main() -> int:
    try:
        asyncio.run(_run())
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"JARVIS text console failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
