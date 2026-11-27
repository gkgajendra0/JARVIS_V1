"""Process-owned bounded learning queue; canonical accepted USER turns only."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import monotonic, perf_counter

from jarvis.provider_retry import decide_retry

from .learning_clarification import (
    ALTERNATIVES,
    ClarificationBoard,
    alternatives_questions,
    answer_candidate,
    answers_the_question,
    chosen_values,
    clarification_for,
    has_statement,
    stated_details,
)
from .learning_contracts import AcceptedLearningSource, LearningBatch
from .learning_controls import category_veto, suppression_binding
from .learning_diagnostics import log_learning
from .learning_limits import INFERENCE_TIMEOUT, PROCESSING_BUDGET
from .learning_policy import LearningPolicy, ground_plan_label
from .memory_receipts import MemoryReceipts

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


def _already_held(note, entry) -> bool:
    """Skip alternatives already confirmed for this resolved plan."""
    if entry is None or note.kind != ALTERNATIVES:
        return False
    try:
        slots = json.loads(entry.value).get("slots") or {}
    except (TypeError, ValueError, AttributeError):
        return False
    return all(
        {o.casefold() for o in (slots.get(name) or {}).get("options") or ()}
        == {o.casefold() for o in options}
        for name, options in note.choices
    )


def _mutation_label(mutation, catalog):
    """The display name of the fact a committed mutation wrote or withdrew."""
    value = mutation.draft.value if mutation.draft is not None else None
    if isinstance(value, dict) and value.get("label"):
        return str(value["label"])
    if isinstance(value, str) and value:
        return value
    for entry in catalog.entries:
        if entry.assertion_id == mutation.expected_assertion_id:
            try:
                return json.loads(entry.value).get("label")
            except (TypeError, ValueError, AttributeError):
                return None
    return None


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
        retry_observer=None,
        sleep=asyncio.sleep,
        rng=random.random,
        clarification_observer=None,
        receipts=None,
    ):
        self.authority, self.service = authority, service
        # What learning verifiably did per owner turn (memory_receipts): the
        # only basis on which a reply may say something was saved.
        self.receipts = receipts if receipts is not None else MemoryReceipts()
        self._turn_ops = []
        self.extractor, self.resolver, self.reconciler = extractor, resolver, reconciler
        self.clock, self.status_observer = clock, status_observer
        # Content-free record of every provider attempt that failed and what
        # the bounded retry policy decided (jarvis.provider_retry).
        self.retry_observer = retry_observer
        self._sleep, self._rng = sleep, rng
        # "Meaning unclear" outcomes for the reply path (learning_clarification):
        # session-bound, offered once per detail, cleared on invalidation.
        self.clarifications = ClarificationBoard()
        self.clarification_observer = clarification_observer
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
        self._speaker_evidence = None
        self._admissions = set()
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

    def bind(self, conversation, grant, *, speaker_evidence=None):
        self._grant = grant
        self._speaker_evidence = speaker_evidence
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
                self.receipts.learning_started(source.session_id, source.turn_id)
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
            evidence = self._speaker_evidence
            if evidence is not None and evidence.enforcing:
                # The source is fixed now (latest turn, its context window);
                # registration waits for the speaker evidence. memory_status
                # reports it as still processing meanwhile.
                self.receipts.learning_started(source.session_id, source.turn_id)
                task = asyncio.create_task(
                    self._admit_after_evidence(evidence, source, turn, grant),
                    name="jarvis-learning-speaker-evidence",
                )
                self._admissions.add(task)
                task.add_done_callback(self._admissions.discard)
                return
            self._admit(source, turn, grant)
        except (ValueError, PermissionError) as exc:
            self._source_denied(turn, exc, grant)

    async def _admit_after_evidence(self, evidence, source, turn, grant):
        """Automatic learning admits only speech scored as the owner: an
        earlier context turn that is not is removed before any provider sees
        it, and the source itself is dropped unless it is."""
        try:
            for context_turn in source.turns[:-1]:
                if not evidence.admits_learning(
                    await evidence.wait(context_turn.turn_id)
                ):
                    self._vetoed.add(context_turn.turn_id)
            result = await evidence.wait(turn.turn_id)
        except BaseException:
            self.receipts.learning_finished(
                source.session_id, source.turn_id, "speaker_evidence_unavailable"
            )
            raise
        if self._closed:
            self.receipts.learning_finished(source.session_id, source.turn_id, "closed")
            return
        if not evidence.admits_learning(result):
            self._vetoed.add(turn.turn_id)
            log_learning(
                self.diagnostics,
                source,
                "source",
                "rejected",
                reason="speaker_not_owner",
                status=result.status.value,
                score=None if result.score is None else round(result.score, 4),
            )
            self.receipts.learning_finished(
                source.session_id, source.turn_id, "speaker_not_owner"
            )
            self._report("speaker_not_owner")
            return
        try:
            self._admit(source, turn, grant, receipt_started=True)
        except (ValueError, PermissionError) as exc:
            self.receipts.learning_finished(
                source.session_id, source.turn_id, "source_denied"
            )
            self._source_denied(turn, exc, grant)

    def _admit(self, source, turn, grant, *, receipt_started=False):
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
            if receipt_started:
                self.receipts.learning_finished(
                    source.session_id, source.turn_id, "queue_full"
                )
            self._report("queue_full")
            return
        self.authority.register_source(grant, source.receipt_id, source=source)
        self._pending[source.receipt_id] = (source, grant)
        log_learning(self.diagnostics, source, "source", "queued", text=source.text)
        if not receipt_started:
            self.receipts.learning_started(source.session_id, source.turn_id)
        self._enqueue(source.receipt_id)

    def _source_denied(self, turn, exc, grant):
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
        self.clarifications.clear()
        if turn_id is None:
            self._window_cutoff = datetime.now(UTC)
        for receipt, (source, grant) in tuple(self._pending.items()):
            if (turn_id is None or source.turn_id == turn_id) and (
                self._closed or receipt not in self._controls
            ):
                if receipt != self._inflight_receipt:
                    # The in-flight turn is finished by its own worker, with
                    # anything it already committed.
                    self.receipts.learning_finished(
                        source.session_id, source.turn_id, "sources_invalidated"
                    )
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

    async def _infer(self, source, operation, receipt=None, grant=None):
        """Run one provider stage inside the source's existing processing budget.

        This runtime is the single retry owner for direct provider calls: a
        temporary provider failure (503/500/lost connection) may be retried at
        most twice, after a growing randomized wait, only when the wait plus a
        useful attempt still fits in the remaining budget. Source validity and
        the learning grant are rechecked before every retry. Each attempt's
        timeout is the smaller of INFERENCE_TIMEOUT and the remaining budget, so
        retries never extend the budget or the 30-second source lease. A stall
        (no response before the timeout) is never retried. Failures from the
        model router are not retried here: the router owns its retries.
        """
        from .learning_extractors import LearningProviderUnavailable

        attempt = 0
        while True:
            attempt += 1
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
                attempt=attempt,
                timeout_seconds=round(timeout, 3),
                source_age_ms=round(
                    (self.clock() - source.created_monotonic) * 1000, 1
                ),
            )
            try:
                return await asyncio.wait_for(operation(), timeout)
            except LearningProviderUnavailable as exc:
                failure = exc.failure
                remaining = source.created_monotonic + PROCESSING_BUDGET - self.clock()
                if exc.retry_owner != "runtime":
                    decision_reason, delay, retry = "retry_owned_by_router", 0.0, False
                else:
                    decision = decide_retry(
                        failure, attempt=attempt, remaining=remaining, rng=self._rng
                    )
                    decision_reason = decision.reason
                    delay, retry = decision.delay, decision.retry
                self._observe_retry(
                    source,
                    attempt=attempt,
                    failure=failure,
                    decision=decision_reason,
                    delay=delay,
                    remaining=remaining,
                )
                if not retry:
                    raise
            finally:
                log_learning(
                    self.diagnostics,
                    source,
                    self._stage,
                    "finished_wait",
                    attempt=attempt,
                    elapsed_ms=round((perf_counter() - started) * 1000, 1),
                )
            await self._sleep(delay)
            # The wait may have outlived a revocation, a privacy control or the
            # session: recheck before dispatching again.
            self._require(receipt, source, grant)

    def _observe_retry(self, source, *, attempt, failure, decision, delay, remaining):
        kind = getattr(getattr(failure, "kind", None), "value", None)
        status = getattr(failure, "status_code", None)
        record = {
            "stage": self._stage,
            "attempt": attempt,
            "failure_kind": kind,
            "status": status if type(status) is int else None,
            "decision": decision,
            "delay_seconds": delay,
            "remaining_seconds": round(remaining, 3),
        }
        log_learning(
            self.diagnostics,
            source,
            self._stage,
            "attempt_failed",
            **{k: v for k, v in record.items() if k != "stage"},
        )
        if self.retry_observer is not None:
            try:
                self.retry_observer(record)
            except Exception:
                LOGGER.debug("learning retry observer failed", exc_info=True)

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
            self._turn_ops = [("suppress", category) for category in categories]
            self._report("category_suppressed")
            return
        self._stage = "extraction"
        window = {t.turn_id for t in source.turns}
        open_questions = [
            n
            for n in self.clarifications.pending(source.session_id)
            if n.turn_id in window and n.turn_id != source.turn_id
        ]
        if open_questions:
            views = [n.model_view() for n in open_questions]
            batch = await self._infer(
                source,
                lambda: self.extractor.extract(source, open_questions=views),
                receipt,
                grant,
            )
        else:
            batch = await self._infer(
                source, lambda: self.extractor.extract(source), receipt, grant
            )
        self._require(receipt, source, grant)
        answered, answers, replaced = self._answered(source, batch, open_questions)
        self._stage = "eligibility"
        suppression = await self.service.learning_suppression()
        self._require(receipt, source, grant)
        eligible = []
        notes, confirmation_questions = [], {}
        proposals = [
            (candidate, ())
            for index, candidate in enumerate(batch.candidates)
            if index not in replaced
        ] + answers
        grounded_count = len(proposals)
        for index, (candidate, questions) in enumerate(proposals):
            grounded = ground_plan_label(source, candidate)
            if grounded is not candidate:
                log_learning(
                    self.diagnostics,
                    source,
                    "eligibility",
                    "label_from_value",
                    grounded_index=index,
                )
                candidate = grounded
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
                ordinal = len(eligible)
                eligible.append(candidate)
                if questions:
                    confirmation_questions[ordinal] = questions
                if note := clarification_for(source, candidate):
                    notes.append((ordinal, note))
                notes.extend(
                    (ordinal, note)
                    for note in alternatives_questions(source, candidate)
                )
            elif decision.reason == "meaning_unclear":
                if note := clarification_for(source, candidate, dropped_unclear=True):
                    notes.append((None, note))
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
            self._publish(source, (note for _, note in notes), (), answered)
            self._report("no_eligible_fact")
            return
        self._stage = "catalog"
        targets = {
            i: questions[0].plan_predicate
            for i, questions in confirmation_questions.items()
            if questions[0].plan_predicate is not None
        }
        catalog = await self.reconciler.catalog(
            source, batch, grant, targets=tuple(targets.values())
        )
        log_learning(
            self.diagnostics, source, "catalog", "loaded", count=len(catalog.entries)
        )
        self._require(receipt, source, grant)
        catalog = catalog.model_copy(update={"suppression_epochs": suppression.epochs})
        self._stage = "resolution"
        resolutions = await self._infer(
            source,
            lambda: self.resolver.resolve(source, batch, catalog),
            receipt,
            grant,
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
        plan = self.reconciler.plan(
            source,
            batch,
            catalog,
            resolutions,
            confirmation_targets=targets,
        )
        committed = {}
        if not plan.mutations and not plan.outcomes:
            log_learning(self.diagnostics, source, "reconciliation", "no_change")
            status = "no_change"
        else:
            self._stage = "storage"
            permit = self.authority.issue_child(grant, plan.binding())
            result = await self.service.admit_learning(plan, permit)
            status = result.status
            if status == "committed":
                self._committed += len(result.assertion_ids)
                self._turn_ops = [
                    (m.action, _mutation_label(m, catalog)) for m in plan.mutations
                ]
                committed = {
                    m.ordinal: m.predicate
                    for m in plan.mutations
                    if m.draft is not None
                }
            log_learning(
                self.diagnostics,
                source,
                "storage",
                status,
                assertion_ids=list(result.assertion_ids),
                skipped=[
                    {"candidate_index": o.ordinal, "reason": o.reason}
                    for o in plan.outcomes
                ],
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

        if status == "committed":
            # A plan that ended (cancelled, completed or withdrawn) leaves
            # nothing to ask about it.
            for mutation in plan.mutations:
                value = mutation.draft.value if mutation.draft is not None else None
                if mutation.action == "retract" or (
                    isinstance(value, dict)
                    and value.get("state") in {"cancelled", "completed"}
                ):
                    for note in self.clarifications.pending(source.session_id):
                        if note.plan_predicate == mutation.predicate:
                            self.clarifications.close(note)
        by_id = {entry.assertion_id: entry for entry in catalog.entries}
        matched = {i: by_id[aid] for i, aid in plan.matched_plan_ids}
        predicates = {i: entry.predicate for i, entry in matched.items()} | committed
        skipped = {o.ordinal for o in plan.outcomes} | {
            m.ordinal for m in plan.mutations if m.ordinal not in committed
        }
        settled = [
            (eligible[i], predicate)
            for i, predicate in predicates.items()
            if i not in skipped
        ]
        for i, questions in confirmation_questions.items():
            answered.extend(
                question
                for question in questions
                if i in committed or _already_held(question, matched.get(i))
            )
        self._publish(
            source,
            (
                replace(note, plan_predicate=predicates.get(i))
                for i, note in notes
                if not _already_held(note, matched.get(i))
            ),
            settled,
            answered,
        )
        self._report(status)

    def _answered(self, source, batch, open_questions):
        """The owner's answers to open questions, as the extractor read them.

        Code decides what each allows. Confirmed alternatives and checked
        choices become one proposal per plan, from the question's own identity
        and the owner's original words plus the current turn
        (:func:`answer_candidate`); it must then reconcile to the question's
        canonical plan. The extractor's own proposal of the same answer is
        replaced (``replaced``: its batch indices), so a paraphrased name or a
        missing earlier citation cannot block or duplicate it. An answer code
        cannot check stores nothing and leaves its question open.

        Returns ``(answered, [(candidate, questions)], replaced)``."""
        by_id = {n.question_id: n for n in open_questions}
        current = next(
            (t.text for t in source.turns if t.turn_id == source.turn_id), ""
        )
        answered, confirmed, chosen = [], [], []
        for answer in batch.answers:
            note = by_id.pop(answer.question_id, None)
            if note is None:
                continue
            log_learning(
                self.diagnostics,
                source,
                "clarification",
                "answered",
                question=note.kind,
                answer=answer.answer,
                details=list(note.details),
            )
            if answer.answer in {"confirmed", "chosen"} and not has_statement(current):
                # A question back is not an answer, whatever the reading.
                self._unusable(source, note, "question_not_answer")
            elif answer.answer == "confirmed" and note.kind == ALTERNATIVES:
                confirmed.append(note)
            elif answer.answer == "chosen" and note.details:
                chosen.append(note)
            else:
                answered.append(note)
        values, refused = chosen_values(source, chosen, batch.candidates)
        for note, reason in refused:
            self._unusable(source, note, reason)
        replaced = {
            index
            for index, candidate in enumerate(batch.candidates)
            if answers_the_question(source, candidate, chosen, values)
        }
        groups: dict[object, tuple[list, list]] = {}

        def group(note):
            key = note.plan_predicate or ("proposal", id(note.candidate))
            return groups.setdefault(key, ([], []))

        for note in confirmed:
            group(note)[0].append(note)
        for note in chosen:
            if note.question_id in values:
                group(note)[1].append((note, values[note.question_id]))
        answers = []
        room = 8 - len(batch.candidates) + len(replaced)
        for confirms, picks in groups.values():
            questions = [*confirms, *(n for n, _ in picks)]
            candidate, reason = answer_candidate(source, confirms, picks)
            if candidate is not None and len(answers) >= room:
                candidate, reason = None, "too_many_proposals"
            if candidate is None:
                for note in questions:
                    self._unusable(source, note, reason)
                continue
            answers.append((candidate, questions))
        return answered, answers, replaced

    def _unusable(self, source, note, reason):
        """An answer that stores nothing: recorded, never claimed; the question
        stays open in its conversation."""
        log_learning(
            self.diagnostics,
            source,
            "clarification",
            "answer_not_used",
            question=note.kind,
            details=list(note.details),
            reason=reason,
        )

    def _publish(self, source, notes, settled, answered=()):
        """After the turn's learning completed: answered questions close;
        details stated clearly settle earlier questions about them; new
        questions go to the reply path. Nothing here is a storage receipt."""
        closed = set()
        for note in answered:
            self.clarifications.close(note)
            closed.add(note.key)
        for candidate, predicate in settled:
            details = stated_details(candidate)
            if details:
                self.clarifications.resolve(
                    source.session_id,
                    candidate.category,
                    candidate.label or candidate.value,
                    details,
                    plan_predicate=predicate,
                )
        for note in notes:
            if note.key in closed or not self.clarifications.offer(note):
                continue
            log_learning(
                self.diagnostics,
                source,
                "clarification",
                "offered",
                category=note.category,
                details=list(note.details),
            )
            if self.clarification_observer is not None:
                try:
                    self.clarification_observer(note)
                except Exception as exc:  # noqa: BLE001 - reply path never breaks learning
                    LOGGER.warning(
                        "Learning clarification observer failed | error=%s",
                        type(exc).__name__,
                    )

    async def _run(self):
        while not self._closed:
            receipt = await self._queue.get()
            item = self._pending.get(receipt)
            try:
                if item:
                    source, grant = item
                    self._turn_ops = []
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
                    self.receipts.learning_finished(
                        item[0].session_id,
                        item[0].turn_id,
                        self._reason,
                        self._turn_ops,
                    )
                    self._turn_ops = []
                    self.authority.release_source(item[1], receipt)
                self._pending.pop(receipt, None)
                self._controls.pop(receipt, None)
                self._inflight = None
                self._inflight_receipt = None
                self._queue.task_done()

    async def drain(self):
        while self._admissions:
            await asyncio.gather(*tuple(self._admissions), return_exceptions=True)
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
        for task in tuple(self._admissions):
            task.cancel()
        for adapter in {
            id(self.extractor): self.extractor,
            id(self.resolver): self.resolver,
        }.values():
            close = getattr(adapter, "close", None)
            if close:
                await close()
