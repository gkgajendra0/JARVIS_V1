"""Research-only Hindsight external-fact archive: NO NETWORK OR MODEL CALLS.

This module does not open a DB or import the Hindsight SDK. Its purpose is
to prove the shape/lineage of a pinned fictional fact transfer before an
owner-machine-only server trial. It NEVER ingests JARVIS owner memories.

The external import endpoint is a separate PostgreSQL/Hindsight store,
not a replacement for JARVIS SQLCipher. Import can activate automatic
consolidation/webhooks on a server; building the ZIP does not disable it.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any

_SYNTHETIC_ID = re.compile(r"^synthetic-[a-z0-9-]{3,72}$")
_SAFE_PREDICATE = re.compile(r"^[a-z][a-z0-9_]{1,79}$")
_MAX_FACTS = 8
_MAX_ARCHIVE_BYTES = 32_768
_FIXED_ZIP_TIME = (2026, 1, 1, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class SyntheticFact:
    """Explicit fictional assertion, not an inferred canonical write."""

    assertion_id: str
    source_turn_id: str
    predicate: str
    text: str
    mentioned_at: str
    occurred_start: str
    revision_kind: str
    version: int
    supersedes_id: str | None = None


# The versioned facts below are fictional, with no names or preferences from
# the actual owner. The ambiguous utterance is NOT admitted as a fact.
PINNED_FACTS: tuple[SyntheticFact, ...] = (
    SyntheticFact(
        "synthetic-workshop-day-v1",
        "synthetic-turn-001",
        "workshop_day",
        "The fictional Atlas workshop was described as Saturday.",
        "2026-01-02T10:00:00Z",
        "2026-01-02T10:00:00Z",
        "original_statement",
        1,
    ),
    SyntheticFact(
        "synthetic-workshop-day-v2",
        "synthetic-turn-002",
        "workshop_day",
        "Correction: the fictional Atlas workshop is on Sunday, not Saturday.",
        "2026-01-03T10:00:00Z",
        "2026-01-03T10:00:00Z",
        "correction",
        2,
        "synthetic-workshop-day-v1",
    ),
    SyntheticFact(
        "synthetic-report-day-v1",
        "synthetic-turn-003",
        "report_day",
        "The fictional Nile project report was sent on Monday.",
        "2026-01-02T10:00:00Z",
        "2026-01-02T10:00:00Z",
        "historical_state",
        1,
    ),
    SyntheticFact(
        "synthetic-report-day-v2",
        "synthetic-turn-004",
        "report_day",
        "The fictional Nile project report is now sent on Thursday.",
        "2026-02-01T10:00:00Z",
        "2026-02-01T10:00:00Z",
        "historical_change",
        2,
        "synthetic-report-day-v1",
    ),
    SyntheticFact(
        "synthetic-workshop-venue-v1",
        "synthetic-turn-005",
        "workshop_venue",
        "The fictional Atlas workshop venue is Hall B.",
        "2026-01-02T10:00:00Z",
        "2026-01-02T10:00:00Z",
        "unrelated_current_fact",
        1,
    ),
)


def _iso_utc(value: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("synthetic timestamps require explicit UTC Z suffix")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid synthetic UTC timestamp") from exc
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("synthetic timestamp must be UTC")
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate(facts: tuple[SyntheticFact, ...]) -> None:
    if not isinstance(facts, tuple) or not 1 <= len(facts) <= _MAX_FACTS:
        raise ValueError("bounded synthetic tuple required")
    ids: set[str] = set()
    seen: dict[str, SyntheticFact] = {}
    for fact in facts:
        if not isinstance(fact, SyntheticFact):
            raise TypeError("fact must be SyntheticFact")
        if (
            not _SYNTHETIC_ID.fullmatch(fact.assertion_id)
            or not _SYNTHETIC_ID.fullmatch(fact.source_turn_id)
            or not _SAFE_PREDICATE.fullmatch(fact.predicate)
        ):
            raise ValueError("non-synthetic identity or invalid predicate")
        if fact.assertion_id in ids:
            raise ValueError("duplicate synthetic assertion id")
        if type(fact.version) is not int or not 1 <= fact.version <= 16:
            raise ValueError("invalid synthetic version")
        if not isinstance(fact.text, str) or not 5 <= len(fact.text) <= 200:
            raise ValueError("invalid synthetic fact text")
        if any(x in fact.text.casefold() for x in ("api key", "password", "secret")):
            raise ValueError("potential secret in synthetic fixture")
        mentioned = _iso_utc(fact.mentioned_at)
        occurred = _iso_utc(fact.occurred_start)
        if occurred > mentioned:
            raise ValueError("event cannot occur after its recording time")
        if not isinstance(fact.revision_kind, str) or fact.revision_kind not in {
            "original_statement",
            "correction",
            "historical_state",
            "historical_change",
            "unrelated_current_fact",
        }:
            raise ValueError("invalid synthetic revision label")
        if fact.supersedes_id is not None:
            previous = seen.get(fact.supersedes_id)
            if previous is None:
                raise ValueError("synthetic predecessor missing or out of order")
            if (
                previous.predicate != fact.predicate
                or fact.version != previous.version + 1
            ):
                raise ValueError("synthetic version lineage mismatch")
            if fact.revision_kind not in {"correction", "historical_change"}:
                raise ValueError("unexpected supersession label")
        elif fact.version != 1:
            raise ValueError("noninitial synthetic version without predecessor")
        ids.add(fact.assertion_id)
        seen[fact.assertion_id] = fact


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def build_synthetic_external_fact_zip(
    facts: tuple[SyntheticFact, ...] = PINNED_FACTS,
) -> bytes:
    """Generate documented Hindsight /transfer/import ZIP, without I/O.

    One fact per document prevents replacement of an unrelated assertion
    during document_conflict=skip. Internal Hindsight ids are untrusted;
    our stable identifiers remain explicit metadata.
    """

    _validate(facts)
    payloads: dict[str, bytes] = {
        "manifest.json": _json_bytes(
            {"schema_version": 1, "source_bank_id": "jarvis-dev-only-external"}
        )
    }
    for fact in facts:
        doc_id = f"jarvis-dev-only-{fact.assertion_id}"
        context = {
            "source_turn_id": fact.source_turn_id,
            "assertion_id": fact.assertion_id,
            "assertion_version": fact.version,
            "predicate": fact.predicate,
            "revision_kind": fact.revision_kind,
            "supersedes_id": fact.supersedes_id,
            "source_class": "synthetic_owner_direct",
            "admission_policy": "shadow_only_no_write",
        }
        payloads[f"documents/{doc_id}.json"] = _json_bytes(
            {
                "id": doc_id,
                "original_text": fact.text,
                "chunks": [{"chunk_index": 0, "chunk_text": fact.text}],
                "tags": ["jarvis-dev-only", "synthetic"],
                "facts": [
                    {
                        "text": fact.text,
                        "fact_type": "world",
                        "chunk_index": 0,
                        "mentioned_at": _iso_utc(fact.mentioned_at),
                        "occurred_start": _iso_utc(fact.occurred_start),
                        "entities": ["Atlas Workshop"]
                        if fact.predicate.startswith("workshop_")
                        else ["Nile Project"],
                        "metadata": context,
                        "tags": ["jarvis-dev-only", "synthetic"],
                    }
                ],
            }
        )
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(payloads.items()):
            entry = zipfile.ZipInfo(name, _FIXED_ZIP_TIME)
            entry.compress_type = zipfile.ZIP_STORED
            entry.external_attr = 0o600 << 16
            archive.writestr(entry, data)
    result = output.getvalue()
    if len(result) > _MAX_ARCHIVE_BYTES:
        raise ValueError("synthetic archive exceeds limit")
    return result


def inspect_synthetic_archive(archive_bytes: bytes) -> dict[str, Any]:
    """Only local integrity inspection; not evidence Hindsight imported it."""

    if len(archive_bytes) > _MAX_ARCHIVE_BYTES:
        raise ValueError("oversized archive")
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        expected = {
            "manifest.json",
            *{
                f"documents/jarvis-dev-only-{fact.assertion_id}.json"
                for fact in PINNED_FACTS
            },
        }
        if set(archive.namelist()) != expected or len(archive.namelist()) != len(
            expected
        ):
            raise ValueError("unexpected files or duplicate ZIP paths")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest != {
            "schema_version": 1,
            "source_bank_id": "jarvis-dev-only-external",
        }:
            raise ValueError("invalid manifest")
        for fact in PINNED_FACTS:
            filename = f"documents/jarvis-dev-only-{fact.assertion_id}.json"
            record = json.loads(archive.read(filename))
            stored = record["facts"][0]
            meta = stored["metadata"]
            if (
                record["id"] != f"jarvis-dev-only-{fact.assertion_id}"
                or record["original_text"] != fact.text
                or stored["text"] != fact.text
                or stored["fact_type"] != "world"
                or stored["mentioned_at"] != _iso_utc(fact.mentioned_at)
                or stored["occurred_start"] != _iso_utc(fact.occurred_start)
                or meta["assertion_id"] != fact.assertion_id
                or meta["assertion_version"] != fact.version
                or meta["source_turn_id"] != fact.source_turn_id
                or meta["supersedes_id"] != fact.supersedes_id
            ):
                raise ValueError("synthetic archive provenance mismatch")
    return {
        "kind": "OFFLINE_HINDSIGHT_EXTERNAL_FACT_CONTRACT_ONLY",
        "document_count": len(PINNED_FACTS),
        "fact_count": len(PINNED_FACTS),
        "sha256": hashlib.sha256(archive_bytes).hexdigest(),
        "synthetic_only": True,
        "no_provider_calls": True,
        "no_database_access": True,
        "no_server_import_tested": True,
    }
