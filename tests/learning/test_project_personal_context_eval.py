"""Harness for the personal-context evaluation: real storage, routing, personal
projection and coordinator; fictional data; a scripted fake model. It qualifies
the harness and its failure localisation, not Gemini's behaviour."""

import json
from types import SimpleNamespace

import pytest
from test_project_memory_acceptance_lab import (
    empty_access as empty_access,  # noqa: PLC0414
)
from test_project_personal_acceptance import runtime as acceptance_runtime

from jarvis.voice.project_answer_provider import ProjectAnswerProvider
from jarvis.voice.project_personal_context_eval import (
    QUESTIONS,
    answer_checks,
    run_context_eval,
)

SCOPES = {
    "travel_named_destination": "owned_item.vehicle",
    "travel_ambiguous_followup": "owned_item.vehicle",
    "dinner_after_correction": "food_preference",
}


def scripted(answers, *, request_personal=True):
    """Fake model: asks for the question's scope once, then answers."""
    payloads = []

    class Wire:
        async def parse_with_telemetry(self, **kwargs):
            await kwargs["before_dispatch"]()
            payload = kwargs["input_payload"]
            payloads.append(payload)
            question = next(
                q for q in QUESTIONS if q["question"] == payload["question"]
            )
            if request_personal and payload["available_tools"]["personal_available"]:
                response = {
                    "personal_requests": [{"scope_key": SCOPES[question["id"]]}]
                }
            else:
                response = {"answer": answers[question["id"]]}
            return SimpleNamespace(
                parsed=kwargs["response_model"](response=response),
                usage={},
                usage_observed=False,
                latency_ms=1,
            )

    return ProjectAnswerProvider(Wire()), payloads


GOOD = {
    "travel_named_destination": "For Gokarna the Thar is easiest: about eight "
    "hours on the highway with room for luggage; the scooter's range is too short.",
    "travel_ambiguous_followup": "Which trip do you mean, Gokarna or Spiti?",
    "dinner_after_correction": "Try a quick chickpea and spinach curry with rice.",
}


async def run(
    empty_access,
    authority_parts,
    tmp_path,
    arm,
    answers,
    *,
    personal_session=None,
    case=None,
    **kwargs,
):
    memory, capability, coordinator, _, _ = acceptance_runtime(
        empty_access, authority_parts
    )
    provider, payloads = scripted(answers, **kwargs)
    root = tmp_path / arm
    root.mkdir()
    try:
        summary = await run_context_eval(
            root,
            arm=arm,
            memory=memory,
            capability=capability,
            coordinator=coordinator,
            access=empty_access,
            provider=provider,
            personal_session=personal_session,
            case=case,
        )
    finally:
        coordinator.invalidate("test_end")
    rows = [
        json.loads(line)
        for line in (root / f"context-eval-{arm}.jsonl").read_text().splitlines()
    ]
    return summary, rows, payloads, memory


@pytest.mark.asyncio
async def test_with_facts_records_what_the_model_saw_and_what_was_selected(
    empty_access, authority_parts, tmp_path
):
    summary, rows, payloads, memory = await run(
        empty_access, authority_parts, tmp_path, "with", GOOD
    )
    assert summary["completed"] == [q["id"] for q in QUESTIONS]
    assert summary["first_failures"] == dict.fromkeys(SCOPES)
    mutations = [r for r in rows if r["kind"] == "mutation"]
    assert [m["operation"] for m in mutations] == ["remember", "remember", "correct"]
    questions = {r["question_id"]: r for r in rows if r["kind"] == "question"}
    travel = questions["travel_named_destination"]
    # What the model saw on its final step: the vehicle fact, Spiti history.
    final = travel["steps"][-1]["input_payload"]
    assert final["question"].startswith("I'm going to Gokarna")
    assert final["context"]["personal"]["facts"][0]["text"].startswith("vehicles:")
    assert "Chandigarh" in json.dumps(final["context"])
    assert travel["personal"]["requested_scopes"] == ["owned_item.vehicle"]
    assert travel["personal"]["expected_selected"]
    assert travel["routing"]["stayed_in_selected_project"]
    dinner = questions["dinner_after_correction"]
    assert dinner["personal"]["selected_facts"] == ["diet preference: vegan"]
    assert dinner["personal"]["expected_selected"]
    assert not dinner["personal"]["stale_selected"]
    assert not dinner["personal"]["stale_in_final_context"]
    # The first step of every question carries no personal fact and no rubric.
    for payload in payloads:
        text = json.dumps(payload)
        assert "expected" not in text and "passes" not in text
    # Before any personal query, no vehicle fact reaches the model.
    assert "Thar" not in json.dumps(payloads[0])
    assert (
        await memory.service.inspect_exact(predicate="diet preference")
    ).record.value == "vegan"


@pytest.mark.asyncio
async def test_without_facts_runs_the_same_questions_without_mutations(
    empty_access, authority_parts, tmp_path
):
    answers = {
        **GOOD,
        "travel_named_destination": "For Gokarna, the overnight train or a bus is easiest.",
    }
    summary, rows, _payloads, _ = await run(
        empty_access, authority_parts, tmp_path, "without", answers
    )
    assert not [r for r in rows if r["kind"] == "mutation"]
    questions = [r for r in rows if r["kind"] == "question"]
    assert [q["personal"]["selected_facts"] for q in questions] == [[], [], []]
    assert summary["first_failures"] == dict.fromkeys(SCOPES)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("request_personal", "answers", "question", "stage"),
    [
        (False, GOOD, "travel_named_destination", "personal_request"),
        (
            True,
            {**GOOD, "travel_named_destination": "Fly from Bengaluru to Goa."},
            "travel_named_destination",
            "answer",
        ),
        (
            True,
            {**GOOD, "travel_named_destination": "As for Spiti, the Thar for Gokarna."},
            "travel_named_destination",
            "answer",
        ),
        (
            True,
            {
                **GOOD,
                "dinner_after_correction": "A paneer wrap, since you're vegetarian.",
            },
            "dinner_after_correction",
            "answer",
        ),
        (
            True,
            {**GOOD, "travel_ambiguous_followup": "Yes, take the Thar to Gokarna."},
            "travel_ambiguous_followup",
            "answer",
        ),
    ],
)
async def test_the_first_failing_stage_is_located(
    empty_access, authority_parts, tmp_path, request_personal, answers, question, stage
):
    summary, *_ = await run(
        empty_access,
        authority_parts,
        tmp_path,
        "with",
        answers,
        request_personal=request_personal,
    )
    assert summary["first_failures"][question] == stage


def test_dinner_check_reads_the_current_preference_not_the_word_vegetarian():
    vegan = answer_checks("dinner_after_correction", "with", "A vegan dal, no ghee.")
    assert vegan["non_vegan_terms"] == ["ghee"]  # "no ghee" still flags: manual review
    old = answer_checks("dinner_after_correction", "with", "A vegetarian pulao.")
    assert old["relies_on_old_preference"] and not old["passes"]


@pytest.mark.parametrize(
    "extra", ["--resume-lab", "--seed-acceptance", "--personal-acceptance"]
)
def test_context_eval_requires_a_fresh_standalone_lab(
    tmp_path, monkeypatch, capsys, extra
):
    import sys

    from jarvis.voice.project_memory_lab import main

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lab",
            "--lab-root",
            str(tmp_path / "absent"),
            "--source-commit",
            "a" * 40,
            "--model",
            "fictional",
            "--context-eval",
            extra,
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert (
        "context evaluation requires a fresh standalone lab" in capsys.readouterr().err
    )
    assert not (tmp_path / "absent").exists()


def test_one_arm_runs_alone_in_its_own_new_root(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from jarvis.voice import project_memory_lab as lab

    roots = []
    monkeypatch.setattr(
        lab,
        "prepare_project_profile",
        lambda source, root, **kw: roots.append(root) or root / "machine.json",
    )

    class Env:
        def __init__(self, *a):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(lab, "project_lab_environment", Env)
    arms = []

    async def fake_run(config, root, **kwargs):
        arms.append(kwargs["context_eval_arm"])

    monkeypatch.setattr(lab, "run_text_lab", fake_run)
    import jarvis.config

    monkeypatch.setattr(
        jarvis.config.JarvisConfig,
        "from_environment",
        classmethod(lambda cls: SimpleNamespace(ai_provider="gemini")),
    )
    args = SimpleNamespace(
        lab_root=tmp_path / "profile",
        profile=tmp_path / "live.json",
        source_commit="a" * 40,
        model="fictional",
        context_eval_arm="with",
        context_eval_case=None,
    )
    lab.run_context_eval_mode(args, tmp_path, {})
    assert arms == ["with"]
    assert roots == [tmp_path / "profile" / "with"]
    with pytest.raises(FileExistsError):  # never reuses an earlier root
        lab.run_context_eval_mode(args, tmp_path, {})


def test_context_eval_arm_requires_context_eval(tmp_path, monkeypatch, capsys):
    import sys

    from jarvis.voice.project_memory_lab import main

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "lab",
            "--lab-root",
            str(tmp_path / "absent"),
            "--source-commit",
            "a" * 40,
            "--model",
            "fictional",
            "--context-eval-arm",
            "with",
        ],
    )
    with pytest.raises(SystemExit):
        main()
    assert (
        "--context-eval-arm/--context-eval-case require --context-eval"
        in capsys.readouterr().err
    )
    assert not (tmp_path / "absent").exists()


class StartSession:
    """PersonalReadSession stand-in: approve once, or refuse like Hello did."""

    def __init__(self, refuse=None):
        self.refuse = refuse
        self.opened = 0
        self.calls = 0

    async def active_grant(self):
        self.calls += 1
        if self.refuse:
            try:
                raise RuntimeError(self.refuse)
            except RuntimeError as exc:
                raise PermissionError("learning session was not authorized") from exc
        self.opened += 1
        return object()


@pytest.mark.asyncio
async def test_personal_reads_are_approved_first_and_the_travel_case_runs_alone(
    empty_access, authority_parts, tmp_path
):
    session = StartSession()
    summary, rows, payloads, memory = await run(
        empty_access,
        authority_parts,
        tmp_path,
        "with",
        GOOD,
        personal_session=session,
        case="travel",
    )
    assert rows[0] == {
        **rows[0],
        "kind": "authorization",
        "result": "approved",
        "requested": "at_start",
    }
    assert summary["planned"] == [
        "travel_named_destination",
        "travel_ambiguous_followup",
    ]
    assert summary["not_run"] == ["dinner_after_correction"]
    assert summary["personal_reads"] == "approved_at_start"
    assert [r["operation"] for r in rows if r["kind"] == "mutation"] == ["remember"]
    assert all(p["question"] != QUESTIONS[2]["question"] for p in payloads)
    questions = [r for r in rows if r["kind"] == "question"]
    assert [q["personal_session_opened_total"] for q in questions] == [1, 1]
    from jarvis.memory.service import MemoryNotFoundError

    with pytest.raises(MemoryNotFoundError):  # the diet case never ran
        await memory.service.inspect_exact(predicate="diet preference")


@pytest.mark.asyncio
async def test_a_refused_start_approval_blocks_every_model_call(
    empty_access, authority_parts, tmp_path
):
    session = StartSession(
        refuse="strong owner verification was not granted: user_canceled"
    )
    with pytest.raises(PermissionError):
        await run(
            empty_access,
            authority_parts,
            tmp_path,
            "with",
            GOOD,
            personal_session=session,
            case="travel",
        )
    root = tmp_path / "with"
    rows = [
        json.loads(line)
        for line in (root / "context-eval-with.jsonl").read_text().splitlines()
    ]
    assert rows[0]["kind"] == "authorization"
    assert rows[0]["result"] == "refused"
    assert rows[0]["reason"] == (
        "strong owner verification was not granted: user_canceled"
    )
    blocked = [r for r in rows if r.get("status") == "authorization_blocked"]
    assert [r["question_id"] for r in blocked] == [
        "travel_named_destination",
        "travel_ambiguous_followup",
    ]
    assert not [r for r in rows if r["kind"] in {"seed", "mutation"}]
    summary = json.loads((root / "context-eval-with-summary.json").read_text())
    assert summary["authorization_blocked"] == summary["planned"]
    assert summary["completed"] == []
