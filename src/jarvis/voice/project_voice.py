"""Project conversation memory for native Gemini Live voice (isolated, opt-in).

Native audio generates its own reply, so the text path's "capture -> context ->
answer" order is enforced at the only synchronous boundary the model has: one
blocking tool, ``prepare_project_turn``, which Gemini calls before it answers.

* The tool takes no arguments. It waits for the bridge's committed canonical
  USER transcript and never uses the model's restatement as a source.
* Routing, recording, provenance, retention, forget and the history grant are
  the tested :class:`ProjectConversationCoordinator` from the text lab.
* Jarvis's spoken reply is recorded only when the bridge commits that
  ASSISTANT turn after a prepared request and before any newer USER turn.
  Unprepared turns are counted, never recorded, and never answered from here.
* Nothing in this module produces an answer, so it cannot race the model.

Disabled by default. Only ``jarvis.voice.project_voice_lab`` constructs it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic
from uuid import uuid4

from livekit.agents import function_tool

from jarvis.conversation import ConversationRole, ConversationStatus
from jarvis.memory.project_routing import ProjectClarificationRequired

LOGGER = logging.getLogger(__name__)

_SOURCE_WAIT_SECONDS = 3.0

_GUIDANCE = (
    "Answer from this project context. If 'announcement' is non-empty, say it "
    "first, exactly. Rows with 'from_project' come from that other project: say "
    "so. Only the selected project and listed referenced projects exist; never "
    "claim a project was created, switched or saved unless the announcement "
    "says so. If the context lacks the answer, say you don't have it."
)


@dataclass
class VoiceProjectMetrics:
    """Content-free counters for comparing against ordinary voice."""

    user_turns: int = 0
    prepared: int = 0
    clarifications: int = 0
    not_saved: int = 0
    interrupted: int = 0
    failed: int = 0
    duplicate_calls: int = 0
    unprepared_user_turns: int = 0
    assistant_recorded: int = 0
    assistant_skipped: int = 0
    record_failures: int = 0
    prepare_ms: list[float] = field(default_factory=list)
    context_tokens: list[int] = field(default_factory=list)

    def snapshot(self) -> dict[str, object]:
        def stats(values):
            if not values:
                return {"count": 0}
            ordered = sorted(values)
            return {
                "count": len(ordered),
                "median": ordered[len(ordered) // 2],
                "max": ordered[-1],
            }

        data = {
            k: v
            for k, v in self.__dict__.items()
            if k not in {"prepare_ms", "context_tokens"}
        }
        data["prepare_ms"] = stats(self.prepare_ms)
        data["context_tokens"] = stats(self.context_tokens)
        return data


@dataclass
class _Prepared:
    turn: object
    packet: object
    result: dict


class VoiceProjectMemory:
    """Runtime-scoped owner of the project history grant and coordinator."""

    def __init__(
        self,
        memory_runtime,
        capability_runtime,
        *,
        source_clearance: Callable[[object], bool],
        provider: str = "gemini",
    ) -> None:
        if not callable(source_clearance):
            raise TypeError("original-history source clearance required")
        self._memory = memory_runtime
        self._capability = capability_runtime
        self._clearance = source_clearance
        self._provider = provider
        self.access = None
        self.coordinator = None
        self.metrics = VoiceProjectMetrics()
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    async def start(self, *, open_grant=None) -> None:
        """Open the project-history grant (Windows Hello) after memory starts."""
        from jarvis.memory.project_access import ProjectArchiveAccess
        from jarvis.voice.project_conversation import ProjectConversationCoordinator

        if self.access is not None:
            return
        authority = self._capability.conversation_history_authority
        self._memory.bind_conversation_history_authority(authority)
        opener = open_grant or (
            lambda: authority.open("voice-" + uuid4().hex, self._provider)
        )
        grant = await asyncio.to_thread(opener)
        self.access = ProjectArchiveAccess(
            self._memory.project_conversations, authority=authority, grant=grant
        )
        self.coordinator = ProjectConversationCoordinator(
            self.access, source_clearance=self._clearance
        )
        catalog = await self.access.catalog()
        current = next(
            (e.title for e in catalog.entries if e.selection == catalog.current), None
        )
        LOGGER.info(
            "Voice project memory active | projects=%s | current=%s",
            len({e.selection.project_id for e in catalog.entries}),
            "yes" if current else "none",
        )

    def session(self, conversation) -> VoiceProjectTurns:
        if self.coordinator is None or self._closed:
            raise RuntimeError("voice project memory is not active")
        return VoiceProjectTurns(self, conversation)

    def _spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine, name="jarvis-project-voice-record")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def aclose(self) -> None:
        """Let committed recordings finish, then end the grant."""
        if self._closed:
            return
        self._closed = True
        await self.drain()
        if self.coordinator is not None:
            self.coordinator.invalidate("shutdown")
        if self.access is not None:
            try:
                await asyncio.to_thread(
                    self.access.authority.revoke, self.access.grant, "shutdown"
                )
            except Exception:  # noqa: BLE001 - shutdown continues; grant expires
                LOGGER.warning("Voice project grant revoke failed during shutdown")
        LOGGER.info(
            "Voice project memory summary | %s",
            json.dumps(self.metrics.snapshot(), sort_keys=True),
        )


class VoiceProjectTurns:
    """One wake session: accepted turns in, one prepared context per USER turn."""

    def __init__(self, owner: VoiceProjectMemory, conversation) -> None:
        self._owner = owner
        self._conversation = conversation
        self._lock = asyncio.Lock()
        self._turn_ready = asyncio.Event()
        self._prepared: _Prepared | None = None
        self._recorded_assistant: set[str] = set()
        self._seen_user: set[str] = set()
        self._closed = False

    @property
    def metrics(self) -> VoiceProjectMetrics:
        return self._owner.metrics

    # -- bridge observers (synchronous, never answer) -------------------------

    def observe_turn(self, turn) -> None:
        if self._closed:
            return
        if turn.role is ConversationRole.USER:
            if turn.turn_id not in self._seen_user:
                self._seen_user.add(turn.turn_id)
                # Count the turn this one supersedes if it was never prepared.
                previous = self._previous_user_turn(turn)
                if previous is not None and not self._was_prepared(previous):
                    self.metrics.unprepared_user_turns += 1
                self.metrics.user_turns += 1
            self._turn_ready.set()
            return
        if turn.role is not ConversationRole.ASSISTANT:
            return
        if turn.turn_id in self._recorded_assistant:
            return
        prepared = self._prepared
        if prepared is None or self._latest_user_before(turn) is not prepared.turn:
            # Preamble before the tool, an unprepared turn, or a reply that
            # arrived after a newer user turn: never attribute it to a request.
            self.metrics.assistant_skipped += 1
            return
        self._recorded_assistant.add(turn.turn_id)
        self._owner._spawn(self._record_assistant(prepared, turn))

    def observe_activity(self) -> None:
        """New user speech: wake any waiting tool so it can re-check currentness."""
        self._turn_ready.set()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._turn_ready.set()
        latest = self._latest_user()
        if latest is not None and not self._was_prepared(latest):
            self.metrics.unprepared_user_turns += 1
        coordinator = self._owner.coordinator
        if coordinator is not None:
            coordinator.invalidate("voice_session_closed")

    # -- helpers --------------------------------------------------------------

    def _user_turns(self):
        return [t for t in self._conversation.turns if t.role is ConversationRole.USER]

    def _latest_user(self):
        users = self._user_turns()
        return users[-1] if users else None

    def _previous_user_turn(self, turn):
        users = self._user_turns()
        index = next((i for i, t in enumerate(users) if t is turn), None)
        return users[index - 1] if index else None

    def _latest_user_before(self, turn):
        latest = None
        for item in self._conversation.turns:
            if item is turn:
                return latest
            if item.role is ConversationRole.USER:
                latest = item
        return None

    def _was_prepared(self, turn) -> bool:
        return self._prepared is not None and self._prepared.turn is turn

    def _active(self) -> bool:
        return (
            not self._closed
            and not self._owner._closed
            and self._conversation.status is ConversationStatus.ACTIVE
        )

    async def _wait_source(self, activity):
        while self._active():
            if self._conversation.user_activity_epoch != activity:
                return None
            turn = self._latest_user()
            if turn is not None and turn.user_activity_epoch == (activity or None):
                return turn
            self._turn_ready.clear()
            await self._turn_ready.wait()
        return None

    # -- the blocking tool ----------------------------------------------------

    async def prepare(self) -> dict:
        activity = self._conversation.user_activity_epoch
        started = monotonic()
        try:
            source = await asyncio.wait_for(
                self._wait_source(activity), timeout=_SOURCE_WAIT_SECONDS
            )
        except TimeoutError:
            source = None
        if source is None:
            self.metrics.interrupted += 1
            return {"status": "unavailable", "reason": "no_current_request"}
        async with self._lock:
            prepared = self._prepared
            if prepared is not None and prepared.turn is source:
                # Gemini may retry or re-issue the call for the same utterance.
                self.metrics.duplicate_calls += 1
                return prepared.result

            def current() -> bool:
                return (
                    self._active()
                    and self._latest_user() is source
                    and self._conversation.user_activity_epoch == activity
                )

            coordinator = self._owner.coordinator
            try:
                packet = await coordinator.prepare_reply(
                    self._conversation, source, authorize=current
                )
            except ProjectClarificationRequired as exc:
                self.metrics.clarifications += 1
                result = {
                    "status": "clarification",
                    "question": exc.question,
                    "guidance": "Ask exactly this question. Nothing was created or switched.",
                }
                self._prepared = _Prepared(source, None, result)
                return result
            except asyncio.CancelledError:
                coordinator.invalidate("tool_cancelled")
                self.metrics.interrupted += 1
                raise
            except PermissionError:
                stage = coordinator.stage
                if stage in {"retention_paused", "source_not_eligible"}:
                    self.metrics.not_saved += 1
                    result = {
                        "status": "not_saved",
                        "reason": stage,
                        "guidance": "Answer normally without project history. "
                        "Do not say this was saved.",
                    }
                    self._prepared = _Prepared(source, None, result)
                    return result
                if not current():
                    self.metrics.interrupted += 1
                    return {"status": "unavailable", "reason": "request_changed"}
                self.metrics.failed += 1
                LOGGER.warning("Project voice prepare failed | stage=%s", stage)
                return {"status": "unavailable", "reason": "project_memory_error"}
            except (ValueError, RuntimeError, OSError) as exc:
                self.metrics.failed += 1
                LOGGER.warning(
                    "Project voice prepare failed | stage=%s | error=%s",
                    coordinator.stage,
                    type(exc).__name__,
                )
                return {"status": "unavailable", "reason": "project_memory_error"}
            decision = coordinator.last_decision
            result = {
                "status": "ready",
                "project": decision.title,
                "announcement": decision.announcement,
                "context": json.loads(packet.context),
                "guidance": _GUIDANCE,
            }
            self._prepared = _Prepared(source, packet, result)
            elapsed = (monotonic() - started) * 1000
            self.metrics.prepared += 1
            self.metrics.prepare_ms.append(round(elapsed, 1))
            self.metrics.context_tokens.append(packet.estimated_tokens)
            LOGGER.info(
                "Project voice prepared | action=%s | references=%s | sources=%s | "
                "tokens=%s | prepare_ms=%.1f",
                decision.action,
                len(decision.references),
                len(packet.source_ids),
                packet.estimated_tokens,
                elapsed,
            )
            return result

    async def _record_assistant(self, prepared: _Prepared, turn) -> None:
        if prepared.packet is None:
            # Clarification or excluded request: no project context was used,
            # so there is nothing project-derived to record.
            return
        try:
            await self._owner.coordinator.record_spoken_assistant(
                self._conversation, prepared.packet, turn
            )
            self.metrics.assistant_recorded += 1
        except Exception as exc:  # noqa: BLE001 - recording failure must not stop voice
            self.metrics.record_failures += 1
            LOGGER.warning(
                "Project voice reply not recorded | error=%s", type(exc).__name__
            )


_TOOL_DESCRIPTION = (
    "Call this FIRST, before answering, for every owner request while project "
    "memory is on. It takes no arguments: it reads the owner's exact words, "
    "selects or creates a project only for explicit project commands, saves "
    "the turn and returns that project's context. Then answer from the result."
)


class VoiceProjectTools:
    def __init__(self, turns: VoiceProjectTurns) -> None:
        self._turns = turns

    @property
    def tools(self) -> list:
        return [self.prepare_project_turn]

    @function_tool(
        raw_schema={
            "name": "prepare_project_turn",
            "description": _TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        }
    )
    async def prepare_project_turn(self, raw_arguments: dict[str, object]) -> dict:
        if raw_arguments not in ({}, None):
            return {"status": "denied", "reason": "no_arguments_accepted"}
        return await self._turns.prepare()
