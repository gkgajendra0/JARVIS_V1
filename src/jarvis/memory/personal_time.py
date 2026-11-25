"""Owner-stated times with their actual precision (personal memory slice 1).

A time the owner states ("2021", "in March 2017", "last week", "on 14 March
2023") is kept as a *time object*:

    {"expression": <verbatim>, "precision": day|week|month|year|range|unresolved,
     "earliest": "YYYY-MM-DD" | None, "latest": "YYYY-MM-DD" | None,
     "anchor_at": <ISO datetime of the turn it was said in>, "basis": "stated"}

``earliest``/``latest`` are inclusive local calendar dates bounding exactly
what was said; nothing finer is invented. Relative phrases resolve against the
turn's local date and the owner's timezone (the turn's UTC offset). "Last
week" is the previous Monday-Sunday calendar week. Ambiguous phrases ("kal",
a bare month name, "around ...") stay ``unresolved`` with the expression.

One exception, only where the caller has supporting context that the time is
already past (see ``learning_reconciliation._item_fields``): with
``direction="past"`` a bare month name ("in October") is its most recent
occurrence on or before the told date (told 2026-11-20: October -> 2026-10;
November -> 2026-11). The wording is kept verbatim in ``expression`` and the
object's ``basis`` is ``"inferred_year"`` instead of ``"stated"``, so an
inferred year is never presented as one the owner said. A year the owner said
("October 2026") is ``basis="stated"`` with or without a direction. Plans and
events never use it, so "January" for a plan stays unresolved.

Only ``day`` precision maps to the timestamp validity columns, through
:func:`day_boundary` (start of that local day in UTC). That instant is an
internal boundary, not a known time of day: callers must present it with the
time object's day precision, never as a clock time. Every coarser or
unresolved time leaves validity unknown (NULL). When Jarvis *learned* a fact
is separate: the source's ``observed_at`` (``recorded_at`` in the temporal
context), never used as the event time.
"""

from __future__ import annotations

import calendar
import re
from datetime import UTC, date, datetime, time, timedelta

PRECISIONS = ("day", "week", "month", "year", "range", "unresolved")

_MONTHS = {
    name: index
    for index in range(1, 13)
    for name in (
        calendar.month_name[index].casefold(),
        calendar.month_abbr[index].casefold(),
    )
}
_MONTHS["sept"] = 9
_MONTH = "(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_YEAR = r"(1[89]\d\d|20\d\d|2100)"
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"

_DAY_WORDS = {
    "today": 0,
    "yesterday": -1,
    "tomorrow": 1,
    "day before yesterday": -2,
    "the day before yesterday": -2,
    "day after tomorrow": 2,
    "the day after tomorrow": 2,
    "aaj": 0,
    "aaj hi": 0,
    "आज": 0,
}
_RELATIVE_UNITS = {
    "last week": ("week", -1),
    "this week": ("week", 0),
    "next week": ("week", 1),
    "last month": ("month", -1),
    "this month": ("month", 0),
    "next month": ("month", 1),
    "last year": ("year", -1),
    "this year": ("year", 0),
    "next year": ("year", 1),
    "pichle hafte": ("week", -1),
    "pichhle hafte": ("week", -1),
    "is hafte": ("week", 0),
    "agle hafte": ("week", 1),
    "pichle mahine": ("month", -1),
    "pichhle mahine": ("month", -1),
    "is mahine": ("month", 0),
    "agle mahine": ("month", 1),
    "pichle saal": ("year", -1),
    "pichhle saal": ("year", -1),
    "is saal": ("year", 0),
    "agle saal": ("year", 1),
}
_PREFIXES = ("in ", "on ", "since ", "from ", "during ", "back in ")
# Hedges make any bound a guess: keep the words, claim no precision.
_HEDGES = ("around", "about", "approximately", "roughly", "sometime", "some time")


def _normalize(expression: str) -> str:
    text = " ".join(expression.casefold().replace(",", " ").split())
    changed = True
    while changed:
        changed = False
        for prefix in _PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix) :]
                changed = True
    return text


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + offset
    return index // 12, index % 12 + 1


def _valid_day(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _resolve(
    text: str, anchor: date, direction: str | None = None
) -> tuple[str, date | None, date | None]:
    if not text or any(text == h or text.startswith(h + " ") for h in _HEDGES):
        return "unresolved", None, None
    if direction == "past":
        match = re.fullmatch(_MONTH, text)
        if match:
            month = _MONTHS[match.group(1)]
            year = anchor.year if month <= anchor.month else anchor.year - 1
            return ("month", *_month_bounds(year, month))
    if text in _DAY_WORDS:
        day = anchor + timedelta(days=_DAY_WORDS[text])
        return "day", day, day
    if text in _RELATIVE_UNITS:
        unit, offset = _RELATIVE_UNITS[text]
        if unit == "week":
            monday = anchor - timedelta(days=anchor.weekday()) + timedelta(weeks=offset)
            return "week", monday, monday + timedelta(days=6)
        if unit == "month":
            year, month = _shift_month(anchor.year, anchor.month, offset)
            return ("month", *_month_bounds(year, month))
        year = anchor.year + offset
        return "year", date(year, 1, 1), date(year, 12, 31)
    match = re.fullmatch(r"(\d{1,3}) days? ago", text)
    if match:
        day = anchor - timedelta(days=int(match.group(1)))
        return "day", day, day
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        day = _valid_day(*(int(g) for g in match.groups()))
        return ("day", day, day) if day else ("unresolved", None, None)
    match = re.fullmatch(_DAY + r" (?:of )?" + _MONTH + " " + _YEAR, text)
    if match:
        day = _valid_day(
            int(match.group(3)), _MONTHS[match.group(2)], int(match.group(1))
        )
        return ("day", day, day) if day else ("unresolved", None, None)
    match = re.fullmatch(_MONTH + " " + _DAY + " " + _YEAR, text)
    if match:
        day = _valid_day(
            int(match.group(3)), _MONTHS[match.group(1)], int(match.group(2))
        )
        return ("day", day, day) if day else ("unresolved", None, None)
    match = re.fullmatch(_MONTH + " " + _YEAR, text)
    if match:
        return ("month", *_month_bounds(int(match.group(2)), _MONTHS[match.group(1)]))
    match = re.fullmatch(r"(last|this|next) " + _MONTH, text)
    if match:
        month = _MONTHS[match.group(2)]
        year = anchor.year
        if match.group(1) == "last" and month >= anchor.month:
            year -= 1
        elif match.group(1) == "next" and month <= anchor.month:
            year += 1
        return ("month", *_month_bounds(year, month))
    match = re.fullmatch(_YEAR, text)
    if match:
        year = int(match.group(1))
        return "year", date(year, 1, 1), date(year, 12, 31)
    match = re.fullmatch(r"(?:between )?(.+?) (?:and|to|until|till) (.+)", text)
    if match:
        first = _resolve(_normalize(match.group(1)), anchor)
        second = _resolve(_normalize(match.group(2)), anchor)
        if (
            first[0] not in ("unresolved", "range")
            and second[0] not in ("unresolved", "range")
            and first[1] <= second[2]
        ):
            return "range", first[1], second[2]
    return "unresolved", None, None


def time_object(
    expression: str | None, anchor_at: datetime, *, direction: str | None = None
) -> dict | None:
    """The owner-stated time with its actual precision, or None if none was said.

    ``direction="past"`` only for times that already happened (see module)."""
    if direction not in (None, "past"):
        raise ValueError("direction must be None or 'past'")
    if expression is None or not expression.strip():
        return None
    if anchor_at.tzinfo is None:
        raise ValueError("anchor_at must be timezone-aware")
    normalized = _normalize(expression)
    precision, earliest, latest = _resolve(normalized, anchor_at.date(), direction)
    inferred = direction == "past" and re.fullmatch(_MONTH, normalized) is not None
    return {
        "expression": expression,
        "precision": precision,
        "earliest": earliest.isoformat() if earliest else None,
        "latest": latest.isoformat() if latest else None,
        "anchor_at": anchor_at.isoformat(),
        "basis": "inferred_year" if inferred else "stated",
    }


def day_boundary(obj: dict | None) -> datetime | None:
    """Internal validity boundary for a *day-precision* time only.

    The start of that local day (owner's timezone, from the anchor) in UTC.
    It is not a known time of day; every other precision returns None so the
    validity column stays unknown instead of inventing precision."""
    if not obj or obj.get("precision") != "day" or not obj.get("earliest"):
        return None
    zone = datetime.fromisoformat(obj["anchor_at"]).tzinfo
    local = datetime.combine(date.fromisoformat(obj["earliest"]), time(0), tzinfo=zone)
    return local.astimezone(UTC)


def date_status(obj: dict | None, today: date) -> str:
    """Where a stated time stands relative to ``today`` (owner's local date).

    ``passed_outcome_unknown``: the whole stated window is over; whether the
    plan happened, changed or was cancelled is not known from the date."""
    if not obj or obj.get("precision") == "unresolved" or not obj.get("latest"):
        return "unknown"
    earliest = date.fromisoformat(obj["earliest"])
    latest = date.fromisoformat(obj["latest"])
    if latest < today:
        return "passed_outcome_unknown"
    if earliest <= today:
        return "in_window"
    return "upcoming"


def present(obj: dict | None) -> str | None:
    """Human wording at the precision held (never a clock time)."""
    if not obj:
        return None
    precision = obj.get("precision")
    earliest, latest = obj.get("earliest"), obj.get("latest")
    if precision == "unresolved" or not earliest:
        return obj.get("expression")
    first, last = date.fromisoformat(earliest), date.fromisoformat(latest)
    if precision == "day":
        return f"{first.day} {calendar.month_name[first.month]} {first.year}"
    if precision == "month":
        return f"{calendar.month_name[first.month]} {first.year}"
    if precision == "year":
        return str(first.year)
    return (
        f"{obj.get('expression')} (between {first.day} "
        f"{calendar.month_name[first.month]} {first.year} and {last.day} "
        f"{calendar.month_name[last.month]} {last.year})"
    )
