"""Awaited dispatch seam for the controlled project-memory path.

This does not attach to Gemini's proactive native-audio observer. The provider
must start generation only when generate(packet) is consumed, and include the
packet's context in that request. Playback admission must be synchronous: an
async callback could queue stale audio after this boundary's final check.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Protocol

from jarvis.memory.project_conversations import PreparedProjectReply


class StaleProjectReply(PermissionError):
    """The request, transport, source revision or authority ceased to be current."""


class ProjectReplyProvider(Protocol):
    def generate(self, packet: PreparedProjectReply) -> AsyncGenerator[bytes, None]: ...


class ProjectReplyDispatcher:
    def __init__(
        self,
        provider: ProjectReplyProvider,
        *,
        validate_current: Callable[[PreparedProjectReply], bool],
        release_audio: Callable[[bytes], None],
    ) -> None:
        self._provider = provider
        self._validate = validate_current
        self._release = release_audio
        self._epoch = 0
        self._request_id: str | None = None

    def invalidate(self, reason: str) -> None:
        """Call synchronously on speech, selection changes and transport retirement."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("invalidation reason required")
        self._epoch += 1

    async def reply(
        self,
        request_id: str,
        prepare: Callable[[], Awaitable[PreparedProjectReply]],
    ) -> PreparedProjectReply:
        """Await required capture/context; supersede any previous in-flight reply."""
        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("request_id required")
        if request_id == self._request_id:
            raise StaleProjectReply("request already admitted")
        self.invalidate("new_request")
        self._request_id = request_id
        epoch = self._epoch
        try:
            packet = await prepare()  # exceptions propagate; no best-effort save
        except BaseException:
            # No generation was admitted. Permit a retry after storage recovery,
            # without clearing a newer request that superseded this preparation.
            if self._epoch == epoch and self._request_id == request_id:
                self._request_id = None
            raise
        if (
            not isinstance(packet, PreparedProjectReply)
            or packet.request_id != request_id
        ):
            raise StaleProjectReply("prepared request identity changed")
        await self._dispatch(packet, epoch)
        return packet

    async def dispatch(self, prepared_reply: PreparedProjectReply) -> None:
        """Dispatch an already prepared packet, with the same currentness guards."""
        if not isinstance(prepared_reply, PreparedProjectReply):
            raise TypeError("prepared project reply required")
        if prepared_reply.request_id == self._request_id:
            raise StaleProjectReply("request already admitted")
        self.invalidate("new_request")
        self._request_id = prepared_reply.request_id
        await self._dispatch(prepared_reply, self._epoch)

    def _check(self, packet: PreparedProjectReply, epoch: int) -> None:
        if self._epoch != epoch or self._request_id != packet.request_id:
            raise StaleProjectReply("request or transport changed")
        if self._validate(packet) is not True:
            raise StaleProjectReply("context or authority no longer current")

    async def _dispatch(self, packet: PreparedProjectReply, epoch: int) -> None:
        self._check(packet, epoch)
        stream = self._provider.generate(packet)
        try:
            async for audio in stream:
                self._check(packet, epoch)
                self._release(audio)  # no suspension between admission and release
            self._check(packet, epoch)
        finally:
            await stream.aclose()
