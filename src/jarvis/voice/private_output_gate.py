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
  the request is the accepted turn of the user activity the generation
  started on (never an earlier request once someone spoke after it); while
  that transcript is not accepted the verdict is pending; then its speaker
  evidence is awaited; audio and transcript of one generation share it;
- owner: the held frames are released in order and the rest streams;
- unknown, non-owner or evidence timeout: everything held and everything
  after is dropped, and the wake is ended (``on_denied``); a transcript that
  never arrives, or a closing wake: dropped (nothing is heard);
- private context released while a reply is already streaming (a tool or
  preload result landing late) starts holding from that frame.

Ordinary non-private conversation is never held.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterable, Callable

LOGGER = logging.getLogger(__name__)

TRANSCRIPT_WAIT_SECONDS = 5.0
MAX_TRANSCRIPT_SECONDS = 60.0
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
        # One verdict per generation (its user-activity epoch), shared by its
        # audio and transcript streams.
        self._verdicts: dict[object, asyncio.Task] = {}
        self.held_frames = 0
        self.dropped_frames = 0

    def required(self) -> bool:
        return bool(
            self._evidence is not None and self._evidence.enforcing and self._released()
        )

    async def _verdict(self, epoch) -> tuple[bool, str | None]:
        """(verified, request). request None: the generation's transcript was
        never accepted (or the wake is closing)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + MAX_TRANSCRIPT_SECONDS
        while True:
            if self._closing():
                return False, None
            request = self._settlement.current_request(epoch)
            if request is not None:
                return await self._evidence.owner_verified(request), request
            if loop.time() >= deadline:
                return False, None
            await asyncio.sleep(_POLL)

    def _shared_verdict(self, epoch) -> asyncio.Task:
        task = self._verdicts.get(epoch)
        if task is None:
            task = asyncio.ensure_future(self._verdict(epoch))
            self._verdicts[epoch] = task
            while len(self._verdicts) > 16:
                old = self._verdicts.pop(next(iter(self._verdicts)))
                if not old.done():
                    old.cancel()
        return task

    async def hold(self, stream: AsyncIterable, *, kind: str = "audio"):
        """Yield ``stream``'s items only once they may be heard (see module).

        Held items are released the moment the owner verdict lands, not when
        the next item arrives. While the stream runs the verdict may wait for
        the request's transcript; after the stream ends it gets
        ``transcript_wait`` more seconds. A generation whose transcript never
        arrives is never heard; that alone does not end the wake (no speaker
        was judged)."""
        epoch = self._settlement.speech_epoch()
        iterator = stream.__aiter__()
        decided: bool | None = None
        verdict: asyncio.Task | None = None
        held: list = []
        ended = False
        upcoming: asyncio.Future | None = asyncio.ensure_future(iterator.__anext__())
        try:
            while True:
                if decided is None and verdict is not None and verdict.done():
                    decided = self._decide(verdict, kind)
                    if decided:
                        for item in held:
                            yield item
                    else:
                        self.dropped_frames += len(held)
                    held.clear()
                if ended:
                    if decided is None and verdict is not None:
                        try:
                            await asyncio.wait_for(
                                asyncio.shield(verdict), self._transcript_wait
                            )
                        except TimeoutError:
                            decided = False
                            self.dropped_frames += len(held)
                            held.clear()
                            LOGGER.warning(
                                "Private output withheld | reason=request_unresolved | "
                                "kind=%s",
                                kind,
                            )
                        continue
                    break
                waiting = [upcoming]
                if decided is None and verdict is not None:
                    waiting.append(verdict)
                done, _ = await asyncio.wait(
                    waiting, return_when=asyncio.FIRST_COMPLETED
                )
                if upcoming not in done:
                    continue  # the verdict landed: handled at the loop top
                try:
                    item = upcoming.result()
                except StopAsyncIteration:
                    ended, upcoming = True, None
                    continue
                upcoming = asyncio.ensure_future(iterator.__anext__())
                if decided is None and self._closing():
                    decided = False
                    self.dropped_frames += len(held)
                    held.clear()
                if decided is False:
                    self.dropped_frames += 1
                    continue
                if decided is True:
                    yield item
                    continue
                if verdict is None:
                    if not self.required():
                        yield item
                        continue
                    verdict = self._shared_verdict(epoch)
                held.append(item)
                self.held_frames += 1
        finally:
            if upcoming is not None and not upcoming.done():
                upcoming.cancel()
            close = getattr(stream, "aclose", None)
            if close is not None:
                with contextlib.suppress(Exception):
                    await close()

    def _decide(self, task, kind) -> bool:
        try:
            verified, request = task.result()
        except asyncio.CancelledError:
            verified, request = False, None
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
        if request is not None and self._on_denied is not None:
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
