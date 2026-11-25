"""D9 follow-up: "meaning unclear" learning outcomes reach the reply path.

The real learning runtime and a fictional database, with the recorded D9
proposals (Paid labs 4 and 6, unmodified apart from evidence turn ids):

- clear parts are stored while the unclear detail stays unresolved, and a
  structured note (the owner's words, the details already known, nothing
  about storage) goes to the reply path;
- only "meaning unclear" makes a note; other skips stay silent;
- a detail is offered once; a later clear answer updates the same plan,
  keeps unrelated details, and settles the note;
- genuine tentative plans and alternatives are stored as before, silently;
- the live follow-up asks once, after the reply, only if the owner has not
  spoken since;
- the admitted limitation (a confidently proposed idiom pair) is pinned.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.learning_clarification import (
    ClarificationBoard,
    LearningClarification,
    unclear_slot_names,
)
from jarvis.memory.learning_contracts import (
    EvidenceSpan,
    LearningBatch,
    LearningCandidate,
    LearningResolution,
    LearningResolutionBatch,
    QuestionAnswer,
)

FIXTURES = Path(__file__).parent / "fixtures"
LAB4 = json.loads((FIXTURES / "paid4_d9_recorded.json").read_text(encoding="utf-8"))
LAB6 = json.loads((FIXTURES / "paid6_d9_recorded.json").read_text(encoding="utf-8"))
FIRST = "We're going to Spiti in January, Thar or no Thar."


def _recorded(recorded, step):
    """The recorded proposals; each cited span is rebound to the replayed
    turn whose text it was recorded against."""
    s = recorded["steps"]
    first_id = s["idiom-01"]["extraction"]["candidates"][0]["evidence"][0]["turn_id"]
    raws = json.loads(json.dumps(s[step]["extraction"]["candidates"]))

    def build(source):
        texts = {t.text: t.turn_id for t in source.turns}
        out = []
        for raw in raws:
            for span in raw["evidence"]:
                said = (
                    s["idiom-01"]["utterance"]
                    if span["turn_id"] == first_id
                    else s[step]["utterance"]
                )
                span["turn_id"] = texts[said]
            out.append(LearningCandidate.model_validate(raw))
        return out

    return build


def _said(text, label, *, slots=None, quote=None, **fields):
    """A fictional proposal citing ``quote`` (default: the whole turn)."""

    def build(source):
        turn = next(t for t in source.turns if t.text == text)
        start = turn.text.index(quote) if quote else 0
        end = start + len(quote) if quote else len(turn.text)
        values = {
            "category": "plan",
            "kind": "other",
            "intent": "new",
            "label": label,
            "value": label,
            "state": "planned",
            "plan_status": "planned",
            "slots": slots,
            **fields,
        }
        values["evidence"] = [EvidenceSpan(turn_id=turn.turn_id, start=start, end=end)]
        return [LearningCandidate(**values)]

    return build


class Script:
    """Extractor: the proposals for each owner utterance, and how it reads an
    answer to an open question (``answers[text] = [(answer, detail)]``)."""

    def __init__(self):
        self.by_text, self.answers, self.questions_seen = {}, {}, []

    async def extract(self, source, open_questions=()):
        self.questions_seen.append(list(open_questions))
        build = self.by_text.get(source.text)
        answers = []
        for answer, detail in self.answers.get(source.text, []):
            for q in open_questions:
                if detail in q.get("choices", {}) or detail in q.get("unclear", []):
                    answers.append(
                        QuestionAnswer(question_id=q["question_id"], answer=answer)
                    )
        return LearningBatch(candidates=build(source) if build else [], answers=answers)


class MatchPlan:
    """Resolver: match the stored plan whose label is in ``targets`` for this
    utterance, else new."""

    def __init__(self):
        self.targets = {}

    async def resolve(self, source, batch, catalog):
        target = self.targets.get(source.text)
        out = []
        for i, _ in enumerate(batch.candidates):
            entry = next(
                (
                    e
                    for e in catalog.entries
                    if target and json.loads(e.value).get("label") == target
                ),
                None,
            )
            out.append(
                LearningResolution(
                    candidate_index=i,
                    decision="match" if entry else "new",
                    target_id=entry.assertion_id if entry else None,
                )
            )
        return LearningResolutionBatch(resolutions=out)


@pytest_asyncio.fixture
async def lab(learning):
    from jarvis.memory.learning_reconciliation import LearningReconciler
    from jarvis.memory.learning_runtime import PersonalLearningRuntime

    script, resolver, seen = Script(), MatchPlan(), []
    runtime = PersonalLearningRuntime(
        learning.authority,
        learning.service,
        script,
        resolver,
        LearningReconciler(learning.service.canonical_reader, learning.authority),
        clock=lambda: 100,
        clarification_observer=seen.append,
    )
    conversation = ConversationSession()
    conversation.start()
    observe = runtime.bind(conversation, learning.grant)

    async def say(text):
        observe(conversation.accept_turn(ConversationRole.USER, text))
        await runtime.drain()

    async def plans():
        rows = await learning.reader.run(
            lambda c: c.execute(
                "SELECT value_json FROM semantic_assertion"
                " WHERE state = 'active' AND predicate LIKE 'plan%'"
            ).fetchall()
        )
        return [json.loads(r[0]) for r in rows]

    h = SimpleNamespace(
        runtime=runtime,
        script=script,
        resolver=resolver,
        seen=seen,
        conversation=conversation,
        say=say,
        plans=plans,
    )
    try:
        yield h
    finally:
        await runtime.close()


# clear parts stored, the unclear detail unresolved and offered -------------


@pytest.mark.asyncio
@pytest.mark.parametrize("recorded", [LAB6, LAB4], ids=["lab6-lone", "lab4-uncertain"])
async def test_recorded_first_turn_stores_the_clear_parts_and_offers_the_unclear_one(
    lab, recorded
):
    lab.script.by_text[FIRST] = _recorded(recorded, "idiom-01")
    await lab.say(FIRST)
    (plan,) = await lab.plans()
    assert plan["plan_status"] == "planned"
    assert plan["slots"]["destination"]["value"] == "Spiti"
    assert "vehicle" not in plan["slots"]
    assert plan["slots"]["when"]["value"] == "January"
    (note,) = lab.seen
    assert (note.category, note.details) == ("plan", ("vehicle",))
    assert note.subject in FIRST  # the owner's words (the grounded label)
    assert "Thar" in note.owner_words
    view = note.model_view()
    assert view["already_known"] == {"destination": "Spiti", "when": "January"}
    assert view["unclear"] == ["vehicle"]
    # The note is not a storage receipt: nothing in it says saved or not.
    assert not {"saved", "stored", "committed", "status"} & set(view)
    assert lab.runtime.clarifications.pending(note.session_id) == [note]


@pytest.mark.asyncio
async def test_a_whole_fact_marked_uncertain_stores_nothing_and_is_offered(lab):
    text = "Maybe Spiti, maybe not, who knows."
    lab.script.by_text[text] = _said(
        text, "Spiti", quote="Spiti", certainty="uncertain", plan_status="considering"
    )
    await lab.say(text)
    assert await lab.plans() == []
    (note,) = lab.seen
    assert note.details == () and note.model_view()["unclear"] == ["what was meant"]
    assert note.owner_words == ("Spiti",)


# only "meaning unclear" makes a note ---------------------------------------


@pytest.mark.asyncio
async def test_other_skips_and_clear_statements_make_no_note(lab):
    # A clear plan; repeating it (no change); an unsaid option (refused by
    # grounding); a question: none of these asks anything.
    clear = "We're going to Spiti in January."
    lab.script.by_text[clear] = _said(
        clear,
        "Spiti",
        slots={"when": {"value": "January", "options": [], "certainty": "confirmed"}},
    )
    await lab.say(clear)
    lab.resolver.targets[clear] = "Spiti"
    await lab.say(clear)
    unsaid = "We might go to Spiti."
    lab.script.by_text[unsaid] = _said(
        unsaid,
        "Spiti",
        plan_status="considering",
        slots={
            "vehicle": {"value": None, "options": ["Jimny"], "certainty": "tentative"}
        },
    )
    await lab.say(unsaid)
    # Lab 4's second turn (evidence only in the earlier turn): unsupported.
    lab.script.by_text["Either way, January."] = _recorded(LAB4, "idiom-02")
    await lab.say("Either way, January.")
    assert lab.seen == []
    assert len(await lab.plans()) == 1


@pytest.mark.asyncio
async def test_the_same_unclear_detail_is_offered_once(lab):
    lab.script.by_text[FIRST] = _recorded(LAB6, "idiom-01")
    lab.resolver.targets[FIRST] = "Spiti"
    await lab.say(FIRST)
    await lab.say(FIRST)
    assert len(lab.seen) == 1


# clarification: a later clear answer updates the same plan -----------------


@pytest.mark.asyncio
async def test_a_later_clear_answer_updates_the_same_plan_and_settles_the_note(lab):
    lab.script.by_text[FIRST] = _recorded(LAB6, "idiom-01")
    await lab.say(FIRST)
    (note,) = lab.seen
    answer = "We'll take the Thar."

    # The label "Spiti" is cited from the first turn, the vehicle from the
    # answer (as the extractor does for a follow-up).
    def build(source):
        first = next(t for t in source.turns if t.text == FIRST)
        current = source.turns[-1]
        at = FIRST.index("Spiti")
        return [
            LearningCandidate(
                category="plan",
                kind="other",
                intent="new",
                label="Spiti",
                value="Spiti",
                state="planned",
                plan_status="planned",
                slots={
                    "vehicle": {
                        "value": "Thar",
                        "options": [],
                        "certainty": "confirmed",
                    }
                },
                evidence=[
                    EvidenceSpan(turn_id=first.turn_id, start=at, end=at + 5),
                    EvidenceSpan(
                        turn_id=current.turn_id, start=0, end=len(current.text)
                    ),
                ],
            )
        ]

    lab.script.by_text[answer] = build
    lab.resolver.targets[answer] = "Spiti"
    await lab.say(answer)
    (plan,) = await lab.plans()
    assert plan["slots"]["vehicle"] == {
        "value": "Thar",
        "options": [],
        "certainty": "confirmed",
    }
    assert plan["slots"]["when"]["value"] == "January"
    assert plan["slots"]["destination"]["value"] == "Spiti"
    assert lab.runtime.clarifications.pending(note.session_id) == []
    assert len(lab.seen) == 1  # nothing new to ask


# plan alternatives wait for the owner (amendment 2) -------------------------

CHOICE = "We're going to Spiti in January, Thar or Jimny."


def _choice(text=CHOICE, options=("Thar", "Jimny"), certainty="confirmed"):
    return _said(
        text,
        "Spiti",
        slots={
            "destination": {"value": "Spiti", "options": [], "certainty": "confirmed"},
            "when": {"value": "January", "options": [], "certainty": "confirmed"},
            "vehicle": {
                "value": None,
                "options": list(options),
                "certainty": certainty,
            },
        },
    )


def _decision(text, value):
    """A follow-up stating the vehicle: label cited from the plan's first turn,
    the value from the current turn."""

    def build(source):
        first = next(t for t in source.turns if "Spiti" in t.text)
        current = source.turns[-1]
        at = first.text.index("Spiti")
        return [
            LearningCandidate(
                category="plan",
                kind="other",
                intent="new",
                label="Spiti",
                value="Spiti",
                state="planned",
                plan_status="planned",
                slots={
                    "vehicle": {"value": value, "options": [], "certainty": "confirmed"}
                },
                evidence=[
                    EvidenceSpan(turn_id=first.turn_id, start=at, end=at + 5),
                    EvidenceSpan(
                        turn_id=current.turn_id, start=0, end=len(current.text)
                    ),
                ],
            )
        ]

    return build


async def _rows(learning_reader):
    rows = await learning_reader.run(
        lambda c: c.execute(
            "SELECT state, value_json FROM semantic_assertion"
            " WHERE predicate LIKE 'plan%' ORDER BY assertion_rowid"
        ).fetchall()
    )
    return [(r[0], json.loads(r[1])) for r in rows]


@pytest.mark.asyncio
@pytest.mark.parametrize("certainty", ["confirmed", "tentative"])
async def test_alternatives_wait_for_the_owner_whatever_the_certainty(lab, certainty):
    lab.script.by_text[CHOICE] = _choice(certainty=certainty)
    await lab.say(CHOICE)
    (plan,) = await lab.plans()
    assert "vehicle" not in plan["slots"]  # pending, not stored
    assert plan["slots"]["when"]["value"] == "January"  # clear parts saved
    assert plan["slots"]["destination"]["value"] == "Spiti"
    (note,) = lab.seen
    view = note.model_view()
    assert view["question"] == "confirm_alternatives"
    assert view["choices"] == {"vehicle": ["Thar", "Jimny"]}
    assert view["already_known"] == {"destination": "Spiti", "when": "January"}
    assert not {"saved", "stored", "status"} & set(view)


@pytest.mark.asyncio
async def test_tentative_plans_and_stated_details_save_without_a_question(lab):
    maybe = "Maybe we'll do Goa this winter."
    lab.script.by_text[maybe] = _said(
        maybe, "Goa", quote="Goa", certainty="tentative", plan_status="considering"
    )
    stated = "We're going to Spiti in January in the Jimny."
    lab.script.by_text[stated] = _said(
        stated,
        "Spiti",
        slots={"vehicle": {"value": "Jimny", "options": [], "certainty": "confirmed"}},
    )
    await lab.say(maybe)
    await lab.say(stated)
    plans = {p["label"]: p for p in await lab.plans()}
    assert plans["Goa"]["plan_status"] == "considering"
    assert plans["Spiti"]["slots"]["vehicle"]["value"] == "Jimny"
    assert lab.seen == []


@pytest.mark.asyncio
async def test_confirmation_saves_the_alternatives_undecided_on_the_same_plan(
    lab, learning
):
    lab.script.by_text[CHOICE] = _choice()
    await lab.say(CHOICE)
    (question,) = lab.seen
    yes = "Yes, still deciding."
    lab.script.answers[yes] = [("confirmed", "vehicle")]
    lab.resolver.targets[yes] = "Spiti"
    await lab.say(yes)
    # The extractor was told the open question, in the owner's words.
    assert lab.script.questions_seen[-1] == [question.model_view()]
    (plan,) = await lab.plans()
    assert plan["slots"]["vehicle"] == {
        "value": None,
        "options": ["Thar", "Jimny"],
        "certainty": "tentative",
    }
    assert plan["slots"]["when"]["value"] == "January"  # unrelated kept
    assert plan["slots"]["destination"]["value"] == "Spiti"
    # The same plan: the earlier row is superseded (history), not retracted.
    states = [state for state, value in await _rows(learning.reader)]
    assert states == ["superseded", "active"]
    assert lab.runtime.clarifications.pending(question.session_id) == []
    assert len(lab.seen) == 1  # nothing asked again
    # Restating confirmed alternatives does not ask again.
    lab.resolver.targets[CHOICE] = "Spiti"
    await lab.say(CHOICE)
    assert len(lab.seen) == 1


@pytest.mark.asyncio
async def test_a_final_choice_saves_the_decision_on_the_same_plan(lab, learning):
    lab.script.by_text[CHOICE] = _choice()
    await lab.say(CHOICE)
    (question,) = lab.seen
    take = "We'll take the Jimny."
    lab.script.by_text[take] = _decision(take, "Jimny")
    lab.script.answers[take] = [("chosen", "vehicle")]
    lab.resolver.targets[take] = "Spiti"
    await lab.say(take)
    (plan,) = await lab.plans()
    assert plan["slots"]["vehicle"] == {
        "value": "Jimny",
        "options": [],
        "certainty": "confirmed",
    }
    assert plan["slots"]["when"]["value"] == "January"
    assert [s for s, _ in await _rows(learning.reader)] == ["superseded", "active"]
    assert lab.runtime.clarifications.pending(question.session_id) == []


@pytest.mark.asyncio
async def test_doesnt_matter_discards_the_pending_detail(lab):
    lab.script.by_text[CHOICE] = _choice()
    await lab.say(CHOICE)
    (question,) = lab.seen
    whatever = "Doesn't matter, either is fine."
    lab.script.answers[whatever] = [("doesnt_matter", "vehicle")]
    await lab.say(whatever)
    assert lab.runtime.clarifications.pending(question.session_id) == []
    # A later "yes" has nothing left to confirm.
    yes = "Yes, still deciding."
    lab.script.answers[yes] = [("confirmed", "vehicle")]
    await lab.say(yes)
    assert lab.script.questions_seen[-1] == []
    (plan,) = await lab.plans()
    assert "vehicle" not in plan["slots"]
    assert plan["slots"]["when"]["value"] == "January"


@pytest.mark.asyncio
async def test_an_unrelated_reply_or_conversation_end_leaves_it_unsaved(lab, learning):
    lab.script.by_text[CHOICE] = _choice()
    await lab.say(CHOICE)
    (question,) = lab.seen
    await lab.say("What's the weather like there in January?")
    (plan,) = await lab.plans()
    assert "vehicle" not in plan["slots"]
    # Still open in this conversation, never asked twice.
    assert lab.runtime.clarifications.pending(question.session_id) == [question]
    assert lab.runtime.clarifications.take(question.session_id) == [question]
    assert lab.runtime.clarifications.take(question.session_id) == []
    # A new conversation does not carry the question: a "yes" there saves nothing.
    other = ConversationSession()
    other.start()
    observe = lab.runtime.bind(other, learning.grant)
    yes = "Yes, still deciding."
    lab.script.answers[yes] = [("confirmed", "vehicle")]
    observe(other.accept_turn(ConversationRole.USER, yes))
    await lab.runtime.drain()
    assert lab.script.questions_seen[-1] == []
    (plan,) = await lab.plans()
    assert "vehicle" not in plan["slots"]


@pytest.mark.asyncio
async def test_a_confident_idiom_pair_is_held_and_either_way_discards_it(lab):
    """Paid lab 6's second-turn shape (["Thar", "no Thar"], tentative) proposed
    on the first turn: it is no longer stored. Jarvis asks once; "Either way,
    January." read as doesnt_matter discards it."""
    pair = LAB6["steps"]["idiom-02"]["extraction"]["candidates"][0]["slots"]["vehicle"]
    assert pair == {
        "value": None,
        "options": ["Thar", "no Thar"],
        "certainty": "tentative",
    }
    lab.script.by_text[FIRST] = _choice(FIRST, ("Thar", "no Thar"), "tentative")
    await lab.say(FIRST)
    (plan,) = await lab.plans()
    assert "vehicle" not in plan["slots"]
    (question,) = lab.seen
    assert question.model_view()["choices"] == {"vehicle": ["Thar", "no Thar"]}
    either = "Either way, January."
    lab.script.answers[either] = [("doesnt_matter", "vehicle")]
    await lab.say(either)
    (plan,) = await lab.plans()
    assert "vehicle" not in plan["slots"]
    assert plan["slots"]["when"]["value"] == "January"
    assert lab.runtime.clarifications.pending(question.session_id) == []


@pytest.mark.asyncio
async def test_d9_understood_needs_no_question(lab):
    lab.script.by_text[FIRST] = _said(
        FIRST,
        "Spiti",
        slots={"when": {"value": "January", "options": [], "certainty": "confirmed"}},
    )
    await lab.say(FIRST)
    (plan,) = await lab.plans()
    assert "vehicle" not in plan["slots"]
    assert lab.seen == []


@pytest.mark.asyncio
async def test_the_model_cannot_confirm_alternatives_itself():
    from jarvis.memory.learning_extractors import (
        LearningProviderAdapter,
        _ProviderBatch,
        _ProviderBatchWithAnswers,
    )

    assert "owner_confirmed" not in json.dumps(_ProviderBatch.model_json_schema())
    assert "owner_confirmed" not in json.dumps(
        _ProviderBatchWithAnswers.model_json_schema()
    )
    c = ConversationSession()
    c.start()
    turn = c.accept_turn(ConversationRole.USER, CHOICE)
    from jarvis.memory.learning_contracts import AcceptedLearningSource

    source = AcceptedLearningSource.from_turn("runtime", c, turn, now=100)
    adapter = LearningProviderAdapter("gemini", object(), "model")
    sent = []

    async def request(prompt, payload, schema, **_):
        sent.append((prompt, payload, schema))
        out = {
            "candidates": [
                {
                    "category": "plan",
                    "intent": "new",
                    "label": "Spiti",
                    "value": "Spiti",
                    "state": "planned",
                    "plan_status": "planned",
                    "slots": {
                        "vehicle": {
                            "options": ["Thar", "Jimny"],
                            "certainty": "confirmed",
                        }
                    },
                    # A model cannot confirm on the owner's behalf: dropped.
                    "owner_confirmed": ["vehicle"],
                    "evidence": [{"turn_id": turn.turn_id, "quote": CHOICE}],
                }
            ]
        }
        if "open_questions" in payload:
            out["open_question_answers"] = [
                {"question_id": "q-known", "answer": "confirmed"},
                {"question_id": "q-unknown", "answer": "confirmed"},
            ]
        return out

    adapter._request = request
    plain = await adapter.extract(source)
    assert plain.candidates[0].owner_confirmed == () and plain.answers == []
    prompt, payload, schema = sent[0]
    assert (
        "open_questions" not in payload
        and "open_question_answers" not in json.dumps(schema)
    )
    asked = await adapter.extract(
        source, open_questions=[{"question_id": "q-known", "question": "x"}]
    )
    prompt2, payload, schema = sent[1]
    assert "open_questions lists details" in prompt2
    assert "open_questions lists details" not in prompt
    assert payload["open_questions"] == [{"question_id": "q-known", "question": "x"}]
    answer_schema = schema["$defs"]["_ProviderAnswer"]["properties"]["question_id"]
    assert answer_schema["enum"] == ["q-known"]
    assert [a.answer for a in asked.answers] == ["confirmed"]
    assert asked.candidates[0].owner_confirmed == ()


# structure (no wording) -------------------------------------------------------


def test_unclear_details_come_from_the_proposals_own_structure():
    from jarvis.memory.learning_contracts import PlanSlots

    def slots(**kw):
        return PlanSlots.model_validate(kw)

    lone = {"value": None, "options": ["X"], "certainty": "tentative"}
    pair = {"value": None, "options": ["X", "Y"], "certainty": "tentative"}
    unsure = {"value": "X", "options": [], "certainty": "uncertain"}
    clear = {"value": "X", "options": [], "certainty": "confirmed"}
    assert unclear_slot_names(slots(vehicle=lone)) == ("vehicle",)
    assert unclear_slot_names(slots(stay=unsure)) == ("stay",)
    assert unclear_slot_names(slots(vehicle=pair, when=clear)) == ()
    assert unclear_slot_names(None) == ()


def _note(session="s1", turn="t1", details=("vehicle",), subject="Spiti"):
    return LearningClarification(
        session, turn, "plan", subject, details, ("Thar",), (("when", "January"),)
    )


def test_board_offers_once_settles_and_clears():
    board = ClarificationBoard(limit=2)
    note = _note()
    assert board.offer(note) and not board.offer(_note(turn="t2"))
    board.resolve("s1", "plan", "spiti", {"vehicle"})
    assert board.pending("s1") == []
    assert board.offer(_note(turn="t3"))  # unclear afresh after settling
    assert board.take("s1", "t3") and board.take("s1", "t3") == []
    for i in range(3):
        board.offer(_note(subject=f"p{i}"))
    assert len(board.pending("s1")) == 2  # bounded
    board.clear("s1")
    assert board.pending("s1") == [] and board.offer(note)


# the live follow-up ------------------------------------------------------------


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _follow_up(board, conversation, *, idle):
    from jarvis.voice.learning_followup import LearningFollowUp

    clock, asked = Clock(), []

    async def deliver(notes):
        asked.append(notes)
        return True

    async def sleep(seconds):
        clock.now += seconds
        await asyncio.sleep(0)

    follow = LearningFollowUp(
        board, conversation, deliver, idle=idle, clock=clock, sleep=sleep, max_wait=2
    )
    return follow, asked


def _live():
    c = ConversationSession()
    c.start()
    turn = c.accept_turn(ConversationRole.USER, FIRST)
    return c, turn


@pytest.mark.asyncio
async def test_follow_up_asks_once_after_the_reply_finishes():
    c, turn = _live()
    board = ClarificationBoard()
    note = _note(c.session_id, turn.turn_id)
    states = iter([False, False, True])  # Jarvis still speaking, then idle
    follow, asked = _follow_up(board, c, idle=lambda: next(states, True))
    board.offer(note)
    follow.offer(note)
    await asyncio.sleep(0.05)
    assert asked == [[note]]
    follow.offer(note)  # already taken: never asked twice
    await asyncio.sleep(0.05)
    assert asked == [[note]]
    await follow.close()


@pytest.mark.asyncio
async def test_follow_up_is_not_asked_once_the_owner_moved_on_or_never_idle():
    c, turn = _live()
    board = ClarificationBoard()
    note = _note(c.session_id, turn.turn_id)
    board.offer(note)
    follow, asked = _follow_up(board, c, idle=lambda: False)
    follow.offer(note)
    await asyncio.sleep(0.05)  # gave up after max_wait
    c.accept_turn(ConversationRole.USER, "What about hotels?")
    follow.offer(note)  # the owner has spoken since
    await asyncio.sleep(0.05)
    other = _note("another-session", turn.turn_id)
    follow.offer(other)
    await asyncio.sleep(0.05)
    assert asked == []
    await follow.close()


@pytest.mark.asyncio
async def test_follow_up_waits_and_drops_if_the_owner_speaks_meanwhile():
    c, turn = _live()
    board = ClarificationBoard()
    note = _note(c.session_id, turn.turn_id)
    board.offer(note)
    calls = {"n": 0}

    def idle():
        calls["n"] += 1
        if calls["n"] == 2:
            c.accept_turn(ConversationRole.USER, "Actually, one more thing.")
        return calls["n"] > 3

    follow, asked = _follow_up(board, c, idle=idle)
    follow.offer(note)
    await asyncio.sleep(0.05)
    assert asked == []
    await follow.close()


@pytest.mark.asyncio
async def test_the_note_is_injected_as_a_labelled_exchange_and_a_reply_requested(
    monkeypatch,
):
    import sys

    from jarvis.voice.learning_followup import (
        FOLLOW_UP_REQUEST,
        NOTE_PREFIX,
        inject_learning_note,
    )

    class Message:
        def __init__(self, *, id, role, content):
            self.id, self.role, self.content = id, role, content

    class Context:
        def __init__(self, items):
            self.items = items

    import types

    llm = sys.modules.get("livekit.agents.llm")
    if llm is None:  # environment without livekit
        llm = types.ModuleType("livekit.agents.llm")
        monkeypatch.setitem(sys.modules, "livekit.agents.llm", llm)
    monkeypatch.setattr(llm, "ChatMessage", Message, raising=False)
    monkeypatch.setattr(llm, "ChatContext", Context, raising=False)

    class Ctx:
        def __init__(self, items=None):
            self.items = list(items or [])

        def copy(self):
            return Ctx(self.items)

    class Agent:
        chat_ctx = Ctx()

        async def update_chat_ctx(self, ctx):
            self.chat_ctx = ctx

    class Session:
        def __init__(self):
            self.current_agent, self.requested = Agent(), []

        def generate_reply(self, **kwargs):
            self.requested.append(kwargs)

    session, registered = Session(), []
    assert await inject_learning_note(session, [_note()], register=registered.append)
    roles = [m.role for m in session.current_agent.chat_ctx.items]
    texts = [m.content[0] for m in session.current_agent.chat_ctx.items]
    assert roles == ["user", "assistant", "user"]
    assert texts[0].startswith(NOTE_PREFIX) and '"owner_words": ["Thar"]' in texts[0]
    assert texts[2] == FOLLOW_UP_REQUEST
    assert "saved" not in texts[0] and "mention memory or saving" in FOLLOW_UP_REQUEST
    # No generate_reply instructions (sent as model-role text, echo risk).
    assert session.requested == [{"allow_interruptions": True}]
    assert len(registered) == 1


def test_reply_instructions_explain_the_note_and_forbid_storage_claims():
    from jarvis.voice.agent import PERSONAL_LEARNING_QUERY_INSTRUCTIONS as text

    flat = " ".join(text.split())
    assert "A learning_note (from Jarvis, not speech from the owner)" in flat
    assert "Never ask about already_known details" in flat
    assert "Do not say anything was or was not saved" in flat


@pytest.mark.asyncio
async def test_live_session_wiring_offers_notes_only_while_that_session_is_open():
    module = pytest.importorskip("jarvis.voice.canonical_active_speaker_runtime")
    from jarvis.conversation import ConversationStatus

    c, _turn = _live()
    board = ClarificationBoard()
    learning = SimpleNamespace(clarifications=board, clarification_observer=None)
    closers = []
    bridge = SimpleNamespace(
        conversation=c,
        register_restored_context=lambda ctx: None,
        add_close_observer=closers.append,
    )
    session = object()
    runtime = SimpleNamespace(
        _personal_learning=learning,
        _live_session=session,
        _user_is_speaking=False,
        _agent_state="speaking",
    )
    cls = module.CanonicalActiveSpeakerRuntimeController
    cls._attach_learning_follow_up(runtime, session, bridge)
    observer = learning.clarification_observer
    assert observer is not None and len(closers) == 1
    assert c.status is ConversationStatus.ACTIVE
    for close in closers:
        close()
    await asyncio.sleep(0)
    assert learning.clarification_observer is None


def test_one_open_question_per_detail():
    board = ClarificationBoard()
    unclear = _note()
    assert board.offer(unclear)
    alternatives = LearningClarification(
        "s1",
        "t2",
        "plan",
        "Spiti",
        ("vehicle",),
        ("Thar", "no Thar"),
        kind="confirm_alternatives",
        choices=(("vehicle", ("Thar", "no Thar")),),
    )
    assert not board.offer(alternatives)  # the vehicle is already being asked
    other = LearningClarification(
        "s1",
        "t2",
        "plan",
        "Spiti",
        ("stay",),
        ("hotel", "homestay"),
        kind="confirm_alternatives",
        choices=(("stay", ("hotel", "homestay")),),
    )
    assert board.offer(other)
