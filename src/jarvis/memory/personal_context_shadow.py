"""PI-1B isolated read-only personal-context shadow.

This deliberately has NO provider/chat context delivery, memory mutation,
network calls, or production entrypoint. A future owner-approved integration
must separately prove eligibility, selector quality, and provider behavior.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from .query_plan import MemoryFacetCatalog, MemoryFacetKey
from .retrieval import RetrievalEligibility, SemanticRetrievalService
from .types import (
    AssertionState,
    AuthorityClass,
    FreshnessClass,
    Sensitivity,
    VerificationState,
)

# Conservative PI-1B gate: even PRIVATE and INFERRED are excluded.
# This is intentionally narrower than the existing cloud_context() utility.
_SHADOW_ELIGIBILITY = RetrievalEligibility(
    authorities=frozenset(
        {
            AuthorityClass.OWNER_EXPLICIT,
            AuthorityClass.OWNER_DIRECT,
            AuthorityClass.VERIFIED,
        }
    ),
    sensitivities=frozenset({Sensitivity.STANDARD}),
)


class ShadowDisposition(StrEnum):
    SELECTED = "selected"
    NO_MATCH = "no_match"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ShadowPersonalFact:
    assertion_id: str
    predicate: str
    source_id: str
    compact_text: str
    sensitivity: Sensitivity
    authority_checked: bool


@dataclass(frozen=True, slots=True)
class ShadowPersonalPacket:
    question_sha256: str
    disposition: ShadowDisposition
    facts: tuple[ShadowPersonalFact, ...]
    dropped_count: int
    byte_budget: int
    mode: str = "shadow"

    def export_to_provider(self) -> None:
        """Never provide an escape hatch for accidental live-model injection."""
        raise RuntimeError("PI-1B shadow packet cannot be sent to a provider")


class PersonalFacetSelector(Protocol):
    async def select(
        self, question: str, catalog: MemoryFacetCatalog
    ) -> tuple[MemoryFacetKey, ...]:
        """Suggest canonical facets; proposals have zero release authority."""


class ShadowPersonalContextCoordinator:
    """Apply canonical read eligibility AFTER a replaceable facet proposal.

    Source-of-truth assertions remain JARVIS's existing SQLCipher memory;
    this object only reads eligible records. Failure -> empty packet.
    """

    def __init__(
        self,
        *,
        retrieval: SemanticRetrievalService,
        selector: PersonalFacetSelector,
        byte_budget: int = 1500,
        max_facts: int = 4,
    ) -> None:
        if not isinstance(retrieval, SemanticRetrievalService):
            raise TypeError("retrieval must be the canonical SemanticRetrievalService")
        if not callable(getattr(selector, "select", None)):
            raise TypeError("selector must implement select(question, catalog)")
        if type(byte_budget) is not int or byte_budget <= 0:
            raise ValueError("byte_budget must be positive")
        if type(max_facts) is not int or not 1 <= max_facts <= 8:
            raise ValueError("max_facts must be between 1 and 8")
        self._retrieval = retrieval
        self._selector = selector
        self._byte_budget = byte_budget
        self._max_facts = max_facts

    def _empty(
        self, question: str, disposition: ShadowDisposition
    ) -> ShadowPersonalPacket:
        return ShadowPersonalPacket(
            question_sha256=hashlib.sha256(question.encode("utf-8")).hexdigest(),
            disposition=disposition,
            facts=(),
            dropped_count=0,
            byte_budget=self._byte_budget,
        )

    async def select_context(
        self,
        question: str,
        *,
        authenticated_owner: bool,
    ) -> ShadowPersonalPacket:
        if not isinstance(question, str):
            raise TypeError("question must be text")
        if type(authenticated_owner) is not bool:
            raise TypeError("authenticated_owner must be bool")
        if not question.strip() or not authenticated_owner:
            return self._empty(question, ShadowDisposition.DENIED)
        try:
            catalog = await self._retrieval.eligible_facet_catalog(
                eligibility=_SHADOW_ELIGIBILITY
            )
            # A future selector may be a local/model worker, but it sees only
            # already eligible facet NAMES, never full memory values.
            safe_facets = MemoryFacetCatalog(
                tuple(
                    facet
                    for facet in catalog.facets
                    if facet.subject_scope == "personal" and facet.subject == "owner"
                )
            )
            proposed = await self._selector.select(question, safe_facets)
            if not isinstance(proposed, tuple) or not all(
                isinstance(facet, MemoryFacetKey) for facet in proposed
            ):
                return self._empty(question, ShadowDisposition.UNAVAILABLE)
            # A faulty/untrusted selector cannot introduce any new facet.
            if any(not safe_facets.contains(facet) for facet in proposed):
                return self._empty(question, ShadowDisposition.UNAVAILABLE)
            selected = []
            dropped = 0
            seen = set()
            used_bytes = 0
            for facet in proposed:
                if facet in seen:
                    continue
                seen.add(facet)
                if len(selected) >= self._max_facts:
                    dropped += 1
                    continue
                assertions = await self._retrieval.retrieve_exact_current_facet(
                    facet, eligibility=_SHADOW_ELIGIBILITY
                )
                # Ambiguous current facts are not quietly arbitrated.
                if len(assertions) != 1:
                    dropped += len(assertions)
                    continue
                assertion = assertions[0]
                if (
                    assertion.subject_scope != "personal"
                    or assertion.subject != "owner"
                    or assertion.state is not AssertionState.ACTIVE
                    or assertion.valid_to is not None
                    or assertion.sensitivity is not Sensitivity.STANDARD
                    or (
                        assertion.freshness_class is FreshnessClass.TIME_SENSITIVE
                        and assertion.verification_state
                        is not VerificationState.VERIFIED
                    )
                ):
                    dropped += 1
                    continue
                # Avoid treating a freeform model-generated value as an
                # executable instruction. The actual text is local SHADOW only.
                value = assertion.normalized_text
                if not isinstance(value, str):
                    dropped += 1
                    continue
                units = len(value.encode("utf-8"))
                if not value or used_bytes + units > self._byte_budget:
                    dropped += 1
                    continue
                selected.append(
                    ShadowPersonalFact(
                        assertion_id=assertion.assertion_id,
                        predicate=assertion.predicate,
                        source_id=assertion.source_id,
                        compact_text=value,
                        sensitivity=assertion.sensitivity,
                        authority_checked=True,
                    )
                )
                used_bytes += units
            return ShadowPersonalPacket(
                question_sha256=hashlib.sha256(question.encode("utf-8")).hexdigest(),
                disposition=(
                    ShadowDisposition.SELECTED
                    if selected
                    else ShadowDisposition.NO_MATCH
                ),
                facts=tuple(selected),
                dropped_count=dropped,
                byte_budget=self._byte_budget,
            )
        except Exception:  # noqa: BLE001 - research shadow must fail closed
            # The isolated research coordinator has no authority to turn
            # retrieval errors into guessed memories or live responses.
            return self._empty(question, ShadowDisposition.UNAVAILABLE)
