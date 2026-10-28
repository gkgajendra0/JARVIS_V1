"""Anchor user date expressions to their accepted turn, never to retrieval time."""

from datetime import date, timedelta

HISTORY_CATEGORIES = frozenset({"personal_fact", "activity", "event", "plan"})


def temporal_context(source, candidate):
    recorded = source.turns[-1].accepted_at.astimezone()
    anchor = recorded
    expression = candidate.time_expression
    if expression:
        turns = {turn.turn_id: turn for turn in source.turns}
        quoted = [
            turns[span.turn_id]
            for span in candidate.evidence
            if span.turn_id in turns
            and expression in turns[span.turn_id].text[span.start : span.end]
        ]
        if quoted:
            anchor = max(
                quoted, key=lambda turn: turn.accepted_at
            ).accepted_at.astimezone()
    normalized = expression.casefold().strip() if expression else ""
    offsets = {
        "today": 0,
        "yesterday": -1,
        "tomorrow": 1,
        "aaj": 0,
        "aaj hi": 0,
        "आज": 0,
    }
    resolved = None
    if normalized in offsets:
        resolved = (anchor.date() + timedelta(days=offsets[normalized])).isoformat()
    elif expression:
        try:
            resolved = date.fromisoformat(expression).isoformat()
        except ValueError:
            pass  # Keep ambiguous 'kal', 'next month', etc. anchored but unresolved.
    return {
        "expression": expression,
        "date": resolved,
        "recorded_at": recorded.isoformat(),
        "anchor_at": anchor.isoformat(),
        "local_date": anchor.date().isoformat(),
    }


def occurrence_matches(entry, candidate, source):
    if candidate.category not in {"event", "activity", "plan"}:
        return True
    import json

    try:
        old = json.loads(entry.value).get("temporal", {})
    except (ValueError, AttributeError):
        return False
    new = temporal_context(source, candidate)
    if old.get("date") or new["date"]:
        return old.get("date") == new["date"]
    return (old.get("expression"), old.get("local_date")) == (
        new["expression"],
        new["local_date"],
    )
