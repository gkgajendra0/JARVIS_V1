from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlparse


class ModelAssetError(RuntimeError):
    pass


class ModelManifestError(ModelAssetError):
    pass


class ModelAssetIntegrityError(ModelAssetError):
    pass


@dataclass(frozen=True, slots=True)
class ModelAssetManifest:
    asset_id: str
    role: str
    filename: str
    source_path: str
    source_url: str
    source_revision: str
    sha256: str
    size_bytes: int
    code_license: str
    model_license: str
    provenance_status: str
    training_data_note: str
    commercial_distribution_status: str
    deployment_status: str
    minimum_opencv_version: str
    backend: str
    calibration_status: str
    reference_thresholds: dict[str, float]

    def __post_init__(self) -> None:
        required = {
            "asset_id": self.asset_id,
            "role": self.role,
            "filename": self.filename,
            "source_path": self.source_path,
            "source_url": self.source_url,
            "source_revision": self.source_revision,
            "code_license": self.code_license,
            "model_license": self.model_license,
            "provenance_status": self.provenance_status,
            "training_data_note": self.training_data_note,
            "commercial_distribution_status": self.commercial_distribution_status,
            "deployment_status": self.deployment_status,
            "minimum_opencv_version": self.minimum_opencv_version,
            "backend": self.backend,
            "calibration_status": self.calibration_status,
        }
        for field_name, value in required.items():
            if not value.strip():
                raise ModelManifestError(f"{field_name} must not be empty")
        if Path(self.filename).name != self.filename:
            raise ModelManifestError("model filename must be a basename")
        if len(self.sha256) != 64:
            raise ModelManifestError("model sha256 must be 64 hexadecimal characters")
        try:
            int(self.sha256, 16)
        except ValueError as exc:
            raise ModelManifestError("model sha256 is not hexadecimal") from exc
        if self.size_bytes <= 0:
            raise ModelManifestError("model size_bytes must be positive")
        parsed = urlparse(self.source_url)
        if parsed.scheme != "https" or parsed.hostname != "github.com":
            raise ModelManifestError("model source_url must use pinned GitHub HTTPS")
        if self.source_revision not in self.source_url:
            raise ModelManifestError("model source_url must contain source_revision")


@dataclass(frozen=True, slots=True)
class FaceModelManifestSet:
    schema_version: int
    source_repository: str
    source_revision: str
    assets: tuple[ModelAssetManifest, ...]

    def by_id(self, asset_id: str) -> ModelAssetManifest:
        for asset in self.assets:
            if asset.asset_id == asset_id:
                return asset
        raise ModelManifestError(f"unknown model asset: {asset_id}")

    def by_role(self, role: str) -> ModelAssetManifest:
        matches = [asset for asset in self.assets if asset.role == role]
        if len(matches) != 1:
            raise ModelManifestError(
                f"expected exactly one model asset for role {role!r}, got {len(matches)}"
            )
        return matches[0]


def load_default_face_model_manifest() -> FaceModelManifestSet:
    manifest_resource = resources.files("jarvis.identity").joinpath(
        "manifests/step3_face_models.json"
    )
    with manifest_resource.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return _parse_manifest_set(payload)


def _parse_manifest_set(payload: object) -> FaceModelManifestSet:
    if not isinstance(payload, dict):
        raise ModelManifestError("model manifest root must be an object")
    if payload.get("schema_version") != 1:
        raise ModelManifestError("unsupported model manifest schema_version")
    repository = payload.get("source_repository")
    revision = payload.get("source_revision")
    raw_assets = payload.get("assets")
    if not isinstance(repository, str) or not repository.strip():
        raise ModelManifestError("source_repository must not be empty")
    if not isinstance(revision, str) or len(revision) != 40:
        raise ModelManifestError("source_revision must be a 40-character commit SHA")
    if not isinstance(raw_assets, list) or not raw_assets:
        raise ModelManifestError("assets must be a non-empty list")

    assets: list[ModelAssetManifest] = []
    seen_ids: set[str] = set()
    for raw in raw_assets:
        if not isinstance(raw, dict):
            raise ModelManifestError("each model asset must be an object")
        reference_thresholds = raw.get("reference_thresholds", {})
        if not isinstance(reference_thresholds, dict):
            raise ModelManifestError("reference_thresholds must be an object")
        thresholds: dict[str, float] = {}
        for name, value in reference_thresholds.items():
            if not isinstance(name, str) or not isinstance(value, int | float):
                raise ModelManifestError("reference thresholds must be numeric")
            thresholds[name] = float(value)
        asset = ModelAssetManifest(
            asset_id=_string_field(raw, "asset_id"),
            role=_string_field(raw, "role"),
            filename=_string_field(raw, "filename"),
            source_path=_string_field(raw, "source_path"),
            source_url=_string_field(raw, "source_url"),
            source_revision=revision,
            sha256=_string_field(raw, "sha256").lower(),
            size_bytes=_positive_int_field(raw, "size_bytes"),
            code_license=_string_field(raw, "code_license"),
            model_license=_string_field(raw, "model_license"),
            provenance_status=_string_field(raw, "provenance_status"),
            training_data_note=_string_field(raw, "training_data_note"),
            commercial_distribution_status=_string_field(
                raw, "commercial_distribution_status"
            ),
            deployment_status=_string_field(raw, "deployment_status"),
            minimum_opencv_version=_string_field(raw, "minimum_opencv_version"),
            backend=_string_field(raw, "backend"),
            calibration_status=_string_field(raw, "calibration_status"),
            reference_thresholds=thresholds,
        )
        if asset.asset_id in seen_ids:
            raise ModelManifestError(f"duplicate model asset_id: {asset.asset_id}")
        seen_ids.add(asset.asset_id)
        assets.append(asset)
    return FaceModelManifestSet(
        schema_version=1,
        source_repository=repository,
        source_revision=revision,
        assets=tuple(assets),
    )


def _string_field(payload: dict[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str):
        raise ModelManifestError(f"{name} must be a string")
    return value


def _positive_int_field(payload: dict[str, object], name: str) -> int:
    value = payload.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ModelManifestError(f"{name} must be a positive integer")
    return value


def default_model_cache_dir() -> Path:
    configured = os.getenv("JARVIS_MODEL_CACHE")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "JARVIS" / "models"
    xdg_cache = os.getenv("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "jarvis" / "models"
    return Path.home() / ".cache" / "jarvis" / "models"


UrlOpener = Callable[..., BinaryIO]


class ModelAssetCache:
    """External model cache with exact byte-count and SHA-256 verification."""

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_model_cache_dir()

    def path_for(self, asset: ModelAssetManifest) -> Path:
        return self.root / asset.asset_id / asset.filename

    def verify(self, asset: ModelAssetManifest) -> Path:
        path = self.path_for(asset)
        if not path.is_file():
            raise ModelAssetIntegrityError(f"model asset is missing: {asset.asset_id}")
        size, digest = _file_identity(path)
        if size != asset.size_bytes:
            raise ModelAssetIntegrityError(
                f"model asset size mismatch for {asset.asset_id}: {size}"
            )
        if digest != asset.sha256:
            raise ModelAssetIntegrityError(
                f"model asset sha256 mismatch for {asset.asset_id}: {digest}"
            )
        return path

    def is_valid(self, asset: ModelAssetManifest) -> bool:
        try:
            self.verify(asset)
        except ModelAssetIntegrityError:
            return False
        return True

    def fetch(
        self,
        asset: ModelAssetManifest,
        *,
        timeout_seconds: float = 120.0,
        opener: UrlOpener = urllib.request.urlopen,
    ) -> Path:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.is_valid(asset):
            return self.path_for(asset)

        target = self.path_for(asset)
        target.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(
            asset.source_url,
            headers={"User-Agent": "JARVIS-V1-model-fetch/1"},
        )
        temporary_path: Path | None = None
        try:
            with (
                opener(request, timeout=timeout_seconds) as response,
                tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=f".{asset.filename}.",
                    suffix=".tmp",
                    dir=target.parent,
                    delete=False,
                ) as temporary,
            ):
                temporary_path = Path(temporary.name)
                digest = hashlib.sha256()
                total = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > asset.size_bytes:
                        raise ModelAssetIntegrityError(
                            f"download exceeded expected size for {asset.asset_id}"
                        )
                    digest.update(chunk)
                    temporary.write(chunk)
            if total != asset.size_bytes:
                raise ModelAssetIntegrityError(
                    f"download size mismatch for {asset.asset_id}: {total}"
                )
            actual_sha256 = digest.hexdigest()
            if actual_sha256 != asset.sha256:
                raise ModelAssetIntegrityError(
                    f"download sha256 mismatch for {asset.asset_id}: {actual_sha256}"
                )
            os.replace(temporary_path, target)
            temporary_path = None
            return self.verify(asset)
        except OSError as exc:
            raise ModelAssetError(
                f"model download failed for {asset.asset_id}"
            ) from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def _file_identity(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
    return total, digest.hexdigest()
