from __future__ import annotations

import numpy as np
import pytest

from jarvis.authority import EvidenceModality, EvidenceVerdict
from jarvis.identity.speaker_identity import (
    SessionSpeakerPrototypeBank,
    SpeakerQualityPolicy,
    SpeakerShadowSession,
    SpeakerShadowState,
    assess_speaker_segment,
)


class _FakeEmbeddingProvider:
    provider_id = "fake-speaker-provider"
    dimension = 3

    def __init__(self, embeddings: list[np.ndarray | None]) -> None:
        self._embeddings = list(embeddings)

    def embed(
        self,
        samples: np.ndarray,
        *,
        sample_rate: int,
    ) -> np.ndarray | None:
        del samples, sample_rate
        return self._embeddings.pop(0)


def _pcm(
    *,
    seconds: float = 2.0,
    sample_rate: int = 48_000,
    amplitude: int = 4_000,
) -> np.ndarray:
    return np.full(int(seconds * sample_rate), amplitude, dtype=np.int16)


def test_quality_accepts_healthy_two_second_segment() -> None:
    quality = assess_speaker_segment(_pcm(), sample_rate=48_000)
    assert quality.accepted
    assert quality.duration_seconds == pytest.approx(2.0)
    assert quality.rms_dbfs > -45.0
    assert quality.reason_codes == ()


def test_quality_rejects_near_silence_as_insufficient() -> None:
    quality = assess_speaker_segment(
        _pcm(amplitude=5),
        sample_rate=48_000,
    )
    assert not quality.accepted
    assert "speaker_segment_below_rms_floor" in quality.reason_codes


def test_quality_rejects_one_second_turn_by_default() -> None:
    quality = assess_speaker_segment(
        _pcm(seconds=1.0),
        sample_rate=48_000,
    )
    assert not quality.accepted
    assert "speaker_segment_too_short" in quality.reason_codes


def test_quality_rejects_excessive_clipping() -> None:
    quality = assess_speaker_segment(
        np.full(96_000, 32767, dtype=np.int16),
        sample_rate=48_000,
    )
    assert not quality.accepted
    assert "speaker_segment_excessive_clipping" in quality.reason_codes


def test_prototype_bank_is_bounded_and_scores_max_cosine() -> None:
    bank = SessionSpeakerPrototypeBank(dimension=3, max_prototypes=2)
    assert bank.add(np.array([1.0, 0.0, 0.0], dtype=np.float32))
    assert bank.add(np.array([0.0, 1.0, 0.0], dtype=np.float32))
    assert not bank.add(np.array([0.0, 0.0, 1.0], dtype=np.float32))
    assert bank.count == 2
    assert bank.score(np.array([0.9, 0.1, 0.0], dtype=np.float32)) > 0.99


def test_shadow_session_never_bootstraps_from_untrusted_audio() -> None:
    provider = _FakeEmbeddingProvider([np.array([1.0, 0.0, 0.0], dtype=np.float32)])
    session = SpeakerShadowSession(
        session_id="session-1",
        embedding_provider=provider,
    )

    assessment = session.observe_segment(
        _pcm(),
        sample_rate=48_000,
        audio_turn_id="turn-1",
        trusted_owner_context=False,
        observed_at_monotonic=10.0,
    )

    assert assessment.state is SpeakerShadowState.INSUFFICIENT
    assert assessment.prototype_count == 0
    assert assessment.max_reference_cosine is None
    assert "speaker_shadow_has_no_trusted_prototypes" in assessment.reason_codes


def test_shadow_session_builds_only_from_trusted_owner_context_then_scores() -> None:
    provider = _FakeEmbeddingProvider(
        [
            np.array([1.0, 0.0, 0.0], dtype=np.float32),
            np.array([0.99, 0.01, 0.0], dtype=np.float32),
        ]
    )
    session = SpeakerShadowSession(
        session_id="session-1",
        embedding_provider=provider,
    )

    first = session.observe_segment(
        _pcm(),
        sample_rate=48_000,
        audio_turn_id="turn-1",
        trusted_owner_context=True,
        observed_at_monotonic=10.0,
    )
    second = session.observe_segment(
        _pcm(),
        sample_rate=48_000,
        audio_turn_id="turn-2",
        trusted_owner_context=True,
        observed_at_monotonic=12.0,
    )

    assert first.state is SpeakerShadowState.PROFILE_BUILDING
    assert first.prototype_count == 1
    assert first.max_reference_cosine is None
    assert second.state is SpeakerShadowState.SCORED
    assert second.prototype_count == 2
    assert second.max_reference_cosine is not None
    assert second.max_reference_cosine > 0.99


def test_bad_quality_never_calls_embedding_provider() -> None:
    provider = _FakeEmbeddingProvider([])
    session = SpeakerShadowSession(
        session_id="session-1",
        embedding_provider=provider,
        quality_policy=SpeakerQualityPolicy(min_rms_dbfs=-40.0),
    )

    assessment = session.observe_segment(
        _pcm(amplitude=5),
        sample_rate=48_000,
        audio_turn_id="turn-quiet",
        trusted_owner_context=True,
        observed_at_monotonic=10.0,
    )

    assert assessment.state is SpeakerShadowState.INSUFFICIENT
    assert assessment.prototype_count == 0
    assert "speaker_segment_below_rms_floor" in assessment.reason_codes


def test_shadow_identity_evidence_is_always_insufficient() -> None:
    provider = _FakeEmbeddingProvider([np.array([1.0, 0.0, 0.0], dtype=np.float32)])
    session = SpeakerShadowSession(
        session_id="session-1",
        embedding_provider=provider,
    )
    assessment = session.observe_segment(
        _pcm(),
        sample_rate=48_000,
        audio_turn_id="turn-1",
        trusted_owner_context=True,
        observed_at_monotonic=10.0,
    )

    evidence = assessment.to_identity_evidence(evidence_ttl_seconds=2.0)

    assert evidence.modality is EvidenceModality.SPEAKER_MATCH
    assert evidence.verdict is EvidenceVerdict.INSUFFICIENT
    assert evidence.audio_turn_id == "turn-1"
    assert evidence.expires_at_monotonic == pytest.approx(12.0)
    assert "speaker_shadow_only_no_threshold" in evidence.reason_codes
