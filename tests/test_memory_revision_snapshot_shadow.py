"""Synthetic SQLite proof for read-only revision metadata resolution.

No owner database, SQLCipher key, provider call or production write is touched.
The SQLite fixtures are disposable and contain only invented project facts.
"""

from __future__ import annotations

import itertools
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jarvis.memory.assertions import SemanticAssertionDraft
from jarvis.memory.candidates import (
    MemoryCandidateType,
    MemoryExtractionIntent,
    MemoryExtractionProposal,
    MemoryExtractionSensitivity,
)
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.provenance import MemorySource
from jarvis.memory.revision_proposal_shadow import review_extracted_revision_shadow
from jarvis.memory.revision_shadow import (
    RevisionDisposition,
    RevisionIntent,
    RevisionShadowInput,
    assess_revision_shadow,
)
from jarvis.memory.revision_snapshot_shadow import CanonicalRevisionSnapshotReader
from jarvis.memory.types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)
from jarvis.memory.worker import SerialConnectionWorker

BASE = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)


def _ids(prefix: str):
    sequence = itertools.count(1)
    return lambda: f"{prefix}-{next(sequence)}"


def _draft(
    text: str, *, predicate: str = "reply_style", sensitivity=Sensitivity.STANDARD
) -> SemanticAssertionDraft:
    return SemanticAssertionDraft(
        subject_scope="personal",
        subject="owner",
        predicate=predicate,
        value_type=ValueType.TEXT,
        value=text,
        normalized_text=text,
        freshness_class=FreshnessClass.CHANGEABLE,
        sensitivity=sensitivity,
    )


def _source(
    ident: str,
    *,
    source_class=MemorySourceClass.OWNER_EXPLICIT,
    authority=AuthorityClass.OWNER_EXPLICIT,
    sensitivity=Sensitivity.STANDARD,
) -> MemorySource:
    return MemorySource(
        source_id=ident,
        source_class=source_class,
        canonical_ref=f"conversation:synthetic:{ident}",
        observed_at=BASE,
        authority_class=authority,
        sensitivity=sensitivity,
        created_at=BASE,
    )


def _setup(path: Path):
    def writer_factory() -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        MemoryMigrationRunner(clock=lambda: BASE).apply(connection)
        return connection

    def reader_factory() -> sqlite3.Connection:
        # SQLite itself refuses all mutations on the research reader.
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only = ON")
        return connection

    writer = SerialConnectionWorker(
        writer_factory, thread_name="revision-shadow-synthetic-writer"
    )
    read_worker = SerialConnectionWorker(
        reader_factory, thread_name="revision-shadow-synthetic-reader"
    )
    lifecycle = MemoryLifecycleService(
        writer,
        clock=lambda: BASE,
        assertion_id_factory=_ids("synthetic"),
        operation_id_factory=_ids("operation"),
    )
    return writer, read_worker, lifecycle, CanonicalRevisionSnapshotReader(read_worker)


@pytest.mark.asyncio
async def test_derived_lineage_version_and_owner_source_metadata(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _setup(tmp_path / "facts.db")
    try:
        first = await lifecycle.create(
            _draft("short examples"), _source("owner-initial")
        )
        changed = await lifecycle.correct(
            first.assertion_id,
            _draft("detailed examples"),
            _source("owner-correction"),
        )
        snapshot = await resolver.resolve_exact(
            subject_scope="personal", subject="owner", predicate="reply_style"
        )
        witness = snapshot.witness
        assert witness is not None
        assert witness.assertion_id == changed.assertion_id
        assert witness.assertion_version == 2
        assert witness.canonical_source_ref == "conversation:synthetic:owner-correction"
        assert witness.latest_version_verified
        assert witness.owner_authority_verified
        assert witness.meaning_equivalent_verified is None

        decision = assess_revision_shadow(
            RevisionShadowInput(
                accepted_user_turn=True,
                source_class=MemorySourceClass.OWNER_DIRECT,
                sensitivity=MemoryExtractionSensitivity.NORMAL,
                intent=RevisionIntent.FACT_CORRECTION,
                witness=witness,
            )
        )
        assert decision.disposition is RevisionDisposition.CONFLICT_REVIEW
        assert not hasattr(decision, "value")
        assert not hasattr(decision, "authorized_write")
        assert not hasattr(witness, "value")

        # The old assertion must never be accepted as the latest one.
        assert changed.supersedes_id == first.assertion_id
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_missing_or_ambiguous_canonical_target_is_not_guessed(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _setup(tmp_path / "ambiguous.db")
    try:
        # The writer initializes the disposable schema before a mode=ro reader
        # can open it; unlike other cases there is no initial create() call.
        await writer.start()
        missing = await resolver.resolve_exact(
            subject_scope="personal", subject="owner", predicate="reply_style"
        )
        assert missing.witness is None
        assert missing.reason_code == "canonical_target_not_found"
        await lifecycle.create(_draft("small examples"), _source("owner-one"))
        await lifecycle.create(_draft("large examples"), _source("owner-two"))
        ambiguous = await resolver.resolve_exact(
            subject_scope="personal", subject="owner", predicate="reply_style"
        )
        assert ambiguous.witness is None
        assert ambiguous.reason_code == "ambiguous_current_assertions"
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_wrong_scope_and_untrusted_source_fail_closed(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _setup(tmp_path / "untrusted.db")
    try:
        await lifecycle.create(
            _draft("short examples"),
            _source(
                "untrusted-web",
                source_class=MemorySourceClass.EXTERNAL_WEB,
                authority=AuthorityClass.UNTRUSTED,
            ),
        )
        for scope, reason in [
            ("wrong-scope", "canonical_target_not_found"),
            ("personal", "canonical_owner_source_not_verified"),
        ]:
            result = await resolver.resolve_exact(
                subject_scope=scope, subject="owner", predicate="reply_style"
            )
            assert result.witness is None
            assert result.reason_code == reason
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_restricted_sensitive_assertion_never_returns_witness(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _setup(tmp_path / "private.db")
    try:
        await lifecycle.create(
            _draft("fictional sensitive item", sensitivity=Sensitivity.PRIVATE),
            _source("private", sensitivity=Sensitivity.PRIVATE),
        )
        result = await resolver.resolve_exact(
            subject_scope="personal", subject="owner", predicate="reply_style"
        )
        assert result.witness is None
        assert result.reason_code == "canonical_sensitivity_restricted"
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_retraction_removes_current_target_from_revision_resolver(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _setup(tmp_path / "retracted.db")
    try:
        original = await lifecycle.create(_draft("short examples"), _source("initial"))
        await lifecycle.retract(original.assertion_id, _source("retracted"))
        result = await resolver.resolve_exact(
            subject_scope="personal", subject="owner", predicate="reply_style"
        )
        assert result.witness is None
        assert result.reason_code == "canonical_target_not_found"
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_correction_cannot_launder_an_untrusted_ancestor(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _setup(tmp_path / "laundered.db")
    try:
        external = await lifecycle.create(
            _draft("external claim"),
            _source(
                "untrusted-original",
                source_class=MemorySourceClass.EXTERNAL_WEB,
                authority=AuthorityClass.UNTRUSTED,
            ),
        )
        await lifecycle.correct(
            external.assertion_id,
            _draft("owner replacement"),
            _source("owner-correction"),
        )
        resolved = await resolver.resolve_exact(
            subject_scope="personal", subject="owner", predicate="reply_style"
        )
        assert resolved.witness is None
        assert resolved.reason_code == "canonical_lineage_source_unverified"
    finally:
        await reader.close()
        await writer.close()


def _proposal(
    intent: MemoryExtractionIntent,
    candidate_type: MemoryCandidateType,
    *,
    predicate: str = "reply_style",
    subject: str = "owner",
    durable: bool = True,
    sensitivity: MemoryExtractionSensitivity = MemoryExtractionSensitivity.NORMAL,
) -> MemoryExtractionProposal:
    return MemoryExtractionProposal(
        intent=intent,
        candidate_type=candidate_type,
        durable_candidate=durable,
        subject=subject,
        predicate=predicate,
        value="fictional revision candidate",
        sensitivity=sensitivity,
        confidence=0.85,
    )


@pytest.mark.asyncio
async def test_proposal_bridge_matches_a_real_synthetic_canonical_revision(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _setup(tmp_path / "bridge.db")
    try:
        first = await lifecycle.create(_draft("initial"), _source("first-owner"))
        await lifecycle.correct(
            first.assertion_id, _draft("changed"), _source("second-owner")
        )
        for intent, kind in (
            (MemoryExtractionIntent.HISTORICAL_CHANGE, MemoryCandidateType.FACT_CHANGE),
            (MemoryExtractionIntent.CORRECTION, MemoryCandidateType.FACT_CORRECTION),
            (MemoryExtractionIntent.RETRACTION, MemoryCandidateType.FACT_RETRACTION),
        ):
            decision = await review_extracted_revision_shadow(
                proposal=_proposal(intent, kind),
                accepted_user_turn=True,
                source_class=MemorySourceClass.OWNER_DIRECT,
                reader=resolver,
            )
            assert decision.disposition is RevisionDisposition.CONFLICT_REVIEW
            assert decision.reason_code == "verified_lifecycle_review"
            assert not hasattr(decision, "source_ref")
            assert not hasattr(decision, "memory_value")
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_proposal_bridge_does_not_guess_missing_or_duplicate_memories(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _setup(tmp_path / "bridge-missing.db")
    try:
        await writer.start()
        change = await review_extracted_revision_shadow(
            proposal=_proposal(
                MemoryExtractionIntent.CORRECTION, MemoryCandidateType.FACT_CORRECTION
            ),
            accepted_user_turn=True,
            source_class=MemorySourceClass.OWNER_DIRECT,
            reader=resolver,
        )
        assert change.disposition is RevisionDisposition.NEEDS_CLARIFICATION
        new = await review_extracted_revision_shadow(
            proposal=_proposal(
                MemoryExtractionIntent.CANDIDATE, MemoryCandidateType.PREFERENCE
            ),
            accepted_user_turn=True,
            source_class=MemorySourceClass.OWNER_DIRECT,
            reader=resolver,
        )
        assert new.disposition is RevisionDisposition.REVIEW

        await lifecycle.create(_draft("one"), _source("owner-1"))
        await lifecycle.create(_draft("two"), _source("owner-2"))
        ambiguous = await review_extracted_revision_shadow(
            proposal=_proposal(
                MemoryExtractionIntent.RETRACTION, MemoryCandidateType.FACT_RETRACTION
            ),
            accepted_user_turn=True,
            source_class=MemorySourceClass.OWNER_DIRECT,
            reader=resolver,
        )
        assert ambiguous.disposition is RevisionDisposition.NEEDS_CLARIFICATION
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_proposal_bridge_rejects_source_laundering_and_sensitive_metadata(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _setup(tmp_path / "bridge-protect.db")
    try:
        await lifecycle.create(
            _draft("private", sensitivity=Sensitivity.PRIVATE),
            _source("private", sensitivity=Sensitivity.PRIVATE),
        )
        result = await review_extracted_revision_shadow(
            proposal=_proposal(
                MemoryExtractionIntent.CORRECTION, MemoryCandidateType.FACT_CORRECTION
            ),
            accepted_user_turn=True,
            source_class=MemorySourceClass.OWNER_DIRECT,
            reader=resolver,
        )
        assert result.disposition is RevisionDisposition.SKIP
        assert result.reason_code == "canonical_sensitivity_restricted"
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_proposal_bridge_preflight_skips_untrusted_non_durable_and_bad_pairs(
    tmp_path: Path,
) -> None:
    writer, reader, _lifecycle, resolver = _setup(tmp_path / "bridge-denied.db")
    try:
        # Reader is deliberately unopened. Any accidental read will fail,
        # so these pre-provider/source policy cases prove early exit.
        cases = (
            (
                _proposal(
                    MemoryExtractionIntent.CORRECTION,
                    MemoryCandidateType.FACT_CORRECTION,
                ),
                False,
                MemorySourceClass.OWNER_DIRECT,
                RevisionDisposition.SKIP,
            ),
            (
                _proposal(
                    MemoryExtractionIntent.CORRECTION,
                    MemoryCandidateType.FACT_CORRECTION,
                ),
                True,
                MemorySourceClass.EXTERNAL_WEB,
                RevisionDisposition.SKIP,
            ),
            (
                _proposal(
                    MemoryExtractionIntent.CANDIDATE,
                    MemoryCandidateType.PREFERENCE,
                    durable=False,
                ),
                True,
                MemorySourceClass.OWNER_DIRECT,
                RevisionDisposition.SKIP,
            ),
            (
                _proposal(
                    MemoryExtractionIntent.CANDIDATE,
                    MemoryCandidateType.FACT_CORRECTION,
                ),
                True,
                MemorySourceClass.OWNER_DIRECT,
                RevisionDisposition.SKIP,
            ),
            (
                _proposal(
                    MemoryExtractionIntent.CORRECTION,
                    MemoryCandidateType.FACT_CORRECTION,
                    subject="other_person",
                ),
                True,
                MemorySourceClass.OWNER_DIRECT,
                RevisionDisposition.NEEDS_CLARIFICATION,
            ),
        )
        for proposal, accepted, origin, expected in cases:
            result = await review_extracted_revision_shadow(
                proposal=proposal,
                accepted_user_turn=accepted,
                source_class=origin,
                reader=resolver,
            )
            assert result.disposition is expected
    finally:
        await reader.close()
        await writer.close()
