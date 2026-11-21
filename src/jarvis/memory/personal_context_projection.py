"""Question-bound personal evidence contracts; canonical storage retains truth."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, model_validator

from jarvis.personal_learning_scope import (
    LEGACY_FACETS,
    POLICY_VERSION,
    SUPPRESSION_KEYS,
)

from .assertions import SemanticAssertionRecord
from .types import AssertionState, FreshnessClass, Sensitivity, ValueType

ScopeKey = Literal[
    "owned_item.vehicle",
    "owned_item.device",
    "owned_item.other",
    "food_preference",
    "response_preference",
    "routine",
    "goal",
    "personal_fact",
    "activity",
    "event",
    "plan",
]


# A current question that refers back ("When did I sell it?") may name its
# target from the owner's earlier turns in the same authorised session. A
# closed list of referring words gates that; anything else must still quote
# the current question.
_REFERRING = re.compile(
    r"\b(?:it|its|that|this|these|those|them|one|woh|wo|vo|voh|use|usko|"
    r"uska|isko|iska|ye|yeh)\b",
    re.IGNORECASE,
)
_REFERENCE_TURNS = 4


class PersonalContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    scope_key: ScopeKey
    target_quote: str | None = None
    # Set only by parse_context_requests (never by the model): the earlier
    # owner turns of the bound session that the target was quoted from.
    reference: tuple[str, ...] | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_target(cls, value):
        if isinstance(value, dict) and "reference" in value:
            raise ValueError("invalid context request")
        if isinstance(value, dict) and "target_quote" in value:
            quote = value["target_quote"]
            if (
                type(quote) is not str
                or not quote.strip()
                or len(quote.encode("utf-8")) > 256
                or value.get("scope_key") in ("food_preference", "response_preference")
            ):
                raise ValueError("invalid context target")
        return value


def parse_context_requests(
    requests: object, *, question: str, context: tuple[str, ...] = ()
) -> tuple[PersonalContextRequest, ...]:
    """Validate the model's requests against the current question.

    A target must be quoted from the current question, except when the
    question refers back (closed referring-word list) and the target is
    quoted from one of the owner's earlier turns in ``context`` (the bound
    session's previous USER turns). Such a request carries those turns; the
    projection then releases the item only if it is the one unambiguous
    referent there, and otherwise asks which item was meant."""
    if type(requests) is not list or not 1 <= len(requests) <= 4:
        raise ValueError("invalid context requests")
    if not isinstance(question, str):
        raise ValueError("invalid current question")  # noqa: TRY004 - closed parser contract
    if frozenset(get_args(ScopeKey)) != SUPPRESSION_KEYS:
        raise ValueError("context scope registry mismatch")
    parsed = []
    seen = set()
    for item in requests:
        if isinstance(item, PersonalContextRequest):
            item = item.model_dump(exclude_unset=True)
        if isinstance(item, dict) and "reference" in item:
            raise ValueError("invalid context request")
        request = PersonalContextRequest.model_validate(item, strict=True)
        quote = request.target_quote
        if quote is not None and quote not in question:
            earlier = tuple(t for t in context if isinstance(t, str))[
                -_REFERENCE_TURNS:
            ]
            if not (
                _REFERRING.search(question)
                and any(quote.casefold() in t.casefold() for t in earlier)
            ):
                raise ValueError("context target is not current question text")
            request = request.model_copy(update={"reference": earlier})
        key = (request.scope_key, quote)
        if key in seen:
            raise ValueError("duplicate context request")
        seen.add(key)
        parsed.append(request)
    return tuple(parsed)


@dataclass(frozen=True)
class ScopedContextSnapshot:
    entries: tuple[tuple[SemanticAssertionRecord, str], ...]
    suppression: tuple[tuple[str, int, bool], ...]
    # (source_id, canonical_ref) for the entries, read in the same transaction.
    sources: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ContextProjection:
    status: str
    reason: str | None
    facts: tuple[dict[str, object], ...]
    selected: tuple[SemanticAssertionRecord, ...]
    scope_keys: tuple[str, ...]
    signature: str
    # Every requested scope's own outcome: "selected", "no_match" or
    # "clarification_required". A mixed request releases the matched scopes and
    # names the rest, so a partial result is never presented as complete.
    scope_results: tuple[tuple[str, str], ...] = ()
    # Paging (slice 1 PR C). ``total`` facts match the request; this page
    # starts at ``offset``; ``next_offset`` is None only when the list is
    # complete. ``omitted`` counts items on this page too large to release
    # whole. ``scope_counts`` is (scope, total, released_through) per scope.
    total: int = 0
    offset: int = 0
    next_offset: int | None = None
    omitted: int = 0
    scope_counts: tuple[tuple[str, int, int], ...] = ()

    @property
    def complete(self) -> bool:
        return self.next_offset is None and self.omitted == 0


def _json_default(value):
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    raise ValueError("unsupported context metadata")


def context_scope_signature(
    snapshot: ScopedContextSnapshot, scope_keys: tuple[str, ...]
) -> str:
    rows = sorted(
        (
            (scope, asdict(record))
            for record, scope in snapshot.entries
            if scope in scope_keys
        ),
        key=lambda pair: (pair[0], pair[1]["predicate"], pair[1]["assertion_id"]),
    )
    epochs = {k: (epoch, suppressed) for k, epoch, suppressed in snapshot.suppression}
    payload = [rows, [(k, *epochs.get(k, (0, False))) for k in sorted(scope_keys)]]
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
            default=_json_default,
        ).encode()
    ).hexdigest()


def only_additions_from_turn(
    before: ScopedContextSnapshot,
    after: ScopedContextSnapshot,
    scope_keys: tuple[str, ...],
    canonical_ref: str,
) -> bool:
    """Whether ``after`` differs from ``before`` within ``scope_keys`` only by
    new rows learned from ``canonical_ref`` (one accepted owner turn).

    Every looked-up row is still current and unchanged, nothing new replaces
    anything, and suppression for those scopes is the same. Any other
    difference - a correction, forget, retraction, disabled category, or a row
    from another turn or source - is not accepted."""
    keys = set(scope_keys)

    def rows(snapshot):
        return {
            record.assertion_id: asdict(record)
            for record, scope in snapshot.entries
            if scope in keys
        }

    def suppression(snapshot):
        return {k: (e, x) for k, e, x in snapshot.suppression if k in keys}

    if suppression(before) != suppression(after):
        return False
    old, new = rows(before), rows(after)
    if any(new.get(assertion) != row for assertion, row in old.items()):
        return False
    added = [row for assertion, row in new.items() if assertion not in old]
    references = dict(after.sources)
    return bool(added) and all(
        row["supersedes_id"] is None
        and references.get(row["source_id"]) == canonical_ref
        for row in added
    )


# Slice 1 PR C: a page holds at most 8 items or 3,000 bytes of facts,
# whichever comes first; an item is never cut.
PAGE_ITEMS = 8
PAGE_BYTES = 3000
RELEASED_STATES = frozenset(
    {
        "owned",
        "not_owned",
        "sold",
        "gave_away",
        "lost",
        "active",
        "completed",
        "planned",
        "cancelled",
    }
)
_ITEM_TIME_KEYS = ("expression", "precision", "earliest", "latest", "basis")
OVERSIZED = "item_exceeds_page_budget"


def _current_label(record, scope):
    value = record.value
    if (
        record.value_type is not ValueType.JSON
        or not isinstance(value, dict)
        or value.get("schema") != POLICY_VERSION
        or value.get("category") != scope.split(".")[0]
        or (
            scope.startswith("owned_item.") and value.get("kind") != scope.split(".")[1]
        )
    ):
        return None
    label = value.get("label")
    return (
        label
        if isinstance(label, str) and label.strip() and len(label) <= 240
        else None
    )


def _normalize_label(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _name_words(record, scope):
    """Word sets of a fact's names (its label and aliases)."""
    from .learning_catalog_page import name_words

    names = [_current_label(record, scope)]
    if isinstance(record.value, dict):
        names += [a for a in record.value.get("aliases") or () if isinstance(a, str)]
    return [w for w in (name_words(n) for n in names if n) if w]


def _referent(candidates, scope, quote, turns):
    """The single item a referring question means, from the owner's earlier
    turns only. Returns (items, None) or ([], reason).

    The referent is what the most recent earlier owner turn that names any
    item of this scope names (by a word that belongs to that item's names
    and to no other item's). It is released only when that turn names exactly
    one item and the model's quote names that same item; two named items ask
    which one was meant."""
    from .learning_catalog_page import name_words

    names = {r.assertion_id: _name_words(r, scope) for r in candidates}
    every = {r.assertion_id: set().union(*names[r.assertion_id]) for r in candidates}
    distinct = {
        r.assertion_id: {
            w
            for w in every[r.assertion_id]
            if len(w) >= 3
            and not any(w in every[o.assertion_id] for o in candidates if o is not r)
        }
        for r in candidates
    }
    mentioned = []
    for text in reversed(turns):
        words = name_words(text)
        mentioned = [r for r in candidates if distinct[r.assertion_id] & words]
        if mentioned:
            break
    wanted = name_words(quote)
    quoted = [
        r
        for r in candidates
        if wanted and any(wanted <= n for n in names[r.assertion_id])
    ]
    if len(mentioned) > 1:
        return [], "ambiguous_reference"
    if len(mentioned) == 1 and quoted == mentioned:
        return mentioned, None
    return [], "unresolved_target"


def _encoded_size(facts) -> int:
    return len(
        json.dumps(
            facts, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    )


def _owner_today(temporal, now):
    anchor = temporal.get("anchor_at") if isinstance(temporal, dict) else None
    zone = datetime.fromisoformat(anchor).tzinfo if isinstance(anchor, str) else None
    return now.astimezone(zone).date() if zone is not None else now.date()


def _sort_label(record, scope):
    label = _current_label(record, scope)
    return _normalize_label(label if label is not None else record.normalized_text)


def _released_fact(r, scope, ordinal, now):
    """One fact as released, or None when the stored row is not releasable."""
    from .personal_time import date_status

    if (
        r.subject_scope != "personal"
        or r.subject != "owner"
        or r.state is not AssertionState.ACTIVE
        or r.valid_to is not None
        or r.sensitivity is not Sensitivity.STANDARD
        or r.freshness_class is FreshnessClass.TIME_SENSITIVE
        or not isinstance(r.normalized_text, str)
        or not r.normalized_text
    ):
        return None
    text = r.normalized_text
    if r.value_type is ValueType.TEXT and r.predicate not in LEGACY_FACETS:
        if not isinstance(r.value, str) or not r.value:
            return None
        # Registered corrections retain scope, not the opaque display prefix.
        text = f"{scope}: {r.value}"
    fact = {
        "evidence_ref": ordinal,
        "scope_key": scope,
        "text": text,
        "recorded_at": _json_default(r.system_from),
        "freshness": "last_known",
    }
    if isinstance(r.value, dict) and r.value.get("schema") == POLICY_VERSION:
        state = r.value.get("state")
        if state not in RELEASED_STATES:
            return None
        fact["state"] = state
        for key in (
            "certainty",
            "temporal",
            "location",
            "reason",
            "aliases",
            "details",
            "plan_status",
            "slots",
        ):
            if key in r.value:
                fact[key] = r.value[key]
        for key in ("acquired", "disposed"):
            stated = r.value.get(key)
            if isinstance(stated, dict):
                fact[key] = {k: stated.get(k) for k in _ITEM_TIME_KEYS}
        temporal = fact.get("temporal")
        if isinstance(temporal, dict) and temporal.get("precision"):
            # Only the precision held is released; a passed window says
            # nothing about whether the plan happened.
            fact["temporal"] = {
                **temporal,
                "date_status": date_status(temporal, _owner_today(temporal, now)),
            }
    return fact


def _oversized_fact(fact, label):
    """An item larger than a whole page: released in a reduced, explicitly
    marked form that names it by its stored label when that is short (never
    cut mid-value, never an empty page). The omitted details are not
    summarized or guessed."""
    reduced = {
        key: fact[key]
        for key in ("evidence_ref", "scope_key", "state", "recorded_at", "freshness")
        if key in fact
    }
    if label is not None:
        reduced["label"] = label
    reduced["omitted"] = OVERSIZED
    return reduced


def project_personal_context(
    snapshot: ScopedContextSnapshot,
    requests: tuple[PersonalContextRequest, ...],
    *,
    offset: int = 0,
    now: datetime | None = None,
) -> ContextProjection:
    """One page of the requested scopes' current facts.

    Facts are ordered by scope, label, then assertion ID; ``offset`` counts
    facts already released for this question. The projection reports the
    total, how many this page holds, and the next offset, so a partial list is
    never presented as complete."""
    scopes = tuple(sorted({r.scope_key for r in requests}))
    now = now or datetime.now(UTC)

    outcome = {}

    def result(status, reason=None, facts=(), selected=(), signature="", **paging):
        return ContextProjection(
            status,
            reason,
            tuple(facts),
            tuple(selected),
            scopes,
            signature,
            ()
            if status == "unavailable"  # nothing was reliably checked
            else tuple((scope, outcome[scope]) for scope in scopes if scope in outcome),
            **paging,
        )

    def settle(scope, status):
        # Within one scope: clarification outranks a match, a match outranks none.
        rank = {"no_match": 0, "selected": 1, "clarification_required": 2}
        if rank[status] >= rank.get(outcome.get(scope), -1):
            outcome[scope] = status

    try:
        if type(offset) is not int or offset < 0:
            return result("unavailable", "storage_unavailable")
        chosen = {}
        clarification = None
        for request in requests:
            candidates = [
                r for r, scope in snapshot.entries if scope == request.scope_key
            ]
            if request.reference is not None:
                candidates, unclear = _referent(
                    candidates,
                    request.scope_key,
                    request.target_quote,
                    request.reference,
                )
                if unclear:
                    clarification = clarification or unclear
                    settle(request.scope_key, "clarification_required")
                    continue
            elif request.target_quote is not None:
                labels = [(r, _current_label(r, request.scope_key)) for r in candidates]
                candidates = [
                    r
                    for r, label in labels
                    if label is not None
                    and _normalize_label(label)
                    == _normalize_label(request.target_quote)
                ]
                unclear = None
                if len(candidates) > 1:
                    unclear = "ambiguous_target"
                elif not candidates and any(label is None for _, label in labels):
                    unclear = "unresolved_target"
                if unclear:
                    # That scope releases nothing; matched scopes still do.
                    clarification = clarification or unclear
                    settle(request.scope_key, "clarification_required")
                    continue
            settle(request.scope_key, "selected" if candidates else "no_match")
            for r in candidates:
                chosen[r.assertion_id] = (r, request.scope_key)
        chosen = {k: v for k, v in chosen.items() if outcome[v[1]] == "selected"}
        if not chosen:
            if clarification:
                return result("clarification_required", clarification)
            return result("no_match")
        ordered = sorted(
            chosen.values(),
            key=lambda pair: (
                pair[1],
                _sort_label(pair[0], pair[1]),
                pair[0].assertion_id,
            ),
        )
        total = len(ordered)
        if offset >= total:
            return result("unavailable", "storage_unavailable")
        facts = []
        selected = []
        omitted = 0
        for ordinal, (r, scope) in enumerate(ordered[offset:], start=offset + 1):
            if len(facts) >= PAGE_ITEMS:
                break
            fact = _released_fact(r, scope, ordinal, now)
            if fact is None:
                return result("unavailable", "storage_unavailable")
            if _encoded_size([*facts, fact]) > PAGE_BYTES:
                if facts:
                    break  # the page ends by bytes; the next page starts here
                fact = _oversized_fact(fact, _current_label(r, scope))
                if _encoded_size([fact]) > PAGE_BYTES:
                    return result("unavailable", "storage_unavailable")
                omitted += 1
            facts.append(fact)
            selected.append(r)
        released_through = offset + len(facts)
        per_scope = {}
        for index, (_, scope) in enumerate(ordered):
            entry = per_scope.setdefault(scope, [0, 0])
            entry[0] += 1
            if index < released_through:
                entry[1] += 1
        return result(
            "selected",
            facts=facts,
            selected=selected,
            signature=context_scope_signature(snapshot, scopes),
            total=total,
            offset=offset,
            next_offset=released_through if released_through < total else None,
            omitted=omitted,
            scope_counts=tuple(
                (scope, counts[0], counts[1])
                for scope, counts in sorted(per_scope.items())
            ),
        )
    except (TypeError, ValueError, AttributeError):
        return result("unavailable", "storage_unavailable")
