from __future__ import annotations

import numpy as np

from jarvis.identity.speaker_shadow import (
    EnrolledSpeakerShadowObserver,
    RuntimeOwnerSpeakerTemplate,
)


class FakeEmbeddingProvider:
    provider_id = "fake"
    dimension = 3

    def __init__(self, embedding: np.ndarray | None) -> None:
        self.embedding = embedding

    def embed(self, samples: np.ndarray, *, sample_rate: int) -> np.ndarray | None:
        del samples, sample_rate
        if self.embedding is None:
            return None
        value = self.embedding.astype(np.float32)
        return value / np.linalg.norm(value)


def _template() -> RuntimeOwnerSpeakerTemplate:
    return RuntimeOwnerSpeakerTemplate(
        template_id="voice-1",
        profile_version=2,
        provider_id="test",
        model_id="test",
        model_version="test",
        model_sha256="0" * 64,
        prototypes=np.asarray(
            [
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
            ],
            dtype=np.float32,
        ),
    )


def test_enrolled_speaker_shadow_scores_without_classifying_or_mutating() -> None:
    provider = FakeEmbeddingProvider(np.asarray([0.9, 0.1, 0.0], dtype=np.float32))
    observer = EnrolledSpeakerShadowObserver(
        template=_template(),
        embedding_provider=provider,  # type: ignore[arg-type]
    )
    result = observer.score(
        np.ones(32_000, dtype=np.int16),
        sample_rate=16_000,
    )
    assert result.state == "scored"
    assert result.max_reference_cosine is not None
    assert result.max_reference_cosine > 0.99
    assert result.reason_codes == ("speaker_shadow_score_observed_no_threshold",)


def test_enrolled_speaker_shadow_fails_insufficient_when_embedding_not_ready() -> None:
    observer = EnrolledSpeakerShadowObserver(
        template=_template(),
        embedding_provider=FakeEmbeddingProvider(None),  # type: ignore[arg-type]
    )
    result = observer.score(
        np.ones(32_000, dtype=np.int16),
        sample_rate=16_000,
    )
    assert result.state == "insufficient"
    assert result.max_reference_cosine is None
    assert result.reason_codes == ("speaker_embedding_not_ready",)
