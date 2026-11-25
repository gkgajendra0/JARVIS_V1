"""Anchor user date expressions to their accepted turn, never to retrieval time."""

from .personal_time import time_object

HISTORY_CATEGORIES = frozenset({"personal_fact", "activity", "event", "plan"})
# Categories whose stored record carries certainty, so a possibility can be
# kept as a possibility. In every other category (possessions, single-value
# preferences) a possibility is not saved: it would read as a current fact.
POSSIBILITY_CATEGORIES = HISTORY_CATEGORIES | frozenset({"routine", "goal"})


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
    stated = time_object(expression, anchor)
    # ``date`` keeps its meaning: a resolved single day, else None. Coarser
    # times keep their real precision and bounds; ambiguous ones ('kal', a
    # bare month) stay anchored but unresolved.
    resolved = stated["earliest"] if stated and stated["precision"] == "day" else None
    context = {
        "expression": expression,
        "date": resolved,
        "recorded_at": recorded.isoformat(),
        "anchor_at": anchor.isoformat(),
        "local_date": anchor.date().isoformat(),
    }
    if stated:
        context.update(
            precision=stated["precision"],
            earliest=stated["earliest"],
            latest=stated["latest"],
        )
    return context


def occurrence_matches(entry, candidate, source):
    if candidate.category not in {"event", "activity", "plan"}:
        return True
    import json

    try:
        old = json.loads(entry.value).get("temporal", {})
    except (ValueError, AttributeError):
        return False
    new = temporal_context(source, candidate)
    old_date = _resolved_day(old)
    if old_date or new["date"]:
        return old_date == new["date"]
    return (old.get("expression"), old.get("local_date")) == (
        new["expression"],
        new["local_date"],
    )


def _resolved_day(temporal):
    """The stored day, re-resolved under the current rules when it was saved
    before they resolved that wording (no duplicate occurrence for the same
    stated day)."""
    if not isinstance(temporal, dict):
        return None
    if temporal.get("date"):
        return temporal["date"]
    expression, anchor = temporal.get("expression"), temporal.get("anchor_at")
    if not expression or not anchor:
        return None
    from datetime import datetime

    try:
        stated = time_object(expression, datetime.fromisoformat(anchor))
    except ValueError:
        return None
    return stated["earliest"] if stated and stated["precision"] == "day" else None
