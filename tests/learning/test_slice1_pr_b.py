"""Personal memory slice 1, PR B: possessions, plans, minimal owner quotes,
recorded skips and forgetting, at the stored-record level.

Fixed extractor/resolver outputs are replayed through the real policy,
reconciler, admission boundary and storage (the model's own choices are
measured in the isolated text acceptance, not here). Fictional data only.
"""

from __future__ import annotations

import json

import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.forget_residuals import residual_report
from jarvis.memory.learning_contracts import (
    AcceptedLearningSource,
    EvidenceSpan,
    LearningBatch,
    LearningCandidate,
    LearningResolution,
    LearningResolutionBatch,
    PlanSlots,
    SlotValue,
)
from jarvis.memory.learning_policy import LearningPolicy
from jarvis.memory.learning_reconciliation import LearningReconciler
from jarvis.memory.personal_time import time_object


class Owner:
    """One fictional conversation; each say() learns from one accepted turn."""

    def __init__(self, h):
        self.h = h
        self.conversation = ConversationSession()
        self.conversation.start()
        self.reconciler = LearningReconciler(h.service.canonical_reader, h.authority)

    async def say(self, text, specs, decisions):
        turn = self.conversation.accept_turn(ConversationRole.USER, text)
        source = AcceptedLearningSource.from_turn(
            "runtime", self.conversation, turn, now=100
        )
        self.h.authority.register_source(self.h.grant, source.receipt_id, source=source)
        candidates = []
        for spec in specs:
            spec = dict(spec)
            quotes = spec.pop("quotes")
            spans = []
            for quote in quotes:
                start = text.index(quote)
                spans.append(
                    EvidenceSpan(
                        turn_id=turn.turn_id, start=start, end=start + len(quote)
                    )
                )
            candidates.append(LearningCandidate(**spec, evidence=spans))
        eligible = [
            c
            for c in candidates
            if LearningPolicy().evaluate(source, c).status == "eligible"
        ]
        self.rejected = len(candidates) - len(eligible)
        batch = LearningBatch(candidates=eligible)
        if not eligible:
            return None, None, turn
        catalog = await self.reconciler.catalog(source, batch, self.h.grant)
        by_label = {}
        for entry in catalog.entries:
            try:
                by_label[json.loads(entry.value).get("label")] = entry.assertion_id
            except (TypeError, ValueError):
                by_label[entry.predicate] = entry.assertion_id
        resolutions = LearningResolutionBatch(
            resolutions=[
                LearningResolution(
                    candidate_index=i,
                    decision=decision,
                    target_id=by_label.get(target) if target else None,
                )
                for i, (decision, target) in enumerate(decisions[: len(eligible)])
            ]
        )
        plan = self.reconciler.plan(source, batch, catalog, resolutions)
        result = None
        if plan.mutations or plan.outcomes:
            result = await self.h.service.admit_learning(
                plan, self.h.authority.issue_child(self.h.grant, plan.binding())
            )
        return plan, result, turn


async def rows(h):
    return await h.reader.run(
        lambda c: [
            dict(
                zip(
                    (
                        "id",
                        "predicate",
                        "state",
                        "valid_from",
                        "valid_to",
                        "system_to",
                        "value",
                        "quote",
                        "ref",
                        "source_id",
                        "supersedes",
                    ),
                    (*r[:6], json.loads(r[6]) if r[6] else None, *r[7:]),
                    strict=True,
                )
            )
            for r in c.execute(
                "SELECT a.assertion_id, a.predicate, a.state, a.valid_from,"
                " a.valid_to, a.system_to, a.value_json, s.evidence_text,"
                " s.canonical_ref, a.source_id, a.supersedes_id"
                " FROM semantic_assertion a JOIN memory_source s"
                " ON s.source_id = a.source_id ORDER BY a.system_from, a.rowid"
            )
        ]
    )


def current(all_rows):
    return [r for r in all_rows if r["state"] == "active"]


def labelled(all_rows, label):
    return [r for r in current(all_rows) if r["value"].get("label") == label]


def item(label, quotes, **extra):
    return {
        "category": "owned_item",
        "kind": extra.pop("kind", "vehicle"),
        "intent": extra.pop("intent", "new"),
        "label": label,
        "value": extra.pop("value", label),
        "state": extra.pop("state", "owned"),
        "quotes": quotes,
        **extra,
    }


D1 = (
    "I have a Royal Enfield Classic 350 from 2021, a Tata Tigor I bought in "
    "March 2017, and last month I got a Jimny."
)


async def seed_d1(h):
    owner = Owner(h)
    _plan, result, turn = await owner.say(
        D1,
        [
            item(
                "Royal Enfield Classic 350",
                ["Royal Enfield Classic 350 from 2021"],
                acquired_expression="2021",
            ),
            item(
                "Tata Tigor",
                ["a Tata Tigor I bought in March 2017"],
                acquired_expression="March 2017",
            ),
            item(
                "Jimny", ["last month I got a Jimny"], acquired_expression="last month"
            ),
        ],
        [("new", None)] * 3,
    )
    assert result.status == "committed"
    return owner, turn


# D1 --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d1_separate_items_keep_partial_dates_and_their_own_quotes(learning):
    _, turn = await seed_d1(learning)
    stored = current(await rows(learning))
    assert len(stored) == 3
    assert len({r["source_id"] for r in stored}) == 3  # one source per fact
    anchor = turn.accepted_at.astimezone()
    expected = {
        "Royal Enfield Classic 350": ("year", time_object("2021", anchor)),
        "Tata Tigor": ("month", time_object("March 2017", anchor)),
        "Jimny": ("month", time_object("last month", anchor)),
    }
    for row in stored:
        precision, obj = expected[row["value"]["label"]]
        acquired = row["value"]["acquired"]
        assert acquired["precision"] == precision
        assert (acquired["earliest"], acquired["latest"]) == (
            obj["earliest"],
            obj["latest"],
        )
        assert row["valid_from"] is None  # no invented day
        others = set(expected) - {row["value"]["label"]}
        assert row["value"]["label"].split()[-1] in row["quote"]
        assert not any(o in row["quote"] for o in others)  # separable sentence
        assert row["quote"] in D1 and len(row["quote"]) <= 500
        assert row["ref"].endswith(":turn:" + turn.turn_id)


# D2 --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d2_added_detail_refines_the_same_item(learning):
    owner, _ = await seed_d1(learning)
    before = labelled(await rows(learning), "Tata Tigor")[0]
    text = "I bought the Tata Tigor in March 2017, it's the diesel one."
    plan, _result, _ = await owner.say(
        text,
        [
            item(
                "Tata Tigor",
                ["I bought the Tata Tigor in March 2017, it's the diesel one"],
                details="diesel",
                acquired_expression="March 2017",
            )
        ],
        [("match", "Tata Tigor")],
    )
    assert [m.action for m in plan.mutations] == ["refine"]
    all_rows = await rows(learning)
    old = next(r for r in all_rows if r["id"] == before["id"])
    new = labelled(all_rows, "Tata Tigor")[0]
    assert old["state"] == "superseded" and old["state"] != "retracted"
    assert old["valid_from"] is None and old["valid_to"] is None
    assert new["supersedes"] == old["id"] and new["value"]["details"] == "diesel"
    assert len(current(all_rows)) == 3  # no new item


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,reason",
    [
        ("I bought the Jimny in 2019.", "refine_conflicts_existing_detail"),
        # No acquisition wording: the date is not applied at all (owner rule
        # 2026-11-23, positive evidence for purchase/disposal dates).
        ("The Jimny is from 2019.", "date_evidence_missing"),
    ],
)
async def test_refine_never_overrides_a_contradicting_detail(learning, text, reason):
    owner, _ = await seed_d1(learning)
    plan, result, _ = await owner.say(
        text,
        [item("Jimny", [text.rstrip(".")], acquired_expression="2019")],
        [("match", "Jimny")],
    )
    assert plan.mutations == ()
    assert [o.reason for o in plan.outcomes] == [reason]
    assert result.status == "recorded"


# D5 / D22 / D23 ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_d5_d22_week_dated_sale_ends_ownership_without_an_exact_day(learning):
    owner, _ = await seed_d1(learning)
    before = labelled(await rows(learning), "Tata Tigor")[0]
    plan, _result, turn = await owner.say(
        "I sold the Tata Tigor last week.",
        [
            item(
                "Tata Tigor",
                ["I sold the Tata Tigor last week"],
                intent="change",
                state="sold",
                disposed_expression="last week",
            )
        ],
        [("match", "Tata Tigor")],
    )
    assert [m.action for m in plan.mutations] == ["change"]
    assert plan.mutations[0].effective_at is None
    all_rows = await rows(learning)
    old = next(r for r in all_rows if r["id"] == before["id"])
    new = labelled(all_rows, "Tata Tigor")[0]
    assert old["state"] == "superseded" and old["valid_to"] is None
    assert new["value"]["state"] == "sold" and new["valid_from"] is None
    week = time_object("last week", turn.accepted_at.astimezone())
    assert new["value"]["disposed"]["precision"] == "week"
    assert (
        new["value"]["disposed"]["earliest"],
        new["value"]["disposed"]["latest"],
    ) == (
        week["earliest"],
        week["latest"],
    )
    owned = [r for r in current(all_rows) if r["value"].get("state") == "owned"]
    assert "Tata Tigor" not in {r["value"]["label"] for r in owned}


@pytest.mark.asyncio
async def test_d23_month_only_sale_and_a_stated_day_boundary(learning):
    owner, _ = await seed_d1(learning)
    plan, *_ = await owner.say(
        "I sold the Royal Enfield Classic 350 in October 2026.",
        [
            item(
                "Royal Enfield Classic 350",
                ["I sold the Royal Enfield Classic 350 in October 2026"],
                intent="change",
                state="sold",
                disposed_expression="October 2026",
            )
        ],
        [("match", "Royal Enfield Classic 350")],
    )
    assert plan.mutations[0].effective_at is None
    plan, *_ = await owner.say(
        "I gave away the Jimny on 14 November 2026.",
        [
            item(
                "Jimny",
                ["I gave away the Jimny on 14 November 2026"],
                intent="change",
                state="gave_away",
                disposed_expression="14 November 2026",
            )
        ],
        [("match", "Jimny")],
    )
    effective = plan.mutations[0].effective_at
    assert effective is not None and effective.tzinfo is not None
    stored = current(await rows(learning))
    assert {r["value"]["state"] for r in stored} >= {"sold", "gave_away"}
    jimny = labelled(await rows(learning), "Jimny")[0]
    assert jimny["value"]["disposed"]["precision"] == "day"


# D3 explicit list --------------------------------------------------------------


@pytest.mark.asyncio
async def test_d3_explicit_list_split_under_one_approval_and_legacy_untouched(learning):
    from dataclasses import replace

    from jarvis.memory.types import AuthorityClass, MemorySourceClass
    from jarvis.voice.memory_tools import MemoryAgentTools

    legacy_source = replace(
        learning.plan.mutations[0].source,
        source_id="legacy-source",
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
        evidence_text=None,
    )
    legacy = await learning.service.remember_text(
        predicate="vehicles",
        value="a Bajaj Chetak and a Hero Splendor",
        source=legacy_source,
    )
    conversation = ConversationSession()
    conversation.start()
    conversation.accept_turn(
        ConversationRole.USER, "Remember my devices are a Dell XPS and an iPad Air."
    )
    approvals = []

    class Personal:
        def reserve_mutation(self, operation):
            pass

        async def authorize_mutation(self, operation, predicate, value=None, **kw):
            approvals.append((operation, predicate, value))

        def validate_mutation_commit(self):
            pass

        def mutation_committed(self):
            pass

        def mutation_failed(self):
            pass

    tools = MemoryAgentTools(
        learning.service, conversation, personal_context=Personal()
    )
    receipt = await tools.remember(
        predicate="devices", value="a Dell XPS and an iPad Air"
    )
    assert approvals == [("remember", "devices", "Dell XPS; iPad Air")]
    assert receipt["saved"] == ["Dell XPS", "iPad Air"]
    stored = current(await rows(learning))
    devices = [
        r
        for r in stored
        if isinstance(r["value"], dict) and r["value"].get("kind") == "device"
    ]
    assert sorted(r["value"]["label"] for r in devices) == ["Dell XPS", "iPad Air"]
    assert all(r["quote"] is None for r in devices)  # explicit: no copied text
    still = next(r for r in stored if r["id"] == legacy.record.assertion_id)
    assert still["state"] == "active"  # existing combined record untouched


# Plans: D6-D11 -----------------------------------------------------------------


def plan_spec(label, quotes, **extra):
    return {
        "category": "plan",
        "intent": extra.pop("intent", "new"),
        "label": label,
        "value": extra.pop("value", label),
        "state": extra.pop("state", "planned"),
        "quotes": quotes,
        **extra,
    }


@pytest.mark.asyncio
async def test_d6_destination_options_leave_the_trip_planned(learning):
    owner = Owner(learning)
    text = "I'm planning a Ladakh or winter Spiti trip in January."
    _plan, _result, _ = await owner.say(
        text,
        [
            plan_spec(
                "Ladakh or winter Spiti trip",
                [text.rstrip(".")],
                plan_status="planned",
                certainty="confirmed",
                time_expression="January",
                slots=PlanSlots(
                    destination=SlotValue(
                        options=["Ladakh", "winter Spiti"], certainty="confirmed"
                    ),
                    when=SlotValue(value="January"),
                ),
            )
        ],
        [("new", None)],
    )
    value = current(await rows(learning))[0]["value"]
    assert value["plan_status"] == "planned" and value["state"] == "planned"
    destination = value["slots"]["destination"]
    assert destination["options"] == ["Ladakh", "winter Spiti"]
    assert destination["value"] is None and destination["certainty"] != "confirmed"
    assert value["slots"]["when"]["value"] == "January"


@pytest.mark.asyncio
async def test_d7_trip_level_uncertainty_is_considering(learning):
    owner = Owner(learning)
    text = "Maybe we'll do Goa this winter."
    await owner.say(
        text,
        [
            plan_spec(
                "Goa",
                ["Maybe we'll do Goa this winter"],
                plan_status="considering",
                certainty="confirmed",
                time_expression="this winter",
            )
        ],
        [("new", None)],
    )
    value = current(await rows(learning))[0]["value"]
    assert value["plan_status"] == "considering" and value["certainty"] == "tentative"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,quote",
    [
        ("Kaza or Manali, which has better fuel stations?", "Kaza or Manali"),
        ("Pack shorts or jeans?", "shorts or jeans"),
    ],
)
async def test_d8_questions_are_not_plans(learning, text, quote):
    owner = Owner(learning)
    plan, _result, _ = await owner.say(
        text,
        [
            plan_spec(
                quote,
                [quote],
                slots=PlanSlots(destination=SlotValue(options=quote.split(" or "))),
            )
        ],
        [("new", None)],
    )
    assert owner.rejected == 1 and plan is None
    assert current(await rows(learning)) == []


@pytest.mark.asyncio
async def test_d9_idiom_without_alternatives_keeps_single_values(learning):
    owner = Owner(learning)
    text = "We're going to Spiti in January, Thar or no Thar."
    await owner.say(
        text,
        [
            plan_spec(
                "Spiti",
                ["We're going to Spiti in January"],
                plan_status="planned",
                time_expression="January",
                slots=PlanSlots(
                    destination=SlotValue(value="Spiti"),
                    when=SlotValue(value="January"),
                ),
            )
        ],
        [("new", None)],
    )
    value = current(await rows(learning))[0]["value"]
    assert "vehicle" not in value["slots"]
    assert value["slots"]["destination"] == {
        "value": "Spiti",
        "options": [],
        "certainty": "confirmed",
    }


@pytest.mark.asyncio
async def test_unspoken_options_are_rejected(learning):
    owner = Owner(learning)
    text = "We're going to Spiti in January."
    await owner.say(
        text,
        [
            plan_spec(
                "Spiti",
                ["We're going to Spiti in January"],
                plan_status="planned",
                slots=PlanSlots(destination=SlotValue(options=["Spiti", "Ladakh"])),
            )
        ],
        [("new", None)],
    )
    assert owner.rejected == 1


@pytest.mark.asyncio
async def test_d10_decision_and_trip_vehicle_never_change_ownership(learning):
    owner, _ = await seed_d1(learning)
    text = "I'm planning a Ladakh or winter Spiti trip."
    await owner.say(
        text,
        [
            plan_spec(
                "trip",
                [text.rstrip(".")],
                plan_status="planned",
                slots=PlanSlots(
                    destination=SlotValue(options=["Ladakh", "winter Spiti"])
                ),
            )
        ],
        [("new", None)],
    )
    owned_before = {
        r["id"]
        for r in current(await rows(learning))
        if r["value"]["category"] == "owned_item"
    }
    text = "We're going with winter Spiti for the trip, and we'll take the Jimny."
    plan, _result, _ = await owner.say(
        text,
        [
            plan_spec(
                "trip",
                [
                    "We're going with winter Spiti for the trip, and we'll take the Jimny"
                ],
                intent="change",
                plan_status="planned",
                slots=PlanSlots(
                    destination=SlotValue(value="winter Spiti"),
                    vehicle=SlotValue(value="Jimny"),
                ),
            ),
            item("Jimny", ["we'll take the Jimny"], intent="change", state="not_owned"),
        ],
        [("match", "trip"), ("match", "Jimny")],
    )
    assert [m.action for m in plan.mutations] == ["change"]
    assert [o.reason for o in plan.outcomes] == ["trip_choice_not_ownership"]
    all_rows = await rows(learning)
    trip = labelled(all_rows, "trip")[0]["value"]
    assert trip["slots"]["destination"]["value"] == "winter Spiti"
    assert trip["slots"]["vehicle"]["value"] == "Jimny"
    owned_after = {
        r["id"] for r in current(all_rows) if r["value"]["category"] == "owned_item"
    }
    assert owned_after == owned_before
    history = [r for r in all_rows if r["value"].get("label") == "trip"]
    assert any(
        r["state"] == "superseded"
        and r["value"]["slots"]["destination"]["options"] == ["Ladakh", "winter Spiti"]
        for r in history
    )


@pytest.mark.asyncio
async def test_d11_cancellation(learning):
    owner = Owner(learning)
    await owner.say(
        "Maybe we'll do Goa this winter.",
        [
            plan_spec(
                "Goa", ["Maybe we'll do Goa this winter"], plan_status="considering"
            )
        ],
        [("new", None)],
    )
    await owner.say(
        "Cancel the Goa plan.",
        [
            plan_spec(
                "Goa",
                ["Cancel the Goa plan"],
                intent="change",
                state="cancelled",
                plan_status="cancelled",
            )
        ],
        [("match", "Goa")],
    )
    value = current(await rows(learning))[0]["value"]
    assert value["plan_status"] == "cancelled" and value["state"] == "cancelled"


# D12 correction ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_d12_correction_retracts_rather_than_refines(learning):
    owner, _ = await seed_d1(learning)
    before = labelled(await rows(learning), "Jimny")[0]
    plan, *_ = await owner.say(
        "I misspoke, the Jimny is from September 2026, not October.",
        [
            item(
                "Jimny",
                ["the Jimny is from September 2026"],
                intent="correction",
                acquired_expression="September 2026",
            )
        ],
        [("match", "Jimny")],
    )
    assert [m.action for m in plan.mutations] == ["correct"]
    all_rows = await rows(learning)
    assert next(r for r in all_rows if r["id"] == before["id"])["state"] == "retracted"
    new = labelled(all_rows, "Jimny")[0]["value"]["acquired"]
    assert new["precision"] == "month" and new["earliest"].startswith("2026-09")


# Identifiers, quotes, admission ------------------------------------------------


@pytest.mark.asyncio
async def test_identifiers_are_kept_out_of_items(learning):
    owner = Owner(learning)
    await owner.say(
        "My scooter is MH 12 AB 1234.",
        [item("MH 12 AB 1234", ["MH 12 AB 1234"])],
        [("new", None)],
    )
    assert owner.rejected == 1
    await owner.say(
        "My Vespa is the blue one, registration KA 05 MN 2021.",
        [
            item(
                "Vespa",
                ["My Vespa is the blue one, registration KA 05 MN 2021"],
                details="registration KA 05 MN 2021",
            )
        ],
        [("new", None)],
    )
    vespa = labelled(await rows(learning), "Vespa")[0]["value"]
    assert "details" not in vespa


def test_quote_is_minimal_and_capped():
    from jarvis.memory.learning_values import minimal_quote

    long_clause = "I have a Vespa " + "and it is lovely " * 40
    assert minimal_quote([long_clause], ["Vespa"]) is None  # over the ceiling
    text = "Work was busy. I have a Vespa. The weather is nice."
    assert minimal_quote([text], ["Vespa"]) == "I have a Vespa."


@pytest.mark.asyncio
async def test_admission_refuses_quotes_not_made_of_the_owners_words(learning):
    from dataclasses import replace

    plan = learning.plan
    forged = replace(
        plan,
        mutations=(
            replace(
                plan.mutations[0],
                source=replace(
                    plan.mutations[0].source, evidence_text="I own a Ferrari"
                ),
            ),
        ),
    )
    with pytest.raises(PermissionError):
        await learning.service.admit_learning(
            forged, learning.authority.issue_child(learning.grant, forged.binding())
        )
    explicit = replace(
        plan.mutations[0].source,
        source_id="explicit-with-quote",
        evidence_text="I own a City",
        source_class=__import__(
            "jarvis.memory.types", fromlist=["MemorySourceClass"]
        ).MemorySourceClass.OWNER_EXPLICIT,
    )
    from jarvis.memory.lifecycle import MemoryLifecycleError

    with pytest.raises(MemoryLifecycleError):
        await learning.lifecycle.create(plan.mutations[0].draft, explicit)


# D24 skipped candidates --------------------------------------------------------


@pytest.mark.asyncio
async def test_d24_ambiguous_candidate_is_recorded_not_saved_or_claimed(learning):
    owner = Owner(learning)
    for when in ("on 1 May 2027", "on 8 May 2027"):
        text = f"We have a paragliding trip {when}."
        await owner.say(
            text,
            [
                plan_spec(
                    "paragliding trip",
                    [text.rstrip(".")],
                    plan_status="planned",
                    time_expression=when.removeprefix("on "),
                )
            ],
            [("new", None)],
        )
    before = await rows(learning)
    assert len(current(before)) == 2
    # "Add Bir to the paragliding trip" cannot be matched to one of the two:
    # the resolver is uncertain, so the candidate is skipped and recorded.
    plan, result, turn = await owner.say(
        "Add Bir to the paragliding trip.",
        [
            plan_spec(
                "paragliding trip",
                ["Add Bir to the paragliding trip"],
                intent="change",
                plan_status="planned",
                slots=PlanSlots(destination=SlotValue(value="Bir")),
            )
        ],
        [("uncertain", None)],
    )
    assert plan.mutations == ()
    assert [o.reason for o in plan.outcomes] == ["uncertain"]
    assert result.status == "recorded" and result.assertion_ids == ()
    assert await rows(learning) == before
    recorded = await learning.reader.run(
        lambda c: c.execute(
            "SELECT category_key, reason_code, source_turn_ref"
            " FROM personal_learning_outcome"
        ).fetchall()
    )
    assert recorded == [
        (
            "plan",
            "uncertain",
            f"conversation:{owner.conversation.session_id}:turn:{turn.turn_id}",
        )
    ]


# D17 / D26 forgetting ----------------------------------------------------------


@pytest.mark.asyncio
async def test_d17_d26_forget_removes_quote_and_leaves_no_residue(learning):
    from dataclasses import replace

    owner, _ = await seed_d1(learning)
    # A later combined quote that names the forgotten item inside another fact.
    text = "My Jimny is parked next to the Royal Enfield Classic 350."
    await owner.say(
        text,
        [
            item(
                "Jimny",
                [text.rstrip(".")],
                details="parked next to the Royal Enfield Classic 350",
            )
        ],
        [("match", "Jimny")],
    )
    target = labelled(await rows(learning), "Royal Enfield Classic 350")[0]
    forget_source = replace(
        learning.plan.mutations[0].source,
        source_id="forget-command",
        evidence_text=None,
    )
    await learning.writer.run(
        lambda c: learning.lifecycle._forget_sync(
            c, target["id"], forget_source, "owner_forget", purge_lineage=True
        )
    )
    after = await rows(learning)
    assert not [r for r in after if r["predicate"] == target["predicate"]]
    others = current(after)
    assert {r["value"]["label"] for r in others} == {"Tata Tigor", "Jimny"}
    assert all("Classic 350" not in (r["quote"] or "") for r in others)
    tigor = labelled(after, "Tata Tigor")[0]
    assert tigor["quote"] == "a Tata Tigor I bought in March 2017"  # unrelated intact
    report = await learning.reader.run(
        lambda c: residual_report(c, ["Royal Enfield Classic 350"])
    )
    jimny_details = labelled(after, "Jimny")[0]["value"].get("details", "")
    # The Jimny's own stored detail still names the other bike: a structured
    # field of another fact, reported, not silently hidden.
    assert report["evidence_quotes"] == 0
    assert report["search_index"] == report["assertion_text"] == 0
    assert report["orphan_embeddings"] == report["learning_outcomes"] == 0
    assert report["assertion_value"] == (1 if "Classic 350" in jimny_details else 0)
    scrubbed = await learning.reader.run(
        lambda c: c.execute(
            "SELECT count(*) FROM memory_operation WHERE reason_code="
            "'evidence_removed_by_forget'"
        ).fetchone()[0]
    )
    assert scrubbed == 1


# D21 history integrity ---------------------------------------------------------


@pytest.mark.asyncio
async def test_d21_history_integrity_after_a_mixed_sequence(learning):
    owner, _ = await seed_d1(learning)
    await owner.say(
        "I bought the Tata Tigor in March 2017, it's the diesel one.",
        [
            item(
                "Tata Tigor",
                ["I bought the Tata Tigor in March 2017, it's the diesel one"],
                details="diesel",
            )
        ],
        [("match", "Tata Tigor")],
    )
    await owner.say(
        "I sold the Tata Tigor last week.",
        [
            item(
                "Tata Tigor",
                ["I sold the Tata Tigor last week"],
                intent="change",
                state="sold",
                disposed_expression="last week",
            )
        ],
        [("match", "Tata Tigor")],
    )
    await owner.say(
        "I misspoke, the Jimny is from September 2026.",
        [
            item(
                "Jimny",
                ["the Jimny is from September 2026"],
                intent="correction",
                acquired_expression="September 2026",
            )
        ],
        [("match", "Jimny")],
    )
    ops = await learning.reader.run(
        lambda c: dict(
            c.execute(
                "SELECT target_id, operation_type FROM memory_operation"
                " WHERE target_kind='semantic_assertion'"
            ).fetchall()
        )
    )
    all_rows = await rows(learning)
    by_id = {r["id"]: r for r in all_rows}
    for row in all_rows:
        if row["supersedes"]:
            old = by_id[row["supersedes"]]
            kind = ops[row["id"]]
            if kind == "refine":
                assert old["state"] == "superseded" and old["valid_to"] is None
            elif kind == "correct":
                assert old["state"] == "retracted"
            elif kind == "historical_change":
                assert old["state"] == "superseded"
    assert all(r["quote"] for r in current(all_rows))  # every current fact has evidence
    orphans = await learning.reader.run(
        lambda c: c.execute(
            "SELECT count(*) FROM memory_source s WHERE NOT EXISTS (SELECT 1 FROM"
            " semantic_assertion a WHERE a.source_id=s.source_id) AND NOT EXISTS"
            " (SELECT 1 FROM memory_operation o WHERE o.source_id=s.source_id)"
        ).fetchone()[0]
    )
    assert orphans == 0


@pytest.mark.asyncio
async def test_voice_forget_path_also_scrubs_quotes(learning):
    from datetime import UTC, datetime

    from jarvis.memory.project_controls import _erase_personal_facts

    owner, _ = await seed_d1(learning)
    text = "My Jimny is parked next to the Tata Tigor."
    await owner.say(
        text,
        [item("Jimny", [text.rstrip(".")], details="parked next to the Tata Tigor")],
        [("match", "Jimny")],
    )
    tigor = labelled(await rows(learning), "Tata Tigor")[0]

    def erase(conn):
        conn.execute("BEGIN IMMEDIATE")
        _erase_personal_facts(conn, [tigor["id"]], [], datetime.now(UTC))
        conn.commit()

    await learning.writer.run(erase)
    after = await rows(learning)
    assert not [r for r in after if r["id"] == tigor["id"]]
    assert all("Tigor" not in (r["quote"] or "") for r in current(after))
    report = await learning.reader.run(lambda c: residual_report(c, ["Tata Tigor"]))
    assert report["evidence_quotes"] == report["search_index"] == 0


# Explicit-list splitter (owner review 2026-11-20 19:32) ------------------------


@pytest.mark.parametrize(
    "predicate,value,status,items,reason",
    [
        # Genuine lists of separate items.
        (
            "devices",
            "a Dell XPS and an iPad Air",
            "items",
            ("Dell XPS", "iPad Air"),
            "",
        ),
        (
            "vehicles",
            "a Hero Splendor, an Ola S1 and a Bajaj Pulsar",
            "items",
            ("Hero Splendor", "Ola S1", "Bajaj Pulsar"),
            "",
        ),
        (
            "vehicles",
            "a Bajaj Chetak; a TVS Jupiter",
            "items",
            ("Bajaj Chetak", "TVS Jupiter"),
            "",
        ),
        ("vehicles", "ek Chetak aur ek Pulsar", "items", ("Chetak", "Pulsar"), ""),
        # A conjunction inside a name or description is kept.
        ("vehicle", "a black and white Vespa", "single", (), ""),
        ("device", "a Bang and Olufsen speaker", "single", (), ""),
        (
            "devices",
            "a Bang and Olufsen speaker",
            "ambiguous",
            (),
            "one_or_several_items",
        ),
        (
            "devices",
            "a Bang and Olufsen speaker and an iPad Air",
            "items",
            ("Bang and Olufsen speaker", "iPad Air"),
            "",
        ),
        (
            "vehicles",
            "a black and white Vespa and a Bajaj Pulsar",
            "items",
            ("black and white Vespa", "Bajaj Pulsar"),
            "",
        ),
        # Shared wording across items cannot stand alone.
        ("vehicles", "a red Chetak and a blue one", "ambiguous", (), "shared_wording"),
        ("devices", "Dell and HP laptops", "ambiguous", (), "one_or_several_items"),
        # Ambiguous boundaries: refuse rather than guess.
        ("vehicles", "a Pulsar and Chetak", "ambiguous", (), "one_or_several_items"),
        (
            "vehicles",
            "a Pulsar, Chetak and Jupiter",
            "ambiguous",
            (),
            "item_boundaries_unclear",
        ),
        # Not a list at all.
        ("vehicles", "a Bajaj Pulsar", "single", (), ""),
        ("home_city", "Pune and Mumbai", "not_a_list", (), ""),
    ],
)
def test_explicit_list_split_only_at_unambiguous_boundaries(
    predicate, value, status, items, reason
):
    from jarvis.voice.memory_tools import _parse_item_list

    parsed = _parse_item_list(predicate, value, f"Remember my {predicate} are {value}.")
    assert (parsed.status, parsed.items, parsed.reason) == (status, items, reason)


class _Approvals:
    def __init__(self):
        self.approvals = []

    def reserve_mutation(self, operation):
        pass

    async def authorize_mutation(self, operation, predicate, value=None, **kw):
        self.approvals.append((operation, predicate, value))

    def validate_mutation_commit(self):
        pass

    def mutation_committed(self):
        pass

    def mutation_failed(self):
        pass


def _tools(learning, text):
    from jarvis.voice.memory_tools import MemoryAgentTools

    conversation = ConversationSession()
    conversation.start()
    conversation.accept_turn(ConversationRole.USER, text)
    personal = _Approvals()
    return MemoryAgentTools(
        learning.service, conversation, personal_context=personal
    ), personal


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value,reason",
    [
        ("a Pulsar and Chetak", "one_or_several_items"),
        ("a red Chetak and a blue one", "shared_wording"),
    ],
)
async def test_ambiguous_list_asks_and_saves_nothing(learning, value, reason):
    before = await rows(learning)
    tools, personal = _tools(learning, f"Remember my vehicles are {value}.")
    receipt = await tools.remember(predicate="vehicles", value=value)
    assert receipt["ok"] is False
    assert receipt["status"] == "clarification_required"
    assert receipt["reason"] == reason and receipt["saved"] == []
    assert personal.approvals == []  # no Windows Hello prompt for a guess
    assert await rows(learning) == before


@pytest.mark.asyncio
async def test_hello_review_shows_exactly_what_is_committed(learning):
    tools, personal = _tools(
        learning, "Remember my vehicles are a Bajaj Chetak and a TVS Jupiter."
    )
    await tools.remember(predicate="vehicles", value="a Bajaj Chetak and a TVS Jupiter")
    tools, personal = _tools(
        learning,
        "Remember my vehicles are a TVS Jupiter, a Bang and Olufsen bike and an Ola S1.",
    )
    receipt = await tools.remember(
        predicate="vehicles",
        value="a TVS Jupiter, a Bang and Olufsen bike and an Ola S1",
    )
    # Already saved items are left out before the review, not after it.
    assert personal.approvals == [
        ("remember", "vehicles", "Bang and Olufsen bike; Ola S1")
    ]
    assert receipt["saved"] == ["Bang and Olufsen bike", "Ola S1"]
    assert receipt["already_saved"] == ["TVS Jupiter"]
    labels = sorted(
        r["value"]["label"]
        for r in current(await rows(learning))
        if isinstance(r["value"], dict)
    )
    assert labels == ["Bajaj Chetak", "Bang and Olufsen bike", "Ola S1", "TVS Jupiter"]


@pytest.mark.asyncio
async def test_commit_refuses_a_set_that_changed_after_review(learning):
    from dataclasses import replace

    from jarvis.memory.service import MemoryServiceError
    from jarvis.memory.types import AuthorityClass, MemorySourceClass

    source = replace(
        learning.plan.mutations[0].source,
        source_id="explicit-items",
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
        evidence_text=None,
    )
    await learning.service.remember_owned_items(
        kind="vehicle", items=("Ola S1",), source=source
    )
    before = await rows(learning)
    with pytest.raises(MemoryServiceError, match="changed before commit"):
        await learning.service.remember_owned_items(
            kind="vehicle", items=("Bajaj Pulsar", "Ola S1"), source=source
        )
    assert await rows(learning) == before  # nothing partial
