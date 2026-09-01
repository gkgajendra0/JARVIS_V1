from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from jarvis.identity.model_assets import (
    ModelAssetCache,
    ModelAssetIntegrityError,
    ModelAssetManifest,
    default_model_cache_dir,
    load_default_face_model_manifest,
)


def test_default_face_manifest_is_pinned_to_reviewed_opencv_zoo_revision() -> None:
    manifest = load_default_face_model_manifest()

    assert manifest.schema_version == 1
    assert manifest.source_revision == "47534e27c9851bb1128ccc0102f1145e27f23f98"

    yunet = manifest.by_role("face_detector")
    assert yunet.filename == "face_detection_yunet_2026may.onnx"
    assert yunet.sha256 == (
        "ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0"
    )
    assert yunet.size_bytes == 229738
    assert yunet.model_license == "MIT"
    assert yunet.provenance_status == "documented_upstream"

    sface = manifest.by_role("face_recognizer")
    assert sface.filename == "face_recognition_sface_2021dec.onnx"
    assert sface.sha256 == (
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"
    )
    assert sface.size_bytes == 38696353
    assert sface.provenance_status == "exact_training_dataset_unresolved"
    assert sface.commercial_distribution_status == (
        "review_required_before_commercial_distribution"
    )
    assert sface.reference_thresholds["cosine_same_identity_min"] == 0.363


def test_model_cache_uses_explicit_environment_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "models"
    monkeypatch.setenv("JARVIS_MODEL_CACHE", str(target))

    assert default_model_cache_dir() == target


def test_model_fetch_verifies_size_sha_and_reuses_valid_cache(tmp_path: Path) -> None:
    payload = b"pinned-test-model-bytes"
    asset = _test_asset(payload)
    cache = ModelAssetCache(tmp_path)
    calls = 0

    def opener(request, *, timeout: float):
        nonlocal calls
        calls += 1
        assert request.full_url == asset.source_url
        assert timeout == 12.0
        return io.BytesIO(payload)

    path = cache.fetch(asset, timeout_seconds=12.0, opener=opener)

    assert path.read_bytes() == payload
    assert cache.verify(asset) == path
    assert calls == 1

    assert cache.fetch(asset, timeout_seconds=12.0, opener=opener) == path
    assert calls == 1


def test_model_cache_fails_closed_after_cached_asset_tampering(tmp_path: Path) -> None:
    payload = b"pinned-test-model-bytes"
    asset = _test_asset(payload)
    cache = ModelAssetCache(tmp_path)
    path = cache.path_for(asset)
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)

    assert cache.verify(asset) == path

    path.write_bytes(payload + b"tampered")

    with pytest.raises(ModelAssetIntegrityError, match="size mismatch"):
        cache.verify(asset)


def test_model_fetch_rejects_wrong_download_without_replacing_existing_file(
    tmp_path: Path,
) -> None:
    expected = b"expected-pinned-bytes"
    asset = _test_asset(expected)
    cache = ModelAssetCache(tmp_path)
    target = cache.path_for(asset)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old-invalid-cache")

    def opener(request, *, timeout: float):
        _ = request, timeout
        return io.BytesIO(b"different-download")

    with pytest.raises(ModelAssetIntegrityError):
        cache.fetch(asset, opener=opener)

    assert target.read_bytes() == b"old-invalid-cache"


def _test_asset(payload: bytes) -> ModelAssetManifest:
    return ModelAssetManifest(
        asset_id="test-model",
        role="test",
        filename="test.onnx",
        source_path="models/test/test.onnx",
        source_url=(
            "https://github.com/example/models/raw/"
            "0123456789abcdef0123456789abcdef01234567/models/test/test.onnx"
        ),
        source_revision="0123456789abcdef0123456789abcdef01234567",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        code_license="MIT",
        model_license="MIT",
        provenance_status="test",
        training_data_note="test fixture",
        commercial_distribution_status="test",
        deployment_status="test",
        minimum_opencv_version="5.0.0",
        backend="test",
        calibration_status="test",
        reference_thresholds={},
    )
