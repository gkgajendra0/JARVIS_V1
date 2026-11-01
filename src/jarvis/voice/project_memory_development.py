"""Opt-in six-case development measurement; never an automatic accuracy grade."""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from jarvis.authority.conversation_history import HistoryActionBinding
from jarvis.memory.project_conversation_store import archive_digest
from jarvis.memory.project_conversations import ConversationEvent, ProjectSelection
from jarvis.memory.project_routing import ProjectRoutingDecision

CASE_IDS = ("p0-q0", "p1-q1", "p2-q2", "p3-q3", "p4-q4", "p5-q5")
FIXTURE_HASHES = {
    "questions-v1.json": "0ea667daadbf7de34c409598e6a7e62355fe53f1896d0533f867c03a6fedf7a0",
    "events-v1.json": "b6fbdbe38e80a8b6fd15afc73f4f847c345dabca1b2b41aae51d9ab22faacd16",
}


@dataclass(frozen=True)
class DevelopmentCase:
    question: dict
    events: tuple[dict, ...]


def load_cases(repo: Path):
    """Normalize checkout line endings, then verify the frozen source datasets."""
    datasets = {}
    for name, expected in FIXTURE_HASHES.items():
        text = (repo / "tests/project_memory/fixtures" / name).read_text(
            encoding="utf-8"
        )
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != expected:
            raise ValueError("frozen development fixtures changed")
        datasets[name] = json.loads(text)
    questions = {q["id"]: q for q in datasets["questions-v1.json"]}
    cases = []
    for ident in CASE_IDS:
        question = questions[ident]
        if question["split"] != "development":
            raise ValueError("development questions only")
        target = int(question["project_id"][1:])
        projects = {f"p{(target + offset) % 10}" for offset in range(3)}
        events = tuple(
            e for e in datasets["events-v1.json"] if e["project_id"] in projects
        )
        if len(events) != 60:
            raise ValueError("fixed sixty-event case required")
        cases.append(DevelopmentCase(question, events))
    return tuple(cases)


async def seed_development_case(access, case: DevelopmentCase):
    """Fresh archive only, real source-bound permits, no inference or budget change."""
    from jarvis.conversation import ConversationRole, ConversationTurn
    from jarvis.voice.project_memory_lab import standard_history_source

    catalog = await access.catalog()
    if catalog.entries:
        raise ValueError("development fixture requires an empty archive")
    selections = {}
    titles = {}
    for row in case.events:
        key = row["project_id"]
        if key not in selections:
            # Frozen fixture format, not a general natural-language title extractor.
            prefix = "We are discussing "
            if not row["text"].startswith(prefix) or not row["text"].endswith("."):
                raise ValueError("invalid frozen project header")
            title = row["text"][len(prefix) : -1]
            selection = ProjectSelection(str(uuid4()), str(uuid4()), 0)
            catalog = await access.catalog()
            await access.select(
                ProjectRoutingDecision(
                    "ready", selection, title, catalog.selection_revision, create=True
                )
            )
            selections[key], titles[key] = selection, title
        selection = selections[key]
        event = ConversationEvent(
            **{
                k: v
                for k, v in row.items()
                if k not in {"project_id", "thread_id", "accepted_at"}
            },
            accepted_at=datetime.fromisoformat(row["accepted_at"]),
        )
        turn = ConversationTurn(
            ConversationRole(event.role),
            event.text,
            turn_id=event.event_id,
            accepted_at=event.accepted_at,
        )
        if not standard_history_source(turn):
            raise ValueError("ineligible development fixture source")
        revision = int(event.event_id.rsplit("e", 1)[1])
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
    target = case.question["project_id"]
    selection = selections[target]
    catalog = await access.catalog()
    await access.select(
        ProjectRoutingDecision(
            "ready",
            selection,
            titles[target],
            catalog.selection_revision,
            archive_revision=20,
        )
    )
    return {
        "case_id": case.question["id"],
        "project_id": selection.project_id,
        "thread_id": selection.thread_id,
        "seeded_events": len(case.events),
        "target_source_ids": [
            e["event_id"] for e in case.events if e["project_id"] == target
        ],
        "seeded_source_ids": [e["event_id"] for e in case.events],
    }


class DevelopmentProvider:
    """Check selected scope on every provider step, without exposing the rubric."""

    def __init__(self, provider, manifest):
        self.provider, self.manifest = provider, manifest
        self.foreign_ids = set()
        self.contexts_seen = 0

    async def step(self, packet, **kwargs):
        checked = kwargs["check"]()
        if inspect.isawaitable(checked):
            await checked
        self.contexts_seen += 1
        self.foreign_ids.update(
            set(packet.source_ids)
            & (
                set(self.manifest["seeded_source_ids"])
                - set(self.manifest["target_source_ids"])
            )
        )
        if self.foreign_ids or (
            packet.selection.project_id,
            packet.selection.thread_id,
        ) != (self.manifest["project_id"], self.manifest["thread_id"]):
            raise PermissionError("development source scope mismatch")
        return await self.provider.step(packet, **kwargs)


def _number(value):
    return type(value) in {int, float} and math.isfinite(value) and value >= 0


def case_report(case, manifest, result, observer, *, elapsed_ms):
    rows = result.usage
    known = [
        r["usage"]["total_tokens"]
        for r in rows
        if r.get("observed") is True
        and type(r.get("usage", {}).get("total_tokens")) is int
        and r["usage"]["total_tokens"] >= 0
    ]
    latencies = [r["latency_ms"] for r in rows if _number(r.get("latency_ms"))]
    unknown = len(rows) - len(known)
    sources = set(result.packet.source_ids)
    return {
        "case_id": case.question["id"],
        "split": "development",
        "status": "completed",
        "question": case.question["question"],
        "expected_manual_rubric": case.question["expected"],
        "answer": result.answer,
        "answer_quality": "manual_review_required",
        "request_id": result.packet.request_id,
        "context_revision": result.packet.revision,
        "expected_source_ids": case.question["source_ids"],
        "expected_sources_in_final_context": sorted(
            sources & set(case.question["source_ids"])
        ),
        "final_source_ids": sorted(sources),
        "foreign_fixture_sources_seen": sorted(observer.foreign_ids),
        "contexts_checked": observer.contexts_seen,
        "seeded_events": manifest.get("seeded_events"),
        "returned_provider_steps": len(rows),
        "usage": {
            "total_tokens": sum(known) if not unknown and rows else None,
            "known_total_tokens": sum(known),
            "unknown_steps": unknown,
        },
        "provider_latency_ms": sum(latencies)
        if len(latencies) == len(rows) and rows
        else None,
        "known_provider_latency_ms": sum(latencies),
        "unknown_provider_latency_steps": len(rows) - len(latencies),
        "elapsed_ms": elapsed_ms,
        "step_telemetry": rows,
    }


async def run_case_question(case, manifest, coordinator, access, provider):
    """One accepted question, release and persisted answer; no retries or input()."""
    from jarvis.conversation import ConversationRole, ConversationSession

    observer = DevelopmentProvider(provider, manifest)
    conversation = ConversationSession()
    conversation.start()
    print("Jarvis> " + case.question["question"], flush=True)
    started = time.perf_counter()
    result = await coordinator.respond(
        conversation,
        conversation.accept_turn(ConversationRole.USER, case.question["question"]),
        provider=observer,
        authorize=access.current,
    )
    await coordinator.validate_for_release(result)
    if not coordinator.validate_current(result.packet):
        raise PermissionError("answer invalidated")
    print(result.answer, flush=True)
    await coordinator.record_assistant(
        conversation, result, delivered_text=result.answer
    )
    return case_report(
        case,
        manifest,
        result,
        observer,
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )


def batch_summary(rows, planned_ids):
    completed = [r for r in rows if r["status"] == "completed"]

    def distribution(field):
        values = sorted(r[field] for r in completed if _number(r.get(field)))
        return {
            "sample_count": len(values),
            "p50": values[math.ceil(0.50 * len(values)) - 1] if values else None,
            "p95": values[math.ceil(0.95 * len(values)) - 1] if values else None,
        }

    usage = [r.get("usage") or {} for r in rows]
    unknown_cases = sum(u.get("total_tokens") is None for u in usage)

    return {
        "kind": "project-memory-development-six-v1",
        "planned": len(planned_ids),
        "completed": len(completed),
        "failed": len(rows) - len(completed),
        "unrun": [k for k in planned_ids if k not in {r["case_id"] for r in rows}],
        "answer_quality": "manual_review_required",
        "manually_graded": 0,
        "turn_latency_ms": distribution("elapsed_ms"),
        "provider_latency_ms": distribution("provider_latency_ms"),
        "usage": {
            "total_tokens": sum(u["total_tokens"] for u in usage)
            if usage and not unknown_cases
            else None,
            "known_total_tokens": sum(u.get("known_total_tokens", 0) for u in usage),
            "unknown_cases": unknown_cases,
        },
        "returned_provider_steps": sum(
            r.get("returned_provider_steps", 0) for r in completed
        ),
        "percentile_method": "nearest-rank; successful turns only; excludes setup/Hello; small development sample",
        "limits": "No held-out accuracy, speech latency, billing total or speed improvement established. Returned provider steps may omit failed dispatches or lower-layer attempts.",
    }


def run_development_batch(root, cases, run_case, *, source_commit, model):
    """Exclusive, durable per-case output; setup/Hello/runtime errors stop the batch."""
    root.mkdir(parents=True, exist_ok=False)
    metadata = {
        "source_commit": source_commit,
        "model": model,
        "fixture_hashes": FIXTURE_HASHES,
        "batch_started_at": datetime.now(UTC).isoformat(),
    }
    rows = []
    reporting_errors = []
    stream = None
    ident = None
    try:
        stream = (root / "results.jsonl").open("x", encoding="utf-8")
        for case in cases:
            ident = case.question["id"]
            try:
                row = run_case(case, root / ident)
                if row["case_id"] != ident or row["status"] != "completed":
                    raise ValueError("invalid development case result")
            # Terminal batch boundary: retain a sanitized failure and stop. Never retry.
            except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001
                from jarvis.voice.project_contract_diagnostics import (
                    DevelopmentCaseFailure,
                )

                row = {
                    "case_id": ident,
                    "status": "failed",
                    "error": type(exc).__name__,
                    "stage": "setup_or_turn",
                    "answer_quality": "not_evaluated",
                    "usage": None,
                }
                if isinstance(exc, DevelopmentCaseFailure):
                    row = {"case_id": ident, **exc.report}
            row.update(metadata)
            rows.append(row)
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            try:
                print(
                    "DEVELOPMENT_CASE " + json.dumps(row, ensure_ascii=False),
                    flush=True,
                )
            except (OSError, UnicodeError) as exc:
                reporting_errors.append(
                    {
                        "channel": "console",
                        "error": type(exc).__name__,
                        "case_id": ident,
                    }
                )
                break
            if row["status"] != "completed":
                break
    except (OSError, UnicodeError) as exc:
        reporting_errors.append(
            {"channel": "results_jsonl", "error": type(exc).__name__, "case_id": ident}
        )
    finally:
        if stream is not None:
            try:
                stream.close()
            except OSError as exc:
                reporting_errors.append(
                    {
                        "channel": "results_jsonl",
                        "error": type(exc).__name__,
                        "case_id": ident,
                    }
                )
    summary = {
        **batch_summary(rows, [c.question["id"] for c in cases]),
        **metadata,
        "reporting_errors": reporting_errors,
    }
    if rows and any(e["channel"] == "results_jsonl" for e in reporting_errors):
        # The last row may be absent/partial; retain its answer without rerunning it.
        summary["terminal_case_result"] = rows[-1]
    with (root / "summary.json").open("x+", encoding="utf-8") as output:
        json.dump(summary, output, indent=2)
        output.flush()
        if not any(e["channel"] == "console" for e in reporting_errors):
            try:
                print("DEVELOPMENT_SUMMARY " + json.dumps(summary), flush=True)
            except (OSError, UnicodeError) as exc:
                reporting_errors.append(
                    {"channel": "console", "error": type(exc).__name__, "case_id": None}
                )
                # This exclusively created file is ours; preserve the final output error.
                output.seek(0)
                output.truncate()
                json.dump(summary, output, indent=2)
                output.flush()
    return summary
