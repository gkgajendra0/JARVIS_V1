from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from jarvis.identity.model_assets import default_model_cache_dir


class PassivePadAssetError(RuntimeError):
    pass


class PassivePadAssetIntegrityError(PassivePadAssetError):
    pass


@dataclass(frozen=True, slots=True)
class PassivePadAsset:
    asset_id: str
    filename: str
    source_url: str
    source_revision: str
    size_bytes: int
    digest_algorithm: str
    digest: str
    model_license: str
    training_data_note: str

    def __post_init__(self) -> None:
        if not self.asset_id.strip():
            raise ValueError("asset_id must not be empty")
        if Path(self.filename).name != self.filename:
            raise ValueError("filename must be a basename")
        if not self.source_url.startswith("https://"):
            raise ValueError("source_url must use HTTPS")
        if not self.source_revision.strip():
            raise ValueError("source_revision must not be empty")
        if self.size_bytes <= 0:
            raise ValueError("size_bytes must be positive")
        if self.digest_algorithm not in {"sha256", "sha384"}:
            raise ValueError("unsupported digest algorithm")
        expected_length = 64 if self.digest_algorithm == "sha256" else 96
        if len(self.digest) != expected_length:
            raise ValueError("digest has unexpected length")
        try:
            int(self.digest, 16)
        except ValueError as exc:
            raise ValueError("digest must be hexadecimal") from exc
        if not self.model_license.strip():
            raise ValueError("model_license must not be empty")
        if not self.training_data_note.strip():
            raise ValueError("training_data_note must not be empty")


ANTI_SPOOF_MN3 = PassivePadAsset(
    asset_id="openvino-anti-spoof-mn3",
    filename="anti-spoof-mn3.onnx",
    source_url=(
        "https://storage.openvinotoolkit.org/repositories/open_model_zoo/public/"
        "2022.1/anti-spoof-mn3/anti-spoof-mn3.onnx"
    ),
    source_revision="open-model-zoo:4d4266fbbb7eb5ab80944c2800d7f304868d573d",
    size_bytes=12_270_179,
    digest_algorithm="sha384",
    digest=(
        "6de4534964b723397b3e8c995cadcf43bc007cc2f9930b95a"
        "e25f76adccece5d1d4d058d0b15117b9e4a9f758424f92a"
    ),
    model_license="MIT",
    training_data_note="Open Model Zoo documents training on CelebA-Spoof.",
)

MINIFASNET_V1SE = PassivePadAsset(
    asset_id="minifasnet-v1se-onnx",
    filename="MiniFASNetV1SE.onnx",
    source_url=(
        "https://github.com/yakhyo/face-anti-spoofing/releases/download/weights/"
        "MiniFASNetV1SE.onnx"
    ),
    source_revision="github-release:271938250:asset:331026162",
    size_bytes=1_742_335,
    digest_algorithm="sha256",
    digest="ebab7f90c7833fbccd46d3a555410e78d969db5438e169b6524be444862b3676",
    model_license="Apache-2.0 lineage",
    training_data_note=(
        "Exact training-dataset provenance for the released MiniFAS weights requires "
        "future commercial-distribution review."
    ),
)

MINIFASNET_V2 = PassivePadAsset(
    asset_id="minifasnet-v2-onnx",
    filename="MiniFASNetV2.onnx",
    source_url=(
        "https://github.com/yakhyo/face-anti-spoofing/releases/download/weights/"
        "MiniFASNetV2.onnx"
    ),
    source_revision="github-release:271938250:asset:331026163",
    size_bytes=1_743_581,
    digest_algorithm="sha256",
    digest="b32929adc2d9c34b9486f8c4c7bc97c1b69bc0ea9befefc380e4faae4e463907",
    model_license="Apache-2.0 lineage",
    training_data_note=(
        "Exact training-dataset provenance for the released MiniFAS weights requires "
        "future commercial-distribution review."
    ),
)

PASSIVE_PAD_ASSETS = (ANTI_SPOOF_MN3, MINIFASNET_V1SE, MINIFASNET_V2)


class PassivePadAssetCache:
    """External cache that verifies the exact digest published for each PAD asset."""

    def __init__(self, root: str | Path | None = None) -> None:
        base = Path(root) if root is not None else default_model_cache_dir()
        self.root = base / "passive-pad"

    def path_for(self, asset: PassivePadAsset) -> Path:
        return self.root / asset.asset_id / asset.filename

    def verify(self, asset: PassivePadAsset) -> Path:
        path = self.path_for(asset)
        if not path.is_file():
            raise PassivePadAssetIntegrityError(
                f"passive PAD asset is missing: {asset.asset_id}"
            )
        size, digest = _file_identity(path, asset.digest_algorithm)
        if size != asset.size_bytes:
            raise PassivePadAssetIntegrityError(
                f"passive PAD asset size mismatch for {asset.asset_id}: {size}"
            )
        if digest != asset.digest:
            raise PassivePadAssetIntegrityError(
                f"passive PAD digest mismatch for {asset.asset_id}: {digest}"
            )
        return path

    def is_valid(self, asset: PassivePadAsset) -> bool:
        try:
            self.verify(asset)
        except PassivePadAssetIntegrityError:
            return False
        return True

    def fetch(self, asset: PassivePadAsset, *, timeout_seconds: float = 120.0) -> Path:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.is_valid(asset):
            return self.path_for(asset)

        target = self.path_for(asset)
        target.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(
            asset.source_url,
            headers={"User-Agent": "JARVIS-V1-passive-pad-fetch/1"},
        )
        temporary_path: Path | None = None
        try:
            with (
                urllib.request.urlopen(request, timeout=timeout_seconds) as response,
                tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=f".{asset.filename}.",
                    suffix=".tmp",
                    dir=target.parent,
                    delete=False,
                ) as temporary,
            ):
                temporary_path = Path(temporary.name)
                digest = hashlib.new(asset.digest_algorithm)
                total = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > asset.size_bytes:
                        raise PassivePadAssetIntegrityError(
                            f"download exceeded expected size for {asset.asset_id}"
                        )
                    digest.update(chunk)
                    temporary.write(chunk)
            if total != asset.size_bytes:
                raise PassivePadAssetIntegrityError(
                    f"download size mismatch for {asset.asset_id}: {total}"
                )
            if digest.hexdigest() != asset.digest:
                raise PassivePadAssetIntegrityError(
                    f"download digest mismatch for {asset.asset_id}: "
                    f"{digest.hexdigest()}"
                )
            os.replace(temporary_path, target)
            temporary_path = None
            return self.verify(asset)
        except (OSError, urllib.error.URLError) as exc:
            raise PassivePadAssetError(
                f"passive PAD download failed for {asset.asset_id}"
            ) from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def _file_identity(path: Path, algorithm: str) -> tuple[int, str]:
    digest = hashlib.new(algorithm)
    total = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
    return total, digest.hexdigest()
