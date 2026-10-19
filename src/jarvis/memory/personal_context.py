"""Read-only personal-context shadow boundary; never updates a voice provider.

The first native source preserves bounded exact-fact recall. It does not implement
general advice relevance, implicit memory admission, or a live context bridge.
Packets are transient diagnostics and cannot authorize actions or provider release.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

from jarvis.conversation import (
    ConversationRole,
    ConversationSession,
    ConversationStatus,
)

from .assertions import SemanticAssertionRecord
from .context import Utf8ByteBudgetEstimator
from .evidence_gate import MemoryEvidenceDisposition
from .provider_verified_query import ProviderVerifiedMemoryQueryCoordinator
from .query import CanonicalMemoryReader
from .query_coordinator import MemoryQueryCoordinator
from .query_plan import MemoryFacetKey
from .retrieval import RetrievalEligibility, SemanticRetrievalService
from .types import (
    AssertionState,
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
)


@dataclass(frozen=True, slots=True)
class PersonalContextRequest:
    turn_id: str
    session_id: str
    requester: str
    utterance: str
    as_of: datetime
    destination: Literal["local", "cloud"]
    budget_units: int
    deadline_ms: int

    def __post_init__(self) -> None:
        for name in ("turn_id", "session_id", "requester", "utterance"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty string")
        if not isinstance(self.as_of, datetime):
            raise TypeError("as_of must be a datetime")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if self.destination not in {"local", "cloud"}:
            raise ValueError("destination must be local or cloud")
        for name in ("budget_units", "deadline_ms"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class PersonalContextEvidence:
    assertion_id: str
    source_ids: tuple[str, ...]
    text: str
    subject: str
    observed_at: datetime
    valid_until: datetime | None
    sensitivity: Sensitivity
    authority_class: AuthorityClass
    source_version: str


@dataclass(frozen=True, slots=True)
class PersonalContextPacket:
    turn_id: str
    session_id: str
    status: Literal["ready", "abstain", "unavailable", "stale_turn"]
    evidence: tuple[PersonalContextEvidence, ...]
    used_units: int
    reason_codes: tuple[str, ...]
    elapsed_ms: float
    budget_unit: str = "utf8_bytes_with_framing"

    def operational_summary(self) -> dict:
        """Safe diagnostic projection: no utterance, source text or private error."""
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "status": self.status,
            "evidence_count": len(self.evidence),
            "used_units": self.used_units,
            "budget_unit": self.budget_unit,
            "reason_codes": list(self.reason_codes),
            "elapsed_ms": self.elapsed_ms,
        }


class NativePersonalContextSource:
    """Read existing admitted owner facts; recheck eligibility at shadow release.

    Coordinator configuration remains caller-owned, including any provider verifier.
    A model proposal alone never supplies canonical text, provenance or currentness.
    Canonical source IDs are immutable under MemoryLifecycleService.
    """

    def __init__(
        self,
        *,
        coordinator: MemoryQueryCoordinator | ProviderVerifiedMemoryQueryCoordinator,
        retrieval: SemanticRetrievalService,
        reader: CanonicalMemoryReader,
    ) -> None:
        if not isinstance(
            coordinator,
            (MemoryQueryCoordinator, ProviderVerifiedMemoryQueryCoordinator),
        ):
            raise TypeError("coordinator must be a native memory query coordinator")
        if not isinstance(retrieval, SemanticRetrievalService):
            raise TypeError("retrieval must be SemanticRetrievalService")
        if not isinstance(reader, CanonicalMemoryReader):
            raise TypeError("reader must be CanonicalMemoryReader")
        self._coordinator = coordinator
        self._retrieval = retrieval
        self._reader = reader

    @staticmethod
    def _eligibility(request: PersonalContextRequest) -> RetrievalEligibility:
        policy = (
            RetrievalEligibility.cloud_context()
            if request.destination == "cloud"
            else RetrievalEligibility.local()
        )
        # This slice measures explicit admitted owner memory, not inferred profiles.
        return RetrievalEligibility(
            authorities=frozenset({AuthorityClass.OWNER_EXPLICIT}),
            sensitivities=policy.sensitivities,
        )

    async def propose(
        self, request: PersonalContextRequest
    ) -> SemanticAssertionRecord | None:
        decision = await self._coordinator.resolve(
            request.utterance, eligibility=self._eligibility(request)
        )
        if (
            decision.disposition is MemoryEvidenceDisposition.ABSTAIN
            or decision.evidence is None
        ):
            return None
        return decision.evidence.assertion

    async def revalidate(
        self,
        candidate: SemanticAssertionRecord,
        request: PersonalContextRequest,
        *,
        now: datetime,
    ) -> PersonalContextEvidence | None:
        if candidate.subject_scope != "personal" or candidate.subject != "owner":
            return None
        source = await self._reader.get_source(candidate.source_id)
        if (
            source is None
            or source.source_class is not MemorySourceClass.OWNER_EXPLICIT
        ):
            return None
        if source.authority_class is not AuthorityClass.OWNER_EXPLICIT:
            return None
        if (
            source.sensitivity is not candidate.sensitivity
            or source.observed_at > request.as_of
        ):
            return None
        if (
            candidate.state is not AssertionState.ACTIVE
            or candidate.system_to is not None
        ):
            return None
        if (
            candidate.system_from > request.as_of
            or candidate.updated_at > request.as_of
        ):
            return None
        if candidate.valid_from is not None and candidate.valid_from > request.as_of:
            return None
        if candidate.valid_to is not None and candidate.valid_to <= max(
            now, request.as_of
        ):
            return None
        # No refresh/expiry contract exists for open-ended time-sensitive observations.
        if candidate.freshness_class is FreshnessClass.TIME_SENSITIVE:
            return None
        facet = MemoryFacetKey(
            candidate.subject_scope, candidate.subject, candidate.predicate
        )
        current = await self._retrieval.retrieve_exact_current_facet(
            facet, eligibility=self._eligibility(request)
        )
        if current != (candidate,):
            return None
        # Render the canonical structured value, not adapter prose or a source quote.
        text = json.dumps(
            {
                "subject": candidate.subject,
                "predicate": candidate.predicate,
                "value": candidate.value,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        version = json.dumps(
            {"assertion": asdict(candidate), "source": asdict(source)},
            sort_keys=True,
            default=lambda value: value.isoformat(),
            ensure_ascii=False,
            allow_nan=False,
        )
        return PersonalContextEvidence(
            assertion_id=candidate.assertion_id,
            source_ids=(source.source_id,),
            text=text,
            subject=candidate.subject,
            observed_at=source.observed_at,
            valid_until=candidate.valid_to,
            sensitivity=source.sensitivity,
            authority_class=source.authority_class,
            source_version=hashlib.sha256(version.encode("utf-8")).hexdigest(),
        )


class PersonalContextSelector:
    """OFF by default; explicit SHADOW reads with accepted-turn and epoch binding.

    Identity comes from a trusted caller-owned observer, never from the request
    declaring itself owner. ConversationSession is canonical turn truth, not the
    provider conversation. There is no writer, executor, provider, or packet cache.
    All methods run on the owning event loop. Reconnect/OFF invalidate pending reads.
    """

    def __init__(
        self,
        *,
        source: NativePersonalContextSource,
        conversation: ConversationSession,
        requester: Callable[[], str],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(source, NativePersonalContextSource):
            raise TypeError("source must be NativePersonalContextSource")
        if not isinstance(conversation, ConversationSession):
            raise TypeError("conversation must be ConversationSession")
        if not callable(requester):
            raise TypeError("requester must be a trusted identity observer")
        self._source = source
        self._conversation = conversation
        self._requester = requester
        self._clock = clock or (lambda: datetime.now(UTC))
        self._enabled = False
        self._epoch = 0
        self._pending: set[asyncio.Task] = set()
        self._last_key: tuple | None = None
        self._estimator = Utf8ByteBudgetEstimator()

    def _invalidate(self) -> None:
        self._epoch += 1
        for task in tuple(self._pending):
            task.cancel()

    def set_enabled(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be bool")
        if self._enabled != enabled:
            self._enabled = enabled
            self._invalidate()

    def reconnect(self, conversation: ConversationSession) -> None:
        if not isinstance(conversation, ConversationSession):
            raise TypeError("conversation must be ConversationSession")
        self._invalidate()
        self._conversation = conversation
        self._last_key = None

    def _binding_failure(
        self, request: PersonalContextRequest, epoch: int
    ) -> tuple[str, str] | None:
        if not self._enabled:
            return "abstain", "disabled"
        if self._epoch != epoch:
            return "stale_turn", "session_invalidated"
        if request.requester != "owner" or self._requester() != "owner":
            return "abstain", "owner_required"
        if (
            self._conversation.status is not ConversationStatus.ACTIVE
            or self._conversation.session_id != request.session_id
        ):
            return "stale_turn", "session_changed"
        turn = next(
            (
                turn
                for turn in reversed(self._conversation.turns)
                if turn.role is ConversationRole.USER
            ),
            None,
        )
        if (
            turn is None
            or turn.turn_id != request.turn_id
            or turn.text != request.utterance
        ):
            return "stale_turn", "accepted_turn_changed"
        return None

    def _finished(self, task: asyncio.Task) -> None:
        self._pending.discard(task)
        if not task.cancelled():
            task.exception()  # Consume failures from reads abandoned at the deadline.

    async def select(self, request: PersonalContextRequest) -> PersonalContextPacket:
        if not isinstance(request, PersonalContextRequest):
            raise TypeError("request must be PersonalContextRequest")
        started = time.monotonic()
        epoch = self._epoch
        abandoned = False

        def packet(status, reason, evidence=(), used_units=0):
            return PersonalContextPacket(
                turn_id=request.turn_id,
                session_id=request.session_id,
                status=status,
                evidence=evidence,
                used_units=used_units,
                reason_codes=(reason,),
                elapsed_ms=(time.monotonic() - started) * 1000,
            )

        async def read():
            candidate = await self._source.propose(request)
            # A slow provider may suppress cancellation. Do not start further reads
            # once its request has expired or OFF/reconnect/identity invalidated it.
            if abandoned or self._binding_failure(request, epoch):
                return None, "session_invalidated"
            if (time.monotonic() - started) * 1000 >= request.deadline_ms:
                return None, "deadline_exceeded"
            if candidate is None:
                return None, "native_abstained"
            evidence = await self._source.revalidate(
                candidate, request, now=self._clock()
            )
            return evidence, "source_changed" if evidence is None else "shadow_only"

        task = None
        try:
            failure = self._binding_failure(request, epoch)
            if failure:
                return packet(*failure)
            if request.as_of > self._clock():
                return packet("abstain", "future_request")
            key = (epoch, request.session_id, request.turn_id)
            if key == self._last_key:
                return packet("abstain", "duplicate_turn")
            # Cancellation is cooperative. A provider may still hold the previous
            # request after timeout; do not accumulate requests behind a stuck read.
            if any(not pending.done() for pending in self._pending):
                return packet("unavailable", "source_busy")
            self._last_key = key
            task = asyncio.create_task(read())
            self._pending.add(task)
            task.add_done_callback(self._finished)
            done, _ = await asyncio.wait({task}, timeout=request.deadline_ms / 1000)
            failure = self._binding_failure(request, epoch)
            if failure:
                abandoned = True
                task.cancel()
                return packet(*failure)
            if not done or (time.monotonic() - started) * 1000 >= request.deadline_ms:
                abandoned = True
                task.cancel()
                return packet("unavailable", "deadline_exceeded")
            evidence, reason = task.result()
            if evidence is None:
                return packet("abstain", reason)
            units = self._estimator.estimate_text(evidence.text)
            if units > request.budget_units:
                return packet("abstain", "budget_exceeded")
            return packet("ready", "shadow_only", (evidence,), units)
        except asyncio.CancelledError:
            abandoned = True
            if task is not None:
                task.cancel()
            raise
        except Exception:  # noqa: BLE001 -- Fail closed without logging private provider errors.
            abandoned = True
            if task is not None:
                task.cancel()
            return packet("unavailable", "source_unavailable")
