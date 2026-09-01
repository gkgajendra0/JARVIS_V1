from __future__ import annotations

import math

import numpy as np
import pytest

from jarvis.identity.face_template import (
    FaceTemplateError,
    build_face_prototype_set,
    deserialize_face_prototype_set,
    serialize_face_prototype_set,
)


def _feature(angle: float, *, dimension: int = 128) -> np.ndarray:
    vector = np.zeros((1, dimension), dtype=np.float32)
    vector[0, 0] = math.cos(angle)
    vector[0, 1] = math.sin(angle)
    return vector


def test_prototype_selection_is_deterministic_and_covers_samples() -> None:
    features = [_feature(-0.7 + (1.4 * index / 79)) for index in range(80)]

    first = build_face_prototype_set(features, prototype_count=8)
    second = build_face_prototype_set(features, prototype_count=8)

    assert first.prototypes.shape == (8, 128)
    assert np.allclose(first.prototypes, second.prototypes)
    assert first.source_sample_count == 80
    assert first.inlier_sample_count >= 72
    assert first.coverage_median > 0.95
    assert first.coverage_p05 > 0.90


def test_face_template_binary_round_trip_preserves_prototypes() -> None:
    features = [_feature(-0.5 + (1.0 * index / 63)) for index in range(64)]
    template = build_face_prototype_set(features, prototype_count=6)

    payload = serialize_face_prototype_set(template)
    restored = deserialize_face_prototype_set(payload)

    assert restored.shape == (6, 128)
    assert np.allclose(restored, template.prototypes, atol=1e-6)
    assert np.allclose(np.linalg.norm(restored, axis=1), 1.0, atol=1e-5)


def test_face_template_rejects_truncated_payload() -> None:
    features = [_feature(-0.4 + (0.8 * index / 47)) for index in range(48)]
    template = build_face_prototype_set(features, prototype_count=4)
    payload = serialize_face_prototype_set(template)

    with pytest.raises(FaceTemplateError, match="size does not match"):
        deserialize_face_prototype_set(payload[:-4])


def test_prototype_selection_rejects_too_few_samples() -> None:
    features = [_feature(0.01 * index) for index in range(7)]

    with pytest.raises(FaceTemplateError, match="twice the prototype count"):
        build_face_prototype_set(features, prototype_count=4)
