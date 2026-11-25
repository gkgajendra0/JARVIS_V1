"""Deterministic source/span/category gates around fallible semantic proposals."""

from pydantic import ValidationError

from jarvis.personal_learning_scope import SCALAR_FACETS

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
from .learning_temporal import POSSIBILITY_CATEGORIES
from .learning_values import SLOT_NAMES, has_identifier
from .project_routing import is_project_control_command
from .topic_continuity_policy import SENSITIVE_DATA


def ground_plan_label(source, candidate):
    """A plan's label is only its display name. When the model composed one
    that the owner never said ("Goa trip" for "Maybe we'll do Goa this
    winter.") but the plan's value is the owner's own words, the value becomes
    the label instead of the whole plan being dropped. Plans only; every other
    category and every other gate is unchanged, and nothing unsaid is stored."""
    if getattr(candidate, "category", None) != "plan" or not candidate.value:
        return candidate
    turns = {t.turn_id: t.text for t in source.turns}
    fragments = []
    for span in candidate.evidence:
        text = turns.get(span.turn_id)
        if text is None or not 0 <= span.start < span.end <= len(text):
            return candidate
        fragments.append(text[span.start : span.end])
    if any(candidate.label in f for f in fragments) or not any(
        candidate.value in f for f in fragments
    ):
        return candidate
    return candidate.model_copy(update={"label": candidate.value})


class LearningPolicy:
    @staticmethod
    def source_allowed(source: AcceptedLearningSource) -> bool:
        try:
            reject_negated_memory_change(source.text)
            reject_prohibited_secret(predicate="", value=source.text)
        except (ExplicitMemoryAuthorizationError, MemorySecretRejectedError):
            return False
        if is_explicit_memory_control_text(source.text):
            return False
        # "Create a project called Nepal trip" / "Switch to Nepal trip" control
        # project memory; they are not statements about the owner's life
        # (production 2026-11-04: a create command was stored as a plan).
        return not is_project_control_command(source.text)

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
        episodic = c.category in {"activity", "event", "plan"}
        if c.intent == "none" or (
            not episodic and (c.intent == "transient" or c.importance == "transient")
        ):
            return LearningEligibility("transient", "not_durable")
        if c.certainty == "uncertain":
            # The proposal itself says the meaning is unclear: nothing is
            # saved as a guessed fact (the reply asks what the owner meant).
            return LearningEligibility("drop", "meaning_unclear")
        if c.certainty == "tentative" and c.category not in POSSIBILITY_CATEGORIES:
            # A possibility is kept only where the record carries its
            # certainty. A possession or a single-value preference has none:
            # "maybe I'll get a Kindle" must never read as owning one.
            return LearningEligibility("drop", "possibility_not_fact")
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
        for field in (
            "time_expression",
            "location",
            "reason",
            "details",
            "acquired_expression",
            "disposed_expression",
        ):
            text = getattr(c, field)
            if text is not None and not any(text in fragment for fragment in fragments):
                return LearningEligibility("drop", "unsupported_" + field)
        slot_texts = []
        if c.slots is not None:
            for name in SLOT_NAMES:
                slot = getattr(c.slots, name)
                if slot is not None:
                    slot_texts += [t for t in (slot.value, *slot.options) if t]
        for text in (*c.aliases, *slot_texts):
            # Aliases, plan details and alternatives must be the owner's own
            # words; the model cannot add an option that was never said.
            if not any(text in fragment for fragment in fragments):
                return LearningEligibility("drop", "unsupported_detail")
        if c.category != "plan" and (c.plan_status is not None or c.slots is not None):
            return LearningEligibility("drop", "plan_fields_on_non_plan")
        if all(_interrogative(turns[span.turn_id], span.end) for span in c.evidence):
            # A question is not a disclosure, in any category ("Kaza or
            # Manali, which is better?", "Should I buy a Kindle?"). Only the
            # sentences a proposal cites count: an assertion in the same turn
            # as a question keeps its own evidence and is judged on it.
            return LearningEligibility("drop", "question_not_disclosure")
        if any(SENSITIVE_DATA.search(fragment) for fragment in fragments):
            # Credentials, identity documents, financial and medical data are
            # outside automatic admission (the same classes already excluded
            # from topic and project history). Judged on the cited words, so
            # a separate standard fact in the same turn is unaffected.
            return LearningEligibility("drop", "sensitive_content")
        if has_identifier(c.label) or has_identifier(c.value):
            return LearningEligibility("drop", "identifier_not_allowed")
        try:
            reject_prohibited_secret(predicate=c.label, value=c.value)
            for text in (
                c.time_expression,
                c.location,
                c.reason,
                c.details,
                c.acquired_expression,
                c.disposed_expression,
                *c.aliases,
                *slot_texts,
            ):
                if text:
                    reject_prohibited_secret(predicate="", value=text)
        except MemorySecretRejectedError:
            return LearningEligibility("drop", "secret")
        return LearningEligibility("eligible")


def _interrogative(text: str, end: int) -> bool:
    """Whether the sentence containing a cited span ends as a question."""
    for char in text[end:]:
        if char in ".!\n":
            return False
        if char == "?":
            return True
    stripped = text[:end].rstrip()
    return stripped.endswith("?")
