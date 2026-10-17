"""Zero-network Hindsight external fact archive contract tests."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import replace

import pytest

from jarvis.memory.hindsight_transfer_shadow import (
    PINNED_FACTS,
    _validate,
    build_synthetic_external_fact_zip,
    inspect_synthetic_archive,
)


def _open_archive() -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(build_synthetic_external_fact_zip()))


def test_pinned_archive_matches_documented_external_import_shape():
    archive = build_synthetic_external_fact_zip()
    report = inspect_synthetic_archive(archive)
    assert report["document_count"] == 5
    assert report["fact_count"] == 5
    assert report["no_provider_calls"] is True
    assert report["no_server_import_tested"] is True
    assert all(value not in json.dumps(report) for value in ("Saturday", "Sunday"))
    with _open_archive() as z:
        assert json.loads(z.read("manifest.json")) == {
            "schema_version": 1,
            "source_bank_id": "jarvis-dev-only-external",
        }
        docs = [name for name in z.namelist() if name.startswith("documents/")]
        assert len(docs) == 5
        for name in docs:
            assert ".." not in name
            doc = json.loads(z.read(name))
            assert doc["id"].startswith("jarvis-dev-only-synthetic-")
            assert doc["chunks"][0]["chunk_index"] == 0
            fact = doc["facts"][0]
            assert fact["fact_type"] == "world"
            assert fact["chunk_index"] == 0
            assert fact["metadata"]["source_class"] == "synthetic_owner_direct"
            assert fact["metadata"]["admission_policy"] == "shadow_only_no_write"
            assert fact["mentioned_at"].endswith("Z")


def test_deterministic_bytes_and_identity_to_source_turn():
    first = build_synthetic_external_fact_zip()
    assert first == build_synthetic_external_fact_zip()
    with zipfile.ZipFile(io.BytesIO(first)) as z:
        metadata = {}
        for path in z.namelist():
            if path.startswith("documents/"):
                fact = json.loads(z.read(path))["facts"][0]
                meta = fact["metadata"]
                metadata[meta["assertion_id"]] = meta
        assert metadata["synthetic-workshop-day-v2"]["supersedes_id"] == (
            "synthetic-workshop-day-v1"
        )
        assert metadata["synthetic-report-day-v2"]["supersedes_id"] == (
            "synthetic-report-day-v1"
        )
        assert metadata["synthetic-workshop-venue-v1"]["predicate"] == (
            "workshop_venue"
        )


def test_invalid_versions_and_unauthorized_identity_fail_before_zip():
    with pytest.raises(ValueError, match="non-synthetic"):
        build_synthetic_external_fact_zip(
            (replace(PINNED_FACTS[0], assertion_id="owner-private-memory"),)
        )
    with pytest.raises(ValueError, match="duplicate"):
        build_synthetic_external_fact_zip((PINNED_FACTS[0], PINNED_FACTS[0]))
    with pytest.raises(ValueError, match="predecessor"):
        build_synthetic_external_fact_zip((PINNED_FACTS[1],))
    with pytest.raises(ValueError, match="lineage"):
        build_synthetic_external_fact_zip(
            (
                PINNED_FACTS[0],
                replace(PINNED_FACTS[1], predicate="workshop_venue"),
            )
        )


def test_bad_timestamp_secret_and_future_timestamp_fail():
    with pytest.raises(ValueError, match="timestamp"):
        build_synthetic_external_fact_zip(
            (replace(PINNED_FACTS[0], mentioned_at="not-a-date"),)
        )
    with pytest.raises(ValueError, match="secret"):
        build_synthetic_external_fact_zip(
            (replace(PINNED_FACTS[0], text="My password is a synthetic secret."),)
        )
    with pytest.raises(ValueError, match="after"):
        build_synthetic_external_fact_zip(
            (replace(PINNED_FACTS[0], occurred_start="2027-01-02T10:00:00Z"),)
        )


def test_ambiguous_unresolved_correction_is_not_imported():
    with _open_archive() as z:
        docs = [
            json.loads(z.read(f)) for f in z.namelist() if f.startswith("documents/")
        ]
    assert all("not final" not in doc["original_text"].casefold() for doc in docs)
    assert all("ambiguous" not in doc["facts"][0]["metadata"] for doc in docs)
    assert len(docs) == len(PINNED_FACTS)


def test_archive_tampering_cannot_be_misreported_as_valid():
    source = build_synthetic_external_fact_zip()
    with zipfile.ZipFile(io.BytesIO(source)) as original:
        files = {name: original.read(name) for name in original.namelist()}
    target = next(name for name in files if name.startswith("documents/"))
    doc = json.loads(files[target])
    doc["facts"][0]["text"] = "An inconsistent altered statement"
    files[target] = json.dumps(doc).encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
    with pytest.raises(ValueError, match="provenance"):
        inspect_synthetic_archive(stream.getvalue())


def test_real_owner_inputs_and_arbitrary_file_paths_are_not_supported():
    with pytest.raises((TypeError, ValueError)):
        _validate([PINNED_FACTS[0]])  # type: ignore[arg-type]
    assert not hasattr(PINNED_FACTS[0], "database_path")
    assert not hasattr(PINNED_FACTS[0], "provider_key")
