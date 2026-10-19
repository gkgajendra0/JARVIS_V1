"""PI-1A offline evaluation contract. Fictional data only; no model or memory writes."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

EXPECTED_CASE_IDS = frozenset(
    {
        "F1", "F2", "V1", "V2", "T1", "T2", "C1", "C2", "H1", "H2",
        "U1", "U2", "E1", "E2", "G1", "R1", "R2", "P1", "P2", "Q1",
    }
)
DECISIONS = frozenset(
    {"personalize", "clarify", "abstain", "refuse", "generic", "require_authority"}
)
ARMS = frozenset({"control", "candidate"})


class PersonalEvalContractError(ValueError):
    """A fictional benchmark contract or annotation is invalid."""


def _json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PersonalEvalContractError("evaluation input must be a JSON object")
    return payload


def load_corpus(
    cases_path: Path, gold_path: Path
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    """Validate independent user-facing cases and *separate* reviewer gold.

    Neither file contains real-owner data. Gold must never be sent as a
    provider prompt, retrieval query hint, or context selection input.
    """
    cases_file, gold_file = _json_object(cases_path), _json_object(gold_path)
    if (
        cases_file.get("suite") != "pi1a.v1"
        or gold_file.get("suite") != "pi1a.v1"
        or cases_file.get("fictional_only") is not True
        or gold_file.get("fictional_only") is not True
    ):
        raise PersonalEvalContractError("unknown or non-fictional corpus")
    cases = cases_file.get("cases")
    gold = gold_file.get("gold")
    if not isinstance(cases, list) or not isinstance(gold, list):
        raise PersonalEvalContractError("cases and gold must be lists")
    if len(cases) != len(EXPECTED_CASE_IDS) or len(gold) != len(cases):
        raise PersonalEvalContractError("expected exactly 20 personal life-domain cases")
    case_ids, gold_ids = set(), set()
    category_counts: Counter[str] = Counter()
    for case in cases:
        if not isinstance(case, dict):
            raise PersonalEvalContractError("case must be an object")
        if set(case) != {
            "case_id", "category", "user_question", "requestor",
            "restart", "provider_unavailable", "events",
        }:
            raise PersonalEvalContractError("case has missing fields or leaked gold")
        ident = case["case_id"]
        if ident in case_ids or not isinstance(ident, str):
            raise PersonalEvalContractError("duplicate or invalid case id")
        case_ids.add(ident)
        category_counts[case["category"]] += 1
        if (
            not isinstance(case["user_question"], str)
            or not case["user_question"].strip()
            or case["requestor"] not in {"owner", "guest"}
            or type(case["restart"]) is not bool
            or type(case["provider_unavailable"]) is not bool
        ):
            raise PersonalEvalContractError("invalid question or execution condition")
        events = case["events"]
        if not isinstance(events, list) or not events:
            raise PersonalEvalContractError("each case requires evidence-bearing events")
        event_ids = set()
        for event in events:
            if not isinstance(event, dict) or set(event) != {
                "event_id", "session_id", "speaker", "text"
            }:
                raise PersonalEvalContractError("event has invalid schema")
            if (
                event["event_id"] in event_ids
                or not isinstance(event["event_id"], str)
                or not isinstance(event["session_id"], str)
                or event["speaker"] not in {"owner", "guest", "untrusted", "runtime"}
                or not isinstance(event["text"], str)
                or not event["text"].strip()
            ):
                raise PersonalEvalContractError("invalid or duplicate evidence event")
            event_ids.add(event["event_id"])
    if case_ids != EXPECTED_CASE_IDS or len(category_counts) < 10:
        raise PersonalEvalContractError("missing cases or insufficient life-domain variety")
    case_by_id = {case["case_id"]: case for case in cases}
    for expectation in gold:
        if not isinstance(expectation, dict) or set(expectation) != {
            "case_id", "category", "expected_decision",
            "must_use_event_ids", "must_not_use_event_ids",
        }:
            raise PersonalEvalContractError("gold schema invalid")
        ident = expectation["case_id"]
        if ident not in case_by_id or ident in gold_ids:
            raise PersonalEvalContractError("unknown or duplicate gold entry")
        gold_ids.add(ident)
        case = case_by_id[ident]
        ids = {event["event_id"] for event in case["events"]}
        positive = expectation["must_use_event_ids"]
        negative = expectation["must_not_use_event_ids"]
        if (
            expectation["category"] != case["category"]
            or expectation["expected_decision"] not in DECISIONS
            or not isinstance(positive, list)
            or not isinstance(negative, list)
            or not all(isinstance(x, str) for x in positive + negative)
            or not set(positive + negative).issubset(ids)
            or set(positive) & set(negative)
            or len(set(positive)) != len(positive)
            or len(set(negative)) != len(negative)
        ):
            raise PersonalEvalContractError("invalid gold evidence or behavior")
    return tuple(cases), tuple(gold)


def corpus_manifest(
    cases_path: Path, gold_path: Path
) -> dict[str, Any]:
    cases, gold = load_corpus(cases_path, gold_path)
    return {
        "suite": "pi1a.v1",
        "cases": len(cases),
        "categories": dict(sorted(Counter(x["category"] for x in cases).items())),
        "cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "gold_sha256": hashlib.sha256(gold_path.read_bytes()).hexdigest(),
        "model_answer_evaluation": "NOT_RUN",
        "live_provider_context_injection": "NOT_RUN",
        "automatic_durable_memory_capture": "DISABLED",
    }


def validate_paired_annotations(
    cases_path: Path, gold_path: Path, annotations_path: Path
) -> dict[str, Any]:
    """Validate independent reviews, but never auto-grade answer semantics.

    This reports structural coverage, not a fabricated personalization pass.
    Reviewers must inspect actual response text and supporting evidence before
    recording 'appropriate' or 'inappropriate'.
    """
    cases, _ = load_corpus(cases_path, gold_path)
    payload = _json_object(annotations_path)
    responses = payload.get("responses")
    if payload.get("suite") != "pi1a.v1" or not isinstance(responses, list):
        raise PersonalEvalContractError("invalid paired evaluation payload")
    allowed = {c["case_id"] for c in cases}
    observed: set[tuple[str, str]] = set()
    reviewed = 0
    for entry in responses:
        if not isinstance(entry, dict) or set(entry) != {
            "case_id", "arm", "answer", "cited_event_ids", "review",
        }:
            raise PersonalEvalContractError("invalid response annotation schema")
        case_id, arm = entry["case_id"], entry["arm"]
        if case_id not in allowed or arm not in ARMS or (case_id, arm) in observed:
            raise PersonalEvalContractError("invalid or duplicate case/arm")
        observed.add((case_id, arm))
        case = next(c for c in cases if c["case_id"] == case_id)
        ids = {e["event_id"] for e in case["events"]}
        cited = entry["cited_event_ids"]
        if (
            not isinstance(entry["answer"], str)
            or not entry["answer"].strip()
            or not isinstance(cited, list)
            or not all(isinstance(x, str) for x in cited)
            or not set(cited).issubset(ids)
            or len(cited) != len(set(cited))
            or entry["review"] not in {"unreviewed", "appropriate", "inappropriate"}
        ):
            raise PersonalEvalContractError("invalid answer, source or reviewer label")
        if entry["review"] != "unreviewed":
            reviewed += 1
    if observed != {(c["case_id"], arm) for c in cases for arm in ARMS}:
        raise PersonalEvalContractError("a paired response is missing")
    return {
        "suite": "pi1a.v1",
        "pairs": len(cases),
        "annotations": len(responses),
        "manually_reviewed": reviewed,
        "semantic_accuracy": (
            "NOT_MEASURED" if reviewed != len(responses) else "MANUAL_REVIEW_REQUIRED"
        ),
        "security_approval": "NOT_GRANTED",
    }
