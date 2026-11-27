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
import re
import sqlite3
import sys
import time
from itertools import pairwise
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


def _approved_test_ledger(monkeypatch, path):
    from jarvis.voice import paid_acceptance_budget, project_memory_lab

    monkeypatch.setattr(project_memory_lab, "APPROVED_PAID_LEDGER", path)
    paid_acceptance_budget.PaidBudgetLedger(path).close()
    return path


@pytest.mark.asyncio
async def test_recorded_when_only_plan_releases_elapsed_status(lab, monkeypatch):
    recorded = json.loads(
        (Path(__file__).parent / "fixtures" / "codex_7e787c53_d13.json").read_text(
            encoding="utf-8"
        )
    )
    raw = json.loads(json.dumps(recorded["extraction"]["candidates"][0]))
    spans = raw.pop("evidence")
    assert raw["time_expression"] is None
    raw["quote"] = [recorded["utterance"][s["start"] : s["end"]] for s in spans]
    monkeypatch.setitem(EXTRACT, recorded["utterance"], [raw])
    runner, _ = lab.runner(stop_after="story-13c", stop_on_failure=True)
    summary = await runner.run(groups=("story",))
    checks = summary["cases"]["D13"]["checks"]
    assert checks[0]["status"] == acceptance.PASS
    assert checks[0]["detail"] == ["passed_outcome_unknown"]


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
    acceptance.D1_A1_TEXT: [
        item(
            "Royal Enfield Classic 350",
            "I have a Royal Enfield Classic 350 I bought in 2021",
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

EXTRACT.update(
    {
        # Amendment 2: the other answers to plan alternatives (group alternatives).
        "We're going to Spiti in January, Thar or Jimny.": [
            plan(
                "Spiti",
                "We're going to Spiti in January, Thar or Jimny.",
                plan_status="planned",
                slots={
                    "destination": slot("Spiti"),
                    "when": slot("January"),
                    "vehicle": slot(options=("Thar", "Jimny")),
                },
            )
        ],
        "We'll take the Jimny.": [
            plan(
                "Spiti",
                ["We're going to Spiti", "We'll take the Jimny."],
                plan_status="planned",
                slots={"vehicle": slot("Jimny")},
            )
        ],
        "We're going to Kerala in March, train or flight.": [
            plan(
                "Kerala",
                "We're going to Kerala in March, train or flight.",
                plan_status="planned",
                slots={
                    "destination": slot("Kerala"),
                    "when": slot("March"),
                    "other": slot(options=("train", "flight")),
                },
            )
        ],
        "We're going to Goa in April, Airbnb or hotel.": [
            plan(
                "Goa",
                "We're going to Goa in April, Airbnb or hotel.",
                plan_status="planned",
                slots={
                    "destination": slot("Goa"),
                    "when": slot("April"),
                    "stay": slot(options=("Airbnb", "hotel")),
                },
            )
        ],
    }
)

# How the scripted extractor reads an answer to an open question: (answer,
# detail); detail None answers every open question.
ANSWERS = {
    acceptance.D6_CONFIRMATION: [("confirmed", "destination")],
    "We'll take the Jimny.": [("chosen", "vehicle")],
    "Doesn't matter, either is fine.": [("doesnt_matter", None)],
}

RESOLVE = {
    acceptance.D6_CONFIRMATION: [("match", "ladakh")],
    "We'll take the Jimny.": [("match", "spiti")],
    "We're going to Spiti in January, Thar or Jimny.": [("new", None)],
    "We're going to Kerala in March, train or flight.": [("new", None)],
    "We're going to Goa in April, Airbnb or hotel.": [("new", None)],
    "I bought the Tigor in March 2017, it's the diesel one.": [("match", "tigor")],
    "I sold the Tigor last week.": [("match", "tigor")],
    "I'm planning a Ladakh or winter Spiti trip in January.": [("new", None)],
    "Maybe we'll do Goa this winter.": [("new", None)],
    "We're going with winter Spiti, and we'll take the Jimny.": [("match", "ladakh")],
    "Cancel the Goa plan.": [("match", "goa")],
    "I misspoke, the Jimny is from September, not October.": [("match", "jimny")],
    "I sold the Classic 350 in October.": [("match", "classic")],
}


class Http503(Exception):
    status_code = 503


class Http429(Exception):
    status_code = 429


class FakeGenai:
    """Scripted Gemini for the learning adapter (extraction + resolution)."""

    def __init__(self):
        self.calls = []
        self.fail_on = set()
        self.transient = {}  # (stage, text) -> number of 503s still to return
        self.aio = SimpleNamespace(interactions=SimpleNamespace(create=self.create))

    async def create(self, *, model, input, system_instruction, **_):
        payload = json.loads(input)
        current = next(
            t for t in payload["turns"] if t["turn_id"] == payload["current_turn_id"]
        )
        text = current["text"]
        stage = (
            "extraction"
            if system_instruction.startswith(EXTRACTION_PROMPT)
            else "resolution"
        )
        self.calls.append((stage, text))
        if text in self.fail_on:
            raise RuntimeError("fictional 429 quota")
        if self.transient.get((stage, text)):
            self.transient[(stage, text)] -= 1
            raise Http503("fictional overload")
        if stage == "extraction":
            proposals = []
            for proposal in EXTRACT.get(text, []):
                proposal = dict(proposal)
                quotes = proposal.pop("quote")
                if isinstance(quotes, str):
                    quotes = [quotes]
                evidence = []
                for quote in quotes:
                    turn = next(t for t in payload["turns"] if quote in t["text"])
                    evidence.append({"turn_id": turn["turn_id"], "quote": quote})
                proposals.append({**proposal, "evidence": evidence})
            out = {"candidates": proposals}
            questions = payload.get("open_questions") or []
            if questions:
                out["open_question_answers"] = [
                    {"question_id": q["question_id"], "answer": answer}
                    for answer, detail in ANSWERS.get(text, [])
                    for q in questions
                    if detail is None
                    or detail in (q.get("choices") or {})
                    or detail in (q.get("unclear") or [])
                ]
        else:
            entries = payload["catalog"]["entries"]
            resolutions = []
            for index, (decision, needle) in enumerate(RESOLVE.get(text, [])):
                target = None
                if needle:
                    exact = needle.startswith("=")  # "=trip": the label exactly

                    def names(label, needle=needle, exact=exact):
                        label = label.casefold()
                        return label == needle[1:] if exact else needle in label

                    def matches(entry, names=names, exact=exact, needle=needle):
                        stored = json.loads(entry["value"])
                        return names(stored.get("label", "")) or (
                            not exact
                            and needle in str(stored.get("value", "")).casefold()
                        )

                    target = next(e["assertion_id"] for e in entries if matches(e))
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
    acceptance.D6_CONFIRMATION: ("answer", "Okay."),
    "We're going to Spiti in January, Thar or Jimny.": (
        "answer",
        "Are you still deciding between the Thar and the Jimny?",
    ),
    "We'll take the Jimny.": ("answer", "The Jimny it is."),
    "We're going to Kerala in March, train or flight.": (
        "answer",
        "Still choosing between train and flight?",
    ),
    "Doesn't matter, either is fine.": ("answer", "Okay."),
    "We're going to Goa in April, Airbnb or hotel.": (
        "answer",
        "Still deciding between an Airbnb and a hotel?",
    ),
    "What's the weather like there in April?": ("answer", "Warm and humid."),
    "We're planning a Rishikesh trip in October 2026.": ("answer", "Sounds lovely."),
    "I have a Royal Enfield Classic 350 from 2021, a Tata Tigor I bought in March 2017, and last month I got a Jimny.": (
        "answer",
        "Understood.",
    ),
    acceptance.D1_A1_TEXT: ("answer", "Understood."),
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
        ["owned_item.vehicle", "plan=Spiti"],
        "The Jimny: you're already taking it on your winter Spiti trip.",
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
        self.errors = {}  # utterance -> list of exceptions/actions to return first

    async def parse_with_telemetry(
        self, *, system_prompt, input_payload, response_model, **_
    ):
        utterance = input_payload["latest_owner_utterance"]
        self.calls.append(utterance)
        assert "read_personal_context_for_question" in system_prompt
        if utterance in self.fail_on:
            raise RuntimeError("fictional 429 quota")
        queued = self.errors.get(utterance)
        if queued:
            first = queued.pop(0)
            if isinstance(first, BaseException):
                raise first
            if first == "stall":
                import asyncio

                await asyncio.sleep(5)
            if first == "invalid":
                return SimpleNamespace(
                    parsed=response_model.model_validate({"response": {"x": 1}}),
                    usage={},
                )
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
            requests = [
                {"scope_key": s.split("=")[0], "target_quote": s.split("=", 1)[1]}
                if "=" in s
                else {"scope_key": s}
                for s in scopes
            ]
            if not results:
                return {"read_personal_context_for_question": {"requests": requests}}
            paging = results[-1]["result"].get("paging") or {}
            if paging.get("next_page"):
                return {
                    "read_personal_context_for_question": {
                        "requests": requests,
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
        if spec[0] == "catalog_only":
            if not results:
                return {"personal_context_catalog": {}}
            return {"answer": spec[1]}
        if spec[0] == "stepwise_forget":
            # As recorded in the final acceptance (story-18): catalog, then one
            # facet at a time, starting with the Tigor, repeating one read,
            # until a read shows the item; then forget that index. If reads
            # keep failing, answer with a clarifying question.
            needle, done, clarify = spec[1], spec[2], spec[3]
            if not results:
                return {"personal_context_catalog": {}}
            catalog = results[0]["result"]
            facets = catalog["facets"]
            owned = [i for i, f in enumerate(facets) if f.startswith("owned_item")]
            first = await self._facet_index(facets, "tigor")
            order = [first] + [i for i in owned if i != first]
            order = [order[0], order[1], order[1], *order[2:]]
            order += [i for i in range(len(facets)) if i not in order]
            last = results[-1]
            if last["tool"] == "forget_memory":
                return {"answer": done}
            for call in results:
                if call["tool"] == "read_personal_context":
                    for fact in call["result"].get("facts") or ():
                        if needle in fact["text"].casefold():
                            index = facets.index(fact["predicate"])
                            return {
                                "forget_memory": {
                                    "predicate": needle,
                                    "catalog_id": catalog["catalog_id"],
                                    "facet_index": index,
                                }
                            }
            reads = sum(1 for c in results if c["tool"] == "read_personal_context")
            if reads >= 5:
                return {"answer": clarify}
            return {
                "read_personal_context": {
                    "catalog_id": catalog["catalog_id"],
                    "facet_indices": [order[reads]],
                }
            }
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
    # Do not parse the sealed cases, even during offline harness tests.
    assert utterances


def test_windows_line_endings_are_not_a_change_but_an_edit_is(tmp_path):
    for name in acceptance.FROZEN_SHA256:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        content = (REPO / name).read_bytes().replace(b"\r\n", b"\n")
        target.write_bytes(content.replace(b"\n", b"\r\n"))
    assert acceptance.frozen_hashes(tmp_path) == acceptance.FROZEN_SHA256
    path = tmp_path / acceptance.ACCEPTANCE_FILE
    path.write_bytes(path.read_bytes().replace(b"D23", b"D99", 1))
    with pytest.raises(ValueError, match="frozen case file changed"):
        acceptance.frozen_hashes(tmp_path)


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
    # Amendment 1: D1 runs as D1-A1 (amended wording) plus D1-R (regression).
    # Amendment 2: D6 runs as D6-A2 (with its confirmation turn); D28-D30 added.
    assert planned == (
        {f"D{i}" for i in range(2, 28)} - {"D6"}
        | {"D1-A1", "D1-R", "D6-A2", "D28", "D29", "D30"}
    )
    assert set(acceptance.CASES_RUN) == set(acceptance.CHECKS)
    # The frozen wording is used verbatim wherever the case gives it.
    frozen = (REPO / acceptance.ACCEPTANCE_FILE).read_text(encoding="utf-8")
    amended = (REPO / acceptance.AMENDMENT_1_FILE).read_text(encoding="utf-8")
    amended_2 = (REPO / acceptance.AMENDMENT_2_FILE).read_text(encoding="utf-8")
    for group in acceptance.GROUPS.values():
        for step in group:
            if not isinstance(step, acceptance.Say) or "harness-chosen" in step.note:
                continue
            if "amendment-1 wording" in step.note:
                assert step.text in amended and step.text not in frozen, step.text
            elif step.case in {"D28", "D29", "D30"} or "amendment-2" in step.note:
                assert step.text in amended_2, step.text
            else:
                assert step.text.casefold() in frozen.casefold(), step.text
    assert acceptance.D1_FROZEN_TEXT in frozen


@pytest.mark.parametrize("index", [0, 1])
def test_amendments_are_verified_and_a_changed_file_refuses_to_run(tmp_path, index):
    actives = acceptance.active_amendments(REPO)
    assert [a["id"] for a in actives] == ["amendment-1", "amendment-2"]
    assert all(a["status"] == "active" for a in actives)
    for a in acceptance.ACCEPTANCE_AMENDMENTS:
        target = tmp_path / a["file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO / a["file"]).read_bytes())
    name = acceptance.ACCEPTANCE_AMENDMENTS[index]["file"]
    target = tmp_path / name
    content = (REPO / name).read_bytes().replace(b"\r\n", b"\n")
    target.write_bytes(content.replace(b"\n", b"\r\n"))  # CRLF is not a change
    assert (
        acceptance.active_amendments(tmp_path)[index]["sha256"]
        == (actives[index]["sha256"])
    )
    target.write_bytes(content.replace(b"APPROVED", b"PROPOSED", 1))
    with pytest.raises(ValueError, match="approved amendment file changed"):
        acceptance.active_amendments(tmp_path)


def test_a_superseded_expectation_never_decides_a_case_status():
    checks = [
        {"check": "a", "level": "a", "status": acceptance.PASS},
        {"check": "old", "level": "a", "status": acceptance.SUPERSEDED},
    ]
    assert acceptance._overall(checks) == acceptance.PASS
    checks[0]["status"] = acceptance.FAIL
    assert acceptance._overall(checks) == acceptance.FAIL


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
    assert failed == {}, json.dumps(failed, indent=1, default=str)[:4000]
    assert summary["automatic_verdict"] == "PASS_PENDING_MANUAL_REVIEW"
    # Amendments 1 and 2 are active and identified in the report and on every row.
    amendments = summary["acceptance_amendments"]
    assert [a["id"] for a in amendments] == ["amendment-1", "amendment-2"]
    assert all(a["status"] == "active" for a in amendments)
    assert [a["sha256"] for a in amendments] == [
        a["sha256"] for a in acceptance.ACCEPTANCE_AMENDMENTS
    ]
    for row in log.read(log.cases):
        assert row["acceptance_amendments"] == summary["acceptance_amendments"]
    # D1-A1 passes on the amended wording (Classic bought in 2021).
    assert summary["cases"]["D1-A1"]["status"] == acceptance.PASS
    assert "D1" not in summary["cases"]
    # D1-R: the current requirement passes; the frozen purchase-year
    # expectation is SUPERSEDED, not PASS or FAIL, and not in any verdict.
    d1r = {c["check"]: c for c in summary["cases"]["D1-R"]["checks"]}
    assert (
        d1r["no Classic purchase date invented from 'from 2021'"]["status"]
        == acceptance.PASS
    )
    superseded = d1r["frozen D1 expectation: Classic acquired year 2021"]
    assert superseded["status"] == acceptance.SUPERSEDED
    assert superseded["detail"]["superseded_by"] == "amendment-1"
    assert superseded["detail"]["observed"] == [None, None, None]
    assert summary["cases"]["D1-R"]["status"] == acceptance.PASS
    assert sorted(e["check"] for e in summary["superseded_expectations"]) == [
        "frozen D1 expectation: Classic acquired year 2021",
        "frozen D6 expectation: destination options from the statement",
    ]
    # Amendment 2: D6-A2 (confirmation turn) passes; D28-D30 pass.
    for case in ("D6-A2", "D28", "D29", "D30"):
        assert summary["cases"][case]["status"] in {acceptance.PASS, acceptance.REVIEW}
    assert "D6" not in summary["cases"]
    assert summary["d17_failed_stage"] is None
    assert "D17" in summary["required_gates"]
    hello = [c for c in summary["cases"]["D3"]["checks"] if c["check"] == "one Hello"]
    assert hello[0]["status"] == acceptance.REVIEW  # owner observation
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
    assert summary["cases"]["D6-A2"]["status"] == acceptance.FAIL
    failing = {
        c["check"]
        for c in summary["cases"]["D6-A2"]["checks"]
        if c["status"] == acceptance.FAIL
    }
    assert "destination options [Ladakh, winter Spiti], undecided" in failing


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
    assert set(summary["cases"]) >= {"D1-A1", "D2", "D5", "D22"}
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
    assert summary["cases"]["D6-A2"]["status"] == acceptance.REVIEW  # (c) answer
    assert summary["cases"]["D1-A1"]["status"] == acceptance.PASS  # preserved


@pytest.mark.asyncio
async def test_checkpoint_pauses_after_learning_lookup_and_answer_and_resume_never_repeats(
    lab,
):
    runner, log = lab.runner(
        stop_after=acceptance.CHECKPOINT_STOP_AFTER, stop_on_failure=True
    )
    summary = await runner.run(groups=("story",))
    assert summary["run_state"] == "checkpoint_paused_for_review"
    assert summary["checkpoint_paused_after"] == "story-05c"
    assert set(summary["cases"]) == {"D1-A1", "D2", "D5"}
    states = log.step_states()
    assert "story-06" not in states
    # It covered learning (extraction), a lookup and an answer.
    assert any(stage == "extraction" for stage, _ in lab.genai.calls)
    d5 = {c["check"]: c["status"] for c in summary["cases"]["D5"]["checks"]}
    assert d5["follow-up lookup completed"] == acceptance.PASS
    assert "When did I sell it?" in lab.driver.calls
    learning_before, answers_before = list(lab.genai.calls), list(lab.driver.calls)
    d5_case = summary["cases"]["D5"]

    # Running the checkpoint again sends nothing.
    runner, log = lab.runner(
        stop_after=acceptance.CHECKPOINT_STOP_AFTER, stop_on_failure=True
    )
    again = await runner.run(groups=("story",))
    assert again["run_state"] == "checkpoint_paused_for_review"
    assert lab.genai.calls == learning_before and lab.driver.calls == answers_before

    # Continuing without the checkpoint never repeats a completed step's calls.
    runner, log = lab.runner(stop_on_failure=True)
    summary = await runner.run(groups=("story",))
    assert lab.genai.calls[: len(learning_before)] == learning_before
    later = lab.genai.calls[len(learning_before) :]
    assert not set(later) & set(learning_before)
    later_answers = lab.driver.calls[len(answers_before) :]
    assert not set(later_answers) & set(answers_before)
    assert summary["run_state"] in {"complete", "partial"}
    assert summary["cases"]["D5"] == d5_case  # checkpoint results preserved
    assert summary["cases"]["D6-A2"]["status"] == acceptance.REVIEW  # (c) answer
    started = [r["step_id"] for r in log.read(log.steps) if r["status"] == "started"]
    assert len(started) == len(set(started))  # no step ran twice


@pytest.mark.asyncio
async def test_a_definite_failure_stops_the_run_and_resume_refuses(lab, monkeypatch):
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
    runner, log = lab.runner(stop_on_failure=True)
    with pytest.raises(acceptance.AcceptanceStoppedOnFailure, match="D6-A2 FAIL"):
        await runner.run(groups=("story",))
    states = log.step_states()
    assert states["story-07c"]["case_status"] == acceptance.FAIL
    assert "story-08" not in states  # no dependent case was run
    summary = json.loads(log.summary.read_text(encoding="utf-8"))
    assert summary["run_state"] == "stopped_on_failure"
    assert summary["stopped_on_failure"]["case"] == "D6-A2"
    calls = (list(lab.genai.calls), list(lab.driver.calls))

    # Resuming refuses before any model call; the failed answer is not retried.
    runner, log = lab.runner(stop_on_failure=True, retry_interrupted=True)
    with pytest.raises(
        acceptance.AcceptanceStoppedOnFailure, match="does not continue"
    ):
        await runner.run(groups=("story",))
    assert (lab.genai.calls, lab.driver.calls) == calls


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
    built = {}

    def free_client(**kwargs):
        built.update(kwargs)
        return lab.driver

    monkeypatch.setattr(
        "jarvis.hands.provider_adapters.build_structured_output_client", free_client
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
        call_spacing_seconds=0.5,
    )
    assert summary["cases"]["D9"]["status"] == acceptance.PASS
    assert (root / "acceptance-summary.json").is_file()
    steps = [
        json.loads(line)
        for line in (root / "acceptance-steps.jsonl").read_text().splitlines()
    ]
    assert {row["source_commit"] for row in steps} == {"1" * 40}
    assert {row["lane"] for row in steps} == {"free"}
    assert {row["call_spacing_seconds"] for row in steps} == {0.5}
    # Answer calls: Free credential only, SDK retries off, no router.
    assert built["credential_ref"] == "GOOGLE_API_KEY"
    assert built["provider_retries"] is False and built["provider"] == "gemini"
    assert summary["retry_policy"]["max_attempts"] == 3


@pytest.mark.asyncio
async def test_windows_entry_wiring_paid_lane_uses_only_the_paid_key_and_ledger(
    lab, monkeypatch, authority_parts, tmp_path
):
    """The Paid lane through the real entry point: no Free client or router is
    built, the Free key is withheld for the run, every row says paid, and the
    ledger snapshot is written."""
    import os
    import types

    from jarvis.voice import paid_acceptance_budget, project_memory_lab

    fake_msvcrt = types.SimpleNamespace(locking=lambda *a: None, LK_NBLCK=1, LK_UNLCK=0)
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(
        authority_parts.broker._audit, "close", lambda: None, raising=False
    )
    monkeypatch.setattr(
        "jarvis.capabilities.authority_bridge.CapabilityAuthorityBroker",
        lambda: authority_parts.broker,
    )

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

    def never(*_a, **_k):
        raise AssertionError("a Free-lane client or router was built")

    monkeypatch.setattr("jarvis.model_routing.runtime.build_routing_runtime", never)
    monkeypatch.setattr(
        "jarvis.hands.provider_adapters.build_structured_output_client", never
    )
    monkeypatch.setattr(
        "jarvis.memory.learning_extractors.build_learning_adapters", never
    )
    seen = {}

    def paid_clients(model, ledger, *, lab, allowance=None):
        seen["ledger"] = ledger.path
        seen["allowance"] = allowance
        return lab_deps.extractor, lab_driver

    lab_deps, lab_driver = lab.deps, lab.driver
    monkeypatch.setattr(paid_acceptance_budget, "build_paid_clients", paid_clients)
    monkeypatch.setenv("GOOGLE_API_KEY", "free-must-not-be-used")
    original_reply = lab_driver.parse_with_telemetry

    async def reply(**kwargs):
        seen.setdefault("free_key_during_run", os.environ.get("GOOGLE_API_KEY"))
        return await original_reply(**kwargs)

    monkeypatch.setattr(lab_driver, "parse_with_telemetry", reply)
    config = types.SimpleNamespace(gemini_fallback=types.SimpleNamespace(enabled=True))
    root = lab.root / "entry-paid"
    root.mkdir()
    ledger_path = tmp_path / "shared-paid-ledger" / "ledger.sqlite3"
    _approved_test_ledger(monkeypatch, ledger_path)
    summary = await project_memory_lab.run_slice1_acceptance(
        config,
        root,
        model="fictional-answer",
        source_commit="1" * 40,
        hashes=dict(acceptance.FROZEN_SHA256),
        groups=("idiom",),
        retry_interrupted=False,
        call_spacing_seconds=0.5,
        lane="paid",
        paid_ledger=ledger_path,
        checkpoint=True,
    )
    assert summary["cases"]["D9"]["status"] == acceptance.PASS
    assert seen["allowance"] == project_memory_lab.CHECKPOINT_ALLOWANCE
    assert summary["paid_budget"]["allowance"] == {
        "allowance_id": "slice1-paid-checkpoint-1",
        "cap_usd": 0.10,
    }
    assert summary["lane"] == "paid"
    assert summary["credential_ref"] == "JARVIS_GEMINI_PAID_API_KEY"
    assert summary["paid_budget"]["ceiling_usd"] == 1.0
    assert seen["ledger"] == ledger_path
    assert seen["free_key_during_run"] is None  # withheld while running
    assert os.environ["GOOGLE_API_KEY"] == "free-must-not-be-used"  # restored
    for name in ("acceptance-steps.jsonl", "acceptance-events.jsonl"):
        rows = [json.loads(x) for x in (root / name).read_text().splitlines()]
        assert {row["lane"] for row in rows} == {"paid"}, name
    snapshot = json.loads((root / "paid-budget-snapshot.json").read_text())
    assert snapshot["ceiling_usd"] == 1.0 and snapshot["ledger"] == str(ledger_path)
    # The lab can never continue on the Free lane.
    with pytest.raises(ValueError, match="cannot change its lane"):
        await project_memory_lab.run_slice1_acceptance(
            config,
            root,
            model="fictional-answer",
            source_commit="1" * 40,
            hashes=dict(acceptance.FROZEN_SHA256),
            groups=("idiom",),
            retry_interrupted=False,
            call_spacing_seconds=0.5,
        )


# D17 stage diagnosis (owner check 2026-11-21) ---------------------------------

TARGET = "owned_item_classic"


def _catalog(facets, catalog_id="cat-1"):
    return {
        "tool": "personal_context_catalog",
        "arguments": {},
        "result": {"catalog_id": catalog_id, "facets": facets},
    }


def _forget(index, ok=True, catalog_id="cat-1"):
    return {
        "tool": "forget_memory",
        "arguments": {
            "predicate": "Classic 350",
            "catalog_id": catalog_id,
            "facet_index": index,
        },
        "result": {"ok": ok},
    }


CLEAN = {"evidence_quotes": 0, "search_index": 0}


@pytest.mark.parametrize(
    "tools,remaining,residual,stage",
    [
        ([], 1, CLEAN, "item_absent_from_available_catalog"),
        (
            [_catalog(["owned_item_jimny", "plan_goa"])],
            1,
            CLEAN,
            "item_absent_from_available_catalog",
        ),
        (
            [_catalog(["owned_item_jimny", TARGET])],
            1,
            CLEAN,
            "model_did_not_select_available_item",
        ),
        (
            [_catalog(["owned_item_jimny", TARGET]), _forget(0)],
            1,
            CLEAN,
            "model_did_not_select_available_item",
        ),
        (
            [_catalog(["owned_item_jimny", TARGET]), _forget(7)],
            1,
            CLEAN,
            "model_did_not_select_available_item",
        ),
        (
            [_catalog(["owned_item_jimny", TARGET]), _forget(1, ok=False)],
            1,
            CLEAN,
            "forget_operation_failed",
        ),
        (
            [_catalog(["owned_item_jimny", TARGET]), _forget(1)],
            1,
            CLEAN,
            "forget_operation_failed",
        ),
        (
            [_catalog(["owned_item_jimny", TARGET]), _forget(1)],
            0,
            {"evidence_quotes": 1, "search_index": 0},
            "deleted_but_residual_remains",
        ),
        ([_catalog(["owned_item_jimny", TARGET]), _forget(1)], 0, CLEAN, None),
    ],
    ids=[
        "no_catalog",
        "not_listed",
        "listed_no_forget",
        "forgot_another_item",
        "bad_index",
        "forget_refused",
        "ok_but_rows_remain",
        "residual",
        "passed",
    ],
)
def test_d17_failure_stage_is_diagnosed(tools, remaining, residual, stage):
    found, detail = acceptance.diagnose_forget(tools, [TARGET], remaining, residual)
    assert found == stage
    assert detail["lineage_remaining"] == remaining


@pytest.mark.asyncio
async def test_d17_without_a_forget_fails_the_gate_with_its_stage(lab, monkeypatch):
    driver = dict(DRIVER)
    driver["Forget the Classic 350."] = ("answer", "Done.")  # claims, never calls
    monkeypatch.setattr(sys.modules[__name__], "DRIVER", driver)
    runner, _ = lab.runner()
    summary = await runner.run(groups=("story",))
    assert summary["cases"]["D17"]["status"] == acceptance.FAIL
    assert summary["d17_failed_stage"] == "item_absent_from_available_catalog"
    assert summary["cases"]["D26"]["status"] == acceptance.UNTESTED
    assert summary["automatic_verdict"] == acceptance.FAIL


@pytest.mark.asyncio
async def test_d17_catalog_without_a_forget_is_a_selection_failure(lab, monkeypatch):
    driver = dict(DRIVER)
    driver["Forget the Classic 350."] = ("catalog_only", "I couldn't find it.")
    monkeypatch.setattr(sys.modules[__name__], "DRIVER", driver)
    runner, _ = lab.runner()
    summary = await runner.run(groups=("story",))
    assert summary["d17_failed_stage"] == "model_did_not_select_available_item"
    assert summary["cases"]["D17"]["status"] == acceptance.FAIL


# Shared Free-lane pacing (owner check 2026-11-21) -----------------------------


class _FakeTime:
    def __init__(self):
        self.now = 0.0
        self.starts = []

    def clock(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


@pytest.mark.asyncio
async def test_pacer_spaces_call_starts_and_never_retries():
    t = _FakeTime()
    pacer = acceptance.FreeLanePacer(6.0, clock=t.clock, sleep=t.sleep)
    for gap in (0.0, 1.0, 10.0, 0.5):
        t.now += gap
        await pacer.wait()
        t.starts.append(t.now)
    deltas = [b - a for a, b in pairwise(t.starts)]
    assert all(d >= 6.0 for d in deltas), deltas
    assert pacer.calls == 4
    with pytest.raises(ValueError):
        acceptance.FreeLanePacer(0)


@pytest.mark.asyncio
async def test_one_pacer_is_shared_by_learning_and_answer_calls(lab):
    t = _FakeTime()
    pacer = acceptance.FreeLanePacer(6.0, clock=t.clock, sleep=t.sleep)
    lab.deps.pacer = pacer
    runner, log = lab.runner()
    summary = await runner.run(groups=("idiom", "scale-11"))
    assert summary["cases"]["D9"]["status"] == acceptance.PASS
    driver_steps = [e for e in log.read(log.events) if e.get("kind") == "driver_step"]
    # Every provider call is counted once: learning calls (only real
    # provider calls, not deterministic resolutions) and answer steps.
    assert pacer.calls == len(lab.genai.calls) + len(driver_steps)
    # On average one call per spacing (two learning calls may run together).
    assert t.now >= (pacer.calls - 2) * 6.0


@pytest.mark.asyncio
async def test_pacer_ready_waits_outside_and_note_never_waits():
    t = _FakeTime()
    pacer = acceptance.FreeLanePacer(6.0, clock=t.clock, sleep=t.sleep)
    await pacer.wait()  # answer call at 0
    await pacer.ready()  # owner turn observed only at 6
    assert t.now == 6.0
    pacer.note(2)  # extraction + resolution inside learning: no waiting
    assert t.now == 6.0
    await pacer.wait()  # next answer waits for both counted calls
    assert t.now == 18.0 and pacer.calls == 4


# Run 2: pacing must not consume the learning deadline (owner check) -----------


class _SlowGenai(FakeGenai):
    """Each provider call takes ``latency`` real seconds."""

    def __init__(self, latency):
        super().__init__()
        self.latency = latency

    async def create(self, **kwargs):
        import asyncio

        await asyncio.sleep(self.latency)
        return await super().create(**kwargs)


@pytest.mark.asyncio
async def test_run2_reproduction_pacer_wait_must_not_eat_the_learning_deadline(
    lab, monkeypatch
):
    """Run 2: learning waited for the shared pacer inside its own 25 s
    inference deadline. Scaled down: deadline 1.0 s, provider latency 0.2 s,
    spacing 2.0 s, the previous call just started. A provider that answers
    well within its own budget must not time out because of harness pacing."""
    from jarvis.memory import learning_runtime

    monkeypatch.setattr(learning_runtime, "INFERENCE_TIMEOUT", 1.0)
    monkeypatch.setattr(learning_runtime, "PROCESSING_BUDGET", 1.5)
    slow = LearningProviderAdapter("gemini", _SlowGenai(0.2), "fictional-model")
    lab.deps.extractor = lab.deps.resolver = slow
    pacer = acceptance.FreeLanePacer(2.0)
    await pacer.wait()  # a call has just started
    lab.deps.pacer = pacer
    runner, log = lab.runner()
    summary = await runner.run(groups=("idiom",))
    statuses = [e for e in log.read(log.events) if e.get("kind") == "learning_status"]
    assert [s["reason"] for s in statuses][:1] == ["committed"], statuses
    assert summary["cases"]["D9"]["status"] == acceptance.PASS


@pytest.mark.asyncio
async def test_a_learning_timeout_stops_the_run_and_is_not_completed_setup(
    lab, monkeypatch
):
    """Run 2: timed-out learning turns were treated as completed setup and
    their dependent cases were graded as FAIL. Now the run stops at that
    turn: no checks of it, no retry, no reseeding."""
    from jarvis.memory import learning_runtime

    monkeypatch.setattr(learning_runtime, "INFERENCE_TIMEOUT", 0.3)
    monkeypatch.setattr(learning_runtime, "PROCESSING_BUDGET", 0.5)
    adapter = LearningProviderAdapter("gemini", _SlowGenai(1.0), "fictional-model")
    lab.deps.extractor = lab.deps.resolver = adapter
    runner, log = lab.runner()
    with pytest.raises(acceptance.AcceptanceInterrupted, match="learning incomplete"):
        await runner.run(groups=("idiom",))
    states = log.step_states()
    assert states["idiom-01"]["status"] == "interrupted"
    assert "idiom-02" not in states and "idiom-02c" not in states
    assert log.read(log.cases) == []  # nothing graded on missing setup
    cancelled = [
        e for e in log.read(log.events) if e.get("status") == "cancelled_at_deadline"
    ]
    assert len(cancelled) == 1 and cancelled[0]["kind"] == "learning_extraction"
    assert adapter.attempts == 1  # one provider call, no retry


# Bounded retries for temporary provider failures (owner policy 2026-11-21) ----


@pytest.fixture
def fast_retries(monkeypatch):
    from jarvis import provider_retry

    monkeypatch.setattr(provider_retry, "RETRY_DELAYS", (0.01, 0.02))


def _events(log, kind=None, step=None):
    return [
        e
        for e in log.read(log.events)
        if (kind is None or e.get("kind") == kind)
        and (step is None or e.get("step_id") == step)
    ]


@pytest.mark.asyncio
async def test_learning_503_then_success_continues_and_is_reported(lab, fast_retries):
    text = "We're going to Spiti in January, Thar or no Thar."
    lab.genai.transient[("extraction", text)] = 1
    runner, log = lab.runner()
    summary = await runner.run(groups=("idiom",))
    assert summary["cases"]["D9"]["status"] == acceptance.PASS
    attempts = _events(log, "learning_extraction", "idiom-01")
    assert [(e["attempt"], e["status"]) for e in attempts] == [
        (1, "provider_failure"),
        (2, "ok"),
    ]
    assert attempts[0]["failure_kind"] == "service_unavailable"
    decisions = _events(log, "learning_retry_decision", "idiom-01")
    assert [d["decision"] for d in decisions] == ["transient_retry"]
    reliability = summary["provider_reliability"]
    assert reliability["completed_after_retry"] == 1
    assert reliability["unrecovered_provider_failures"] == 0
    assert reliability["first_attempt_ok"] == reliability["calls"] - 1
    assert reliability["first_attempt_ok_rate"] < 1
    assert reliability["eventual_completion_rate"] == 1
    assert reliability["steps_completed_only_after_retry"] == ["idiom-01"]
    assert reliability["failed_attempts_by_kind"] == {"service_unavailable": 1}
    status = _events(log, "learning_status", "idiom-01")[0]
    assert status["committed"] >= 1 and status["failed_provider_attempts"] == 1


@pytest.mark.asyncio
async def test_learning_repeated_503_stops_after_two_retries_without_saving(
    lab, fast_retries
):
    text = "We're going to Spiti in January, Thar or no Thar."
    lab.genai.transient[("extraction", text)] = 3
    runner, log = lab.runner()
    with pytest.raises(acceptance.AcceptanceInterrupted, match="provider failure"):
        await runner.run(groups=("idiom",))
    attempts = _events(log, "learning_extraction", "idiom-01")
    assert [e["status"] for e in attempts] == ["provider_failure"] * 3
    decisions = [d["decision"] for d in _events(log, "learning_retry_decision")]
    assert decisions == ["transient_retry", "transient_retry", "attempts_exhausted"]
    status = _events(log, "learning_status", "idiom-01")[0]
    assert (status["committed"], status["dropped"]) == (0, 1)
    assert log.step_states()["idiom-01"]["status"] == "interrupted"
    summary = json.loads(log.summary.read_text(encoding="utf-8"))
    assert summary["provider_reliability"]["unrecovered_provider_failures"] == 1
    assert summary["provider_reliability"]["steps_with_unrecovered_failure"] == [
        "idiom-01"
    ]


@pytest.mark.asyncio
async def test_learning_429_is_never_retried(lab, fast_retries, monkeypatch):
    text = "We're going to Spiti in January, Thar or no Thar."

    async def rate_limited(**kwargs):
        raise Http429("fictional rate limit")

    original = lab.genai.create

    async def create(**kwargs):
        if text in kwargs["input"]:
            lab.genai.calls.append(("extraction", text))
            return await rate_limited(**kwargs)
        return await original(**kwargs)

    lab.genai.aio.interactions.create = create
    runner, log = lab.runner()
    with pytest.raises(acceptance.AcceptanceInterrupted):
        await runner.run(groups=("idiom",))
    assert len(_events(log, "learning_extraction", "idiom-01")) == 1
    decisions = [d["decision"] for d in _events(log, "learning_retry_decision")]
    assert decisions == ["not_transient"]


@pytest.mark.asyncio
async def test_driver_503_then_success_runs_each_tool_once(lab, fast_retries):
    utterance = "Which vehicles do I own?"
    lab.driver.errors[utterance] = [Http503("fictional overload")]
    runner, log = lab.runner()
    summary = await runner.run(groups=("scale-11",))
    assert summary["cases"]["D18"]["status"] in {acceptance.PASS, acceptance.REVIEW}
    steps = _events(log, "driver_step", "s11-01")
    assert [(e["index"], e["attempt"], e["status"]) for e in steps] == [
        (0, 1, "provider_failure"),
        (0, 2, "ok"),
        (1, 1, "ok"),
        (2, 1, "ok"),
    ][: len(steps)]
    assert steps[0]["decision"] == "transient_retry"
    assert steps[0]["status_code"] == 503
    reads = [e for e in _events(log, "tool_result", "s11-01")]
    first_reads = [r for r in reads if "page_token" not in r["arguments"]]
    assert len(first_reads) == 1  # the tool ran once despite the retry
    reliability = summary["provider_reliability"]
    assert reliability["completed_after_retry"] == 1
    assert reliability["steps_completed_only_after_retry"] == ["s11-01"]


@pytest.mark.asyncio
async def test_driver_repeated_503_stops_after_two_retries(lab, fast_retries):
    utterance = "Which vehicles do I own?"
    lab.driver.errors[utterance] = [Http503("x"), Http503("x"), Http503("x")]
    runner, log = lab.runner()
    with pytest.raises(acceptance.AcceptanceInterrupted):
        await runner.run(groups=("scale-11",))
    steps = _events(log, "driver_step", "s11-01")
    assert [e["decision"] for e in steps] == [
        "transient_retry",
        "transient_retry",
        "attempts_exhausted",
    ]
    assert _events(log, "tool_result", "s11-01") == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,decision",
    [
        (Http429("fictional rate limit"), "not_transient"),
        (PermissionError("denied"), "not_transient"),
        ("invalid", "invalid_output"),
    ],
)
async def test_driver_non_transient_failures_and_invalid_output_are_final(
    lab, fast_retries, error, decision
):
    utterance = "Which vehicles do I own?"
    lab.driver.errors[utterance] = [error]
    runner, log = lab.runner()
    with pytest.raises(acceptance.AcceptanceInterrupted):
        await runner.run(groups=("scale-11",))
    steps = _events(log, "driver_step", "s11-01")
    assert len(steps) == 1 and steps[0]["decision"] == decision
    assert lab.driver.calls.count(utterance) == 1


@pytest.mark.asyncio
async def test_driver_stall_is_unresolved_and_not_retried(lab, monkeypatch):
    from jarvis.memory import learning_limits

    monkeypatch.setattr(learning_limits, "INFERENCE_TIMEOUT", 0.05)
    utterance = "Which vehicles do I own?"
    lab.driver.errors[utterance] = ["stall"]
    runner, log = lab.runner()
    with pytest.raises(acceptance.AcceptanceInterrupted, match="stalled"):
        await runner.run(groups=("scale-11",))
    steps = _events(log, "driver_step", "s11-01")
    assert [e["status"] for e in steps] == ["stall_unresolved"]
    assert lab.driver.calls.count(utterance) == 1
    summary = json.loads(log.summary.read_text(encoding="utf-8"))
    assert summary["provider_reliability"]["stalls_unresolved"] == 1


@pytest.mark.asyncio
async def test_driver_retry_needs_room_in_the_step_budget(lab, monkeypatch):
    from jarvis.memory import learning_limits

    monkeypatch.setattr(learning_limits, "PROCESSING_BUDGET", 7.0)
    utterance = "Which vehicles do I own?"
    lab.driver.errors[utterance] = [Http503("x")]
    runner, log = lab.runner()
    with pytest.raises(acceptance.AcceptanceInterrupted):
        await runner.run(groups=("scale-11",))
    steps = _events(log, "driver_step", "s11-01")
    assert [e["decision"] for e in steps] == ["deadline_insufficient"]


def test_free_lane_driver_client_drops_routing_ids_only():
    import asyncio

    seen = {}

    class Inner:
        model_name = "m"

        async def parse_with_telemetry(self, **kwargs):
            seen.update(kwargs)
            return "ok"

    client = acceptance.FreeLaneDriverClient(Inner())
    result = asyncio.run(
        client.parse_with_telemetry(
            system_prompt="p",
            input_payload={},
            response_model=dict,
            scope_id="s",
            operation_id="o",
        )
    )
    assert result == "ok"
    assert set(seen) == {"system_prompt", "input_payload", "response_model"}


# Run 4 D7 / D10: the recorded model outputs, replayed offline ------------------

RUN4_EXTRACT = {
    # Recorded verbatim in run 4 (lab 67967242), evidence = whole turn.
    "I'm planning a Ladakh or winter Spiti trip in January.": [
        plan(
            "Ladakh or winter Spiti trip",
            "I'm planning a Ladakh or winter Spiti trip in January.",
            importance="transient",
            time_expression="January",
            plan_status="planned",
            slots={
                "destination": slot(options=("Ladakh", "winter Spiti")),
                "when": slot("January"),
            },
        )
    ],
    "Maybe we'll do Goa this winter.": [
        plan(
            "Goa trip",
            "Maybe we'll do Goa this winter.",
            value="Goa",
            importance="transient",
            certainty="tentative",
            time_expression="this winter",
            location="Goa",
            plan_status="considering",
            slots={"destination": slot("Goa"), "when": slot("this winter")},
        )
    ],
    "We're going with winter Spiti, and we'll take the Jimny.": [
        plan(
            "winter Spiti",
            "We're going with winter Spiti, and we'll take the Jimny.",
            importance="transient",
            plan_status="planned",
            slots={"destination": slot("winter Spiti"), "vehicle": slot("Jimny")},
        )
    ],
}


@pytest.mark.asyncio
async def test_run4_recorded_outputs_now_pass_d7_and_d10(lab, monkeypatch):
    """Run 4 recorded D7 FAIL (no eligible fact: label "Goa trip" not said)
    and D10 FAIL (decision skipped as refine_conflicts_existing_detail). The
    same model outputs, replayed through the fixed product code, pass; the
    frozen checks are unchanged."""
    for text, proposals in RUN4_EXTRACT.items():
        monkeypatch.setitem(EXTRACT, text, proposals)
    runner, log = lab.runner()
    summary = await runner.run(groups=("story",))
    assert summary["cases"]["D7"]["status"] == acceptance.PASS, summary["cases"]["D7"]
    assert summary["cases"]["D10"]["status"] == acceptance.PASS, summary["cases"]["D10"]
    assert summary["cases"]["D11"]["status"] in {acceptance.PASS, acceptance.REVIEW}
    status = {
        e["step_id"]: e
        for e in log.read(log.events)
        if e.get("kind") == "learning_status"
    }
    assert status["story-08"]["committed"] == 1
    assert status["story-10"]["committed"] == 1 and status["story-10"]["skipped"] == []


RUN5_EXTRACT = {
    # Recorded verbatim in run 5 (lab 7a0a29e2): stored label "trip".
    "I'm planning a Ladakh or winter Spiti trip in January.": [
        plan(
            "trip",
            "I'm planning a Ladakh or winter Spiti trip in January.",
            value="Ladakh or winter Spiti trip",
            importance="transient",
            time_expression="January",
            plan_status="planned",
            slots={
                "destination": slot(options=("Ladakh", "winter Spiti")),
                "when": slot("January"),
            },
        )
    ],
    "We're going with winter Spiti, and we'll take the Jimny.": [
        plan(
            "winter Spiti",
            "We're going with winter Spiti, and we'll take the Jimny.",
            value="We're going with winter Spiti, and we'll take the Jimny.",
            importance="transient",
            location="Spiti",
            plan_status="planned",
            slots={"destination": slot("winter Spiti"), "vehicle": slot("Jimny")},
        )
    ],
}


@pytest.mark.asyncio
async def test_run5_recorded_outputs_now_pass_d10(lab, monkeypatch):
    """Run 5 recorded D10 FAIL (new_fact_cannot_mutate_target: the decision's
    label "winter Spiti" does not name the stored plan "trip"). The same model
    outputs, replayed through the fixed code, pass the unchanged frozen
    checks."""
    for text, proposals in RUN5_EXTRACT.items():
        monkeypatch.setitem(EXTRACT, text, proposals)
    # As recorded: the resolver matched the stored plan labelled "trip".
    monkeypatch.setitem(
        RESOLVE,
        "We're going with winter Spiti, and we'll take the Jimny.",
        [("match", "=trip")],
    )
    runner, log = lab.runner()
    summary = await runner.run(groups=("story",))
    assert summary["cases"]["D10"]["status"] == acceptance.PASS, summary["cases"]["D10"]
    status = {
        e["step_id"]: e
        for e in log.read(log.events)
        if e.get("kind") == "learning_status"
    }
    assert status["story-10"]["committed"] == 1 and status["story-10"]["skipped"] == []


@pytest.mark.asyncio
async def test_run5_recorded_outputs_pass_d10_d12_and_release_d16_evidence(
    lab, monkeypatch
):
    """Run 5's recorded D10 and D12 proposals together (D12 put "September"
    in the Jimny's value). Through the fixed code: D10 and D12 pass,
    including the new identity check; D14/D15 still read the Jimny as the
    Jimny; D16's lookup now releases the owner's words, the told dates and
    recorded_at separately."""
    for text, proposals in RUN5_EXTRACT.items():
        monkeypatch.setitem(EXTRACT, text, proposals)
    monkeypatch.setitem(
        RESOLVE,
        "We're going with winter Spiti, and we'll take the Jimny.",
        [("match", "=trip")],
    )
    d12 = "I misspoke, the Jimny is from September, not October."
    monkeypatch.setitem(
        EXTRACT,
        d12,
        [
            item(
                "Jimny",
                d12,
                intent="correction",
                value="September",
                time_expression="September",
                acquired_expression="September",
            )
        ],
    )
    runner, log = lab.runner()
    summary = await runner.run(groups=("story",))
    cases = summary["cases"]
    for case in ("D10", "D12"):
        assert cases[case]["status"] == acceptance.PASS, cases[case]
    events = log.read(log.events)

    def reads(step):
        return [
            fact
            for e in events
            if e.get("kind") == "tool_result" and e.get("step_id") == step
            for fact in (e.get("result") or {}).get("facts", [])
        ]

    for step in ("story-14", "story-15", "story-16"):
        jimny = [f for f in reads(step) if "Jimny" in f["text"]]
        assert jimny and all("value=September" not in f["text"] for f in jimny)
    (fact,) = [f for f in reads("story-16") if "Jimny" in f["text"]]
    assert fact["told"]["how"] == "owner_said" and fact["told"]["quote"]
    assert fact["told"]["date"] == "2026-11-19"  # the correction's telling
    assert fact["first_told"]["date"] == "2026-11-17"  # D1's telling
    assert fact["acquired"]["expression"] == "September"
    assert "recorded_at" in fact  # the system's time, released separately
    d16 = {c["check"]: c for c in cases["D16"]["checks"]}
    evidence = d16[
        "released evidence: owner's words and told date, apart from recorded_at"
    ]
    assert evidence["status"] == acceptance.PASS


# Run 6 D15: the new grading against the recorded behaviour ----------------------

RUN6 = json.loads(
    (Path(__file__).parent / "fixtures" / "run6_d11_d15_recorded.json").read_text(
        encoding="utf-8"
    )
)
D15 = "Which of my vehicles is best for a snowy Spiti trip?"


def _d15_checks(summary):
    return {c["check"]: c["status"] for c in summary["cases"]["D15"]["checks"]}


@pytest.mark.asyncio
async def test_run6_d15_recorded_behaviour_now_fails_the_decided_plan_check(
    lab, monkeypatch
):
    """Run 6: only vehicles were requested and the plan was not in context.
    The old check passed; the new one records that the decided plan never
    reached the model (consistency cannot be judged)."""
    (recorded,) = RUN6["steps"]["story-15"]["tool_results"]
    scopes = [r["scope_key"] for r in recorded["arguments"]["requests"]]
    assert scopes == ["owned_item.vehicle"]
    monkeypatch.setitem(
        DRIVER, D15, ("read", scopes, RUN6["steps"]["story-15"]["answer"])
    )
    runner, _log = lab.runner()
    checks = _d15_checks(await runner.run(groups=("story",)))
    assert (
        checks["decided plan reached the model (released this turn or in context)"]
        == acceptance.FAIL
    )
    assert checks["answer consistent with the decided plan"] == acceptance.UNTESTED
    assert checks["unrelated plans left out"] == acceptance.PASS


@pytest.mark.asyncio
async def test_d15_unrelated_plans_in_the_lookup_fail(lab, monkeypatch):
    monkeypatch.setitem(
        DRIVER, D15, ("read", ["owned_item.vehicle", "plan"], "The Jimny.")
    )
    runner, _log = lab.runner()
    checks = _d15_checks(await runner.run(groups=("story",)))
    assert checks["unrelated plans left out"] == acceptance.FAIL
    assert (
        checks["decided plan reached the model (released this turn or in context)"]
        == acceptance.PASS
    )


@pytest.mark.asyncio
async def test_d15_answer_contradicting_the_decided_plan_fails(lab, monkeypatch):
    monkeypatch.setitem(
        DRIVER,
        D15,
        (
            "read",
            ["owned_item.vehicle", "plan=Spiti"],
            "Take the Classic 350, it is the best for snow.",
        ),
    )
    runner, _log = lab.runner()
    checks = _d15_checks(await runner.run(groups=("story",)))
    assert checks["answer consistent with the decided plan"] == acceptance.FAIL


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        # Lab eea8eea5's recorded answer: correct, failed by the old pattern.
        (
            (
                "For a snowy Spiti trip, your Jimny is definitely the best choice. You"
                " also own a Royal Enfield Classic 350, but the Jimny's 4x4 capability"
                " will handle the snow and terrain much better. You mentioned taking"
                " the Jimny when you planned this trip for January."
            ),
            "PASS",
        ),
        ("The Jimny is fine. The Classic 350 is the best for snow.", "FAIL"),
    ],
    ids=["comparison-naming-both", "recommends-another"],
)
async def test_d15_consistency_reads_each_sentence(lab, monkeypatch, answer, expected):
    monkeypatch.setitem(
        DRIVER, D15, ("read", ["owned_item.vehicle", "plan=Spiti"], answer)
    )
    runner, _log = lab.runner()
    summary = await runner.run(groups=("story",))
    checks = _d15_checks(summary)
    assert checks["answer consistent with the decided plan"] == getattr(
        acceptance, expected
    )
    (review,) = [
        c for c in summary["cases"]["D15"]["checks"] if c["check"] == "useful advice"
    ]
    flags = review["detail"]["keyword_flags"]
    assert flags["compares with another vehicle (check which is recommended)"]


@pytest.mark.asyncio
async def test_run6_d11_goa_lookup_by_word_finds_the_cancelled_plan(lab, monkeypatch):
    (recorded,) = RUN6["steps"]["story-11"]["tool_results"]
    assert recorded["result"]["status"] == "no_match"  # run 6
    monkeypatch.setitem(
        DRIVER, "Cancel the Goa plan.", ("read", ["plan=Goa"], "Done, cancelled.")
    )
    runner, log = lab.runner()
    await runner.run(groups=("story",))
    (result,) = [
        e["result"]
        for e in log.read(log.events)
        if e.get("kind") == "tool_result" and e.get("step_id") == "story-11"
    ]
    assert result["status"] == "selected"
    (fact,) = result["facts"]
    assert fact["plan_status"] == "cancelled" and "Goa" in fact["text"]


# Lab 7 D17: refused consent is kept apart from deletion correctness -------------


def test_d17_refused_consent_is_its_own_stage():
    refused = _forget(1, ok=False)
    refused["result"] = {
        "ok": False,
        "error": "PermissionError",
        "message": "Fresh owner consent was not granted for this request",
    }
    found, _ = acceptance.diagnose_forget(
        [_catalog(["owned_item_jimny", TARGET]), refused], [TARGET], 1, CLEAN
    )
    assert found == "owner_consent_not_granted"
    other = _forget(1, ok=False)
    other["result"] = {"ok": False, "error": "PermissionError", "message": "stale"}
    found, _ = acceptance.diagnose_forget(
        [_catalog(["owned_item_jimny", TARGET]), other], [TARGET], 1, CLEAN
    )
    assert found == "forget_operation_failed"


@pytest.mark.asyncio
async def test_d17_consent_refusal_is_recorded_and_deletion_left_untested(lab):
    from jarvis.capabilities.authority_bridge import CapabilityAuthorizationError

    real = lab.deps.capability.authorize_personal_context

    def refuse_forget(**kwargs):
        if kwargs.get("operation") == "forget":
            raise CapabilityAuthorizationError("owner did not approve")
        return real(**kwargs)

    lab.deps.capability.authorize_personal_context = refuse_forget
    runner, log = lab.runner()
    summary = await runner.run(groups=("story",))
    checks = {c["check"]: c for c in summary["cases"]["D17"]["checks"]}
    assert summary["d17_failed_stage"] == "owner_consent_not_granted"
    assert checks["fresh owner consent granted (Windows Hello)"]["status"] == (
        acceptance.FAIL
    )
    for name in ("forget gate (stage diagnosis)", "lineage gone"):
        assert checks[name]["status"] == acceptance.UNTESTED
    outcomes = [
        e
        for e in log.read(log.events)
        if e.get("kind") == "consent_outcome" and e.get("step_id") == "story-18"
    ]
    assert [(e["operation"], e["outcome"]) for e in outcomes] == [
        ("forget", "CapabilityAuthorizationError")
    ]
    assert summary["cases"]["D26"]["status"] == acceptance.UNTESTED


def _refuse_forget_consent(lab):
    from jarvis.capabilities.authority_bridge import CapabilityAuthorizationError

    real = lab.deps.capability.authorize_personal_context

    def refuse_forget(**kwargs):
        if kwargs.get("operation") == "forget":
            raise CapabilityAuthorizationError("owner did not approve")
        return real(**kwargs)

    lab.deps.capability.authorize_personal_context = refuse_forget
    return real


@pytest.mark.asyncio
async def test_d17_consent_recovery_reruns_only_the_forget_turn_and_keeps_the_original(
    lab,
):
    real = _refuse_forget_consent(lab)
    runner, log = lab.runner(stop_on_failure=True)
    with pytest.raises(acceptance.AcceptanceStoppedOnFailure, match="D17 FAIL"):
        await runner.run(groups=("story",))
    before = {
        name: (lab.root / name).read_text(encoding="utf-8")
        for name in (
            "acceptance-cases.jsonl",
            "acceptance-steps.jsonl",
            "acceptance-events.jsonl",
        )
    }
    learning_calls, answer_calls = list(lab.genai.calls), list(lab.driver.calls)
    # Without the recovery the lock still refuses; nothing is sent.
    runner, log = lab.runner(stop_on_failure=True)
    with pytest.raises(acceptance.AcceptanceStoppedOnFailure):
        await runner.run(groups=("story",))
    assert lab.driver.calls == answer_calls

    # Windows Hello stays mandatory: the recovered attempt is approved.
    lab.deps.capability.authorize_personal_context = real
    runner, log = lab.runner(stop_on_failure=True, recover_d17_consent=True)
    summary = await runner.run(groups=("story",))
    assert summary["run_state"] == "checkpoint_paused_for_review"
    assert summary["checkpoint_paused_after"] == "story-18c"
    assert summary["cases"]["D17"]["status"] == acceptance.PASS
    assert [r["status"] for r in summary["earlier_case_results"]["D17"]] == [
        acceptance.FAIL
    ]
    assert [r["step_id"] for r in summary["recoveries"]] == ["story-18", "story-18c"]
    # The original attempt's rows are kept byte for byte, before the new ones.
    for name, text in before.items():
        assert (lab.root / name).read_text(encoding="utf-8").startswith(text), name
    # Only the forget turn ran again: no learning call, one forget question.
    assert lab.genai.calls == learning_calls
    new_answers = lab.driver.calls[len(answer_calls) :]
    assert set(new_answers) == {"Forget the Classic 350."}
    states = log.step_states()
    assert states["story-18"]["attempt"] == 2
    assert "story-18d" not in states  # paused before D26/D21
    outcomes = [
        e["outcome"]
        for e in log.read(log.events)
        if e.get("kind") == "consent_outcome" and e.get("step_id") == "story-18"
    ]
    assert outcomes == ["CapabilityAuthorizationError", "granted"]

    # A normal resume then continues after D17 without repeating it.
    runner, log = lab.runner(stop_on_failure=True)
    summary = await runner.run(groups=("story",))
    assert summary["cases"]["D26"]["status"] == acceptance.PASS
    # Each attempt made the same model steps; the resume added none.
    first = answer_calls.count("Forget the Classic 350.")
    assert lab.driver.calls.count("Forget the Classic 350.") == 2 * first

    # The recovery is single-use.
    runner, log = lab.runner(stop_on_failure=True, recover_d17_consent=True)
    with pytest.raises(acceptance.AcceptanceRecoveryRefused):
        await runner.run(groups=("story",))


@pytest.mark.asyncio
async def test_d17_recovery_refused_for_any_other_failure_and_sends_nothing(
    lab, monkeypatch
):
    # A run where D17 passed: nothing to recover.
    runner, _log = lab.runner(stop_on_failure=True)
    await runner.run(groups=("story",))
    calls = list(lab.driver.calls)
    runner, _log = lab.runner(stop_on_failure=True, recover_d17_consent=True)
    with pytest.raises(acceptance.AcceptanceRecoveryRefused, match="no recorded"):
        await runner.run(groups=("story",))
    assert lab.driver.calls == calls
    with pytest.raises(acceptance.AcceptanceRecoveryRefused, match="story group"):
        await lab.runner(recover_d17_consent=True)[0].run(groups=("idiom",))


ORIGINAL_BUILD = "0" * 40  # the lab fixture's commit: the build that failed
RECOVERY_BUILD = "7" * 40
UNRELATED_BUILD = "9" * 40


def _entry_point(lab, monkeypatch, authority_parts, tmp_path, clock):
    """The real CLI entry (main -> prepare_project_profile -> slice-1 mode ->
    run_slice1_acceptance -> runner) with only the machine-bound parts faked:
    Windows check, source checkout check, machine profile, SQLCipher memory,
    the authority broker and the Paid clients (scripted fakes, no network)."""
    import contextlib
    import types

    from jarvis.voice import paid_acceptance_budget, project_memory_lab

    monkeypatch.setitem(
        sys.modules,
        "msvcrt",
        types.SimpleNamespace(locking=lambda *a: None, LK_NBLCK=1, LK_UNLCK=0),
    )
    # Each launch is its own process in real use, with its own broker; here
    # the test broker (fake Hello, test policy) serves every launch, so a
    # launch's closing must not shut it down for the next one.
    monkeypatch.setattr(authority_parts.broker, "close", lambda: None)
    monkeypatch.setattr(
        "jarvis.capabilities.authority_bridge.CapabilityAuthorityBroker",
        lambda: authority_parts.broker,
    )

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
    verified = []
    monkeypatch.setattr(project_memory_lab, "_require_windows", lambda _p: None)
    monkeypatch.setattr(
        project_memory_lab, "verify_source", lambda _repo, c: verified.append(c)
    )
    monkeypatch.setattr(project_memory_lab, "_same_product_source", lambda *_a: True)
    monkeypatch.setattr(
        project_memory_lab,
        "project_lab_environment",
        lambda *_a: contextlib.nullcontext(),
    )
    monkeypatch.setattr(
        "jarvis.machine_config.load_machine_settings", lambda *_a, **_k: {}
    )
    monkeypatch.setattr(
        "jarvis.config.JarvisConfig.from_environment",
        staticmethod(
            lambda: types.SimpleNamespace(
                ai_provider="gemini",
                gemini_fallback=types.SimpleNamespace(enabled=False),
            )
        ),
    )
    monkeypatch.setattr(
        paid_acceptance_budget,
        "build_paid_clients",
        lambda model, ledger, *, lab, allowance=None: (
            lab_deps.extractor,
            lab_driver,
        ),
    )
    lab_deps, lab_driver = lab.deps, lab.driver
    source_profile = tmp_path / "machine-source.json"
    source_profile.write_text("{}", encoding="utf-8")
    ledger = tmp_path / "shared-ledger" / "ledger.sqlite3"
    _approved_test_ledger(monkeypatch, ledger)

    def run(commit, *extra):
        # Each launch is a separate process in real use: a later moment, so
        # its fresh learning-session approval is not a replay of the last one.
        clock.advance(120)
        project_memory_lab.main(
            [
                "--lab-root",
                str(lab.root),
                "--profile",
                str(source_profile),
                "--model",
                "fictional-answer",
                "--source-commit",
                commit,
                "--resume-lab",
                "--slice1-acceptance",
                "--slice1-group",
                "story",
                "--call-spacing-seconds",
                "0.01",
                "--paid-lane",
                "--paid-budget-ledger",
                str(ledger),
                *extra,
            ]
        )

    return run, verified


def _original_build_lab_with_d17_consent_failure(lab):
    """The original build's lab: its marker, profile and a story run that
    stopped at D17 because fresh owner consent was not granted."""
    import asyncio

    from jarvis.voice import project_memory_lab

    (lab.root / "project-memory.marker").write_text(
        json.dumps(
            {"kind": project_memory_lab.MARKER, "commit": ORIGINAL_BUILD},
            sort_keys=True,
        )
    )
    (lab.root / "machine.json").write_text("{}", encoding="utf-8")
    real = _refuse_forget_consent(lab)
    runner, _log = lab.runner(stop_on_failure=True)
    with pytest.raises(acceptance.AcceptanceStoppedOnFailure, match="D17 FAIL"):
        asyncio.run(runner.run(groups=("story",)))
    lab.deps.capability.authorize_personal_context = real
    return (lab.root / "project-memory.marker").read_bytes()


def test_d17_recovery_through_the_entry_point_on_an_original_build_lab(
    lab, monkeypatch, authority_parts, tmp_path, clock
):
    from jarvis.capabilities.runtime import CapabilityRuntime

    marker = _original_build_lab_with_d17_consent_failure(lab)
    original_logs = {
        n: (lab.root / n).read_text(encoding="utf-8")
        for n in ("acceptance-cases.jsonl", "acceptance-steps.jsonl")
    }
    run, verified = _entry_point(lab, monkeypatch, authority_parts, tmp_path, clock)
    consents = []
    real_authorize = CapabilityRuntime.authorize_personal_context

    def recorded(self, **kwargs):  # mocked Windows Hello: the owner approves
        consents.append(kwargs.get("operation"))
        return real_authorize(self, **kwargs)

    monkeypatch.setattr(CapabilityRuntime, "authorize_personal_context", recorded)
    learning_before, answers_before = list(lab.genai.calls), list(lab.driver.calls)

    # An ordinary resume on another build is refused before anything runs.
    with pytest.raises(ValueError, match="exact-source marked lab"):
        run(RECOVERY_BUILD)
    assert lab.driver.calls == answers_before and consents == []

    # The explicit recovery on the recovery build reaches consent and recovers.
    run(RECOVERY_BUILD, "--recover-d17-consent")
    assert verified[-1] == RECOVERY_BUILD
    assert "forget" in consents
    assert lab.genai.calls == learning_before  # no learning call
    assert set(lab.driver.calls[len(answers_before) :]) == {"Forget the Classic 350."}
    summary = json.loads((lab.root / "acceptance-summary.json").read_text())
    assert summary["run_state"] == "checkpoint_paused_for_review"
    assert summary["cases"]["D17"]["status"] == acceptance.PASS
    assert summary["lane"] == "paid" and summary["source_commit"] == RECOVERY_BUILD
    assert summary["paid_budget"]["allowance"]["allowance_id"] == (
        "slice1-paid-d17-recovery-1"
    )
    assert [r["status"] for r in summary["earlier_case_results"]["D17"]] == ["FAIL"]
    assert (lab.root / "project-memory.marker").read_bytes() == marker  # unchanged
    for name, text in original_logs.items():
        assert (lab.root / name).read_text(encoding="utf-8").startswith(text), name
    recovery = json.loads((lab.root / "recovery-source.json").read_text())
    assert (recovery["original_commit"], recovery["recovery_commit"]) == (
        ORIGINAL_BUILD,
        RECOVERY_BUILD,
    )

    # Its recorded continuation is allowed on the recovery build only.
    with pytest.raises(ValueError, match="exact-source marked lab"):
        run(UNRELATED_BUILD)
    with pytest.raises(ValueError, match="exact-source marked lab"):
        run(UNRELATED_BUILD, "--recover-d17-consent")
    calls = list(lab.driver.calls)
    run(RECOVERY_BUILD)
    summary = json.loads((lab.root / "acceptance-summary.json").read_text())
    assert summary["cases"]["D26"]["status"] == acceptance.PASS
    assert summary["cases"]["D21"]["status"] == acceptance.PASS
    assert lab.driver.calls == calls  # D26/D21 are checks; nothing repeated
    # The recovery cannot be used again (exit 4, nothing sent).
    with pytest.raises(SystemExit) as refused:
        run(RECOVERY_BUILD, "--recover-d17-consent")
    assert refused.value.code == 4 and lab.driver.calls == calls


def test_an_unrelated_build_never_resumes_an_original_build_lab(
    lab, monkeypatch, authority_parts, tmp_path, clock
):
    import asyncio

    from jarvis.voice import project_memory_lab

    (lab.root / "project-memory.marker").write_text(
        json.dumps(
            {"kind": project_memory_lab.MARKER, "commit": ORIGINAL_BUILD},
            sort_keys=True,
        )
    )
    (lab.root / "machine.json").write_text("{}", encoding="utf-8")
    runner, _log = lab.runner(stop_on_failure=True)
    asyncio.run(runner.run(groups=("idiom",)))  # a lab whose D17 never failed
    run, _verified = _entry_point(lab, monkeypatch, authority_parts, tmp_path, clock)
    calls = list(lab.driver.calls)
    with pytest.raises(ValueError, match="exact-source marked lab"):
        run(UNRELATED_BUILD)
    # The recovery flag lets the entry reach validation, which refuses: D17
    # has no consent failure. Nothing is sent and no recovery is recorded.
    with pytest.raises(SystemExit) as refused:
        run(UNRELATED_BUILD, "--recover-d17-consent")
    assert refused.value.code == 4
    assert lab.driver.calls == calls
    assert not (lab.root / "recovery-source.json").exists()
    with pytest.raises(ValueError, match="exact-source marked lab"):
        run(UNRELATED_BUILD)


def test_d17_recovery_preconditions_refuse_a_non_consent_stage(tmp_path):
    log = acceptance.ResultLog(tmp_path, commit="c", hashes={}, models={})

    def record(stage, error="PermissionError", remaining=2, extra=None):
        log._append(
            log.cases,
            {
                "case": "D17",
                "step_id": "story-18c",
                "status": acceptance.FAIL,
                "checks": [
                    {
                        "check": "forget gate (stage diagnosis)",
                        "status": acceptance.UNTESTED,
                        "detail": {
                            "failed_stage": stage,
                            "listed_in_catalog": True,
                            "shown_by_read": True,
                            "forget_calls": [
                                {"targets_item": True, "result": {"error": error}}
                            ],
                            "lineage_remaining": remaining,
                        },
                    }
                ],
            },
        )
        if extra:
            log._append(log.cases, extra)

    runner = acceptance.AcceptanceRunner(tmp_path, None, log, recover_d17_consent=True)
    record("model_did_not_select_available_item")
    with pytest.raises(acceptance.AcceptanceRecoveryRefused, match="not at consent"):
        runner._check_d17_recovery()
    record("owner_consent_not_granted", error="ValueError")
    with pytest.raises(acceptance.AcceptanceRecoveryRefused, match="past consent"):
        runner._check_d17_recovery()
    record("owner_consent_not_granted", remaining=0)
    with pytest.raises(acceptance.AcceptanceRecoveryRefused, match="no longer stored"):
        runner._check_d17_recovery()
    record(
        "owner_consent_not_granted",
        extra={
            "case": "D23",
            "step_id": "story-17c",
            "status": acceptance.FAIL,
            "checks": [],
        },
    )
    with pytest.raises(acceptance.AcceptanceRecoveryRefused, match="D23"):
        runner._check_d17_recovery()


@pytest.mark.asyncio
async def test_granted_consent_is_recorded(lab):
    runner, log = lab.runner()
    summary = await runner.run(groups=("story",))
    outcomes = [
        (e["operation"], e["outcome"])
        for e in log.read(log.events)
        if e.get("kind") == "consent_outcome" and e.get("step_id") == "story-18"
    ]
    assert outcomes == [("forget", "granted")]
    assert summary["cases"]["D17"]["status"] == acceptance.PASS


@pytest.mark.asyncio
async def test_lab7_recorded_outputs_now_pass_d12_d23_and_d15(lab, monkeypatch):
    """Lab 7's recorded proposals (D12 month in details/time_expression; D23
    sale proposed as intent new) and its recorded D15 request ("Spiti trip")
    through the repaired code: D12, D23 and D15's automatic checks pass."""
    d12 = "I misspoke, the Jimny is from September, not October."
    d23 = "I sold the Classic 350 in October."
    monkeypatch.setitem(
        EXTRACT,
        d12,
        [
            item(
                "Jimny",
                d12,
                intent="correction",
                details="September",
                time_expression="September",
            )
        ],
    )
    monkeypatch.setitem(
        EXTRACT,
        d23,
        [
            item(
                "Classic 350",
                d23,
                intent="new",
                state="sold",
                time_expression="October",
                disposed_expression="October",
            )
        ],
    )
    monkeypatch.setitem(
        DRIVER,
        D15,
        (
            "read",
            ["owned_item.vehicle", "plan=Spiti trip"],
            "The Jimny: you're already taking it on your winter Spiti trip.",
        ),
    )
    runner, _log = lab.runner()
    summary = await runner.run(groups=("story",))
    cases = summary["cases"]
    for case in ("D12", "D23"):
        assert cases[case]["status"] == acceptance.PASS, cases[case]
    checks = _d15_checks(summary)
    assert (
        checks["decided plan reached the model (released this turn or in context)"]
        == acceptance.PASS
    )
    assert checks["answer consistent with the decided plan"] == acceptance.PASS
    assert checks["unrelated plans left out"] == acceptance.PASS


# Paid lab 4 D9: the recorded model outputs, replayed offline ---------------------

PAID4_D9 = json.loads(
    (Path(__file__).parent / "fixtures" / "paid4_d9_recorded.json").read_text(
        encoding="utf-8"
    )
)


def _recorded_as_scripted(step):
    """The recorded proposal unmodified, with its cited span given as the
    quote it covered (the scripted provider re-binds quotes to turns)."""
    st = PAID4_D9["steps"]
    first = st["idiom-01"]["utterance"]
    out = []
    for raw in st[step]["extraction"]["candidates"]:
        raw = json.loads(json.dumps(raw))
        (span,) = raw.pop("evidence")
        # Both recorded proposals cite the first turn's 49 characters.
        assert (span["start"], span["end"]) == (0, len(first))
        out.append({**raw, "quote": first})
    return out


@pytest.mark.asyncio
async def test_paid4_recorded_d9_outputs_now_pass_d9(lab, monkeypatch):
    """Paid lab 4 recorded D9 FAIL ("no vehicle options": ["Thar", "no Thar"]
    stored as an undecided vehicle). The same model outputs, replayed through
    the fixed code, pass the unchanged frozen checks."""
    st = PAID4_D9["steps"]
    for step in ("idiom-01", "idiom-02"):
        monkeypatch.setitem(EXTRACT, st[step]["utterance"], _recorded_as_scripted(step))
    runner, _log = lab.runner(stop_on_failure=True)
    summary = await runner.run(groups=("idiom",))
    d9 = {c["check"]: c["status"] for c in summary["cases"]["D9"]["checks"]}
    assert d9 == {
        "one Spiti plan": acceptance.PASS,
        "status planned": acceptance.PASS,
        "destination Spiti": acceptance.PASS,
        "no vehicle options": acceptance.PASS,
        "when January confirmed": acceptance.PASS,
        "no owned Thar": acceptance.PASS,
        "at most one question, only about the vehicle": acceptance.PASS,
    }, summary["cases"]["D9"]


# Paid lab 6 D9: the second recorded shape, replayed offline -----------------------

PAID6_D9 = json.loads(
    (Path(__file__).parent / "fixtures" / "paid6_d9_recorded.json").read_text(
        encoding="utf-8"
    )
)


def _lab6_as_scripted(step):
    """The recorded proposal unmodified; each cited span is given as the
    quote it covered in its own turn."""
    st = PAID6_D9["steps"]
    texts = {
        "b23b2888-2fc8-49e6-98fa-7225f74cbcc2": st["idiom-01"]["utterance"],
        "2ce657e5-28b6-4f09-abbc-cc297d7e7917": st["idiom-02"]["utterance"],
    }
    out = []
    for raw in st[step]["extraction"]["candidates"]:
        raw = json.loads(json.dumps(raw))
        quotes = [
            texts[span["turn_id"]][span["start"] : span["end"]]
            for span in raw.pop("evidence")
        ]
        out.append({**raw, "quote": quotes})
    return out


@pytest.mark.asyncio
async def test_paid6_recorded_d9_outputs_now_pass_d9(lab, monkeypatch):
    """Paid lab 6 recorded D9 FAIL: the lone option ["Thar"] was promoted to a
    tentative vehicle value. The same outputs (and the recorded "match" of the
    second turn to the Spiti plan), replayed through the general rules, pass
    the unchanged frozen checks."""
    st = PAID6_D9["steps"]
    (vehicle,) = [
        c["slots"]["vehicle"] for c in st["idiom-01"]["extraction"]["candidates"]
    ]
    assert vehicle == {"value": None, "options": ["Thar"], "certainty": "tentative"}
    for step in ("idiom-01", "idiom-02"):
        monkeypatch.setitem(EXTRACT, st[step]["utterance"], _lab6_as_scripted(step))
    assert [r["decision"] for r in st["idiom-02"]["resolution"]["resolutions"]] == [
        "match"
    ]
    monkeypatch.setitem(RESOLVE, st["idiom-02"]["utterance"], [("match", "spiti")])
    runner, log = lab.runner(stop_on_failure=True)
    summary = await runner.run(groups=("idiom",))
    d9 = {c["check"]: c["status"] for c in summary["cases"]["D9"]["checks"]}
    assert d9 == {
        "one Spiti plan": acceptance.PASS,
        "status planned": acceptance.PASS,
        "destination Spiti": acceptance.PASS,
        "no vehicle options": acceptance.PASS,
        "when January confirmed": acceptance.PASS,
        "no owned Thar": acceptance.PASS,
        "at most one question, only about the vehicle": acceptance.PASS,
    }, summary["cases"]["D9"]
    # The unclear vehicle reached the reply of the first turn, with what is
    # already known; the second turn (nothing unclear) carries no note.
    first = [
        e["input"]
        for e in _events(log, "driver_step", "idiom-01")
        if e.get("status") == "ok"
    ]
    (note,) = first[0]["learning_notes"]
    assert note["unclear"] == ["vehicle"] and "Thar" in note["owner_words"]
    assert note["already_known"] == {"destination": "Spiti", "when": "January"}
    assert not {"saved", "stored", "status"} & set(note)
    later = [e["input"] for e in _events(log, "driver_step", "idiom-02")]
    assert later and all("learning_notes" not in p for p in later)


# Amendment 2: plan alternatives wait for the owner ---------------------------


@pytest.mark.asyncio
async def test_amendment_2_alternatives_need_the_owners_confirmation(lab, monkeypatch):
    """Without a confirmation the destination options are never stored, and
    D6-A2 fails on them (not on the clear parts); the superseded frozen D6
    expectation is reported, not graded."""
    monkeypatch.setitem(ANSWERS, acceptance.D6_CONFIRMATION, [])
    runner, log = lab.runner()
    summary = await runner.run(groups=("story",))
    d6 = {c["check"]: c for c in summary["cases"]["D6-A2"]["checks"]}
    assert d6["no destination options stored before confirmation"]["status"] == (
        acceptance.PASS
    )
    assert d6["one question about the destination choices"]["status"] == (
        acceptance.PASS
    )
    assert d6["destination options [Ladakh, winter Spiti], undecided"]["status"] == (
        acceptance.FAIL
    )
    assert d6["when January"]["status"] == acceptance.PASS
    superseded = d6["frozen D6 expectation: destination options from the statement"]
    assert superseded["status"] == acceptance.SUPERSEDED
    assert superseded["detail"]["superseded_by"] == "amendment-2"
    # The confirmation turn's extraction was told the open question.
    first_reply = [
        e
        for e in log.read(log.events)
        if e.get("step_id") == "story-07" and e.get("kind") == "reply"
    ]
    (note,) = first_reply[0]["learning"]["clarification_notes"]
    assert note["question"] == "confirm_alternatives"
    assert note["choices"] == {"destination": ["Ladakh", "winter Spiti"]}
    assert note["already_known"] == {"when": "January"}


@pytest.mark.asyncio
async def test_amendment_2_other_answers_pass_d28_to_d30(lab):
    runner, _log = lab.runner(stop_on_failure=True)
    summary = await runner.run(groups=("alternatives",))
    for case in ("D28", "D29", "D30"):
        checks = {c["check"]: c["status"] for c in summary["cases"][case]["checks"]}
        assert set(checks.values()) == {acceptance.PASS}, (case, checks)


@pytest.mark.asyncio
@pytest.mark.parametrize("resolver", ["new", "match"])
async def test_recorded_ef0c9340_d28_passes_through_the_lab_runner(
    lab, monkeypatch, resolver
):
    """The latest D28 failure end to end through the lab runner: the scripted
    provider returns lab ef0c9340's recorded extractions (paraphrased name,
    only the answer turn cited, restated details), unmodified apart from
    evidence given as quotes of the same spans."""
    recorded = json.loads(
        (Path(__file__).parent / "fixtures" / "codex_ef0c9340_d28.json").read_text(
            encoding="utf-8"
        )
    )["steps"]
    texts = {}
    for step in ("alt-01", "alt-02"):
        for raw in recorded[step]["extraction"]["candidates"]:
            for span in raw["evidence"]:
                texts[span["turn_id"]] = recorded[step]["utterance"][
                    span["start"] : span["end"]
                ]
    for step in ("alt-01", "alt-02"):
        raws = []
        for raw in json.loads(json.dumps(recorded[step]["extraction"]["candidates"])):
            raw["quote"] = [texts[s["turn_id"]] for s in raw.pop("evidence")]
            raws.append(raw)
        monkeypatch.setitem(EXTRACT, recorded[step]["utterance"], raws)
    if resolver == "new":
        monkeypatch.setitem(RESOLVE, "We'll take the Jimny.", [("new", None)])
    runner, _log = lab.runner(stop_on_failure=True)
    summary = await runner.run(groups=("alternatives",))
    checks = {c["check"]: c["status"] for c in summary["cases"]["D28"]["checks"]}
    assert set(checks.values()) == {acceptance.PASS}, checks


# Bounded final evaluation: invariants stop, quality is measured ------------------

D11_8EA0FD4E_REPLY = "Understood, I've noted that the Goa plan is cancelled."


@pytest.mark.asyncio
async def test_recorded_d11_quality_miss_is_measured_and_its_false_claim_corrected(
    lab, monkeypatch
):
    """Paid lab 8ea0fd4e D11: the extractor proposed nothing for "Cancel the
    Goa plan." and the reply claimed it was noted. With stop_on="invariant"
    the storage miss is a quality measurement (the story continues), and the
    reply's claim is corrected from the record (nothing saved)."""
    monkeypatch.setitem(EXTRACT, "Cancel the Goa plan.", [])
    monkeypatch.setitem(DRIVER, "Cancel the Goa plan.", ("answer", D11_8EA0FD4E_REPLY))
    runner, _log = lab.runner(stop_on_failure=True, stop_on="invariant")
    summary = await runner.run(groups=("story",))
    assert summary["run_state"] != "stopped_on_failure"
    d11 = {c["check"]: c for c in summary["cases"]["D11"]["checks"]}
    assert d11["Goa status cancelled"]["status"] == acceptance.FAIL
    assert d11["Goa status cancelled"]["tier"] == "quality"
    # Later story cases still ran.
    assert "D17" in summary["cases"] and "D21" in summary["cases"]
    tiers = summary["tiers"]
    assert tiers["invariants"]["failed"] == []
    assert tiers["invariants"]["untested_cases"] == []
    # Only the story ran, so the other groups' invariants are not checked.
    assert tiers["invariants"]["verdict"] == acceptance.UNTESTED
    assert {"case": "D11", "check": "Goa status cancelled"} in tiers["quality"][
        "failed_checks"
    ]
    (claim,) = [c for c in summary["memory_claims"] if c["step_id"] == "story-11"]
    assert claim["claims"] == ["saved"]
    assert "nothing was saved" in claim["spoken"]


@pytest.mark.asyncio
async def test_a_failed_invariant_still_stops_the_bounded_evaluation(lab, monkeypatch):
    async def broken(context, log):
        return [{"check": "owned items unchanged", "level": "a", "status": "FAIL"}]

    monkeypatch.setitem(acceptance.CHECKS, "D1-A1", broken)
    runner, _log = lab.runner(stop_on_failure=True, stop_on="invariant")
    with pytest.raises(acceptance.AcceptanceStoppedOnFailure):
        await runner.run(groups=("story",))
    summary = json.loads(runner.log.summary.read_text(encoding="utf-8"))
    assert summary["stopped_on_failure"]["case"] == "D1-A1"
    assert summary["tiers"]["invariants"]["verdict"] == acceptance.FAIL


def test_untested_invariants_are_never_reported_as_passing():
    cases = {
        "D17": {
            "status": acceptance.UNTESTED,
            "checks": acceptance._tiered(
                [
                    {
                        "check": "forget gate (stage diagnosis)",
                        "status": acceptance.UNTESTED,
                        "detail": {"failed_stage": "owner_consent_not_granted"},
                    },
                    {"check": "lineage gone", "status": acceptance.UNTESTED},
                ]
            ),
        },
        "D2": {
            "status": acceptance.PASS,
            "checks": acceptance._tiered(
                [{"check": "A not retracted", "status": acceptance.PASS}]
            ),
        },
    }
    tiers = acceptance._tier_summary(cases)
    assert tiers["invariants"]["verdict"] == acceptance.UNTESTED
    assert tiers["invariants"]["untested_cases"] == ["D17"]


def test_d17_deletion_checks_are_invariants_only_when_the_code_failed():
    def tiers(stage):
        checks = acceptance._tiered(
            [
                {
                    "check": "forget gate (stage diagnosis)",
                    "status": acceptance.FAIL,
                    "detail": {"failed_stage": stage},
                },
                {"check": "lineage gone", "status": acceptance.FAIL},
            ]
        )
        return [c["tier"] for c in checks]

    assert tiers("model_did_not_select_available_item") == ["quality", "quality"]
    assert tiers("forget_operation_failed") == ["invariant", "invariant"]
    assert tiers(None) == ["quality", "invariant"]


def test_stop_on_accepts_only_known_modes(lab):
    with pytest.raises(ValueError):
        lab.runner(stop_on="sometimes")


def test_launcher_and_cli_accept_every_slice1_group():
    """The exact entry path: every group the runner defines is accepted by the
    Windows launcher's ValidateSet and by the lab CLI."""
    launcher = (REPO / "tools/windows/Start-JarvisProjectMemoryLab.ps1").read_text(
        encoding="utf-8"
    )
    (valid,) = re.findall(
        r"ValidateSet\(([^)]*)\)\]\[string\[\]\]\$Slice1Group", launcher
    )
    assert set(re.findall(r"'([^']+)'", valid)) == set(acceptance.GROUP_ORDER)
    assert "alternatives" in acceptance.GROUP_ORDER
    # The lab CLI's --slice1-group choices are GROUP_ORDER itself.
    source = (REPO / "src/jarvis/voice/project_memory_lab.py").read_text(
        encoding="utf-8"
    )
    assert (
        "GROUP_ORDER as SLICE1_GROUPS" in source and "choices=SLICE1_GROUPS" in source
    )


@pytest.mark.asyncio
async def test_paid_entry_runs_the_targeted_d9_and_alternatives_groups(
    lab, monkeypatch, authority_parts, tmp_path
):
    """The proposed targeted qualification, offline through the real entry
    point on the Paid lane (scripted clients, no network): only the idiom and
    alternatives groups run, every row is paid, no checkpoint allowance."""
    import types

    from jarvis.voice import paid_acceptance_budget, project_memory_lab

    monkeypatch.setitem(
        sys.modules,
        "msvcrt",
        types.SimpleNamespace(locking=lambda *a: None, LK_NBLCK=1, LK_UNLCK=0),
    )
    monkeypatch.setattr(
        authority_parts.broker._audit, "close", lambda: None, raising=False
    )
    monkeypatch.setattr(
        "jarvis.capabilities.authority_bridge.CapabilityAuthorityBroker",
        lambda: authority_parts.broker,
    )

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
    seen = {}

    def paid_clients(model, ledger, *, lab, allowance=None):
        seen["allowance"] = allowance
        return lab_deps.extractor, lab_driver

    lab_deps, lab_driver = lab.deps, lab.driver
    monkeypatch.setattr(paid_acceptance_budget, "build_paid_clients", paid_clients)
    root = lab.root / "entry-targeted"
    root.mkdir()
    ledger_path = _approved_test_ledger(
        monkeypatch, tmp_path / "ledger" / "ledger.sqlite3"
    )
    summary = await project_memory_lab.run_slice1_acceptance(
        types.SimpleNamespace(gemini_fallback=types.SimpleNamespace(enabled=True)),
        root,
        model="fictional-answer",
        source_commit="2" * 40,
        hashes=dict(acceptance.FROZEN_SHA256),
        groups=("idiom", "alternatives"),
        retry_interrupted=False,
        call_spacing_seconds=0.5,
        lane="paid",
        paid_ledger=ledger_path,
    )
    assert set(summary["cases"]) == {"D9", "D28", "D29", "D30"}
    assert {c: summary["cases"][c]["status"] for c in summary["cases"]} == {
        "D9": acceptance.PASS,
        "D28": acceptance.PASS,
        "D29": acceptance.PASS,
        "D30": acceptance.PASS,
    }
    assert seen["allowance"] is None
    assert [a["id"] for a in summary["acceptance_amendments"]] == [
        "amendment-1",
        "amendment-2",
    ]
    rows = [
        json.loads(x)
        for x in (root / "acceptance-steps.jsonl").read_text().splitlines()
    ]
    assert {row["lane"] for row in rows} == {"paid"}


# Held-out execution method (lab only; the sealed file is never read) ----------

FICTIONAL_SCRIPT = {
    "cases": [
        {
            "id": "H1",
            "steps": [
                {
                    "seed": [
                        {
                            "category": "owned_item",
                            "label": "Pulsar 150",
                            "kind": "vehicle",
                        }
                    ]
                },
                {
                    "say": "Which vehicles do I own?",
                    "told_at": "2026-11-17T10:00:00+05:30",
                },
            ],
        },
        {
            "id": "H2",
            "steps": [
                {
                    "say": "We're going to Spiti in January, Thar or Jimny.",
                    "told_at": "2026-11-18T10:00:00+05:30",
                },
                {
                    "say": "We'll take the Jimny.",
                    "told_at": "2026-11-18T10:01:00+05:30",
                    "same_conversation": True,
                },
                {"restart": True},
            ],
        },
    ]
}


def test_heldout_script_is_validated_without_any_case_content(tmp_path):
    from jarvis.voice import heldout_player

    path = tmp_path / "script.json"
    path.write_text(json.dumps(FICTIONAL_SCRIPT), encoding="utf-8")
    groups, checks, planned, sha = heldout_player.load_script(path)
    assert planned == ("H1", "H2") and set(checks) == {"H1", "H2"}
    assert [type(s).__name__ for s in groups["H2"]] == [
        "Say",
        "Say",
        "Restart",
        "Check",
    ]
    assert groups["H2"][1].new_session is False
    assert len(sha) == 64
    for bad in (
        {"cases": []},
        {
            "cases": [
                {
                    "id": "D9",
                    "steps": [{"say": "x", "told_at": "2026-11-17T10:00:00+05:30"}],
                }
            ]
        },
        {
            "cases": [
                {"id": "H1", "steps": [{"say": "x", "told_at": "2026-11-17T10:00:00"}]}
            ]
        },
        {
            "cases": [
                {
                    "id": "H1",
                    "steps": [
                        {
                            "say": "x",
                            "told_at": "2026-11-17T10:00:00+05:30",
                            "same_conversation": True,
                        }
                    ],
                }
            ]
        },
        {
            "cases": [
                {
                    "id": "H1",
                    "steps": [{"seed": [{"category": "routine", "label": "x"}]}],
                }
            ]
        },
        {"cases": [{"id": "H1", "steps": [{"restart": True}]}]},
    ):
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(heldout_player.HeldoutScriptError):
            heldout_player.load_script(path)


@pytest.mark.asyncio
async def test_heldout_player_records_every_case_for_manual_grading(lab, tmp_path):
    from jarvis.voice import heldout_player

    path = tmp_path / "script.json"
    path.write_text(json.dumps(FICTIONAL_SCRIPT), encoding="utf-8")
    groups, checks, planned, _sha = heldout_player.load_script(path)
    # The fictional turns use the scripted driver's existing answers.
    assert "Which vehicles do I own?" in DRIVER
    runner, _log = lab.runner(
        groups_map=groups, checks_map=checks, planned_cases=planned, not_run_here={}
    )
    summary = await runner.run()
    assert set(summary["cases"]) == {"H1", "H2"} and summary["untested"] == []
    for case in ("H1", "H2"):
        statuses = {c["status"] for c in summary["cases"][case]["checks"]}
        assert statuses == {acceptance.REVIEW}
    h2 = {c["check"]: c["detail"] for c in summary["cases"]["H2"]["checks"]}
    stored = h2["stored records (current and history), for manual grading"]
    current = [r for r in stored if r["current"]]
    assert [r["slots"]["vehicle"]["value"] for r in current] == ["Jimny"]
    replies = h2["lookups, learning outcomes and answers, for manual grading"]
    assert set(replies) == {"H2-01", "H2-02"}
    assert "D9" not in summary["cases"] and summary["planned_cases"] == ["H1", "H2"]


def test_heldout_mode_refuses_the_paid_lane_and_other_modes(tmp_path):
    from jarvis.voice import project_memory_lab

    base = [
        "--lab-root",
        str(tmp_path / "lab"),
        "--model",
        "m",
        "--source-commit",
        "0" * 40,
        "--slice1-acceptance",
        "--slice1-heldout-script",
        str(tmp_path / "s.json"),
    ]
    for extra in (
        ["--paid-lane", "--paid-budget-ledger", str(tmp_path / "l.sqlite3")],
        ["--slice1-group", "idiom"],
        ["--resume-lab"],
    ):
        with pytest.raises(SystemExit) as exc:
            project_memory_lab.main(base + extra)
        assert exc.value.code == 2
    launcher = (REPO / "tools/windows/Start-JarvisProjectMemoryLab.ps1").read_text(
        encoding="utf-8"
    )
    assert "--slice1-heldout-script" in launcher and "Free lane only" in launcher


# D17 in the final acceptance (f6bd4972): target resolution, not consent ------

STEPWISE_D17 = (
    "stepwise_forget",
    "classic",
    "Forgotten.",
    "Which Classic 350 record would you like me to forget?",
)


@pytest.mark.asyncio
async def test_d17_stepwise_reads_now_reach_consent_and_deletion(lab, monkeypatch):
    """The recorded tool flow (catalog, then one facet per read, starting with
    the Tigor, one read repeated) now resolves the target, reaches consent
    and deletes the item."""
    driver = dict(DRIVER)
    driver["Forget the Classic 350."] = STEPWISE_D17
    monkeypatch.setattr(sys.modules[__name__], "DRIVER", driver)
    runner, _log = lab.runner()
    summary = await runner.run(groups=("story",))
    d17 = {c["check"]: c for c in summary["cases"]["D17"]["checks"]}
    assert summary["cases"]["D17"]["status"] == acceptance.PASS, d17
    consent = d17["fresh owner consent granted (Windows Hello)"]
    assert consent["status"] == acceptance.PASS and consent["detail"]["reached"]
    stage = d17["forget gate (stage diagnosis)"]["detail"]
    statuses = [r["status"] for r in stage["target_reads"]]
    assert statuses and set(statuses) == {"selected"}, stage["target_reads"]
    assert summary["cases"]["D26"]["status"] == acceptance.PASS


@pytest.mark.asyncio
async def test_d17_consent_not_reached_is_untested_never_granted(lab, monkeypatch):
    """The final-acceptance grader passed "fresh owner consent granted" with
    an empty consent list. With no forget call there is no consent request:
    the check is UNTESTED (not reached), the case still FAILs on its stage."""
    driver = dict(DRIVER)
    driver["Forget the Classic 350."] = ("catalog_only", "Which one?")
    monkeypatch.setattr(sys.modules[__name__], "DRIVER", driver)
    runner, _ = lab.runner()
    summary = await runner.run(groups=("story",))
    d17 = {c["check"]: c for c in summary["cases"]["D17"]["checks"]}
    consent = d17["fresh owner consent granted (Windows Hello)"]
    assert consent["status"] == acceptance.UNTESTED
    assert consent["detail"]["reached"] is False
    assert consent["detail"]["consent_outcomes"] == []
    assert summary["cases"]["D17"]["status"] == acceptance.FAIL


def test_consent_check_distinguishes_granted_refused_and_not_reached():
    detail = {"forget_calls": [], "target_reads": []}
    granted = acceptance._consent_check([{"outcome": "granted"}], detail)
    refused = acceptance._consent_check([{"outcome": "PermissionError"}], detail)
    absent = acceptance._consent_check([], detail)
    assert [c["status"] for c in (granted, refused, absent)] == [
        acceptance.PASS,
        acceptance.FAIL,
        acceptance.UNTESTED,
    ]
