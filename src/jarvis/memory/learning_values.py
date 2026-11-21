"""Deterministic value rules for personal memory slice 1.

Structural only: nothing here decides meaning from keywords. The model
proposes; these rules enforce structure the application owns.
"""

from __future__ import annotations

import re

from .personal_time import time_object

QUOTE_CEILING = 500  # a ceiling, not a target
_QUOTE_JOIN = " … "

# Identifiers are excluded from item details in slice 1 (owner decision).
_PLATE = re.compile(r"\b[A-Z]{2}[\s-]?\d{1,2}[\s-]?[A-Z]{0,3}[\s-]?\d{4}\b")
_IDENTIFIER = re.compile(
    r"(?ix)"
    r"\b[a-hj-npr-z0-9]{17}\b"  # VIN-shaped
    r"|\b(?:serial|s/n|imei|chassis|engine\s+no)\b"
    r"|\b(?=[a-z0-9]*\d)(?=[a-z0-9]*[a-z])[a-z0-9]{10,}\b"  # long mixed code
)

SLOT_NAMES = ("destination", "when", "vehicle", "stay", "companions", "other")
PLAN_STATE = {
    "considering": "planned",
    "planned": "planned",
    "cancelled": "cancelled",
    "done": "completed",
}
DISPOSED_STATES = frozenset({"not_owned", "sold", "gave_away", "lost"})


def has_identifier(text: str | None) -> bool:
    return bool(text) and (
        _PLATE.search(text) is not None or _IDENTIFIER.search(text) is not None
    )


def normalized_slots(slots) -> dict[str, dict]:
    """Slots as stored. A slot with two or more options is undecided: its value
    is cleared and its certainty can never be confirmed. Options never touch
    the plan's own status."""
    stored = {}
    if slots is None:
        return stored
    for name in SLOT_NAMES:
        slot = getattr(slots, name)
        if slot is None:
            continue
        options = list(dict.fromkeys(o for o in slot.options if o))
        if len(options) >= 2:
            entry = {
                "value": None,
                "options": options,
                "certainty": "uncertain"
                if slot.certainty == "uncertain"
                else "tentative",
            }
        elif slot.value or options:
            entry = {
                "value": slot.value or options[0],
                "options": [],
                "certainty": slot.certainty,
            }
        else:
            continue
        stored[name] = entry
    return stored


def item_time(expression: str | None, anchor, *, past: bool = False) -> dict | None:
    """When an item was acquired or disposed of, at the precision said.

    ``past=True`` only when the caller has supporting context that the time
    already happened; a bare month then gets an inferred year, marked
    ``basis="inferred_year"`` (personal_time module). Otherwise a bare month
    stays unresolved with its wording."""
    if not expression:
        return None
    return time_object(expression, anchor, direction="past" if past else None)


def _clauses(fragment: str) -> list[str]:
    parts = re.split(r"(?<=[.!?;])\s+|\n+", fragment)
    return [p.strip() for p in parts if p.strip()]


def _without_others(clause: str, wanted: list[str], others: list[str]) -> str:
    """Where separable, keep only the comma/conjunction part of a clause that
    names this fact and none of the other facts from the same sentence."""
    if not any(o in clause.casefold() for o in others):
        return clause
    parts = [
        re.sub(r"^(?:and|aur)\s+", "", p.strip(" ,"), flags=re.IGNORECASE)
        for p in re.split(r",\s*|\s+(?:and|aur)\s+", clause)
        if p and p.strip(" ,")
    ]
    own = [
        p
        for p in parts
        if any(n in p.casefold() for n in wanted)
        and not any(o in p.casefold() for o in others)
    ]
    return ", ".join(own) if own else clause


def minimal_quote(
    fragments: list[str], needles: list[str], others: list[str] | None = None
) -> str | None:
    """The minimum supporting owner quote: only the clauses of the grounded
    evidence that contain the fact's own words, joined in order. 500
    characters is a ceiling; if even the shortest supporting clause exceeds
    it, no quote is kept."""
    wanted = [n.casefold() for n in needles if n]
    if not wanted:
        return None
    other_names = [
        o.casefold()
        for o in (others or [])
        if o and not any(o.casefold() in n or n in o.casefold() for n in wanted)
    ]
    chosen = []
    for fragment in fragments:
        for clause in _clauses(fragment):
            if any(n in clause.casefold() for n in wanted):
                clause = _without_others(clause, wanted, other_names)
                if clause not in chosen:
                    chosen.append(clause)
    if not chosen:
        return None
    quote = _QUOTE_JOIN.join(chosen)
    if len(quote) <= QUOTE_CEILING:
        return quote
    primary = wanted[0]
    single = sorted((c for c in chosen if primary in c.casefold()), key=len) or sorted(
        chosen, key=len
    )
    return single[0] if len(single[0]) <= QUOTE_CEILING else None


def _within(new: dict, old: dict) -> bool:
    """A refined time must be the same or finer and inside the old bounds."""
    if old.get("precision") in (None, "unresolved") or not old.get("earliest"):
        return True
    if new.get("precision") in (None, "unresolved") or not new.get("earliest"):
        return False
    return old["earliest"] <= new["earliest"] and new["latest"] <= old["latest"]


def _option_key(text) -> str:
    return " ".join(str(text).casefold().split())


def decides_stated_options(old: dict, added: dict) -> bool:
    """True when the only disagreement between a stored plan and new detail is
    a decision among alternatives the owner already stated: a stored slot with
    no value and options, and a new value that is one of those options ("Ladakh
    or winter Spiti" -> "winter Spiti"). That is a real change of the plan
    (the earlier row, with its options, stays in history), never a refine and
    never a conflict. Any other disagreement keeps its existing handling."""
    old_slots = old.get("slots") or {}
    rest = {}
    decided = False
    for name, slot in (added.get("slots") or {}).items():
        current = old_slots.get(name)
        if current is None or current == slot:
            rest[name] = slot
            continue
        options = {_option_key(o) for o in current.get("options") or () if o}
        value = slot.get("value")
        if not current.get("value") and value and _option_key(value) in options:
            decided = True
            continue
        return False
    if not decided:
        return False
    merged, reason = refine_merge(old, {**added, "slots": rest})
    return merged is not None or reason == "already_stored"


def refine_merge(old: dict, added: dict) -> tuple[dict | None, str]:
    """Merge detail into a true-but-less-complete stored value.

    Returns (merged, "") when something consistent was added, (None,
    "already_stored") when nothing new was said, or (None, reason) when the
    new detail contradicts the stored one (that is a correction or a real
    change, never a refine)."""
    merged = dict(old)
    changed = False
    aliases = list(old.get("aliases") or [])
    for alias in added.get("aliases") or []:
        if (
            alias.casefold() not in {a.casefold() for a in aliases}
            and alias.casefold() != str(old.get("label", "")).casefold()
        ):
            aliases.append(alias)
            changed = True
    if aliases:
        merged["aliases"] = aliases[:8]
    details = added.get("details")
    if details:
        current = old.get("details")
        if not current:
            merged["details"] = details
            changed = True
        elif details.casefold() != current.casefold():
            if current.casefold() in details.casefold():
                merged["details"] = details
                changed = True
            else:
                return None, "refine_conflicts_existing_detail"
    for key in ("acquired", "disposed"):
        new_time = added.get(key)
        if not new_time:
            continue
        current = old.get(key)
        if not current:
            merged[key] = new_time
            changed = True
        elif (current.get("earliest"), current.get("latest")) == (
            new_time.get("earliest"),
            new_time.get("latest"),
        ) and current.get("precision") == new_time.get("precision"):
            continue
        elif _within(new_time, current):
            merged[key] = new_time
            changed = True
        else:
            return None, "refine_conflicts_existing_detail"
    slots = dict(old.get("slots") or {})
    for name, slot in (added.get("slots") or {}).items():
        if name not in slots:
            slots[name] = slot
            changed = True
        elif slots[name] != slot:
            # Deciding or changing a plan detail is a real change, not a refine.
            return None, "refine_conflicts_existing_detail"
    if slots:
        merged["slots"] = slots
    return (merged, "") if changed else (None, "already_stored")
