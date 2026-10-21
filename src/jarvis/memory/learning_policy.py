"""Deterministic source/span/category gates around fallible semantic proposals."""

from pydantic import ValidationError

from .explicit import (
    ExplicitMemoryAuthorizationError,
    MemorySecretRejectedError,
    is_explicit_memory_control_text,
    reject_negated_memory_change,
    reject_prohibited_secret,
)
from .learning_contracts import (
    AcceptedLearningSource,
    LearningCandidate,
    LearningEligibility,
)

SCALAR_FACETS = {
    "food_preference": frozenset({"diet_preference"}),
    "response_preference": frozenset({"response_language", "response_style"}),
}


class LearningPolicy:
    @staticmethod
    def source_allowed(source: AcceptedLearningSource) -> bool:
        try:
            reject_negated_memory_change(source.text)
            reject_prohibited_secret(predicate="", value=source.text)
        except (ExplicitMemoryAuthorizationError, MemorySecretRejectedError):
            return False
        return not is_explicit_memory_control_text(source.text)

    def evaluate(self, source, candidate, suppressed_categories=frozenset()):
        try:
            # Revalidate even internal copies; an update cannot bypass schema.
            c = LearningCandidate.model_validate(candidate.model_dump())
        except (ValidationError, AttributeError):
            return LearningEligibility("drop", "invalid_proposal")
        if not self.source_allowed(source):
            return LearningEligibility("drop", "source_veto")
        if c.sensitivity != "standard" or c.qualification != "direct":
            return LearningEligibility("drop", "not_direct_standard")
        if c.intent in {"none", "transient"} or c.importance == "transient":
            return LearningEligibility("transient", "not_durable")
        if (
            c.category in suppressed_categories
            or c.suppression_key in suppressed_categories
        ):
            return LearningEligibility("drop", "suppressed")
        if (
            c.category in SCALAR_FACETS
            and c.scalar_facet not in SCALAR_FACETS[c.category]
        ):
            return LearningEligibility("drop", "invalid_scalar")
        turns = {t.turn_id: t.text for t in source.turns}
        fragments = []
        latest = False
        for span in c.evidence:
            text = turns.get(span.turn_id)
            if text is None or not 0 <= span.start < span.end <= len(text):
                return LearningEligibility("drop", "invalid_span")
            fragments.append(text[span.start : span.end])
            latest |= span.turn_id == source.turn_id
        if not latest or not any(c.value in text for text in fragments):
            return LearningEligibility("drop", "unsupported_value")
        if c.category not in SCALAR_FACETS and not any(
            c.label in text for text in fragments
        ):
            return LearningEligibility("drop", "unsupported_label")
        try:
            reject_prohibited_secret(predicate=c.label, value=c.value)
        except MemorySecretRejectedError:
            return LearningEligibility("drop", "secret")
        return LearningEligibility("eligible")


SUPPRESSION_KEYS = frozenset(
    {
        "owned_item.vehicle",
        "owned_item.device",
        "owned_item.other",
        "food_preference",
        "response_preference",
        "routine",
        "goal",
    }
)
