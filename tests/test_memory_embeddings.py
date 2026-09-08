from __future__ import annotations

import itertools
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from jarvis.memory.assertions import SemanticAssertionDraft
from jarvis.memory.embeddings import (
    QWEN3_EMBEDDING_CONTRACT,
    EmbeddingContract,
    EmbeddingContractError,
    EmbeddingDataError,
    SemanticEmbeddingStore,
    deserialize_embedding,
    embedding_content_sha256,
    serialize_embedding,
)
from jarvis.memory.lifecycle import MemoryLifecycleService
from jarvis.memory.migration_runner import MemoryMigrationRunner
from jarvis.memory.provenance import MemorySource
from jarvis.memory.types import (
    AuthorityClass,
    FreshnessClass,
    MemorySourceClass,
    Sensitivity,
    ValueType,
)
from jarvis.memory.worker import SerialConnectionWorker

BASE = datetime(2026, 9, 5, 18, 0, tzinfo=UTC)


def worker_for(path: Path) -> SerialConnectionWorker:
    def connection_factory() -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA secure_delete = ON")
        MemoryMigrationRunner(clock=lambda: BASE).apply(connection)
        return connection

    return SerialConnectionWorker(
        connection_factory,
        thread_name="jarvis-memory-embedding-test",
    )


def id_factory(prefix: str):
    values = itertools.count(1)
    return lambda: f"{prefix}-{next(values)}"


def source(source_id: str) -> MemorySource:
    return MemorySource(
        source_id=source_id,
        source_class=MemorySourceClass.OWNER_EXPLICIT,
        canonical_ref=f"conversation:session-embedding:{source_id}",
        observed_at=BASE,
        authority_class=AuthorityClass.OWNER_EXPLICIT,
        sensitivity=Sensitivity.STANDARD,
        created_at=BASE,
    )


def draft(marker: str = "favorite wild bird falcon") -> SemanticAssertionDraft:
    return SemanticAssertionDraft(
        subject_scope="owner",
        subject="owner",
        predicate="favorite_wild_bird",
        value_type=ValueType.TEXT,
        value="falcon",
        normalized_text=marker,
        freshness_class=FreshnessClass.STABLE,
        sensitivity=Sensitivity.STANDARD,
    )


def vector() -> np.ndarray:
    values = np.linspace(-1.0, 1.0, QWEN3_EMBEDDING_CONTRACT.dimension)
    return values.astype(np.float32)


def test_embedding_contract_requires_immutable_full_revision() -> None:
    with pytest.raises(EmbeddingContractError, match="full 40-character"):
        EmbeddingContract(
            model_id="Qwen/Qwen3-Embedding-0.6B",
            model_revision="main",
            dimension=256,
        )


def test_embedding_codec_roundtrips_little_endian_float32() -> None:
    original = vector()

    payload = serialize_embedding(original)
    restored = deserialize_embedding(payload)

    assert len(payload) == 1024
    assert restored.dtype == np.dtype("float32")
    np.testing.assert_array_equal(restored, original)
    little_endian_view = np.frombuffer(payload, dtype="<f4")
    np.testing.assert_array_equal(little_endian_view, original)


def test_embedding_codec_rejects_wrong_shape_and_nonfinite_values() -> None:
    with pytest.raises(EmbeddingDataError, match="dimension"):
        serialize_embedding(np.zeros(255, dtype=np.float32))

    bad = vector()
    bad[10] = np.nan
    with pytest.raises(EmbeddingDataError, match="finite"):
        serialize_embedding(bad)

    with pytest.raises(EmbeddingDataError, match="expected 1024"):
        deserialize_embedding(bytes(4))


def test_content_fingerprint_is_exact_utf8_sha256() -> None:
    first = embedding_content_sha256("सागर Jimny")
    second = embedding_content_sha256("सागर Jimny")
    changed = embedding_content_sha256("सागर jimny")

    assert len(first) == 64
    assert first == second
    assert changed != first


@pytest.mark.asyncio
async def test_store_roundtrip_and_stale_detection(tmp_path: Path) -> None:
    worker = worker_for(tmp_path / "embedding.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=id_factory("assertion"),
        operation_id_factory=id_factory("operation"),
    )
    store = SemanticEmbeddingStore(worker, clock=lambda: BASE)
    try:
        assertion = await lifecycle.create(draft(), source("create-source"))
        saved = await store.upsert(
            assertion.assertion_id,
            normalized_text=assertion.normalized_text,
            vector=vector(),
        )

        assert saved.assertion_id == assertion.assertion_id
        assert saved.contract == QWEN3_EMBEDDING_CONTRACT
        np.testing.assert_array_equal(saved.vector, vector())
        assert await store.is_current(
            assertion.assertion_id,
            normalized_text=assertion.normalized_text,
        )
        assert not await store.is_current(
            assertion.assertion_id,
            normalized_text="changed canonical representation",
        )

        other_contract = EmbeddingContract(
            model_id=QWEN3_EMBEDDING_CONTRACT.model_id,
            model_revision="b" * 40,
            dimension=QWEN3_EMBEDDING_CONTRACT.dimension,
        )
        other_store = SemanticEmbeddingStore(
            worker,
            contract=other_contract,
            clock=lambda: BASE,
        )
        assert not await other_store.is_current(
            assertion.assertion_id,
            normalized_text=assertion.normalized_text,
        )
    finally:
        await worker.close()


@pytest.mark.asyncio
async def test_canonical_forget_physically_removes_derived_embedding(
    tmp_path: Path,
) -> None:
    worker = worker_for(tmp_path / "forget.db")
    lifecycle = MemoryLifecycleService(
        worker,
        clock=lambda: BASE,
        assertion_id_factory=id_factory("assertion"),
        operation_id_factory=id_factory("operation"),
    )
    store = SemanticEmbeddingStore(worker, clock=lambda: BASE)
    try:
        assertion = await lifecycle.create(draft(), source("create-source"))
        await store.upsert(
            assertion.assertion_id,
            normalized_text=assertion.normalized_text,
            vector=vector(),
        )
        assert await store.get(assertion.assertion_id) is not None

        forgotten = await lifecycle.forget(
            assertion.assertion_id,
            source("forget-source"),
        )

        assert forgotten is True
        assert await lifecycle.get(assertion.assertion_id) is None
        assert await store.get(assertion.assertion_id) is None
        vector_rows = await worker.run(
            lambda connection: connection.execute(
                "SELECT count(*) FROM semantic_assertion_embedding"
            ).fetchone()[0]
        )
        assert vector_rows == 0
    finally:
        await worker.close()
