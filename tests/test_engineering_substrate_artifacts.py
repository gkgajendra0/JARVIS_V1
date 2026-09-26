from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from jarvis.engineering_substrate import (
    ArtifactIntegrityError,
    ArtifactPathError,
    ArtifactRetentionReferences,
    ArtifactStore,
)


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def test_artifact_admission_is_content_addressed_and_idempotent(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "store")
    source = tmp_path / "artifact.whl"
    payload = b"deterministic-wheel-bytes"
    source.write_bytes(payload)
    expected = _digest(payload)

    first = store.admit_file(
        source,
        expected_sha256=expected,
        provenance_id="provenance-1",
        source_id="pypi.public.v1",
    )
    second = store.admit_file(
        source,
        expected_sha256=expected,
        provenance_id="provenance-1",
        source_id="pypi.public.v1",
    )

    assert first.artifact_sha256 == expected
    assert first.object_path == store.objects_root / expected
    assert first.object_path.read_bytes() == payload
    assert first.already_present is False
    assert second.already_present is True
    assert second.object_path == first.object_path
    assert second.admission_record_path == first.admission_record_path
    assert store.read_bytes(expected) == payload


def test_artifact_same_bytes_can_have_multiple_immutable_provenance_links(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "store")
    source = tmp_path / "artifact.whl"
    source.write_bytes(b"same-content")

    first = store.admit_file(
        source,
        provenance_id="provenance-a",
        source_id="pypi.public.v1",
    )
    store.admit_file(
        source,
        provenance_id="provenance-b",
        source_id="mirror.reviewed.v1",
    )

    records = store.list_admission_records(first.artifact_sha256)
    assert len(records) == 2
    assert all(path.read_text(encoding="utf-8") for path in records)


def test_wrong_expected_digest_is_rejected_and_quarantined(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "store")
    source = tmp_path / "artifact.whl"
    source.write_bytes(b"wrong-content")

    with pytest.raises(ArtifactIntegrityError, match="quarantined"):
        store.admit_file(source, expected_sha256="a" * 64)

    assert list(store.objects_root.iterdir()) == []
    quarantined = list(store.quarantine_root.iterdir())
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == b"wrong-content"


def test_verify_on_read_detects_object_tampering(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "store")
    source = tmp_path / "artifact.whl"
    source.write_bytes(b"trusted")
    admitted = store.admit_file(source)

    admitted.object_path.write_bytes(b"tampered")

    with pytest.raises(ArtifactIntegrityError, match="verify-on-read"):
        store.read_bytes(admitted.artifact_sha256)


def test_artifact_source_and_root_symlinks_are_rejected(tmp_path: Path) -> None:
    real_source = tmp_path / "real.whl"
    real_source.write_bytes(b"payload")
    source_link = tmp_path / "link.whl"
    real_root = tmp_path / "real-store"
    real_root.mkdir()
    root_link = tmp_path / "store-link"

    try:
        source_link.symlink_to(real_source)
        root_link.symlink_to(real_root, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    store = ArtifactStore(tmp_path / "store")
    with pytest.raises(ArtifactPathError, match="source cannot be a symlink"):
        store.admit_file(source_link)

    with pytest.raises(ArtifactPathError, match="root cannot be a symlink"):
        ArtifactStore(root_link)


def test_digest_path_cannot_be_escaped(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "store")

    with pytest.raises(ValueError, match="64-character"):
        store.read_bytes("../../outside")

    with pytest.raises(ValueError, match="64-character"):
        store.list_admission_records("../" + ("a" * 64))


def test_gc_contract_only_identifies_unreferenced_objects(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "store")
    first = tmp_path / "first.whl"
    second = tmp_path / "second.whl"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    a = store.admit_file(first)
    b = store.admit_file(second)

    refs = ArtifactRetentionReferences((a.artifact_sha256,))
    assert store.garbage_collection_candidates(refs) == (b.artifact_sha256,)
    assert a.object_path.exists()
    assert b.object_path.exists()
