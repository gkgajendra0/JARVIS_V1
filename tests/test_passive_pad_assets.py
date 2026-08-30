from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from jarvis.identity.passive_pad_assets import (
    PassivePadAsset,
    PassivePadAssetCache,
    PassivePadAssetIntegrityError,
)


def _asset(payload: bytes, *, algorithm: str = "sha256") -> PassivePadAsset:
    digest = hashlib.new(algorithm, payload).hexdigest()
    return PassivePadAsset(
        asset_id="test-pad",
        filename="test.onnx",
        source_url="https://example.invalid/test.onnx",
        source_revision="test-revision",
        size_bytes=len(payload),
        digest_algorithm=algorithm,
        digest=digest,
        model_license="test-license",
        training_data_note="synthetic test asset",
    )


@pytest.mark.parametrize("algorithm", ["sha256", "sha384"])
def test_asset_cache_verifies_supported_digest_algorithms(
    tmp_path: Path,
    algorithm: str,
) -> None:
    payload = b"passive-pad-test-model"
    asset = _asset(payload, algorithm=algorithm)
    cache = PassivePadAssetCache(tmp_path)
    path = cache.path_for(asset)
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)

    assert cache.verify(asset) == path


def test_asset_cache_rejects_tampered_bytes(tmp_path: Path) -> None:
    payload = b"passive-pad-test-model"
    asset = _asset(payload)
    cache = PassivePadAssetCache(tmp_path)
    path = cache.path_for(asset)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"tampered-test-model!!")

    with pytest.raises(PassivePadAssetIntegrityError):
        cache.verify(asset)


def test_asset_rejects_unknown_digest_algorithm() -> None:
    with pytest.raises(ValueError):
        PassivePadAsset(
            asset_id="bad",
            filename="bad.onnx",
            source_url="https://example.invalid/bad.onnx",
            source_revision="bad-revision",
            size_bytes=1,
            digest_algorithm="md5",
            digest="0" * 32,
            model_license="test-license",
            training_data_note="synthetic test asset",
        )
