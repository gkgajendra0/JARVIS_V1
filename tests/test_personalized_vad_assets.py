from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from jarvis.identity import personalized_vad_assets as assets


def _complete_fake_assets(root: Path, payload: bytes) -> Path:
    root.mkdir(parents=True)
    (root / assets.FIRERED_PVAD_ONNX_FILENAME).write_bytes(payload)
    speaker = root / assets.FIRERED_PVAD_SPEAKER_DIRNAME
    speaker.mkdir()
    for name in ("hyperparams.yaml", "classifier.ckpt", "embedding_model.ckpt"):
        (speaker / name).write_bytes(b"fixture")
    return root


def test_verify_personalized_vad_assets_accepts_pinned_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"pvad-test-model"
    root = _complete_fake_assets(tmp_path / "firered", payload)
    monkeypatch.setattr(assets, "FIRERED_PVAD_ONNX_SIZE_BYTES", len(payload))
    monkeypatch.setattr(
        assets,
        "FIRERED_PVAD_ONNX_SHA256",
        hashlib.sha256(payload).hexdigest(),
    )

    assert assets.verify_personalized_vad_assets(root) == root


def test_verify_personalized_vad_assets_rejects_wrong_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"pvad-test-model"
    root = _complete_fake_assets(tmp_path / "firered", payload)
    monkeypatch.setattr(assets, "FIRERED_PVAD_ONNX_SIZE_BYTES", len(payload))
    monkeypatch.setattr(assets, "FIRERED_PVAD_ONNX_SHA256", "0" * 64)

    with pytest.raises(assets.PersonalizedVadAssetIntegrityError, match="sha256"):
        assets.verify_personalized_vad_assets(root)


def test_verify_personalized_vad_assets_requires_ecapa_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"pvad-test-model"
    root = tmp_path / "firered"
    root.mkdir()
    (root / assets.FIRERED_PVAD_ONNX_FILENAME).write_bytes(payload)
    (root / assets.FIRERED_PVAD_SPEAKER_DIRNAME).mkdir()
    monkeypatch.setattr(assets, "FIRERED_PVAD_ONNX_SIZE_BYTES", len(payload))
    monkeypatch.setattr(
        assets,
        "FIRERED_PVAD_ONNX_SHA256",
        hashlib.sha256(payload).hexdigest(),
    )

    with pytest.raises(assets.PersonalizedVadAssetIntegrityError, match="incomplete"):
        assets.verify_personalized_vad_assets(root)
