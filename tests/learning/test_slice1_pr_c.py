"""Personal memory slice 1, PR C: scale, paging and question-bound pages.

Offline, fictional data only. Covers D18-D20 and D25 at the release level,
page-token binding, an item larger than a whole page, the bounded learning
catalog, the new released fields, and a 500-row performance check. Answer
wording is graded in the isolated text acceptance, not here.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from time import perf_counter
from uuid import uuid4

import pytest
from context_query_helpers import context_session, seed_item
from test_slice1_pr_b import Owner, item

from jarvis.conversation import ConversationRole
from jarvis.memory.learning_catalog_page import (
    CANDIDATE_LIMIT,
    PAGE_AMBIGUOUS,
    bounded_entries,
)
from jarvis.memory.learning_contracts import LearningCatalogEntry
from jarvis.memory.learning_policy import SCALAR_FACETS
from jarvis.memory.personal_context_projection import (
    PAGE_BYTES,
    parse_context_requests,
    project_personal_context,
)
from jarvis.memory.query import CanonicalMemoryReader
from jarvis.memory.retrieval import SemanticRetrievalService

VEHICLES = [{"scope_key": "owned_item.vehicle"}]
PLANS = [{"scope_key": "plan"}]


async def seed_vehicles(h, count, *, prefix="Vehicle", details=None):
    seeded = []
    for i in range(count):
        record = await seed_item(h, f"{prefix} {i:02d}")
        if details is not None:
            record = await _with_details(h, record, details(i))
        seeded.append(record)
    return seeded


async def _with_details(h, record, details):
    template = h.plan.mutations[0]
    value = {**record.value, "details": details}
    draft = replace(
        template.draft,
        predicate=f"owned_item_{uuid4().hex}",
        value=value,
        normalized_text=f"{value['label']}; {details}; state=owned",
    )
    source = replace(template.source, source_id=str(uuid4()), evidence_text=None)
    await h.lifecycle.forget(record.assertion_id, source)
    return await h.lifecycle.create(draft, replace(source, source_id=str(uuid4())))


async def seed_plan(h, label, *, earliest=None, latest=None, precision=None):
    template = h.plan.mutations[0]
    temporal = {
        "expression": None,
        "date": None,
        "recorded_at": "2026-11-01T10:00:00+05:30",
    }
    if precision:
        temporal.update(
            expression=label,
            precision=precision,
            earliest=earliest,
            latest=latest,
            anchor_at="2026-11-01T10:00:00+05:30",
        )
    value = {
        "schema": template.draft.value["schema"],
        "category": "plan",
        "kind": "other",
        "label": label,
        "value": label,
        "state": "planned",
        "certainty": "tentative",
        "temporal": temporal,
    }
    draft = replace(
        template.draft,
        predicate=f"plan_{uuid4().hex}",
        value=value,
        normalized_text=f"{label}; state=planned",
    )
    source = replace(template.source, source_id=str(uuid4()), evidence_text=None)
    return await h.lifecycle.create(draft, source)


def labels(result):
    return [f.get("text", f.get("label")) for f in result["facts"]]


async def page_through(session, requests, first):
    pages = [first]
    while "next_page" in pages[-1]["paging"]:
        pages.append(
            await session.query_for_question(requests, pages[-1]["paging"]["next_page"])
        )
        assert pages[-1]["status"] == "selected", pages[-1]
    return pages


# D18: scale beyond one page ----------------------------------------------------


@pytest.mark.asyncio
async def test_d18_eleven_vehicles_page_truthfully_then_all_are_named(learning):
    await seed_vehicles(learning, 11)
    async with context_session(learning, "Which vehicles do I own?") as (s, _, _):
        first = await s.query_for_question(VEHICLES)
        paging = first["paging"]
        assert first["status"] == "selected"
        assert paging["total"] == 11 and paging["complete"] is False
        assert paging["this_page"] == {"from": 1, "to": 8}
        assert len(first["facts"]) == 8 and "next_page" in paging
        assert "11 saved; here are 8" in paging["list_rule"]
        assert paging["scopes"]["owned_item.vehicle"] == {
            "total": 11,
            "released_through": 8,
            "complete": False,
        }
        pages = await page_through(s, VEHICLES, first)
        assert len(pages) == 2
        last = pages[-1]["paging"]
        assert last["complete"] is True and last["this_page"] == {"from": 9, "to": 11}
        named = [t.split(";")[0] for p in pages for t in labels(p)]
        assert named == [f"Vehicle {i:02d}" for i in range(11)]
        refs = [f["evidence_ref"] for p in pages for f in p["facts"]]
        assert refs == list(range(1, 12))


# D19: more than 32 rows in storage -----------------------------------------------


@pytest.mark.asyncio
async def test_d19_ninety_rows_learning_resolves_and_lookup_is_truthful(learning):
    for i in range(45):
        await seed_plan(learning, f"Trip to Harbourtown {i:02d}")
    for i in range(45):
        await seed_item(learning, f"Gadget {i:02d}", "device")
    owner = Owner(learning)
    text = "I bought a Brightwave scooter."
    plan, result, _ = await owner.say(
        text,
        [item("Brightwave scooter", ["a Brightwave scooter"])],
        [("new", None)],
    )
    assert result is not None and result.status == "committed"
    assert not plan.outcomes
    async with context_session(learning, "What plans do I have?") as (s, _, _):
        first = await s.query_for_question(PLANS)
        assert first["status"] == "selected"
        assert first["paging"]["total"] == 45
        assert first["paging"]["complete"] is False
        assert "45 saved" in first["paging"]["list_rule"]
    async with context_session(learning, "Which vehicles do I own?") as (s, _, _):
        vehicles = await s.query_for_question(VEHICLES)
        assert vehicles["paging"]["complete"] is True
        assert any("Brightwave scooter" in t for t in labels(vehicles))


# D20: byte budget -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_d20_page_ends_by_bytes_and_never_cuts_an_item(learning):
    long = "fictional touring kit, panniers and a tall screen " * 6  # ~300 chars
    await seed_vehicles(learning, 6, prefix="Tourer", details=lambda i: f"{i} {long}")
    async with context_session(learning, "Which vehicles do I own?") as (s, _, _):
        first = await s.query_for_question(VEHICLES)
        released = first["facts"]
        assert 0 < len(released) < 6
        encoded = json.dumps(released, ensure_ascii=False, separators=(",", ":"))
        assert len(encoded.encode()) <= PAGE_BYTES
        assert first["paging"]["complete"] is False and "next_page" in first["paging"]
        for fact in released:
            assert fact["details"].endswith(long) and "omitted" not in fact
        pages = await page_through(s, VEHICLES, first)
        assert sum(len(p["facts"]) for p in pages) == 6
        assert pages[-1]["paging"]["complete"] is True


# D25: pages run out ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_d25_forty_vehicles_release_four_pages_then_say_more_remain(learning):
    await seed_vehicles(learning, 40)
    async with context_session(learning, "List all my vehicles.") as (s, _, _):
        first = await s.query_for_question(VEHICLES)
        pages = await page_through(s, VEHICLES, first)
        assert len(pages) == 4  # the first page plus 3 extra pages
        assert sum(len(p["facts"]) for p in pages) == 32
        last = pages[-1]["paging"]
        assert last["more_remaining"] is True and "next_page" not in last
        assert last["total"] == 40 and last["complete"] is False
        assert "total 40" in last["list_rule"]
        # Every page belonged to the same question permit.
        assert s._extra_pages == 3
        replay = await s.query_for_question(VEHICLES, pages[1]["paging"]["next_page"])
        assert replay["status"] == "invalid_page_token"


# Page-token binding ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_page_token_is_refused_for_another_question(learning):
    await seed_vehicles(learning, 11)
    async with context_session(learning, "Which vehicles do I own?") as (s, _, _):
        token = (await s.query_for_question(VEHICLES))["paging"]["next_page"]
    async with context_session(learning, "Which vehicles do I own?") as (s, _, _):
        await s.query_for_question(VEHICLES)
        refused = await s.query_for_question(VEHICLES, token)
        assert refused["status"] == "invalid_page_token" and not refused["facts"]
        assert refused["lookup"] == "not_completed"


@pytest.mark.asyncio
async def test_page_token_is_refused_for_other_requests_or_tampering(learning):
    await seed_vehicles(learning, 11)
    async with context_session(learning, "Which vehicles do I own?") as (s, _, _):
        token = (await s.query_for_question(VEHICLES))["paging"]["next_page"]
        other = [{"scope_key": "owned_item.vehicle"}, {"scope_key": "plan"}]
        assert (await s.query_for_question(other, token))["status"] in {
            "invalid_page_token",
            "invalid_selection",
        }
        body, mac = token.split(".")
        forged = body + "." + ("0" if mac[0] != "0" else "1") + mac[1:]
        assert (await s.query_for_question(VEHICLES, forged))["status"] == (
            "invalid_page_token"
        )
        assert (await s.query_for_question(VEHICLES, token))["status"] == "selected"


@pytest.mark.asyncio
async def test_page_token_is_refused_after_a_new_turn(learning):
    await seed_vehicles(learning, 11)
    async with context_session(learning, "Which vehicles do I own?") as (s, c, _):
        token = (await s.query_for_question(VEHICLES))["paging"]["next_page"]
        c.accept_turn(ConversationRole.USER, "Actually, tell me about plans.")
        refused = await s.query_for_question(VEHICLES, token)
        assert refused["status"] in {"denied", "invalid_page_token"}
        assert not refused.get("facts")


@pytest.mark.asyncio
async def test_page_token_is_refused_after_a_forget_mid_paging(learning):
    seeded = await seed_vehicles(learning, 11)
    async with context_session(learning, "Which vehicles do I own?") as (s, _, _):
        token = (await s.query_for_question(VEHICLES))["paging"]["next_page"]
        template = learning.plan.mutations[0]
        await learning.lifecycle.forget(
            seeded[-1].assertion_id,
            replace(template.source, source_id=str(uuid4()), evidence_text=None),
        )
        refused = await s.query_for_question(VEHICLES, token)
        assert refused["status"] in {"denied", "invalid_page_token"}
        assert not refused.get("facts")


@pytest.mark.asyncio
async def test_page_token_is_refused_once_the_lease_has_expired(learning, clock):
    from jarvis.voice import personal_context

    await seed_vehicles(learning, 11)
    async with context_session(learning, "Which vehicles do I own?") as (s, _, _):
        token = (await s.query_for_question(VEHICLES))["paging"]["next_page"]
        clock.advance(31)
        s._read_renewals = personal_context.MAX_READ_RENEWALS  # no renewal left
        refused = await s.query_for_question(VEHICLES, token)
        assert refused["status"] == "denied" and not refused.get("facts")


# An item larger than a whole page -------------------------------------------------


@pytest.mark.asyncio
async def test_oversized_item_is_marked_never_cut_and_never_an_empty_page(learning):
    await seed_vehicles(learning, 3, prefix="Bike")
    huge = "x" * (PAGE_BYTES + 500)
    big = await seed_item(learning, "Bike 01b")
    template = learning.plan.mutations[0]
    source = replace(template.source, source_id=str(uuid4()), evidence_text=None)
    await learning.lifecycle.forget(big.assertion_id, source)
    await learning.lifecycle.create(
        replace(
            template.draft,
            predicate=f"owned_item_{uuid4().hex}",
            value=big.value,
            normalized_text=f"Bike 01b; {huge}",
        ),
        replace(source, source_id=str(uuid4())),
    )
    async with context_session(learning, "Which vehicles do I own?") as (s, _, _):
        first = await s.query_for_question(VEHICLES)
        pages = await page_through(s, VEHICLES, first)
        released = [f for p in pages for f in p["facts"]]
        assert len(released) == 4 and all(p["facts"] for p in pages)
        oversized = [f for f in released if "omitted" in f]
        assert len(oversized) == 1
        assert oversized[0]["omitted"] == "item_exceeds_page_budget"
        assert oversized[0]["label"] == "Bike 01b"
        assert huge[:50] not in json.dumps(pages)
        last = pages[-1]["paging"]
        assert last["complete"] is False and last.get("omitted_items") is True
        assert "not included" in last["list_rule"]
        assert last["scopes"]["owned_item.vehicle"]["complete"] is False


def test_oversized_item_is_reduced_and_the_page_continues_past_it():
    from test_context_projection import record, snap

    big = record("Huge", "h", normalized_text="y" * (PAGE_BYTES * 2))
    rest = [record(f"Zeta {i}", f"z{i}") for i in range(9)]
    requests = parse_context_requests(VEHICLES, question="My vehicles?")
    first = project_personal_context(snap(big, *rest), requests)
    assert first.facts[0]["omitted"] == "item_exceeds_page_budget"
    assert first.facts[0]["label"] == "Huge" and "text" not in first.facts[0]
    assert len(first.facts) == 8 and first.next_offset == 8
    second = project_personal_context(snap(big, *rest), requests, offset=8)
    assert [f["text"] for f in second.facts] == ["Zeta 7", "Zeta 8"]
    assert second.next_offset is None
    assert not first.complete and second.complete  # per page; the session
    # carries the omission forward (see the session-level test above).


# New released fields --------------------------------------------------------------


@pytest.mark.asyncio
async def test_sold_items_precision_and_passed_plans_are_released_as_held(learning):
    past = await seed_plan(
        learning,
        "Weekend at Pinecrest",
        earliest="2026-09-05",
        latest="2026-09-06",
        precision="range",
    )
    assert past is not None
    owner = Owner(learning)
    _plan, result, _ = await owner.say(
        "I sold my Falcon bike in March 2024.",
        [
            item(
                "Falcon bike",
                ["I sold my Falcon bike in March 2024"],
                state="sold",
                disposed_expression="March 2024",
            )
        ],
        [("new", None)],
    )
    assert result.status == "committed"
    async with context_session(learning, "What do you know about my plans?") as (
        s,
        _,
        _,
    ):
        plans = await s.query_for_question(PLANS)
        temporal = plans["facts"][0]["temporal"]
        assert temporal["precision"] == "range"
        assert temporal["date_status"] == "passed_outcome_unknown"
    async with context_session(learning, "Which vehicles did I have?") as (s, _, _):
        vehicles = await s.query_for_question(VEHICLES)
        falcon = [f for f in vehicles["facts"] if f.get("state") == "sold"]
        assert len(falcon) == 1
        assert falcon[0]["disposed"]["precision"] == "month"
        assert set(falcon[0]["disposed"]) == {
            "expression",
            "precision",
            "earliest",
            "latest",
        }
        assert "T" not in json.dumps(falcon[0]["disposed"])  # no clock time


# Bounded learning catalog ---------------------------------------------------------


def _entry(i, label, *, details=None, kind="vehicle"):
    value = {"label": label, "value": label, "category": "owned_item", "kind": kind}
    if details:
        value["details"] = details
    return LearningCatalogEntry(
        assertion_id=f"a{i:03d}",
        predicate=f"owned_item_{i:03d}",
        category="owned_item",
        kind=kind,
        text=label,
        value=json.dumps(value),
    )


class _Candidate:
    def __init__(self, label, *, category="owned_item", kind="vehicle", **extra):
        self.label, self.category, self.kind = label, category, kind
        self.aliases = extra.get("aliases", [])
        self.details = extra.get("details")


def test_small_category_is_supplied_whole_as_before():
    entries = [_entry(i, f"Bike {i}") for i in range(CANDIDATE_LIMIT)]
    supplied, skipped = bounded_entries(
        entries, [_Candidate("Unrelated")], SCALAR_FACETS
    )
    assert len(supplied) == CANDIDATE_LIMIT and skipped == ()


def test_large_category_is_narrowed_by_distinguishing_words():
    entries = [_entry(i, f"Bike {i}") for i in range(40)]
    supplied, skipped = bounded_entries(entries, [_Candidate("Bike 7")], SCALAR_FACETS)
    # "bike" is in all 40 facts and distinguishes nothing; "7" picks one.
    assert [json.loads(e.value)["label"] for e in supplied] == ["Bike 7"]
    assert skipped == ()


def test_new_words_match_nothing_and_the_resolver_sees_no_false_targets():
    entries = [_entry(i, f"Bike {i}") for i in range(40)]
    supplied, skipped = bounded_entries(entries, [_Candidate("Glider")], SCALAR_FACETS)
    assert supplied == [] and skipped == ()


@pytest.mark.parametrize(
    "candidate",
    [_Candidate("Bike"), _Candidate("Red Blue")],
    ids=["only_common_words", "too_many_matches"],
)
def test_ambiguous_page_skips_only_that_candidate(candidate):
    entries = [_entry(i, f"Red Bike {i}") for i in range(20)] + [
        _entry(20 + i, f"Blue Bike {i}") for i in range(20)
    ]
    supplied, skipped = bounded_entries(
        entries, [candidate, _Candidate("Bike 3")], SCALAR_FACETS
    )
    assert skipped == (0,)
    assert {json.loads(e.value)["label"] for e in supplied} == {
        "Red Bike 3",
        "Blue Bike 3",
    }


@pytest.mark.asyncio
async def test_ambiguous_candidate_is_recorded_not_lost_or_claimed(learning):
    for i in range(40):
        await seed_item(learning, f"Bike {i:02d}")
    owner = Owner(learning)
    plan, result, _ = await owner.say(
        "My bike is red.",
        [item("bike", ["My bike is red"], details="red")],
        [("match", "Bike 00")],
    )
    assert [o.reason for o in plan.outcomes] == [PAGE_AMBIGUOUS]
    assert not plan.mutations and result.status == "recorded"
    stored = await learning.reader.run(
        lambda c: c.execute(
            "SELECT reason_code FROM personal_learning_outcome"
        ).fetchall()
    )
    assert stored == [(PAGE_AMBIGUOUS,)]


# Performance ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_five_hundred_rows_read_page_and_catalog_quickly(learning):
    for i in range(250):
        await seed_item(learning, f"Vehicle {i:03d}")
    for i in range(250):
        await seed_plan(learning, f"Plan {i:03d}")
    reader = CanonicalMemoryReader(learning.reader)
    requests = parse_context_requests(VEHICLES, question="My vehicles?")
    start = perf_counter()
    snapshot = await SemanticRetrievalService(
        learning.reader
    ).learning_context_snapshot(("owned_item.vehicle",))
    projection = project_personal_context(snapshot, requests)
    read_ms = (perf_counter() - start) * 1000
    assert projection.total == 250 and len(projection.facts) == 8
    start = perf_counter()
    scoped = await reader.learning_current_scoped()
    full_ms = (perf_counter() - start) * 1000
    assert len(scoped) == 500
    print(f"PR_C_500_ROWS read_page_ms={read_ms:.1f} full_scoped_ms={full_ms:.1f}")
    assert read_ms < 3000 and full_ms < 3000


def test_projection_now_is_the_owner_local_date():
    from test_context_projection import record

    base = record("Trip", "t")
    plan = replace(
        base,
        predicate="plan_t",
        value={
            **base.value,
            "category": "plan",
            "kind": "other",
            "state": "planned",
            "temporal": {
                "expression": "on 20 November 2026",
                "precision": "day",
                "earliest": "2026-11-20",
                "latest": "2026-11-20",
                "anchor_at": "2026-11-01T10:00:00+05:30",
            },
        },
    )
    from jarvis.memory.personal_context_projection import ScopedContextSnapshot

    def snap(record):
        return ScopedContextSnapshot(((record, "plan"),), ())

    requests = parse_context_requests(PLANS, question="My plans?")
    # 19:00 UTC on the 19th is already the 20th in IST.
    now = datetime(2026, 11, 19, 19, 0, tzinfo=UTC)
    result = project_personal_context(snap(plan), requests, now=now)
    assert result.facts[0]["temporal"]["date_status"] == "in_window"
    later = project_personal_context(snap(plan), requests, now=now + timedelta(days=2))
    assert later.facts[0]["temporal"]["date_status"] == "passed_outcome_unknown"
