"""Fictional comparison contracts; default CLI only validates public fixtures.

This first transport uses source-linked extractive context, not vendor-derived
profile prose. It is neither a service benchmark nor a production memory path.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import math
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

SCHEMA = "jarvis.personal_intelligence.eval.v1"
DEFAULT_CORPUS = (
    Path(__file__).resolve().parents[2] / "benchmarks/personal_intelligence_v1.json"
)
CASE_FIELDS = {"id", "domain", "language", "events", "query", "evaluation_only"}
EVENT_REQUIRED = {
    "id",
    "at",
    "session_id",
    "actor",
    "text",
    "cloud_release_allowed",
    "retention",
}
EVENT_FIELDS = EVENT_REQUIRED | {"kind", "target_source_ids"}
QUERY_FIELDS = {"at", "session_id", "requester", "utterance", "actions_authorized"}
RETENTION_BY_ACTOR = {
    "owner": "authorized_fictional_source",
    "tool": "authorized_fictional_source",
    "assistant": "unverified_assistant_claim",
    "external": "untrusted_ephemeral",
}


class MemoryTrialAdapter(Protocol):
    """Trusted lab adapters supply candidates, never canonical authority."""

    async def reset(self, identity: str) -> None: ...
    async def ingest(self, event: dict) -> None: ...
    async def wait_ready(self, timeout_s: float) -> bool: ...
    async def invalidate(self, source_ids: tuple[str, ...]) -> None: ...
    async def select(self, query: dict, token_budget: int) -> dict: ...
    async def close(self) -> None: ...


class _Unavailable(RuntimeError):
    pass


class TrialInputError(ValueError):
    """Invalid JSON fixture or adapter payload at a comparison boundary."""


def _fields(value: object, required: set[str], allowed: set[str]) -> dict:
    if not isinstance(value, dict) or not required <= value.keys() <= allowed:
        raise ValueError("missing or unsupported fixture fields")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected nonempty fixture text")
    return value


def _timestamp(value: object) -> datetime:
    timestamp = datetime.fromisoformat(_text(value))
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("fixture timestamp must include a timezone")
    return timestamp


def _validate_case(case: object) -> dict:
    case = _fields(case, CASE_FIELDS, CASE_FIELDS)
    _text(case["id"])
    _text(case["domain"])
    if _text(case["language"]) not in {"en", "hi", "hi-Latn"}:
        raise ValueError("unsupported fixture language")
    query = _fields(case["query"], QUERY_FIELDS, QUERY_FIELDS)
    query_at = _timestamp(query["at"])
    _text(query["session_id"])
    _text(query["utterance"])
    if (
        _text(query["requester"]) not in {"owner", "guest"}
        or query["actions_authorized"] is not False
    ):
        raise ValueError("unsupported requester or execution authority")
    if not isinstance(case["events"], list):
        raise TrialInputError("events must be a list")
    seen: set[str] = set()
    previous = None
    for event in case["events"]:
        event = _fields(event, EVENT_REQUIRED, EVENT_FIELDS)
        event_id = _text(event["id"])
        if event_id in seen:
            raise ValueError("duplicate source ID")
        at = _timestamp(event["at"])
        if at >= query_at or (previous is not None and at < previous):
            raise ValueError("events must precede query in chronological order")
        previous = at
        _text(event["session_id"])
        _text(event["text"])
        if type(event["cloud_release_allowed"]) is not bool:
            raise ValueError("cloud permission must be an explicit boolean")
        actor = event["actor"]
        if (
            not isinstance(actor, str)
            or actor not in RETENTION_BY_ACTOR
            or RETENTION_BY_ACTOR.get(actor) != event["retention"]
        ):
            raise ValueError("invalid fixture actor or retention class")
        kind = event.get("kind")
        if kind is not None and _text(kind) not in {
            "verified_forget",
            "permitted_observation",
            "canonical_work_status",
        }:
            raise ValueError("unsupported fixture event kind")
        if kind is not None and actor != "tool":
            raise ValueError("verified operation requires tool provenance")
        if kind == "verified_forget":
            targets = event.get("target_source_ids")
            if not isinstance(targets, list) or not targets:
                raise ValueError("forget operation needs prior source IDs")
            if any(
                not isinstance(target, str) or target not in seen for target in targets
            ):
                raise ValueError("forget targets must be earlier sources in this case")
            if len(targets) != len(set(targets)):
                raise ValueError("duplicate forget target")
        elif "target_source_ids" in event:
            raise ValueError("source invalidation requires verified forget")
        seen.add(event_id)
    rubric = case["evaluation_only"]
    if not isinstance(rubric, dict):
        raise TrialInputError("evaluation rubric must be an object")
    for key in (
        "requirements",
        "prohibitions",
        "required_source_ids",
        "forbidden_source_ids",
    ):
        values = rubric.get(key)
        if not isinstance(values, list) or any(
            not isinstance(value, str) for value in values
        ):
            raise ValueError("malformed evaluation rubric")
    required, forbidden = (
        set(rubric["required_source_ids"]),
        set(rubric["forbidden_source_ids"]),
    )
    if not required | forbidden <= seen or required & forbidden:
        raise ValueError("invalid evaluator source references")
    return case


def load_cases(path: Path) -> list[dict]:
    """Validate fixture shape; a synthetic flag is an assertion, not a classifier."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA:
        raise ValueError("unsupported corpus schema")
    if document.get("synthetic_only") is not True:
        raise ValueError("only declared fictional corpora are supported")
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("corpus needs cases")
    case_ids: set[str] = set()
    event_ids: set[str] = set()
    for case in cases:
        _validate_case(case)
        if case["id"] in case_ids:
            raise ValueError("duplicate case ID")
        case_ids.add(case["id"])
        for event in case["events"]:
            if event["id"] in event_ids:
                raise ValueError("source ID reused across cases")
            event_ids.add(event["id"])
    return copy.deepcopy(cases)


def candidate_input(case: dict, *, destination: str) -> dict:
    """Project only permitted inputs; no rubric or classification reaches adapters."""
    _validate_case(case)
    if destination not in {"cloud", "local"}:
        raise ValueError("destination must be cloud or local")
    events = []
    if case["query"]["requester"] == "owner":
        events = [
            {key: copy.deepcopy(event[key]) for key in EVENT_FIELDS if key in event}
            for event in case["events"]
            if destination == "local" or event["cloud_release_allowed"]
        ]
    return {
        "id": case["id"],
        "language": case["language"],
        "events": events,
        "query": {key: copy.deepcopy(case["query"][key]) for key in QUERY_FIELDS},
    }


def _source_context(selection: dict, active: dict[str, dict]) -> list[dict]:
    """Resolve IDs to original quotes; derived prose is not this phase's input."""
    if not isinstance(selection, dict):
        raise TrialInputError("adapter selection must be an object")
    if selection.get("status") == "unavailable":
        raise _Unavailable
    if selection.get("status") not in {"ready", "abstain"}:
        raise ValueError("unsupported adapter selection status")
    evidence = selection.get("evidence")
    if not isinstance(evidence, list):
        raise TrialInputError("adapter evidence must be a list")
    if selection["status"] == "abstain" and evidence:
        raise ValueError("abstention cannot carry evidence")
    context = []
    released: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict):
            raise TrialInputError("malformed evidence item")
        source_ids = item.get("source_ids")
        if not isinstance(source_ids, list) or not source_ids:
            raise ValueError("evidence needs original source lineage")
        for source_id in source_ids:
            if not isinstance(source_id, str) or source_id not in active:
                raise ValueError("unadmitted or invalidated source")
            if source_id in released:
                continue
            source = active[source_id]
            context.append(
                {
                    "source_ids": [source_id],
                    "text": source["text"],
                    "actor": source["actor"],
                    "at": source["at"],
                }
            )
            released.add(source_id)
    return context


async def run_case(
    case: dict,
    adapter: MemoryTrialAdapter,
    answerer: Callable[[dict], Awaitable[dict]],
    *,
    destination: str,
    token_budget: int,
    timeout_s: float,
) -> dict:
    """Run one bounded fictional trial; return evidence, never a quality grade.

    token_budget is conservatively enforced as UTF-8 bytes in this first slice.
    Exact tokenizer accounting and model cost belong to the later live runner.
    Adapter and answerer implementations are trusted injected lab dependencies.
    """
    if type(token_budget) is not int or token_budget <= 0:
        raise ValueError("context budget must be a positive integer")
    if (
        not isinstance(timeout_s, (int, float))
        or not math.isfinite(timeout_s)
        or timeout_s <= 0
    ):
        raise ValueError("timeout must be positive and finite")
    started = time.monotonic()
    run_id = uuid.uuid4().hex
    trace = {
        "case_id": case.get("id"),
        "run_id": run_id,
        "status": "failed",
        "operations": [],
    }
    stage = "input"

    async def bounded(operation):
        return await asyncio.wait_for(operation, timeout=timeout_s)

    async def ready():
        if await bounded(adapter.wait_ready(timeout_s)) is not True:
            raise _Unavailable

    try:
        projected = candidate_input(case, destination=destination)
        stage = "reset"
        await bounded(adapter.reset(f"pi-{run_id}"))
        await ready()
        active = {}
        permitted_ids = {event["id"] for event in projected["events"]}
        # Local lifecycle controls still revoke prior releases when their text is private.
        for event in case["events"]:
            if event.get("kind") == "verified_forget":
                stage = "invalidate"
                targets = tuple(
                    target for target in event["target_source_ids"] if target in active
                )
                if targets:
                    await bounded(adapter.invalidate(targets))
                    for target in targets:
                        active.pop(target)
                    trace["operations"].append(
                        {"kind": "invalidate", "source_ids": list(targets)}
                    )
                    await ready()
            elif event["id"] in permitted_ids:
                stage = "ingest"
                await bounded(adapter.ingest(copy.deepcopy(event)))
                active[event["id"]] = copy.deepcopy(event)
                trace["operations"].append(
                    {"kind": "ingest", "source_ids": [event["id"]]}
                )
                await ready()
        stage = "select"
        selection = await bounded(
            adapter.select(copy.deepcopy(projected["query"]), token_budget)
        )
        stage = "validate_release"
        context = _source_context(selection, active)
        context_bytes = len(json.dumps(context, ensure_ascii=False).encode("utf-8"))
        if context_bytes > token_budget:
            raise ValueError("selected context exceeds conservative byte budget")
        trace["context_utf8_bytes"] = context_bytes
        trace["budget_unit"] = "utf8_bytes_upper_bound"
        trace["context"] = copy.deepcopy(context)
        stage = "answer"
        answer = await bounded(
            answerer({"query": projected["query"], "context": context, "tools": []})
        )
        if not isinstance(answer, dict) or not isinstance(answer.get("text"), str):
            raise TrialInputError("answerer must return a text-bearing object")
        trace["answer"] = answer
        trace["status"] = "answered"
    except (TimeoutError, _Unavailable) as error:
        trace.update(
            status="unavailable", failure_stage=stage, error_type=type(error).__name__
        )
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 -- sanitize arbitrary adapter failures.
        trace.update(
            status="failed", failure_stage=stage, error_type=type(error).__name__
        )
    finally:
        try:
            await asyncio.shield(asyncio.wait_for(adapter.close(), timeout=timeout_s))
            trace["cleanup"] = "completed"
        except Exception as error:  # noqa: BLE001 -- cleanup is a separate failure gate.
            trace.pop("answer", None)
            trace.update(
                status="cleanup_failed",
                cleanup="failed",
                cleanup_error_type=type(error).__name__,
            )
        trace["elapsed_ms"] = round((time.monotonic() - started) * 1000, 3)
    return trace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    args = parser.parse_args(argv)
    try:
        cases = load_cases(args.corpus)
    except (ValueError, OSError) as error:
        print(f"Invalid comparison corpus: {type(error).__name__}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": "validated_only",
                "cases": len(cases),
                "events": sum(len(case["events"]) for case in cases),
                "model_calls": 0,
                "engine_trials": 0,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
