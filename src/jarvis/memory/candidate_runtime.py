"""Session-scoped background runtime for Phase-4.4 memory candidate extraction."""

from __future__ import annotations

import asyncio
import logging

from jarvis.conversation import ConversationRole, ConversationSession, ConversationTurn
from jarvis.memory.candidates import (
    MemoryCandidateCoordinator,
    MemoryCandidateExtractor,
    MemoryCandidateQuarantine,
)

LOGGER = logging.getLogger(__name__)
_DEFAULT_DEFER_SECONDS = 5.0


class MemoryCandidateSessionRuntime:
    """Own background extraction tasks and one non-durable session quarantine."""

    def __init__(
        self,
        *,
        conversation: ConversationSession,
        extractor: MemoryCandidateExtractor,
        defer_seconds: float = _DEFAULT_DEFER_SECONDS,
    ) -> None:
        if not isinstance(conversation, ConversationSession):
            raise TypeError("conversation must be a ConversationSession")
        if not 0.0 <= float(defer_seconds) <= 60.0:
            raise ValueError("memory candidate defer_seconds must be between 0 and 60")
        self._conversation = conversation
        self._defer_seconds = float(defer_seconds)
        self._quarantine = MemoryCandidateQuarantine(
            session_id=conversation.session_id,
        )
        self._coordinator = MemoryCandidateCoordinator(
            extractor=extractor,
            quarantine=self._quarantine,
        )
        self._tasks: set[asyncio.Task[None]] = set()
        self._closed = False

    @property
    def quarantine(self) -> MemoryCandidateQuarantine:
        return self._quarantine

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def pending_task_count(self) -> int:
        return len(self._tasks)

    @property
    def defer_seconds(self) -> float:
        return self._defer_seconds

    def observe_turn(self, turn: ConversationTurn) -> None:
        """Schedule candidate extraction without delaying the conversation callback."""

        if self._closed or turn.role is not ConversationRole.USER:
            return
        task = asyncio.create_task(
            self._process_turn(turn),
            name=f"jarvis-memory-candidate-{turn.turn_id[:8]}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)

    async def _process_turn(self, turn: ConversationTurn) -> None:
        try:
            if self._defer_seconds > 0:
                await asyncio.sleep(self._defer_seconds)
                if self._closed:
                    return
            result = await self._coordinator.consider_user_turn(
                self._conversation,
                turn,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception(
                "Memory candidate shadow failed for turn %s; conversation is unaffected",
                turn.turn_id,
            )
            return
        LOGGER.info(
            "Memory candidate shadow turn %s | outcome=%s | reason=%s | "
            "quarantine=session_local | durable_admission=False | defer_seconds=%.1f",
            turn.turn_id,
            result.outcome.value,
            result.reason_code,
            self._defer_seconds,
        )

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        task.result()

    def close(self) -> None:
        """Cancel in-flight work and physically discard all session candidates."""

        if self._closed:
            return
        self._closed = True
        disposed_candidates = len(self._quarantine.snapshot())
        cancelled_tasks = len(self._tasks)
        for task in tuple(self._tasks):
            task.cancel()
        self._quarantine.dispose()
        LOGGER.info(
            "Memory candidate shadow session closed | disposed_candidates=%s | "
            "cancelled_tasks=%s | quarantine_disposed=True | durable_admission=False",
            disposed_candidates,
            cancelled_tasks,
        )
