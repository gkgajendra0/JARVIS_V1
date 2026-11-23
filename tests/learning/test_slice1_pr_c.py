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
            "basis",
        }
        assert falcon[0]["disposed"]["basis"] == "stated"  # "March 2024" said
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


# Learning in a category with more than 32 facts (owner check, 2026-11-21) -------


class _NoModel:
    """A resolver client that must not be reached."""

    def __getattr__(self, name):
        raise AssertionError("model must not be called")


async def _learn(h, text, spec, decide):
    """One turn through the real catalog; ``decide(catalog)`` gives the
    resolution (as the model would, from the supplied page only)."""
    from jarvis.memory.learning_contracts import (
        LearningBatch,
        LearningCandidate,
        LearningResolution,
        LearningResolutionBatch,
    )
    from jarvis.memory.learning_reconciliation import LearningReconciler

    owner = Owner(h)
    turn = owner.conversation.accept_turn(ConversationRole.USER, text)
    from jarvis.memory.learning_contracts import (
        AcceptedLearningSource,
        EvidenceSpan,
    )

    source = AcceptedLearningSource.from_turn(
        "runtime", owner.conversation, turn, now=100
    )
    h.authority.register_source(h.grant, source.receipt_id, source=source)
    spec = dict(spec)
    quote = spec.pop("quotes")[0]
    start = text.index(quote)
    candidate = LearningCandidate(
        **spec,
        evidence=[
            EvidenceSpan(turn_id=turn.turn_id, start=start, end=start + len(quote))
        ],
    )
    batch = LearningBatch(candidates=[candidate])
    reconciler = LearningReconciler(h.service.canonical_reader, h.authority)
    catalog = await reconciler.catalog(source, batch, h.grant)
    decision = await decide(source, batch, catalog)
    if not isinstance(decision, LearningResolutionBatch):
        decision = LearningResolutionBatch(
            resolutions=[LearningResolution(candidate_index=0, **decision)]
        )
    plan = reconciler.plan(source, batch, catalog, decision)
    result = None
    if plan.mutations or plan.outcomes:
        result = await h.service.admit_learning(
            plan, h.authority.issue_child(h.grant, plan.binding())
        )
    return catalog, plan, result


@pytest.mark.asyncio
async def test_large_category_still_admits_a_genuinely_new_item(learning):
    from jarvis.memory.learning_extractors import LearningProviderAdapter

    await seed_vehicles(learning, 40, prefix="Bike")
    resolver = LearningProviderAdapter("gemini", _NoModel(), "fictional")

    async def decide(source, batch, catalog):
        return await resolver.resolve(source, batch, catalog)

    catalog, plan, result = await _learn(
        learning,
        "I bought a Brightwave scooter.",
        item("Brightwave scooter", ["a Brightwave scooter"]),
        decide,
    )
    # No existing fact shares a distinguishing word: an empty page, a
    # deterministic "new" without a model call, and the item is admitted.
    assert catalog.entries == [] and catalog.page_ambiguous == []
    assert [m.action for m in plan.mutations] == ["create"] and not plan.outcomes
    assert result.status == "committed"
    labels_now = await learning.service.current_owned_item_labels()
    assert "brightwave scooter" in labels_now and len(labels_now) == 41


@pytest.mark.asyncio
async def test_large_category_refines_the_one_reliable_match(learning):
    await seed_vehicles(learning, 40, prefix="Bike")

    async def decide(source, batch, catalog):
        target = [
            e for e in catalog.entries if json.loads(e.value)["label"] == "Bike 07"
        ]
        assert len(catalog.entries) == 1 and len(target) == 1
        return {"decision": "match", "target_id": target[0].assertion_id}

    _catalog, plan, result = await _learn(
        learning,
        "Bike 07 is the red one.",
        item("Bike 07", ["Bike 07 is the red one"], details="red"),
        decide,
    )
    assert [m.action for m in plan.mutations] == ["refine"] and not plan.outcomes
    assert result.status == "committed"
    assert plan.mutations[0].draft.value["details"] == "red"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "label,reason",
    [
        ("bike", PAGE_AMBIGUOUS),
        ("old touring bike", "target_missing_or_category_mismatch"),
    ],
    ids=["only_common_words", "match_outside_the_page"],
)
async def test_large_category_skips_ambiguous_or_incomplete_matching(
    learning, label, reason
):
    await seed_vehicles(learning, 40, prefix="Bike")
    outside = (
        await learning.reader.run(
            lambda c: c.execute(
                "SELECT assertion_id FROM semantic_assertion WHERE normalized_text"
                " LIKE 'Bike 31%' AND state='active'"
            ).fetchone()
        )
    )[0]

    async def decide(source, batch, catalog):
        # A model claiming a target that was not on the supplied page.
        return {"decision": "match", "target_id": outside}

    _catalog, plan, result = await _learn(
        learning,
        f"My {label} is red.",
        item(label, [f"My {label} is red"], details="red"),
        decide,
    )
    assert not plan.mutations
    assert [o.reason for o in plan.outcomes] == [reason]
    assert result.status == "recorded"


# Lease renewal keeps every earlier refusal (owner check, 2026-11-21) ------------


async def _released_pages(learning, authority_parts):
    from test_personal_context_session import _question, _setup

    await seed_vehicles(learning, 11)
    factory, session = await _setup(learning, authority_parts)
    conversation = _question("Which vehicles do I own?")
    personal = factory(conversation)
    first = await personal.query_for_question(VEHICLES)
    assert first["status"] == "selected" and "next_page" in first["paging"]
    return personal, session, conversation, first["paging"]["next_page"]


@pytest.fixture
def proposal_clock(monkeypatch, clock):
    from types import SimpleNamespace

    from jarvis.authority import proposal

    monkeypatch.setattr(proposal, "time", SimpleNamespace(monotonic=clock))


@pytest.mark.asyncio
async def test_lapsed_lease_alone_renews_and_the_next_page_is_released(
    learning, authority_parts, clock, proposal_clock
):
    personal, session, _, token = await _released_pages(learning, authority_parts)
    hellos = len(authority_parts.hello.calls)
    try:
        clock.advance(31)
        second = await personal.query_for_question(VEHICLES, token)
        assert second["status"] == "selected" and second["paging"]["complete"]
        assert personal._inner._read_renewals == 1
        assert len(authority_parts.hello.calls) == hellos
    finally:
        personal.close()
        session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "windows_lock",
        "session_revoked",
        "session_expired",
        "new_owner_turn",
        "renewal_cap",
        "corrected",
        "forgotten",
        "category_disabled",
        "session_closed",
    ],
)
async def test_lease_renewal_keeps_every_refusal_for_the_next_page(
    learning, authority_parts, clock, proposal_clock, change
):
    from jarvis.authority.personal_context_session import ABSOLUTE_LIMIT_SECONDS
    from jarvis.voice import personal_context

    personal, session, conversation, token = await _released_pages(
        learning, authority_parts
    )
    statements = {
        "corrected": "UPDATE semantic_assertion SET normalized_text='Nexon'"
        " WHERE state='active' AND predicate LIKE 'owned_item%'",
        "forgotten": "UPDATE semantic_assertion SET state='retracted'"
        " WHERE state='active' AND predicate LIKE 'owned_item%'",
        "category_disabled": "INSERT INTO personal_learning_suppression"
        " VALUES ('owned_item.vehicle',1,1,'fictional')",
    }

    def update(connection):
        with connection:
            connection.execute(statements[change])

    try:
        clock.advance(31)
        if change == "windows_lock":
            authority_parts.windows.lock_unlock()
        elif change == "session_revoked":
            session.close("owner_revoked")
        elif change == "session_expired":
            clock.advance(ABSOLUTE_LIMIT_SECONDS)
        elif change == "new_owner_turn":
            conversation.accept_turn(ConversationRole.USER, "Actually, never mind.")
        elif change == "renewal_cap":
            personal._inner._read_renewals = personal_context.MAX_READ_RENEWALS
        elif change == "session_closed":
            personal._inner.close()
        else:
            await learning.writer.run(update)
        refused = await personal.query_for_question(VEHICLES, token)
        assert refused["status"] in {"denied", "invalid_page_token", "unavailable"}
        assert not refused.get("facts")
        if change in statements:
            # The renewal itself re-checks the released facts, finds them
            # changed and closes the read.
            assert personal._inner._closed
        else:
            assert personal._inner._read_renewals == (
                personal_context.MAX_READ_RENEWALS if change == "renewal_cap" else 0
            )
    finally:
        personal.close()
        session.close()


@pytest.mark.asyncio
async def test_frozen_d23_wording_stores_the_month_of_the_sale(learning):
    """Found by the acceptance harness: "in October" (no year) told in
    November is October of that year, not an unresolved time."""
    owner = Owner(learning)
    _plan, result, _ = await owner.say(
        "I sold the Classic 350 in October.",
        [
            item(
                "Classic 350",
                ["I sold the Classic 350 in October"],
                state="sold",
                disposed_expression="October",
            )
        ],
        [("new", None)],
    )
    assert result.status == "committed"
    rows = await learning.reader.run(
        lambda c: c.execute(
            "SELECT value_json, valid_from FROM semantic_assertion WHERE state='active'"
            " AND predicate LIKE 'owned_item%'"
        ).fetchall()
    )
    value, valid_from = json.loads(rows[-1][0]), rows[-1][1]
    today = datetime.now().astimezone().date()
    year = today.year if today.month >= 10 else today.year - 1
    assert (value["disposed"]["precision"], value["disposed"]["earliest"]) == (
        "month",
        f"{year}-10-01",
    )
    assert value["disposed"]["latest"] == f"{year}-10-31"
    assert value["disposed"]["expression"] == "October"  # the owner's words
    assert value["disposed"]["basis"] == "inferred_year"  # year not said
    assert valid_from is None  # the effective day is still unknown


@pytest.mark.asyncio
async def test_frozen_d2_wording_refines_by_a_unique_shorter_name(learning):
    """Found by the acceptance harness: "the Tigor" for the stored "Tata
    Tigor" is the same item, so the added detail refines it."""
    from test_slice1_pr_b import current, labelled, rows, seed_d1

    owner, _ = await seed_d1(learning)
    before = labelled(await rows(learning), "Tata Tigor")[0]
    plan, result, _ = await owner.say(
        "I bought the Tigor in March 2017, it's the diesel one.",
        [
            item(
                "Tigor",
                ["I bought the Tigor in March 2017, it's the diesel one"],
                details="diesel",
                acquired_expression="March 2017",
            )
        ],
        [("match", "Tata Tigor")],
    )
    assert [m.action for m in plan.mutations] == ["refine"] and not plan.outcomes
    assert result.status == "committed"
    all_rows = await rows(learning)
    old = next(r for r in all_rows if r["id"] == before["id"])
    new = labelled(all_rows, "Tata Tigor")[0]
    assert old["state"] == "superseded" and new["supersedes"] == old["id"]
    assert new["value"]["label"] == "Tata Tigor"  # the stored name is kept
    assert new["value"]["details"] == "diesel"
    assert len(current(all_rows)) == 3


@pytest.mark.asyncio
async def test_a_shorter_name_shared_by_two_items_never_refines(learning):
    from test_slice1_pr_b import rows

    owner = Owner(learning)
    for label in ("Classic 350 bike", "Pulsar 150 bike"):
        await owner.say(
            f"I have a {label}.", [item(label, [f"I have a {label}"])], [("new", None)]
        )
    plan, result, _ = await owner.say(
        "My bike is red.",
        [item("bike", ["My bike is red"], details="red")],
        [("match", "Classic 350 bike")],
    )
    assert not plan.mutations
    assert [o.reason for o in plan.outcomes] == ["new_fact_cannot_mutate_target"]
    assert result.status == "recorded"
    assert all("red" not in str(r["value"]) for r in await rows(learning))


@pytest.mark.asyncio
async def test_explicit_list_gives_each_item_its_own_source_and_forgets_one(learning):
    """Found by the acceptance harness (frozen D3: 2 rows, 2 sources). With a
    shared source, forgetting one listed item would touch the other's
    provenance."""
    from jarvis.memory.explicit import build_owner_explicit_source
    from jarvis.memory.types import Sensitivity

    conversation = Owner(learning).conversation
    turn = conversation.accept_turn(
        ConversationRole.USER, "Remember my devices are a Dell XPS and an iPad Air."
    )
    source = build_owner_explicit_source(
        conversation=conversation, turn=turn, sensitivity=Sensitivity.STANDARD
    )
    records = await learning.service.remember_owned_items(
        kind="device", items=("Dell XPS", "iPad Air"), source=source
    )
    assert len({r.source_id for r in records}) == 2
    stored = await learning.reader.run(
        lambda c: c.execute(
            "SELECT s.canonical_ref, s.observed_at FROM semantic_assertion a JOIN"
            " memory_source s ON s.source_id = a.source_id WHERE a.assertion_id IN (?, ?)",
            (records[0].assertion_id, records[1].assertion_id),
        ).fetchall()
    )
    assert len(set(stored)) == 1  # same owner turn and time
    forget_source = replace(source, source_id=str(uuid4()))
    await learning.lifecycle.forget(records[0].assertion_id, forget_source)
    left = await learning.reader.run(
        lambda c: c.execute(
            "SELECT a.state, s.source_id FROM semantic_assertion a JOIN memory_source"
            " s ON s.source_id = a.source_id WHERE a.assertion_id = ?",
            (records[1].assertion_id,),
        ).fetchall()
    )
    assert left == [("active", records[1].source_id)]


# Month without a year: inferred only with supporting context ------------------
# (owner check 2026-11-21; examples outside the frozen files)


async def _stored_items(learning):
    rows = await learning.reader.run(
        lambda c: c.execute(
            "SELECT value_json, state, valid_from FROM semantic_assertion"
            " WHERE predicate LIKE 'owned_item%' ORDER BY system_from"
        ).fetchall()
    )
    return [(json.loads(v), state, valid_from) for v, state, valid_from in rows]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,label,expression",
    [
        ("I have a Gypsy from September.", "Gypsy", "September"),
        ("I bought a Duster in September.", "Duster", "September"),
    ],
)
async def test_new_item_bare_month_is_never_turned_into_a_purchase_date(
    learning, text, label, expression
):
    owner = Owner(learning)
    _plan, result, _ = await owner.say(
        text,
        [item(label, [text.rstrip(".")], acquired_expression=expression)],
        [("new", None)],
    )
    assert result.status == "committed"
    value, _state, valid_from = (await _stored_items(learning))[-1]
    if "bought" not in text:
        # "have ... from <time>" is not acquisition wording (owner decision on
        # D1, 2026-11-23): the item is saved without any purchase date.
        assert "acquired" not in value and valid_from is None
        return
    assert value["acquired"]["expression"] == expression  # wording kept
    assert value["acquired"]["precision"] == "unresolved"
    assert value["acquired"]["earliest"] is None and value["acquired"]["latest"] is None
    assert value["acquired"]["basis"] == "stated"
    assert valid_from is None


@pytest.mark.asyncio
async def test_a_date_without_acquisition_wording_is_not_a_purchase_date(learning):
    # "My Nexon is from March." says nothing about buying it.
    owner = Owner(learning)
    text = "My Nexon is from March."
    _plan, result, _ = await owner.say(
        text,
        [item("Nexon", [text.rstrip(".")], acquired_expression="March")],
        [("new", None)],
    )
    assert result.status == "committed"
    value, _state, _ = (await _stored_items(learning))[-1]
    assert value["label"] == "Nexon" and "acquired" not in value


@pytest.mark.asyncio
async def test_correction_without_a_stored_purchase_time_infers_no_year(learning):
    owner = Owner(learning)
    await owner.say(
        "I have a Hector.", [item("Hector", ["I have a Hector"])], [("new", None)]
    )
    plan, _result, _ = await owner.say(
        "Actually, the Hector is from September.",
        [
            item(
                "Hector",
                ["the Hector is from September"],
                intent="correction",
                acquired_expression="September",
            )
        ],
        [("match", "Hector")],
    )
    # No acquisition wording and no stored date it replaces: not applied,
    # recorded (owner rule 2026-11-23, positive evidence).
    assert plan.mutations == ()
    assert [o.reason for o in plan.outcomes] == ["date_evidence_missing"]
    value, _state, _ = (await _stored_items(learning))[-1]
    assert "acquired" not in value


@pytest.mark.asyncio
async def test_correction_of_a_stored_purchase_month_infers_and_marks_the_year(
    learning,
):
    from test_slice1_pr_b import seed_d1

    owner, _ = await seed_d1(learning)  # Jimny acquired "last month"
    plan, _result, _ = await owner.say(
        "I misspoke, the Jimny is from September, not October.",
        [
            item(
                "Jimny",
                ["the Jimny is from September, not October"],
                intent="correction",
                acquired_expression="September",
            )
        ],
        [("match", "Jimny")],
    )
    assert [m.action for m in plan.mutations] == ["correct"], plan.outcomes
    value, _state, _ = (await _stored_items(learning))[-1]
    acquired = value["acquired"]
    today = datetime.now().astimezone().date()
    year = today.year if today.month >= 9 else today.year - 1
    assert (acquired["precision"], acquired["earliest"]) == ("month", f"{year}-09-01")
    assert acquired["expression"] == "September"
    assert acquired["basis"] == "inferred_year"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state,expression,basis,precision",
    [
        ("sold", "October", "inferred_year", "month"),
        ("sold", "October 2025", "stated", "month"),
        ("lost", "in March", "inferred_year", "month"),
    ],
)
async def test_disposal_month_infers_a_year_only_when_the_item_is_gone(
    learning, state, expression, basis, precision
):
    owner = Owner(learning)
    verb = {"sold": "I sold the Ertiga", "lost": "I lost the Ertiga"}[state]
    text = f"{verb} {expression}."
    _plan, result, _ = await owner.say(
        text,
        [
            item(
                "Ertiga",
                [text.rstrip(".")],
                state=state,
                disposed_expression=expression,
            )
        ],
        [("new", None)],
    )
    assert result.status == "committed"
    value, _state, _ = (await _stored_items(learning))[-1]
    assert value["disposed"]["expression"] == expression
    assert (value["disposed"]["basis"], value["disposed"]["precision"]) == (
        basis,
        precision,
    )


@pytest.mark.asyncio
async def test_a_disposal_time_on_an_item_still_owned_is_never_stored(learning):
    # Not gone: no year is inferred, and since lab 7 the consistency gate
    # refuses an owned item carrying a disposal time at all.
    owner = Owner(learning)
    text = "I sold the Ertiga in October."
    plan, result, _ = await owner.say(
        text,
        [
            item(
                "Ertiga",
                [text.rstrip(".")],
                state="owned",
                disposed_expression="October",
            )
        ],
        [("new", None)],
    )
    assert result.status != "committed" and plan.mutations == ()
    assert [o.reason for o in plan.outcomes] == ["inconsistent_item_state"]
    assert await _stored_items(learning) == []


# Pronoun follow-ups (owner check 2026-11-21, from run-1 D5) -------------------


async def _follow_up(learning, earlier, question, requests):
    """A follow-up question in the same session as earlier owner turns
    (sentences of ``earlier`` become separate turns)."""
    turns = [t.strip() + "." for t in earlier.rstrip(".").split(". ")]
    async with context_session(learning, turns[0]) as (s, c, _):
        for text in turns[1:]:
            c.accept_turn(ConversationRole.ASSISTANT, "Okay.")
            c.accept_turn(ConversationRole.USER, text)
        c.accept_turn(ConversationRole.ASSISTANT, "Okay.")
        c.accept_turn(ConversationRole.USER, question)
        return await s.query_for_question(requests)


@pytest.mark.asyncio
async def test_d5_reproduction_pronoun_follow_up_with_a_name_from_the_last_turn(
    learning,
):
    """Run 1: "When did I sell it?" with target_quote "Tigor" (named only in
    the previous owner turn) was refused as invalid_selection."""
    await seed_item(learning, "Tata Tigor")
    await seed_item(learning, "Jimny")
    result = await _follow_up(
        learning,
        "I sold the Tigor last week.",
        "When did I sell it?",
        [{"scope_key": "owned_item.vehicle", "target_quote": "Tigor"}],
    )
    assert result["status"] == "selected", result
    assert [f["text"].split(";")[0] for f in result["facts"]] == ["Tata Tigor"]


@pytest.mark.asyncio
async def test_ambiguous_pronoun_follow_up_asks_which_item_and_releases_nothing(
    learning,
):
    await seed_item(learning, "Tata Tigor")
    await seed_item(learning, "Royal Enfield Classic 350")
    result = await _follow_up(
        learning,
        "I sold the Tigor and the Classic 350.",
        "When did I sell it?",
        [{"scope_key": "owned_item.vehicle", "target_quote": "Tigor"}],
    )
    assert result["status"] == "clarification_required", result
    assert not result.get("facts")


@pytest.mark.asyncio
async def test_pronoun_follow_up_prefers_the_category_lookup_without_a_target(learning):
    await seed_item(learning, "Tata Tigor")
    await seed_item(learning, "Jimny")
    result = await _follow_up(
        learning,
        "I sold the Tigor last week.",
        "When did I sell it?",
        [{"scope_key": "owned_item.vehicle"}],
    )
    assert result["status"] == "selected"
    assert len(result["facts"]) == 2  # the permitted category; the answer picks


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "earlier,question,quote,status",
    [
        # No referring word: the target must still quote the current question.
        (
            "I sold the Tigor last week.",
            "When did I buy the Jimny?",
            "Tigor",
            "invalid_selection",
        ),
        # A name the owner never said in this session is never accepted.
        (
            "I sold the Tigor last week.",
            "When did I sell it?",
            "Pulsar",
            "invalid_selection",
        ),
        # The quote names an item, but the most recent naming turn meant another.
        (
            "I love my Jimny. I sold the Tigor last week.",
            "When did I sell it?",
            "Jimny",
            "clarification_required",
        ),
    ],
    ids=["no_referring_word", "never_said", "quote_not_the_referent"],
)
async def test_pronoun_follow_up_keeps_grounding(
    learning, earlier, question, quote, status
):
    await seed_item(learning, "Tata Tigor")
    await seed_item(learning, "Jimny")
    result = await _follow_up(
        learning,
        earlier,
        question,
        [{"scope_key": "owned_item.vehicle", "target_quote": quote}],
    )
    assert result["status"] == status, result
    assert not result.get("facts")


def test_the_model_cannot_supply_a_reference():
    with pytest.raises(ValueError):
        parse_context_requests(
            [
                {
                    "scope_key": "owned_item.vehicle",
                    "target_quote": "Tigor",
                    "reference": ["x"],
                }
            ],
            question="When did I sell it?",
            context=("I sold the Tigor.",),
        )


def test_reference_turns_are_only_the_last_four_earlier_owner_turns():
    old = ("I sold the Tigor.", "a", "b", "c", "d")
    with pytest.raises(ValueError):
        parse_context_requests(
            [{"scope_key": "owned_item.vehicle", "target_quote": "Tigor"}],
            question="When did I sell it?",
            context=old,
        )
