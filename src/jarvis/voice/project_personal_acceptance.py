"""Explicit fictional positive-recall fixture; no setup inference or owner data."""

from __future__ import annotations

import json
from contextlib import contextmanager, suppress
from types import SimpleNamespace
from uuid import uuid4

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.project_conversations import ProjectSelection
from jarvis.memory.project_routing import ProjectRoutingDecision
from jarvis.voice.memory_tools import MemoryAgentTools
from jarvis.voice.project_memory_development import run_case_question
from jarvis.voice.project_memory_lab import build_project_personal_session

PREDICATE = "diet preference"
PHASES = ("travel_initial", "study_shared", "travel_corrected")


def record_runtime_failure(root, report):
    """Terminal CLI boundary; retain cleanup diagnostics after the sequence returns."""
    persisted = False
    try:
        path = root / "personal-summary.json"
        try:
            summary = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            summary = {"completed": None, "unrun": "unknown; inspect retained JSONL"}
        summary.update(failed=1, runtime_failure=report)
        pending = root / "personal-summary.failed.json"
        with pending.open("x", encoding="utf-8") as output:
            json.dump(summary, output, indent=2)
        pending.replace(path)
        persisted = True
    except (OSError, UnicodeError):
        pass
    with suppress(OSError, UnicodeError):
        print(
            "PERSONAL_RUNTIME_FAILURE "
            + json.dumps({"report": report, "summary_persisted": persisted}),
            flush=True,
        )
    return persisted


@contextmanager
def _exclusive_report(path):
    stream = path.open("x", encoding="utf-8")
    try:
        yield stream
    except BaseException:
        with suppress(OSError, UnicodeError):
            stream.close()
        raise
    else:
        stream.close()


async def _mutate(memory, capability, operation, value):
    conversation = ConversationSession()
    conversation.start()
    text = (
        f"Remember that my diet preference is {value}."
        if operation == "remember"
        else f"Correct my diet preference to {value}."
    )
    print("FICTIONAL MEMORY COMMAND: " + text, flush=True)
    conversation.accept_turn(ConversationRole.USER, text)
    session = build_project_personal_session(conversation, memory, capability)
    tools = MemoryAgentTools(memory.service, conversation, personal_context=session)
    try:
        receipt = await getattr(tools, operation)(predicate=PREDICATE, value=value)
        if receipt.get("ok") is not True:
            raise PermissionError("fictional mutation did not commit")
        record = (await memory.service.inspect_exact(predicate=PREDICATE)).record
        if record.assertion_id != receipt["memory_id"] or record.value != value:
            raise PermissionError("fictional mutation receipt mismatch")
        return record
    finally:
        session.close()


class _EvidenceProvider:
    def __init__(self, provider, coordinator, expected, stale):
        self.provider, self.coordinator = provider, coordinator
        self.expected, self.stale = expected, stale
        self.evidence = {}

    async def step(self, packet, **kwargs):
        personal = json.loads(packet.context).get("personal", {})
        texts = [f.get("text") for f in personal.get("facts", [])]
        projection = getattr(self.coordinator._personal, "_query_projection", None)
        ids = {r.assertion_id for r in projection.selected} if projection else set()
        self.evidence = {
            "expected_assertion_selected": self.expected.assertion_id in ids,
            "stale_assertion_selected": self.stale is not None
            and self.stale.assertion_id in ids,
            "expected_fact_in_final_context": personal.get("status") == "selected"
            and self.expected.normalized_text in texts,
            "stale_fact_in_personal_context": self.stale is not None
            and self.stale.normalized_text in texts,
        }
        return await self.provider.step(packet, **kwargs)


async def _select(access, title, *, new_thread=False):
    catalog = await access.catalog()
    entries = [e for e in catalog.entries if e.title == title]
    if len({e.selection.project_id for e in entries}) > 1:
        raise PermissionError("ambiguous fixture project")
    entry = entries[-1] if entries else None
    selection = (
        ProjectSelection(
            entry.selection.project_id, str(uuid4()), entry.selection.revision
        )
        if entry and new_thread
        else entry.selection
        if entry
        else ProjectSelection(str(uuid4()), str(uuid4()), 0)
    )
    await access.select(
        ProjectRoutingDecision(
            "ready",
            selection,
            title,
            catalog.selection_revision,
            entry.archive_revision if entry and not new_thread else 0,
            create=entry is None,
            new_thread=bool(entry and new_thread),
        )
    )
    return selection


async def _question(access, coordinator, provider, selection, phase, expected, stale):
    catalog = await access.catalog()
    target_ids, all_ids = set(), set()
    for project_id in {e.selection.project_id for e in catalog.entries}:
        entry = next(e for e in catalog.entries if e.selection.project_id == project_id)
        snapshot = await access.snapshot(entry.selection, limit=128, project_wide=True)
        ids = {s.event.event_id for s in snapshot.sources}
        all_ids.update(ids)
        if project_id == selection.project_id:
            target_ids.update(ids)
    manifest = {
        "project_id": selection.project_id,
        "thread_id": selection.thread_id,
        "target_source_ids": sorted(target_ids),
        "seeded_source_ids": sorted(all_ids),
        "seeded_events": 0,
    }
    case = SimpleNamespace(
        question={
            "id": phase,
            "question": "What is my saved diet preference?",
            "expected": expected.value,
            "source_ids": [],
        }
    )
    observer = _EvidenceProvider(provider, coordinator, expected, stale)
    report = await run_case_question(case, manifest, coordinator, access, observer)
    report.update(
        kind="question",
        split="supplemental_personal_fixture",
        project_id=selection.project_id,
        thread_id=selection.thread_id,
        expected_personal_assertion_id=expected.assertion_id,
        stale_personal_assertion_id=stale.assertion_id if stale else None,
        personal_evidence=observer.evidence,
    )
    return report


async def run_personal_acceptance(
    root,
    *,
    memory,
    capability,
    coordinator,
    access,
    provider,
    source_commit=None,
    model=None,
):
    """Three questions, independent accepted sessions, real guarded mutation/read."""
    summary = {
        "kind": "personal-recall-correction-v1",
        "planned": 3,
        "completed": 0,
        "failed": 0,
        "unrun": list(PHASES),
        "answer_quality": "manual_review_required",
        "source_commit": source_commit,
        "model": model,
        "limits": "Supplemental fixture only; no automatic learning, restart, native voice, held-out accuracy or speed qualification.",
    }
    # Exclusive output first: accidental rerun must not perform another mutation.
    with (
        _exclusive_report(root / "personal-results.jsonl") as stream,
        _exclusive_report(root / "personal-summary.json") as output,
    ):

        def emit(row):
            row.update(source_commit=source_commit, model=model)
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            print(
                "PERSONAL_ACCEPTANCE " + json.dumps(row, ensure_ascii=False), flush=True
            )

        stage = "empty_fixture"
        primary = None
        try:
            if (await access.catalog()).entries or (
                await memory.retrieval.learning_context_snapshot()
            ).entries:
                raise PermissionError("empty isolated fixture required")
            stage = "remember"
            current = await _mutate(memory, capability, "remember", "vegetarian")
            emit(
                {
                    "kind": "mutation",
                    "operation": "remember",
                    "status": "committed",
                    "assertion_id": current.assertion_id,
                }
            )
            stale = None
            for index, phase in enumerate(PHASES):
                stage = phase
                if index == 2:
                    stage = "correct"
                    stale = current
                    current = await _mutate(memory, capability, "correct", "vegan")
                    emit(
                        {
                            "kind": "mutation",
                            "operation": "correct",
                            "status": "committed",
                            "assertion_id": current.assertion_id,
                            "superseded_assertion_id": stale.assertion_id,
                        }
                    )
                    stage = phase
                title = "Study acceptance" if index == 1 else "Travel acceptance"
                selection = await _select(access, title, new_thread=index == 2)
                report = await _question(
                    access, coordinator, provider, selection, phase, current, stale
                )
                summary["unrun"].remove(phase)
                try:
                    emit(report)
                except (OSError, UnicodeError):
                    summary["terminal_case_result"] = report
                    summary["reporting_error"] = "question_record_incomplete"
                    raise
                evidence = report["personal_evidence"]
                if not (
                    evidence.get("expected_assertion_selected")
                    and evidence.get("expected_fact_in_final_context")
                    and not evidence.get("stale_assertion_selected")
                    and not evidence.get("stale_fact_in_personal_context")
                ):
                    raise PermissionError("required personal evidence absent")
                summary["completed"] += 1
        except BaseException as exc:
            primary = exc
            summary["failed"] = 1
            with suppress(OSError, UnicodeError):
                emit(
                    {
                        "kind": "failure",
                        "stage": stage,
                        "error": type(exc).__name__,
                        "failed_usage": "unknown; earlier completed question usage retained",
                    }
                )
            raise
        finally:
            try:
                json.dump(summary, output, indent=2)
                output.flush()
                print("PERSONAL_SUMMARY " + json.dumps(summary), flush=True)
            except (OSError, UnicodeError):
                if primary is None:
                    raise
    return summary
