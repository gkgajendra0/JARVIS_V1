"""Nonblocking, authorization-bound semantic ingestion for canonical voice turns.

The pipeline does not own persistent memory or model-context release. It is
deliberately separate from the audio critical path, and cannot synthesize
canonical turns. The embedding application must rotate authorization bindings
when owner authority changes and call invalidate() on a lock or revocation.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from jarvis.conversation import (
    ConversationRole,
    ConversationSession,
    ConversationStatus,
    ConversationTurn,
)

from .conversation_semantics import (
    SemanticContextEngine,
    SemanticProposal,
    SemanticRejected,
)

LOGGER = logging.getLogger(__name__)

ProposalProducer = Callable[[ConversationTurn], Awaitable[Sequence[SemanticProposal]]]
AuthorizationBinding = Callable[[], str | None]


@dataclass(frozen=True, slots=True)
class SemanticPipelineStatus:
    submitted: int
    applied: int
    dropped: int
    failures: int
    queued: int


class SemanticTurnPipeline:
    """Single-writer semantic queue, with bounded work and revoke fencing.

    A binding is an opaque, rotating authorization epoch from the existing
    authority system, not a user ID or an API key. No binding means no work.
    Successful proposals are still *transient*, not permission to release state.
    """

    def __init__(
        self,
        *,
        conversation: ConversationSession,
        state: SemanticContextEngine,
        producer: ProposalProducer,
        authorization_binding: AuthorizationBinding,
        max_pending: int = 16,
        timeout_seconds: float = 5.0,
    ) -> None:
        if not isinstance(conversation, ConversationSession):
            raise TypeError("conversation must be canonical")
        if not isinstance(state, SemanticContextEngine):
            raise TypeError("state must be SemanticContextEngine")
        if not callable(producer) or not callable(authorization_binding):
            raise TypeError("producer and authorization_binding must be callable")
        if type(max_pending) is not int or not 1 <= max_pending <= 128:
            raise ValueError("max_pending must be between 1 and 128")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int | float)
            or not 0 < float(timeout_seconds) <= 20
        ):
            raise ValueError("timeout_seconds must be in (0, 20]")
        self._conversation = conversation
        self.state = state
        self._producer = producer
        self._authorization_binding = authorization_binding
        self._timeout_seconds = float(timeout_seconds)
        self._queue: asyncio.Queue[tuple[ConversationTurn, str, int]] = asyncio.Queue(
            maxsize=max_pending
        )
        self._worker: asyncio.Task[None] | None = None
        self._binding: str | None = None
        self._closed = False
        self._submitted = 0
        self._applied = 0
        self._dropped = 0
        self._failures = 0

    @property
    def status(self) -> SemanticPipelineStatus:
        return SemanticPipelineStatus(
            submitted=self._submitted,
            applied=self._applied,
            dropped=self._dropped,
            failures=self._failures,
            queued=self._queue.qsize(),
        )

    def start(self) -> None:
        if self._closed:
            raise RuntimeError("pipeline is closed")
        if self._worker is not None:
            raise RuntimeError("pipeline already started")
        self._worker = asyncio.create_task(
            self._run(), name="jarvis-semantic-turn-pipeline"
        )

    def submit(self, turn: ConversationTurn) -> bool:
        """An accepted-turn observer may call this without awaiting inference."""
        if self._closed or self._worker is None:
            return False
        if (
            not isinstance(turn, ConversationTurn)
            or turn.role is not ConversationRole.USER
            or self._conversation.status is not ConversationStatus.ACTIVE
            or not any(item is turn for item in self._conversation.turns)
        ):
            self._dropped += 1
            return False
        binding = self._current_binding()
        if binding is None:
            self.invalidate()
            self._dropped += 1
            return False
        if self._binding is not None and binding != self._binding:
            self.invalidate()
        self._binding = binding
        try:
            self._queue.put_nowait((turn, binding, self.state.epoch))
        except asyncio.QueueFull:
            self._dropped += 1
            return False
        self._submitted += 1
        return True

    def invalidate(self) -> None:
        """Must be called on owner lock, grant expiry, or protected retirement."""
        self.state.clear()
        self._binding = None
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self._queue.task_done()
            self._dropped += 1

    async def drain(self) -> None:
        """Test/integration flush; never call on the synchronous voice path."""
        await self._queue.join()

    async def close(self) -> None:
        self._closed = True
        self.invalidate()
        task, self._worker = self._worker, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _current_binding(self) -> str | None:
        try:
            value = self._authorization_binding()
        except Exception:
            LOGGER.exception("Semantic owner binding check failed")
            return None
        return value if type(value) is str and value.strip() else None

    async def _run(self) -> None:
        while True:
            turn, binding, epoch = await self._queue.get()
            try:
                if not self._still_authorized(binding, epoch):
                    self._dropped += 1
                    continue
                proposals = await asyncio.wait_for(
                    self._producer(turn), timeout=self._timeout_seconds
                )
                if not self._still_authorized(binding, epoch):
                    self._dropped += 1
                    continue
                if not isinstance(proposals, (tuple, list)):
                    raise SemanticRejected("producer must return a proposal sequence")
                self.state.apply(self._conversation, turn, proposals, epoch=epoch)
                self._applied += 1
            except asyncio.CancelledError:
                raise
            except (SemanticRejected, TimeoutError, ValueError, TypeError):
                self._failures += 1
                LOGGER.warning(
                    "Semantic proposal rejected or timed out; canonical conversation unchanged"
                )
            except Exception:
                self._failures += 1
                LOGGER.exception("Semantic producer failed; conversation continues")
            finally:
                self._queue.task_done()

    def _still_authorized(self, binding: str, epoch: int) -> bool:
        return (
            not self._closed
            and self._conversation.status is ConversationStatus.ACTIVE
            and epoch == self.state.epoch
            and self._binding == binding
            and self._current_binding() == binding
        )
