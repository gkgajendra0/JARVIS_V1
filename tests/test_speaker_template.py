from __future__ import annotations

import numpy as np
import pytest

from jarvis.identity.speaker_template import (
    SpeakerPrototypeSet,
    SpeakerTemplateError,
    build_speaker_prototype_set,
    deserialize_speaker_prototype_set,
    serialize_speaker_prototype_set,
)


def _speaker_embeddings(count: int = 16, dimension: int = 12) -> list[np.ndarray]:
    rng = np.random.default_rng(17)
    base = rng.normal(size=dimension).astype(np.float32)
    base /= np.linalg.norm(base)
    values: list[np.ndarray] = []
    for _ in range(count):
        item = base + rng.normal(scale=0.08, size=dimension).astype(np.float32)
        item /= np.linalg.norm(item)
        values.append(item)
    return values


def test_speaker_prototype_set_is_bounded_normalized_and_round_trips() -> None:
    template = build_speaker_prototype_set(
        _speaker_embeddings(),
        prototype_count=6,
    )
    assert template.prototype_count == 6
    assert template.embedding_dimension == 12
    assert template.source_sample_count == 16
    np.testing.assert_allclose(
        np.linalg.norm(template.prototypes, axis=1),
        np.ones(6),
        atol=1e-5,
    )

    payload = serialize_speaker_prototype_set(template)
    restored = deserialize_speaker_prototype_set(payload)
    np.testing.assert_allclose(restored, template.prototypes, atol=1e-6)


def test_speaker_prototype_selection_requires_enough_diverse_samples() -> None:
    with pytest.raises(SpeakerTemplateError, match="at least twice"):
        build_speaker_prototype_set(_speaker_embeddings(count=7), prototype_count=4)


def test_speaker_template_rejects_tampered_numeric_body() -> None:
    template = build_speaker_prototype_set(_speaker_embeddings(), prototype_count=4)
    payload = bytearray(serialize_speaker_prototype_set(template))
    payload[-1] ^= 0x7F
    with pytest.raises(SpeakerTemplateError):
        deserialize_speaker_prototype_set(bytes(payload))


def test_speaker_serializer_rejects_non_finite_prototype() -> None:
    prototypes = np.eye(2, dtype=np.float32)
    prototypes[0, 0] = np.nan
    template = SpeakerPrototypeSet(
        prototypes=prototypes,
        source_sample_count=4,
        inlier_sample_count=4,
        centroid_inlier_floor=0.0,
        coverage_minimum=0.0,
        coverage_p05=0.0,
        coverage_median=0.0,
    )
    with pytest.raises(SpeakerTemplateError, match="finite"):
        serialize_speaker_prototype_set(template)
