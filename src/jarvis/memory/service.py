"""Sole public facade for explicit canonical semantic-memory operations."""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from number_parser import parse as parse_number_words

from .assertions import SemanticAssertionDraft, SemanticAssertionRecord
from .lifecycle import MemoryCurrentFacetExistsError, MemoryLifecycleService
from .provenance import MemorySource
from .query import CanonicalMemoryReader
from .types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)

_PERSONAL_SCOPE = "personal"
_OWNER_SUBJECT = "owner"


class MemoryServiceError(RuntimeError):
    pass


class MemoryAlreadyExistsError(MemoryServiceError):
    pass


class MemoryNotFoundError(MemoryServiceError):
    pass


class MemoryAmbiguousError(MemoryServiceError):
    pass


class MemoryStaleTargetError(MemoryServiceError):
    pass


def normalize_memory_surface(value: str) -> str:
    """Normalize user-facing memory text without introducing fuzzy semantics.

    Spoken number words are folded to digits before canonical key comparison so
    equivalent ASR/model forms such as ``phase four`` and ``phase 4`` resolve to
    the same deterministic key. English normalization always runs; Hindi number
    normalization is applied only when Devanagari is present.
    """

    if not isinstance(value, str):
        raise TypeError("memory surface must be a string")
    normalized = unicodedata.normalize("NFKC", value.strip())
    normalized = parse_number_words(normalized, language="en")
    if any("\u0900" <= character <= "\u097f" for character in normalized):
        normalized = parse_number_words(normalized, language="hi")
    return normalized.casefold()


def canonical_memory_predicate(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("predicate must be a string")
    normalized_input = normalize_memory_surface(value)
    characters: list[str] = []
    previous_was_separator = False
    for character in normalized_input:
        category_group = unicodedata.category(character)[0]
        if character == "_" or category_group in {"L", "M", "N"}:
            characters.append(character)
            previous_was_separator = False
            continue
        if characters and not previous_was_separator:
            characters.append("_")
            previous_was_separator = True
    normalized = "".join(characters).strip("_")
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    if not normalized:
        raise ValueError("predicate must contain letters or digits")
    if len(normalized) > 96:
        raise ValueError("predicate must not exceed 96 characters")
    return normalized


def _structured_correction(current, predicate, text):
    """The corrected value of a registered personal-learning text fact, or
    None for a plain record. Owned items are identified by their label, so an
    explicit text correction never rewrites one (the learning path owns item
    changes)."""
    from jarvis.personal_learning_scope import POLICY_VERSION

    value = current.value
    if (
        not isinstance(value, dict)
        or value.get("schema") != POLICY_VERSION
        or value.get("category") in {None, "owned_item"}
        or not predicate.startswith(f"{value.get('category')}_")
    ):
        return None
    return {**value, "value": text}


def _text_value(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("memory value must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError("memory value must not be empty")
    return normalized


def _normalized_text(predicate: str, value: str) -> str:
    human_key = predicate.replace("_", " ")
    return f"{human_key}: {value}"


@dataclass(frozen=True, slots=True)
class ExplicitMemoryResult:
    predicate: str
    record: SemanticAssertionRecord


class MemoryService:
    """Own explicit high-level memory semantics above lifecycle/query primitives."""

    def __init__(
        self,
        lifecycle: MemoryLifecycleService,
        reader: CanonicalMemoryReader,
    ) -> None:
        self._lifecycle = lifecycle
        self._reader = reader
        self._learning_authority = None
        self._learning_invalidator = None
        self._plan_epoch_refresher = None

    def bind_learning_turn_claim(self, callback):
        """Automatic learning's hook for a turn an explicit request claimed."""
        self._learning_turn_claim = callback

    def claim_explicit_request(self, *, session_id: str, turn_id: str) -> None:
        """An explicit memory request (remember / correct / forget) is about
        to act on this owner turn. From now on only that request may write
        from it: automatic learning drops its sources for the turn and the
        learning authority refuses any write citing or quoting it, whether
        the explicit request is later granted, denied, cancelled or fails."""
        if self._learning_authority is not None:
            self._learning_authority.claim_explicit_request(turn_id)
        callback = getattr(self, "_learning_turn_claim", None)
        if callback is not None:
            callback(turn_id)

    def bind_learning_invalidator(self, callback):
        if self._learning_invalidator is not None or not callable(callback):
            raise RuntimeError("learning invalidator already bound or invalid")
        self._learning_invalidator = callback

    def _invalidate_learning(self):
        if self._learning_invalidator:
            self._learning_invalidator()

    def bind_plan_epoch_refresher(self, callback):
        if self._plan_epoch_refresher is not None or not callable(callback):
            raise RuntimeError("plan epoch refresher already bound or invalid")
        self._plan_epoch_refresher = callback

    async def _refresh_plan_epoch(self):
        if self._plan_epoch_refresher is not None:
            await self._plan_epoch_refresher()

    @property
    def canonical_reader(self):
        return self._reader

    def bind_learning_authority(self, authority):
        from jarvis.authority.personal_learning import PersonalLearningAuthority

        if self._learning_authority is not None or not isinstance(
            authority, PersonalLearningAuthority
        ):
            raise PermissionError("learning authority already bound or invalid")
        self._learning_authority = authority

    async def admit_learning(self, plan, permit):
        from jarvis.personal_learning_scope import CATEGORIES

        from .learning_reconciliation import LearningPlan

        authority = self._learning_authority
        if authority is None or not isinstance(plan, LearningPlan):
            raise PermissionError("learning admission unavailable")
        if (
            authority.child_binding(permit) != plan.binding()
            or authority.source_for(permit) is not plan.source
        ):
            raise PermissionError("learning plan/source binding mismatch")
        # Revalidate every code-owned policy field at the sole write boundary.
        seen = set()
        for m in plan.mutations:
            if (
                m.ordinal in seen
                or m.action not in {"create", "correct", "change", "retract", "refine"}
                or (m.action == "create") != (m.expected_assertion_id is None)
                or (m.action != "change" and m.effective_at is not None)
                or (
                    m.effective_at is not None
                    and (
                        not isinstance(m.effective_at, datetime)
                        or m.effective_at.tzinfo is None
                    )
                )
                or m.category not in CATEGORIES
                or m.source.source_class is not MemorySourceClass.OWNER_DIRECT
                or m.source.authority_class is not AuthorityClass.OWNER_DIRECT
                or m.source.sensitivity is not Sensitivity.STANDARD
                or not _quote_admissible(m.source, plan.source)
                or m.source.canonical_ref
                != f"conversation:{plan.source.session_id}:turn:{plan.source.turn_id}"
            ):
                raise PermissionError("learning policy mismatch")
            seen.add(m.ordinal)
            if m.draft is not None:
                from .types import VerificationState

                d = m.draft
                if (
                    d.subject_scope != "personal"
                    or d.subject != "owner"
                    or d.predicate != m.predicate
                    or d.sensitivity is not Sensitivity.STANDARD
                    or d.verification_state is not VerificationState.UNVERIFIED
                    or d.freshness_class is not FreshnessClass.CHANGEABLE
                ):
                    raise PermissionError("learning draft scope mismatch")
        for outcome in plan.outcomes:
            if (
                outcome.category not in CATEGORIES
                or not outcome.reason
                or len(outcome.reason) > 64
                or not outcome.reason.replace("_", "").isalnum()
                or not outcome.reason.islower()
            ):
                raise PermissionError("learning outcome mismatch")
        return await self._lifecycle.apply_learning_batch(plan, permit, authority)

    async def learning_suppression(self):
        return await self._reader.learning_suppression()

    async def suppress_learning_categories(self, source, categories, permit):
        from .learning_controls import category_veto, suppression_binding

        authority = self._learning_authority
        if authority is None or tuple(categories) != category_veto(source.text):
            raise PermissionError("canonical category veto required")
        binding = suppression_binding(source, categories)
        if (
            authority.child_binding(permit) != binding
            or authority.source_for(permit) is not source
        ):
            raise PermissionError("suppression source binding mismatch")
        await self._lifecycle.suppress_learning_categories(
            categories, source, permit, authority, binding
        )
        if "plan" in categories:
            await self._refresh_plan_epoch()

    async def reenable_learning_category(self, category, explicit_source, commit_guard):
        from jarvis.personal_learning_scope import SUPPRESSION_KEYS

        if (
            self._learning_authority is None
            or category not in SUPPRESSION_KEYS
            or not callable(commit_guard)
        ):
            raise PermissionError("exact explicit category approval required")
        try:
            self._validate_owner_explicit_source(explicit_source, Sensitivity.STANDARD)
        except MemoryServiceError as exc:
            raise PermissionError("explicit owner source required") from exc
        await self._lifecycle.reenable_learning_category(
            category, explicit_source, commit_guard, self._learning_authority
        )
        if category == "plan":
            await self._refresh_plan_epoch()
        self._invalidate_learning()

    async def remember_text(
        self,
        *,
        predicate: str,
        value: str,
        source: MemorySource,
        sensitivity: Sensitivity = Sensitivity.STANDARD,
        freshness_class: FreshnessClass = FreshnessClass.CHANGEABLE,
        commit_guard: Callable[[], None] | None = None,
    ) -> ExplicitMemoryResult:
        key = canonical_memory_predicate(predicate)
        text = _text_value(value)
        self._validate_write_policy(source, sensitivity, freshness_class)
        try:
            record = await self._lifecycle.create(
                self._draft(
                    predicate=key,
                    value=text,
                    sensitivity=sensitivity,
                    freshness_class=freshness_class,
                ),
                source,
                reason_code="explicit_owner_remember",
                require_absent_current=True,
                commit_guard=commit_guard,
            )
        except MemoryCurrentFacetExistsError as exc:
            raise MemoryAlreadyExistsError(
                f"current memory already exists for predicate {key!r}; use correction"
            ) from exc
        self._invalidate_learning()
        return ExplicitMemoryResult(predicate=key, record=record)

    async def current_owned_item_labels(self) -> set[str]:
        return {
            str(r.value.get("label", "")).casefold()
            for r in await self._reader.learning_current()
            if isinstance(r.value, dict) and r.value.get("category") == "owned_item"
        }

    async def remember_owned_items(
        self,
        *,
        kind: str,
        items: tuple[str, ...],
        source: MemorySource,
        commit_guard: Callable[[], None] | None = None,
    ) -> tuple[SemanticAssertionRecord, ...]:
        """A newly supplied explicit list ("my vehicles are X and Y") stored as
        one owned-item fact per item, in one transaction under the single
        approval that showed every item. Items already current under the same
        label are not duplicated. Existing combined records are untouched."""
        from uuid import uuid4

        from jarvis.personal_learning_scope import POLICY_VERSION

        if kind not in {"vehicle", "device", "other"} or not 1 <= len(items) <= 8:
            raise MemoryServiceError("owned item list must have 1 to 8 items")
        if len({i.casefold() for i in items}) != len(items):
            raise MemoryServiceError("owned item list repeats an item")
        self._validate_write_policy(
            source, Sensitivity.STANDARD, FreshnessClass.CHANGEABLE
        )
        current = await self.current_owned_item_labels()
        if any(i.casefold() in current for i in items):
            # The approval showed exactly these items; never commit a
            # different set than the owner reviewed.
            raise MemoryServiceError("reviewed items changed before commit")
        drafts = []
        for item in items:
            text = _text_value(item)
            drafts.append(
                SemanticAssertionDraft(
                    "personal",
                    "owner",
                    f"owned_item_{uuid4().hex}",
                    ValueType.JSON,
                    {
                        "schema": POLICY_VERSION,
                        "category": "owned_item",
                        "kind": kind,
                        "label": text,
                        "value": text,
                        "state": "owned",
                    },
                    f"owned_item.{kind}: {text}; value={text}; state=owned",
                    FreshnessClass.CHANGEABLE,
                    Sensitivity.STANDARD,
                )
            )
        # One source per item: the same owner turn and times, distinct IDs.
        sources = (source,) + tuple(
            replace(source, source_id=str(uuid4())) for _ in drafts[1:]
        )
        records = await self._lifecycle.create_many(
            tuple(drafts),
            sources,
            reason_code="explicit_owner_remember",
            commit_guard=commit_guard,
        )
        self._invalidate_learning()
        return records

    async def remember_personal_fact(
        self,
        *,
        label: str,
        value: str,
        source: MemorySource,
        commit_guard: Callable[[], None] | None = None,
    ) -> ExplicitMemoryResult:
        """An explicit standard owner fact ("my home city is Jaipur") in the
        registered personal-learning shape, so the owner-memory reads of a
        learning session (record_scope: category personal_fact) can find it,
        and correction, forgetting and the personal_fact suppression apply to
        it like any learned personal fact. Provenance stays owner-explicit.
        Live voice 27 Nov: a plain-text "home_city" record was saved but
        invisible to every later read."""
        from uuid import uuid4

        from jarvis.personal_learning_scope import POLICY_VERSION

        label = _text_value(label)
        text = _text_value(value)
        self._validate_write_policy(
            source, Sensitivity.STANDARD, FreshnessClass.CHANGEABLE
        )
        if any(
            isinstance(r.value, dict)
            and r.value.get("category") == "personal_fact"
            and str(r.value.get("label", "")).casefold() == label.casefold()
            for r in await self._reader.learning_current()
        ):
            raise MemoryAlreadyExistsError(
                f"current memory already exists for {label!r}; use correction"
            )
        draft = SemanticAssertionDraft(
            "personal",
            "owner",
            f"personal_fact_{uuid4().hex}",
            ValueType.JSON,
            {
                "schema": POLICY_VERSION,
                "category": "personal_fact",
                "kind": "other",
                "label": label,
                "value": text,
                "state": "active",
            },
            f"personal_fact: {label}; value={text}; state=active",
            FreshnessClass.CHANGEABLE,
            Sensitivity.STANDARD,
        )
        record = await self._lifecycle.create(
            draft,
            source,
            reason_code="explicit_owner_remember",
            require_absent_current=True,
            commit_guard=commit_guard,
        )
        self._invalidate_learning()
        return ExplicitMemoryResult(predicate=draft.predicate, record=record)

    async def correct_text(
        self,
        *,
        predicate: str,
        value: str,
        source: MemorySource,
        sensitivity: Sensitivity | None = None,
        freshness_class: FreshnessClass | None = None,
        commit_guard: Callable[[], None] | None = None,
        expected_assertion_id: str | None = None,
    ) -> ExplicitMemoryResult:
        key = canonical_memory_predicate(predicate)
        text = _text_value(value)
        current = await self._require_one_current(key)
        if (
            expected_assertion_id is not None
            and current.assertion_id != expected_assertion_id
        ):
            raise MemoryStaleTargetError(
                "The selected memory changed; resolve it again before correction"
            )
        resolved_sensitivity = sensitivity or current.sensitivity
        resolved_freshness = freshness_class or current.freshness_class
        self._validate_write_policy(source, resolved_sensitivity, resolved_freshness)
        draft = self._draft(
            predicate=key,
            value=text,
            sensitivity=resolved_sensitivity,
            freshness_class=resolved_freshness,
        )
        structured = _structured_correction(current, key, text)
        if structured is not None:
            # A registered personal-learning record keeps its shape (and so
            # its read scope and suppression category); only its value changes.
            draft = replace(
                draft,
                value_type=ValueType.JSON,
                value=structured,
                normalized_text=(
                    f"{structured['category']}: {structured.get('label', '')}; "
                    f"value={text}; state={structured.get('state', '')}"
                ),
            )
        record = await self._lifecycle.correct(
            current.assertion_id,
            draft,
            source,
            reason_code="explicit_owner_correction",
            commit_guard=commit_guard,
        )
        self._invalidate_learning()
        # An explicit legacy plan correction may have advanced the plan epoch
        # and erased checkpoints in the same canonical transaction.
        await self._refresh_plan_epoch()
        return ExplicitMemoryResult(predicate=key, record=record)

    async def forget_exact(
        self,
        *,
        predicate: str,
        source: MemorySource,
        commit_guard: Callable[[], None] | None = None,
        expected_assertion_id: str | None = None,
    ) -> str:
        key = canonical_memory_predicate(predicate)
        current = await self._require_one_current(key)
        if (
            expected_assertion_id is not None
            and current.assertion_id != expected_assertion_id
        ):
            raise MemoryStaleTargetError(
                "The selected memory changed; resolve it again before deletion"
            )
        self._validate_owner_explicit_source(source, current.sensitivity)
        forgotten = await self._lifecycle.forget(
            current.assertion_id,
            source,
            reason_code="explicit_owner_request",
            commit_guard=commit_guard,
            require_current=True,
            purge_lineage=True,
        )
        if not forgotten:
            raise MemoryNotFoundError(f"memory disappeared before forget for {key!r}")
        self._invalidate_learning()
        # Legacy exact forgetting can now suppress the plan category inside its
        # SQLCipher transaction. Refresh the cached epoch after any exact delete;
        # unchanged generations are harmless and there is no voice-path read.
        await self._refresh_plan_epoch()
        after = await self._reader.find_current_exact(
            subject_scope=_PERSONAL_SCOPE,
            subject=_OWNER_SUBJECT,
            predicate=key,
        )
        if after:
            raise MemoryServiceError(
                f"forget verification still found current memory for predicate {key!r}"
            )
        return key

    async def inspect_exact(self, *, predicate: str) -> ExplicitMemoryResult:
        key = canonical_memory_predicate(predicate)
        record = await self._require_one_current(key)
        return ExplicitMemoryResult(predicate=key, record=record)

    async def _require_one_current(self, predicate: str) -> SemanticAssertionRecord:
        matches = await self._reader.find_current_exact(
            subject_scope=_PERSONAL_SCOPE,
            subject=_OWNER_SUBJECT,
            predicate=predicate,
        )
        if not matches:
            raise MemoryNotFoundError(f"no current memory for predicate {predicate!r}")
        if len(matches) != 1:
            raise MemoryAmbiguousError(
                f"multiple current memories exist for predicate {predicate!r}"
            )
        return matches[0]

    @staticmethod
    def _draft(
        *,
        predicate: str,
        value: str,
        sensitivity: Sensitivity,
        freshness_class: FreshnessClass,
    ) -> SemanticAssertionDraft:
        return SemanticAssertionDraft(
            subject_scope=_PERSONAL_SCOPE,
            subject=_OWNER_SUBJECT,
            predicate=predicate,
            value_type=ValueType.TEXT,
            value=value,
            normalized_text=_normalized_text(predicate, value),
            freshness_class=freshness_class,
            sensitivity=sensitivity,
        )

    @classmethod
    def _validate_write_policy(
        cls,
        source: MemorySource,
        sensitivity: Sensitivity,
        freshness_class: FreshnessClass,
    ) -> None:
        cls._validate_owner_explicit_source(source, sensitivity)
        if not isinstance(freshness_class, FreshnessClass):
            raise TypeError("freshness_class must be a FreshnessClass")

    @staticmethod
    def _validate_owner_explicit_source(
        source: MemorySource,
        sensitivity: Sensitivity,
    ) -> None:
        if not isinstance(source, MemorySource):
            raise TypeError("source must be a MemorySource")
        if source.source_class is not MemorySourceClass.OWNER_EXPLICIT:
            raise MemoryServiceError(
                "explicit memory mutation requires owner-explicit source provenance"
            )
        if source.authority_class is not AuthorityClass.OWNER_EXPLICIT:
            raise MemoryServiceError(
                "explicit memory mutation requires owner-explicit authority"
            )
        if not isinstance(sensitivity, Sensitivity):
            raise TypeError("sensitivity must be a Sensitivity")
        if sensitivity is Sensitivity.SECRET_PROHIBITED:
            raise ValueError("secret-prohibited content cannot be remembered")
        if source.sensitivity is not sensitivity:
            raise MemoryServiceError(
                "explicit memory source sensitivity must match the stored memory"
            )


def _quote_admissible(memory_source, accepted_source) -> bool:
    """None, or a minimum owner quote made only of the accepted USER turns'
    own words (docs/policy/personal-memory-evidence-retention.md)."""
    from .lifecycle import learning_quote_allowed

    text = memory_source.evidence_text
    if text is None:
        return True
    if not learning_quote_allowed(memory_source):
        return False
    turns = [t.text for t in accepted_source.turns]
    return all(
        piece and any(piece in turn for turn in turns) for piece in text.split(" … ")
    )
