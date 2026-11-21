"""Owner-stated times keep their real precision; only a known day maps to a
validity boundary, and that boundary is never presented as a clock time."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from jarvis.memory.personal_time import date_status, day_boundary, present, time_object

IST = timezone(timedelta(hours=5, minutes=30))


def at(y, m, d, hh=12, mm=0, tz=IST):
    return datetime(y, m, d, hh, mm, tzinfo=tz)


@pytest.mark.parametrize(
    "expression,anchor,precision,earliest,latest",
    [
        # Day precision.
        ("on 14 March 2023", at(2026, 11, 20), "day", "2023-03-14", "2023-03-14"),
        ("14th March 2023", at(2026, 11, 20), "day", "2023-03-14", "2023-03-14"),
        ("March 14, 2023", at(2026, 11, 20), "day", "2023-03-14", "2023-03-14"),
        ("2023-03-14", at(2026, 11, 20), "day", "2023-03-14", "2023-03-14"),
        ("yesterday", at(2026, 11, 20), "day", "2026-11-19", "2026-11-19"),
        ("Today", at(2026, 11, 20), "day", "2026-11-20", "2026-11-20"),
        ("aaj", at(2026, 11, 20), "day", "2026-11-20", "2026-11-20"),
        ("3 days ago", at(2026, 11, 20), "day", "2026-11-17", "2026-11-17"),
        # "Last week": previous Monday-Sunday calendar week (owner's timezone).
        ("last week", at(2026, 11, 18), "week", "2026-11-09", "2026-11-15"),  # Wed
        ("last week", at(2026, 11, 22), "week", "2026-11-09", "2026-11-15"),  # Sun
        ("last week", at(2026, 11, 23), "week", "2026-11-16", "2026-11-22"),  # Mon
        ("last week", at(2026, 12, 2), "week", "2026-11-23", "2026-11-29"),
        ("last week", at(2027, 1, 6), "week", "2026-12-28", "2027-01-03"),  # year
        ("pichle hafte", at(2026, 11, 18), "week", "2026-11-09", "2026-11-15"),
        ("next week", at(2026, 11, 18), "week", "2026-11-23", "2026-11-29"),
        # Month precision.
        ("in March 2017", at(2026, 11, 20), "month", "2017-03-01", "2017-03-31"),
        ("Feb 2024", at(2026, 11, 20), "month", "2024-02-01", "2024-02-29"),
        ("last month", at(2026, 11, 17), "month", "2026-10-01", "2026-10-31"),
        ("last month", at(2026, 1, 10), "month", "2025-12-01", "2025-12-31"),
        ("since this August", at(2026, 11, 20), "month", "2026-08-01", "2026-08-31"),
        ("last March", at(2026, 3, 10), "month", "2025-03-01", "2025-03-31"),
        ("last March", at(2026, 11, 20), "month", "2026-03-01", "2026-03-31"),
        ("next January", at(2026, 11, 20), "month", "2027-01-01", "2027-01-31"),
        ("agle mahine", at(2026, 11, 20), "month", "2026-12-01", "2026-12-31"),
        # Year precision.
        ("2021", at(2026, 11, 20), "year", "2021-01-01", "2021-12-31"),
        ("in 2019", at(2026, 11, 20), "year", "2019-01-01", "2019-12-31"),
        ("next year", at(2026, 11, 20), "year", "2027-01-01", "2027-12-31"),
        # Ranges.
        (
            "between March 2023 and June 2023",
            at(2026, 11, 20),
            "range",
            "2023-03-01",
            "2023-06-30",
        ),
        ("from 2019 to 2021", at(2026, 11, 20), "range", "2019-01-01", "2021-12-31"),
        # Unresolved: ambiguous, hedged, bare month, impossible, reversed.
        ("kal", at(2026, 11, 20), "unresolved", None, None),
        ("in August", at(2026, 11, 20), "unresolved", None, None),
        ("around March 2017", at(2026, 11, 20), "unresolved", None, None),
        ("recently", at(2026, 11, 20), "unresolved", None, None),
        ("a while ago", at(2026, 11, 20), "unresolved", None, None),
        ("31 February 2023", at(2026, 11, 20), "unresolved", None, None),
        ("between 2021 and 2019", at(2026, 11, 20), "unresolved", None, None),
        ("between Diwali and New Year", at(2026, 11, 20), "unresolved", None, None),
    ],
)
def test_calendar_resolution_keeps_actual_precision(
    expression, anchor, precision, earliest, latest
):
    obj = time_object(expression, anchor)
    assert obj["expression"] == expression  # verbatim
    assert obj["anchor_at"] == anchor.isoformat()
    assert obj["basis"] == "stated"
    assert (obj["precision"], obj["earliest"], obj["latest"]) == (
        precision,
        earliest,
        latest,
    )


def test_relative_dates_resolve_in_the_owners_timezone_near_midnight():
    # 00:30 IST on Monday 23 Nov is still Sunday 22 Nov in UTC.
    local = datetime(2026, 11, 23, 0, 30, tzinfo=IST)
    assert time_object("last week", local)["earliest"] == "2026-11-16"
    assert time_object("yesterday", local)["earliest"] == "2026-11-22"
    utc = local.astimezone(UTC)
    assert time_object("last week", utc)["earliest"] == "2026-11-09"


def test_nothing_said_is_no_time_object():
    assert time_object(None, at(2026, 11, 20)) is None
    assert time_object("  ", at(2026, 11, 20)) is None
    with pytest.raises(ValueError):
        time_object("2021", datetime(2026, 11, 20, 12))  # noqa: DTZ001 - naive anchor refused


@pytest.mark.parametrize(
    "expression",
    ["2021", "in March 2017", "last week", "between 2019 and 2021", "kal"],
)
def test_only_a_known_day_maps_to_a_validity_boundary(expression):
    assert day_boundary(time_object(expression, at(2026, 11, 18))) is None


def test_day_boundary_is_local_day_start_in_utc_not_a_known_time():
    obj = time_object("on 14 March 2023", at(2026, 11, 20, 21, 47))
    boundary = day_boundary(obj)
    assert boundary == datetime(2023, 3, 13, 18, 30, tzinfo=UTC)  # 00:00 IST
    # Presentation keeps day precision: no clock time, and not the told time.
    text = present(obj)
    assert text == "14 March 2023"
    assert ":" not in text and "18" not in text and "21" not in text
    assert day_boundary(None) is None


@pytest.mark.parametrize(
    "expression,wording",
    [
        ("in March 2017", "March 2017"),
        ("2021", "2021"),
        ("kal", "kal"),
        ("last week", "last week (between 9 November 2026 and 15 November 2026)"),
    ],
)
def test_presentation_states_only_the_precision_held(expression, wording):
    assert present(time_object(expression, at(2026, 11, 18))) == wording


@pytest.mark.parametrize(
    "expression,today,status",
    [
        ("in October 2026", date(2026, 11, 20), "passed_outcome_unknown"),
        ("last week", date(2026, 11, 20), "passed_outcome_unknown"),
        ("this month", date(2026, 11, 20), "in_window"),
        ("next January", date(2026, 11, 20), "upcoming"),
        ("kal", date(2026, 11, 20), "unknown"),
    ],
)
def test_elapsed_dates_are_never_assumed_done_or_upcoming(expression, today, status):
    assert date_status(time_object(expression, at(2026, 11, 18)), today) == status
    assert date_status(None, today) == "unknown"


@pytest.mark.parametrize(
    "expression,anchor,earliest,latest",
    [
        # Frozen D23: "I sold the Classic 350 in October." told 2026-11-20.
        ("October", at(2026, 11, 20), "2026-10-01", "2026-10-31"),
        ("in October", at(2026, 11, 20), "2026-10-01", "2026-10-31"),
        # Frozen D12: "the Jimny is from September" told 2026-11-19.
        ("September", at(2026, 11, 19), "2026-09-01", "2026-09-30"),
        # The told month itself, and a later month name means last year.
        ("November", at(2026, 11, 20), "2026-11-01", "2026-11-30"),
        ("December", at(2026, 11, 20), "2025-12-01", "2025-12-31"),
        ("Sept", at(2026, 1, 5), "2025-09-01", "2025-09-30"),
    ],
)
def test_bare_month_for_a_past_item_time_is_its_latest_occurrence(
    expression, anchor, earliest, latest
):
    stated = time_object(expression, anchor, direction="past")
    assert (stated["precision"], stated["earliest"], stated["latest"]) == (
        "month",
        earliest,
        latest,
    )
    assert stated["expression"] == expression  # wording kept verbatim
    assert stated["basis"] == "inferred_year"  # the year was not said


@pytest.mark.parametrize("expression", ["January", "October", "around March", "kal"])
def test_bare_month_stays_unresolved_without_a_past_direction(expression):
    assert time_object(expression, at(2026, 11, 20))["precision"] == "unresolved"


def test_past_direction_never_changes_other_wording():
    anchor = at(2026, 11, 18)
    for expression in ("last week", "2021", "March 2017", "around March", "kal"):
        assert time_object(expression, anchor, direction="past") == time_object(
            expression, anchor
        )
    with pytest.raises(ValueError):
        time_object("October", anchor, direction="future")


@pytest.mark.parametrize(
    "expression,precision",
    [
        ("October 2025", "month"),
        ("2021", "year"),
        ("last week", "week"),
        ("March 2017", "month"),
    ],
)
def test_a_stated_year_or_relative_time_is_never_marked_inferred(expression, precision):
    stated = time_object(expression, at(2026, 11, 20), direction="past")
    assert stated["basis"] == "stated" and stated["precision"] == precision


def test_bare_month_without_past_context_keeps_wording_and_no_year():
    stated = time_object("September", at(2026, 11, 20))
    assert stated["expression"] == "September"
    assert (stated["precision"], stated["earliest"], stated["latest"]) == (
        "unresolved",
        None,
        None,
    )
    assert stated["basis"] == "stated"
