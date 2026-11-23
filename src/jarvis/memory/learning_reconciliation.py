"""Closed canonical identity resolution and immutable, version-bound write plans."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import uuid4

from jarvis.authority.personal_learning import POLICY_VERSION, LearningActionBinding
from jarvis.authority.proposal import canonical_json
from jarvis.personal_learning_scope import CATEGORIES

from .assertions import SemanticAssertionDraft
from .learning_catalog_page import PAGE_AMBIGUOUS, bounded_entries, unique_reference
from .learning_contracts import (
    AcceptedLearningSource,
    LearningBatch,
    LearningCatalog,
    LearningCatalogEntry,
    LearningResolutionBatch,
)
from .learning_diagnostics import log_learning
from .learning_policy import SCALAR_FACETS, LearningPolicy
from .learning_temporal import HISTORY_CATEGORIES, occurrence_matches, temporal_context
from .learning_values import (
    DISPOSED_STATES,
    PLAN_STATE,
    decided_options,
    decides_stated_options,
    has_identifier,
    item_time,
    minimal_quote,
    normalized_slots,
    option_keys,
    refine_merge,
)
from .personal_time import day_boundary
from .provenance import MemorySource
from .service import normalize_memory_surface
from .types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)


@dataclass(frozen=True)
class PlannedLearningMutation:
    ordinal: int
    action: str
    category_key: str
    category: str
    predicate: str
    expected_assertion_id: str | None
    draft: SemanticAssertionDraft | None
    source: MemorySource
    # A real-world change's effective time, only when the owner stated it at
    # day precision; None means unknown (never the time Jarvis was told).
    effective_at: datetime | None = None


@dataclass(frozen=True)
class LearningOutcome:
    """A candidate that passed policy but was not saved, and why. Content-free:
    candidate ordinal, category key and reason code only."""

    ordinal: int
    category_key: str
    category: str
    reason: str


@dataclass(frozen=True)
class LearningPlan:
    source: AcceptedLearningSource
    mutations: tuple[PlannedLearningMutation, ...]
    suppression_epochs: tuple[tuple[str, int], ...] = ()
    outcomes: tuple[LearningOutcome, ...] = ()

    @property
    def digest(self):
        rows = []
        for m in self.mutations:
            draft = m.draft
            rows.append(
                {
                    "material": json.loads(
                        json.dumps(
                            asdict(m),
                            default=lambda v: (
                                v.isoformat() if hasattr(v, "isoformat") else v.value
                            ),
                        )
                    ),
                    "ordinal": m.ordinal,
                    "action": m.action,
                    "category": m.category_key,
                    "predicate": m.predicate,
                    "expected_id": m.expected_assertion_id,
                    "value": draft.value if draft else None,
                    "normalized_text": draft.normalized_text if draft else None,
                    "type": draft.value_type.value if draft else None,
                    "source_id": m.source.source_id,
                    "source_ref": m.source.canonical_ref,
                    "source_digest": m.source.evidence_hash,
                    "observed_at": m.source.observed_at.isoformat(),
                }
            )
        return hashlib.sha256(
            canonical_json(
                {
                    "receipt": self.source.receipt_id,
                    "turn": self.source.turn_id,
                    "epochs": self.suppression_epochs,
                    "mutations": rows,
                    "outcomes": [asdict(o) for o in self.outcomes],
                }
            ).encode()
        ).hexdigest()

    def mutation_digest(self, mutation):
        material = json.loads(
            json.dumps(
                asdict(mutation),
                default=lambda v: v.isoformat() if hasattr(v, "isoformat") else v.value,
            )
        )
        return hashlib.sha256(
            canonical_json(
                {
                    "turn": self.source.turn_id,
                    "policy": POLICY_VERSION,
                    "mutation": material,
                }
            ).encode()
        ).hexdigest()

    def binding(self):
        return LearningActionBinding(
            "admit",
            self.source.receipt_id,
            self.digest,
            tuple(
                sorted(
                    {m.category for m in self.mutations}
                    | {o.category for o in self.outcomes}
                )
            ),
            tuple((m.predicate, m.expected_assertion_id) for m in self.mutations),
            self.suppression_epochs,
        )


def _value(entry):
    if entry.category != "legacy":
        try:
            parsed = json.loads(entry.value)
            if isinstance(parsed, dict):
                return parsed.get("value", entry.value)
        except (ValueError, TypeError):
            pass
    return entry.value


def _label(entry):
    try:
        value = json.loads(entry.value)
    except (ValueError, TypeError):
        return None
    return (
        normalize_memory_surface(str(value.get("label", "")))
        if isinstance(value, dict)
        else None
    )


class LearningReconciler:
    def __init__(self, reader, authority, *, diagnostics=False):
        self.diagnostics = diagnostics
        self.reader = reader
        self.authority = authority

    async def catalog(self, source, batch, grant):
        categories = tuple(sorted(CATEGORIES))
        permit = self.authority.issue_child(
            grant,
            LearningActionBinding(
                "read",
                source.receipt_id,
                source.digest,
                categories,
            ),
        )
        self.authority.consume_read(permit)
        records = await self.reader.learning_current_scoped()
        entries = []
        for record, scope in records:
            category, _, kind = scope.partition(".")
            kind = kind or "other"
            if category not in SCALAR_FACETS and not isinstance(record.value, dict):
                category = "legacy"  # Never split/mutate a plural legacy entity.
            text_value = (
                json.dumps(record.value, ensure_ascii=False)
                if isinstance(record.value, dict)
                else str(record.value)
            )
            entries.append(
                LearningCatalogEntry(
                    assertion_id=record.assertion_id,
                    predicate=record.predicate,
                    category=category,
                    kind=kind,
                    text=record.normalized_text,
                    value=text_value,
                )
            )
        self.authority.validate_read(permit)
        # Only the proposed categories, bounded per proposal (PR C); a proposal
        # whose identity cannot be resolved from a bounded page is skipped and
        # recorded instead of failing the whole turn.
        supplied, ambiguous = bounded_entries(entries, batch.candidates, SCALAR_FACETS)
        return LearningCatalog(entries=supplied, page_ambiguous=list(ambiguous))

    def plan(
        self,
        source: AcceptedLearningSource,
        batch: LearningBatch,
        catalog: LearningCatalog,
        resolutions: LearningResolutionBatch,
    ) -> LearningPlan:
        by_id = {entry.assertion_id: entry for entry in catalog.entries}
        choices = {}
        duplicate_indices = set()
        for choice in resolutions.resolutions:
            if choice.candidate_index in choices:
                duplicate_indices.add(choice.candidate_index)
            choices[choice.candidate_index] = choice
        mutations = []
        outcomes = []
        used = set()
        trip_choices = _trip_choices(batch)
        for index, candidate in enumerate(batch.candidates):

            def skip(reason, *, index=index, candidate=candidate, record=True):
                log_learning(
                    self.diagnostics,
                    source,
                    "reconciliation",
                    "skipped",
                    candidate_index=index,
                    reason=reason,
                    fact=candidate.model_dump(mode="json"),
                )
                if record and reason not in {"already_stored", "duplicate"}:
                    # Never silently lost, never claimed saved: a content-free
                    # record of an eligible candidate that was not saved.
                    outcomes.append(
                        LearningOutcome(
                            index,
                            candidate.suppression_key,
                            candidate.category,
                            reason,
                        )
                    )

            if LearningPolicy().evaluate(source, candidate).status != "eligible":
                skip("policy_rejected", record=False)
                continue
            if index in catalog.page_ambiguous:
                skip(PAGE_AMBIGUOUS)
                continue
            if (
                candidate.category == "owned_item"
                and normalize_memory_surface(candidate.label) in trip_choices
                and (
                    candidate.intent in {"change", "correction", "retraction"}
                    or candidate.state in DISPOSED_STATES
                )
            ):
                # Taking a vehicle on a trip is a plan detail, never a change
                # to what the owner owns.
                skip("trip_choice_not_ownership")
                continue
            choice = choices.get(index)
            if (
                choice is None
                or index in duplicate_indices
                or choice.decision == "uncertain"
            ):
                skip(
                    "missing_resolution"
                    if choice is None
                    else "conflicting_resolutions"
                    if index in duplicate_indices
                    else "uncertain"
                )
                continue
            entry = by_id.get(choice.target_id)
            same = [
                e
                for e in catalog.entries
                if e.category == candidate.category
                and e.kind == candidate.kind
                and (
                    candidate.category in SCALAR_FACETS
                    or _label(e) == normalize_memory_surface(candidate.label)
                )
                and normalize_memory_surface(str(_value(e)))
                == normalize_memory_surface(candidate.value)
                and occurrence_matches(e, candidate, source)
            ]
            if len(same) > 1:
                skip("ambiguous_existing_fact")
                continue
            refine_target = None
            decision_only = False
            added = (
                _added_detail(candidate, source)
                if candidate.intent == "new" and candidate.category not in SCALAR_FACETS
                else {}
            )
            if added:
                if same:
                    refine_target = same[0]
                elif (
                    choice.decision in {"match", "duplicate"}
                    and entry is not None
                    and entry.category == candidate.category
                    and entry.kind == candidate.kind
                    and (
                        _label(entry) == normalize_memory_surface(candidate.label)
                        # A shorter name for exactly one item ("the Tigor"
                        # for "Tata Tigor"); never between two plausible items.
                        or unique_reference(entry, candidate.label, catalog.entries)
                    )
                ):
                    refine_target = entry
                elif candidate.category == "plan" and _option_decision_target(
                    choice, entry, candidate, added, catalog.entries
                ):
                    # The new words name the decision, not the stored plan
                    # (run 5: stored label "trip", new label "winter Spiti").
                    # The chosen option itself identifies the plan: it must be
                    # one of this plan's stated alternatives and of no other
                    # current plan. Only the option-decision change is allowed
                    # through this route, never a refine.
                    refine_target, decision_only = entry, True
            if refine_target is not None:
                try:
                    old_value = json.loads(refine_target.value)
                except (TypeError, ValueError):
                    old_value = None
                if not isinstance(old_value, dict):
                    skip("already_stored")
                    continue
                # Recomputed with the stored value as context (a restated
                # acquired month may then get its inferred year).
                added = _added_detail(candidate, source, old_value) or added
                merged, reason = refine_merge(old_value, added)
                predicate, expected = (
                    refine_target.predicate,
                    refine_target.assertion_id,
                )
                if (
                    merged is None
                    and candidate.category == "plan"
                    and decides_stated_options(old_value, added)
                ):
                    # Choosing one of the owner's stated alternatives changes
                    # the same plan (D10); the earlier row keeps the options.
                    if predicate in used:
                        skip("conflicting_mutations")
                        continue
                    used.add(predicate)
                    mutations.append(
                        self._mutation(
                            index,
                            candidate,
                            source,
                            "change",
                            predicate,
                            expected,
                            _changed_value(old_value, candidate, source),
                            others=_other_labels(batch, index),
                        )
                    )
                    continue
                if decision_only:
                    skip("new_fact_cannot_mutate_target")
                    continue
                if merged is None:
                    skip(reason)
                    continue
                if predicate in used:
                    skip("conflicting_mutations")
                    continue
                used.add(predicate)
                mutations.append(
                    self._mutation(
                        index,
                        candidate,
                        source,
                        "refine",
                        predicate,
                        expected,
                        merged,
                        valid_from=day_boundary(merged.get("acquired"))
                        if candidate.category == "owned_item"
                        else None,
                        others=_other_labels(batch, index),
                    )
                )
                continue
            if choice.decision == "duplicate":
                skip("duplicate")
                continue  # No write; semantic equivalence is not a new fact.
            if candidate.intent == "new" and same:
                skip("already_stored")
                continue
            if choice.decision == "new":
                if candidate.intent != "new" or choice.target_id is not None:
                    skip("new_resolution_conflicts_with_intent_or_target")
                    continue
                # Do not split a related legacy plural/scalar representation.
                if any(
                    e.category == "legacy"
                    and normalize_memory_surface(candidate.value)
                    in normalize_memory_surface(e.value)
                    for e in catalog.entries
                ):
                    skip("legacy_fact_overlap")
                    continue
                predicate = (
                    candidate.scalar_facet
                    if candidate.category in SCALAR_FACETS
                    else f"{candidate.category}_{uuid4().hex}"
                )
                if any(e.predicate == predicate for e in catalog.entries):
                    skip("predicate_already_exists")
                    continue
                action, expected = "create", None
            else:
                if entry is None or entry.category != candidate.category:
                    skip("target_missing_or_category_mismatch")
                    continue
                if (
                    candidate.category in SCALAR_FACETS
                    and entry.predicate != candidate.scalar_facet
                ):
                    skip("scalar_facet_mismatch")
                    continue
                if candidate.category == "owned_item" and entry.kind != candidate.kind:
                    skip("item_kind_mismatch")
                    continue
                if candidate.intent == "new":
                    skip("new_fact_cannot_mutate_target")
                    continue
                action = {
                    "change": "change",
                    "correction": "correct",
                    "retraction": "retract",
                }.get(candidate.intent)
                if action is None:
                    skip("unsupported_intent")
                    continue
                predicate, expected = entry.predicate, entry.assertion_id
            if predicate in used:
                skip("conflicting_mutations")
                continue
            used.add(predicate)
            value = candidate.value
            if candidate.category not in SCALAR_FACETS:
                if entry is not None and action == "change":
                    try:
                        old = json.loads(entry.value)
                    except (TypeError, ValueError):
                        skip("invalid_existing_value")
                        continue
                    value = _changed_value(old, candidate, source)
                    if candidate.category == "plan" and _names_entry(
                        candidate, entry, catalog.entries
                    ):
                        # "Cancel the Goa plan": a status change of the plan
                        # it names keeps that plan's name.
                        value["label"] = old.get("label", value["label"])
                        value["value"] = old.get("value", value["value"])
                elif entry is not None and action == "correct":
                    try:
                        old = json.loads(entry.value)
                    except (TypeError, ValueError):
                        old = None
                    value = _new_value(candidate, source, old)
                    if candidate.category == "owned_item" and isinstance(old, dict):
                        value = _corrected_item_value(
                            old, value, candidate, entry, catalog.entries
                        )
                else:
                    value = _new_value(candidate, source)
            effective_at = None
            valid_from = None
            if candidate.category == "owned_item" and isinstance(value, dict):
                if action == "change" and value.get("state") in DISPOSED_STATES:
                    # Only a stated day becomes the change boundary; week,
                    # month or year leaves it unknown (never the told time).
                    effective_at = day_boundary(value.get("disposed"))
                elif action == "create":
                    valid_from = day_boundary(value.get("acquired"))
            mutations.append(
                self._mutation(
                    index,
                    candidate,
                    source,
                    action,
                    predicate,
                    expected,
                    value,
                    effective_at=effective_at,
                    valid_from=valid_from,
                    others=_other_labels(batch, index),
                )
            )
        return LearningPlan(
            source,
            tuple(mutations),
            tuple(sorted(catalog.suppression_epochs.items())),
            tuple(outcomes),
        )

    @staticmethod
    def _mutation(
        index,
        candidate,
        source,
        action,
        predicate,
        expected,
        value,
        *,
        effective_at=None,
        valid_from=None,
        others=(),
    ):
        value_type = ValueType.TEXT if isinstance(value, str) else ValueType.JSON
        normalized = f"{candidate.category}: {candidate.value}"
        if isinstance(value, dict):
            normalized = (
                f"{candidate.category}.{candidate.kind}: {value['label']}; "
                f"value={value['value']}; state={value['state']}"
            )
        draft = (
            None
            if action == "retract"
            else SemanticAssertionDraft(
                "personal",
                "owner",
                predicate,
                value_type,
                value,
                normalized,
                FreshnessClass.CHANGEABLE,
                Sensitivity.STANDARD,
                valid_from=valid_from,
            )
        )
        fact_digest = hashlib.sha256(
            canonical_json(
                {
                    "value": candidate.value,
                    "evidence": [e.model_dump() for e in candidate.evidence],
                }
            ).encode()
        ).hexdigest()
        source_record = MemorySource(
            str(uuid4()),  # one source per fact, never shared
            MemorySourceClass.OWNER_DIRECT,
            f"conversation:{source.session_id}:turn:{source.turn_id}",
            source.turns[-1].accepted_at,
            AuthorityClass.OWNER_DIRECT,
            Sensitivity.STANDARD,
            source.turns[-1].accepted_at,
            evidence_text=evidence_quote(source, candidate, others),
            evidence_hash=fact_digest,
        )
        return PlannedLearningMutation(
            index,
            action,
            candidate.suppression_key,
            candidate.category,
            predicate,
            expected,
            draft,
            source_record,
            effective_at=effective_at,
        )


def _anchor(source, candidate):
    from .learning_temporal import temporal_context

    return temporal_context(source, candidate)["anchor_at"]


def _item_fields(candidate, source, context=None):
    """Slice-1 fields for an owned item: aliases, details (identifiers
    removed), acquired/disposed time objects at their stated precision.

    A bare month ("from September") gets an inferred year only with
    supporting context that the time is already past:
    - disposed: the owner said the item is gone (sold, given away, lost or
      no longer owned), so the disposal already happened;
    - acquired: ``context`` (the stored value being corrected, changed or
      refined) already holds an acquired time, so the owner is restating
      that same past time.
    Without that context (for example a new item "from September") the month
    stays unresolved with its wording; it is never turned into a purchase
    date."""
    from datetime import datetime

    anchor = datetime.fromisoformat(_anchor(source, candidate))
    context = context if isinstance(context, dict) else {}
    past = {
        "disposed": candidate.state in DISPOSED_STATES,
        "acquired": isinstance(context.get("acquired"), dict),
    }
    fields = {}
    aliases = [a for a in candidate.aliases if not has_identifier(a)]
    if aliases:
        fields["aliases"] = aliases
    if candidate.details and not has_identifier(candidate.details):
        fields["details"] = candidate.details
    for key, expression in (
        ("acquired", candidate.acquired_expression),
        ("disposed", candidate.disposed_expression),
    ):
        stated = item_time(expression, anchor, past=past[key])
        if stated:
            fields[key] = stated
    return fields


def _time_words(candidate) -> set[str]:
    return {
        normalize_memory_surface(t)
        for t in (
            candidate.acquired_expression,
            candidate.disposed_expression,
            candidate.time_expression,
        )
        if t
    }


def _item_identity(candidate) -> str:
    """An owned item's value is the item, never one of its times: a proposal
    that put the time in ``value`` ("Jimny", value "September") keeps the
    item's name instead."""
    value = candidate.value
    if not value or normalize_memory_surface(value) in _time_words(candidate):
        return candidate.label
    return value


_ARTICLES = ("the ", "my ", "our ", "a ", "an ")


def _without_article(label):
    """'the Tigor' names the Tigor: a leading article is not part of a name."""
    text = (label or "").strip()
    lowered = text.casefold()
    for article in _ARTICLES:
        if lowered.startswith(article) and len(text) > len(article):
            return text[len(article) :].strip()
    return text


def _names_entry(candidate, entry, entries) -> bool:
    """True when the proposal's label names the stored fact: the same label,
    a unique shorter reference ("Tigor" -> "Tata Tigor"), or a label that
    wholly contains the stored name of exactly one fact of that category and
    kind ("Goa plan" -> "Goa"). A leading article is ignored."""
    from .learning_catalog_page import identity_words, name_words

    label = _without_article(candidate.label)
    if _label(entry) == normalize_memory_surface(label):
        return True
    if unique_reference(entry, label, entries):
        return True
    words = name_words(label)
    inside = [
        e.assertion_id
        for e in entries
        if e.category == entry.category
        and e.kind == entry.kind
        and any(w and w <= words for w in identity_words(e))
    ]
    return inside == [entry.assertion_id]


def _corrected_item_value(old, fresh, candidate, entry, entries):
    """A correction of one owned item changes only what the owner corrected.

    When the correction names the stored item (same label, or a unique
    shorter name), its identity - label, value and aliases - and every
    attribute the correction does not restate are kept; only the restated
    attributes (acquired, disposed, details, aliases, state) are replaced. A
    correction naming a different item ("it's a Jimny, not a Thar") corrects
    the identity and still keeps the unrelated attributes. A state corrected
    back to owned drops the disposal time."""
    names_item = _names_entry(candidate, entry, entries)
    value = {**old, "schema": fresh["schema"], "state": fresh["state"]}
    if not names_item:
        value["label"], value["value"] = fresh["label"], fresh["value"]
        value.pop("aliases", None)
    for key in ("aliases", "details", "acquired", "disposed"):
        if key in fresh:
            value[key] = fresh[key]
    if value["state"] not in DISPOSED_STATES:
        value.pop("disposed", None)
    return value


def _plan_fields(candidate):
    fields = {}
    if candidate.plan_status is not None:
        fields["plan_status"] = candidate.plan_status
    slots = normalized_slots(candidate.slots)
    if slots:
        fields["slots"] = slots
    return fields


def _option_decision_target(choice, entry, candidate, added, entries) -> bool:
    """True when the resolver's matched plan is identified by the decision
    itself: a current plan of the same kind, supplied in this catalog page,
    whose stated alternatives include every chosen option, while no other
    current plan in the page offers any of them."""
    if (
        choice.decision not in {"match", "duplicate"}
        or entry is None
        or entry.category != "plan"
        or entry.kind != candidate.kind
    ):
        return False
    try:
        old = json.loads(entry.value)
    except (TypeError, ValueError):
        return False
    if not isinstance(old, dict):
        return False
    chosen = set(decided_options(old, added).values())
    if not chosen:
        return False
    for other in entries:
        if other.assertion_id == entry.assertion_id or other.category != "plan":
            continue
        try:
            other_value = json.loads(other.value)
        except (TypeError, ValueError):
            continue
        if chosen & option_keys(other_value):
            return False
    return True


def _added_detail(candidate, source, context=None):
    if candidate.category == "owned_item":
        return _item_fields(candidate, source, context)
    if candidate.category == "plan":
        return _plan_fields(candidate)
    return {}


def _plan_state_and_certainty(candidate):
    if candidate.category != "plan" or candidate.plan_status is None:
        return candidate.state, candidate.certainty
    certainty = (
        "tentative" if candidate.plan_status == "considering" else candidate.certainty
    )
    return PLAN_STATE[candidate.plan_status], certainty


def _new_value(candidate, source, context=None):
    state, certainty = _plan_state_and_certainty(candidate)
    value = {
        "schema": POLICY_VERSION,
        "category": candidate.category,
        "kind": candidate.kind,
        "label": candidate.label,
        "value": (
            _item_identity(candidate)
            if candidate.category == "owned_item"
            else candidate.value
        ),
        "state": state,
    }
    if candidate.category == "owned_item":
        value.update(_item_fields(candidate, source, context))
    if candidate.category in HISTORY_CATEGORIES:
        value["certainty"] = certainty
        value["temporal"] = temporal_context(source, candidate)
        for key in ("location", "reason"):
            detail = getattr(candidate, key)
            if detail is not None:
                value[key] = detail
        if candidate.category == "plan":
            value.update(_plan_fields(candidate))
    return value


def _changed_value(old, candidate, source):
    """A real-world change to the same thing: keep its identity, update what
    the owner said changed."""
    state, certainty = _plan_state_and_certainty(candidate)
    value = {**old, "state": state}
    if candidate.category != "owned_item":
        value["value"] = candidate.value
    else:
        fields = _item_fields(candidate, source, old)
        for key in ("aliases", "details", "disposed"):
            if key in fields:
                value[key] = fields[key]
        if "acquired" in fields and "acquired" not in value:
            value["acquired"] = fields["acquired"]
    if candidate.category in HISTORY_CATEGORIES:
        value["label"] = candidate.label
        value["certainty"] = certainty
        if candidate.time_expression is not None or "temporal" not in value:
            value["temporal"] = temporal_context(source, candidate)
        for key in ("location", "reason"):
            detail = getattr(candidate, key)
            if detail is not None:
                value[key] = detail
        if candidate.category == "plan":
            fields = _plan_fields(candidate)
            if "plan_status" in fields:
                value["plan_status"] = fields["plan_status"]
            if "slots" in fields:
                value["slots"] = {**(old.get("slots") or {}), **fields["slots"]}
    return value


def _other_labels(batch, index):
    return [c.label for i, c in enumerate(batch.candidates) if i != index and c.label]


def _trip_choices(batch):
    """Vehicles/stays named as plan details in this batch (normalized)."""
    names = set()
    for candidate in batch.candidates:
        if candidate.category != "plan" or candidate.slots is None:
            continue
        for slot in (candidate.slots.vehicle, candidate.slots.stay):
            if slot is None:
                continue
            for text in (slot.value, *slot.options):
                if text:
                    names.add(normalize_memory_surface(text))
    return names


def evidence_quote(source, candidate, others=()):
    """The minimum supporting owner quote for one admitted standard fact
    (docs/policy/personal-memory-evidence-retention.md)."""
    if candidate.sensitivity != "standard" or candidate.qualification != "direct":
        return None
    turns = {t.turn_id: t.text for t in source.turns}
    fragments = [
        turns[e.turn_id][e.start : e.end]
        for e in candidate.evidence
        if e.turn_id in turns
    ]
    needles = [candidate.value, candidate.label, *candidate.aliases]
    return minimal_quote(fragments, needles, list(others))
