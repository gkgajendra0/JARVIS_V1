"""Provider-independent structured query planning for canonical JARVIS memory."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class MemoryQueryIntent(StrEnum):
    """Semantic shape proposed for one memory lookup request."""

    EXACT_FACT = "exact_fact"
    QUALIFIED_FACT = "qualified_fact"
    EXTERNAL_SOURCE_FACT = "external_source_fact"
    BROAD_RECALL = "broad_recall"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


class MemoryTemporalScope(StrEnum):
    """Requested valid-time scope; canonical policy remains authoritative."""

    UNSPECIFIED = "unspecified"
    CURRENT = "current"
    HISTORICAL = "historical"
    AS_OF = "as_of"


class MemoryQueryPlanDisposition(StrEnum):
    ALLOW_CURRENT_FACT = "allow_current_fact"
    ABSTAIN = "abstain"


class MemoryQueryProposal(BaseModel):
    """Replaceable interpreter proposal; never canonical truth or release authority."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    intent: MemoryQueryIntent
    subject_scope: str | None = Field(default=None, min_length=1, max_length=160)
    subject: str | None = Field(default=None, min_length=1, max_length=160)
    predicate: str | None = Field(default=None, min_length=1, max_length=160)
    subject_reference: str | None = Field(default=None, min_length=1, max_length=240)
    requested_relation: str | None = Field(default=None, min_length=1, max_length=240)
    temporal_scope: MemoryTemporalScope = MemoryTemporalScope.UNSPECIFIED
    as_of_text: str | None = Field(default=None, min_length=1, max_length=240)


@dataclass(frozen=True, slots=True, order=True)
class MemoryFacetKey:
    """Exact canonical semantic facet that may be selected for retrieval."""

    subject_scope: str
    subject: str
    predicate: str

    def __post_init__(self) -> None:
        for name in ("subject_scope", "subject", "predicate"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string")
            normalized = value.strip()
            if not normalized:
                raise ValueError(f"{name} must not be empty")
            object.__setattr__(self, name, normalized)


@dataclass(frozen=True, slots=True)
class MemoryFacetCatalog:
    """JARVIS-owned set of exact canonical facets exposed to an interpreter."""

    facets: tuple[MemoryFacetKey, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.facets, tuple):
            raise TypeError("facets must be a tuple")
        if not all(isinstance(facet, MemoryFacetKey) for facet in self.facets):
            raise TypeError("facets must contain only MemoryFacetKey values")
        if len(self.facets) != len(set(self.facets)):
            raise ValueError("facets must not contain duplicates")
        object.__setattr__(self, "facets", tuple(sorted(self.facets)))

    def contains(self, facet: MemoryFacetKey) -> bool:
        if not isinstance(facet, MemoryFacetKey):
            raise TypeError("facet must be a MemoryFacetKey")
        return facet in self.facets


@dataclass(frozen=True, slots=True)
class MemoryQueryPlan:
    """Deterministically validated current-fact plan safe to hand to retrieval."""

    facet: MemoryFacetKey
    temporal_scope: MemoryTemporalScope
    requested_relation: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.facet, MemoryFacetKey):
            raise TypeError("facet must be a MemoryFacetKey")
        if self.temporal_scope is not MemoryTemporalScope.CURRENT:
            raise ValueError(
                "validated current-fact plan must use current temporal scope"
            )
        if self.requested_relation is not None:
            if not isinstance(self.requested_relation, str):
                raise TypeError("requested_relation must be a string when provided")
            normalized = self.requested_relation.strip()
            if not normalized:
                raise ValueError("requested_relation must not be empty when provided")
            object.__setattr__(self, "requested_relation", normalized)


@dataclass(frozen=True, slots=True)
class MemoryQueryPolicyDecision:
    disposition: MemoryQueryPlanDisposition
    reason_code: str
    plan: MemoryQueryPlan | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, MemoryQueryPlanDisposition):
            raise TypeError("disposition must be a MemoryQueryPlanDisposition")
        if not isinstance(self.reason_code, str):
            raise TypeError("reason_code must be a string")
        reason = self.reason_code.strip()
        if not reason:
            raise ValueError("reason_code must not be empty")
        object.__setattr__(self, "reason_code", reason)
        if self.disposition is MemoryQueryPlanDisposition.ALLOW_CURRENT_FACT:
            if not isinstance(self.plan, MemoryQueryPlan):
                raise ValueError("allowed current-fact decision requires a plan")
        elif self.plan is not None:
            raise ValueError("abstain decision must not carry a retrieval plan")


class MemoryQueryInterpreter(Protocol):
    """Replaceable semantic proposal adapter; implementations have no authority."""

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    async def interpret(
        self,
        *,
        text: str,
        catalog: MemoryFacetCatalog,
    ) -> MemoryQueryProposal: ...


class MemoryQueryPolicy:
    """Fail-closed JARVIS authority for turning proposals into retrieval plans."""

    def evaluate(
        self,
        proposal: MemoryQueryProposal,
        catalog: MemoryFacetCatalog,
    ) -> MemoryQueryPolicyDecision:
        if not isinstance(proposal, MemoryQueryProposal):
            raise TypeError("proposal must be a MemoryQueryProposal")
        if not isinstance(catalog, MemoryFacetCatalog):
            raise TypeError("catalog must be a MemoryFacetCatalog")

        if proposal.intent is MemoryQueryIntent.AMBIGUOUS:
            return self._abstain("ambiguous_query")
        if proposal.intent is MemoryQueryIntent.UNSUPPORTED:
            return self._abstain("unsupported_query")
        if proposal.intent is MemoryQueryIntent.BROAD_RECALL:
            return self._abstain("broad_recall_not_auto_release_eligible")
        if proposal.intent is MemoryQueryIntent.QUALIFIED_FACT:
            return self._abstain("qualified_relation_requires_separate_path")
        if proposal.intent is MemoryQueryIntent.EXTERNAL_SOURCE_FACT:
            return self._abstain("external_source_query_not_canonical_memory")
        if proposal.intent is not MemoryQueryIntent.EXACT_FACT:
            return self._abstain("unknown_query_intent")

        if proposal.temporal_scope is MemoryTemporalScope.HISTORICAL:
            return self._abstain("historical_query_requires_separate_path")
        if proposal.temporal_scope is MemoryTemporalScope.AS_OF:
            return self._abstain("as_of_query_requires_separate_path")
        if proposal.as_of_text is not None:
            return self._abstain("as_of_hint_requires_separate_path")

        if (
            proposal.subject_scope is None
            or proposal.subject is None
            or proposal.predicate is None
        ):
            return self._abstain("incomplete_exact_fact_query")

        facet = MemoryFacetKey(
            subject_scope=proposal.subject_scope,
            subject=proposal.subject,
            predicate=proposal.predicate,
        )
        if not catalog.contains(facet):
            return self._abstain("unknown_canonical_facet")

        return MemoryQueryPolicyDecision(
            disposition=MemoryQueryPlanDisposition.ALLOW_CURRENT_FACT,
            reason_code="validated_current_exact_fact",
            plan=MemoryQueryPlan(
                facet=facet,
                temporal_scope=MemoryTemporalScope.CURRENT,
                requested_relation=proposal.requested_relation,
            ),
        )

    @staticmethod
    def _abstain(reason_code: str) -> MemoryQueryPolicyDecision:
        return MemoryQueryPolicyDecision(
            disposition=MemoryQueryPlanDisposition.ABSTAIN,
            reason_code=reason_code,
        )
