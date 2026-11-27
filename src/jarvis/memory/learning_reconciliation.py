"""Closed canonical identity resolution and immutable, version-bound write plans."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from uuid import uuid4

from jarvis.authority.personal_learning import POLICY_VERSION, LearningActionBinding
from jarvis.authority.proposal import canonical_json
from jarvis.personal_learning_scope import CATEGORIES

from .assertions import SemanticAssertionDraft
from .learning_catalog_page import (
    CATALOG_LIMIT,
    PAGE_AMBIGUOUS,
    bounded_entries,
    unique_reference,
)
from .learning_contracts import (
    AcceptedLearningSource,
    LearningBatch,
    LearningCatalog,
    LearningCatalogEntry,
    LearningResolution,
    LearningResolutionBatch,
)
from .learning_diagnostics import log_learning
from .learning_policy import SCALAR_FACETS, LearningPolicy
from .learning_temporal import (
    HISTORY_CATEGORIES,
    POSSIBILITY_CATEGORIES,
    normalize_plan_time,
    occurrence_matches,
    plan_schedule_unspecified,
    plan_time_restated,
    temporal_context,
)
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
from .personal_time import day_boundary, time_object
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
    # Ephemeral clarification bookkeeping, excluded from write authorization.
    matched_plan_ids: tuple[tuple[int, str], ...] = ()

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

    async def catalog(self, source, batch, grant, *, targets=()):
        """Current entries for these proposals. ``targets``: canonical plans
        an answered open question is bound to; always supplied, so the
        answer can reach its own plan however many entries exist."""
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
        held = {e.assertion_id for e in supplied}
        supplied += [
            e for e in entries if e.predicate in targets and e.assertion_id not in held
        ][: max(0, CATALOG_LIMIT - len(supplied))]
        return LearningCatalog(entries=supplied, page_ambiguous=list(ambiguous))

    def plan(
        self,
        source: AcceptedLearningSource,
        batch: LearningBatch,
        catalog: LearningCatalog,
        resolutions: LearningResolutionBatch,
        *,
        confirmation_targets: dict[int, str] | None = None,
    ) -> LearningPlan:
        by_id = {entry.assertion_id: entry for entry in catalog.entries}
        confirmation_targets = confirmation_targets or {}
        choices = {}
        duplicate_indices = set()
        for choice in resolutions.resolutions:
            if choice.candidate_index in choices:
                duplicate_indices.add(choice.candidate_index)
            choices[choice.candidate_index] = choice
        mutations = []
        outcomes = []
        matched_plan_ids = {}
        used = set()
        trip_choices = _trip_choices(batch)
        for index, candidate in enumerate(batch.candidates):
            candidate = normalize_plan_time(candidate)

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
            candidate = _settled_item_times(candidate)
            candidate, date_issue = _evidenced_item_dates(candidate, source, batch)
            if date_issue and _restates_nothing(candidate):
                # A date with no positive evidence of being the purchase or
                # disposal date (or with another role): nothing else was said,
                # so the item stays unchanged and the reason is recorded.
                skip(date_issue)
                continue
            required = confirmation_targets.get(index)
            if index in catalog.page_ambiguous and required is None:
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
            if required is not None:
                # An answer to an open question is bound by code to the plan
                # the question was asked about; the resolver's reading and the
                # proposal's display name cannot redirect it. It only adds the
                # answered details to that current plan, or nothing.
                bound = next(
                    (
                        e
                        for e in catalog.entries
                        if e.predicate == required and e.category == candidate.category
                    ),
                    None,
                )
                if bound is None:
                    skip("confirmation_target_missing")
                    continue
                matched_plan_ids[index] = bound.assertion_id
                try:
                    held = json.loads(bound.value)
                except (TypeError, ValueError):
                    held = None
                if not isinstance(held, dict):
                    skip("invalid_existing_value")
                    continue
                if held.get("state") in {"cancelled", "completed"}:
                    # A question about a plan that has since ended is moot.
                    skip("plan_ended")
                    continue
                # The plan's own kind, status and certainty stay as stored.
                candidate = candidate.model_copy(
                    update={
                        "kind": bound.kind,
                        "state": held.get("state", candidate.state),
                        "certainty": held.get("certainty", candidate.certainty),
                        "plan_status": held.get("plan_status"),
                    }
                )
                if not _added_detail(candidate, source):
                    skip("already_stored")
                    continue
                choice = LearningResolution(
                    candidate_index=index,
                    decision="match",
                    target_id=bound.assertion_id,
                )
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
            if len(same) > 1 and required is None:
                skip("ambiguous_existing_fact")
                continue
            named_target = same[0] if same else None
            compatible_match = (
                choice.decision in {"match", "duplicate"}
                and entry is not None
                and entry.category == candidate.category
                and entry.kind == candidate.kind
            )
            if (
                named_target is None
                and compatible_match
                and (
                    _label(entry) == normalize_memory_surface(candidate.label)
                    # A shorter name for exactly one item ("the Tigor"
                    # for "Tata Tigor"); never between two plausible items.
                    or unique_reference(entry, candidate.label, catalog.entries)
                )
            ):
                named_target = entry
            if required is not None:
                named_target = entry
            if candidate.category == "plan":
                if named_target is not None:
                    matched_plan_ids[index] = named_target.assertion_id
                elif compatible_match and _names_entry(
                    candidate, entry, catalog.entries
                ):
                    # A longer reference may identify an existing question
                    # without satisfying the narrower rules for a write.
                    matched_plan_ids[index] = entry.assertion_id

            added = (
                _added_detail(candidate, source)
                if candidate.intent == "new" and candidate.category not in SCALAR_FACETS
                else {}
            )
            refine_target = named_target if added else None
            decision_only = False
            if (
                date_issue
                and not added
                and candidate.state == "owned"
                and choice.decision in {"match", "duplicate"}
            ):
                # The only new detail for a known item was an unevidenced date:
                # nothing to apply, recorded rather than silently dropped.
                skip(date_issue)
                continue
            if (
                added
                and refine_target is None
                and candidate.category == "plan"
                and _option_decision_target(
                    choice, entry, candidate, added, catalog.entries
                )
            ):
                # The chosen option identifies the plan when it is one of the
                # alternatives on only that plan. Only that decision can
                # change the plan through this route, which keeps its kind.
                refine_target, decision_only = entry, True
                if candidate.kind != entry.kind:
                    candidate = candidate.model_copy(update={"kind": entry.kind})
            required = confirmation_targets.get(index)
            if required is not None and (
                refine_target is None or refine_target.predicate != required
            ):
                skip("confirmation_target_mismatch")
                continue
            if refine_target is not None:
                try:
                    old_value = json.loads(refine_target.value)
                except (TypeError, ValueError):
                    old_value = None
                if not isinstance(old_value, dict):
                    skip("already_stored")
                    continue
                if candidate.category == "plan":
                    matched_plan_ids[index] = refine_target.assertion_id
                # Recomputed with the stored value as context (a restated
                # acquired month may then get its inferred year).
                added = _added_detail(candidate, source, old_value) or added
                merged, reason = refine_merge(old_value, added)
                predicate, expected = (
                    refine_target.predicate,
                    refine_target.assertion_id,
                )
                if (
                    candidate.category == "owned_item"
                    and not decision_only
                    and candidate.state in OWNERSHIP_STATES
                    and old_value.get("state") in OWNERSHIP_STATES
                    and candidate.state != old_value.get("state")
                ):
                    # "I sold the Classic 350 in October." proposed as new
                    # detail (run 7 D23): a different ownership state of the
                    # named item is a real change of that item, never a
                    # refine that would keep it owned.
                    if predicate in used:
                        skip("conflicting_mutations")
                        continue
                    used.add(predicate)
                    value = _changed_value(old_value, candidate, source)
                    mutations.append(
                        self._mutation(
                            index,
                            candidate,
                            source,
                            "change",
                            predicate,
                            expected,
                            value,
                            effective_at=day_boundary(value.get("disposed")),
                            others=_other_labels(batch, index),
                        )
                    )
                    continue
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
                    value = _changed_value(old_value, candidate, source)
                    for key in ("label", "value"):
                        if key in old_value:
                            value[key] = old_value[key]
                    mutations.append(
                        self._mutation(
                            index,
                            candidate,
                            source,
                            "change",
                            predicate,
                            expected,
                            value,
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
                if candidate.category == "plan" and "when" in added.get("slots", {}):
                    # Adding a schedule detail must also fill its calendar.
                    # A refinement cannot change an already stated window,
                    # including a relative date re-anchored to a later turn.
                    fresh_time = temporal_context(source, candidate)
                    old_time = old_value.get("temporal") or {}
                    if old_time.get("expression"):
                        keys = ("precision", "earliest", "latest")
                        same = all(old_time.get(k) == fresh_time.get(k) for k in keys)
                        if old_time.get("precision") in {None, "unresolved"}:
                            same = same and old_time.get(
                                "expression"
                            ) == fresh_time.get("expression")
                        if not same:
                            skip("refine_conflicts_existing_detail")
                            continue
                    else:
                        merged["temporal"] = fresh_time
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
                    if candidate.category == "owned_item" and isinstance(old, dict):
                        candidate, unclear = _attributed_correction(
                            candidate, old, source, batch
                        )
                        if unclear:
                            skip(unclear)
                            continue
                    value = _new_value(candidate, source, old)
                    if candidate.category == "owned_item" and isinstance(old, dict):
                        value = _corrected_item_value(
                            old, value, candidate, entry, catalog.entries
                        )
                    elif candidate.category == "plan" and isinstance(old, dict):
                        value = _corrected_plan_value(
                            old, value, candidate, entry, catalog.entries
                        )
                        if value is None:
                            skip("correction_unclear")
                            continue
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
        kept = []
        for mutation in mutations:
            candidate = batch.candidates[mutation.ordinal]
            problem = _item_inconsistency(mutation) or _possibility_overrides_fact(
                mutation, candidate, by_id
            )
            if problem is None:
                kept.append(mutation)
                continue
            log_learning(
                self.diagnostics,
                source,
                "reconciliation",
                "skipped",
                candidate_index=mutation.ordinal,
                reason=problem,
            )
            outcomes.append(
                LearningOutcome(
                    mutation.ordinal,
                    candidate.suppression_key,
                    candidate.category,
                    problem,
                )
            )
        mutations = kept
        return LearningPlan(
            source,
            tuple(mutations),
            tuple(sorted(catalog.suppression_epochs.items())),
            tuple(outcomes),
            tuple(matched_plan_ids.items()),
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


OWNERSHIP_STATES = frozenset({"owned"}) | frozenset(DISPOSED_STATES)


def _settled_item_times(candidate):
    """Drop details that only repeat a time the proposal already placed in
    its acquired or disposed field ("March 2024" twice). Nothing is moved:
    what a date means is never inferred from where the model put it."""
    if candidate.category != "owned_item" or not candidate.details:
        return candidate
    placed = {
        normalize_memory_surface(t)
        for t in (candidate.acquired_expression, candidate.disposed_expression)
        if t
    }
    if normalize_memory_surface(candidate.details) in placed:
        return candidate.model_copy(update={"details": None})
    return candidate


# "X, not Y" / "Y nahi, X": the owner names the stored time being replaced.
_REPLACED_TIME = re.compile(
    r"(?:\bnot\b|\binstead of\b|\brather than\b)\s+([^,.;!?]+)"
    r"|([^,.;!?]+?)\s+(?:nahi|nahin)\b",
    re.IGNORECASE,
)


def _corrected_reference(candidate, old, source):
    """The stored date a correction refers to: the owner names the replaced
    time ("from September, not October") and it falls inside exactly one of
    the item's stored acquired/disposed periods. Returns "acquired",
    "disposed" or None."""
    anchor = datetime.fromisoformat(_anchor(source, candidate))
    # "April 2017, not March": the replaced month shares the stated year.
    years = {
        y
        for t in (
            candidate.acquired_expression,
            candidate.disposed_expression,
            candidate.time_expression,
        )
        if t
        for y in re.findall(r"\b(?:19|20)\d{2}\b", t)
    }
    matches = set()
    for m in _REPLACED_TIME.finditer(source.text):
        words = (m.group(1) or m.group(2) or "").strip()
        if words and len(years) == 1 and not re.search(r"\b\d{4}\b", words):
            words = f"{words} {next(iter(years))}"
        named = time_object(words, anchor, direction="past") if words else None
        if not named or not named.get("earliest"):
            continue
        for key in ("acquired", "disposed"):
            stored = old.get(key)
            if (
                isinstance(stored, dict)
                and stored.get("earliest")
                and stored.get("latest")
                and stored["earliest"] <= named["latest"]
                and named["earliest"] <= stored["latest"]
            ):
                matches.add(key)
    return matches.pop() if len(matches) == 1 else None


def _attributed_correction(candidate, old, source, batch):
    """Positive evidence for a correction's purchase/disposal date.

    A date stays (or is placed) as the acquired/disposed time only with
    acquisition/disposal wording for that item and date in the owner's words,
    or when the correction unambiguously refers to that stored date (it names
    the replaced time, which falls inside exactly that stored period). A
    lone stored date is not enough, and wording giving the date another role
    blocks it. Otherwise the date is not applied, and the correction is
    skipped with a recorded reason when nothing else remains. Returns
    (candidate, None) or (candidate, reason)."""
    if candidate.category != "owned_item" or candidate.intent != "correction":
        return candidate, None
    reference = _corrected_reference(candidate, old, source)
    update = {}
    for key in ("acquired", "disposed"):
        field = key + "_expression"
        phrase = getattr(candidate, field)
        if (
            phrase
            and not _has_date_evidence(source, candidate, phrase, key, batch)
            and reference != key
        ):
            update[field] = None
    if update:
        candidate = candidate.model_copy(update=update)
    if candidate.acquired_expression or candidate.disposed_expression:
        return candidate, None
    details = candidate.details
    phrase = candidate.time_expression
    time_only_details = bool(details and phrase) and normalize_memory_surface(
        details
    ) == normalize_memory_surface(phrase)
    if not phrase or (details and not time_only_details):
        if update and _restates_nothing(candidate):
            return candidate, "date_evidence_missing"
        return candidate, None
    if _date_role(source, candidate, phrase):
        return candidate, "date_role_conflict"
    if reference is None:
        return candidate, "time_meaning_unclear"
    placed = {reference + "_expression": phrase}
    if time_only_details:
        placed["details"] = None
    return candidate.model_copy(update=placed), None


# Wording that gives a date another role on the same item. A date in the same
# clause as one of these is never the item's purchase or disposal date.
_OTHER_DATE_ROLES = re.compile(
    r"\bmodel\b|\bmanufactur\w*|\bmfg\b"
    r"|\bservic\w*"
    r"|\bwarrant\w*|\bguarantee\w*"
    r"|\binsur\w*|\bbima\b|\bpolicy\b|\brenew\w*",
    re.IGNORECASE,
)
_CLAUSE_BREAK = re.compile(r"[,;.!?]|\b(?:and|aur|but|lekin|par)\b", re.IGNORECASE)


def _evidence_text(source, candidate):
    """The owner turns the evidence comes from, whole: a minimal quote such as
    "a Royal Enfield Classic 350 from 2021" shares its verb ("I have ...")
    with the rest of the owner's sentence."""
    turns = {t.turn_id: t.text for t in source.turns}
    cited = dict.fromkeys(
        turns[span.turn_id] for span in candidate.evidence if span.turn_id in turns
    )
    return " ".join(cited) or source.text


def _date_role(source, candidate, phrase):
    """The other role the owner's own words give this date, or None: a clause
    of the evidence that contains the date phrase also says model, service,
    warranty or insurance. Checked on the owner's words, never the model's."""
    if not phrase:
        return None
    wanted = phrase.casefold()
    for clause in _CLAUSE_BREAK.split(_evidence_text(source, candidate)):
        if wanted in clause.casefold():
            found = _OTHER_DATE_ROLES.search(clause)
            if found:
                return found.group(0).casefold()
    return None


_ACQUISITION_WORDING = re.compile(
    r"\b(?:bought|buy|buying|purchas\w*|got|get|getting|acquired|picked up"
    r"|took delivery|liya|liye|kharid\w*)\b"
    # "since" only: "I have X from 2021" may name a model year or vintage,
    # so "from" alone never establishes when the owner got it (owner decision
    # 2026-11-23 on frozen D1's ambiguous wording).
    r"|\b(?:have|has|had|having|own|owns|owned|rakh\w*)\b[^,;.]*\bsince\b",
    re.IGNORECASE,
)
_DISPOSAL_WORDING = re.compile(
    r"\b(?:sold|sell|selling|gave|give|given|lost|lose|scrapp?\w*|traded"
    r"|exchanged|stolen|bech\w*|kho\w*)\b",
    re.IGNORECASE,
)
_REFERRING_ITEM = re.compile(
    r"\b(?:it|its|this|that|woh|wo|use|usko|isko|ise)\b", re.IGNORECASE
)


def _names_this_item(clause, candidate, batch):
    from .learning_catalog_page import name_words

    words = name_words(clause)
    own = (name_words(candidate.label) | name_words(candidate.value or "")) - {
        "the",
        "my",
        "an",
    }
    if own & words:
        return True
    items = [c for c in batch.candidates if c.category == "owned_item"]
    return len(items) == 1 and bool(_REFERRING_ITEM.search(clause))


def _has_date_evidence(source, candidate, phrase, key, batch):
    """Positive evidence that ``phrase`` is this item's acquisition (or
    disposal) time: one clause of the owner's evidence contains the date,
    acquisition (disposal) wording and the item (or, when the turn has a
    single item, a referring word)."""
    wording = _ACQUISITION_WORDING if key == "acquired" else _DISPOSAL_WORDING
    wanted = phrase.casefold()
    for clause in _CLAUSE_BREAK.split(_evidence_text(source, candidate)):
        if (
            wanted in clause.casefold()
            and wording.search(clause)
            and _names_this_item(clause, candidate, batch)
        ):
            return True
    return False


def _evidenced_item_dates(candidate, source, batch):
    """Purchase/disposal dates need positive evidence, whoever supplied them.

    Kept when the owner's words give acquisition/disposal wording linked to
    the item and date. A correction's date is decided against the stored item
    (``_attributed_correction``). Removed when the words give the date another
    role (a veto, not the rule) or nothing positive supports it, so an
    unfamiliar date role never defaults to purchase or sale. Returns
    (candidate, reason or None)."""
    if candidate.category != "owned_item":
        return candidate, None
    update, reason = {}, None
    for key in ("acquired", "disposed"):
        field = key + "_expression"
        phrase = getattr(candidate, field)
        if not phrase:
            continue
        if _date_role(source, candidate, phrase):
            update[field], reason = None, "date_role_conflict"
        elif _has_date_evidence(source, candidate, phrase, key, batch):
            continue
        elif candidate.intent == "correction":
            continue  # decided against the stored item
        else:
            update[field] = None
            reason = reason or "date_evidence_missing"
    if not update:
        return candidate, None
    return candidate.model_copy(update=update), reason


def _restates_nothing(candidate):
    """A correction or change left with nothing to apply once a conflicting
    date was removed (a different ownership state still counts as content)."""
    if candidate.intent not in {"correction", "change"}:
        return False
    return not (
        candidate.acquired_expression
        or candidate.disposed_expression
        or candidate.details
        or candidate.aliases
        or (candidate.intent == "change" and candidate.state in DISPOSED_STATES)
    )


def _item_inconsistency(mutation):
    """Record-level invariants for an owned item about to be written; a
    violation is skipped with a reason instead of stored:
    - a disposal time only for a no-longer-owned state;
    - details are never just one of the item's own time phrases;
    - the value is never one of the item's own time phrases."""
    value = getattr(mutation.draft, "value", None)
    if not isinstance(value, dict) or value.get("category") != "owned_item":
        return None
    if value.get("disposed") and value.get("state") not in DISPOSED_STATES:
        return "inconsistent_item_state"
    times = {
        normalize_memory_surface(t.get("expression"))
        for t in (value.get("acquired"), value.get("disposed"))
        if isinstance(t, dict) and t.get("expression")
    }
    details = value.get("details")
    if isinstance(details, str) and normalize_memory_surface(details) in times:
        return "time_in_item_details"
    item = value.get("value")
    if isinstance(item, str) and normalize_memory_surface(item) in times:
        return "time_as_item_value"
    return None


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
    from .learning_catalog_page import PLAN_HEAD_NOUNS, identity_words, name_words

    label = _without_article(candidate.label)
    if _label(entry) == normalize_memory_surface(label):
        return True
    if unique_reference(entry, label, entries):
        return True
    words = name_words(label)
    if entry.category in {"plan", "event"}:
        # "Spiti trip" names "winter Spiti": the head noun says what kind of
        # plan it is, not which one; the remaining words must name one plan.
        wanted = words - PLAN_HEAD_NOUNS
        named = [
            e.assertion_id
            for e in entries
            if e.category == entry.category
            and e.kind == entry.kind
            and wanted
            and any(wanted <= w for w in identity_words(e))
        ]
        if named == [entry.assertion_id]:
            return True
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


def _corrected_plan_value(old, fresh, candidate, entry, entries):
    """A correction of one plan changes only what it restates.

    Shared update rule (as for owned items): the plan's identity and every
    detail the correction does not restate are kept. Replaced when restated
    and different: plan status (with its state), individual slots (merged,
    never dropped), the time (temporal), location, reason, certainty. The
    name changes only when the correction names a different plan ("the
    Kerala trip, not the Goa trip"). A correction that restates nothing
    different is unclear: None (skipped and recorded). An unstated detail is
    never removed; the slice-1 schema has no way to state a removal."""
    value = {**old, "schema": fresh["schema"]}
    restated = False
    if candidate.plan_status is not None and fresh.get("plan_status") != old.get(
        "plan_status"
    ):
        value["plan_status"], value["state"] = fresh["plan_status"], fresh["state"]
        restated = True
    old_slots = old.get("slots") or {}
    changed = {
        k: v for k, v in (fresh.get("slots") or {}).items() if old_slots.get(k) != v
    }
    if changed:
        value["slots"] = {**old_slots, **changed}
        restated = True
    old_time = old.get("temporal") or {}
    fresh_time = fresh["temporal"]
    if (candidate.time_expression is not None or plan_time_restated(candidate)) and any(
        old_time.get(key) != fresh_time.get(key)
        for key in ("expression", "precision", "earliest", "latest")
    ):
        value["temporal"] = fresh_time
        restated = True
    for key in ("location", "reason"):
        if fresh.get(key) is not None and fresh[key] != old.get(key):
            value[key] = fresh[key]
            restated = True
    if restated and fresh.get("certainty") is not None:
        value["certainty"] = fresh["certainty"]
    if not _names_entry(candidate, entry, entries):
        value["label"], value["value"] = fresh["label"], fresh["value"]
        restated = True
    return value if restated else None


def _plan_fields(candidate, context=None):
    fields = {}
    if candidate.plan_status is not None:
        fields["plan_status"] = candidate.plan_status
    slots = normalized_slots(candidate.slots, candidate.owner_confirmed)
    if (
        candidate.time_expression is not None
        and plan_schedule_unspecified(candidate)
        and context
        and "when" in (context.get("slots") or {})
    ):
        # A legacy time-only update restates the same schedule detail; it
        # must not leave its older slot value contradicting the calendar.
        slots["when"] = {
            "value": candidate.time_expression,
            "options": [],
            "certainty": candidate.certainty,
        }
    if slots:
        fields["slots"] = slots
    return fields


def _option_decision_target(choice, entry, candidate, added, entries) -> bool:
    """True when the resolver's matched plan is identified by the decision
    itself: a current plan, supplied in this catalog page, whose stated
    alternatives include every chosen option, while no other current plan in
    the page (of any kind) offers any of them. The proposal's plan kind is not
    required to match: it does not identify a plan, and the change keeps the
    stored plan's kind."""
    if (
        choice.decision not in {"match", "duplicate"}
        or entry is None
        or entry.category != "plan"
        or candidate.category != "plan"
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
        return _plan_fields(candidate, context)
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
            value.update(_plan_fields(candidate, context))
    return _record_certainty(value, candidate, certainty)


def _possibility_overrides_fact(mutation, candidate, by_id):
    """A possibility never changes, corrects or withdraws a stored fact, in
    any category: "maybe we'll cancel Goa" leaves the plan as it is, and
    "I might move my swim to 7" leaves 6. It may update a stored possibility.
    Adding a detail (refine) is not affected; a detail keeps its own
    certainty."""
    # The owner's own certainty about what they said, not the plan's status:
    # "the trip is only being considered now" is a stated change.
    if candidate.certainty != "tentative" or mutation.action not in {
        "change",
        "correct",
        "retract",
    }:
        return None
    entry = by_id.get(mutation.expected_assertion_id)
    try:
        old = json.loads(entry.value) if entry is not None else None
    except (TypeError, ValueError):
        old = None
    if isinstance(old, dict) and old.get("certainty") == "tentative":
        return None
    return "possibility_cannot_change_fact"


def _record_certainty(value, candidate, certainty):
    """Routines and goals record a possibility (absent means confirmed, as in
    rows stored before this rule); history categories always record it."""
    if candidate.category in POSSIBILITY_CATEGORIES - HISTORY_CATEGORIES:
        value.pop("certainty", None)
        if certainty == "tentative":
            value["certainty"] = "tentative"
    return value


def _changed_value(old, candidate, source):
    """A real-world change to the same thing: keep its identity, update what
    the owner said changed."""
    state, certainty = _plan_state_and_certainty(candidate)
    value = _record_certainty({**old, "state": state}, candidate, certainty)
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
        if (
            candidate.time_expression is not None
            or plan_time_restated(candidate)
            or "temporal" not in value
        ):
            value["temporal"] = temporal_context(source, candidate)
        for key in ("location", "reason"):
            detail = getattr(candidate, key)
            if detail is not None:
                value[key] = detail
        if candidate.category == "plan":
            fields = _plan_fields(candidate, old)
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
