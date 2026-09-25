"""Local-first EngineeringKnowledge indexing and retrieval.

Canonical EngineeringKnowledge stays in the engineering SQLite schema. Search documents,
FTS rows and embeddings are derived, replaceable indexes that can be rebuilt.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Protocol

import numpy as np

from jarvis.engineering_knowledge.applicability import (
    ApplicabilityContext,
    ApplicabilityDecision,
    EngineeringKnowledgeApplicabilityService,
)
from jarvis.engineering_knowledge.defaults import build_default_facet_registry
from jarvis.engineering_knowledge.models import (
    AttestationVerdict,
    EngineeringApplicability,
    EngineeringAttestation,
    EngineeringEvidence,
    EngineeringKnowledgeFacet,
    EngineeringKnowledgeRevision,
    KnowledgeFreshnessState,
    KnowledgeSensitivity,
)
from jarvis.engineering_knowledge.security import (
    EngineeringEvidenceAdmissionGate,
    EngineeringKnowledgeIntegrityVerifier,
    EvidenceAdmissionRequest,
)
from jarvis.incidents.migration_runner import EngineeringMigrationRunner
from jarvis.memory.embeddings import (
    QWEN3_EMBEDDING_CONTRACT,
    EmbeddingContract,
    deserialize_embedding,
    serialize_embedding,
)
from jarvis.memory.retrieval import build_fts5_query, reciprocal_rank_fuse
from jarvis.memory.retrieval_models import (
    LocalRetrievalModelError,
    Qwen3EmbeddingEncoder,
)

JARVIS_ENGINEERING_RETRIEVAL_INSTRUCTION = (
    "Instruct: Given a JARVIS engineering query, retrieve the most relevant "
    "verified engineering knowledge applicable to the current component, version, "
    "device, dependency, protocol, or environment\nQuery:"
)

_DEFAULT_LOCAL_SENSITIVITIES = frozenset(
    {
        KnowledgeSensitivity.STANDARD,
        KnowledgeSensitivity.PRIVATE,
        KnowledgeSensitivity.LOCAL_ONLY,
    }
)
_DEFAULT_FTS_WINDOW = 20
_DEFAULT_DENSE_WINDOW = 20
_DEFAULT_RRF_K = 60


class EngineeringKnowledgeRetrievalError(RuntimeError):
    """Base error for EngineeringKnowledge indexing/retrieval."""


class EngineeringKnowledgeRetrievalQueryError(EngineeringKnowledgeRetrievalError):
    """The retrieval query violates the deterministic contract."""


@dataclass(frozen=True, slots=True)
class EngineeringKnowledgeRetrievalPolicy:
    sensitivities: frozenset[KnowledgeSensitivity]

    def __post_init__(self) -> None:
        if not isinstance(self.sensitivities, frozenset) or not all(
            isinstance(value, KnowledgeSensitivity) for value in self.sensitivities
        ):
            raise TypeError("sensitivities must be a frozenset[KnowledgeSensitivity]")

    @classmethod
    def local(cls) -> EngineeringKnowledgeRetrievalPolicy:
        return cls(sensitivities=_DEFAULT_LOCAL_SENSITIVITIES)

    @classmethod
    def external_context(cls) -> EngineeringKnowledgeRetrievalPolicy:
        """Conservative policy for material leaving the local JARVIS boundary."""

        return cls(sensitivities=frozenset({KnowledgeSensitivity.STANDARD}))


@dataclass(frozen=True, slots=True)
class EngineeringKnowledgeIndexResult:
    revision_id: str
    content_sha256: str
    indexed: bool
    embedding_indexed: bool
    embedding_reason: str


@dataclass(frozen=True, slots=True)
class EngineeringKnowledgeEvidenceSummary:
    evidence_id: str
    relation_type: str
    evidence_type: str
    source_class: str
    canonical_reference: str
    summary: str


@dataclass(frozen=True, slots=True)
class EngineeringKnowledgeRetrievalCandidate:
    revision: EngineeringKnowledgeRevision
    searchable_text: str
    rank: int
    fused_score: float
    exact_rank: int | None
    lexical_rank: int | None
    lexical_score: float | None
    dense_rank: int | None
    dense_score: float | None
    applicability: ApplicabilityDecision
    evidence: tuple[EngineeringKnowledgeEvidenceSummary, ...]
    attestations: tuple[EngineeringAttestation, ...]


class EngineeringKnowledgeIndexEncoder(Protocol):
    @property
    def contract(self) -> EmbeddingContract: ...

    def encode_query(self, text: str) -> np.ndarray: ...

    def encode_documents(self, texts: tuple[str, ...]) -> tuple[np.ndarray, ...]: ...


def build_engineering_qwen_encoder(
    *,
    device: str | None = "cuda",
    contract: EmbeddingContract = QWEN3_EMBEDDING_CONTRACT,
) -> Qwen3EmbeddingEncoder:
    """Build the existing pinned Qwen adapter with an engineering-specific prompt."""

    return Qwen3EmbeddingEncoder(
        device=device,
        contract=contract,
        query_instruction=JARVIS_ENGINEERING_RETRIEVAL_INSTRUCTION,
    )


class EngineeringKnowledgeRetrievalIndex:
    """Independent derived-index connection over the canonical engineering DB."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._lock = RLock()
        EngineeringMigrationRunner().apply(self._connection)
        self._facet_registry = build_default_facet_registry()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def get_engineering_knowledge_revision(
        self,
        revision_id: str,
    ) -> EngineeringKnowledgeRevision | None:
        normalized = _required_text(revision_id, "revision_id")
        with self._lock:
            cursor = self._connection.execute(
                """
                SELECT *
                FROM engineering_knowledge_revision
                WHERE revision_id = ?
                """,
                (normalized,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            columns = [item[0] for item in cursor.description or ()]
        return _revision_from_row(dict(zip(columns, row, strict=True)))

    def list_engineering_knowledge_facets(
        self,
        revision_id: str,
    ) -> tuple[EngineeringKnowledgeFacet, ...]:
        normalized = _required_text(revision_id, "revision_id")
        with self._lock:
            cursor = self._connection.execute(
                """
                SELECT *
                FROM engineering_knowledge_facet
                WHERE revision_id = ?
                ORDER BY facet_type, schema_id, schema_version, facet_id
                """,
                (normalized,),
            )
            rows = cursor.fetchall()
            columns = [item[0] for item in cursor.description or ()]
        return tuple(
            _facet_from_row(dict(zip(columns, row, strict=True))) for row in rows
        )

    def list_engineering_knowledge_applicability(
        self,
        revision_id: str,
    ) -> tuple[EngineeringApplicability, ...]:
        normalized = _required_text(revision_id, "revision_id")
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT applicability_id, revision_id, target_namespace,
                       target_identity, matcher_type, constraint_json,
                       required, created_at_epoch
                FROM engineering_knowledge_applicability
                WHERE revision_id = ?
                ORDER BY target_namespace, target_identity, matcher_type,
                         applicability_id
                """,
                (normalized,),
            ).fetchall()
        return tuple(
            EngineeringApplicability(
                applicability_id=str(row[0]),
                revision_id=str(row[1]),
                target_namespace=str(row[2]),
                target_identity=str(row[3]),
                matcher_type=str(row[4]),
                constraint_json=str(row[5]),
                required=bool(row[6]),
                created_at_epoch=float(row[7]),
            )
            for row in rows
        )

    def list_engineering_knowledge_evidence(
        self,
        revision_id: str,
    ) -> tuple[EngineeringEvidence, ...]:
        normalized = _required_text(revision_id, "revision_id")
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT DISTINCT evidence.evidence_id, evidence.evidence_type,
                       evidence.source_class, evidence.canonical_reference,
                       evidence.summary, evidence.occurred_at_epoch,
                       evidence.observed_at_epoch, evidence.sensitivity,
                       evidence.producer, evidence.integrity_algorithm,
                       evidence.integrity_digest, evidence.created_at_epoch
                FROM engineering_knowledge_evidence_link AS link
                JOIN engineering_evidence AS evidence
                  ON evidence.evidence_id = link.evidence_id
                WHERE link.revision_id = ?
                ORDER BY evidence.canonical_reference, evidence.evidence_id
                """,
                (normalized,),
            ).fetchall()
        return tuple(
            EngineeringEvidence(
                evidence_id=str(row[0]),
                evidence_type=str(row[1]),
                source_class=str(row[2]),
                canonical_reference=str(row[3]),
                summary=str(row[4]),
                occurred_at_epoch=(float(row[5]) if row[5] is not None else None),
                observed_at_epoch=float(row[6]),
                sensitivity=KnowledgeSensitivity(str(row[7])),
                producer=str(row[8]),
                integrity_algorithm=(str(row[9]) if row[9] is not None else None),
                integrity_digest=(str(row[10]) if row[10] is not None else None),
                created_at_epoch=float(row[11]),
            )
            for row in rows
        )

    def list_engineering_attestations(
        self,
        *,
        subject_type: str,
        subject_id: str,
    ) -> tuple[EngineeringAttestation, ...]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT attestation_id, subject_type, subject_id, subject_digest,
                       predicate_type, producer, expected_contract_json,
                       observed_result_json, verdict, evidence_ids_json,
                       observed_at_epoch, created_at_epoch
                FROM engineering_attestation
                WHERE subject_type = ? AND subject_id = ?
                ORDER BY predicate_type, observed_at_epoch, attestation_id
                """,
                (str(subject_type).strip().casefold(), str(subject_id).strip()),
            ).fetchall()
        return tuple(
            EngineeringAttestation(
                attestation_id=str(row[0]),
                subject_type=str(row[1]),
                subject_id=str(row[2]),
                subject_digest=str(row[3]),
                predicate_type=str(row[4]),
                producer=str(row[5]),
                expected_contract_json=str(row[6]),
                observed_result_json=str(row[7]),
                verdict=AttestationVerdict(str(row[8])),
                evidence_ids=tuple(json.loads(str(row[9]))),
                observed_at_epoch=float(row[10]),
                created_at_epoch=float(row[11]),
            )
            for row in rows
        )

    def refresh_revision(
        self,
        revision_id: str,
        *,
        encoder: EngineeringKnowledgeIndexEncoder | None = None,
        now_epoch: float,
    ) -> EngineeringKnowledgeIndexResult:
        revision = self.get_engineering_knowledge_revision(revision_id)
        if revision is None:
            raise EngineeringKnowledgeRetrievalError(
                f"unknown knowledge revision: {revision_id}"
            )
        searchable_text = self._build_searchable_text(revision)
        content_sha256 = hashlib.sha256(searchable_text.encode("utf-8")).hexdigest()
        timestamp = _finite_epoch(now_epoch)

        with self._lock, self._connection:
            existing = self._connection.execute(
                """
                SELECT content_sha256
                FROM engineering_knowledge_search_document
                WHERE revision_id = ?
                """,
                (revision.revision_id,),
            ).fetchone()
            changed = existing is None or str(existing[0]) != content_sha256
            self._connection.execute(
                """
                INSERT INTO engineering_knowledge_search_document (
                    revision_id, searchable_text, content_sha256, updated_at_epoch
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(revision_id) DO UPDATE SET
                    searchable_text=excluded.searchable_text,
                    content_sha256=excluded.content_sha256,
                    updated_at_epoch=excluded.updated_at_epoch
                """,
                (
                    revision.revision_id,
                    searchable_text,
                    content_sha256,
                    timestamp,
                ),
            )
            self._connection.execute(
                "DELETE FROM engineering_knowledge_fts WHERE revision_id = ?",
                (revision.revision_id,),
            )
            self._connection.execute(
                """
                INSERT INTO engineering_knowledge_fts (
                    revision_id, searchable_text
                ) VALUES (?, ?)
                """,
                (revision.revision_id, searchable_text),
            )
            if changed:
                self._connection.execute(
                    """
                    DELETE FROM engineering_knowledge_embedding
                    WHERE revision_id = ? AND content_sha256 <> ?
                    """,
                    (revision.revision_id, content_sha256),
                )

        if encoder is None:
            return EngineeringKnowledgeIndexResult(
                revision_id=revision.revision_id,
                content_sha256=content_sha256,
                indexed=True,
                embedding_indexed=False,
                embedding_reason="encoder_not_configured",
            )

        try:
            vectors = encoder.encode_documents((searchable_text,))
        except (LocalRetrievalModelError, ImportError):
            return EngineeringKnowledgeIndexResult(
                revision_id=revision.revision_id,
                content_sha256=content_sha256,
                indexed=True,
                embedding_indexed=False,
                embedding_reason="encoder_unavailable",
            )
        if len(vectors) != 1:
            raise EngineeringKnowledgeRetrievalError(
                "embedding encoder must return exactly one document vector"
            )
        vector = _unit_vector(vectors[0], encoder.contract)
        self._upsert_embedding(
            revision.revision_id,
            content_sha256=content_sha256,
            vector=vector,
            contract=encoder.contract,
            now_epoch=timestamp,
        )
        return EngineeringKnowledgeIndexResult(
            revision_id=revision.revision_id,
            content_sha256=content_sha256,
            indexed=True,
            embedding_indexed=True,
            embedding_reason="indexed",
        )

    def rebuild_accepted(
        self,
        *,
        encoder: EngineeringKnowledgeIndexEncoder | None = None,
        now_epoch: float,
    ) -> tuple[EngineeringKnowledgeIndexResult, ...]:
        timestamp = _finite_epoch(now_epoch)
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT revision.revision_id
                FROM engineering_knowledge_revision AS revision
                JOIN engineering_knowledge_revision_state AS state
                  ON state.revision_id = revision.revision_id
                WHERE state.lifecycle_state = 'accepted'
                  AND revision.freshness_state = 'current'
                  AND revision.system_to_epoch IS NULL
                  AND (
                      revision.valid_from_epoch IS NULL
                      OR revision.valid_from_epoch <= ?
                  )
                  AND (
                      revision.valid_to_epoch IS NULL
                      OR revision.valid_to_epoch >= ?
                  )
                ORDER BY revision.revision_id
                """,
                (timestamp, timestamp),
            ).fetchall()
        return tuple(
            self.refresh_revision(
                str(row[0]),
                encoder=encoder,
                now_epoch=timestamp,
            )
            for row in rows
        )

    def retrieve(
        self,
        query_text: str,
        *,
        context: ApplicabilityContext,
        encoder: EngineeringKnowledgeIndexEncoder | None = None,
        policy: EngineeringKnowledgeRetrievalPolicy | None = None,
        now_epoch: float,
        limit: int = 5,
        fts_window: int = _DEFAULT_FTS_WINDOW,
        dense_window: int = _DEFAULT_DENSE_WINDOW,
        rank_constant: int = _DEFAULT_RRF_K,
    ) -> tuple[EngineeringKnowledgeRetrievalCandidate, ...]:
        query = _required_text(query_text, "query_text")
        if not isinstance(context, ApplicabilityContext):
            raise TypeError("context must be an ApplicabilityContext")
        _positive_int(limit, "limit")
        _positive_int(fts_window, "fts_window")
        _positive_int(dense_window, "dense_window")
        _positive_int(rank_constant, "rank_constant")
        timestamp = _finite_epoch(now_epoch)
        query_security = EngineeringEvidenceAdmissionGate().assess(
            EvidenceAdmissionRequest(
                source_class="external_research",
                content=query,
            )
        )
        if not query_security.admissible:
            return ()

        resolved_policy = policy or EngineeringKnowledgeRetrievalPolicy.local()
        if not isinstance(resolved_policy, EngineeringKnowledgeRetrievalPolicy):
            raise TypeError("policy must be an EngineeringKnowledgeRetrievalPolicy")

        eligible = self._eligible_revision_ids(
            context=context,
            policy=resolved_policy,
            now_epoch=timestamp,
        )
        if not eligible:
            return ()

        exact_ids = self._exact_ids(query, eligible)
        lexical_query = _query_without_applicability_identity_terms(query, context)
        lexical = self._lexical_rank(
            lexical_query,
            eligible,
            window=fts_window,
        )
        dense: list[tuple[str, float]] = []
        if encoder is not None:
            try:
                query_vector = _unit_vector(
                    encoder.encode_query(query),
                    encoder.contract,
                )
            except (LocalRetrievalModelError, ImportError):
                query_vector = None
            if query_vector is not None:
                dense = self._dense_rank(
                    query_vector,
                    eligible,
                    contract=encoder.contract,
                    window=dense_window,
                )

        lexical_ids = [revision_id for revision_id, _ in lexical]
        dense_ids = [revision_id for revision_id, _ in dense]
        fused = reciprocal_rank_fuse(
            lexical_ids,
            dense_ids,
            rank_constant=rank_constant,
        )
        fused_score = {item.assertion_id: item.fused_score for item in fused}
        lexical_rank = {
            revision_id: rank for rank, (revision_id, _) in enumerate(lexical, start=1)
        }
        lexical_score = dict(lexical)
        dense_rank = {
            revision_id: rank for rank, (revision_id, _) in enumerate(dense, start=1)
        }
        dense_score = dict(dense)
        exact_rank = {
            revision_id: rank for rank, revision_id in enumerate(exact_ids, start=1)
        }

        ordered: list[str] = list(exact_ids)
        ordered.extend(
            item.assertion_id for item in fused if item.assertion_id not in exact_rank
        )
        selected = ordered[:limit]
        output: list[EngineeringKnowledgeRetrievalCandidate] = []
        for rank, revision_id in enumerate(selected, start=1):
            revision = self.get_engineering_knowledge_revision(revision_id)
            if revision is None:
                continue
            document = self._search_document(revision_id)
            if document is None:
                continue
            applicability = eligible[revision_id]
            output.append(
                EngineeringKnowledgeRetrievalCandidate(
                    revision=revision,
                    searchable_text=document,
                    rank=rank,
                    fused_score=(
                        1.0
                        if revision_id in exact_rank
                        else fused_score.get(
                            revision_id,
                            0.0,
                        )
                    ),
                    exact_rank=exact_rank.get(revision_id),
                    lexical_rank=lexical_rank.get(revision_id),
                    lexical_score=lexical_score.get(revision_id),
                    dense_rank=dense_rank.get(revision_id),
                    dense_score=dense_score.get(revision_id),
                    applicability=applicability,
                    evidence=self._evidence_summary(revision_id),
                    attestations=self._attestations(revision_id),
                )
            )
        return tuple(output)

    def _eligible_revision_ids(
        self,
        *,
        context: ApplicabilityContext,
        policy: EngineeringKnowledgeRetrievalPolicy,
        now_epoch: float,
    ) -> dict[str, ApplicabilityDecision]:
        if not policy.sensitivities:
            return {}
        sensitivity_values = tuple(sorted(item.value for item in policy.sensitivities))
        placeholders = ", ".join("?" for _ in sensitivity_values)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT revision.revision_id
                FROM engineering_knowledge_revision AS revision
                JOIN engineering_knowledge_revision_state AS state
                  ON state.revision_id = revision.revision_id
                JOIN engineering_knowledge_search_document AS document
                  ON document.revision_id = revision.revision_id
                WHERE state.lifecycle_state = 'accepted'
                  AND revision.freshness_state = 'current'
                  AND revision.system_to_epoch IS NULL
                  AND revision.sensitivity IN ({placeholders})
                  AND (
                      revision.valid_from_epoch IS NULL
                      OR revision.valid_from_epoch <= ?
                  )
                  AND (
                      revision.valid_to_epoch IS NULL
                      OR revision.valid_to_epoch >= ?
                  )
                ORDER BY revision.revision_id
                """,
                (*sensitivity_values, now_epoch, now_epoch),
            ).fetchall()

        applicability_service = EngineeringKnowledgeApplicabilityService(self)
        integrity_verifier = EngineeringKnowledgeIntegrityVerifier()
        eligible: dict[str, ApplicabilityDecision] = {}
        for row in rows:
            revision_id = str(row[0])
            integrity = integrity_verifier.verify(self, revision_id)
            if not integrity.valid:
                continue
            if not self._derived_document_matches_canonical(revision_id):
                continue
            decision = applicability_service.evaluate(revision_id, context)
            if decision.eligible:
                eligible[revision_id] = decision
        return eligible

    def _build_searchable_text(
        self,
        revision: EngineeringKnowledgeRevision,
    ) -> str:
        with self._lock:
            cursor = self._connection.execute(
                """
                SELECT *
                FROM engineering_knowledge_facet
                WHERE revision_id = ?
                ORDER BY facet_type, schema_id, schema_version, facet_id
                """,
                (revision.revision_id,),
            )
            rows = cursor.fetchall()
            columns = [item[0] for item in cursor.description or ()]

        parts = [revision.normalized_summary]
        for row in rows:
            facet = _facet_from_row(dict(zip(columns, row, strict=True)))
            assessment = self._facet_registry.assess_for_decision(facet)
            if not assessment.eligible or assessment.validated is None:
                continue
            parts.append(assessment.validated.searchable_text)
        normalized = " ".join(part.strip() for part in parts if part and part.strip())
        if not normalized:
            raise EngineeringKnowledgeRetrievalError(
                "knowledge revision produced no safe searchable text"
            )
        decision = EngineeringEvidenceAdmissionGate().assess(
            EvidenceAdmissionRequest(
                source_class="authoritative_engineering_record",
                content=normalized,
                sensitivity=revision.sensitivity,
            )
        )
        if not decision.admissible:
            raise EngineeringKnowledgeRetrievalError(
                "knowledge search projection failed security screening: "
                + ",".join(decision.reason_codes)
            )
        return normalized

    def _derived_document_matches_canonical(self, revision_id: str) -> bool:
        revision = self.get_engineering_knowledge_revision(revision_id)
        if revision is None:
            return False
        stored = self._search_document_with_hash(revision_id)
        if stored is None:
            return False
        searchable_text, stored_digest = stored
        try:
            canonical_text = self._build_searchable_text(revision)
        except EngineeringKnowledgeRetrievalError:
            return False
        canonical_digest = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
        return searchable_text == canonical_text and stored_digest == canonical_digest

    def _search_document_with_hash(
        self,
        revision_id: str,
    ) -> tuple[str, str] | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT searchable_text, content_sha256
                FROM engineering_knowledge_search_document
                WHERE revision_id = ?
                """,
                (revision_id,),
            ).fetchone()
        if row is None:
            return None
        return str(row[0]), str(row[1])

    def _upsert_embedding(
        self,
        revision_id: str,
        *,
        content_sha256: str,
        vector: np.ndarray,
        contract: EmbeddingContract,
        now_epoch: float,
    ) -> None:
        payload = serialize_embedding(vector, contract=contract)
        with self._lock, self._connection:
            existing = self._connection.execute(
                """
                SELECT created_at_epoch
                FROM engineering_knowledge_embedding
                WHERE revision_id = ?
                """,
                (revision_id,),
            ).fetchone()
            created_at = float(existing[0]) if existing is not None else now_epoch
            self._connection.execute(
                """
                INSERT INTO engineering_knowledge_embedding (
                    revision_id, model_id, model_revision, dimension,
                    dtype, byte_order, normalized, content_sha256,
                    embedding_blob, created_at_epoch, updated_at_epoch
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(revision_id) DO UPDATE SET
                    model_id=excluded.model_id,
                    model_revision=excluded.model_revision,
                    dimension=excluded.dimension,
                    dtype=excluded.dtype,
                    byte_order=excluded.byte_order,
                    normalized=excluded.normalized,
                    content_sha256=excluded.content_sha256,
                    embedding_blob=excluded.embedding_blob,
                    updated_at_epoch=excluded.updated_at_epoch
                """,
                (
                    revision_id,
                    contract.model_id,
                    contract.model_revision,
                    contract.dimension,
                    contract.dtype,
                    contract.byte_order,
                    int(contract.normalized),
                    content_sha256,
                    payload,
                    created_at,
                    now_epoch,
                ),
            )

    def _exact_ids(
        self,
        query: str,
        eligible: dict[str, ApplicabilityDecision],
    ) -> tuple[str, ...]:
        revision_ids = tuple(eligible)
        if not revision_ids:
            return ()
        placeholders = ", ".join("?" for _ in revision_ids)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT DISTINCT revision.revision_id
                FROM engineering_knowledge_revision AS revision
                LEFT JOIN engineering_knowledge_evidence_link AS link
                  ON link.revision_id = revision.revision_id
                LEFT JOIN engineering_evidence AS evidence
                  ON evidence.evidence_id = link.evidence_id
                WHERE revision.revision_id IN ({placeholders})
                  AND (
                      revision.revision_id = ?
                      OR revision.knowledge_id = ?
                      OR evidence.canonical_reference = ?
                  )
                ORDER BY revision.revision_id
                """,
                (*revision_ids, query, query, query),
            ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def _lexical_rank(
        self,
        query: str,
        eligible: dict[str, ApplicabilityDecision],
        *,
        window: int,
    ) -> list[tuple[str, float]]:
        revision_ids = tuple(eligible)
        if not revision_ids:
            return []
        fts_query = build_fts5_query(query)
        placeholders = ", ".join("?" for _ in revision_ids)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT revision_id, bm25(engineering_knowledge_fts) AS score
                FROM engineering_knowledge_fts
                WHERE engineering_knowledge_fts MATCH ?
                  AND revision_id IN ({placeholders})
                ORDER BY score ASC, revision_id ASC
                LIMIT ?
                """,
                (fts_query, *revision_ids, window),
            ).fetchall()
        return [(str(row[0]), float(row[1])) for row in rows]

    def _dense_rank(
        self,
        query_vector: np.ndarray,
        eligible: dict[str, ApplicabilityDecision],
        *,
        contract: EmbeddingContract,
        window: int,
    ) -> list[tuple[str, float]]:
        revision_ids = tuple(eligible)
        if not revision_ids:
            return []
        placeholders = ", ".join("?" for _ in revision_ids)
        with self._lock:
            rows = self._connection.execute(
                f"""
                SELECT embedding.revision_id, embedding.content_sha256,
                       embedding.embedding_blob, document.content_sha256
                FROM engineering_knowledge_embedding AS embedding
                JOIN engineering_knowledge_search_document AS document
                  ON document.revision_id = embedding.revision_id
                WHERE embedding.revision_id IN ({placeholders})
                  AND embedding.model_id = ?
                  AND embedding.model_revision = ?
                  AND embedding.dimension = ?
                  AND embedding.dtype = ?
                  AND embedding.byte_order = ?
                  AND embedding.normalized = ?
                ORDER BY embedding.revision_id
                """,
                (
                    *revision_ids,
                    contract.model_id,
                    contract.model_revision,
                    contract.dimension,
                    contract.dtype,
                    contract.byte_order,
                    int(contract.normalized),
                ),
            ).fetchall()

        scored: list[tuple[str, float]] = []
        for row in rows:
            if str(row[1]) != str(row[3]):
                continue
            vector = deserialize_embedding(row[2], contract=contract)
            score = float(np.dot(query_vector, vector))
            if not math.isfinite(score):
                continue
            scored.append((str(row[0]), score))
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored[:window]

    def _search_document(self, revision_id: str) -> str | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT searchable_text
                FROM engineering_knowledge_search_document
                WHERE revision_id = ?
                """,
                (revision_id,),
            ).fetchone()
        return None if row is None else str(row[0])

    def _evidence_summary(
        self,
        revision_id: str,
    ) -> tuple[EngineeringKnowledgeEvidenceSummary, ...]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT evidence.evidence_id, link.relation_type,
                       evidence.evidence_type, evidence.source_class,
                       evidence.canonical_reference, evidence.summary
                FROM engineering_knowledge_evidence_link AS link
                JOIN engineering_evidence AS evidence
                  ON evidence.evidence_id = link.evidence_id
                WHERE link.revision_id = ?
                ORDER BY link.relation_type, evidence.canonical_reference,
                         evidence.evidence_id
                """,
                (revision_id,),
            ).fetchall()
        return tuple(
            EngineeringKnowledgeEvidenceSummary(
                evidence_id=str(row[0]),
                relation_type=str(row[1]),
                evidence_type=str(row[2]),
                source_class=str(row[3]),
                canonical_reference=str(row[4]),
                summary=str(row[5]),
            )
            for row in rows
        )

    def _attestations(
        self,
        revision_id: str,
    ) -> tuple[EngineeringAttestation, ...]:
        return self.list_engineering_attestations(
            subject_type="knowledge_revision",
            subject_id=revision_id,
        )


def _revision_from_row(payload: dict[str, object]) -> EngineeringKnowledgeRevision:
    return EngineeringKnowledgeRevision(
        revision_id=str(payload["revision_id"]),
        knowledge_id=str(payload["knowledge_id"]),
        revision_number=int(payload["revision_number"]),
        parent_revision_id=(
            str(payload["parent_revision_id"])
            if payload["parent_revision_id"] is not None
            else None
        ),
        supersedes_revision_id=(
            str(payload["supersedes_revision_id"])
            if payload["supersedes_revision_id"] is not None
            else None
        ),
        kind_namespace=str(payload["kind_namespace"]),
        normalized_summary=str(payload["normalized_summary"]),
        valid_from_epoch=(
            float(payload["valid_from_epoch"])
            if payload["valid_from_epoch"] is not None
            else None
        ),
        valid_to_epoch=(
            float(payload["valid_to_epoch"])
            if payload["valid_to_epoch"] is not None
            else None
        ),
        system_from_epoch=float(payload["system_from_epoch"]),
        system_to_epoch=(
            float(payload["system_to_epoch"])
            if payload["system_to_epoch"] is not None
            else None
        ),
        sensitivity=KnowledgeSensitivity(str(payload["sensitivity"])),
        freshness_state=KnowledgeFreshnessState(str(payload["freshness_state"])),
        canonicalization=str(payload["canonicalization"]),
        digest_algorithm=str(payload["digest_algorithm"]),
        canonical_digest=str(payload["canonical_digest"]),
        created_at_epoch=float(payload["created_at_epoch"]),
        created_by=str(payload["created_by"]),
    )


def _facet_from_row(payload: dict[str, object]) -> EngineeringKnowledgeFacet:
    return EngineeringKnowledgeFacet(
        facet_id=str(payload["facet_id"]),
        revision_id=str(payload["revision_id"]),
        facet_type=str(payload["facet_type"]),
        schema_id=str(payload["schema_id"]),
        schema_version=str(payload["schema_version"]),
        schema_digest=str(payload["schema_digest"]),
        producer=str(payload["producer"]),
        payload_json=(
            str(payload["payload_json"])
            if payload["payload_json"] is not None
            else None
        ),
        protected_payload_ref=(
            str(payload["protected_payload_ref"])
            if payload["protected_payload_ref"] is not None
            else None
        ),
        payload_digest=str(payload["payload_digest"]),
        created_at_epoch=float(payload["created_at_epoch"]),
    )


def _query_without_applicability_identity_terms(
    query: str,
    context: ApplicabilityContext,
) -> str:
    """Remove target-identity terms already enforced by applicability gates."""

    identity_tokens: set[str] = set()
    for fact in context.facts:
        identity_tokens.update(
            token.casefold()
            for token in re.findall(r"[^\W_]+", fact.target_identity, flags=re.UNICODE)
            if len(token) >= 2
        )
    query_tokens = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
    remaining = [
        token for token in query_tokens if token.casefold() not in identity_tokens
    ]
    return " ".join(remaining) if remaining else "__no_match__"


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise EngineeringKnowledgeRetrievalQueryError(f"{field} must not be empty")
    return normalized


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an integer")
    if value <= 0:
        raise ValueError(f"{field} must be positive")
    return value


def _finite_epoch(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("now_epoch must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError("now_epoch must be finite")
    return normalized


def _unit_vector(
    value: np.ndarray,
    contract: EmbeddingContract,
) -> np.ndarray:
    try:
        vector = np.asarray(value, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise EngineeringKnowledgeRetrievalQueryError(
            "embedding vector must be numeric"
        ) from exc
    if vector.ndim != 1 or vector.shape != (contract.dimension,):
        raise EngineeringKnowledgeRetrievalQueryError(
            f"embedding vector must have shape ({contract.dimension},)"
        )
    if not np.all(np.isfinite(vector)):
        raise EngineeringKnowledgeRetrievalQueryError(
            "embedding vector must contain finite values"
        )
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= 0.0:
        raise EngineeringKnowledgeRetrievalQueryError(
            "embedding vector norm must be positive"
        )
    return np.asarray(vector / norm, dtype=np.float32)
