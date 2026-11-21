"""Offline verification of the slice-1 development acceptance harness.

A scripted model stands in for Gemini (extraction, resolution and the text
driver); everything else is the real runtime: learning queue, policy,
reconciler, admission, projection, paging, permits, memory tools and the
harness's own checks and result files. This proves the harness wiring, the
checks, interruption and resume; it says nothing about the real model.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.capabilities.discovery import CapabilityResolver
from jarvis.capabilities.runtime import CapabilityRuntime
from jarvis.memory.learning_extractors import (
    EXTRACTION_PROMPT,
    LearningProviderAdapter,
)
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.query import CanonicalMemoryReader
from jarvis.memory.runtime import MemoryRuntime
from jarvis.memory.service import MemoryService
from jarvis.memory.worker import SerialConnectionWorker
from jarvis.voice import personal_memory_acceptance as acceptance

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def owner_timezone(monkeypatch):
    # The PC runs in IST; "local" dates in the learning input use it. Where
    # the process zone cannot be switched (Windows CI), the frozen told times
    # (10:00-15:00 IST) fall on the same calendar date in UTC anyway.
    if not hasattr(time, "tzset"):
        yield
        return
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    time.tzset()
    yield
    monkeypatch.delenv("TZ")
    time.tzset()


def item(label, quote, **extra):
    return {
        "category": "owned_item",
        "kind": extra.pop("kind", "vehicle"),
        "intent": extra.pop("intent", "new"),
        "label": label,
        "value": label,
        "state": extra.pop("state", "owned"),
        "certainty": "confirmed",
        "quote": quote,
        **extra,
    }


def plan(label, quote, **extra):
    return {
        "category": "plan",
        "kind": "other",
        "intent": extra.pop("intent", "new"),
        "label": label,
        "value": label,
        "state": extra.pop("state", "planned"),
        "certainty": extra.pop("certainty", "confirmed"),
        "quote": quote,
        **extra,
    }


def slot(value=None, options=(), certainty="confirmed"):
    return {"value": value, "options": list(options), "certainty": certainty}


EXTRACT = {
    "We're planning a Rishikesh trip in October 2026.": [
        plan(
            "Rishikesh trip",
            "We're planning a Rishikesh trip in October 2026.",
            plan_status="planned",
            time_expression="October 2026",
            slots={"when": slot("October 2026")},
        )
    ],
    "I have a Royal Enfield Classic 350 from 2021, a Tata Tigor I bought in March 2017, and last month I got a Jimny.": [
        item(
            "Royal Enfield Classic 350",
            "I have a Royal Enfield Classic 350 from 2021",
            acquired_expression="2021",
        ),
        item(
            "Tata Tigor",
            "a Tata Tigor I bought in March 2017",
            acquired_expression="March 2017",
        ),
        item("Jimny", "last month I got a Jimny", acquired_expression="last month"),
    ],
    "I bought the Tigor in March 2017, it's the diesel one.": [
        item(
            "Tigor",
            "I bought the Tigor in March 2017, it's the diesel one.",
            details="diesel",
            acquired_expression="March 2017",
        )
    ],
    "I sold the Tigor last week.": [
        item(
            "Tigor",
            "I sold the Tigor last week.",
            intent="change",
            state="sold",
            disposed_expression="last week",
        )
    ],
    "I'm planning a Ladakh or winter Spiti trip in January.": [
        plan(
            "Ladakh or winter Spiti trip",
            "I'm planning a Ladakh or winter Spiti trip in January.",
            plan_status="planned",
            certainty="tentative",
            slots={
                "destination": slot(options=("Ladakh", "winter Spiti")),
                "when": slot("January"),
            },
        )
    ],
    "Maybe we'll do Goa this winter.": [
        plan(
            "Goa",
            "Maybe we'll do Goa this winter.",
            plan_status="considering",
            certainty="tentative",
            slots={"when": slot("this winter", certainty="tentative")},
        )
    ],
    "We're going with winter Spiti, and we'll take the Jimny.": [
        plan(
            "winter Spiti",
            "We're going with winter Spiti, and we'll take the Jimny.",
            intent="change",
            plan_status="planned",
            slots={"destination": slot("winter Spiti"), "vehicle": slot("Jimny")},
        )
    ],
    "Cancel the Goa plan.": [
        plan(
            "Goa",
            "Cancel the Goa plan.",
            intent="change",
            state="cancelled",
            plan_status="cancelled",
        )
    ],
    "I misspoke, the Jimny is from September, not October.": [
        item(
            "Jimny",
            "I misspoke, the Jimny is from September, not October.",
            intent="correction",
            acquired_expression="September",
        )
    ],
    "I sold the Classic 350 in October.": [
        item(
            "Classic 350",
            "I sold the Classic 350 in October.",
            intent="change",
            state="sold",
            disposed_expression="October",
        )
    ],
    "We're going to Spiti in January, Thar or no Thar.": [
        plan(
            "Spiti",
            "We're going to Spiti in January",
            plan_status="planned",
            slots={"destination": slot("Spiti"), "when": slot("January")},
        )
    ],
    "I just bought a Hero Xoom scooter.": [
        item("Hero Xoom scooter", "I just bought a Hero Xoom scooter.")
    ],
    "Add Bir to the paragliding trip.": [
        plan(
            "paragliding trip",
            "Add Bir to the paragliding trip.",
            intent="change",
            plan_status="planned",
            slots={"destination": slot("Bir")},
        )
    ],
}

RESOLVE = {
    "I bought the Tigor in March 2017, it's the diesel one.": [("match", "tigor")],
    "I sold the Tigor last week.": [("match", "tigor")],
    "I'm planning a Ladakh or winter Spiti trip in January.": [("new", None)],
    "Maybe we'll do Goa this winter.": [("new", None)],
    "We're going with winter Spiti, and we'll take the Jimny.": [("match", "ladakh")],
    "Cancel the Goa plan.": [("match", "goa")],
    "I misspoke, the Jimny is from September, not October.": [("match", "jimny")],
    "I sold the Classic 350 in October.": [("match", "classic")],
}


class FakeGenai:
    """Scripted Gemini for the learning adapter (extraction + resolution)."""

    def __init__(self):
        self.calls = []
        self.fail_on = set()
        self.aio = SimpleNamespace(interactions=SimpleNamespace(create=self.create))

    async def create(self, *, model, input, system_instruction, **_):
        payload = json.loads(input)
        current = next(
            t for t in payload["turns"] if t["turn_id"] == payload["current_turn_id"]
        )
        text = current["text"]
        stage = (
            "extraction" if system_instruction == EXTRACTION_PROMPT else "resolution"
        )
        self.calls.append((stage, text))
        if text in self.fail_on:
            raise RuntimeError("fictional 429 quota")
        if stage == "extraction":
            proposals = []
            for proposal in EXTRACT.get(text, []):
                proposal = dict(proposal)
                quote = proposal.pop("quote")
                turn = next(t for t in payload["turns"] if quote in t["text"])
                proposals.append(
                    {
                        **proposal,
                        "evidence": [{"turn_id": turn["turn_id"], "quote": quote}],
                    }
                )
            out = {"candidates": proposals}
        else:
            entries = payload["catalog"]["entries"]
            resolutions = []
            for index, (decision, needle) in enumerate(RESOLVE.get(text, [])):
                target = None
                if needle:
                    target = next(
                        e["assertion_id"]
                        for e in entries
                        if needle in json.loads(e["value"]).get("label", "").casefold()
                    )
                resolutions.append(
                    {
                        "candidate_index": index,
                        "decision": decision,
                        "target_id": target,
                    }
                )
            out = {"resolutions": resolutions}
        return SimpleNamespace(output_text=json.dumps(out), usage=None)


DRIVER = {
    "We're planning a Rishikesh trip in October 2026.": ("answer", "Sounds lovely."),
    "I have a Royal Enfield Classic 350 from 2021, a Tata Tigor I bought in March 2017, and last month I got a Jimny.": (
        "answer",
        "Understood.",
    ),
    "I bought the Tigor in March 2017, it's the diesel one.": ("answer", "Got it."),
    "I sold the Tigor last week.": ("answer", "Understood."),
    "When did I sell it?": (
        "read",
        ["owned_item.vehicle"],
        "You sold the Tigor last week, around 9 to 15 November.",
    ),
    "Which vehicles do I own?": ("read", ["owned_item.vehicle"], None),
    "I'm planning a Ladakh or winter Spiti trip in January.": ("answer", "Nice."),
    "Maybe we'll do Goa this winter.": ("answer", "Okay."),
    "Kaza or Manali, which has better fuel stations?": (
        "answer",
        "Manali has more fuel stations.",
    ),
    "We're going with winter Spiti, and we'll take the Jimny.": (
        "answer",
        "Great choice.",
    ),
    "Cancel the Goa plan.": ("answer", "Understood."),
    "I misspoke, the Jimny is from September, not October.": ("answer", "Understood."),
    "What's coming up?": (
        "read",
        ["plan"],
        "The Rishikesh trip's October date has passed; I don't know whether it happened.",
    ),
    "Which vehicles do I own and since when?": (
        "read",
        ["owned_item.vehicle"],
        "The Classic 350 since 2021 and the Jimny since September 2026. You sold the Tigor.",
    ),
    "Which of my vehicles is best for a snowy Spiti trip?": (
        "read",
        ["owned_item.vehicle", "plan"],
        "The Jimny, for winter Spiti.",
    ),
    "How do you know I have a Jimny, and when did I tell you?": (
        "read",
        ["owned_item.vehicle"],
        "You said 'last month I got a Jimny'; it is from September.",
    ),
    "I sold the Classic 350 in October.": ("answer", "Understood."),
    "Forget the Classic 350.": ("forget", "classic", "Forgotten."),
    "Remember my devices are a Dell XPS and an iPad Air.": (
        "remember",
        "devices",
        "a Dell XPS and an iPad Air",
        "Saved both.",
    ),
    "Should I service my bike before the trip?": (
        "read",
        ["owned_item.vehicle", "plan"],
        "Which bike: the Classic 350 or the Pulsar 150?",
    ),
    "We're going to Spiti in January, Thar or no Thar.": ("answer", "Okay."),
    "Either way, January.": ("answer", "January it is."),
    "I just bought a Hero Xoom scooter.": ("answer", "Nice."),
    "What trips am I planning?": ("read", ["plan"], None),
    "Add Bir to the paragliding trip.": (
        "answer",
        "Which paragliding trip do you mean?",
    ),
    "List all my vehicles.": ("read", ["owned_item.vehicle"], None),
}


class FakeDriver:
    """Scripted text driver: reads (following pages), forgets or remembers."""

    def __init__(self, holder):
        self.holder = holder
        self.calls = []
        self.fail_on = set()

    async def parse_with_telemetry(
        self, *, system_prompt, input_payload, response_model, **_
    ):
        utterance = input_payload["latest_owner_utterance"]
        self.calls.append(utterance)
        assert "read_personal_context_for_question" in system_prompt
        if utterance in self.fail_on:
            raise RuntimeError("fictional 429 quota")
        action = await self._decide(utterance, input_payload)
        return SimpleNamespace(
            parsed=response_model.model_validate({"response": action}), usage={}
        )

    async def _decide(self, utterance, payload):
        spec = DRIVER[utterance]
        results = payload["tool_results"]
        if spec[0] == "answer":
            return {"answer": spec[1]}
        if spec[0] == "read":
            scopes, answer = spec[1], spec[2]
            if not results:
                return {
                    "read_personal_context_for_question": {
                        "requests": [{"scope_key": s} for s in scopes]
                    }
                }
            paging = results[-1]["result"].get("paging") or {}
            if paging.get("next_page"):
                return {
                    "read_personal_context_for_question": {
                        "requests": [{"scope_key": s} for s in scopes],
                        "page_token": paging["next_page"],
                    }
                }
            if answer is None:
                released = sum(len(r["result"].get("facts") or ()) for r in results)
                total = paging.get("total")
                labels = ", ".join(
                    f.get("text", "").split(";")[0]
                    for r in results
                    for f in r["result"].get("facts") or ()
                )
                more = (
                    ""
                    if paging.get("complete")
                    else f" That's {released} of {total}; more exist."
                )
                answer = f"You have {total} saved: {labels}.{more}"
            return {"answer": answer}
        if spec[0] == "remember":
            if not results:
                return {"remember_memory": {"predicate": spec[1], "value": spec[2]}}
            return {"answer": spec[3]}
        if spec[0] == "forget":
            if not results:
                return {"personal_context_catalog": {}}
            last = results[-1]
            if last["tool"] == "personal_context_catalog":
                catalog = last["result"]
                index = await self._facet_index(catalog["facets"], spec[1])
                return {
                    "forget_memory": {
                        "predicate": spec[1],
                        "catalog_id": catalog["catalog_id"],
                        "facet_index": index,
                    }
                }
            return {"answer": spec[2]}
        raise AssertionError(spec)

    async def _facet_index(self, facets, needle):
        # The scripted model "knows" which opaque facet holds the item.
        memory = self.holder.memory

        def find(connection):
            rows = connection.execute(
                "SELECT predicate, value_json FROM current_semantic_assertion"
            ).fetchall()
            return {p for p, v in rows if needle in v.casefold()}

        predicates = await memory._reader.run(find)
        return next(i for i, f in enumerate(facets) if f in predicates)


@pytest.fixture
def lab(tmp_path, authority_parts, clock, monkeypatch):
    from jarvis.authority import proposal

    # Permit leases and the broker share the fake clock, as in the lease tests.
    monkeypatch.setattr(proposal, "time", SimpleNamespace(monotonic=clock))
    holder = SimpleNamespace(memory=None)

    async def open_memory(path):
        path.parent.mkdir(parents=True, exist_ok=True)

        def connect():
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA foreign_keys=ON")
            MemoryMigrationRunner().apply(connection)
            return connection

        writer = SerialConnectionWorker(connect, thread_name="acceptance-writer")
        reader = SerialConnectionWorker(connect, thread_name="acceptance-reader")
        runtime = MemoryRuntime(
            MemoryService(
                MemoryLifecycleService(writer), CanonicalMemoryReader(reader)
            ),
            writer=writer,
            reader=reader,
        )
        await runtime.start()
        holder.memory = runtime
        return runtime

    async def pause(seconds):
        clock.advance(seconds)

    capability = CapabilityRuntime(
        executors=(),
        resolver=CapabilityResolver((), builtins=()),
        authority=authority_parts.broker,
    )
    learning_authority = capability.personal_learning_authority
    grant = learning_authority.open("acceptance-runtime", "gemini")
    genai = FakeGenai()
    adapter = LearningProviderAdapter("gemini", genai, "fictional-model")
    driver = FakeDriver(holder)
    deps = acceptance.LabDeps(
        open_memory=open_memory,
        capability=capability,
        learning_authority=learning_authority,
        learning_grant=grant,
        extractor=adapter,
        resolver=adapter,
        driver_client=driver,
        models={
            "answer_model": "fictional-answer",
            "learning_model": "fictional-model",
        },
        pause=pause,
    )
    root = tmp_path / "lab"
    root.mkdir()

    def runner(**kwargs):
        log = acceptance.ResultLog(
            root,
            commit="0" * 40,
            hashes=dict(acceptance.FROZEN_SHA256),
            models=deps.models,
        )
        return acceptance.AcceptanceRunner(root, deps, log, **kwargs), log

    return SimpleNamespace(
        root=root,
        deps=deps,
        genai=genai,
        driver=driver,
        runner=runner,
        hello=authority_parts.hello,
    )


def test_frozen_case_files_are_verified_and_heldout_is_never_read():
    assert acceptance.frozen_hashes(REPO) == acceptance.FROZEN_SHA256
    source = Path(acceptance.__file__).read_text(encoding="utf-8")
    # The held-out file is only hashed (to prove it is unchanged), never parsed.
    assert source.count("HELDOUT_FILE") == 2
    utterances = {
        s.text
        for g in acceptance.GROUPS.values()
        for s in g
        if isinstance(s, acceptance.Say)
    }
    heldout = (REPO / acceptance.HELDOUT_FILE).read_text(encoding="utf-8")
    assert not [u for u in utterances if u in heldout]


def test_frozen_case_file_change_refuses_to_run(tmp_path):
    for name in acceptance.FROZEN_SHA256:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO / name).read_bytes())
    (tmp_path / acceptance.ACCEPTANCE_FILE).write_text("edited", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen case file changed"):
        acceptance.frozen_hashes(tmp_path)


def test_every_development_case_is_planned_or_recorded():
    planned = set(acceptance.CASES_RUN) | set(acceptance.NOT_RUN_HERE)
    assert planned == {f"D{i}" for i in range(1, 28)}
    assert set(acceptance.CASES_RUN) == set(acceptance.CHECKS)
    # The frozen wording is used verbatim wherever the case gives it.
    frozen = (REPO / acceptance.ACCEPTANCE_FILE).read_text(encoding="utf-8")
    for group in acceptance.GROUPS.values():
        for step in group:
            if isinstance(step, acceptance.Say) and "harness-chosen" not in step.note:
                assert step.text.casefold() in frozen.casefold(), step.text


def test_live_tool_descriptions_are_available():
    names = (
        "read_personal_context_for_question",
        "personal_context_catalog",
        "read_personal_context",
        "remember_memory",
        "correct_memory",
        "forget_memory",
    )
    descriptions = acceptance.tool_descriptions(names)
    assert all(len(descriptions[n]) > 40 for n in names), descriptions


@pytest.mark.asyncio
async def test_full_scripted_run_passes_every_automatic_check(lab):
    runner, log = lab.runner()
    summary = await runner.run()
    failed = {
        case: [
            c
            for c in row["checks"]
            if c["status"] in {acceptance.FAIL, acceptance.UNTESTED}
        ]
        for case, row in summary["cases"].items()
        if row["status"] in {acceptance.FAIL, acceptance.UNTESTED}
    }
    # D3 keeps one owner-observed check (the Hello count) open by design.
    assert set(failed) == {"D3"}, json.dumps(failed, indent=1, default=str)[:4000]
    assert [c["check"] for c in failed["D3"]] == ["one Hello"]
    assert summary["untested"] == []
    assert summary["interrupted_at"] is None
    assert summary["not_run_here"]["D27"].startswith("Recorded from the owner-run")
    # Every result row records the tested commit and both case-file hashes.
    for row in log.read(log.cases) + log.read(log.steps):
        assert row["source_commit"] == "0" * 40
        assert row["case_files"] == acceptance.FROZEN_SHA256
    # (c) answers are never auto-passed.
    answers = [
        c
        for row in summary["cases"].values()
        for c in row["checks"]
        if c["level"] == "c"
    ]
    assert answers and {c["status"] for c in answers} == {acceptance.REVIEW}
    # Fresh Hello only for the two explicit memory commands (the learning
    # session was opened by the fixture before the run).
    operations = [p.operation for p in lab.hello.calls]
    assert operations.count("remember") + operations.count("forget") >= 2
    # Each model call happened once per step: no automatic retry.
    from collections import Counter

    events = log.read(log.events)
    learning_calls = Counter(
        (e["group"], e["step_id"], e["kind"])
        for e in events
        if e.get("kind") in {"learning_extraction", "learning_resolution"}
    )
    assert learning_calls and max(learning_calls.values()) == 1
    driver_calls = Counter(
        (e["group"], e["step_id"], e["index"])
        for e in events
        if e.get("kind") == "driver_step"
    )
    assert driver_calls and max(driver_calls.values()) == 1


@pytest.mark.asyncio
async def test_wrong_model_output_fails_the_case(lab, monkeypatch):
    wrong = dict(EXTRACT)
    wrong["I'm planning a Ladakh or winter Spiti trip in January."] = [
        plan(
            "Ladakh",
            "I'm planning a Ladakh or winter Spiti trip in January.",
            plan_status="planned",
            slots={"destination": slot("Ladakh"), "when": slot("January")},
        )
    ]
    monkeypatch.setattr(sys.modules[__name__], "EXTRACT", wrong)
    runner, _ = lab.runner()
    summary = await runner.run(groups=("story",))
    assert summary["cases"]["D6"]["status"] == acceptance.FAIL
    failing = {
        c["check"]
        for c in summary["cases"]["D6"]["checks"]
        if c["status"] == acceptance.FAIL
    }
    assert "destination options [Ladakh, winter Spiti]" in failing


@pytest.mark.asyncio
async def test_quota_interruption_preserves_completed_steps_and_resume_never_repeats(
    lab,
):
    lab.genai.fail_on.add("I'm planning a Ladakh or winter Spiti trip in January.")
    runner, log = lab.runner()
    with pytest.raises(acceptance.AcceptanceInterrupted):
        await runner.run(groups=("story",))
    states = log.step_states()
    assert states["story-07"]["status"] == "interrupted"
    assert states["story-06c"]["status"] == "checked"
    summary = json.loads(log.summary.read_text(encoding="utf-8"))
    assert summary["interrupted_at"] == "story-07"
    assert set(summary["cases"]) >= {"D1", "D2", "D5", "D22"}
    done_before = list(lab.genai.calls)

    # Resume without the owner's explicit retry option refuses to rerun it.
    runner, log = lab.runner()
    with pytest.raises(acceptance.AcceptanceInterrupted, match="retry-interrupted"):
        await runner.run(groups=("story",))
    assert lab.genai.calls == done_before

    # With it, the interrupted step is attempt 2 and nothing earlier repeats.
    lab.genai.fail_on.clear()
    runner, log = lab.runner(retry_interrupted=True)
    summary = await runner.run(groups=("story",))
    later = lab.genai.calls[len(done_before) :]
    earlier_texts = {
        text
        for _, text in done_before
        if text != "I'm planning a Ladakh or winter Spiti trip in January."
    }
    assert not [text for _, text in later if text in earlier_texts]
    assert log.step_states()["story-07"]["attempt"] == 2
    assert summary["cases"]["D6"]["status"] == acceptance.PASS
    assert summary["cases"]["D1"]["status"] == acceptance.PASS  # preserved


@pytest.mark.asyncio
async def test_driver_quota_interruption_is_recorded(lab):
    lab.driver.fail_on.add("When did I sell it?")
    runner, log = lab.runner()
    with pytest.raises(acceptance.AcceptanceInterrupted):
        await runner.run(groups=("story",))
    assert log.step_states()["story-05"]["status"] == "interrupted"
    events = [
        e
        for e in log.read(log.events)
        if e.get("kind") == "driver_step" and e["status"] == "provider_failure"
    ]
    assert len(events) == 1


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="process zone fixed on Windows")
def test_offline_suite_runs_in_owner_timezone():
    assert time.strftime("%z") == "+0530"
    assert os.environ["TZ"] == "Asia/Kolkata"


@pytest.mark.parametrize(
    "extra,message",
    [
        (["--context-eval"], "runs alone"),
        (["--slice1-group", "story"], None),
        (["--retry-interrupted"], "--resume-lab"),
    ],
)
def test_cli_keeps_the_acceptance_run_alone_and_explicit(
    monkeypatch, capsys, extra, message
):
    from jarvis.voice import project_memory_lab

    argv = ["lab", "--lab-root", "x", "--model", "m", "--source-commit", "0" * 40]
    if extra[0] != "--slice1-group":
        argv.append("--slice1-acceptance")
    monkeypatch.setattr("sys.argv", argv + extra)
    with pytest.raises(SystemExit):
        project_memory_lab.main()
    err = capsys.readouterr().err
    assert (message or "require --slice1-acceptance") in err


@pytest.mark.asyncio
async def test_windows_entry_wiring_runs_offline_with_fakes(
    lab, monkeypatch, authority_parts
):
    """run_slice1_acceptance with its Windows-only parts replaced: proves the
    names, arguments and result files of the real entry point."""
    import types

    from jarvis.voice import project_memory_lab

    fake_msvcrt = types.SimpleNamespace(locking=lambda *a: None, LK_NBLCK=1, LK_UNLCK=0)
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    # The real entry closes the capability runtime (and its audit store).
    monkeypatch.setattr(
        authority_parts.broker._audit, "close", lambda: None, raising=False
    )
    monkeypatch.setattr(
        "jarvis.capabilities.authority_bridge.CapabilityAuthorityBroker",
        lambda: authority_parts.broker,
    )

    async def open_memory(path):
        return await lab.deps.open_memory(path)

    def fake_memory(path):
        class Deferred:
            async def start(self_inner):
                self_inner.__dict__.update({"real": await lab.deps.open_memory(path)})

            def __getattr__(self_inner, name):
                return getattr(self_inner.__dict__["real"], name)

        return Deferred()

    monkeypatch.setattr(
        "jarvis.memory.runtime.build_default_memory_runtime", fake_memory
    )

    class Routing:
        async def aclose(self):
            return None

    monkeypatch.setattr(
        "jarvis.model_routing.runtime.build_routing_runtime", lambda **_: Routing()
    )
    monkeypatch.setattr(
        "jarvis.hands.provider_adapters.RoutedStructuredOutputClient",
        lambda **_: lab.driver,
    )
    monkeypatch.setattr(
        "jarvis.memory.learning_extractors.build_learning_adapters",
        lambda *a, **k: (lab.deps.extractor, lab.deps.resolver),
    )
    monkeypatch.setattr("jarvis.work.store.SQLiteWorkStore", lambda *a, **k: object())
    monkeypatch.setattr(
        "jarvis.work.privacy.build_default_work_payload_codec", lambda *a: None
    )
    config = types.SimpleNamespace(gemini_fallback=types.SimpleNamespace(enabled=True))
    monkeypatch.setattr(project_memory_lab, "replace", lambda obj, **k: obj)
    root = lab.root / "entry"
    root.mkdir()
    summary = await project_memory_lab.run_slice1_acceptance(
        config,
        root,
        model="fictional-answer",
        source_commit="1" * 40,
        hashes=dict(acceptance.FROZEN_SHA256),
        groups=("idiom",),
        retry_interrupted=False,
    )
    assert summary["cases"]["D9"]["status"] == acceptance.PASS
    assert (root / "acceptance-summary.json").is_file()
    steps = [
        json.loads(line)
        for line in (root / "acceptance-steps.jsonl").read_text().splitlines()
    ]
    assert {row["source_commit"] for row in steps} == {"1" * 40}
    assert {row["lane"] for row in steps} == {"free"}
