"""Nothing private becomes audible before its exact request is verified.

Owner decision 2026-11-28: once owner-private context is in the live model
context (project history, released personal facts, recalled or inspected
memory, a receipt naming facts), the reply to a new request must not reach
playback until that exact request has positive owner speaker evidence.
Stopping speech after a failed verification is too late.

The gate sits at the output boundary: the agent's audio output nodes
(realtime audio and TTS) and its transcript node pass every frame / text
delta through ``PrivateOutputGate.hold``:

- no private context released (or enforcement off): frames pass at once;
- otherwise frames are held (not played, not forwarded) until the verdict:
  the request is the reply chain's own request, and while that request's
  transcript (same user activity) has not been accepted yet the verdict is
  pending; then its speaker evidence is awaited;
- owner: the held frames are released in order and the rest streams;
- unknown, non-owner, evidence timeout, transcript never accepted, or the
  wake closing: everything held and everything after is dropped, and the
  wake is ended (``on_denied``);
- private context released while a reply is already streaming (a tool or
  preload result landing late) starts holding from that frame.

Ordinary non-private conversation is never held.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterable, Callable

LOGGER = logging.getLogger(__name__)

TRANSCRIPT_WAIT_SECONDS = 5.0
_POLL = 0.05


class PrivateOutputGate:
    def __init__(
        self,
        *,
        evidence,
        settlement,
        released: Callable[[], bool],
        on_denied: Callable[[str | None], None] | None = None,
        transcript_wait: float = TRANSCRIPT_WAIT_SECONDS,
        closing: Callable[[], bool] = lambda: False,
    ):
        self._evidence = evidence
        self._settlement = settlement
        self._released = released
        self._on_denied = on_denied
        self._transcript_wait = transcript_wait
        self._closing = closing
        self.held_frames = 0
        self.dropped_frames = 0

    def required(self) -> bool:
        return bool(
            self._evidence is not None and self._evidence.enforcing and self._released()
        )

    async def _request_turn(self) -> str | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._transcript_wait
        while True:
            request = self._settlement.current_request()
            if request is not None:
                return request
            if loop.time() >= deadline or self._closing():
                return None
            await asyncio.sleep(_POLL)

    async def verdict(self) -> tuple[bool, str | None]:
        if self._closing():
            return False, None
        request = await self._request_turn()
        if request is None:
            return False, None
        return await self._evidence.owner_verified(request), request

    async def hold(self, stream: AsyncIterable, *, kind: str = "audio"):
        """Yield ``stream``'s items only once they may be heard (see module)."""
        decided: bool | None = None  # None: not needed yet / undecided
        verdict_task: asyncio.Task | None = None
        held: list = []
        try:
            async for item in stream:
                if decided is False:
                    self.dropped_frames += 1
                    continue
                if decided is None and self._closing():
                    decided = False
                    self.dropped_frames += 1 + len(held)
                    held.clear()
                    continue
                if decided is None and verdict_task is None:
                    if not self.required():
                        yield item
                        continue
                    verdict_task = asyncio.ensure_future(self.verdict())
                if decided is None:
                    held.append(item)
                    self.held_frames += 1
                    if not verdict_task.done():
                        continue
                    decided = await self._resolve(verdict_task, kind)
                    if not decided:
                        self.dropped_frames += len(held)
                        held.clear()
                        continue
                    for frame in held:
                        yield frame
                    held.clear()
                    continue
                yield item
            # The stream ended while the verdict was still pending.
            if decided is None and verdict_task is not None:
                decided = await self._resolve(verdict_task, kind)
                if decided:
                    for frame in held:
                        yield frame
                else:
                    self.dropped_frames += len(held)
                held.clear()
        finally:
            if verdict_task is not None and not verdict_task.done():
                verdict_task.cancel()

    async def _resolve(self, task, kind) -> bool:
        try:
            verified, request = await task
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - fail closed
            LOGGER.warning(
                "Private output verdict failed | error=%s", type(exc).__name__
            )
            verified, request = False, None
        if verified:
            LOGGER.info(
                "Private output released after owner verification | kind=%s | "
                "turn_id=%s",
                kind,
                request,
            )
            return True
        LOGGER.warning(
            "Private output withheld | reason=speaker_not_verified | kind=%s | "
            "turn_id=%s",
            kind,
            request,
        )
        if self._on_denied is not None:
            try:
                self._on_denied(request)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning(
                    "Private output denial handler failed | error=%s",
                    type(exc).__name__,
                )
        return False


def output_gate_for(session) -> PrivateOutputGate | None:
    return getattr(session, "_jarvis_private_output_gate", None)


def register_output_gate(session, gate) -> None:
    session._jarvis_private_output_gate = gate


def unregister_output_gate(session, gate) -> None:
    if getattr(session, "_jarvis_private_output_gate", None) is gate:
        session._jarvis_private_output_gate = None
