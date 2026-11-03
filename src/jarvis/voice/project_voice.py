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
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from time import monotonic
from uuid import uuid4

from livekit.agents import function_tool

from jarvis.conversation import ConversationRole, ConversationStatus
from jarvis.memory.project_routing import (
    ProjectClarificationRequired,
    needs_project_routing,
)
from jarvis.voice.voice_output_safety import register_internal_text

LOGGER = logging.getLogger(__name__)

_SOURCE_WAIT_SECONDS = 3.0
_REPAIR_WAIT_SECONDS = 10.0
# Fast path: how long the first response frame may wait for streaming
# recognition before the utterance is treated as needing the tool path.
_FAST_PATH_TEXT_WAIT_SECONDS = 0.35
# Session preload bounds: recent current-project rows given once per wake.
PRELOAD_ROWS = 12
PRELOAD_MAX_CHARS = 3000
_FAST_REPLY_WAIT_SECONDS = 15.0
# After a denied or timed-out renewal, do not ask again for this long.
RENEWAL_COOLDOWN_SECONDS = 300.0
# First wake after a lock/unlock waits this long for the fresh Hello approval
# before continuing as ordinary voice (the renewal itself may finish later).
RENEWAL_WAIT_SECONDS = 20.0
PAUSED_NOTICE_INSTRUCTIONS = (
    "Say only this, briefly, then listen: 'Project memory is paused, so I won't "
    "remember this conversation. It resumes after Windows Hello approval.'"
)
# Long-term recall: archive searches per utterance, hits and characters given.
SEARCHES_PER_UTTERANCE = 2
SEARCH_HITS = 8
SEARCH_MAX_CHARS = 2400
_FORGET_VERB = re.compile(
    r"\b(?:forget|delete|erase|remove|wipe|bh[uo]+l|mita)\w*", re.IGNORECASE
)
FORGET_INCOMPLETE_INSTRUCTIONS = (
    "Say only this, briefly: 'I removed the saved fact, but I could not remove "
    "it from our saved conversation yet. Please ask me to forget it again.'"
)
# After a canonical forget, the saved conversation must follow within this time,
# else the honest partial-forget notice above is spoken.
FORGET_HISTORY_SECONDS = 12.0
FORGET_HISTORY_NUDGE = (
    "The owner asked to forget something and the saved personal fact was "
    "removed. Now also call forget_saved_history with the distinctive words the "
    "owner used, then confirm briefly without repeating them."
)

# Conversation-control tools whose acknowledgement needs no project context.
CONTROL_TOOLS = frozenset({"enter_standby"})

# Repair by delivery: the application itself gives Gemini the prepared context
# (no reliance on the model calling a tool), then asks for the answer.
REPAIR_ANSWER_INSTRUCTIONS = (
    "Project memory for the owner's last request was just added to this "
    "conversation. Answer that request now, briefly, from it. Speak only the "
    "answer to the owner. Do not repeat a tool call that already ran."
)
# If a re-request produces no audible reply within this time, speak the fallback
# rather than leaving the owner in silence until the session times out.
REPAIR_RESPONSE_SECONDS = 8.0
REPAIR_INSTRUCTIONS = (
    "Before answering the owner's last request you must call prepare_project_turn. "
    "Call it now, without speaking first, then answer from its result."
)
FALLBACK_INSTRUCTIONS = (
    "Say only this, briefly: 'Sorry, I couldn't load the project memory for that. "
    "Please say it again.' Do not answer the request itself."
)
CORRECTION_INSTRUCTIONS = (
    "Say only this, briefly: 'Correction: {what} You are in {project}.' "
    "Do not add anything else."
)
NO_TRANSCRIPT_INSTRUCTIONS = (
    "Say only this, briefly: 'Sorry, I didn't catch that. Please say it again.'"
)

_GUIDANCE = (
    "Say a non-empty 'announcement' first, exactly. An empty one means do not "
    "mention opening, creating or selecting any project; just answer. 'action' "
    "is what just happened; after 'switched' the owner came from "
    "'previous_project', never say they were already there. Rows with "
    "'from_project' come from that project: say so. If the history lacks the "
    "answer, say you don't have it."
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
    false_claims: int = 0
    corrections: int = 0
    paused_sessions: int = 0
    renewals: int = 0
    renewal_failures: int = 0
    fast_path_turns: int = 0
    tool_path_turns: int = 0
    late_routing: int = 0
    history_searches: int = 0
    history_forgets: int = 0
    search_ms: list[float] = field(default_factory=list)
    search_bytes: list[int] = field(default_factory=list)
    preloads: int = 0
    preload_bytes: list[int] = field(default_factory=list)
    undelivered_user_turns: int = 0
    unprepared_responses_blocked: int = 0
    repairs: int = 0
    repair_deliveries: int = 0
    repair_timeouts: int = 0
    unplayed_replays: int = 0
    fast_context_syncs: int = 0
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

        series = {
            "prepare_ms",
            "packet_bytes",
            "delivered_bytes",
            "preload_bytes",
            "search_ms",
            "search_bytes",
        }
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
        diagnostics=None,
        fast_path: bool = True,
        required: bool = True,
    ) -> None:
        if not callable(source_clearance):
            raise TypeError("original-history source clearance required")
        # Lab-only VoiceDiagnostics (explicit --record-diagnostics), else None.
        self.diagnostics = diagnostics
        # Ordinary turns answered from preloaded context (no tool round trip).
        self.fast_path = bool(fast_path)
        # The lab stops if Windows Hello is denied (required). Production voice
        # continues as ordinary Jarvis without project memory instead.
        self.required = bool(required)
        self._paused_logged = False
        self._opener = None
        self._renewing = None
        self._renew_after = 0.0
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

        if self.access is not None:
            return
        authority = self._capability.conversation_history_authority
        self._memory.bind_conversation_history_authority(authority)
        opener = open_grant or (
            lambda: authority.open("voice-" + uuid4().hex, self._provider)
        )
        self._opener = opener
        grant = await asyncio.to_thread(opener)
        self._attach(grant)
        catalog = await self.access.catalog()
        LOGGER.info(
            "Voice project memory active | projects=%s | current=%s",
            len({e.selection.project_id for e in catalog.entries}),
            "yes" if catalog.current is not None else "none",
        )

    def _attach(self, grant) -> None:
        from jarvis.memory.project_access import ProjectArchiveAccess
        from jarvis.voice.project_conversation import ProjectConversationCoordinator

        authority = self._capability.conversation_history_authority
        self.access = ProjectArchiveAccess(
            self._memory.project_conversations, authority=authority, grant=grant
        )
        self.coordinator = ProjectConversationCoordinator(
            self.access, source_clearance=self._clearance
        )

    def request_renewal(self) -> bool:
        """Ask for a fresh grant (Windows Hello) after the old one lapsed.

        Runs in the background at an eligible wake: that wake stays ordinary
        voice, later wakes use the new grant. The lapsed grant is revoked and
        never reused. After a denial or timeout, the owner is not asked again
        for RENEWAL_COOLDOWN_SECONDS.
        """
        if (
            self._opener is None
            or self._closed
            or self._renewing is not None
            or monotonic() < self._renew_after
        ):
            return False
        self._renewing = self.spawn(self._renew(), name="jarvis-project-renew")
        return True

    async def _renew(self) -> None:
        old_access, old_coordinator = self.access, self.coordinator
        try:
            if old_coordinator is not None:
                old_coordinator.invalidate("grant_renewal")
            try:
                await asyncio.to_thread(
                    old_access.authority.revoke, old_access.grant, "continuity_lost"
                )
            except Exception:  # noqa: BLE001 - it is already inactive
                LOGGER.debug("Lapsed project grant revoke failed")
            grant = await asyncio.to_thread(self._opener)
            if self._closed:
                await asyncio.to_thread(old_access.authority.revoke, grant, "shutdown")
                return
            self._attach(grant)
            self._paused_logged = False
            self.metrics.renewals += 1
            self._runtime_event("renewal_succeeded")
            LOGGER.info("Voice project memory renewed with a fresh Windows Hello grant")
        except Exception as exc:  # noqa: BLE001 - ordinary voice continues
            self.metrics.renewal_failures += 1
            self._renew_after = monotonic() + RENEWAL_COOLDOWN_SECONDS
            self._runtime_event("renewal_failed", error=type(exc).__name__)
            LOGGER.warning(
                "Voice project memory renewal failed; ordinary voice continues | "
                "error=%s",
                type(exc).__name__,
            )
        finally:
            self._renewing = None

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

    def available(self) -> bool:
        """Whether a new wake session can use project memory.

        The history grant ends when Windows session continuity changes (lock,
        user switch). It is never reopened silently: a fresh Windows Hello
        approval is requested and the wake session starts AT ONCE, so the
        owner's speech is captured. Its turns wait (bounded) for the approval
        before anything is saved or answered with project context; see
        :meth:`VoiceProjectTurns._ready`. During the cooldown after a denied
        renewal the wake is ordinary voice.
        """
        if self._grant_current():
            return True
        if self.access is None:
            return False
        if not self._paused_logged:
            self._paused_logged = True
            LOGGER.warning(
                "Voice project memory paused: history grant no longer current; "
                "requesting a fresh Windows Hello approval"
            )
        if self.request_renewal():
            self._runtime_event("renewal_requested")
        if self._renewing is not None:
            return True  # pending: the session waits for the approval
        self.metrics.paused_sessions += 1
        return False

    def _grant_current(self) -> bool:
        if self.access is None or self._closed:
            return False
        try:
            return bool(self.access.current())
        except Exception:  # noqa: BLE001 - unavailable OS evidence fails closed
            return False

    async def prepare_wake(self, timeout: float | None = None) -> str | None:
        """Before an owner wake session: start a lapsed grant's renewal.

        Never blocks the wake: blocking here lost the owner's first words while
        the Hello prompt was open (live qualification at 8155df0d). The
        session's own turns wait for the approval instead (bounded).
        """
        del timeout
        if (
            self.access is not None
            and not self._closed
            and not self._grant_current()
            and self.request_renewal()
        ):
            self._runtime_event("renewal_requested")
        return None

    async def wait_ready(self, deadline: float) -> bool:
        """Whether the grant is current, waiting for a pending renewal until
        ``deadline`` (monotonic). Never extends or reuses a grant."""
        task = self._renewing
        if task is not None and not self._grant_current():
            remaining = deadline - monotonic()
            if remaining > 0:
                try:
                    await asyncio.wait_for(asyncio.shield(task), remaining)
                except TimeoutError:
                    pass
        return self._grant_current()

    def _runtime_event(self, kind, **fields) -> None:
        diagnostics = self.diagnostics
        event = getattr(diagnostics, "runtime_event", None)
        if callable(event):
            try:
                event(kind, **fields)
            except Exception:  # noqa: BLE001 - diagnostics never affect voice
                LOGGER.warning("Voice diagnostics runtime hook failed")

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
        # Rows from a project the question names are targeted evidence for
        # THIS answer: always resent, even if given earlier in the session
        # (acceptance run 7ab7ad answered only half of a cross-project status).
        if row["source_id"] in delivered_ids and not row.get("from_project"):
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
    changed = decision.action in {"created", "switched", "new_thread"}
    result = {
        "status": "ready",
        "project": decision.title,
        "action": decision.action,
        "project_changed": changed,
        "announcement": decision.announcement,
        "history": fresh,
        "earlier_history_already_provided": already,
        "coverage": context.get("coverage"),
        "guidance": _GUIDANCE,
    }
    if not changed:
        result["note"] = (
            "No project was created or switched for this request. Do not say "
            "that one was; the owner is still in '" + decision.title + "'."
        )
    if decision.action == "switched" and outcome.previous:
        result["previous_project"] = outcome.previous
    if decision.reference_titles:
        result["referenced_projects"] = list(decision.reference_titles)
    if decision.ambiguous_reference_titles:
        result["ambiguous_projects"] = list(decision.ambiguous_reference_titles)
        result["ambiguity_note"] = (
            "The owner's words could mean any of these projects; none was read. "
            "Ask which one they mean before answering about it."
        )
    return result, tuple(new_ids)


def _preload_rows(sources, *, exclude) -> list:
    """Newest-first selection of whole rows within the preload budget.

    Rows are never truncated (a shortened row would be marked as delivered and
    then never resent). Rows already given to this Gemini session, or spoken
    in it (Gemini heard those itself), are skipped: no context is sent twice.
    """
    chosen, total = [], 0
    for source in reversed(tuple(sources)):
        event = source.event
        if event.event_id in exclude:
            continue
        size = len(event.text) + 24
        if size > PRELOAD_MAX_CHARS:
            continue  # can never fit whole; the tool can still give it
        if total + size > PRELOAD_MAX_CHARS:
            break
        total += size
        chosen.append(source)
    chosen.reverse()
    return chosen


def _preload_message(title, rows, sources) -> str:
    """Compact, clearly labelled evidence: one line per saved row."""
    if title is None:
        return ""
    lines = [
        "[Project memory from Jarvis, not speech from the owner. Do not reply "
        "to this message.] Current project: " + title + "."
    ]
    if rows:
        older = len(tuple(sources)) > len(rows)
        lines.append(
            "Recent saved history, oldest first"
            + (
                "; older history exists: search_project_history finds it"
                if older
                else ""
            )
            + ":"
        )
        for source in rows:
            event = source.event
            who = "owner" if event.role == "user" else "Jarvis"
            mark = " (interrupted)" if event.delivery == "partial" else ""
            lines.append(
                f"- {event.accepted_at.date().isoformat()} {who}: {event.text}{mark}"
            )
    else:
        lines.append("No new saved history to show.")
    return "\n".join(lines)


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
        self._corrected: set[str] = set()
        self._control_epochs: set[int] = set()
        self._current_title: str | None = None
        self._blocked_speech = None
        self._session = None
        self._closed = False
        # Fast path state (ordinary turns answered from preloaded context).
        self._catalog = None
        self._fast_enabled = False
        self._fast_ready = False
        self._fast_selection = None  # the project Gemini holds context for
        self._committed_selection = None
        self._partials: dict[int, str] = {}
        self._partial_event = asyncio.Event()
        self._fast_epochs: dict[int, str] = {}
        self._preload_task = None
        self._response_epoch = None  # activity epoch of the last played response
        self._tool_epochs: set[int] = set()
        self._searches: dict[int, int] = {}
        self._forget_epochs: set[int] = set()
        self._canonical_forget_epochs: set[int] = set()
        self._nudged_epochs: set[int] = set()
        self._retire = None
        self._played = 0  # audible response segments allowed so far
        self._played_epochs: set[int] = set()
        # Grant renewal pending at wake: turns wait (bounded) for Hello.
        self._renewal_started = monotonic()
        self._renewal_deadline = (
            None
            if owner._grant_current()
            else self._renewal_started + RENEWAL_WAIT_SECONDS
        )
        self._paused = False
        self._forget_incomplete_epochs: set[int] = set()
        self._withheld_keys: set[tuple] = set()

    @property
    def metrics(self) -> VoiceProjectMetrics:
        return self._owner.metrics

    # -- wiring ---------------------------------------------------------------

    def bind_session(self, session) -> None:
        """The AgentSession, used only to interrupt/re-request a gated reply."""
        self._session = session
        on = getattr(session, "on", None)
        if callable(on):
            on("function_tools_executed", self.observe_tools_executed)
            on("user_input_transcribed", self.observe_transcription)

    def observe_tools_executed(self, event) -> None:
        """A deterministic conversation-control tool ran (e.g. standby).

        Its brief acknowledgement is not a project answer, so the context gate
        lets it through instead of re-requesting project memory. The accepted
        turn itself is still saved like any other.
        """
        calls = tuple(getattr(event, "function_calls", ()))
        outputs = tuple(getattr(event, "function_call_outputs", ()) or ())
        names = {getattr(c, "name", "") for c in calls}
        epoch = self._conversation.user_activity_epoch
        control = names & CONTROL_TOOLS
        if control:
            self._control_epochs.add(epoch)
            self._diag("control_tool", epoch=epoch, tools=sorted(control))
        for index, call in enumerate(calls):
            output = outputs[index] if index < len(outputs) else None
            if getattr(call, "name", "") == "forget_memory" and not getattr(
                output, "is_error", True
            ):
                # A canonical fact was forgotten; its saved conversation must be
                # forgotten too (checked after the reply, see observe_turn).
                self._canonical_forget_epochs.add(epoch)

    def observe_speech(self, event) -> None:
        self._speech = getattr(event, "speech_handle", None)

    # -- bridge observers (synchronous; they never answer) --------------------

    def observe_turn(self, turn) -> None:
        if turn.role is ConversationRole.USER:
            if turn.turn_id in self._seen_user:
                return
            self._seen_user.add(turn.turn_id)
            self.metrics.user_turns += 1
            if turn.user_activity_epoch in self._fast_epochs:
                # Answered on the fast path from context Gemini already held.
                self._delivered_turns.add(turn.turn_id)
            # Durable capture does not wait for, or depend on, the model.
            self._outcome_future(turn)
            self._turn_ready.set()
            return
        if turn.role is not ConversationRole.ASSISTANT or self._closed:
            return
        if turn.turn_id in self._recorded_assistant:
            return
        from jarvis.voice.voice_output_safety import non_user_facing_reason

        unsafe = non_user_facing_reason(turn.text)
        if unsafe is not None:
            # An echoed instruction or reasoning trace is never conversation.
            self._recorded_assistant.add(turn.turn_id)
            self.metrics.assistant_skipped += 1
            self._diag("assistant_not_user_facing", reason=unsafe)
            return
        epoch = self._response_epoch
        latest_user = self._latest_user_before(turn)
        if (
            epoch is not None
            and latest_user is not None
            and (latest_user.user_activity_epoch or 0) > epoch
        ):
            # The last audible response belonged to an earlier utterance: this
            # reply was never played (no gate decision), so it is not attributed.
            epoch = None
        if epoch in self._forget_epochs or epoch in self._canonical_forget_epochs:
            # A forget confirmation is never saved (it would restate the words).
            self._recorded_assistant.add(turn.turn_id)
            self.metrics.assistant_skipped += 1
            self._after_forget_reply(epoch)
            return
        delivered = self._delivered
        if epoch in self._fast_epochs and (
            delivered is None or delivered.turn.user_activity_epoch != epoch
        ):
            # A played fast-path answer: recorded after its question is saved.
            self._recorded_assistant.add(turn.turn_id)
            self._owner.spawn(
                self._record_fast_reply(turn, epoch),
                name="jarvis-project-voice-fast-reply",
            )
            return
        if delivered is None or self._latest_user_before(turn) is not delivered.turn:
            # Gated/unheard reply, preamble, or reply to an undelivered turn.
            self.metrics.assistant_skipped += 1
            return
        self._recorded_assistant.add(turn.turn_id)
        if self._correct_false_claim(delivered, turn):
            return  # misinformation is never saved as project history
        evidence = tuple(self._delivered_ids)
        self._owner.spawn(
            self._record_assistant(delivered.outcome, turn, evidence),
            name="jarvis-project-voice-reply",
        )

    def _correct_false_claim(self, delivered: _Delivered, turn) -> bool:
        """A reply may only claim a project change the application committed.

        Spoken audio cannot be retracted, so a false claim is corrected at
        once with fixed wording and is not recorded as project history.
        """
        from jarvis.voice.project_claims import false_project_claims

        outcome = delivered.outcome
        action = outcome.decision.action if outcome.status == "ready" else None
        false = false_project_claims(turn.text, action)
        if not false:
            return False
        self.metrics.false_claims += 1
        epoch = delivered.turn.user_activity_epoch
        self._diag(
            "false_project_claim", epoch=epoch, claims=sorted(false), action=action
        )
        LOGGER.warning(
            "Project voice: reply claimed %s but committed action was %s; correcting",
            sorted(false),
            action,
        )
        if delivered.turn.turn_id not in self._corrected:
            self._corrected.add(delivered.turn.turn_id)
            project = (
                outcome.decision.title
                if outcome.status == "ready"
                else self._current_title or "your current project"
            )
            what = (
                "no project was created or switched."
                if action not in {"created", "switched"}
                else f"the project was {action}, nothing else changed."
            )
            self.metrics.corrections += 1
            self._diag("correction_spoken", epoch=epoch)
            self._generate(CORRECTION_INSTRUCTIONS.format(what=what, project=project))
        return True

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

    # -- grant renewal pending at wake --------------------------------------

    async def _ready(self) -> bool:
        """Whether project memory may be used in this session now.

        On the first wake after a lock/unlock the session starts at once and
        this waits (until RENEWAL_WAIT_SECONDS after the wake) for the fresh
        Hello approval. Not approved in time: the session continues as ordinary
        voice, says so once, and saves nothing.
        """
        # A closed session still finishes its in-flight saves (sleep right
        # after speaking), so only a pause ends readiness.
        if self._paused:
            return False
        if self._renewal_deadline is None:
            # The grant was current at wake. If it lapses mid-session, the
            # archive itself refuses reads and writes (fails closed).
            return True
        ready = await self._owner.wait_ready(self._renewal_deadline)
        if ready:
            if self._renewal_deadline is not None:
                waited = round((monotonic() - self._renewal_started) * 1000)
                self._owner._runtime_event("renewal_ready_for_wake", waited_ms=waited)
                # Also in THIS session's record, so a grader knows which wake.
                self._diag("renewal_ready_for_wake", waited_ms=waited)
                self._renewal_deadline = None
            return True
        self._enter_paused()
        return False

    def approval_pending_seconds(self) -> float:
        """Seconds this wake still waits for the fresh Hello approval (0: none)."""
        deadline = self._renewal_deadline
        if deadline is None or self._paused or self._closed:
            return 0.0
        if self._owner._grant_current():
            return 0.0
        return max(0.0, deadline - monotonic())

    def _enter_paused(self) -> None:
        if self._paused:
            return
        self._paused = True
        self._fast_ready = False
        self._renewal_deadline = None
        self.metrics.paused_sessions += 1
        self._owner._runtime_event("paused_notice_spoken")
        self._diag("project_memory_paused")
        LOGGER.warning("Voice project memory paused for this wake (no Hello grant)")
        if not self._closed:
            self._generate(PAUSED_NOTICE_INSTRUCTIONS)

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
        if not await self._ready():
            # Paused: nothing is saved without a current grant.
            if not future.done():
                future.set_result(_Outcome("not_saved", reason="project_memory_paused"))
            self._diag(
                "prepared",
                epoch=turn.user_activity_epoch,
                turn_id=turn.turn_id,
                status="not_saved",
                reason="project_memory_paused",
            )
            return
        started = monotonic()
        try:
            async with owner.prepare_lock:
                outcome = await self._run_prepare(turn)
        except asyncio.CancelledError:
            if not future.done():
                future.set_result(_Outcome("failed", reason="cancelled"))
            raise
        elapsed = round((monotonic() - started) * 1000, 1)
        if outcome.status == "ready":
            owner.metrics.saved_user_turns += 1
            owner.metrics.prepared += 1
            owner.metrics.prepare_ms.append(elapsed)
            owner.metrics.packet_bytes.append(len(outcome.packet.context.encode()))
        if outcome.status == "ready":
            self._committed_selection = outcome.packet.selection
            if self._fast_enabled:
                self._sync_fast_context(turn, outcome)
        if not future.done():
            future.set_result(outcome)
        if owner.diagnostics is not None:
            await self._diagnose_prepared(turn, outcome, elapsed)
        if turn.user_activity_epoch in self._fast_epochs and not self._closed:
            await self._after_fast_outcome(turn, outcome)

    async def _diagnose_prepared(self, turn, outcome, elapsed) -> None:
        """Lab diagnostics: routing decision, receipt and the text read back."""
        fields = {
            "epoch": turn.user_activity_epoch,
            "turn_id": turn.turn_id,
            "status": outcome.status,
            "prepare_ms": elapsed,
        }
        if outcome.question:
            fields["question"] = outcome.question
        if outcome.reason:
            fields["reason"] = outcome.reason
        decision = outcome.decision
        if decision is not None:
            fields.update(
                action=decision.action,
                project=decision.title,
                announcement=decision.announcement,
                references=list(decision.reference_titles),
                ambiguous_references=list(decision.ambiguous_reference_titles),
                # The selection before this turn: None means no active project
                # (e.g. after forget), when the default General bootstrap is legal.
                previous_selection=outcome.previous,
            )
            if decision.action == "switched" and outcome.previous:
                fields["previous"] = outcome.previous
        if outcome.packet is not None:
            fields["request_id"] = outcome.packet.request_id
            receipt = self._owner.coordinator.receipt_for(outcome.packet.request_id)
            if receipt is not None:
                fields["receipt"] = {
                    "event_id": receipt.event_id,
                    "sequence": receipt.sequence,
                    "revision": receipt.revision,
                    "status": receipt.status,
                }
            try:
                # Read the durable row back: what memory actually holds.
                stored = await self._owner.access.snapshot(
                    outcome.packet.selection, source_ids=(turn.turn_id,)
                )
                texts = [s.event.text for s in stored.sources]
                fields["saved_text"] = texts[0] if texts else None
            except Exception as exc:  # noqa: BLE001 - diagnostics never affect voice
                fields["read_back_error"] = type(exc).__name__
        self._diag("prepared", **fields)

    def _diag(self, kind, **fields) -> None:
        diagnostics = self._owner.diagnostics
        if diagnostics is None:
            return
        try:
            diagnostics.project_event(self._conversation, kind, **fields)
        except Exception:  # noqa: BLE001 - diagnostics never affect voice
            LOGGER.warning("Voice diagnostics hook failed")

    async def _run_prepare(self, turn) -> _Outcome:
        coordinator = self._owner.coordinator
        access = self._owner.access
        try:
            catalog = await access.catalog()
            previous = next(
                (e.title for e in catalog.entries if e.selection == catalog.current),
                None,
            )
            self._current_title = previous
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
        self._current_title = decision.title
        if self._fast_enabled and (
            self._catalog is None
            or decision.create
            or decision.action in {"created", "switched", "new_thread"}
        ):
            # The classifier's catalog changes only when a project is created or
            # the selection moves; ordinary turns cost no extra archive read
            # (each read takes one of the grant's bounded 30-second leases).
            try:
                self._catalog = await access.catalog()
            except Exception:  # noqa: BLE001 - no catalog only disables fast path
                self._catalog = None
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
        self._tool_epochs.add(activity)
        self._diag("tool_called", epoch=activity)
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
        self.metrics.tool_path_turns += 1
        if outcome.status == "ready":
            # Gemini now holds this project's context (from the tool result).
            self._fast_selection = outcome.packet.selection
        self._mark_delivered(activity, source)
        self._diag(
            "delivered_to_model",
            epoch=activity,
            status=result["status"],
            new_rows=len(result.get("history", ())),
            already_provided=result.get("earlier_history_already_provided", 0),
            referenced_projects=result.get("referenced_projects", []),
            # Sealed lab diagnostics only: what the model was actually given.
            history=[
                {k: r[k] for k in ("role", "text", "from_project") if k in r}
                for r in result.get("history", ())
            ],
        )
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
        trailing = self._speech is not None and self._speech is self._blocked_speech
        allowed = self._decide_response_audio()
        if allowed and not trailing:
            self._response_epoch = self._conversation.user_activity_epoch
            self._played += 1
            self._played_epochs.add(self._response_epoch)
        if not trailing:
            self._diag("response_played" if allowed else "response_withheld")
        return allowed

    def _decide_response_audio(self) -> bool:
        """Decide one response segment: play only a context-informed answer."""
        epoch = self._conversation.user_activity_epoch
        if epoch == 0 or self._closed or self._paused:
            # Before any owner speech (wake acknowledgement) nothing to prepare;
            # a paused session is ordinary voice.
            return True
        if epoch in self._forget_incomplete_epochs:
            return True  # the honest partial-forget notice
        if epoch in self._canonical_forget_epochs and epoch not in self._forget_epochs:
            return self._hold_for_history_forget(epoch)
        if epoch in self._control_epochs:
            return True  # acknowledgement of an executed control tool
        key = self._key(epoch)
        if key == self._fallback_key or self._is_delivered(key):
            return True
        if self._fast_path_allows(epoch):
            return True
        # Includes a newer utterance in the same activity (local VAD missed
        # its start): it was never given to the model, so it is gated too.
        handle = self._speech
        if handle is not None and handle is self._blocked_speech:
            return False  # trailing frames of a response already blocked
        self._blocked_speech = handle
        self._withheld_keys.add(key)
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
                outcome = self._outcome_if_done(source)
                if await self._deliver_in_context(source, outcome, epoch):
                    self._diag("repair_requested", epoch=epoch, via="delivery")
                    LOGGER.info(
                        "Project voice: model answered without context; context "
                        "delivered by the application, re-requesting the answer"
                    )
                    self._generate(REPAIR_ANSWER_INSTRUCTIONS)
                else:
                    self._diag("repair_requested", epoch=epoch, via="tool")
                    LOGGER.info(
                        "Project voice: model answered without context; re-requesting"
                    )
                    self._generate(REPAIR_INSTRUCTIONS)
                self._arm_repair_watchdog(key)
            else:
                self._fallback(key, FALLBACK_INSTRUCTIONS)
        finally:
            self._repairing.discard(blocked_key)

    def _outcome_if_done(self, source):
        future = self._outcomes.get(source.turn_id)
        if future is None or not future.done() or future.cancelled():
            return None
        return future.result()

    async def _deliver_in_context(self, source, outcome, epoch) -> bool:
        """Give Gemini this utterance's prepared context directly (chat context),
        exactly what prepare_project_turn would have returned.

        Added as a completed exchange (see :meth:`_inject_closed_context`), and
        never inside generate_reply instructions: LiveKit sends those to Gemini
        as MODEL-role text, which Gemini can echo as if it were its own reply.
        """
        if outcome is None or outcome.status not in {
            "ready",
            "clarification",
            "not_saved",
        }:
            return False
        try:
            agent = self._session.current_agent if self._session is not None else None
        except Exception:  # noqa: BLE001 - not running: fall back to the tool
            agent = None
        if agent is None or not callable(getattr(agent, "update_chat_ctx", None)):
            return False
        result, new_ids = model_view(outcome, self._delivered_ids)
        try:
            await self._inject_closed_context(
                agent,
                "[Project memory from Jarvis for the owner's last request, not "
                "speech from the owner.] " + json.dumps(result, ensure_ascii=False),
            )
        except Exception as exc:  # noqa: BLE001 - fall back to the tool request
            LOGGER.warning(
                "Project voice repair delivery failed | error=%s", type(exc).__name__
            )
            return False
        if not self._still(epoch):
            return False
        for identity in new_ids:
            self._delivered_ids[identity] = None
        self._delivered = _Delivered(source, outcome, result)
        self._delivered_turns.add(source.turn_id)
        self._mark_delivered(epoch, source)
        if outcome.status == "ready":
            self._fast_selection = outcome.packet.selection
        self.metrics.delivered += 1
        self.metrics.repair_deliveries += 1
        self._diag(
            "delivered_to_model",
            epoch=epoch,
            via="repair",
            status=result["status"],
            new_rows=len(result.get("history", ())),
            history=[
                {k: r[k] for k in ("role", "text", "from_project") if k in r}
                for r in result.get("history", ())
            ],
        )
        return True

    def _arm_repair_watchdog(self, key) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        played = self._played
        loop.call_later(REPAIR_RESPONSE_SECONDS, self._repair_watchdog, key, played)

    def _repair_watchdog(self, key, played) -> None:
        if self._played != played or not self._still(key[0]):
            return  # something was heard, or the owner spoke again
        if key == self._fallback_key:
            return
        self.metrics.repair_timeouts += 1
        self._diag("repair_unanswered", epoch=key[0])
        self._fallback(key, FALLBACK_INSTRUCTIONS, reason="repair_produced_no_reply")

    def _sync_fast_context(self, turn, outcome) -> None:
        """Keep the fast path's view of Gemini's context in step with routing.

        The silent default workspace (General opened on a first ordinary turn)
        is a new, empty project: Gemini needs nothing beyond this conversation,
        so its context is already current. Before this, such a first turn was
        withheld as if context were missing (live -Qualification, 3938b428).
        A silent switch to an existing project is preloaded again instead.
        """
        selection = outcome.packet.selection
        if selection == self._fast_selection:
            return
        decision = outcome.decision
        epoch = turn.user_activity_epoch
        if decision.create and not decision.announcement:
            self._fast_selection = selection
            self.metrics.fast_context_syncs += 1
            self._diag("fast_context_synced", epoch=epoch, reason="new_empty_project")
            return
        if (
            not decision.announcement
            and epoch not in self._fast_epochs
            and epoch not in self._tool_epochs
        ):
            agent = None
            try:
                agent = self._session.current_agent if self._session else None
            except Exception:  # noqa: BLE001 - session already gone
                agent = None
            if agent is not None:
                self._owner.spawn(
                    self._safe_preload(agent), name="jarvis-project-preload-sync"
                )

    # -- replies Gemini transcribed but never voiced --------------------------

    def allow_unplayed_reply(self, turn) -> bool:
        """Ownership and gate decision for replaying an assistant turn that
        produced no audio.

        Silent-audio recovery asks this before speaking the turn's text through
        scripted TTS. A transcript alone is not evidence of a reply: the turn
        must answer an accepted owner utterance of the CURRENT activity, which
        has had no audible response yet, and pass the same context decision the
        audio gate makes for audio. Never replayed: the wake acknowledgement or
        any other system generation before owner speech (epoch 0), a stale reply
        (the owner spoke again), a response the gate withheld, a forget
        confirmation, and anything that is not user-facing text.
        """
        from jarvis.voice.voice_output_safety import non_user_facing_reason

        if self._closed or turn.role is not ConversationRole.ASSISTANT:
            return False
        epoch = self._conversation.user_activity_epoch
        latest = self._latest_user_before(turn)
        owned = (
            epoch > 0
            and latest is not None
            and (latest.user_activity_epoch or 0) == epoch
        )
        reason = None
        if not owned:
            reason = "not_owned_by_a_current_owner_utterance"
        elif epoch in self._played_epochs:
            reason = "utterance_already_answered_audibly"
        elif (
            epoch in self._forget_epochs
            or epoch in self._canonical_forget_epochs
            or epoch in self._forget_incomplete_epochs
        ):
            reason = "forget_confirmation"
        elif non_user_facing_reason(turn.text) is not None:
            reason = "not_user_facing"
        else:
            key = self._key(epoch)
            if key in self._withheld_keys and not self._is_delivered(key):
                reason = "withheld_by_context_gate"
            elif not (
                self._paused
                or epoch in self._control_epochs
                or key == self._fallback_key
                or self._is_delivered(key)
                or self._fast_path_allows(epoch)
            ):
                reason = "context_not_delivered"
        if reason is not None:
            self._diag("unplayed_reply_rejected", epoch=epoch, reason=reason)
            return False
        self._response_epoch = epoch
        self._played += 1
        self._played_epochs.add(epoch)
        self._diag("unplayed_reply_replayed", epoch=epoch)
        self.metrics.unplayed_replays += 1
        return True

    def observe_replayed(self, turn) -> None:
        """The replayed reply was heard: record it like any played reply."""
        self.observe_turn(turn)

    def speak_text(self, text) -> None:
        """Last resort when scripted TTS cannot replay an unvoiced reply."""
        self._generate("Say only this, exactly: '" + text.replace("'", "") + "'")

    def _hold_for_history_forget(self, epoch) -> bool:
        """Canonical fact forgotten, saved conversation not yet: no confirmation
        may play until both are done (or the partial result is said honestly)."""
        handle = self._speech
        if handle is not None and handle is self._blocked_speech:
            return False
        self._blocked_speech = handle
        if handle is not None:
            try:
                handle.interrupt()
            except Exception:  # noqa: BLE001 - a non-interruptible speech is muted
                LOGGER.info("Premature forget confirmation could not be interrupted")
        if epoch not in self._nudged_epochs:
            self._nudged_epochs.add(epoch)
            self._diag("forget_history_requested", epoch=epoch)
            self._generate(FORGET_HISTORY_NUDGE)
            try:
                loop = asyncio.get_running_loop()
                loop.call_later(FORGET_HISTORY_SECONDS, self._forget_watchdog, epoch)
            except RuntimeError:
                pass
        return False

    def _forget_watchdog(self, epoch) -> None:
        if self._closed or epoch in self._forget_epochs or not self._still(epoch):
            return
        self._forget_incomplete_epochs.add(epoch)
        self._diag("forget_incomplete", epoch=epoch)
        LOGGER.warning("Canonical forget committed but saved conversation was not")
        self._generate(FORGET_INCOMPLETE_INSTRUCTIONS)

    def _still(self, epoch) -> bool:
        return self._active() and self._conversation.user_activity_epoch == epoch

    def _fallback(self, key, instructions, *, reason=None) -> None:
        self.metrics.fallbacks += 1
        self._diag(
            "fallback",
            epoch=key[0],
            reason=reason
            or ("no_transcript" if key[1] is None else "model_skipped_tool_twice"),
        )
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

    # -- fast path: preloaded context, no tool call for ordinary turns ---------
    #
    # Invariant kept by the gate: a response plays only if Gemini holds the
    # context this utterance needs. Ordinary speech in the current project
    # needs that project's recent history (preloaded once per session) plus
    # the live conversation Gemini heard itself. Speech that could change or
    # widen the context (a project command, another project named) is
    # classified deterministically with the router's own rules and must go
    # through prepare_project_turn. Every accepted turn is still saved by the
    # application, exactly as on the tool path.

    def bind_injection_registry(self, register) -> None:
        """Bridge hook so preloaded context is never taken for a spoken turn."""
        self._register_injected = register

    def start_preload(self) -> None:
        """Begin the one-time session preload (runs once the agent is attached)."""
        if not self._owner.fast_path:
            return  # tool-only mode: every request goes through the tool
        if self._preload_task is None and self._session is not None:
            try:
                self._preload_task = self._owner.spawn(
                    self._preload_when_agent_ready(), name="jarvis-project-preload"
                )
            except RuntimeError:  # no running loop: the tool path still works
                LOGGER.warning("Project voice preload not started")

    async def _preload_when_agent_ready(self) -> None:
        agent = None
        for _ in range(250):  # up to ~5 s for session.start to attach the agent
            if self._closed:
                return
            try:
                agent = self._session.current_agent
                break
            except Exception:  # noqa: BLE001 - not running yet
                await asyncio.sleep(0.02)
        if agent is None:
            LOGGER.warning("Project voice preload skipped: no running agent")
            return
        if not await self._ready():
            return  # paused: no history is given to the model
        await self._safe_preload(agent)

    async def _safe_preload(self, agent) -> None:
        try:
            await self.preload(agent)
        except Exception as exc:  # noqa: BLE001 - the tool path still works
            self._fast_ready = False
            LOGGER.warning(
                "Project voice preload failed | error=%s", type(exc).__name__
            )

    async def preload(self, agent) -> None:
        """Give Gemini the current project's bounded recent history once."""
        self._fast_enabled = True
        self._fast_ready = False
        started = monotonic()
        live = {t.turn_id for t in self._conversation.turns}
        async with self._owner.prepare_lock:
            # One extra row tells whether older history exists.
            catalog, entry, sources = await self._owner.coordinator.session_context(
                limit=PRELOAD_ROWS + 1
            )
            selection = entry.selection if entry else None
            # Truth at this instant: every prepare holds the same lock and
            # records its committed selection as soon as it releases it.
            self._committed_selection = selection
        rows = _preload_rows(
            sources[-PRELOAD_ROWS:], exclude=set(self._delivered_ids) | live
        )
        text = _preload_message(entry.title if entry else None, rows, sources)
        if text:
            await self._inject_closed_context(agent, text)
        for row in rows:
            self._delivered_ids[row.event.event_id] = None
        self._catalog = catalog
        # Fast answers resume only if nothing was committed meanwhile.
        self._fast_selection = selection
        self._fast_ready = self._active()
        size = len(text.encode()) if text else 0
        self.metrics.preloads += 1
        self.metrics.preload_bytes.append(size)
        self._diag(
            "context_preloaded",
            epoch=self._conversation.user_activity_epoch,
            project=entry.title if entry else None,
            rows=len(rows),
            bytes=size,
            preload_ms=round((monotonic() - started) * 1000, 1),
            # Sealed lab diagnostics only: what the model was actually given.
            history=[{"role": r.event.role, "text": r.event.text} for r in rows],
        )

    _register_injected = None

    async def _inject_closed_context(self, agent, text) -> None:
        """Add context as a COMPLETED exchange: the labelled memory message and
        a short Jarvis acknowledgement.

        A lone user-role context message left the owner's "turn" open: the next
        generate_reply (the wake acknowledgement) then treated the memory block
        as the owner's prompt and Gemini returned instructions and a reasoning
        trace as text (live qualification at 8155df0d).
        """
        from livekit.agents.llm import ChatContext, ChatMessage

        identity = uuid4().hex[:12]
        items = [
            ChatMessage(
                id="jarvis:project-context:" + identity,
                role="user",
                content=[text],
            ),
            ChatMessage(
                id="jarvis:project-context-ack:" + identity,
                role="assistant",
                content=["Noted."],
            ),
        ]
        if self._register_injected is not None:
            self._register_injected(ChatContext(items=list(items)))
        context = agent.chat_ctx.copy()
        context.items.extend(items)
        await agent.update_chat_ctx(context)

    def observe_transcription(self, event) -> None:
        """Streaming recognition (cumulative partials, then the final)."""
        text = (getattr(event, "transcript", "") or "").strip()
        if text:
            self._partials[self._conversation.user_activity_epoch] = text
            self._partial_event.set()

    def _provisional_text(self, epoch) -> str | None:
        for turn in reversed(self._user_turns()):
            if turn.user_activity_epoch == (epoch or None):
                return turn.text
        return self._partials.get(epoch)

    def _fast_path_allows(self, epoch) -> bool:
        if (
            not self._fast_ready
            or self._catalog is None
            or self._fast_selection != self._committed_selection
        ):
            return False
        text = self._provisional_text(epoch)
        if not text:
            return False
        router = self._owner.coordinator.router
        if needs_project_routing(text, self._catalog) or router.announces_next_turn(
            self._catalog
        ):
            self._diag("fast_path_declined", epoch=epoch, provisional=text)
            return False
        if epoch not in self._fast_epochs:
            self._fast_epochs[epoch] = text
            self.metrics.fast_path_turns += 1
            self._diag("fast_path", epoch=epoch, provisional=text)
            for turn in self._user_turns():
                if turn.user_activity_epoch == epoch:
                    self._delivered_turns.add(turn.turn_id)
        return True

    async def response_audio_allowed(self) -> bool:
        """Async gate entry: lets streaming recognition catch up briefly
        before deciding, rather than withholding an ordinary answer."""
        epoch = self._conversation.user_activity_epoch
        if epoch and self._renewal_deadline is not None:
            await self._ready()  # bounded wait for the fresh Hello grant
        if (
            epoch
            and self._fast_ready
            and not self._is_delivered(self._key(epoch))
            and not self._provisional_text(epoch)
        ):
            self._partial_event.clear()
            try:
                await asyncio.wait_for(
                    self._partial_event.wait(), _FAST_PATH_TEXT_WAIT_SECONDS
                )
            except TimeoutError:
                pass
        return self.allow_response_audio()

    def _user_turn_for_epoch(self, epoch):
        for turn in reversed(self._user_turns()):
            if turn.user_activity_epoch == (epoch or None):
                return turn
        return None

    async def _record_fast_reply(self, reply, epoch) -> None:
        """Record a fast-path reply after its question, in conversational order."""
        deadline = monotonic() + _FAST_REPLY_WAIT_SECONDS
        user_turn = self._user_turn_for_epoch(epoch)
        while user_turn is None and monotonic() < deadline and not self._owner._closed:
            # The final transcript can commit just after the reply.
            self._turn_ready.clear()
            try:
                await asyncio.wait_for(self._turn_ready.wait(), 0.25)
            except TimeoutError:
                pass
            user_turn = self._user_turn_for_epoch(epoch)
        if user_turn is None:
            self.metrics.assistant_skipped += 1
            return  # never attributed to a question that was not saved
        outcome = await asyncio.shield(self._outcome_future(user_turn))
        if self._correct_false_claim(_Delivered(user_turn, outcome, {}), reply):
            return
        if outcome.status != "ready":
            return
        evidence = tuple(
            dict.fromkeys((*self._delivered_ids, *outcome.packet.source_ids))
        )
        try:
            await self._owner.coordinator.record_spoken_assistant(
                self._conversation,
                outcome.packet,
                reply,
                evidence=evidence,
                not_before=user_turn.accepted_at + timedelta(microseconds=1),
            )
            self.metrics.assistant_recorded += 1
        except Exception as exc:  # noqa: BLE001 - recording failure must not stop voice
            self.metrics.record_failures += 1
            LOGGER.warning(
                "Project voice fast reply not recorded | error=%s", type(exc).__name__
            )

    async def _after_fast_outcome(self, turn, outcome) -> None:
        """The final transcript of a fast-path utterance needed routing after
        all (recognition was incomplete when the answer started)."""
        for _ in range(3):
            await asyncio.sleep(0)  # let a waiting tool call take its result
        if turn.user_activity_epoch in self._tool_epochs:
            return  # Gemini called the tool for it: the tool path delivered it
        if outcome.status == "clarification":
            self.metrics.late_routing += 1
            self._diag(
                "late_routing", epoch=turn.user_activity_epoch, action="clarification"
            )
            self._generate("Say only this, exactly: '" + outcome.question + "'")
            return
        if outcome.status != "ready":
            return
        decision = outcome.decision
        moved = outcome.packet.selection != self._fast_selection
        if decision.references or decision.ambiguous_reference_titles:
            self.metrics.late_routing += 1
            self._diag(
                "late_routing",
                epoch=turn.user_activity_epoch,
                action=decision.action,
                references=list(decision.reference_titles),
            )
        if not moved:
            return
        if decision.announcement:
            self.metrics.late_routing += 1
            self._diag(
                "late_routing",
                epoch=turn.user_activity_epoch,
                action=decision.action,
                announcement=decision.announcement,
            )
            # A committed project change is never left unannounced.
            self._generate("Say only this, exactly: '" + decision.announcement + "'")
        # Gemini needs the new project's context before the next fast answer.
        agent = None
        try:
            agent = self._session.current_agent if self._session else None
        except Exception:  # noqa: BLE001 - session already gone
            agent = None
        if agent is not None and self._active():
            await self._safe_preload(agent)

    # -- forgetting and long-term recall ---------------------------------------

    def bind_retire(self, retire) -> None:
        """Ends this wake session, so forgotten words leave the model context."""
        self._retire = retire

    def _after_forget_reply(self, epoch) -> None:
        if epoch in self._canonical_forget_epochs and epoch not in self._forget_epochs:
            if epoch not in self._nudged_epochs:
                # The confirmation committed without audio reaching the gate:
                # still ask for the saved conversation to be forgotten too.
                self._hold_for_history_forget(epoch)
            return
        if epoch in self._forget_epochs and self._retire is not None:
            retire, self._retire = self._retire, None
            try:
                retire()
            except Exception:  # noqa: BLE001 - the session also ends on its timer
                LOGGER.warning("Project voice: session retire after forget failed")

    async def _current_source(self):
        activity = self._conversation.user_activity_epoch
        try:
            return activity, await asyncio.wait_for(
                self._wait_source(activity), timeout=_SOURCE_WAIT_SECONDS
            )
        except TimeoutError:
            return activity, None

    async def forget_history(self, words) -> dict:
        """Forget saved conversation that mentions what the owner named."""
        from jarvis.memory.project_access import conversation_search_terms
        from jarvis.memory.project_controls import (
            MAX_FORGET_TERMS,
            ForgetTooBroadError,
            ProjectControls,
        )

        epoch, turn = await self._current_source()
        if turn is None:
            return {"status": "unavailable", "reason": "no_current_request"}
        # The reply reports this operation; like standby it needs no project
        # context, so the gate lets it play (it is never saved, see observe_turn).
        self._control_epochs.add(epoch)
        if not _FORGET_VERB.search(turn.text):
            return {
                "status": "denied",
                "reason": "not_a_forget_request",
                "guidance": "Only call this when the owner asks to forget something.",
            }
        spoken = set(conversation_search_terms(turn.text))
        terms = tuple(
            t
            for t in conversation_search_terms(str(words or ""))
            if not _FORGET_VERB.fullmatch(t)
        )
        if not 1 <= len(terms) <= MAX_FORGET_TERMS or not set(terms) <= spoken:
            return {
                "status": "denied",
                "reason": "words_not_said",
                "guidance": "Pass one to six distinctive words the owner actually "
                "said about what to forget (not 'forget' itself).",
            }
        # The request itself mentions the words: wait until it is saved, so it is
        # forgotten with everything else rather than left behind.
        try:
            await asyncio.wait_for(
                asyncio.shield(self._outcome_future(turn)), _REPAIR_WAIT_SECONDS
            )
        except TimeoutError:
            return {"status": "unavailable", "reason": "request_not_saved_yet"}
        owner = self._owner
        controls = ProjectControls(owner.access)
        async with owner.prepare_lock:
            try:
                preview = await controls.preview_forget_mentions(terms)
            except ForgetTooBroadError:
                return {
                    "status": "too_broad",
                    "guidance": "Nothing was deleted. Ask the owner to name it more "
                    "specifically.",
                }
            if not preview.matched:
                return {
                    "status": "nothing_saved",
                    "guidance": "No saved conversation mentions it.",
                }
            try:
                # Fresh Windows Hello approval showing exactly what is removed.
                receipt = await controls.forget_mentions(preview)
            except (PermissionError, RuntimeError):
                # Hello denied or timed out, or the history changed meanwhile.
                self._diag("history_forget_not_approved", epoch=epoch)
                return {
                    "status": "not_forgotten",
                    "reason": "not_approved_or_changed",
                    "guidance": "Say nothing was deleted from saved conversation.",
                }
        self._forget_epochs.add(epoch)
        self._fast_ready = False  # this session's context still holds the words
        for identity in (*preview.matched, *preview.derived):
            self._delivered_ids.pop(identity, None)
        self.metrics.history_forgets += 1
        self._diag(
            "history_forgotten",
            epoch=epoch,
            terms=list(preview.terms),  # sealed lab diagnostics only
            owner_rows=receipt.owner_rows,
            jarvis_rows=receipt.jarvis_rows,
            projects=list(receipt.projects),
        )
        LOGGER.info(
            "Project history forget committed | owner_rows=%s | jarvis_rows=%s | projects=%s",
            receipt.owner_rows,
            receipt.jarvis_rows,
            len(receipt.projects),
        )
        return {
            "status": "forgotten",
            "your_messages": receipt.owner_rows,
            "jarvis_replies": receipt.jarvis_rows,
            "projects": list(receipt.projects),
            "guidance": "Confirm briefly WITHOUT repeating the forgotten words, and "
            "never use them again. If it was also a saved personal fact, call "
            "forget_memory too. This conversation ends after your confirmation.",
        }

    async def search_history(self, query) -> dict:
        """Bounded archive search for older project facts (FTS5, authorized)."""
        from jarvis.memory.project_access import conversation_search_terms

        epoch, turn = await self._current_source()
        if turn is None:
            return {"status": "unavailable", "reason": "no_current_request"}
        used = self._searches.get(epoch, 0)
        if used >= SEARCHES_PER_UTTERANCE:
            return {"status": "denied", "reason": "search_budget_exhausted"}
        if not conversation_search_terms(str(query or "")):
            return {"status": "denied", "reason": "search_words_required"}
        self._searches[epoch] = used + 1
        owner = self._owner
        # The question itself is saved first and never returned as an answer.
        try:
            outcome = await asyncio.wait_for(
                asyncio.shield(self._outcome_future(turn)), _REPAIR_WAIT_SECONDS
            )
        except TimeoutError:
            outcome = None
        exclude = (
            outcome.packet.request_id
            if outcome is not None and outcome.status == "ready"
            else None
        )
        selection = self._committed_selection
        if selection is None:
            catalog = await owner.access.catalog()
            selection = catalog.current
        if selection is None:
            return {"status": "no_match", "history": []}
        started = monotonic()
        result = await owner.access.snapshot(
            selection,
            query=str(query),
            limit=SEARCH_HITS,
            project_wide=True,
            exclude_request_id=exclude,
        )
        status = result.status
        if status == "no_match":
            # Soft separation, as in text: other projects only when this one has
            # nothing; every hit keeps its project label.
            wider = await owner.access.snapshot(
                selection,
                query=str(query),
                limit=SEARCH_HITS,
                all_projects=True,
                exclude_request_id=exclude,
            )
            if wider.sources:
                result, status = wider, "other_projects"
        rows, given, already, total = [], [], 0, 0
        for source in sorted(
            result.sources, key=lambda s: (s.event.accepted_at, s.sequence)
        ):
            event = source.event
            if event.event_id in self._delivered_ids:
                already += 1
                continue
            size = len(event.text) + 40
            if total + size > SEARCH_MAX_CHARS:
                continue  # whole rows only; never shortened
            total += size
            item = {
                "role": "owner" if event.role == "user" else "Jarvis",
                "date": event.accepted_at.date().isoformat(),
                "text": event.text,
            }
            if source.project_id and source.project_id != selection.project_id:
                item["from_project"] = source.project_title
            if event.delivery == "partial":
                item["interrupted"] = True
            rows.append(item)
            given.append(event.event_id)
        for identity in given:
            self._delivered_ids[identity] = None
        elapsed = round((monotonic() - started) * 1000, 1)
        payload = {
            "status": status if rows or already else "no_match",
            "history": rows,
            "already_in_conversation": already,
            "guidance": "Saved conversation, oldest first. When rows disagree, the "
            "newest owner statement is current; mention that it changed. Rows with "
            "from_project come from that project. Missing is not proof it never "
            "happened.",
        }
        size = len(json.dumps(payload, ensure_ascii=False).encode())
        self.metrics.history_searches += 1
        self.metrics.search_ms.append(elapsed)
        self.metrics.search_bytes.append(size)
        self._diag(
            "history_searched",
            epoch=epoch,
            hits=len(rows),
            already=already,
            search_ms=elapsed,
            bytes=size,
            history=[{"role": r["role"], "text": r["text"]} for r in rows],
        )
        return payload

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
    "Returns the application's saved routing and project history for the "
    "owner's current request. No arguments. Call before answering a project "
    "command, a mention of another project, or when the history you have lacks "
    "the answer."
)


_SEARCH_DESCRIPTION = (
    "Searches this project's saved conversation (then other projects if nothing "
    "matches) for older details than the history you have. Bounded and "
    "evidence-only; at most two searches per request."
)
_FORGET_DESCRIPTION = (
    "When the owner asks to forget something, removes saved conversation that "
    "mentions it (all their words must appear) and Jarvis replies made from it, "
    "after the owner approves with Windows Hello. Also use forget_memory for a "
    "saved personal fact."
)


class VoiceProjectTools:
    def __init__(self, turns: VoiceProjectTurns) -> None:
        self._turns = turns

    @property
    def tools(self) -> list:
        return [
            self.prepare_project_turn,
            self.search_project_history,
            self.forget_saved_history,
        ]

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

    @function_tool(
        raw_schema={
            "name": "search_project_history",
            "description": _SEARCH_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A few key words from the owner's question.",
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        }
    )
    async def search_project_history(self, raw_arguments: dict[str, object]) -> dict:
        query = (raw_arguments or {}).get("query")
        if not isinstance(query, str) or len(query) > 200:
            return {"status": "denied", "reason": "short_query_text_required"}
        return await self._turns.search_history(query)

    @function_tool(
        raw_schema={
            "name": "forget_saved_history",
            "description": _FORGET_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "words": {
                        "type": "string",
                        "description": "One to six distinctive words the owner said "
                        "about what to forget.",
                    }
                },
                "required": ["words"],
                "additionalProperties": False,
            },
        }
    )
    async def forget_saved_history(self, raw_arguments: dict[str, object]) -> dict:
        words = (raw_arguments or {}).get("words")
        if not isinstance(words, str) or len(words) > 200:
            return {"status": "denied", "reason": "short_words_text_required"}
        return await self._turns.forget_history(words)


# Instruction text that must never be spoken back or saved as a reply.
register_internal_text(
    REPAIR_ANSWER_INSTRUCTIONS,
    REPAIR_INSTRUCTIONS,
    FORGET_HISTORY_NUDGE,
    _GUIDANCE,
    _TOOL_DESCRIPTION,
    _SEARCH_DESCRIPTION,
    _FORGET_DESCRIPTION,
)
