"""Closed canonical identity resolution and immutable, version-bound write plans."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from uuid import uuid4

from jarvis.authority.personal_learning import POLICY_VERSION, LearningActionBinding
from jarvis.authority.proposal import canonical_json

from .assertions import SemanticAssertionDraft
from .learning_contracts import (
    AcceptedLearningSource,
    LearningBatch,
    LearningCatalog,
    LearningCatalogEntry,
    LearningResolutionBatch,
)
from .learning_policy import SCALAR_FACETS, LearningPolicy
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


@dataclass(frozen=True)
class LearningPlan:
    source: AcceptedLearningSource
    mutations: tuple[PlannedLearningMutation, ...]
    suppression_epochs: tuple[tuple[str, int], ...] = ()

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
                }
            ).encode()
        ).hexdigest()

    def binding(self):
        return LearningActionBinding(
            "admit",
            self.source.receipt_id,
            self.digest,
            tuple(sorted({m.category for m in self.mutations})),
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


class LearningReconciler:
    def __init__(self, reader, authority):
        self.reader = reader
        self.authority = authority

    async def catalog(self, source, batch, grant):
        categories = tuple(sorted({c.category for c in batch.candidates}))
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
        records = await self.reader.learning_current()
        entries = []
        for record in records:
            category, kind = "legacy", "other"
            if (
                isinstance(record.value, dict)
                and record.value.get("schema") == POLICY_VERSION
            ):
                category = record.value.get("category", "legacy")
                kind = record.value.get("kind", "other")
            else:
                for candidate_category, predicates in SCALAR_FACETS.items():
                    if record.predicate in predicates:
                        category = candidate_category
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
        return LearningCatalog(entries=entries)

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
        used = set()
        for index, candidate in enumerate(batch.candidates):
            if LearningPolicy().evaluate(source, candidate).status != "eligible":
                continue
            choice = choices.get(index)
            if (
                choice is None
                or index in duplicate_indices
                or choice.decision == "uncertain"
            ):
                continue
            entry = by_id.get(choice.target_id)
            same = [
                e
                for e in catalog.entries
                if e.category == candidate.category
                and normalize_memory_surface(str(_value(e)))
                == normalize_memory_surface(candidate.value)
            ]
            if len(same) > 1:
                continue
            if choice.decision == "duplicate":
                continue  # No write; semantic equivalence is not a new fact.
            if candidate.intent == "new" and same:
                continue
            if choice.decision == "new":
                if candidate.intent != "new" or choice.target_id is not None:
                    continue
                # Do not split a related legacy plural/scalar representation.
                if any(
                    e.category == "legacy"
                    and normalize_memory_surface(candidate.value)
                    in normalize_memory_surface(e.value)
                    for e in catalog.entries
                ):
                    continue
                predicate = (
                    candidate.scalar_facet
                    if candidate.category in SCALAR_FACETS
                    else f"{candidate.category}_{uuid4().hex}"
                )
                if any(e.predicate == predicate for e in catalog.entries):
                    continue
                action, expected = "create", None
            else:
                if entry is None or entry.category != candidate.category:
                    continue
                if candidate.category == "owned_item" and entry.kind != candidate.kind:
                    continue
                if candidate.intent == "new":
                    continue
                action = {
                    "change": "change",
                    "correction": "correct",
                    "retraction": "retract",
                }.get(candidate.intent)
                if action is None:
                    continue
                predicate, expected = entry.predicate, entry.assertion_id
            if predicate in used:
                continue
            used.add(predicate)
            value = candidate.value
            value_type = ValueType.TEXT
            if candidate.category not in SCALAR_FACETS:
                if entry is not None and action == "change":
                    try:
                        old = json.loads(entry.value)
                    except (TypeError, ValueError):
                        continue
                    value = {**old, "state": candidate.state}
                else:
                    value = {
                        "schema": POLICY_VERSION,
                        "category": candidate.category,
                        "kind": candidate.kind,
                        "label": candidate.label,
                        "value": candidate.value,
                        "state": candidate.state,
                    }
                value_type = ValueType.JSON
            normalized = f"{candidate.category}: {candidate.value}"
            if isinstance(value, dict):
                normalized = f"{candidate.category}.{candidate.kind}: {value['label']}; state={value['state']}"
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
                str(uuid4()),
                MemorySourceClass.OWNER_DIRECT,
                f"conversation:{source.session_id}:turn:{source.turn_id}",
                source.turns[-1].accepted_at,
                AuthorityClass.OWNER_DIRECT,
                Sensitivity.STANDARD,
                source.turns[-1].accepted_at,
                evidence_hash=fact_digest,
            )
            mutations.append(
                PlannedLearningMutation(
                    index,
                    action,
                    candidate.suppression_key,
                    candidate.category,
                    predicate,
                    expected,
                    draft,
                    source_record,
                )
            )
        return LearningPlan(
            source, tuple(mutations), tuple(sorted(catalog.suppression_epochs.items()))
        )
