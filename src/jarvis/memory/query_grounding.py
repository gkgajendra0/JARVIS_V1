"""Deterministic grounding for untrusted memory-query interpreter proposals."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from .query_plan import (
    MemoryFacetCatalog,
    MemoryFacetKey,
    MemoryQueryIntent,
    MemoryQueryProposal,
)


class MemoryQueryGroundingDisposition(StrEnum):
    ALLOW = "allow"
    ABSTAIN = "abstain"


@dataclass(frozen=True, slots=True)
class MemoryQueryGroundingDecision:
    disposition: MemoryQueryGroundingDisposition
    reason_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, MemoryQueryGroundingDisposition):
            raise TypeError("disposition must be a MemoryQueryGroundingDisposition")
        if not isinstance(self.reason_code, str):
            raise TypeError("reason_code must be a string")
        reason = self.reason_code.strip()
        if not reason:
            raise ValueError("reason_code must not be empty")
        object.__setattr__(self, "reason_code", reason)


def semantic_surface_tokens(value: str) -> tuple[str, ...]:
    """Normalize one surface to Unicode letter/mark/number tokens for grounding."""

    if not isinstance(value, str):
        raise TypeError("surface must be a string")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    characters = [
        character if unicodedata.category(character)[0] in {"L", "M", "N"} else " "
        for character in normalized
    ]
    return tuple("".join(characters).split())


def semantic_surface_key(value: str) -> str:
    return "_".join(semantic_surface_tokens(value))


def surface_phrase_is_grounded(text: str, reference: str) -> bool:
    """Require a reference to occur as a contiguous normalized token phrase."""

    text_tokens = semantic_surface_tokens(text)
    reference_tokens = semantic_surface_tokens(reference)
    if not reference_tokens or len(reference_tokens) > len(text_tokens):
        return False
    width = len(reference_tokens)
    return any(
        text_tokens[index : index + width] == reference_tokens
        for index in range(len(text_tokens) - width + 1)
    )


class MemoryQueryGroundingPolicy:
    """Fail closed when exact-fact tool arguments are not grounded in user text."""

    def evaluate(
        self,
        *,
        text: str,
        proposal: MemoryQueryProposal,
        catalog: MemoryFacetCatalog,
    ) -> MemoryQueryGroundingDecision:
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        if not text.strip():
            raise ValueError("text must not be empty")
        if not isinstance(proposal, MemoryQueryProposal):
            raise TypeError("proposal must be a MemoryQueryProposal")
        if not isinstance(catalog, MemoryFacetCatalog):
            raise TypeError("catalog must be a MemoryFacetCatalog")

        if proposal.intent is not MemoryQueryIntent.EXACT_FACT:
            return self._allow("non_exact_query_grounding_deferred_to_query_policy")

        if (
            proposal.subject_scope is None
            or proposal.subject is None
            or proposal.predicate is None
        ):
            return self._allow("incomplete_query_deferred_to_query_policy")

        if proposal.subject_reference is None:
            return self._abstain("subject_reference_required")
        if proposal.requested_relation is None:
            return self._abstain("relation_reference_required")
        if not surface_phrase_is_grounded(text, proposal.subject_reference):
            return self._abstain("subject_reference_not_grounded")
        if not surface_phrase_is_grounded(text, proposal.requested_relation):
            return self._abstain("relation_reference_not_grounded")

        selected = MemoryFacetKey(
            proposal.subject_scope,
            proposal.subject,
            proposal.predicate,
        )
        if not catalog.contains(selected):
            return self._allow("unknown_facet_deferred_to_query_policy")

        subject_key = semantic_surface_key(proposal.subject_reference)
        subjects_by_key = self._catalog_values_by_key(
            catalog,
            attribute="subject",
        )
        if subject_key in subjects_by_key and proposal.subject not in subjects_by_key[
            subject_key
        ]:
            return self._abstain("subject_reference_conflicts_with_selected_subject")

        relation_key = semantic_surface_key(proposal.requested_relation)
        predicates_by_key = self._catalog_values_by_key(
            catalog,
            attribute="predicate",
        )
        if (
            relation_key in predicates_by_key
            and proposal.predicate not in predicates_by_key[relation_key]
        ):
            return self._abstain(
                "relation_reference_conflicts_with_selected_predicate"
            )

        return self._allow("grounded_exact_query_references")

    @staticmethod
    def _catalog_values_by_key(
        catalog: MemoryFacetCatalog,
        *,
        attribute: str,
    ) -> dict[str, frozenset[str]]:
        values: dict[str, set[str]] = {}
        for facet in catalog.facets:
            raw_value = getattr(facet, attribute)
            key = semantic_surface_key(raw_value)
            values.setdefault(key, set()).add(raw_value)
        return {key: frozenset(raw_values) for key, raw_values in values.items()}

    @staticmethod
    def _allow(reason_code: str) -> MemoryQueryGroundingDecision:
        return MemoryQueryGroundingDecision(
            MemoryQueryGroundingDisposition.ALLOW,
            reason_code,
        )

    @staticmethod
    def _abstain(reason_code: str) -> MemoryQueryGroundingDecision:
        return MemoryQueryGroundingDecision(
            MemoryQueryGroundingDisposition.ABSTAIN,
            reason_code,
        )
