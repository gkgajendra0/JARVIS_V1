from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np

from .worker import SerialConnectionWorker

QWEN3_EMBEDDING_MODEL_ID = "Qwen/Qwen3-Embedding-0.6B"
QWEN3_EMBEDDING_REVISION = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
QWEN3_EMBEDDING_DIMENSION = 256
JARVIS_MEMORY_RETRIEVAL_INSTRUCTION = (
    "Instruct: Given a JARVIS memory retrieval query, retrieve the most relevant "
    "trustworthy personal, episodic, project, or self-knowledge memory needed to "
    "answer the query\nQuery:"
)

_REVISION = re.compile(r"^[0-9a-f]{40}$")
_FLOAT32_LE = np.dtype("<f4")
_FLOAT32_BYTES = _FLOAT32_LE.itemsize


class EmbeddingStorageError(RuntimeError):
    pass


class EmbeddingContractError(EmbeddingStorageError):
    pass


class EmbeddingDataError(EmbeddingStorageError):
    pass


@dataclass(frozen=True, slots=True)
class EmbeddingContract:
    model_id: str
    model_revision: str
    dimension: int
    dtype: str = "float32"
    byte_order: str = "little"
    normalized: bool = True

    def __post_init__(self) -> None:
        model_id = self.model_id.strip()
        revision = self.model_revision.strip().casefold()
        if not model_id:
            raise EmbeddingContractError("embedding model_id must not be empty")
        if not _REVISION.fullmatch(revision):
            raise EmbeddingContractError(
                "embedding model_revision must be a full 40-character commit hash"
            )
        if isinstance(self.dimension, bool) or not isinstance(self.dimension, int):
            raise EmbeddingContractError("embedding dimension must be an integer")
        if self.dimension <= 0:
            raise EmbeddingContractError("embedding dimension must be positive")
        if self.dtype != "float32":
            raise EmbeddingContractError("only float32 embedding storage is supported")
        if self.byte_order != "little":
            raise EmbeddingContractError(
                "only little-endian embedding storage is supported"
            )
        if not isinstance(self.normalized, bool):
            raise EmbeddingContractError("embedding normalized flag must be boolean")
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_revision", revision)

    @property
    def expected_bytes(self) -> int:
        return self.dimension * _FLOAT32_BYTES


QWEN3_EMBEDDING_CONTRACT = EmbeddingContract(
    model_id=QWEN3_EMBEDDING_MODEL_ID,
    model_revision=QWEN3_EMBEDDING_REVISION,
    dimension=QWEN3_EMBEDDING_DIMENSION,
)


@dataclass(frozen=True, slots=True)
class StoredEmbedding:
    assertion_id: str
    contract: EmbeddingContract
    content_sha256: str
    vector: np.ndarray
    created_at: datetime
    updated_at: datetime



def embedding_content_sha256(normalized_text: str) -> str:
    if not isinstance(normalized_text, str):
        raise TypeError("normalized_text must be a string")
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()



def serialize_embedding(
    vector: Sequence[float] | np.ndarray,
    *,
    contract: EmbeddingContract = QWEN3_EMBEDDING_CONTRACT,
) -> bytes:
    try:
        array = np.asarray(vector, dtype=_FLOAT32_LE)
    except (TypeError, ValueError) as exc:
        raise EmbeddingDataError("embedding vector must be numeric") from exc
    if array.ndim != 1:
        raise EmbeddingDataError("embedding vector must be one-dimensional")
    if array.shape[0] != contract.dimension:
        raise EmbeddingDataError(
            f"embedding vector dimension {array.shape[0]} does not match "
            f"contract dimension {contract.dimension}"
        )
    if not np.all(np.isfinite(array)):
        raise EmbeddingDataError("embedding vector must contain only finite values")
    contiguous = np.ascontiguousarray(array, dtype=_FLOAT32_LE)
    payload = contiguous.tobytes(order="C")
    if len(payload) != contract.expected_bytes:
        raise EmbeddingDataError("serialized embedding byte length is invalid")
    return payload



def deserialize_embedding(
    payload: bytes | bytearray | memoryview,
    *,
    contract: EmbeddingContract = QWEN3_EMBEDDING_CONTRACT,
) -> np.ndarray:
    raw = bytes(payload)
    if len(raw) != contract.expected_bytes:
        raise EmbeddingDataError(
            f"embedding BLOB is {len(raw)} bytes; expected {contract.expected_bytes}"
        )
    vector = np.frombuffer(raw, dtype=_FLOAT32_LE, count=contract.dimension).copy()
    if vector.shape != (contract.dimension,):
        raise EmbeddingDataError("embedding BLOB decoded to an invalid shape")
    if not np.all(np.isfinite(vector)):
        raise EmbeddingDataError("embedding BLOB contains non-finite values")
    return vector



def _now() -> datetime:
    return datetime.now(UTC)



def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError("embedding clock must return a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("embedding clock must return a timezone-aware datetime")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")



def _parse_timestamp(value: str) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EmbeddingDataError("stored embedding timestamp is not timezone-aware")
    return parsed.astimezone(UTC)



def _assertion_id(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("assertion_id must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError("assertion_id must not be empty")
    return normalized


class SemanticEmbeddingStore:
    """Stores rebuildable derived vectors inside the canonical SQLCipher database."""

    def __init__(
        self,
        worker: SerialConnectionWorker,
        *,
        contract: EmbeddingContract = QWEN3_EMBEDDING_CONTRACT,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._worker = worker
        self._contract = contract
        self._clock = clock

    @property
    def contract(self) -> EmbeddingContract:
        return self._contract

    async def upsert(
        self,
        assertion_id: str,
        *,
        normalized_text: str,
        vector: Sequence[float] | np.ndarray,
    ) -> StoredEmbedding:
        target = _assertion_id(assertion_id)
        fingerprint = embedding_content_sha256(normalized_text)
        payload = serialize_embedding(vector, contract=self._contract)
        timestamp = _timestamp(self._clock())
        return await self._worker.run(
            lambda connection: self._upsert_sync(
                connection,
                target,
                fingerprint,
                payload,
                timestamp,
            )
        )

    async def get(self, assertion_id: str) -> StoredEmbedding | None:
        target = _assertion_id(assertion_id)
        return await self._worker.run(
            lambda connection: self._get_sync(connection, target)
        )

    async def is_current(
        self,
        assertion_id: str,
        *,
        normalized_text: str,
    ) -> bool:
        target = _assertion_id(assertion_id)
        fingerprint = embedding_content_sha256(normalized_text)
        return await self._worker.run(
            lambda connection: self._is_current_sync(
                connection,
                target,
                fingerprint,
            )
        )

    def _upsert_sync(
        self,
        connection: Any,
        assertion_id: str,
        content_sha256: str,
        payload: bytes,
        timestamp: str,
    ) -> StoredEmbedding:
        contract = self._contract
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO semantic_assertion_embedding (
                    assertion_id,
                    model_id,
                    model_revision,
                    dimension,
                    dtype,
                    byte_order,
                    normalized,
                    content_sha256,
                    embedding_blob,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(assertion_id) DO UPDATE SET
                    model_id = excluded.model_id,
                    model_revision = excluded.model_revision,
                    dimension = excluded.dimension,
                    dtype = excluded.dtype,
                    byte_order = excluded.byte_order,
                    normalized = excluded.normalized,
                    content_sha256 = excluded.content_sha256,
                    embedding_blob = excluded.embedding_blob,
                    updated_at = excluded.updated_at
                """,
                (
                    assertion_id,
                    contract.model_id,
                    contract.model_revision,
                    contract.dimension,
                    contract.dtype,
                    contract.byte_order,
                    int(contract.normalized),
                    content_sha256,
                    payload,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        record = self._get_sync(connection, assertion_id)
        if record is None:
            raise EmbeddingStorageError("embedding upsert committed but row is missing")
        return record

    def _get_sync(self, connection: Any, assertion_id: str) -> StoredEmbedding | None:
        row = connection.execute(
            """
            SELECT
                assertion_id,
                model_id,
                model_revision,
                dimension,
                dtype,
                byte_order,
                normalized,
                content_sha256,
                embedding_blob,
                created_at,
                updated_at
            FROM semantic_assertion_embedding
            WHERE assertion_id = ?
            """,
            (assertion_id,),
        ).fetchone()
        if row is None:
            return None
        contract = EmbeddingContract(
            model_id=str(row[1]),
            model_revision=str(row[2]),
            dimension=int(row[3]),
            dtype=str(row[4]),
            byte_order=str(row[5]),
            normalized=bool(row[6]),
        )
        content_sha256 = str(row[7])
        if len(content_sha256) != 64 or not all(
            char in "0123456789abcdef" for char in content_sha256.casefold()
        ):
            raise EmbeddingDataError("stored embedding content_sha256 is invalid")
        return StoredEmbedding(
            assertion_id=str(row[0]),
            contract=contract,
            content_sha256=content_sha256.casefold(),
            vector=deserialize_embedding(row[8], contract=contract),
            created_at=_parse_timestamp(str(row[9])),
            updated_at=_parse_timestamp(str(row[10])),
        )

    def _is_current_sync(
        self,
        connection: Any,
        assertion_id: str,
        content_sha256: str,
    ) -> bool:
        row = connection.execute(
            """
            SELECT
                model_id,
                model_revision,
                dimension,
                dtype,
                byte_order,
                normalized,
                content_sha256,
                length(embedding_blob)
            FROM semantic_assertion_embedding
            WHERE assertion_id = ?
            """,
            (assertion_id,),
        ).fetchone()
        if row is None:
            return False
        contract = self._contract
        return (
            str(row[0]) == contract.model_id
            and str(row[1]).casefold() == contract.model_revision
            and int(row[2]) == contract.dimension
            and str(row[3]) == contract.dtype
            and str(row[4]) == contract.byte_order
            and bool(row[5]) is contract.normalized
            and str(row[6]).casefold() == content_sha256
            and int(row[7]) == contract.expected_bytes
        )
