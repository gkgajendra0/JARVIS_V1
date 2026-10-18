"""Synthetic semantic-pressure evaluation: BM25 baseline against 240 memories.

NO network, Docker, production SQLCipher, API provider, disk writes or model.
For each target the question mentions a human-curated concept alias absent
from the memory text; this measures lexical brittleness, NOT yet the success
of any real semantic engine. All gold scopes are pre-labeled, not extracted.
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
from typing import Any, Literal

from jarvis.memory.research_decision_gate import (
    Assertion,
    MemoryDecisionIndex,
    MemoryQuestion,
)

TARGET_COUNT = 16
DISTRACTOR_COUNT = 208
DOCUMENT_COUNT = TARGET_COUNT * 2 + DISTRACTOR_COUNT
TOP_K_CHOICES = (4, 8, 16)
FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)
MAX_ARCHIVE_BYTES = 1_048_576
TOKEN = re.compile(r"[a-z0-9]+")
TAGS = ["jarvis-dev-only", "synthetic"]


class PressureFailure(ValueError):
    """No raw user data in errors; invalid fixtures/choices fail closed."""


@dataclass(frozen=True, slots=True)
class Concept:
    """Fictional catalog description and independent human semantic paraphrase."""

    descriptor: str
    alias: str


# No named entities, names, preferences, or records belonging to the owner.
# The alias does not occur in the description or corresponding source facts.
CONCEPTS: tuple[Concept, ...] = (
    Concept("optical device for observing distant celestial objects", "telescope"),
    Concept("striped big cat native to forests", "tiger"),
    Concept("eight armed marine invertebrate", "octopus"),
    Concept("our solar system's fourth planet", "mars"),
    Concept("flightless black and white bird of polar coasts", "penguin"),
    Concept("large gray land mammal with a trunk", "elephant"),
    Concept("frozen white flakes falling from winter clouds", "snow"),
    Concept("insect famous for colorful wing patterns", "butterfly"),
    Concept("pedal powered two wheeled vehicle", "bicycle"),
    Concept("sweet golden substance made by bees", "honey"),
    Concept("glowing curtains of light across polar skies", "aurora"),
    Concept("glass vessel measuring time with flowing sand", "hourglass"),
    Concept("household appliance that keeps groceries cold", "refrigerator"),
    Concept("tool for measuring movements of the earth", "seismograph"),
    Concept("night flying mammal using echoes for navigation", "bat"),
    Concept("curved yellow tropical fruit with soft flesh", "banana"),
)


@dataclass(frozen=True, slots=True)
class MemoryFact:
    assertion: Assertion
    text: str
    turn_id: str


@dataclass(frozen=True, slots=True)
class PressureCase:
    case_id: str
    category: Literal[
        "semantic_current",
        "semantic_original",
        "semantic_history",
        "exact_descriptor_control",
        "unknown_detail",
        "unresolved_subject",
    ]
    query: str
    subject: str | None
    predicate: str | None
    intent: Literal["current", "original", "history"] | None
    expected: str | None
    required_ids: tuple[str, ...]


def _make_fact(i: int, version: int) -> MemoryFact:
    if not 0 <= i < TARGET_COUNT or version not in (1, 2):
        raise PressureFailure("invalid_target")
    subject = f"synthetic-exhibit-{i:03d}"
    ident = f"{subject}-site-v{version}"
    turn = f"{subject}-site-turn-{version}"
    descriptor = CONCEPTS[i].descriptor
    if version == 1:
        text = (
            f"In the fictional catalog, the {descriptor} showcase "
            f"was stored at Depot {i:03d} Alpha."
        )
        value = f"depot_{i:03d}_alpha"
        revision = "original_statement"
        predecessor = None
    else:
        text = (
            f"Catalog correction: the {descriptor} showcase moved to "
            f"Depot {i:03d} Beta from Depot {i:03d} Alpha."
        )
        value = f"depot_{i:03d}_beta"
        revision = "correction"
        predecessor = f"{subject}-site-v1"
    fact = Assertion(
        assertion_id=ident,
        subject=subject,
        predicate="site",
        value=value,
        source_ref=f"conversation:synthetic:{turn}",
        mentioned_at=f"2026-01-0{version}T10:00:00Z",
        version=version,
        revision_kind=revision,
        supersedes_id=predecessor,
    )
    return MemoryFact(fact, text, turn)


def _make_distractor(i: int) -> MemoryFact:
    if not 0 <= i < DISTRACTOR_COUNT:
        raise PressureFailure("invalid_distractor")
    subject = f"synthetic-decoy-{i:03d}"
    turn = f"{subject}-site-turn-1"
    fact = Assertion(
        assertion_id=f"{subject}-site-v1",
        subject=subject,
        predicate="site",
        value=f"depot_decoy_{i:03d}",
        source_ref=f"conversation:synthetic:{turn}",
        mentioned_at="2026-01-01T10:00:00Z",
        version=1,
        revision_kind="unrelated_current_fact",
    )
    text = (
        f"Fictional catalog inventory bundle {i:03d} was deposited at "
        f"Depot Decoy {i:03d} for long-term storage."
    )
    return MemoryFact(fact, text, turn)


FACTS = tuple(
    fact
    for index in range(TARGET_COUNT)
    for fact in (_make_fact(index, 1), _make_fact(index, 2))
) + tuple(_make_distractor(index) for index in range(DISTRACTOR_COUNT))
BY_ID = {fact.assertion.assertion_id: fact for fact in FACTS}
if (
    len(CONCEPTS) != TARGET_COUNT
    or len(FACTS) != DOCUMENT_COUNT
    or len(BY_ID) != DOCUMENT_COUNT
):
    raise RuntimeError("invalid_pressure_corpus")

for index, concept in enumerate(CONCEPTS):
    alias_tokens = set(TOKEN.findall(concept.alias.casefold()))
    source_tokens = set(
        TOKEN.findall(_make_fact(index, 1).text.casefold())
        + TOKEN.findall(_make_fact(index, 2).text.casefold())
    )
    if alias_tokens & source_tokens:
        raise RuntimeError("semantic_alias_leaks_into_memory_text")


def cases() -> tuple[PressureCase, ...]:
    result: list[PressureCase] = []
    for i, concept in enumerate(CONCEPTS):
        subject = f"synthetic-exhibit-{i:03d}"
        original = f"{subject}-site-v1"
        updated = f"{subject}-site-v2"
        before = BY_ID[original].assertion.value
        after = BY_ID[updated].assertion.value
        lineage = (original, updated)
        result.extend(
            (
                PressureCase(
                    f"semantic_current_{i:03d}",
                    "semantic_current",
                    f"Where is the {concept.alias} display located now?",
                    subject,
                    "site",
                    "current",
                    after,
                    lineage,
                ),
                PressureCase(
                    f"semantic_original_{i:03d}",
                    "semantic_original",
                    f"Before the relocation, where was the {concept.alias} display kept?",
                    subject,
                    "site",
                    "original",
                    before,
                    lineage,
                ),
                PressureCase(
                    f"semantic_history_{i:03d}",
                    "semantic_history",
                    f"Describe the before and after places for the {concept.alias} installation.",
                    subject,
                    "site",
                    "history",
                    f"{before}_corrected_to_{after}",
                    lineage,
                ),
                PressureCase(
                    f"direct_control_{i:03d}",
                    "exact_descriptor_control",
                    f"What is the current depot for the {concept.descriptor} showcase?",
                    subject,
                    "site",
                    "current",
                    after,
                    lineage,
                ),
            )
        )
    result.extend(
        (
            PressureCase(
                "unknown_open_time",
                "unknown_detail",
                "What exact minute does the telescope display open?",
                "synthetic-exhibit-000",
                "opening_time",
                "current",
                None,
                (),
            ),
            PressureCase(
                "unknown_owner",
                "unknown_detail",
                "Who owns the tiger exhibit?",
                "synthetic-exhibit-001",
                "owner",
                "current",
                None,
                (),
            ),
            PressureCase(
                "unresolved_that_one",
                "unresolved_subject",
                "Where was that display moved?",
                None,
                None,
                None,
                None,
                (),
            ),
            PressureCase(
                "unresolved_which_it",
                "unresolved_subject",
                "Which exhibit was the one we discussed last time?",
                None,
                None,
                None,
                None,
                (),
            ),
        )
    )
    if len(result) != 68 or len({case.case_id for case in result}) != len(result):
        raise RuntimeError("invalid_pressure_cases")
    return tuple(result)


CASES = cases()


def _json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def metadata(fact: MemoryFact) -> dict[str, str]:
    a = fact.assertion
    result = {
        "source_turn_id": fact.turn_id,
        "canonical_source_ref": a.source_ref,
        "assertion_id": a.assertion_id,
        "assertion_version": str(a.version),
        "predicate": a.predicate,
        "subject": a.subject,
        "value": a.value,
        "revision_kind": a.revision_kind,
        "source_class": "synthetic_owner_direct",
        "admission_policy": "shadow_only_no_write",
    }
    if a.supersedes_id is not None:
        result["supersedes_id"] = a.supersedes_id
    return result


def build_archive() -> bytes:
    """Deterministic *preview only* Hindsight-shaped fixture, never uploaded."""
    payloads = {
        "manifest.json": _json(
            {"schema_version": 1, "source_bank_id": "jarvis-dev-only-pressure-external"}
        )
    }
    for fact in FACTS:
        a = fact.assertion
        doc_id = f"jarvis-dev-only-{a.assertion_id}"
        payloads[f"documents/{doc_id}.json"] = _json(
            {
                "id": doc_id,
                "original_text": fact.text,
                "chunks": [{"chunk_index": 0, "chunk_text": fact.text}],
                "tags": TAGS,
                "facts": [
                    {
                        "text": fact.text,
                        "fact_type": "world",
                        "chunk_index": 0,
                        "mentioned_at": a.mentioned_at,
                        "occurred_start": a.mentioned_at,
                        "entities": [a.subject],
                        "metadata": metadata(fact),
                        "tags": TAGS,
                    }
                ],
            }
        )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, contents in sorted(payloads.items()):
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.create_system = 0
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, contents)
    data = buffer.getvalue()
    if len(data) > MAX_ARCHIVE_BYTES:
        raise PressureFailure("archive_too_large")
    return data


def inspect_archive(data: bytes) -> dict[str, Any]:
    if not isinstance(data, bytes) or data != build_archive():
        raise PressureFailure("unrecognized_fictional_archive")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        expected = {
            "manifest.json",
            *(f"documents/jarvis-dev-only-{ident}.json" for ident in BY_ID),
        }
        if len(archive.namelist()) != len(expected) or set(archive.namelist()) != expected:
            raise PressureFailure("unexpected_archive_documents")
        if any(item.create_system != 0 for item in archive.infolist()):
            raise PressureFailure("nonportable_archive_header")
    return {
        "documents": DOCUMENT_COUNT,
        "sha256": hashlib.sha256(data).hexdigest(),
        "synthetic_only": True,
        "upload_authorized": False,
    }


def validate_recall(response: Any) -> tuple[str, ...]:
    """A future live-engine probe must verify original bytes and exact sources."""
    if not isinstance(response, dict) or not isinstance(response.get("results"), list):
        raise PressureFailure("invalid_recall_schema")
    items = response["results"]
    if len(items) > DOCUMENT_COUNT:
        raise PressureFailure("unbounded_recall")
    ids: list[str] = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("metadata"), dict):
            raise PressureFailure("missing_provenance")
        ident = item["metadata"].get("assertion_id")
        if not isinstance(ident, str) or ident not in BY_ID:
            raise PressureFailure("unknown_assertion")
        fact = BY_ID[ident]
        if (
            item["metadata"] != metadata(fact)
            or item.get("text") != fact.text
            or item.get("document_id") != f"jarvis-dev-only-{ident}"
            or item.get("type") != "world"
        ):
            raise PressureFailure("source_mismatch")
        if ident in ids:
            raise PressureFailure("duplicate_evidence")
        ids.append(ident)
    return tuple(ids)


class BM25Index:
    """Single reusable lexical index, ranking only public fictional text."""

    def __init__(self, corpus: tuple[MemoryFact, ...] = FACTS) -> None:
        if (
            not isinstance(corpus, tuple)
            or not 1 <= len(corpus) <= DOCUMENT_COUNT
            or any(not isinstance(x, MemoryFact) for x in corpus)
        ):
            raise PressureFailure("invalid_lexical_corpus")
        self.docs = tuple(
            (fact.assertion.assertion_id, Counter(TOKEN.findall(fact.text.casefold())))
            for fact in corpus
        )
        self.avg_length = (
            sum(sum(tokens.values()) for _, tokens in self.docs) / len(self.docs)
        )
        self.df: Counter[str] = Counter()
        for _, tokens in self.docs:
            self.df.update(tokens.keys())

    def retrieve(self, query: str) -> tuple[str, ...]:
        if not isinstance(query, str) or not 1 <= len(query) <= 400:
            raise PressureFailure("invalid_query")
        terms = set(TOKEN.findall(query.casefold()))
        n_docs = len(self.docs)
        weighted: list[tuple[float, str]] = []
        for ident, tokens in self.docs:
            count = sum(tokens.values())
            score = 0.0
            for term in terms:
                matches = tokens.get(term, 0)
                if matches == 0:
                    continue
                df = self.df[term]
                weight = math.log1p((n_docs - df + 0.5) / (df + 0.5))
                score += weight * matches * 2.2 / (
                    matches + 1.2 * (0.25 + 0.75 * count / self.avg_length)
                )
            if score > 0.0:
                weighted.append((score, ident))
        weighted.sort(key=lambda pair: (-pair[0], pair[1]))
        return tuple(ident for _, ident in weighted)


def fuse(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    """Rank-only RRF at K=60; never upgrades ranking into truthful evidence."""
    scores: dict[str, float] = {}
    for ranking in (left, right):
        if (
            not isinstance(ranking, tuple)
            or len(ranking) > DOCUMENT_COUNT
            or any(not isinstance(ident, str) or ident not in BY_ID for ident in ranking)
            or len(ranking) != len(set(ranking))
        ):
            raise PressureFailure("invalid_ranked_results")
        for idx, ident in enumerate(ranking, start=1):
            scores[ident] = scores.get(ident, 0.0) + 1 / (60 + idx)
    return tuple(sorted(scores, key=lambda ident: (-scores[ident], ident)))


def score_rankings(
    rankings: dict[str, dict[str, tuple[str, ...]]], *, k: int
) -> dict[str, Any]:
    """Compare fixed gold source chains and rule-based structured decisions.

    Scoping/ambiguity labels are supplied by the reviewed synthetic fixture,
    NOT inferred from the user's natural language.
    """
    if type(k) is not int or k not in TOP_K_CHOICES:
        raise PressureFailure("invalid_rank_cutoff")
    if not isinstance(rankings, dict) or set(rankings) != {
        "hindsight",
        "lexical",
        "hybrid",
    }:
        raise PressureFailure("missing_comparison_engines")
    cases_by_id = {case.case_id: case for case in CASES}
    for values in rankings.values():
        if not isinstance(values, dict) or set(values) != set(cases_by_id):
            raise PressureFailure("incomplete_comparison_cases")
        for ranking in values.values():
            if (
                not isinstance(ranking, tuple)
                or len(ranking) > DOCUMENT_COUNT
                or any(not isinstance(i, str) or i not in BY_ID for i in ranking)
                or len(ranking) != len(set(ranking))
            ):
                raise PressureFailure("untrusted_comparison_evidence")
    scored: dict[str, Any] = {}
    for engine, by_case in rankings.items():
        by_category: dict[str, dict[str, int]] = {}
        retrieval_hits = 0
        correct = 0
        for case in CASES:
            group = by_category.setdefault(case.category, {"cases": 0, "correct": 0})
            group["cases"] += 1
            ranks = by_case[case.case_id][:k]
            if case.subject is None:
                # Known-to-fixture unresolved scope: do not credit a language model.
                right = True
            else:
                if case.predicate is None or case.intent is None:
                    raise PressureFailure("incomplete_question_scope")
                gold = tuple(
                    fact.assertion
                    for fact in FACTS
                    if fact.assertion.subject == case.subject
                    and fact.assertion.predicate == case.predicate
                )
                complete = all(fact.assertion_id in ranks for fact in gold)
                if case.expected is not None and all(
                    ident in ranks for ident in case.required_ids
                ):
                    retrieval_hits += 1
                decision = MemoryDecisionIndex(
                    tuple(BY_ID[ident].assertion for ident in ranks)
                ).decide(MemoryQuestion(case.subject, case.predicate, case.intent))
                if case.expected is None:
                    right = decision.status == "abstain"
                else:
                    right = (
                        complete
                        and decision.status == "answer"
                        and decision.answer_code == case.expected
                    )
            group["correct"] += int(right)
            correct += int(right)
        scored[engine] = {
            "supported_retrieval": retrieval_hits,
            "supported_required": 64,
            "decisions_correct": correct,
            "decisions_required": len(CASES),
            "by_category": by_category,
        }
    return {
        "kind": "STEP9_SYNTHETIC_SEMANTIC_PRESSURE",
        "fact_count": DOCUMENT_COUNT,
        "query_count": len(CASES),
        "top_k": k,
        "engines": scored,
        "automatic_entity_resolution_tested": False,
        "llm_answer_accuracy_tested": False,
        "production_promotion_allowed": False,
    }


def offline_report() -> dict[str, Any]:
    """Actual BM25 across three K budgets, no fake semantic measurements."""
    lexical_index = BM25Index()
    baseline = {case.case_id: lexical_index.retrieve(case.query) for case in CASES}
    empty = {case.case_id: () for case in CASES}
    return {
        "kind": "STEP9_OFFLINE_ONLY",
        "status": "pass",
        "archive": inspect_archive(build_archive()),
        "cases": len(CASES),
        "semantic_alias_cases": 48,
        "exact_descriptor_controls": 16,
        "unknown_or_unresolved": 4,
        "results_by_k": {
            str(k): score_rankings(
                {"hindsight": empty, "lexical": baseline, "hybrid": empty},
                k=k,
            )["engines"]["lexical"]
            for k in TOP_K_CHOICES
        },
        "hindsight_measured": False,
        "provider_results_simulated": False,
        "production_promotion_allowed": False,
    }
