"""Research-only 60-document fictional corpus for a fair first retrieval comparison.

No owner data, database, SDK, network or file writes. This deliberately
does NOT modify the original five-document acceptance archive or its hash.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from typing import Any

from jarvis.memory.research_decision_gate import (
    Assertion,
    MemoryDecisionIndex,
    MemoryQuestion,
)

PROJECT_COUNT = 20
DOCUMENT_COUNT = PROJECT_COUNT * 3
TOP_K = 8
MAX_ARCHIVE_BYTES = 196_608
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_ID = re.compile(r"^synthetic-project-[0-9]{4}-(?:schedule-v[12]|venue-v1)$")
_TOKEN = re.compile(r"[a-z0-9]+")
TAGS = ["jarvis-dev-only", "synthetic"]


class ComparisonFailure(ValueError):
    """Fixed, sanitized error codes, never request or memory text."""


@dataclass(frozen=True, slots=True)
class ScaleFact:
    assertion: Assertion
    text: str
    source_turn_id: str


@dataclass(frozen=True, slots=True)
class ScaleCase:
    case_id: str
    query: str
    subject: str
    predicate: str
    intent: str
    required_ids: tuple[str, ...]
    expected_answer_code: str | None


def _fact(i: int, kind: str, version: int) -> ScaleFact:
    subject = f"synthetic-project-{i:04d}"
    assertion_id = f"{subject}-{kind}-v{version}"
    turn_id = f"synthetic-project-{i:04d}-{kind}-turn-{version}"
    first = DAYS[i % len(DAYS)]
    updated = DAYS[(i + 3) % len(DAYS)]
    if kind == "schedule" and version == 1:
        text = (
            f"The fictional Meridian project {i:04d} weekly review was "
            f"originally arranged for {first.title()}."
        )
        value = first
        revision = "original_statement"
        predecessor = None
    elif kind == "schedule" and version == 2:
        text = (
            f"Correction: fictional Meridian project {i:04d} weekly review "
            f"takes place on {updated.title()}, not {first.title()}."
        )
        value = updated
        revision = "correction"
        predecessor = f"{subject}-schedule-v1"
    elif kind == "venue" and version == 1:
        text = (
            f"The fictional Meridian project {i:04d} weekly review "
            f"location is Room {i:04d}."
        )
        value = f"room_{i:04d}"
        revision = "unrelated_current_fact"
        predecessor = None
    else:
        raise ComparisonFailure("invalid_fictional_fact_generator")
    assertion = Assertion(
        assertion_id=assertion_id,
        subject=subject,
        predicate=kind,
        value=value,
        source_ref=f"conversation:synthetic:{turn_id}",
        mentioned_at=f"2026-01-0{version}T10:00:00Z",
        version=version,
        revision_kind=revision,
        supersedes_id=predecessor,
    )
    return ScaleFact(assertion, text, turn_id)


FACTS = tuple(
    fact
    for index in range(PROJECT_COUNT)
    for fact in (
        _fact(index, "schedule", 1),
        _fact(index, "schedule", 2),
        _fact(index, "venue", 1),
    )
)
BY_ID = {item.assertion.assertion_id: item for item in FACTS}
if len(FACTS) != DOCUMENT_COUNT or len(BY_ID) != DOCUMENT_COUNT:
    raise RuntimeError("invalid_fixed_fictional_corpus")


def cases() -> tuple[ScaleCase, ...]:
    rows: list[ScaleCase] = []
    for i in (2, 7, 13, 19):
        subject = f"synthetic-project-{i:04d}"
        older = f"{subject}-schedule-v1"
        newer = f"{subject}-schedule-v2"
        venue = f"{subject}-venue-v1"
        initial = BY_ID[older].assertion.value
        corrected = BY_ID[newer].assertion.value
        rows.extend(
            (
                ScaleCase(
                    f"project_{i:04d}_current",
                    f"Which weekday is the weekly review for fictional Meridian project {i:04d} now?",
                    subject,
                    "schedule",
                    "current",
                    (newer,),
                    corrected,
                ),
                ScaleCase(
                    f"project_{i:04d}_original",
                    f"On which weekday was fictional Meridian project {i:04d} weekly review originally arranged?",
                    subject,
                    "schedule",
                    "original",
                    (older,),
                    initial,
                ),
                ScaleCase(
                    f"project_{i:04d}_correction",
                    f"How was the weekday for fictional Meridian project {i:04d} weekly review corrected?",
                    subject,
                    "schedule",
                    "history",
                    (older, newer),
                    f"{initial}_corrected_to_{corrected}",
                ),
                ScaleCase(
                    f"project_{i:04d}_venue",
                    f"Which room hosts the fictional Meridian project {i:04d} weekly review?",
                    subject,
                    "venue",
                    "current",
                    (venue,),
                    f"room_{i:04d}",
                ),
            )
        )
    rows.extend(
        (
            ScaleCase(
                "unknown_start_time",
                "At what exact time does fictional Meridian project 0002 weekly review begin?",
                "synthetic-project-0002",
                "start_time",
                "current",
                (),
                None,
            ),
            ScaleCase(
                "unknown_budget",
                "What budget was approved for fictional Meridian project 0007 weekly review?",
                "synthetic-project-0007",
                "budget",
                "current",
                (),
                None,
            ),
        )
    )
    if len(rows) != 18 or len({row.case_id for row in rows}) != len(rows):
        raise ComparisonFailure("invalid_case_fixture")
    return tuple(rows)


CASES = cases()


def metadata(fact: ScaleFact) -> dict[str, str]:
    claim = fact.assertion
    result = {
        "source_turn_id": fact.source_turn_id,
        "canonical_source_ref": claim.source_ref,
        "assertion_id": claim.assertion_id,
        "assertion_version": str(claim.version),
        "predicate": claim.predicate,
        "subject": claim.subject,
        "value": claim.value,
        "revision_kind": claim.revision_kind,
        "source_class": "synthetic_owner_direct",
        "admission_policy": "shadow_only_no_write",
    }
    if claim.supersedes_id is not None:
        result["supersedes_id"] = claim.supersedes_id
    return result


def _json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_archive() -> bytes:
    """Reproducible Hindsight external fact ZIP, single document per fact."""
    payloads = {
        "manifest.json": _json(
            {"schema_version": 1, "source_bank_id": "jarvis-dev-only-scale-external"}
        )
    }
    for fact in FACTS:
        claim = fact.assertion
        document_id = f"jarvis-dev-only-{claim.assertion_id}"
        payloads[f"documents/{document_id}.json"] = _json(
            {
                "id": document_id,
                "original_text": fact.text,
                "chunks": [{"chunk_index": 0, "chunk_text": fact.text}],
                "tags": TAGS,
                "facts": [
                    {
                        "text": fact.text,
                        "fact_type": "world",
                        "chunk_index": 0,
                        "mentioned_at": claim.mentioned_at,
                        "occurred_start": claim.mentioned_at,
                        "entities": [f"Meridian Project {claim.subject[-4:]}"],
                        "metadata": metadata(fact),
                        "tags": TAGS,
                    }
                ],
            }
        )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, payload in sorted(payloads.items()):
            entry = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            entry.compress_type = zipfile.ZIP_STORED
            entry.external_attr = 0o600 << 16
            archive.writestr(entry, payload)
    result = output.getvalue()
    if len(result) > MAX_ARCHIVE_BYTES:
        raise ComparisonFailure("synthetic_archive_too_large")
    return result


def validate_archive(archive: bytes) -> dict[str, object]:
    """Require byte-for-byte agreement with the sole reviewed fixture builder."""
    if not isinstance(archive, bytes) or archive != build_archive():
        raise ComparisonFailure("unrecognized_archive")
    with zipfile.ZipFile(io.BytesIO(archive)) as zip_file:
        expected = {
            "manifest.json",
            *(f"documents/jarvis-dev-only-{id_}.json" for id_ in BY_ID),
        }
        if set(zip_file.namelist()) != expected or len(zip_file.namelist()) != len(
            expected
        ):
            raise ComparisonFailure("modified_archive_entries")
    return {
        "sha256": hashlib.sha256(archive).hexdigest(),
        "documents": DOCUMENT_COUNT,
        "synthetic_only": True,
    }


def validate_recall(response: Any) -> tuple[str, ...]:
    """Validate every returned Hindsight fact against the exact local corpus."""
    if not isinstance(response, dict) or not isinstance(response.get("results"), list):
        raise ComparisonFailure("invalid_recall_schema")
    values = response["results"]
    if len(values) > DOCUMENT_COUNT:
        raise ComparisonFailure("unbounded_recall_results")
    found: list[str] = []
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("metadata"), dict):
            raise ComparisonFailure("missing_recall_provenance")
        assertion_id = item["metadata"].get("assertion_id")
        if not isinstance(assertion_id, str) or assertion_id not in BY_ID:
            raise ComparisonFailure("unrecognized_recalled_assertion")
        fact = BY_ID[assertion_id]
        if (
            item["metadata"] != metadata(fact)
            or item.get("type") != "world"
            or item.get("document_id") != f"jarvis-dev-only-{assertion_id}"
            or item.get("text") != fact.text
        ):
            raise ComparisonFailure("recalled_fact_identity_mismatch")
        if assertion_id in found:
            raise ComparisonFailure("duplicate_recalled_assertion")
        found.append(assertion_id)
    return tuple(found)


def tokenize(text: str) -> Counter[str]:
    return Counter(_TOKEN.findall(text.casefold()))


def bm25(query: str) -> tuple[str, ...]:
    """Pure local lexical baseline, scoring ONLY the same factual texts."""
    query_terms = tuple(tokenize(query))
    docs = [(fact.assertion.assertion_id, tokenize(fact.text)) for fact in FACTS]
    avg_length = sum(sum(tokens.values()) for _, tokens in docs) / len(docs)
    n_docs = len(docs)
    scores: list[tuple[float, str]] = []
    for assertion_id, tokens in docs:
        length = sum(tokens.values())
        value = 0.0
        for term in query_terms:
            matches = tokens.get(term, 0)
            if not matches:
                continue
            frequency = sum(1 for _, item in docs if term in item)
            weight = math.log1p((n_docs - frequency + 0.5) / (frequency + 0.5))
            value += (
                weight
                * matches
                * 2.2
                / (matches + 1.2 * (0.25 + 0.75 * length / avg_length))
            )
        if value > 0.0:
            scores.append((value, assertion_id))
    scores.sort(key=lambda pair: (-pair[0], pair[1]))
    return tuple(ident for _, ident in scores)


def fuse(hindsight: tuple[str, ...], lexical: tuple[str, ...]) -> tuple[str, ...]:
    """RRF K=60; no provider is allowed to introduce unknown facts."""
    scores: dict[str, float] = {}
    for ranking in (hindsight, lexical):
        if len(ranking) != len(set(ranking)) or any(
            item not in BY_ID for item in ranking
        ):
            raise ComparisonFailure("invalid_ranked_candidates")
        for pos, ident in enumerate(ranking, start=1):
            scores[ident] = scores.get(ident, 0.0) + 1.0 / (60 + pos)
    return tuple(sorted(scores, key=lambda ident: (-scores[ident], ident)))


def score_rankings(rankings: dict[str, dict[str, tuple[str, ...]]]) -> dict[str, Any]:
    """One identical top-k evidence/decision rubric for every compared engine."""
    if set(rankings) != {"hindsight", "lexical", "hybrid"}:
        raise ComparisonFailure("invalid_comparison_engines")
    expected_cases = {case.case_id for case in CASES}
    for cases_by_id in rankings.values():
        if set(cases_by_id) != expected_cases:
            raise ComparisonFailure("incomplete_comparison_cases")
        for ordered in cases_by_id.values():
            if (
                not isinstance(ordered, tuple)
                or len(ordered) != len(set(ordered))
                or any(ident not in BY_ID for ident in ordered)
            ):
                raise ComparisonFailure("invalid_ranked_candidates")
    results: dict[str, Any] = {}
    facts_by_id = {id_: fact.assertion for id_, fact in BY_ID.items()}
    for engine, ranked_cases in rankings.items():
        retrieved = 0
        decision_correct = 0
        unknown_abstentions = 0
        for case in CASES:
            selected = ranked_cases[case.case_id][:TOP_K]
            if case.required_ids and all(
                required in selected for required in case.required_ids
            ):
                retrieved += 1
            # Don't silently invent missing predecessors. Require the complete
            # canonical group before allowing any structured answer to count.
            group = tuple(
                fact
                for fact in facts_by_id.values()
                if fact.subject == case.subject and fact.predicate == case.predicate
            )
            complete = all(fact.assertion_id in selected for fact in group)
            relevant = tuple(facts_by_id[ident] for ident in selected)
            decision = MemoryDecisionIndex(relevant).decide(
                MemoryQuestion(case.subject, case.predicate, case.intent)
            )
            correct = (
                case.expected_answer_code is None and decision.status == "abstain"
            ) or (
                case.expected_answer_code is not None
                and complete
                and decision.status == "answer"
                and decision.answer_code == case.expected_answer_code
            )
            decision_correct += int(correct)
            unknown_abstentions += int(case.expected_answer_code is None and correct)
        results[engine] = {
            "retrieval_hits": retrieved,
            "retrieval_required": 16,
            "structured_decisions_correct": decision_correct,
            "structured_decisions_required": len(CASES),
            "unknown_abstentions": unknown_abstentions,
            "unknown_required": 2,
        }
    return {
        "kind": "STEP7_SYNTHETIC_ENGINE_COMPARISON",
        "documents": DOCUMENT_COUNT,
        "queries": len(CASES),
        "rank_limit": TOP_K,
        "engines": results,
        "rule_based_not_llm": True,
        "production_promotion_allowed": False,
    }
