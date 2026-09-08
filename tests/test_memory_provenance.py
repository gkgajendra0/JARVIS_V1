from __future__ import annotations

from datetime import UTC, datetime

import pytest

from jarvis.memory import (
    AuthorityClass,
    MemorySource,
    MemorySourceClass,
    Sensitivity,
)


def source(**overrides: object) -> MemorySource:
    values: dict[str, object] = {
        "source_id": "source-1",
        "source_class": MemorySourceClass.OWNER_EXPLICIT,
        "canonical_ref": "conversation:session-1:turn-1",
        "observed_at": datetime.fromisoformat("2026-09-05T10:30:00+05:30"),
        "authority_class": AuthorityClass.OWNER_EXPLICIT,
        "sensitivity": Sensitivity.STANDARD,
        "created_at": datetime(2026, 9, 5, 5, 0, tzinfo=UTC),
        "evidence_hash": "A" * 64,
    }
    values.update(overrides)
    return MemorySource(**values)  # type: ignore[arg-type]


def test_source_normalizes_identifiers_timestamps_and_hash() -> None:
    value = source(source_id=" source-1 ", canonical_ref=" turn:1 ")

    assert value.source_id == "source-1"
    assert value.canonical_ref == "turn:1"
    assert value.observed_at == datetime(2026, 9, 5, 5, 0, tzinfo=UTC)
    assert value.observed_at.tzinfo is UTC
    assert value.evidence_hash == "a" * 64


def test_source_requires_aware_provenance_timestamps() -> None:
    naive = datetime(2026, 9, 5, 5, 0)  # noqa: DTZ001 - deliberately invalid fixture
    with pytest.raises(ValueError, match="timezone-aware"):
        source(observed_at=naive)
    with pytest.raises(ValueError, match="timezone-aware"):
        source(created_at=naive)


def test_source_rejects_invalid_hash_and_empty_canonical_identity() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        source(evidence_hash="not-a-hash")
    with pytest.raises(ValueError, match="source_id"):
        source(source_id="   ")
    with pytest.raises(ValueError, match="canonical_ref"):
        source(canonical_ref="   ")


def test_secret_prohibited_is_a_real_domain_class_not_normal_memory() -> None:
    value = source(sensitivity=Sensitivity.SECRET_PROHIBITED)
    assert value.sensitivity is Sensitivity.SECRET_PROHIBITED
