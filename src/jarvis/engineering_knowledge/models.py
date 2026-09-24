"""Typed, side-effect-free Phase-2 EngineeringKnowledge core contracts."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
CANONICALIZATION_RFC8785 = "rfc8785"
DIGEST_ALGORITHM_SHA256 = "sha256"
MAX_EVIDENCE_IDS = 32


class KnowledgeLifecycleState(StrEnum):
    CANDIDATE = "candidate"
    STAGED = "staged"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RETIRED = "retired"
    SUPERSEDED = "superseded"


class KnowledgeSensitivity(StrEnum):
    STANDARD = "standard"
    PRIVATE = "private"
    LOCAL_ONLY = "local_only"


class KnowledgeFreshnessState(StrEnum):
    CURRENT = "current"
    REVALIDATION_REQUIRED = "revalidation_required"
    EXPIRED = "expired"


class AttestationVerdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


def _required_text(value: object, *, field: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _required_token(value: object, *, field: str) -> str:
    return _required_text(value, field=field).casefold()


def _optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _epoch(value: object | None, *, field: str, optional: bool = False) -> float | None:
    if value is None:
        if optional:
            return None
        raise ValueError(f"{field} must not be None")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field} must be finite")
    return normalized


def _sha256(value: object, *, field: str) -> str:
    normalized = _required_text(value, field=field).casefold()
    if len(normalized) != 64 or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise ValueError(f"{field} must be a 64-character SHA-256 hex digest")
    return normalized


def _json_object_text(value: object, *, field: str) -> str:
    text = _required_text(value, field=field)
    try:
        parsed = json.loads(
            text,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {token}")
            ),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{field} must contain valid JSON") from exc
    if not isinstance(parsed, dict):
        raise TypeError(f"{field} must contain a JSON object")
    return text


def _evidence_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        item = _required_text(value, field="evidence_id")
        if item not in normalized:
            normalized.append(item)
    if len(normalized) > MAX_EVIDENCE_IDS:
        raise ValueError(f"evidence_ids exceed {MAX_EVIDENCE_IDS}")
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class EngineeringKnowledgeIdentity:
    knowledge_id: str
    created_at_epoch: float
    created_by: str
    stable_label: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "knowledge_id",
            _required_text(self.knowledge_id, field="knowledge_id"),
        )
        object.__setattr__(
            self,
            "created_at_epoch",
            _epoch(self.created_at_epoch, field="created_at_epoch"),
        )
        object.__setattr__(
            self,
            "created_by",
            _required_text(self.created_by, field="created_by"),
        )
        object.__setattr__(self, "stable_label", _optional_text(self.stable_label))


@dataclass(frozen=True, slots=True)
class EngineeringKnowledgeRevision:
    revision_id: str
    knowledge_id: str
    revision_number: int
    kind_namespace: str
    normalized_summary: str
    system_from_epoch: float
    sensitivity: KnowledgeSensitivity
    freshness_state: KnowledgeFreshnessState
    canonical_digest: str
    created_at_epoch: float
    created_by: str
    parent_revision_id: str | None = None
    supersedes_revision_id: str | None = None
    valid_from_epoch: float | None = None
    valid_to_epoch: float | None = None
    system_to_epoch: float | None = None
    canonicalization: str = CANONICALIZATION_RFC8785
    digest_algorithm: str = DIGEST_ALGORITHM_SHA256

    def __post_init__(self) -> None:
        revision_id = _required_text(self.revision_id, field="revision_id")
        object.__setattr__(self, "revision_id", revision_id)
        object.__setattr__(
            self,
            "knowledge_id",
            _required_text(self.knowledge_id, field="knowledge_id"),
        )
        if isinstance(self.revision_number, bool) or not isinstance(
            self.revision_number, int
        ):
            raise TypeError("revision_number must be an integer")
        if self.revision_number <= 0:
            raise ValueError("revision_number must be positive")
        object.__setattr__(
            self,
            "kind_namespace",
            _required_token(self.kind_namespace, field="kind_namespace"),
        )
        object.__setattr__(
            self,
            "normalized_summary",
            _required_text(self.normalized_summary, field="normalized_summary"),
        )
        object.__setattr__(
            self,
            "system_from_epoch",
            _epoch(self.system_from_epoch, field="system_from_epoch"),
        )
        object.__setattr__(
            self,
            "created_at_epoch",
            _epoch(self.created_at_epoch, field="created_at_epoch"),
        )
        object.__setattr__(
            self,
            "created_by",
            _required_text(self.created_by, field="created_by"),
        )
        if not isinstance(self.sensitivity, KnowledgeSensitivity):
            raise TypeError("sensitivity must be a KnowledgeSensitivity")
        if not isinstance(self.freshness_state, KnowledgeFreshnessState):
            raise TypeError("freshness_state must be a KnowledgeFreshnessState")
        object.__setattr__(
            self,
            "canonical_digest",
            _sha256(self.canonical_digest, field="canonical_digest"),
        )
        if self.canonicalization != CANONICALIZATION_RFC8785:
            raise ValueError(f"canonicalization must be {CANONICALIZATION_RFC8785!r}")
        if self.digest_algorithm != DIGEST_ALGORITHM_SHA256:
            raise ValueError(f"digest_algorithm must be {DIGEST_ALGORITHM_SHA256!r}")

        parent = _optional_text(self.parent_revision_id)
        supersedes = _optional_text(self.supersedes_revision_id)
        if parent == revision_id:
            raise ValueError("parent_revision_id cannot reference the same revision")
        if supersedes == revision_id:
            raise ValueError(
                "supersedes_revision_id cannot reference the same revision"
            )
        object.__setattr__(self, "parent_revision_id", parent)
        object.__setattr__(self, "supersedes_revision_id", supersedes)

        valid_from = _epoch(
            self.valid_from_epoch,
            field="valid_from_epoch",
            optional=True,
        )
        valid_to = _epoch(
            self.valid_to_epoch,
            field="valid_to_epoch",
            optional=True,
        )
        system_to = _epoch(
            self.system_to_epoch,
            field="system_to_epoch",
            optional=True,
        )
        if valid_from is not None and valid_to is not None and valid_to < valid_from:
            raise ValueError("valid_to_epoch cannot precede valid_from_epoch")
        if system_to is not None and system_to < self.system_from_epoch:
            raise ValueError("system_to_epoch cannot precede system_from_epoch")
        object.__setattr__(self, "valid_from_epoch", valid_from)
        object.__setattr__(self, "valid_to_epoch", valid_to)
        object.__setattr__(self, "system_to_epoch", system_to)


@dataclass(frozen=True, slots=True)
class EngineeringKnowledgeFacet:
    facet_id: str
    revision_id: str
    facet_type: str
    schema_id: str
    schema_version: str
    schema_digest: str
    producer: str
    payload_digest: str
    created_at_epoch: float
    payload_json: str | None = None
    protected_payload_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "facet_id", _required_text(self.facet_id, field="facet_id")
        )
        object.__setattr__(
            self,
            "revision_id",
            _required_text(self.revision_id, field="revision_id"),
        )
        object.__setattr__(
            self,
            "facet_type",
            _required_token(self.facet_type, field="facet_type"),
        )
        object.__setattr__(
            self,
            "schema_id",
            _required_text(self.schema_id, field="schema_id"),
        )
        object.__setattr__(
            self,
            "schema_version",
            _required_text(self.schema_version, field="schema_version"),
        )
        object.__setattr__(
            self,
            "schema_digest",
            _sha256(self.schema_digest, field="schema_digest"),
        )
        object.__setattr__(
            self,
            "producer",
            _required_text(self.producer, field="producer"),
        )
        object.__setattr__(
            self,
            "payload_digest",
            _sha256(self.payload_digest, field="payload_digest"),
        )
        object.__setattr__(
            self,
            "created_at_epoch",
            _epoch(self.created_at_epoch, field="created_at_epoch"),
        )

        payload = self.payload_json
        protected = _optional_text(self.protected_payload_ref)
        if (payload is None) == (protected is None):
            raise ValueError(
                "exactly one of payload_json or protected_payload_ref is required"
            )
        if payload is not None:
            payload = _json_object_text(payload, field="payload_json")
        object.__setattr__(self, "payload_json", payload)
        object.__setattr__(self, "protected_payload_ref", protected)


@dataclass(frozen=True, slots=True)
class EngineeringApplicability:
    applicability_id: str
    revision_id: str
    target_namespace: str
    target_identity: str
    matcher_type: str
    constraint_json: str
    required: bool
    created_at_epoch: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "applicability_id",
            _required_text(self.applicability_id, field="applicability_id"),
        )
        object.__setattr__(
            self,
            "revision_id",
            _required_text(self.revision_id, field="revision_id"),
        )
        object.__setattr__(
            self,
            "target_namespace",
            _required_token(self.target_namespace, field="target_namespace"),
        )
        object.__setattr__(
            self,
            "target_identity",
            _required_text(self.target_identity, field="target_identity"),
        )
        object.__setattr__(
            self,
            "matcher_type",
            _required_token(self.matcher_type, field="matcher_type"),
        )
        object.__setattr__(
            self,
            "constraint_json",
            _json_object_text(self.constraint_json, field="constraint_json"),
        )
        if not isinstance(self.required, bool):
            raise TypeError("required must be a bool")
        object.__setattr__(
            self,
            "created_at_epoch",
            _epoch(self.created_at_epoch, field="created_at_epoch"),
        )


@dataclass(frozen=True, slots=True)
class EngineeringEvidence:
    evidence_id: str
    evidence_type: str
    source_class: str
    canonical_reference: str
    summary: str
    observed_at_epoch: float
    sensitivity: KnowledgeSensitivity
    producer: str
    created_at_epoch: float
    occurred_at_epoch: float | None = None
    integrity_algorithm: str | None = None
    integrity_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_id",
            _required_text(self.evidence_id, field="evidence_id"),
        )
        object.__setattr__(
            self,
            "evidence_type",
            _required_token(self.evidence_type, field="evidence_type"),
        )
        object.__setattr__(
            self,
            "source_class",
            _required_token(self.source_class, field="source_class"),
        )
        object.__setattr__(
            self,
            "canonical_reference",
            _required_text(self.canonical_reference, field="canonical_reference"),
        )
        object.__setattr__(
            self,
            "summary",
            _required_text(self.summary, field="summary"),
        )
        object.__setattr__(
            self,
            "observed_at_epoch",
            _epoch(self.observed_at_epoch, field="observed_at_epoch"),
        )
        object.__setattr__(
            self,
            "occurred_at_epoch",
            _epoch(self.occurred_at_epoch, field="occurred_at_epoch", optional=True),
        )
        if not isinstance(self.sensitivity, KnowledgeSensitivity):
            raise TypeError("sensitivity must be a KnowledgeSensitivity")
        object.__setattr__(
            self,
            "producer",
            _required_text(self.producer, field="producer"),
        )
        object.__setattr__(
            self,
            "created_at_epoch",
            _epoch(self.created_at_epoch, field="created_at_epoch"),
        )

        algorithm = _optional_text(self.integrity_algorithm)
        digest = _optional_text(self.integrity_digest)
        if (algorithm is None) != (digest is None):
            raise ValueError(
                "integrity_algorithm and integrity_digest must be provided together"
            )
        if algorithm is not None:
            algorithm = algorithm.casefold()
            if algorithm != DIGEST_ALGORITHM_SHA256:
                raise ValueError("only sha256 integrity digests are supported")
            assert digest is not None
            digest = _sha256(digest, field="integrity_digest")
        object.__setattr__(self, "integrity_algorithm", algorithm)
        object.__setattr__(self, "integrity_digest", digest)


@dataclass(frozen=True, slots=True)
class KnowledgeEvidenceLink:
    revision_id: str
    evidence_id: str
    relation_type: str
    created_at_epoch: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "revision_id",
            _required_text(self.revision_id, field="revision_id"),
        )
        object.__setattr__(
            self,
            "evidence_id",
            _required_text(self.evidence_id, field="evidence_id"),
        )
        object.__setattr__(
            self,
            "relation_type",
            _required_token(self.relation_type, field="relation_type"),
        )
        object.__setattr__(
            self,
            "created_at_epoch",
            _epoch(self.created_at_epoch, field="created_at_epoch"),
        )


@dataclass(frozen=True, slots=True)
class KnowledgeLifecycleEvent:
    event_id: str
    revision_id: str
    to_state: KnowledgeLifecycleState
    reason_code: str
    actor: str
    evidence_ids: tuple[str, ...]
    occurred_at_epoch: float
    from_state: KnowledgeLifecycleState | None = None
    policy_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_id", _required_text(self.event_id, field="event_id")
        )
        object.__setattr__(
            self,
            "revision_id",
            _required_text(self.revision_id, field="revision_id"),
        )
        if self.from_state is not None and not isinstance(
            self.from_state, KnowledgeLifecycleState
        ):
            raise TypeError("from_state must be a KnowledgeLifecycleState or None")
        if not isinstance(self.to_state, KnowledgeLifecycleState):
            raise TypeError("to_state must be a KnowledgeLifecycleState")
        if self.from_state is self.to_state:
            raise ValueError("lifecycle transition cannot keep the same state")
        object.__setattr__(
            self,
            "reason_code",
            _required_token(self.reason_code, field="reason_code"),
        )
        object.__setattr__(
            self,
            "actor",
            _required_text(self.actor, field="actor"),
        )
        object.__setattr__(self, "policy_id", _optional_text(self.policy_id))
        object.__setattr__(self, "evidence_ids", _evidence_ids(self.evidence_ids))
        object.__setattr__(
            self,
            "occurred_at_epoch",
            _epoch(self.occurred_at_epoch, field="occurred_at_epoch"),
        )


@dataclass(frozen=True, slots=True)
class EngineeringAttestation:
    attestation_id: str
    subject_type: str
    subject_id: str
    subject_digest: str
    predicate_type: str
    producer: str
    expected_contract_json: str
    observed_result_json: str
    verdict: AttestationVerdict
    evidence_ids: tuple[str, ...]
    observed_at_epoch: float
    created_at_epoch: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "attestation_id",
            _required_text(self.attestation_id, field="attestation_id"),
        )
        object.__setattr__(
            self,
            "subject_type",
            _required_token(self.subject_type, field="subject_type"),
        )
        object.__setattr__(
            self,
            "subject_id",
            _required_text(self.subject_id, field="subject_id"),
        )
        object.__setattr__(
            self,
            "subject_digest",
            _sha256(self.subject_digest, field="subject_digest"),
        )
        object.__setattr__(
            self,
            "predicate_type",
            _required_text(self.predicate_type, field="predicate_type"),
        )
        object.__setattr__(
            self,
            "producer",
            _required_text(self.producer, field="producer"),
        )
        object.__setattr__(
            self,
            "expected_contract_json",
            _json_object_text(
                self.expected_contract_json,
                field="expected_contract_json",
            ),
        )
        object.__setattr__(
            self,
            "observed_result_json",
            _json_object_text(
                self.observed_result_json,
                field="observed_result_json",
            ),
        )
        if not isinstance(self.verdict, AttestationVerdict):
            raise TypeError("verdict must be an AttestationVerdict")
        object.__setattr__(self, "evidence_ids", _evidence_ids(self.evidence_ids))
        object.__setattr__(
            self,
            "observed_at_epoch",
            _epoch(self.observed_at_epoch, field="observed_at_epoch"),
        )
        object.__setattr__(
            self,
            "created_at_epoch",
            _epoch(self.created_at_epoch, field="created_at_epoch"),
        )


def lifecycle_evidence_json(event: KnowledgeLifecycleEvent) -> str:
    """Serialize lifecycle evidence IDs deterministically for persistence."""

    if not isinstance(event, KnowledgeLifecycleEvent):
        raise TypeError("event must be a KnowledgeLifecycleEvent")
    return json.dumps(event.evidence_ids, ensure_ascii=False, separators=(",", ":"))
