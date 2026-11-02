"""Project conversation memory for native Gemini Live voice (isolated, opt-in).

Native audio generates its own reply, so "capture -> context -> answer" is
enforced by the integration itself, not by the model's goodwill:

1. **Every accepted USER turn is prepared by the application.** When the bridge
   commits a final transcript, routing + durable recording run immediately,
   serialized across sessions, whether or not Gemini ever calls the tool.
2. **The model receives that context through one blocking tool,**
   ``prepare_project_turn`` (no arguments; it returns the already-prepared
   result for the current utterance). The realtime model is configured with
   BLOCKING tool behaviour (Gemini 3.8 Live otherwise defaults to NON_BLOCKING,
   which lets it answer before the result arrives).
3. **Audio is gated per response.** A response segment plays only if Gemini
   received this utterance's context. Otherwise it is interrupted before any
   audio is heard, and Gemini is asked once to call the tool; if that fails too,
   one fixed fallback ("couldn't load project memory") is spoken. One answer per
   utterance is preserved.
4. Jarvis's spoken reply is recorded only for a delivered request, with every
   source delivered in this Gemini session as its evidence (what it may restate).

Routing, recording, provenance, retention, forget and the history grant are the
tested :class:`ProjectConversationCoordinator`. Disabled by default; only
``jarvis.voice.project_voice_lab`` constructs it.
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
_REPAIR_WAIT_SECONDS = 10.0

REPAIR_INSTRUCTIONS = (
    "Before answering the owner's last request you must call prepare_project_turn. "
    "Call it now, without speaking first, then answer from its result."
)
FALLBACK_INSTRUCTIONS = (
    "Say only this, briefly: 'Sorry, I couldn't load the project memory for that. "
    "Please say it again.' Do not answer the request itself."
)
NO_TRANSCRIPT_INSTRUCTIONS = (
    "Say only this, briefly: 'Sorry, I didn't catch that. Please say it again.'"
)

_GUIDANCE = (
    "Answer from this project context and from project history already given in "
    "this conversation. If 'announcement' is non-empty, say it first, exactly. "
    "'action' is what just happened: created, switched (from 'previous_project'), "
    "resumed, continued or new_thread. Never say the owner was already in a "
    "project they were just switched to. History rows with 'from_project' come "
    "from that other project: say so. Only the selected and referenced projects "
    "exist. If the history lacks the answer, say you don't have it."
)


@dataclass
class VoiceProjectMetrics:
    """Content-free counters for comparing against ordinary voice."""

    user_turns: int = 0
    saved_user_turns: int = 0
    prepared: int = 0
    delivered: int = 0
    clarifications: int = 0
    not_saved: int = 0
    failed: int = 0
    duplicate_calls: int = 0
    undelivered_user_turns: int = 0
    unprepared_responses_blocked: int = 0
    repairs: int = 0
    fallbacks: int = 0
    assistant_recorded: int = 0
    assistant_skipped: int = 0
    record_failures: int = 0
    prepare_ms: list[float] = field(default_factory=list)
    packet_bytes: list[int] = field(default_factory=list)
    delivered_bytes: list[int] = field(default_factory=list)

    def snapshot(self) -> dict[str, object]:
        def stats(values):
            if not values:
                return {"count": 0}
            ordered = sorted(values)
            return {
                "count": len(ordered),
                "median": ordered[len(ordered) // 2],
                "max": ordered[-1],
                "sum": round(sum(ordered), 1),
            }

        series = {"prepare_ms", "packet_bytes", "delivered_bytes"}
        data = {k: v for k, v in self.__dict__.items() if k not in series}
        for name in series:
            data[name] = stats(getattr(self, name))
        return data


@dataclass
class _Outcome:
    """What the application prepared for one accepted USER turn."""

    status: str  # ready | clarification | not_saved | failed
    packet: object = None
    decision: object = None
    previous: str | None = None
    question: str = ""
    reason: str = ""


@dataclass
class _Delivered:
    turn: object
    outcome: _Outcome
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
        # One coordinator: every turn of every wake session is prepared in order.
        self.prepare_lock = asyncio.Lock()
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
        LOGGER.info(
            "Voice project memory active | projects=%s | current=%s",
            len({e.selection.project_id for e in catalog.entries}),
            "yes" if catalog.current is not None else "none",
        )

    @staticmethod
    def configure_realtime_model(llm) -> None:
        """Make the project tool genuinely blocking on the realtime model.

        LiveKit declares Gemini 3.8 Live tools NON_BLOCKING by default, so the
        model may keep speaking (or answer) before the tool result arrives.
        Fails closed: a model that cannot be made blocking is not used.
        """
        # Provider SDK use stays inside the approved LiveKit/Gemini adapter.
        from jarvis.voice.livekit_session import require_blocking_realtime_tools

        require_blocking_realtime_tools(llm)

    def session(self, conversation) -> VoiceProjectTurns:
        if self.coordinator is None or self._closed:
            raise RuntimeError("voice project memory is not active")
        return VoiceProjectTurns(self, conversation)

    def spawn(self, coroutine, name="jarvis-project-voice") -> asyncio.Task:
        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def aclose(self) -> None:
        """Let accepted turns and committed replies finish saving, then end the grant."""
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


def model_view(outcome: _Outcome, delivered_ids: dict) -> tuple[dict, tuple[str, ...]]:
    """Compact tool result: only history rows not yet given in this Gemini session.

    Earlier results stay in the live model's context, so re-sending them every
    turn only grows the per-response prompt. Machine fields (ids, revisions,
    omitted-id lists) are not useful to the model and are left out.
    """
    if outcome.status == "clarification":
        return (
            {
                "status": "clarification",
                "question": outcome.question,
                "guidance": "Ask exactly this question. Nothing was created or switched.",
            },
            (),
        )
    if outcome.status == "not_saved":
        return (
            {
                "status": "not_saved",
                "reason": outcome.reason,
                "guidance": "Answer normally without project history. Do not say "
                "this was saved.",
            },
            (),
        )
    if outcome.status != "ready":
        return ({"status": "unavailable", "reason": "project_memory_error"}, ())
    context = json.loads(outcome.packet.context)
    decision = outcome.decision
    fresh, new_ids, already = [], [], 0
    for row in context.get("sources", ()):
        if row["source_id"] in delivered_ids:
            already += 1
            continue
        new_ids.append(row["source_id"])
        item = {
            "role": row["role"],
            "date": row["accepted_at"][:10],
            "text": row["text"],
        }
        if row.get("from_project"):
            item["from_project"] = row["from_project"]
        if row.get("delivery") == "partial":
            item["interrupted"] = True
        fresh.append(item)
    result = {
        "status": "ready",
        "project": decision.title,
        "action": decision.action,
        "announcement": decision.announcement,
        "history": fresh,
        "earlier_history_already_provided": already,
        "coverage": context.get("coverage"),
        "guidance": _GUIDANCE,
    }
    if decision.action == "switched" and outcome.previous:
        result["previous_project"] = outcome.previous
    if decision.reference_titles:
        result["referenced_projects"] = list(decision.reference_titles)
    return result, tuple(new_ids)


class VoiceProjectTurns:
    """One wake session (one Gemini Live session) of project voice turns."""

    def __init__(self, owner: VoiceProjectMemory, conversation) -> None:
        self._owner = owner
        self._conversation = conversation
        self._turn_ready = asyncio.Event()
        self._outcomes: dict[str, asyncio.Future] = {}
        self._seen_user: set[str] = set()
        self._recorded_assistant: set[str] = set()
        # Every source given to THIS Gemini session, in delivery order.
        self._delivered_ids: dict[str, None] = {}
        self._delivered: _Delivered | None = None
        self._delivered_epoch: int | None = None
        self._delivered_turns: set[str] = set()
        self._fallback_key: tuple | None = None
        self._repair_attempts: dict[tuple, int] = {}
        self._repairing: set[tuple] = set()
        self._speech = None
        self._blocked_speech = None
        self._session = None
        self._closed = False

    @property
    def metrics(self) -> VoiceProjectMetrics:
        return self._owner.metrics

    # -- wiring ---------------------------------------------------------------

    def bind_session(self, session) -> None:
        """The AgentSession, used only to interrupt/re-request a gated reply."""
        self._session = session

    def observe_speech(self, event) -> None:
        self._speech = getattr(event, "speech_handle", None)

    # -- bridge observers (synchronous; they never answer) --------------------

    def observe_turn(self, turn) -> None:
        if turn.role is ConversationRole.USER:
            if turn.turn_id in self._seen_user:
                return
            self._seen_user.add(turn.turn_id)
            self.metrics.user_turns += 1
            # Durable capture does not wait for, or depend on, the model.
            self._outcome_future(turn)
            self._turn_ready.set()
            return
        if turn.role is not ConversationRole.ASSISTANT or self._closed:
            return
        if turn.turn_id in self._recorded_assistant:
            return
        delivered = self._delivered
        if delivered is None or self._latest_user_before(turn) is not delivered.turn:
            # Gated/unheard reply, preamble, or reply to an undelivered turn.
            self.metrics.assistant_skipped += 1
            return
        self._recorded_assistant.add(turn.turn_id)
        evidence = tuple(self._delivered_ids)
        self._owner.spawn(
            self._record_assistant(delivered.outcome, turn, evidence),
            name="jarvis-project-voice-reply",
        )

    def observe_activity(self) -> None:
        """New user speech: wake any waiting tool so it can re-check currentness."""
        self._turn_ready.set()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._turn_ready.set()
        for user in self._user_turns():
            if user.turn_id not in self._delivered_turns:
                self.metrics.undelivered_user_turns += 1
        # Saves already scheduled keep running; VoiceProjectMemory.aclose drains them.

    # -- application-owned preparation ---------------------------------------

    def _outcome_future(self, turn) -> asyncio.Future:
        future = self._outcomes.get(turn.turn_id)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            self._outcomes[turn.turn_id] = future
            self._owner.spawn(
                self._prepare_turn(turn, future), name="jarvis-project-voice-turn"
            )
        return future

    async def _prepare_turn(self, turn, future) -> None:
        owner = self._owner
        started = monotonic()
        try:
            async with owner.prepare_lock:
                outcome = await self._run_prepare(turn)
        except asyncio.CancelledError:
            if not future.done():
                future.set_result(_Outcome("failed", reason="cancelled"))
            raise
        if outcome.status == "ready":
            owner.metrics.saved_user_turns += 1
            owner.metrics.prepared += 1
            owner.metrics.prepare_ms.append(round((monotonic() - started) * 1000, 1))
            owner.metrics.packet_bytes.append(len(outcome.packet.context.encode()))
        if not future.done():
            future.set_result(outcome)

    async def _run_prepare(self, turn) -> _Outcome:
        coordinator = self._owner.coordinator
        access = self._owner.access
        try:
            catalog = await access.catalog()
            previous = next(
                (e.title for e in catalog.entries if e.selection == catalog.current),
                None,
            )
            # Durability: an accepted turn is saved even if a newer utterance or
            # the end of the wake session arrives meanwhile. The coordinator
            # still requires a current history grant.
            packet = await coordinator.prepare_reply(
                self._conversation, turn, authorize=lambda: True
            )
        except ProjectClarificationRequired as exc:
            self.metrics.clarifications += 1
            return _Outcome("clarification", question=exc.question)
        except PermissionError:
            stage = coordinator.stage
            if stage in {"retention_paused", "source_not_eligible"}:
                self.metrics.not_saved += 1
                return _Outcome("not_saved", reason=stage)
            self.metrics.failed += 1
            LOGGER.warning("Project voice turn not saved | stage=%s", stage)
            return _Outcome("failed", reason="permission")
        except (ValueError, RuntimeError, OSError) as exc:
            self.metrics.failed += 1
            LOGGER.warning(
                "Project voice turn not saved | stage=%s | error=%s",
                coordinator.stage,
                type(exc).__name__,
            )
            return _Outcome("failed", reason="error")
        decision = coordinator.last_decision
        LOGGER.info(
            "Project voice turn saved | action=%s | references=%s | sources=%s",
            decision.action,
            len(decision.references),
            len(packet.source_ids),
        )
        return _Outcome("ready", packet=packet, decision=decision, previous=previous)

    # -- helpers --------------------------------------------------------------

    def _user_turns(self):
        return [t for t in self._conversation.turns if t.role is ConversationRole.USER]

    def _latest_user(self):
        users = self._user_turns()
        return users[-1] if users else None

    def _latest_user_before(self, turn):
        latest = None
        for item in self._conversation.turns:
            if item is turn:
                return latest
            if item.role is ConversationRole.USER:
                latest = item
        return None

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
        try:
            source = await asyncio.wait_for(
                self._wait_source(activity), timeout=_SOURCE_WAIT_SECONDS
            )
        except TimeoutError:
            source = None
        if source is None:
            self._mark_delivered(activity, None)
            return {"status": "unavailable", "reason": "no_current_request"}
        delivered = self._delivered
        if delivered is not None and delivered.turn is source:
            self.metrics.duplicate_calls += 1
            return delivered.result
        outcome = await asyncio.shield(self._outcome_future(source))
        if not self._active() or self._conversation.user_activity_epoch != activity:
            return {"status": "unavailable", "reason": "request_changed"}
        result, new_ids = model_view(outcome, self._delivered_ids)
        for identity in new_ids:
            self._delivered_ids[identity] = None
        self._delivered = _Delivered(source, outcome, result)
        self._delivered_turns.add(source.turn_id)
        self._mark_delivered(activity, source)
        self.metrics.delivered += 1
        self.metrics.delivered_bytes.append(
            len(json.dumps(result, ensure_ascii=False).encode())
        )
        return result

    def _mark_delivered(self, epoch, source) -> None:
        # The model now holds this utterance's outcome (or knows it has none).
        self._delivered_epoch = epoch

    # -- audio gate decision --------------------------------------------------

    def _key(self, epoch):
        """(activity epoch, utterance): what a response would be answering."""
        latest = self._latest_user()
        if latest is not None and latest.user_activity_epoch == (epoch or None):
            return epoch, latest.turn_id
        return epoch, None

    def _is_delivered(self, key) -> bool:
        epoch, turn_id = key
        if turn_id is None:
            # No transcript yet: only if the tool already ran in this activity.
            return self._delivered_epoch == epoch
        return turn_id in self._delivered_turns

    def allow_response_audio(self) -> bool:
        """Decide one response segment: play only a context-informed answer."""
        epoch = self._conversation.user_activity_epoch
        if epoch == 0 or self._closed:
            # Before any owner speech (wake acknowledgement), nothing to prepare.
            return True
        key = self._key(epoch)
        if key == self._fallback_key or self._is_delivered(key):
            return True
        # Includes a newer utterance in the same activity (local VAD missed
        # its start): it was never given to the model, so it is gated too.
        handle = self._speech
        if handle is not None and handle is self._blocked_speech:
            return False  # trailing frames of a response already blocked
        self._blocked_speech = handle
        self.metrics.unprepared_responses_blocked += 1
        if handle is not None:
            try:
                handle.interrupt()
            except Exception:  # noqa: BLE001 - a non-interruptible speech is just muted
                LOGGER.info("Unprepared project response could not be interrupted")
        if key not in self._repairing:
            self._repairing.add(key)
            self._owner.spawn(self._repair(key, handle), name="jarvis-project-repair")
        return False

    async def _repair(self, blocked_key, handle) -> None:
        epoch = blocked_key[0]
        try:
            if handle is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(handle.wait_for_playout()), 5)
                except Exception:  # noqa: BLE001 - only a pacing wait
                    LOGGER.debug("Blocked response did not finish within 5 s")
            source = None
            try:
                source = await asyncio.wait_for(
                    self._wait_source(epoch), timeout=_SOURCE_WAIT_SECONDS
                )
            except TimeoutError:
                source = None
            if not self._still(epoch):
                return
            if source is not None:
                # Saving never depends on this repair; wait so the tool is instant.
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._outcome_future(source)),
                        _REPAIR_WAIT_SECONDS,
                    )
                except TimeoutError:
                    pass
            key = (epoch, source.turn_id if source is not None else None)
            if not self._still(epoch) or self._is_delivered(key):
                return
            attempts = self._repair_attempts.get(key, 0)
            self._repair_attempts[key] = attempts + 1
            if source is None:
                self._fallback(key, NO_TRANSCRIPT_INSTRUCTIONS)
            elif attempts == 0:
                self.metrics.repairs += 1
                LOGGER.info(
                    "Project voice: model answered without context; re-requesting"
                )
                self._generate(REPAIR_INSTRUCTIONS)
            else:
                self._fallback(key, FALLBACK_INSTRUCTIONS)
        finally:
            self._repairing.discard(blocked_key)

    def _still(self, epoch) -> bool:
        return self._active() and self._conversation.user_activity_epoch == epoch

    def _fallback(self, key, instructions) -> None:
        self.metrics.fallbacks += 1
        self._fallback_key = key
        LOGGER.warning("Project voice: speaking fallback without project context")
        self._generate(instructions)

    def _generate(self, instructions) -> None:
        if self._session is None:
            return
        try:
            self._session.generate_reply(
                instructions=instructions, allow_interruptions=True
            )
        except Exception as exc:  # noqa: BLE001 - voice continues; next turn retries
            LOGGER.warning(
                "Project voice re-request failed | error=%s", type(exc).__name__
            )

    # -- recording ------------------------------------------------------------

    async def _record_assistant(self, outcome: _Outcome, turn, evidence) -> None:
        if outcome.status != "ready":
            # Clarification/excluded/failed: no project context was used.
            return
        try:
            await self._owner.coordinator.record_spoken_assistant(
                self._conversation, outcome.packet, turn, evidence=evidence
            )
            self.metrics.assistant_recorded += 1
        except Exception as exc:  # noqa: BLE001 - recording failure must not stop voice
            self.metrics.record_failures += 1
            LOGGER.warning(
                "Project voice reply not recorded | error=%s", type(exc).__name__
            )


_TOOL_DESCRIPTION = (
    "Call this FIRST, before answering, for every owner request while project "
    "memory is on. It takes no arguments: it returns the project context the "
    "application already prepared and saved from the owner's exact words. "
    "Only explicit project commands select or create a project. Then answer "
    "from the result."
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
