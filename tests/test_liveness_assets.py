from __future__ import annotations

import hashlib

import pytest

from jarvis.identity import liveness_assets


def test_verify_face_landmarker_model_accepts_exact_asset(
    tmp_path, monkeypatch
) -> None:
    payload = b"pinned-face-landmarker-test-bytes"
    monkeypatch.setattr(liveness_assets, "FACE_LANDMARKER_SIZE_BYTES", len(payload))
    monkeypatch.setattr(
        liveness_assets,
        "FACE_LANDMARKER_SHA256",
        hashlib.sha256(payload).hexdigest(),
    )
    path = tmp_path / "face_landmarker.task"
    path.write_bytes(payload)

    assert liveness_assets.verify_face_landmarker_model(path) == path


def test_existing_tampered_face_landmarker_fails_closed(tmp_path, monkeypatch) -> None:
    expected = b"expected"
    monkeypatch.setattr(liveness_assets, "FACE_LANDMARKER_SIZE_BYTES", len(expected))
    monkeypatch.setattr(
        liveness_assets,
        "FACE_LANDMARKER_SHA256",
        hashlib.sha256(expected).hexdigest(),
    )
    path = tmp_path / "face_landmarker.task"
    path.write_bytes(b"tampered")

    with pytest.raises(liveness_assets.LivenessModelIntegrityError):
        liveness_assets.ensure_face_landmarker_model(path)
