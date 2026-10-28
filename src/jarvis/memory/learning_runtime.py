"""Process-owned bounded learning queue; canonical accepted USER turns only."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import monotonic, perf_counter

from .learning_contracts import AcceptedLearningSource, LearningBatch
from .learning_controls import category_veto, suppression_binding
from .learning_diagnostics import log_learning
from .learning_limits import INFERENCE_TIMEOUT, PROCESSING_BUDGET
from .learning_policy import LearningPolicy

LOGGER = logging.getLogger(__name__)


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
        diagnostics=False,
    ):
        self.authority, self.service = authority, service
        self.extractor, self.resolver, self.reconciler = extractor, resolver, reconciler
        self.clock, self.status_observer = clock, status_observer
        self.diagnostics = diagnostics
        self._stage = "source_validation"
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
        self._unavailable_reported = False
        service.bind_learning_invalidator(self.invalidate_sources)
        for adapter in {id(extractor): extractor, id(resolver): resolver}.values():
            binder = getattr(adapter, "bind_source_validator", None)
            if callable(binder):
                binder(self._validate_inference_source)

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
                log_learning(
                    self.diagnostics, source, "source", "rejected", reason="source_veto"
                )
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
            log_learning(self.diagnostics, source, "source", "queued", text=source.text)
            self._enqueue(source.receipt_id)
        except (ValueError, PermissionError) as exc:
            state = self.authority.validate(grant)
            if state.status != "active" and not self._unavailable_reported:
                self._unavailable_reported = True
                LOGGER.warning(
                    "Automatic memory unavailable | state=%s | reason=%s | "
                    "new memories are not being saved; restart Jarvis and approve Windows Hello",
                    state.status,
                    state.reason,
                )
            # Canonical assistant turns are expected here; distinguish them from
            # rejected user sources without changing admission or counters.
            if self.diagnostics:
                LOGGER.info(
                    "Memory source skipped | turn_id=%s | role=%s | reason=%s | error_type=%s",
                    turn.turn_id,
                    turn.role.value,
                    "not_user_turn" if turn.role.value != "user" else "source_denied",
                    type(exc).__name__,
                )
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

    def _validate_inference_source(self, source):
        item = self._pending.get(source.receipt_id)
        if item is None or item[0] is not source:
            raise PermissionError("Learning source no longer registered")
        self._require(source.receipt_id, source, item[1])

    async def _infer(self, source, operation):
        remaining = source.created_monotonic + PROCESSING_BUDGET - self.clock()
        if remaining <= 0:
            raise TimeoutError("source processing budget exhausted")
        timeout = min(INFERENCE_TIMEOUT, remaining)
        started = perf_counter()
        log_learning(
            self.diagnostics,
            source,
            self._stage,
            "started",
            timeout_seconds=round(timeout, 3),
            source_age_ms=round((self.clock() - source.created_monotonic) * 1000, 1),
        )
        try:
            return await asyncio.wait_for(operation(), timeout)
        finally:
            log_learning(
                self.diagnostics,
                source,
                self._stage,
                "finished_wait",
                elapsed_ms=round((perf_counter() - started) * 1000, 1),
            )

    async def _process(self, receipt, source, grant):
        self._stage = "source_validation"
        self._require(receipt, source, grant)
        if receipt in self._controls:
            self._stage = "suppression"
            categories = self._controls[receipt]
            permit = self.authority.issue_child(
                grant, suppression_binding(source, categories)
            )
            await self.service.suppress_learning_categories(source, categories, permit)
            self._report("category_suppressed")
            return
        self._stage = "extraction"
        batch = await self._infer(source, lambda: self.extractor.extract(source))
        self._require(receipt, source, grant)
        self._stage = "eligibility"
        suppression = await self.service.learning_suppression()
        self._require(receipt, source, grant)
        eligible = []
        grounded_count = len(batch.candidates)
        for index, candidate in enumerate(batch.candidates):
            decision = LearningPolicy().evaluate(
                source, candidate, suppression.suppressed
            )
            log_learning(
                self.diagnostics,
                source,
                "eligibility",
                decision.status,
                grounded_index=index,
                candidate_index=len(eligible)
                if decision.status == "eligible"
                else None,
                reason=decision.reason,
                fact=candidate.model_dump(mode="json"),
            )
            if decision.status == "eligible":
                eligible.append(candidate)
        batch = LearningBatch(candidates=eligible)
        if not batch.candidates:
            log_learning(
                self.diagnostics,
                source,
                "eligibility",
                "no_eligible_fact",
                reason="no_grounded_candidates"
                if grounded_count == 0
                else "all_candidates_rejected",
            )
            self._report("no_eligible_fact")
            return
        self._stage = "catalog"
        catalog = await self.reconciler.catalog(source, batch, grant)
        log_learning(
            self.diagnostics, source, "catalog", "loaded", count=len(catalog.entries)
        )
        self._require(receipt, source, grant)
        catalog = catalog.model_copy(update={"suppression_epochs": suppression.epochs})
        self._stage = "resolution"
        resolutions = await self._infer(
            source, lambda: self.resolver.resolve(source, batch, catalog)
        )
        self._require(receipt, source, grant)
        log_learning(
            self.diagnostics,
            source,
            "resolution",
            "completed",
            decisions=resolutions.model_dump(mode="json")["resolutions"],
        )
        self._stage = "reconciliation"
        plan = self.reconciler.plan(source, batch, catalog, resolutions)
        if not plan.mutations:
            log_learning(self.diagnostics, source, "reconciliation", "no_change")
            self._report("no_change")
            return
        self._stage = "storage"
        permit = self.authority.issue_child(grant, plan.binding())
        result = await self.service.admit_learning(plan, permit)
        if result.status == "committed":
            self._committed += len(result.assertion_ids)
        log_learning(
            self.diagnostics,
            source,
            "storage",
            result.status,
            assertion_ids=list(result.assertion_ids),
            mutations=[
                {
                    "action": m.action,
                    "predicate": m.predicate,
                    "expected_assertion_id": m.expected_assertion_id,
                    "stored_value": m.draft.value if m.draft else None,
                }
                for m in plan.mutations
            ],
        )
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
                        log_learning(self.diagnostics, source, self._stage, "cancelled")
                    except TimeoutError:
                        self._dropped += 1
                        log_learning(
                            self.diagnostics,
                            source,
                            self._stage,
                            "timeout",
                            reason="inference_deadline",
                        )
                        self._report("timeout")
                    except Exception as exc:  # noqa: BLE001 - sanitized background failure boundary
                        self._dropped += 1
                        reason = (
                            str(exc)
                            if str(exc)
                            in {
                                "learning_provider_unavailable",
                                "learning_invalid_schema",
                                "learning_invalid_resolution",
                                "learning_unknown_target",
                                "source no longer current",
                            }
                            else "processing_denied"
                        )
                        log_learning(
                            self.diagnostics,
                            source,
                            self._stage,
                            "failed",
                            reason=reason,
                            error_type=type(exc).__name__,
                        )
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
