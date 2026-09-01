from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from jarvis.identity.face_template import (
    FACE_TEMPLATE_FORMAT,
    FaceTemplateError,
    deserialize_face_prototype_set,
)
from jarvis.identity.model_assets import ModelAssetManifest
from jarvis.identity.store import SqliteOwnerProfileStore
from jarvis.identity.types import BiometricModality, DecryptedTemplate


class OwnerTemplateCompatibilityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RuntimeOwnerFaceTemplate:
    template_id: str
    profile_version: int
    provider_id: str
    model_id: str
    model_version: str
    model_sha256: str
    prototypes: np.ndarray

    @property
    def prototype_count(self) -> int:
        return int(self.prototypes.shape[0])

    @property
    def embedding_dimension(self) -> int:
        return int(self.prototypes.shape[1])


def load_compatible_owner_face_template(
    store: SqliteOwnerProfileStore,
    recognizer_asset: ModelAssetManifest,
) -> RuntimeOwnerFaceTemplate:
    loaded = store.load_template(BiometricModality.FACE)
    _validate_metadata(loaded, recognizer_asset)
    try:
        prototypes = deserialize_face_prototype_set(loaded.payload)
    except FaceTemplateError as exc:
        raise OwnerTemplateCompatibilityError(
            "encrypted OWNER face template payload is invalid"
        ) from exc
    if prototypes.shape[1] != loaded.metadata.embedding_dimension:
        raise OwnerTemplateCompatibilityError(
            "OWNER face template embedding dimension does not match metadata"
        )
    return RuntimeOwnerFaceTemplate(
        template_id=loaded.template_id,
        profile_version=loaded.profile_version,
        provider_id=loaded.metadata.provider_id,
        model_id=loaded.metadata.model_id,
        model_version=loaded.metadata.model_version,
        model_sha256=loaded.metadata.model_sha256.lower(),
        prototypes=prototypes,
    )


def _validate_metadata(
    loaded: DecryptedTemplate,
    recognizer_asset: ModelAssetManifest,
) -> None:
    metadata = loaded.metadata
    expected_compatibility = f"sface:{recognizer_asset.sha256}:prototype-set-v1"
    mismatches: list[str] = []
    if metadata.modality is not BiometricModality.FACE:
        mismatches.append("modality")
    if metadata.provider_id != "opencv-sface-prototype-set-v1":
        mismatches.append("provider_id")
    if metadata.model_id != recognizer_asset.asset_id:
        mismatches.append("model_id")
    if metadata.model_version != recognizer_asset.source_revision:
        mismatches.append("model_version")
    if metadata.model_sha256.lower() != recognizer_asset.sha256.lower():
        mismatches.append("model_sha256")
    if metadata.template_format != FACE_TEMPLATE_FORMAT:
        mismatches.append("template_format")
    if metadata.enrollment_compatibility_version != expected_compatibility:
        mismatches.append("enrollment_compatibility_version")
    if mismatches:
        joined = ", ".join(mismatches)
        raise OwnerTemplateCompatibilityError(
            f"OWNER face template is incompatible with current SFace runtime: {joined}"
        )
