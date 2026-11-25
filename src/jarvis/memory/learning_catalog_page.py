"""Bounded learning catalog at scale (personal memory slice 1, PR C).

The resolver compares each proposed fact with existing facts of the same
category. A category with at most :data:`CANDIDATE_LIMIT` current facts is
supplied whole, exactly as before. A larger category is narrowed per proposal
by a deterministic lexical match: the proposal's label and aliases against
each stored fact's label, aliases and details:

- words are compared after the same surface normalization storage uses;
- a word that appears in more than :data:`CANDIDATE_LIMIT` facts of that
  category does not distinguish anything, so it is ignored (document
  frequency, computed from the owner's own facts; no keyword list);
- a fact with exactly the proposal's label is always included.

When a proposal still matches more than :data:`CANDIDATE_LIMIT` facts, or has
no distinguishing word at all while its category is larger than the limit,
the identity cannot be resolved from a bounded page. That proposal alone is
skipped and recorded as ``catalog_page_ambiguous``; nothing is guessed.
Legacy entries (a fixed, small set of facets) are always supplied for the
existing overlap guards.
"""

from __future__ import annotations

import json
import re

from .service import normalize_memory_surface

CANDIDATE_LIMIT = 32
CATALOG_LIMIT = 96
PAGE_AMBIGUOUS = "catalog_page_ambiguous"
# Head nouns that say what kind of plan or event something is, not which one
# ("the Spiti trip" names the plan called "winter Spiti"). Shared by learning
# (does a proposal name a stored plan?) and retrieval (target lookups).
PLAN_HEAD_NOUNS = frozenset(
    {
        "plan",
        "plans",
        "trip",
        "trips",
        "journey",
        "holiday",
        "holidays",
        "vacation",
        "tour",
        "visit",
        "outing",
        "yatra",
        "safar",
    }
)

# Words that describe a whole category rather than name an item in it ("my
# bike", "the trip"). Retrieval ignores them when narrowing to a named item; a
# quote made only of them names no item and so does not narrow the category.
# General category vocabulary, not aliases of any stored item.
CATEGORY_HEAD_NOUNS = {
    "plan": PLAN_HEAD_NOUNS,
    "event": PLAN_HEAD_NOUNS | {"event", "events"},
    "owned_item.vehicle": frozenset(
        {
            "vehicle",
            "vehicles",
            "car",
            "cars",
            "bike",
            "bikes",
            "motorbike",
            "motorbikes",
            "motorcycle",
            "motorcycles",
            "scooter",
            "scooters",
            "scooty",
            "gaadi",
            "gadi",
        }
    ),
    "owned_item.device": frozenset(
        {
            "device",
            "devices",
            "gadget",
            "gadgets",
            "phone",
            "phones",
            "mobile",
            "laptop",
            "laptops",
            "tablet",
            "tablets",
            "computer",
        }
    ),
}

_WORD = re.compile(r"\w+", re.UNICODE)


def _words(text) -> set[str]:
    if not isinstance(text, str) or not text:
        return set()
    return {
        w
        for w in _WORD.findall(normalize_memory_surface(text))
        if len(w) >= 2 or w.isdigit()
    }


def name_words(text) -> set[str]:
    """Normalized words of a name or utterance (public form of _words)."""
    return _words(text)


def _loaded(entry):
    try:
        value = json.loads(entry.value)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def identity_words(entry) -> list[set[str]]:
    """Word sets of a stored fact's names: its label and each alias."""
    value = _loaded(entry)
    if value is None:
        return []
    names = [value.get("label")] + list(value.get("aliases") or ())
    return [w for w in (_words(n) for n in names if isinstance(n, str)) if w]


def unique_reference(entry, label, entries) -> bool:
    """True when ``label`` names ``entry`` and no other fact of its category
    and kind: the label's words are all contained in one of the entry's names
    ("Tigor" -> "Tata Tigor"), and in no other entry's names."""
    wanted = _words(label)
    if not wanted:
        return False

    def names(e):
        return any(wanted <= words for words in identity_words(e))

    if not names(entry):
        return False
    return not any(
        names(other)
        for other in entries
        if other.assertion_id != entry.assertion_id
        and other.category == entry.category
        and other.kind == entry.kind
    )


def entry_words(entry) -> set[str]:
    try:
        value = json.loads(entry.value)
    except (TypeError, ValueError):
        value = entry.value
    if not isinstance(value, dict):
        return _words(str(value))
    words = _words(value.get("label")) | _words(value.get("details"))
    for alias in value.get("aliases") or ():
        words |= _words(alias)
    return words


def _entry_label(entry):
    try:
        value = json.loads(entry.value)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get("label"), str):
        return None
    return normalize_memory_surface(value["label"])


def candidate_words(candidate) -> set[str]:
    """Identity words of a proposal: its label and aliases. Its details are
    what it adds, not who it is, so they never select a target."""
    words = _words(candidate.label)
    for alias in getattr(candidate, "aliases", None) or ():
        words |= _words(alias)
    return words


def _group(entry) -> tuple[str, str]:
    return entry.category, entry.kind


def bounded_entries(entries, candidates, scalar_facets):
    """Return (entries to supply, candidate indices skipped as ambiguous).

    ``entries`` are all current catalog entries; ``candidates`` the proposals.
    Order is deterministic: legacy first, then by predicate and assertion ID.
    """
    ordered = sorted(entries, key=lambda e: (e.predicate, e.assertion_id))
    legacy = [e for e in ordered if e.category == "legacy"]
    groups: dict[tuple[str, str], list] = {}
    for entry in ordered:
        if entry.category != "legacy":
            groups.setdefault(_group(entry), []).append(entry)
    chosen: dict[str, object] = {e.assertion_id: e for e in legacy}
    skipped: list[int] = []
    for index, candidate in enumerate(candidates):
        kind = candidate.kind if candidate.category == "owned_item" else "other"
        if candidate.category in scalar_facets:
            group = [e for e in ordered if e.category == candidate.category]
        else:
            group = groups.get((candidate.category, kind), [])
        if len(group) <= CANDIDATE_LIMIT:
            picked = group
        else:
            words_by_entry = {e.assertion_id: entry_words(e) for e in group}
            frequency: dict[str, int] = {}
            for words in words_by_entry.values():
                for word in words:
                    frequency[word] = frequency.get(word, 0) + 1
            wanted = {
                w
                for w in candidate_words(candidate)
                if frequency.get(w, 0) <= CANDIDATE_LIMIT
            }
            label = normalize_memory_surface(candidate.label or "")
            picked = [
                e
                for e in group
                if (label and _entry_label(e) == label)
                or (wanted & words_by_entry[e.assertion_id])
            ]
            if not picked and not wanted:
                skipped.append(index)
                continue
            if len(picked) > CANDIDATE_LIMIT:
                skipped.append(index)
                continue
        additions = [e for e in picked if e.assertion_id not in chosen]
        if len(chosen) + len(additions) > CATALOG_LIMIT:
            skipped.append(index)
            continue
        for entry in additions:
            chosen[entry.assertion_id] = entry
    supplied = sorted(
        chosen.values(),
        key=lambda e: (e.category != "legacy", e.predicate, e.assertion_id),
    )
    return supplied, tuple(skipped)
