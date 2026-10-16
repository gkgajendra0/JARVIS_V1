"""Offline end-to-end contextual memory review against disposable SQLite truth."""

from __future__ import annotations

import itertools
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from jarvis.conversation import ConversationRole, ConversationSession
from jarvis.memory.assertions import SemanticAssertionDraft
from jarvis.memory.candidates import (
    MemoryCandidateType,
    MemoryExtractionIntent,
    MemoryExtractionProposal,
    MemoryExtractionSensitivity,
)
from jarvis.memory.contextual_control_shadow import (
    ContextualBoundaryDisposition,
    assess_contextual_memory_boundary,
)
from jarvis.memory.contextual_extractors import (
    ContextualGeminiMemoryExtractor,
    ContextualOpenAIMemoryExtractor,
)
from jarvis.memory.contextual_retrieval_shadow import (
    review_with_existing_retrieval_shadow,
)
from jarvis.memory.contextual_revision_shadow import review_contextual_revision_shadow
from jarvis.memory.embeddings import SemanticEmbeddingStore
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.provenance import MemorySource
from jarvis.memory.retrieval import RetrievalCandidate, SemanticRetrievalService
from jarvis.memory.revision_shadow import RevisionDisposition
from jarvis.memory.revision_snapshot_shadow import CanonicalRevisionSnapshotReader
from jarvis.memory.types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)
from jarvis.memory.worker import SerialConnectionWorker

BASE = datetime(2026, 10, 16, 7, 30, tzinfo=UTC)


def _ids(prefix: str):
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter)}"


def _source(name: str, sensitivity: Sensitivity = Sensitivity.STANDARD):
    return MemorySource(
        source_id=name,
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        canonical_ref=f"conversation:synthetic:{name}",
        observed_at=BASE,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
        sensitivity=sensitivity,
        created_at=BASE,
    )


def _draft(
    value: str,
    *,
    key: str = "reply_style",
    sensitivity: Sensitivity = Sensitivity.STANDARD,
):
    return SemanticAssertionDraft(
        subject_scope="personal",
        subject="owner",
        predicate=key,
        value_type=ValueType.TEXT,
        value=value,
        normalized_text=value,
        freshness_class=FreshnessClass.CHANGEABLE,
        sensitivity=sensitivity,
    )


def _fixture(path: Path):
    def writer_factory():
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys=ON")
        MemoryMigrationRunner(clock=lambda: BASE).apply(connection)
        return connection

    def reader_factory():
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only=ON")
        return connection

    writer = SerialConnectionWorker(
        writer_factory, thread_name="context-revision-disposable-writer"
    )
    reader = SerialConnectionWorker(
        reader_factory, thread_name="context-revision-disposable-reader"
    )
    lifecycle = MemoryLifecycleService(
        writer,
        clock=lambda: BASE,
        assertion_id_factory=_ids("assertion"),
        operation_id_factory=_ids("operation"),
    )
    return writer, reader, lifecycle, CanonicalRevisionSnapshotReader(reader)


def _retrieval(record: Any) -> RetrievalCandidate:
    return RetrievalCandidate(
        assertion=record,
        fused_rank=1,
        fused_score=0.45,
        lexical_rank=1,
        lexical_score=0.5,
        dense_rank=1,
        dense_score=0.7,
    )


def _session(*, current: str = "Ab mujhe detailed answers chahiye."):
    conversation = ConversationSession(session_id="synthetic-only")
    conversation.start()
    conversation.accept_turn(
        ConversationRole.USER, "Pehle main short explanations prefer karta tha."
    )
    conversation.accept_turn(ConversationRole.ASSISTANT, "I can do that.")
    latest = conversation.accept_turn(ConversationRole.USER, current)
    return conversation, latest


def _proposal(
    *,
    predicate: str = "reply_style",
    intent: MemoryExtractionIntent = MemoryExtractionIntent.HISTORICAL_CHANGE,
    candidate_type: MemoryCandidateType = MemoryCandidateType.FACT_CHANGE,
):
    return MemoryExtractionProposal(
        intent=intent,
        candidate_type=candidate_type,
        durable_candidate=True,
        subject="owner",
        predicate=predicate,
        value="Detailed explanations",
        sensitivity=MemoryExtractionSensitivity.NORMAL,
        confidence=0.9,
    )


class FakeContextExtractor:
    def __init__(self, proposal=None, failure: Exception | None = None):
        self.proposal = proposal if proposal is not None else _proposal()
        self.failure = failure
        self.calls: list[dict[str, str]] = []

    async def extract_contextual(self, *, text: str, context: str):
        self.calls.append({"text": text, "context": context})
        if self.failure is not None:
            raise self.failure
        return self.proposal


@pytest.mark.asyncio
async def test_contextual_shadow_joins_owner_turn_retrieval_and_read_only_truth(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _fixture(tmp_path / "joined.db")
    conversation, current = _session()
    extractor = FakeContextExtractor()
    try:
        record = await lifecycle.create(
            _draft("Short explanations"), _source("original")
        )
        result = await review_contextual_revision_shadow(
            conversation=conversation,
            turn=current,
            retrieved=(_retrieval(record),),
            reader=resolver,
            extractor=extractor,
            allow_model_calls=True,
        )
        assert result.disposition is RevisionDisposition.CONFLICT_REVIEW
        assert result.reason_code == "verified_lifecycle_review"
        assert len(extractor.calls) == 1
        assert extractor.calls[0]["text"] == current.text
        context = json.loads(extractor.calls[0]["context"])
        assert context["verified_current_memory_candidates"] == [
            {"predicate": "reply_style", "current_value": "Short explanations"}
        ]
        assert context["recent_accepted_owner_turns"] == [
            "Pehle main short explanations prefer karta tha."
        ]
        assert "I can do that" not in extractor.calls[0]["context"]
        # Pure review: no memory changed, even with a convincing model result.
        observed = await resolver.resolve_exact(
            subject_scope="personal", subject="owner", predicate="reply_style"
        )
        assert observed.witness is not None
        assert observed.witness.assertion_id == record.assertion_id
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_model_off_and_explicit_control_do_not_call_extractor(
    tmp_path: Path,
) -> None:
    writer, reader, _lifecycle, resolver = _fixture(tmp_path / "disabled.db")
    conversation, turn = _session()
    extractor = FakeContextExtractor()
    try:
        default = await review_contextual_revision_shadow(
            conversation=conversation,
            turn=turn,
            retrieved=(),
            reader=resolver,
            extractor=extractor,
        )
        assert default.disposition is RevisionDisposition.SKIP
        assert default.reason_code == "model_calls_disabled"
        assert extractor.calls == []

        session, explicit = _session(
            current="Please remember this: a fictional test statement."
        )
        skipped = await review_contextual_revision_shadow(
            conversation=session,
            turn=explicit,
            retrieved=(),
            reader=resolver,
            extractor=extractor,
            allow_model_calls=True,
        )
        assert skipped.reason_code == "explicit_memory_control_boundary"
        assert extractor.calls == []
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_context_target_must_be_among_verified_retrieved_memories(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _fixture(tmp_path / "target.db")
    conversation, turn = _session()
    extractor = FakeContextExtractor(_proposal(predicate="other_key"))
    try:
        record = await lifecycle.create(_draft("Short"), _source("one"))
        result = await review_contextual_revision_shadow(
            conversation=conversation,
            turn=turn,
            retrieved=(_retrieval(record),),
            reader=resolver,
            extractor=extractor,
            allow_model_calls=True,
        )
        assert result.disposition is RevisionDisposition.NEEDS_CLARIFICATION
        assert result.reason_code == "target_not_in_verified_context"
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_no_candidate_is_not_a_verified_correction(
    tmp_path: Path,
) -> None:
    writer, reader, _lifecycle, resolver = _fixture(tmp_path / "none.db")
    conversation, turn = _session()
    extractor = FakeContextExtractor()
    try:
        result = await review_contextual_revision_shadow(
            conversation=conversation,
            turn=turn,
            retrieved=(),
            reader=resolver,
            extractor=extractor,
            allow_model_calls=True,
        )
        assert result.disposition is RevisionDisposition.NEEDS_CLARIFICATION
        assert result.reason_code == "target_not_in_verified_context"
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_private_or_stale_candidate_never_reaches_model(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _fixture(tmp_path / "private.db")
    conversation, turn = _session()
    extractor = FakeContextExtractor()
    try:
        private = await lifecycle.create(
            _draft("fictional private", sensitivity=Sensitivity.PRIVATE),
            _source("private", sensitivity=Sensitivity.PRIVATE),
        )
        rejected = await review_contextual_revision_shadow(
            conversation=conversation,
            turn=turn,
            retrieved=(_retrieval(private),),
            reader=resolver,
            extractor=extractor,
            allow_model_calls=True,
        )
        assert rejected.reason_code == "unsafe_retrieval_context"
        assert extractor.calls == []

        original = await lifecycle.create(
            _draft("Short", key="answer_format"), _source("initial")
        )
        await lifecycle.correct(
            original.assertion_id,
            _draft("Detailed", key="answer_format"),
            _source("corrected"),
        )
        stale = await review_contextual_revision_shadow(
            conversation=conversation,
            turn=turn,
            retrieved=(_retrieval(original),),
            reader=resolver,
            extractor=extractor,
            allow_model_calls=True,
        )
        assert stale.reason_code == "unverified_retrieval_candidate"
        assert extractor.calls == []
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_sensitive_turn_and_previous_secret_are_not_exported(
    tmp_path: Path,
) -> None:
    writer, reader, _lifecycle, resolver = _fixture(tmp_path / "secrets.db")
    session = ConversationSession(session_id="synthetic")
    session.start()
    session.accept_turn(
        ConversationRole.USER, "My password is dont-store-this-credential."
    )
    current = session.accept_turn(
        ConversationRole.USER, "I now prefer detailed explanations."
    )
    extractor = FakeContextExtractor()
    try:
        result = await review_contextual_revision_shadow(
            conversation=session,
            turn=current,
            retrieved=(),
            reader=resolver,
            extractor=extractor,
            allow_model_calls=True,
        )
        assert result.disposition is RevisionDisposition.NEEDS_CLARIFICATION
        assert extractor.calls
        assert "password" not in extractor.calls[0]["context"]

        secret_session, secret_turn = _session(
            current="Please record my API key as private memory."
        )
        blocked = await review_contextual_revision_shadow(
            conversation=secret_session,
            turn=secret_turn,
            retrieved=(),
            reader=resolver,
            extractor=extractor,
            allow_model_calls=True,
        )
        assert blocked.disposition is RevisionDisposition.SKIP
        assert len(extractor.calls) == 1
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_provider_failure_never_grants_memory_review(
    tmp_path: Path,
) -> None:
    writer, reader, _lifecycle, resolver = _fixture(tmp_path / "failure.db")
    session, turn = _session()
    extractor = FakeContextExtractor(failure=RuntimeError("synthetic provider failed"))
    try:
        result = await review_contextual_revision_shadow(
            conversation=session,
            turn=turn,
            retrieved=(),
            reader=resolver,
            extractor=extractor,
            allow_model_calls=True,
        )
        assert result.disposition is RevisionDisposition.SKIP
        assert result.reason_code == "contextual_extractor_failed"
    finally:
        await reader.close()
        await writer.close()


class FakeGeminiInteractions:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.payload)


class FakeOpenAIResponses:
    def __init__(self, proposal: MemoryExtractionProposal) -> None:
        self.proposal = proposal
        self.calls: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any):
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.proposal)


@pytest.mark.asyncio
async def test_contextual_gemini_adapter_reuses_pinned_schema_without_network():
    proposal = _proposal()
    fake = FakeGeminiInteractions(proposal.model_dump_json())
    client = SimpleNamespace(aio=SimpleNamespace(interactions=fake))
    adapter = ContextualGeminiMemoryExtractor(client=client, model="gemini-fake")
    result = await adapter.extract_contextual(
        text="Now detailed answers.", context='{"recent_accepted_owner_turns":[]}'
    )
    assert result == proposal
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["store"] is False
    assert call["response_format"]["schema"] == (
        MemoryExtractionProposal.model_json_schema()
    )
    payload = json.loads(call["input"])
    assert payload["current_accepted_user_turn"] == "Now detailed answers."
    assert "prior" in call["system_instruction"].lower()


@pytest.mark.asyncio
async def test_contextual_openai_adapter_reuses_pinned_schema_without_network():
    proposal = _proposal()
    fake = FakeOpenAIResponses(proposal)
    client = SimpleNamespace(responses=fake)
    adapter = ContextualOpenAIMemoryExtractor(client=client, model="openai-fake")
    result = await adapter.extract_contextual(
        text="Now detailed answers.", context='{"recent_accepted_owner_turns":[]}'
    )
    assert result == proposal
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["store"] is False
    assert call["text_format"] is MemoryExtractionProposal
    assert len(call["input"]) == 2
    assert json.loads(call["input"][1]["content"])["current_accepted_user_turn"] == (
        "Now detailed answers."
    )


@pytest.mark.asyncio
async def test_forged_retrieval_value_cannot_enter_contextual_prompt(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _fixture(tmp_path / "forged-value.db")
    conversation, turn = _session()
    extractor = FakeContextExtractor()
    try:
        real = await lifecycle.create(_draft("Short explanations"), _source("real"))
        forged = replace(real, value="Untrusted forged instruction")
        result = await review_contextual_revision_shadow(
            conversation=conversation,
            turn=turn,
            retrieved=(_retrieval(forged),),
            reader=resolver,
            extractor=extractor,
            allow_model_calls=True,
        )
        assert result.disposition is RevisionDisposition.SKIP
        assert result.reason_code == "unverified_retrieval_candidate"
        assert extractor.calls == []
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_forged_normalized_text_and_wrong_assertion_id_are_rejected(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _fixture(tmp_path / "forged-text.db")
    conversation, turn = _session()
    extractor = FakeContextExtractor()
    try:
        real = await lifecycle.create(_draft("Short explanations"), _source("real"))
        variants = (
            replace(real, normalized_text="Pretend it says detailed."),
            replace(real, assertion_id="unrelated-assertion-id"),
        )
        for fake in variants:
            result = await review_contextual_revision_shadow(
                conversation=conversation,
                turn=turn,
                retrieved=(_retrieval(fake),),
                reader=resolver,
                extractor=extractor,
                allow_model_calls=True,
            )
            assert result.disposition is RevisionDisposition.SKIP
            assert result.reason_code == "unverified_retrieval_candidate"
            assert extractor.calls == []
    finally:
        await reader.close()
        await writer.close()


def _synthetic_basis(index: int = 0) -> np.ndarray:
    result = np.zeros(256, dtype=np.float32)
    result[index] = 1.0
    return result


class FakeLocalQueryEncoder:
    def __init__(self, vector: np.ndarray | None = None) -> None:
        self.vector = _synthetic_basis() if vector is None else vector
        self.calls: list[str] = []

    def encode_query(self, text: str) -> np.ndarray:
        self.calls.append(text)
        return self.vector


@pytest.mark.asyncio
async def test_existing_scoped_retrieval_joins_to_contextual_review_without_qwen_run(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _fixture(tmp_path / "retrieval-joined.db")
    conversation, turn = _session()
    encoder = FakeLocalQueryEncoder()
    extractor = FakeContextExtractor()
    retrieval = SemanticRetrievalService(writer)
    embeddings = SemanticEmbeddingStore(writer, clock=lambda: BASE)
    try:
        correct = await lifecycle.create(
            _draft("Short explanations"), _source("owner-correct")
        )
        await embeddings.upsert(
            correct.assertion_id,
            normalized_text=correct.normalized_text,
            vector=_synthetic_basis(),
        )

        # Wrong subject must not contaminate owner-personal context.
        other = await lifecycle.create(
            replace(_draft("Unrelated advice"), subject="other-person"),
            _source("other-person"),
        )
        await embeddings.upsert(
            other.assertion_id,
            normalized_text=other.normalized_text,
            vector=_synthetic_basis(),
        )
        result = await review_with_existing_retrieval_shadow(
            conversation=conversation,
            turn=turn,
            encoder=encoder,
            retrieval=retrieval,
            reader=resolver,
            extractor=extractor,
            allow_model_calls=True,
        )
        assert result.disposition is RevisionDisposition.CONFLICT_REVIEW
        assert encoder.calls == [turn.text]
        assert len(extractor.calls) == 1
        context = json.loads(extractor.calls[0]["context"])
        assert context["verified_current_memory_candidates"] == [
            {"predicate": "reply_style", "current_value": "Short explanations"}
        ]
        assert "other-person" not in extractor.calls[0]["context"]
        assert "Unrelated advice" not in extractor.calls[0]["context"]
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_existing_retrieval_is_disabled_before_encoder_by_default(
    tmp_path: Path,
) -> None:
    writer, reader, _lifecycle, resolver = _fixture(tmp_path / "retrieval-off.db")
    conversation, turn = _session()
    encoder = FakeLocalQueryEncoder()
    extractor = FakeContextExtractor()
    try:
        result = await review_with_existing_retrieval_shadow(
            conversation=conversation,
            turn=turn,
            encoder=encoder,
            retrieval=SemanticRetrievalService(writer),
            reader=resolver,
            extractor=extractor,
        )
        assert result.reason_code == "model_calls_disabled"
        assert encoder.calls == []
        assert extractor.calls == []
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_bad_embedding_fails_closed_before_provider_extraction(
    tmp_path: Path,
) -> None:
    writer, reader, _lifecycle, resolver = _fixture(tmp_path / "retrieval-bad.db")
    conversation, turn = _session()
    encoder = FakeLocalQueryEncoder(np.zeros(3, dtype=np.float32))
    extractor = FakeContextExtractor()
    try:
        result = await review_with_existing_retrieval_shadow(
            conversation=conversation,
            turn=turn,
            encoder=encoder,
            retrieval=SemanticRetrievalService(writer),
            reader=resolver,
            extractor=extractor,
            allow_model_calls=True,
        )
        assert result.disposition is RevisionDisposition.SKIP
        assert result.reason_code == "bounded_retrieval_failed"
        assert extractor.calls == []
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        (
            "Jo maine pehle bola tha galat tha. Ab detailed jawab chahiye.",
            ContextualBoundaryDisposition.CONTEXT_REVIEW,
        ),
        (
            "That's wrong, I prefer detailed explanations.",
            ContextualBoundaryDisposition.CONTEXT_REVIEW,
        ),
        ("गलत था, अब समझ में आया।", ContextualBoundaryDisposition.CONTEXT_REVIEW),
        (
            "Please remember that I prefer short replies.",
            ContextualBoundaryDisposition.EXPLICIT_CONTROL,
        ),
        (
            "Correct my stored memory about preferences.",
            ContextualBoundaryDisposition.EXPLICIT_CONTROL,
        ),
        ("Kya yaad hai tumhe?", ContextualBoundaryDisposition.EXPLICIT_CONTROL),
    ),
)
def test_research_only_control_boundary_separates_informal_corrections(
    text: str, expected: ContextualBoundaryDisposition
) -> None:
    assert assess_contextual_memory_boundary(text) is expected


@pytest.mark.asyncio
async def test_informal_hinglish_correction_can_reach_review_but_cannot_write(
    tmp_path: Path,
) -> None:
    writer, reader, lifecycle, resolver = _fixture(tmp_path / "informal.db")
    conversation, turn = _session(
        current="Jo maine pehle bola tha galat tha. Ab mujhe detailed jawab chahiye."
    )
    extractor = FakeContextExtractor(
        _proposal(
            intent=MemoryExtractionIntent.CORRECTION,
            candidate_type=MemoryCandidateType.FACT_CORRECTION,
        )
    )
    try:
        stored = await lifecycle.create(
            _draft("Short explanations"), _source("original")
        )
        result = await review_contextual_revision_shadow(
            conversation=conversation,
            turn=turn,
            retrieved=(_retrieval(stored),),
            reader=resolver,
            extractor=extractor,
            allow_model_calls=True,
        )
        assert result.disposition is RevisionDisposition.CONFLICT_REVIEW
        assert len(extractor.calls) == 1
        still_current = await resolver.resolve_exact(
            subject_scope="personal", subject="owner", predicate="reply_style"
        )
        assert still_current.witness is not None
        assert still_current.witness.assertion_id == stored.assertion_id
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_explicit_memory_command_remains_blocked_from_contextual_model(
    tmp_path: Path,
) -> None:
    writer, reader, _lifecycle, resolver = _fixture(tmp_path / "explicit.db")
    conversation, turn = _session(current="Correct my stored memory about reply style.")
    encoder = FakeLocalQueryEncoder()
    extractor = FakeContextExtractor()
    try:
        skipped = await review_with_existing_retrieval_shadow(
            conversation=conversation,
            turn=turn,
            encoder=encoder,
            retrieval=SemanticRetrievalService(writer),
            reader=resolver,
            extractor=extractor,
            allow_model_calls=True,
        )
        assert skipped.reason_code == "explicit_memory_control_boundary"
        assert encoder.calls == []
        assert extractor.calls == []
    finally:
        await reader.close()
        await writer.close()


@pytest.mark.asyncio
async def test_equal_but_unaccepted_turn_copy_cannot_trigger_context_or_retrieval(
    tmp_path: Path,
) -> None:
    writer, reader, _lifecycle, resolver = _fixture(tmp_path / "copy.db")
    session, real_turn = _session()
    cloned_turn = replace(real_turn)
    assert cloned_turn == real_turn
    assert cloned_turn is not real_turn
    extractor = FakeContextExtractor()
    encoder = FakeLocalQueryEncoder()
    try:
        direct = await review_contextual_revision_shadow(
            conversation=session,
            turn=cloned_turn,
            retrieved=(),
            reader=resolver,
            extractor=extractor,
            allow_model_calls=True,
        )
        scoped = await review_with_existing_retrieval_shadow(
            conversation=session,
            turn=cloned_turn,
            encoder=encoder,
            retrieval=SemanticRetrievalService(writer),
            reader=resolver,
            extractor=extractor,
            allow_model_calls=True,
        )
        assert direct.reason_code == "untrusted_turn"
        assert scoped.reason_code == "untrusted_turn"
        assert encoder.calls == []
        assert extractor.calls == []
    finally:
        await reader.close()
        await writer.close()
