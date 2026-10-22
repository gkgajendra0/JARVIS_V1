"""Process-owned bounded learning queue; canonical accepted USER turns only."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import monotonic

from .learning_contracts import AcceptedLearningSource, LearningBatch
from .learning_controls import category_veto, suppression_binding
from .learning_policy import LearningPolicy

INFERENCE_TIMEOUT = 10.0


@dataclass(frozen=True)
class LearningRuntimeStatus:
    mode: str
    session: str
    queued: int
    processed: int
    committed: int
    dropped: int
    reason: str


class PersonalLearningRuntime:
    def __init__(
        self,
        authority,
        service,
        extractor,
        resolver,
        reconciler,
        *,
        clock=monotonic,
        status_observer=None,
    ):
        self.authority, self.service = authority, service
        self.extractor, self.resolver, self.reconciler = extractor, resolver, reconciler
        self.clock, self.status_observer = clock, status_observer
        self._queue = asyncio.Queue(maxsize=32)
        self._pending = {}
        self._controls = {}
        self._seen = set()
        self._vetoed = set()
        self._window_cutoff = None
        self._worker = None
        self._inflight = None
        self._inflight_receipt = None
        self._closed = False
        self._grant = None
        self._processed = self._committed = self._dropped = 0
        self._reason = "ready"
        service.bind_learning_invalidator(self.invalidate_sources)

    def status(self):
        state = (
            "closed"
            if self._closed
            else (
                self.authority.validate(self._grant).status
                if self._grant
                else "inactive"
            )
        )
        return LearningRuntimeStatus(
            "apply",
            state,
            self._queue.qsize(),
            self._processed,
            self._committed,
            self._dropped,
            self._reason,
        )

    def _report(self, reason):
        self._reason = reason
        if self.status_observer:
            self.status_observer(self.status())

    def bind(self, conversation, grant):
        self._grant = grant
        return lambda turn: self.observe_turn(conversation, turn, grant)

    def observe_turn(self, conversation, turn, grant):
        if self._closed or turn.turn_id in self._seen:
            return
        try:
            source = AcceptedLearningSource.from_turn(
                self.authority.runtime_id_for(grant),
                conversation,
                turn,
                now=self.clock(),
            )
            if len(self._seen) >= 4096:
                raise PermissionError("input limit")
            self._seen.add(turn.turn_id)
            self.authority.observe_accepted_input(grant, turn.turn_id)
            categories = category_veto(source.text)
            if categories:
                self._vetoed.add(turn.turn_id)
                self.invalidate_sources()
                if any(
                    set(categories) <= set(keys) for keys in self._controls.values()
                ):
                    self._report("category_suppression_pending")
                    return
                self.authority.register_source(grant, source.receipt_id, source=source)
                self._pending[source.receipt_id] = (source, grant)
                self._controls[source.receipt_id] = categories
                self._enqueue(source.receipt_id)
                return
            if not LearningPolicy.source_allowed(source):
                self._vetoed.add(turn.turn_id)
                self.invalidate_sources(turn_id=turn.turn_id)
                self._report("source_veto")
                return
            # Remove vetoed/pre-forget context before any provider receives it.
            turns = tuple(
                t
                for t in source.turns
                if t.turn_id not in self._vetoed
                and LearningPolicy.source_allowed(replace(source, turns=(t,)))
                and (self._window_cutoff is None or t.accepted_at > self._window_cutoff)
            )
            if not turns or turns[-1] is not turn:
                raise PermissionError("stale input")
            source = replace(
                source,
                turns=turns,
                digest=hashlib.sha256(
                    json.dumps(
                        [(t.turn_id, t.text) for t in turns], ensure_ascii=False
                    ).encode()
                ).hexdigest(),
            )
            if self._queue.full():
                self._dropped += 1
                self._report("queue_full")
                return
            self.authority.register_source(grant, source.receipt_id, source=source)
            self._pending[source.receipt_id] = (source, grant)
            self._enqueue(source.receipt_id)
        except (ValueError, PermissionError):
            self._dropped += 1
            self._report("source_denied")

    def _enqueue(self, receipt):
        self._queue.put_nowait(receipt)
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(
                self._run(), name="jarvis-personal-learning"
            )

    def invalidate_sources(self, category=None, turn_id=None):
        if turn_id is None:
            self._window_cutoff = datetime.now(UTC)
        for receipt, (source, grant) in tuple(self._pending.items()):
            if (turn_id is None or source.turn_id == turn_id) and (
                self._closed or receipt not in self._controls
            ):
                self.authority.release_source(grant, receipt)
                self._pending.pop(receipt, None)
                self._controls.pop(receipt, None)
        # Retire dead queue entries immediately, so a full fact queue cannot
        # discard an owner privacy control. Preserve live control ordering.
        retained = []
        while not self._queue.empty():
            receipt = self._queue.get_nowait()
            self._queue.task_done()
            if receipt in self._pending:
                retained.append(receipt)
        for receipt in retained:
            self._queue.put_nowait(receipt)
        if (
            self._inflight
            and not self._inflight.done()
            and (self._closed or self._inflight_receipt not in self._controls)
        ):
            self._inflight.cancel()
        self._report("sources_invalidated")

    def _require(self, receipt, source, grant):
        if (
            self._closed
            or receipt not in self._pending
            or self.clock() >= source.created_monotonic + 30
            or self.authority.validate(grant).status != "active"
        ):
            raise PermissionError("source no longer current")

    async def _process(self, receipt, source, grant):
        self._require(receipt, source, grant)
        if receipt in self._controls:
            categories = self._controls[receipt]
            permit = self.authority.issue_child(
                grant, suppression_binding(source, categories)
            )
            await self.service.suppress_learning_categories(source, categories, permit)
            self._report("category_suppressed")
            return
        batch = await asyncio.wait_for(
            self.extractor.extract(source), INFERENCE_TIMEOUT
        )
        self._require(receipt, source, grant)
        suppression = await self.service.learning_suppression()
        self._require(receipt, source, grant)
        batch = LearningBatch(
            candidates=[
                c
                for c in batch.candidates
                if LearningPolicy().evaluate(source, c, suppression.suppressed).status
                == "eligible"
            ]
        )
        if not batch.candidates:
            self._report("no_eligible_fact")
            return
        catalog = await self.reconciler.catalog(source, batch, grant)
        self._require(receipt, source, grant)
        catalog = catalog.model_copy(update={"suppression_epochs": suppression.epochs})
        resolutions = await asyncio.wait_for(
            self.resolver.resolve(source, batch, catalog), INFERENCE_TIMEOUT
        )
        self._require(receipt, source, grant)
        plan = self.reconciler.plan(source, batch, catalog, resolutions)
        if not plan.mutations:
            self._report("no_change")
            return
        permit = self.authority.issue_child(grant, plan.binding())
        result = await self.service.admit_learning(plan, permit)
        if result.status == "committed":
            self._committed += len(result.assertion_ids)
        self._report(result.status)

    async def _run(self):
        while not self._closed:
            receipt = await self._queue.get()
            item = self._pending.get(receipt)
            try:
                if item:
                    source, grant = item
                    self._inflight_receipt = receipt
                    self._inflight = asyncio.create_task(
                        self._process(receipt, source, grant)
                    )
                    try:
                        await self._inflight
                    except asyncio.CancelledError:
                        if self._closed:
                            return
                        self._dropped += 1
                    except TimeoutError:
                        self._dropped += 1
                        self._report("timeout")
                    except Exception:  # noqa: BLE001 - sanitized background failure boundary
                        self._dropped += 1
                        self._report("processing_denied")
                    self._processed += 1
            finally:
                if item:
                    self.authority.release_source(item[1], receipt)
                self._pending.pop(receipt, None)
                self._controls.pop(receipt, None)
                self._inflight = None
                self._inflight_receipt = None
                self._queue.task_done()

    async def drain(self):
        await self._queue.join()

    async def close(self):
        if self._closed:
            return
        self._closed = True
        self.invalidate_sources()
        if self._worker:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()
        self._seen.clear()
        self._vetoed.clear()
        for adapter in {
            id(self.extractor): self.extractor,
            id(self.resolver): self.resolver,
        }.values():
            close = getattr(adapter, "close", None)
            if close:
                await close()
