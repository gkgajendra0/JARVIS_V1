"""Research-only hybrid memory retrieval and bounded context assembly.

Offline, fictional, read-only. NO SDK clients, SQLCipher, Docker, LLMs,
providers, network calls, disk I/O, runtime registrations or writes.

Search channels propose assertion IDs, NEVER truth. Accepted assertions are
validated by the existing synthetic provenance/lineage decision gate.
The packet contains no facts that were absent from candidate retrieval.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from jarvis.memory.research_decision_gate import (
    Assertion,
    DecisionSafetyError,
    MemoryDecisionIndex,
    MemoryQuestion,
)

MAX_STREAM_HITS = 512
MAX_GROUPS = 8
MAX_CONTEXT_CHARS = 8192
RRF_K = 60
_NAMES = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_ID = re.compile(r"^synthetic-[a-z0-9-]{3,80}$")
_ORIGINS = frozenset({"hindsight", "lexical", "temporal", "relationship"})


class HybridSafetyError(ValueError):
    """Fixed-string reason codes only; do not include untrusted content."""


@dataclass(frozen=True, slots=True)
class EvidenceStream:
    """An engine's ranked candidate assertion IDs, not its raw response text."""

    origin: Literal["hindsight", "lexical", "temporal", "relationship"]
    assertion_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextRequest:
    """A trusted, pre-parsed query scope. Not a user-language parser."""

    subject: str
    predicates: tuple[str, ...]
    max_chars: int = 4096
    max_groups: int = 4


@dataclass(frozen=True, slots=True)
class ContextPacket:
    """Structured, bounded serialized facts from complete evidence lineages."""

    status: Literal["ready", "abstain"]
    reason_code: str
    payload_json: str
    included_assertion_ids: tuple[str, ...]
    included_predicates: tuple[str, ...]
    withheld_predicates: tuple[str, ...]
    chars_used: int
    production_promotion_allowed: bool = False


def _validate_request(req: ContextRequest) -> None:
    if not isinstance(req, ContextRequest):
        raise HybridSafetyError("untrusted_context_request")
    if (
        not isinstance(req.subject, str)
        or not _ID.fullmatch(req.subject)
        or not isinstance(req.predicates, tuple)
        or not 1 <= len(req.predicates) <= MAX_GROUPS
        or any(
            not isinstance(pred, str) or not _NAMES.fullmatch(pred)
            for pred in req.predicates
        )
        or len(set(req.predicates)) != len(req.predicates)
        or type(req.max_chars) is not int
        or not 256 <= req.max_chars <= MAX_CONTEXT_CHARS
        or type(req.max_groups) is not int
        or not 1 <= req.max_groups <= MAX_GROUPS
    ):
        raise HybridSafetyError("untrusted_context_request")


def _validate_streams(
    streams: tuple[EvidenceStream, ...], known: set[str]
) -> tuple[EvidenceStream, ...]:
    if not isinstance(streams, tuple) or len(streams) > len(_ORIGINS):
        raise HybridSafetyError("invalid_evidence_streams")
    seen_origins: set[str] = set()
    for stream in streams:
        if (
            not isinstance(stream, EvidenceStream)
            or not isinstance(stream.origin, str)
            or stream.origin not in _ORIGINS
            or stream.origin in seen_origins
            or not isinstance(stream.assertion_ids, tuple)
            or len(stream.assertion_ids) > MAX_STREAM_HITS
        ):
            raise HybridSafetyError("invalid_evidence_streams")
        seen_origins.add(stream.origin)
        seen_ids: set[str] = set()
        for assertion_id in stream.assertion_ids:
            if (
                not isinstance(assertion_id, str)
                or assertion_id not in known
                or assertion_id in seen_ids
            ):
                raise HybridSafetyError("unverified_or_duplicate_candidate")
            seen_ids.add(assertion_id)
    return streams


def _abstain(reason: str, withheld: tuple[str, ...]) -> ContextPacket:
    return ContextPacket("abstain", reason, "[]", (), (), withheld, 2)


def assemble_context(
    canonical_synthetic: tuple[Assertion, ...],
    streams: tuple[EvidenceStream, ...],
    req: ContextRequest,
) -> ContextPacket:
    """Fuse independent candidate rankings and pack only fully verified lineages.

    This test seam has complete *synthetic* canonical assertion metadata.
    It never supplements retrieved candidates with missing source facts.
    In production, provenance must be authenticated by a read-only canonical
    adapter before engine IDs can be considered trustworthy.
    """
    _validate_request(req)
    try:
        index = MemoryDecisionIndex(canonical_synthetic)
    except DecisionSafetyError as exc:
        raise HybridSafetyError("untrusted_canonical_fixture") from exc
    known = {fact.assertion_id for fact in canonical_synthetic}
    _validate_streams(streams, known)

    # RRF uses ranks alone. Repeated hits in one stream and duplicate stream
    # names are rejected, rather than allowing a provider to double-vote.
    rank_score: dict[str, float] = {}
    present: set[str] = set()
    for stream in streams:
        for rank, assertion_id in enumerate(stream.assertion_ids, start=1):
            present.add(assertion_id)
            rank_score[assertion_id] = rank_score.get(assertion_id, 0.0) + (
                1.0 / (RRF_K + rank)
            )

    by_predicate: dict[str, list[Assertion]] = {
        pred: [
            fact
            for fact in canonical_synthetic
            if fact.subject == req.subject and fact.predicate == pred
        ]
        for pred in req.predicates
    }
    candidates: list[tuple[float, str, list[Assertion]]] = []
    withheld: list[str] = []
    for pred in req.predicates:
        group = by_predicate[pred]
        if not group:
            withheld.append(pred)
            continue
        if not all(fact.assertion_id in present for fact in group):
            # A newer claim without its original/correction chain is *not*
            # accepted as a standalone current fact.
            withheld.append(pred)
            continue
        decision = index.decide(MemoryQuestion(req.subject, pred, "history"))
        if decision.status != "answer":
            withheld.append(pred)
            continue
        # Full graph history is deterministic; preserve chronological versions.
        ordered = sorted(group, key=lambda f: (f.version, f.assertion_id))
        evidence_score = sum(rank_score[fact.assertion_id] for fact in ordered)
        candidates.append((evidence_score, pred, ordered))
    if not candidates:
        return _abstain("no_complete_verified_lineage", tuple(withheld))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    packed: list[dict[str, object]] = []
    included_ids: list[str] = []
    included_preds: list[str] = []
    for _score, pred, group in candidates:
        if len(packed) >= req.max_groups:
            withheld.append(pred)
            continue
        unit: dict[str, object] = {
            "predicate": pred,
            "states": [
                {
                    "assertion_id": fact.assertion_id,
                    "version": fact.version,
                    "revision_kind": fact.revision_kind,
                    "value": fact.value,
                    "source_ref": fact.source_ref,
                }
                for fact in group
            ],
        }
        proposed = json.dumps(
            [*packed, unit],
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(proposed) > req.max_chars:
            withheld.append(pred)
            continue
        packed.append(unit)
        included_preds.append(pred)
        included_ids.extend(fact.assertion_id for fact in group)

    if not packed:
        return _abstain("context_budget_exceeded", tuple(sorted(withheld)))
    payload = json.dumps(
        packed, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    return ContextPacket(
        status="ready",
        reason_code="complete_synthetic_evidence",
        payload_json=payload,
        included_assertion_ids=tuple(included_ids),
        included_predicates=tuple(included_preds),
        withheld_predicates=tuple(sorted(withheld)),
        chars_used=len(payload),
    )
