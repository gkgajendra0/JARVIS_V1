"""Speaker evidence for each accepted owner-side transcript (candidate).

The enrolled-speaker shadow already scores the audio of every user turn, but
until now its result was only logged, under its own audio id. This module
links that score to the exact canonical turn and gives the turn one of three
statuses:

- ``owner``: scored at or above the experimental threshold;
- ``non_owner``: scored below it;
- ``unknown``: no usable score (too short, no speech found, scoring failed,
  no evidence in time). Unknown is never treated as verified owner speech.

The turn that opens a wake (after the wake word, not a follow-up) is marked
``opening``; its status still comes from evidence alone.

With enforcement off (the default) nothing waits for, or acts on, the status:
it is logged so the owner can judge it. With enforcement on, project history
and personal learning wait (bounded) for the status of a later turn and keep a
``non_owner`` turn out. Opening and unknown turns are never withheld, so
commands and natural follow-ups behave as before. Conversation, replies and
Windows Hello action permissions are unaffected either way.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import StrEnum

from jarvis.conversation import ConversationRole

LOGGER = logging.getLogger(__name__)

EVIDENCE_WAIT_SECONDS = 1.5


class SpeakerTurnStatus(StrEnum):
    OWNER = "owner"
    NON_OWNER = "non_owner"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SpeakerTurnEvidence:
    turn_id: str
    status: SpeakerTurnStatus
    score: float | None
    reason: str
    opening: bool


class SpeakerTurnEvidenceBook:
    """Per wake session: canonical turn id -> speaker evidence."""

    def __init__(
        self,
        *,
        threshold: float,
        enforce: bool,
        follow_up: bool,
        wait_seconds: float = EVIDENCE_WAIT_SECONDS,
    ) -> None:
        if not 0 < threshold < 1:
            raise ValueError("speaker threshold must be between 0 and 1")
        self.threshold = float(threshold)
        self.enforcing = bool(enforce)
        self._follow_up = bool(follow_up)
        self._wait_seconds = float(wait_seconds)
        self._opening: dict[str, bool] = {}
        self._futures: dict[str, asyncio.Future] = {}
        self._user_turns = 0

    # Accepted-turn observer: registered before project history and learning.
    def observe_turn(self, turn) -> None:
        if turn.role is not ConversationRole.USER or turn.turn_id in self._opening:
            return
        self._user_turns += 1
        self._opening[turn.turn_id] = self._user_turns == 1 and not self._follow_up
        self._future(turn.turn_id)

    def observed(self, turn_id: str) -> bool:
        """This accepted turn has an evidence entry in this wake."""
        return turn_id in self._opening

    def is_opening(self, turn_id: str) -> bool:
        return self._opening.get(turn_id, False)

    def _future(self, turn_id: str) -> asyncio.Future:
        future = self._futures.get(turn_id)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            self._futures[turn_id] = future
        return future

    def resolve(self, turn_id: str, *, score: float | None, reason: str) -> None:
        if turn_id not in self._opening:
            return  # not an accepted turn of this session
        future = self._future(turn_id)
        if future.done():
            return
        if score is None:
            status = SpeakerTurnStatus.UNKNOWN
        elif score >= self.threshold:
            status = SpeakerTurnStatus.OWNER
        else:
            status = SpeakerTurnStatus.NON_OWNER
        evidence = SpeakerTurnEvidence(
            turn_id, status, score, reason, self._opening[turn_id]
        )
        future.set_result(evidence)
        withheld = self.withholds(evidence)
        LOGGER.info(
            "Speaker evidence | turn_id=%s | status=%s | score=%s | threshold=%.2f | "
            "opening=%s | reason=%s | enforcement=%s | effect=%s",
            turn_id,
            status.value,
            f"{score:.4f}" if score is not None else "n/a",
            self.threshold,
            evidence.opening,
            reason,
            "on" if self.enforcing else "off",
            (
                "kept out of project history and personal learning"
                if withheld
                or (self.enforcing and status is not SpeakerTurnStatus.OWNER)
                else "observed only; would keep out of project history and learning"
                if status is not SpeakerTurnStatus.OWNER
                else "none"
            ),
        )

    def current(self, turn_id: str) -> SpeakerTurnEvidence | None:
        future = self._futures.get(turn_id)
        return future.result() if future is not None and future.done() else None

    async def wait(self, turn_id: str) -> SpeakerTurnEvidence:
        """Evidence for an accepted turn; unknown if none arrives in time."""
        opening = self._opening.get(turn_id, False)
        future = self._futures.get(turn_id)
        if future is None:
            return SpeakerTurnEvidence(
                turn_id, SpeakerTurnStatus.UNKNOWN, None, "not_observed", opening
            )
        if future.cancelled():
            return SpeakerTurnEvidence(
                turn_id, SpeakerTurnStatus.UNKNOWN, None, "session_closed", opening
            )
        try:
            return await asyncio.wait_for(
                asyncio.shield(future), timeout=self._wait_seconds
            )
        except TimeoutError:
            return SpeakerTurnEvidence(
                turn_id, SpeakerTurnStatus.UNKNOWN, None, "evidence_timeout", opening
            )
        except asyncio.CancelledError:
            if not future.cancelled():
                raise  # the waiting task itself was cancelled
            return SpeakerTurnEvidence(
                turn_id, SpeakerTurnStatus.UNKNOWN, None, "session_closed", opening
            )

    @staticmethod
    def _would_withhold(evidence: SpeakerTurnEvidence) -> bool:
        return evidence.status is SpeakerTurnStatus.NON_OWNER and not evidence.opening

    def withholds(self, evidence: SpeakerTurnEvidence | None) -> bool:
        """Only positive non-owner evidence on a later turn, with enforcement."""
        return (
            self.enforcing and evidence is not None and self._would_withhold(evidence)
        )

    def authorizes_owner(
        self, evidence: SpeakerTurnEvidence | None, turn_id: str | None = None
    ) -> bool:
        """With enforcement, only positive owner evidence for that exact turn
        acts for the owner: saving to project history, automatic learning,
        project archive reads, personal-context reads and memory receipts.
        Unknown (too short, unscored, timed out, session closed), non-owner,
        missing or another turn's evidence never does, opening turn or not.
        Owner decision, 2026-11-27 (Memory V1 closure)."""
        if not self.enforcing:
            return True
        return (
            evidence is not None
            and evidence.status is SpeakerTurnStatus.OWNER
            and (turn_id is None or evidence.turn_id == turn_id)
            and evidence.turn_id in self._opening
        )

    def admits_learning(self, evidence: SpeakerTurnEvidence | None) -> bool:
        """Automatic learning: see authorizes_owner. The explicit memory
        tools, which need fresh Windows Hello for writes, remain the way to
        save what an unscored short turn said."""
        return self.authorizes_owner(evidence)

    async def owner_verified(self, turn_id: str | None) -> bool:
        """Wait (bounded) for this accepted turn's evidence; True only for
        positive owner evidence (always True without enforcement)."""
        if not self.enforcing:
            return True
        if not turn_id or turn_id not in self._opening:
            return False  # not an accepted turn of this wake
        return self.authorizes_owner(await self.wait(turn_id), turn_id)

    def close(self) -> None:
        for future in self._futures.values():
            if not future.done():
                future.cancel()


class UnavailableSpeakerEvidence:
    """Enforcement is on but no speaker scores exist for this session (no
    enrolled template or model, or a session without scoring): nothing is
    authorized for the owner. Fails closed instead of skipping the check."""

    enforcing = True

    async def wait(self, turn_id: str) -> SpeakerTurnEvidence:
        return SpeakerTurnEvidence(
            turn_id, SpeakerTurnStatus.UNKNOWN, None, "no_speaker_scores", False
        )

    def current(self, turn_id: str) -> None:
        return None

    def observed(self, turn_id: str) -> bool:
        return True

    def authorizes_owner(self, evidence, turn_id=None) -> bool:
        return False

    def admits_learning(self, evidence) -> bool:
        return False

    def withholds(self, evidence) -> bool:
        return False

    async def owner_verified(self, turn_id) -> bool:
        return False
