"""Controlled-text evaluation of automatic personal-context use; fictional data.

Two arms, each in its own fresh isolated lab (Free lane only, no Paid fallback):

- ``without``: the same projects and questions, no saved personal facts.
- ``with``: fictional facts saved through the real explicit memory path
  (MemoryAgentTools, fresh Windows Hello per mutation), then the questions.

Case 1, travel while an unrelated project is active: "Spiti Valley trip" (its
own travel decision: fly, then a hired driver) is the active project. The owner
asks for help getting to Gokarna without naming any vehicle; then, in a fresh
session and new thread, asks an ambiguous follow-up that names no trip.
Case 2, advice after a correction: diet preference vegetarian, corrected to
vegan; a fresh session in another project asks for a quick dinner idea without
naming the preference.

Every provider step's full input (what the model saw) and parsed output, the
personal requests, the facts Jarvis selected and the final answer are written
to ``context-eval-<arm>.jsonl``. Automatic checks are coarse keyword flags that
locate the FIRST failing stage (routing, personal request, selection, final
context, answer); they never grade an answer on their own. No setup inference,
no automatic retry, and no expected answer reaches the model.
"""

from __future__ import annotations

import json
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from jarvis.authority.conversation_history import HistoryActionBinding
from jarvis.conversation import (
    ConversationRole,
    ConversationSession,
    ConversationTurn,
)
from jarvis.memory.project_conversation_store import archive_digest
from jarvis.memory.project_conversations import ConversationEvent, ProjectSelection
from jarvis.memory.project_history_source import standard_history_source
from jarvis.memory.project_routing import (
    ProjectClarificationRequired,
    ProjectRoutingDecision,
)
from jarvis.voice.memory_tools import MemoryAgentTools
from jarvis.voice.project_answer_provider import ProjectAnswerProvider
from jarvis.voice.project_memory_lab import build_project_personal_session

ARMS = ("without", "with")
KIND = "personal-context-eval-v1"
ACTIVE_TRIP = "Spiti Valley trip"
OTHER_PROJECT = "Home errands"

PROJECTS = {
    ACTIVE_TRIP: (
        ("user", "We are planning a Spiti Valley trip for June."),
        (
            "user",
            (
                "For Spiti we will fly to Chandigarh and hire a local driver for "
                "the mountain roads."
            ),
        ),
        ("assistant", "Noted: fly to Chandigarh, then a hired local driver."),
        ("user", "Book the homestay in Kaza for four nights."),
        ("assistant", "Okay, four nights at the homestay in Kaza."),
    ),
    OTHER_PROJECT: (
        ("user", "We are tracking home errands here."),
        ("user", "The plumber visits on Saturday morning."),
        ("assistant", "Noted, the plumber comes Saturday morning."),
    ),
}

# Fictional facts; the predicate is named in each command, as a real owner would.
VEHICLES = (
    "vehicles",
    "a Mahindra Thar diesel 4x4 and an Ather 450X electric scooter",
)
DIET = ("diet preference", "vegetarian", "vegan")

QUESTIONS = (
    {
        "id": "travel_named_destination",
        "case": "travel",
        "project": ACTIVE_TRIP,
        "new_thread": False,
        "question": "I'm going to Gokarna from Bengaluru for a long weekend next "
        "month. Help me decide how to get there.",
        "advice": True,
        "scope": "owned_item.vehicle",
    },
    {
        "id": "travel_ambiguous_followup",
        "case": "travel",
        "project": ACTIVE_TRIP,
        "new_thread": True,
        "question": "Should I just drive myself for the trip, then?",
        "advice": True,
        "scope": "owned_item.vehicle",
    },
    {
        "id": "dinner_after_correction",
        "case": "diet",
        "project": OTHER_PROJECT,
        "new_thread": True,
        "question": "What should I cook for dinner tonight? Something quick.",
        "advice": True,
        "scope": "food_preference",
    },
)

_VEHICLE_WORDS = ("thar", "ather", "scooter", "4x4")
_TRADEOFF_WORDS = (
    "hour",
    "km",
    "kilomet",
    "fuel",
    "diesel",
    "charg",
    "range",
    "tiring",
    "comfort",
    "parking",
    "cost",
    "highway",
    "luggage",
    "train",
    "bus",
    "flight",
    "fly",
)
_NOT_VEGAN = (
    "paneer",
    "cheese",
    "curd",
    "yogurt",
    "yoghurt",
    "ghee",
    "butter",
    "cream",
    "milk",
    "egg",
    "honey",
    "chicken",
    "fish",
    "mutton",
    "prawn",
    "meat",
)


def _has(text, words):
    folded = (text or "").casefold()
    return sorted({w for w in words if w in folded})


def answer_checks(question_id, arm, answer, *, clarified_by_router=False):
    """Coarse keyword flags for locating a failure; manual review decides."""
    text = (answer or "").casefold()
    if question_id == "travel_named_destination":
        vehicles = _has(text, _VEHICLE_WORDS)
        return {
            "names_destination": "gokarna" in text,
            "mentions_active_trip": bool(_has(text, ("spiti", "kaza", "chandigarh"))),
            "vehicle_terms": vehicles,
            "tradeoff_terms": _has(text, _TRADEOFF_WORDS),
            "passes": "gokarna" in text
            and not _has(text, ("spiti", "kaza", "chandigarh"))
            and (
                bool(vehicles) if arm == "with" else not _has(text, ("thar", "ather"))
            ),
        }
    if question_id == "travel_ambiguous_followup":
        asks = "?" in (answer or "")
        names_both = "gokarna" in text and "spiti" in text
        which = "which trip" in text or "which one" in text
        return {
            "asks_a_question": asks,
            "names_both_trips": names_both,
            "asks_which_trip": which,
            "clarified_by_router": clarified_by_router,
            "passes": clarified_by_router or (asks and (names_both or which)),
        }
    if question_id == "dinner_after_correction":
        not_vegan = _has(text, _NOT_VEGAN)
        says_vegetarian = "vegetarian" in text
        says_vegan = "vegan" in text.replace("vegetarian", "")
        return {
            "non_vegan_terms": not_vegan,
            "mentions_vegetarian": says_vegetarian,
            "mentions_vegan": says_vegan,
            "relies_on_old_preference": says_vegetarian and not says_vegan,
            "passes": not not_vegan and not (says_vegetarian and not says_vegan)
            if arm == "with"
            else True,
        }
    raise ValueError("unknown evaluation question")


def first_failure(question, arm, row):
    """The first pipeline stage that failed, in order; None when all passed."""
    if row.get("status") != "completed":
        return "operation"
    if not row["routing"]["stayed_in_selected_project"]:
        return "routing"
    if question["id"] == "travel_ambiguous_followup" and row["answer_checks"]["passes"]:
        return None  # clarifying needs no personal fact
    if arm == "with":
        if question["scope"] not in row["personal"]["requested_scopes"]:
            return "personal_request"
        if (
            not row["personal"]["expected_selected"]
            or row["personal"]["stale_selected"]
        ):
            return "selection"
        if (
            not row["personal"]["expected_in_final_context"]
            or row["personal"]["stale_in_final_context"]
        ):
            return "final_context"
    if not row["answer_checks"]["passes"]:
        return "answer"
    return None


CASES = ("travel", "diet")


async def _open_personal_reads(session):
    """Open the read-only personal session now; record the exact outcome."""
    started = time.perf_counter()
    row = {
        "kind": "authorization",
        "capability": "memory:personal_context_session",
        "requested": "at_start",
    }
    try:
        await session.active_grant()
    except PermissionError as exc:
        cause = exc.__cause__
        row.update(
            result="refused",
            reason=str(cause) if cause is not None else str(exc),
            error_type=type(cause or exc).__name__,
        )
    else:
        row.update(result="approved", reason=None, opened=session.opened)
    row["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    print("PERSONAL_READS " + json.dumps(row), flush=True)
    return row


class RecordingClient:
    """Wraps the routed client: records exactly what each step sent and got."""

    def __init__(self, client):
        self.client = client
        self.steps = []

    async def parse_with_telemetry(self, **kwargs):
        record = {
            "operation_id": kwargs.get("operation_id"),
            "input_payload": json.loads(json.dumps(kwargs["input_payload"])),
        }
        self.steps.append(record)
        result = await self.client.parse_with_telemetry(**kwargs)
        response = result.parsed.response
        record["output"] = response.model_dump(mode="json")
        record["output_kind"] = type(response).__name__.lstrip("_")
        return result


async def _seed_project(access, title, turns, start):
    """Fictional history through real source-bound admission; no inference."""
    selection = ProjectSelection(str(uuid4()), str(uuid4()), 0)
    catalog = await access.catalog()
    await access.select(
        ProjectRoutingDecision(
            "ready", selection, title, catalog.selection_revision, create=True
        )
    )
    tag = uuid4().hex[:8]
    for revision, (role, text) in enumerate(turns):
        event = ConversationEvent(
            event_id=f"eval-{tag}-e{revision}",
            segment_id=f"eval-{tag}-segment",
            request_id=f"eval-{tag}-request-{revision // 2}",
            role=role,
            text=text,
            accepted_at=start + timedelta(minutes=revision),
        )
        turn = ConversationTurn(
            ConversationRole(role),
            text,
            turn_id=event.event_id,
            accepted_at=event.accepted_at,
        )
        if not standard_history_source(turn):
            raise ValueError("ineligible evaluation fixture source")
        material = access.store.append_material(selection, event, revision)
        issuer = access.authority
        issuer.register_source(access.grant, event.event_id, source=event)
        try:
            permit = issuer.issue_child(
                access.grant,
                HistoryActionBinding(
                    "admit",
                    event.event_id,
                    archive_digest(material),
                    targets=(
                        ("project", selection.project_id),
                        ("thread", selection.thread_id),
                    ),
                ),
            )
            await access.store.append_event(
                selection, event, permit=permit, expected_revision=revision
            )
        finally:
            issuer.release_source(access.grant, event.event_id)
    return selection, [f"eval-{tag}-e{i}" for i in range(len(turns))]


async def _select(access, title, *, new_thread):
    catalog = await access.catalog()
    entries = [e for e in catalog.entries if e.title == title]
    if len({e.selection.project_id for e in entries}) != 1:
        raise PermissionError("fixture project missing or ambiguous")
    entry = entries[-1]
    selection = (
        ProjectSelection(
            entry.selection.project_id, str(uuid4()), entry.selection.revision
        )
        if new_thread
        else entry.selection
    )
    await access.select(
        ProjectRoutingDecision(
            "ready",
            selection,
            title,
            catalog.selection_revision,
            0 if new_thread else entry.archive_revision,
            new_thread=new_thread,
        )
    )
    return selection


async def _mutate(memory, capability, operation, predicate, value):
    conversation = ConversationSession()
    conversation.start()
    text = (
        f"Remember that my {predicate} {'are' if predicate.endswith('s') else 'is'} "
        f"{value}."
        if operation == "remember"
        else f"Correct my {predicate} to {value}."
    )
    print("FICTIONAL MEMORY COMMAND: " + text, flush=True)
    conversation.accept_turn(ConversationRole.USER, text)
    session = build_project_personal_session(conversation, memory, capability)
    tools = MemoryAgentTools(memory.service, conversation, personal_context=session)
    try:
        receipt = await getattr(tools, operation)(predicate=predicate, value=value)
        if receipt.get("ok") is not True:
            raise PermissionError("fictional mutation did not commit")
        record = (await memory.service.inspect_exact(predicate=predicate)).record
        if record.assertion_id != receipt["memory_id"] or record.value != value:
            raise PermissionError("fictional mutation receipt mismatch")
        return record
    finally:
        session.close()


def _personal_evidence(steps, projection, expected, stale):
    requested = [
        r
        for step in steps
        for r in step.get("output", {}).get("personal_requests", []) or []
    ]
    final = steps[-1]["input_payload"]["context"].get("personal", {}) if steps else {}
    texts = [f.get("text") for f in final.get("facts", []) or []]
    ids = {r.assertion_id for r in projection.selected} if projection else set()
    return {
        "requested": requested,
        "requested_scopes": sorted({r.get("scope_key") for r in requested}),
        "query_status": final.get("status"),
        "selected_assertion_ids": sorted(ids),
        "selected_facts": texts,
        "expected_assertion_id": expected.assertion_id if expected else None,
        "stale_assertion_id": stale.assertion_id if stale else None,
        "expected_selected": bool(expected) and expected.assertion_id in ids,
        "stale_selected": bool(stale) and stale.assertion_id in ids,
        "expected_in_final_context": bool(expected)
        and expected.normalized_text in texts,
        "stale_in_final_context": bool(stale) and stale.normalized_text in texts,
    }


async def _ask(coordinator, access, provider, recorder, question, selection, facts):
    conversation = ConversationSession()
    conversation.start()
    recorder.steps.clear()
    projections = []

    class Observed:
        async def step(self, packet, **kwargs):
            try:
                return await provider.step(packet, **kwargs)
            finally:
                projections.append(
                    getattr(coordinator._personal, "_query_projection", None)
                )

    print("Owner> " + question["question"], flush=True)
    started = time.perf_counter()
    row = {
        "kind": "question",
        "question_id": question["id"],
        "case": question["case"],
        "question": question["question"],
        "project": question["project"],
        "new_thread": question["new_thread"],
    }
    clarified = False
    answer = ""
    packet = None
    try:
        result = await coordinator.respond(
            conversation,
            conversation.accept_turn(ConversationRole.USER, question["question"]),
            provider=Observed(),
            authorize=access.current,
        )
        await coordinator.validate_for_release(result)
        if not coordinator.validate_current(result.packet):
            raise PermissionError("answer invalidated")
        await coordinator.record_assistant(
            conversation, result, delivered_text=result.answer
        )
        answer, packet = result.answer, result.packet
        row["status"] = "completed"
    except ProjectClarificationRequired as exc:
        clarified, answer = True, exc.question
        row["status"] = "completed"
    except Exception as exc:  # noqa: BLE001 - recorded; the run stops after it
        row.update(status="failed", error=type(exc).__name__)
    print("Jarvis> " + (answer or "(no answer)"), flush=True)
    expected, stale = facts.get(question["scope"], (None, None))
    projection = next((p for p in reversed(projections) if p is not None), None)
    context = json.loads(packet.context) if packet is not None else {}
    row.update(
        answer=answer,
        elapsed_ms=round((time.perf_counter() - started) * 1000),
        routing={
            "action": (context.get("routing") or {}).get("action"),
            "clarified_by_router": clarified,
            "selected_project_id": packet.selection.project_id if packet else None,
            "expected_project_id": selection.project_id,
            "stayed_in_selected_project": clarified
            or (
                packet is not None
                and packet.selection.project_id == selection.project_id
            ),
        },
        personal=_personal_evidence(recorder.steps, projection, expected, stale),
        steps=[dict(s) for s in recorder.steps],
    )
    return row, clarified


async def run_context_eval(
    root,
    *,
    arm,
    memory,
    capability,
    coordinator,
    access,
    provider,
    source_commit=None,
    model=None,
    personal_session=None,
    case=None,
):
    if arm not in ARMS:
        raise ValueError("unknown evaluation arm")
    if case is not None and case not in CASES:
        raise ValueError("unknown evaluation case")
    questions = [q for q in QUESTIONS if case is None or q["case"] == case]
    recorder = RecordingClient(provider.client)
    recorded = ProjectAnswerProvider(recorder)
    summary = {
        "kind": KIND,
        "arm": arm,
        "case": case,
        "planned": [q["id"] for q in questions],
        "not_run": [q["id"] for q in QUESTIONS if q not in questions],
        "completed": [],
        "first_failures": {},
        "answer_quality": "manual_review_required",
        "source_commit": source_commit,
        "model": model,
        "limits": "Controlled text through the project answer model (Free lane), "
        "not Gemini Live voice. Keyword checks only locate failures.",
    }
    with (
        (root / f"context-eval-{arm}.jsonl").open("x", encoding="utf-8") as stream,
        (root / f"context-eval-{arm}-summary.json").open("x", encoding="utf-8") as out,
    ):

        def emit(row):
            row.update(arm=arm, source_commit=source_commit, model=model)
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            stream.flush()

        try:
            if personal_session is not None:
                # As live Jarvis does at startup: the personal-read session is
                # approved before any question, never mid-question. A refusal
                # stops the run before any seeding, memory command or model call.
                authorization = await _open_personal_reads(personal_session)
                emit(authorization)
                if authorization["result"] != "approved":
                    for question in questions:
                        emit(
                            {
                                "kind": "question",
                                "question_id": question["id"],
                                "status": "authorization_blocked",
                                "reason": authorization["reason"],
                            }
                        )
                    summary["authorization_blocked"] = summary["planned"]
                    raise PermissionError("personal-read session was not approved")
                summary["personal_reads"] = "approved_at_start"
            if (await access.catalog()).entries or (
                await memory.retrieval.learning_context_snapshot()
            ).entries:
                raise PermissionError("empty isolated fixture required")
            start = datetime(2026, 11, 1, 9, tzinfo=UTC)
            for offset, (title, turns) in enumerate(PROJECTS.items()):
                _, ids = await _seed_project(
                    access, title, turns, start + timedelta(days=offset)
                )
                emit({"kind": "seed", "project": title, "event_ids": ids})
            facts = {}
            for question in questions:
                if arm == "with" and question["scope"] not in facts:
                    if question["scope"] == "owned_item.vehicle":
                        record = await _mutate(
                            memory, capability, "remember", *VEHICLES
                        )
                        facts["owned_item.vehicle"] = (record, None)
                        emit(
                            {
                                "kind": "mutation",
                                "operation": "remember",
                                "fact": " ".join(VEHICLES),
                                "assertion_id": record.assertion_id,
                            }
                        )
                    else:
                        old = await _mutate(
                            memory, capability, "remember", DIET[0], DIET[1]
                        )
                        emit(
                            {
                                "kind": "mutation",
                                "operation": "remember",
                                "fact": f"{DIET[0]} {DIET[1]}",
                                "assertion_id": old.assertion_id,
                            }
                        )
                        new = await _mutate(
                            memory, capability, "correct", DIET[0], DIET[2]
                        )
                        facts["food_preference"] = (new, old)
                        emit(
                            {
                                "kind": "mutation",
                                "operation": "correct",
                                "fact": f"{DIET[0]} {DIET[2]}",
                                "assertion_id": new.assertion_id,
                                "superseded_assertion_id": old.assertion_id,
                            }
                        )
                selection = await _select(
                    access, question["project"], new_thread=question["new_thread"]
                )
                row, clarified = await _ask(
                    coordinator, access, recorded, recorder, question, selection, facts
                )
                row["answer_checks"] = answer_checks(
                    question["id"], arm, row["answer"], clarified_by_router=clarified
                )
                if personal_session is not None:
                    row["personal_session_opened_total"] = personal_session.opened
                row["first_failure"] = first_failure(question, arm, row)
                emit(row)
                print(
                    "CONTEXT_EVAL "
                    + json.dumps(
                        {
                            "arm": arm,
                            "question": question["id"],
                            "requested_scopes": row["personal"]["requested_scopes"],
                            "selected_facts": row["personal"]["selected_facts"],
                            "first_failure": row["first_failure"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                summary["first_failures"][question["id"]] = row["first_failure"]
                if row["status"] != "completed":
                    raise RuntimeError("evaluation question did not complete")
                summary["completed"].append(question["id"])
        except BaseException as exc:
            summary["stopped"] = type(exc).__name__
            with suppress(OSError, UnicodeError):
                emit({"kind": "failure", "error": type(exc).__name__})
            raise
        finally:
            json.dump(summary, out, indent=2)
            print("CONTEXT_EVAL_SUMMARY " + json.dumps(summary), flush=True)
    return summary
