from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from jarvis.identity.face_template import (
    FACE_TEMPLATE_FORMAT,
    FacePrototypeSet,
    serialize_face_prototype_set,
)
from jarvis.identity.model_assets import load_default_face_model_manifest
from jarvis.identity.owner_template_runtime import (
    OwnerTemplateCompatibilityError,
    load_compatible_owner_face_template,
)
from jarvis.identity.types import (
    BiometricModality,
    DecryptedTemplate,
    TemplateMetadata,
)


class _Store:
    def __init__(self, template: DecryptedTemplate) -> None:
        self.template = template

    def load_template(self, modality: BiometricModality) -> DecryptedTemplate:
        assert modality is BiometricModality.FACE
        return self.template


def _payload() -> bytes:
    prototypes = np.asarray(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    return serialize_face_prototype_set(
        FacePrototypeSet(
            prototypes=prototypes,
            source_sample_count=20,
            inlier_sample_count=18,
            centroid_inlier_floor=0.5,
            coverage_minimum=0.5,
            coverage_p05=0.6,
            coverage_median=0.8,
        )
    )


def _template() -> tuple[DecryptedTemplate, object]:
    asset = load_default_face_model_manifest().by_role("face_recognizer")
    metadata = TemplateMetadata(
        modality=BiometricModality.FACE,
        provider_id="opencv-sface-prototype-set-v1",
        model_id=asset.asset_id,
        model_version=asset.source_revision,
        model_sha256=asset.sha256,
        embedding_dimension=3,
        calibration_version="step3b-owner-positive-baseline-v1",
        enrollment_compatibility_version=f"sface:{asset.sha256}:prototype-set-v1",
        template_format=FACE_TEMPLATE_FORMAT,
    )
    return (
        DecryptedTemplate(
            template_id="template-1",
            profile_version=1,
            metadata=metadata,
            payload=_payload(),
            created_at_epoch=1.0,
        ),
        asset,
    )


def test_compatible_owner_template_loads_prototypes() -> None:
    template, asset = _template()

    loaded = load_compatible_owner_face_template(_Store(template), asset)

    assert loaded.template_id == "template-1"
    assert loaded.profile_version == 1
    assert loaded.prototype_count == 2
    assert loaded.embedding_dimension == 3


def test_model_mismatch_fails_closed() -> None:
    template, asset = _template()
    template = replace(
        template,
        metadata=replace(template.metadata, model_sha256="0" * 64),
    )

    with pytest.raises(OwnerTemplateCompatibilityError, match="model_sha256"):
        load_compatible_owner_face_template(_Store(template), asset)


def test_corrupted_encrypted_payload_fails_after_decrypt_boundary() -> None:
    template, asset = _template()
    template = replace(template, payload=b"not-a-face-template")

    with pytest.raises(OwnerTemplateCompatibilityError, match="payload is invalid"):
        load_compatible_owner_face_template(_Store(template), asset)
