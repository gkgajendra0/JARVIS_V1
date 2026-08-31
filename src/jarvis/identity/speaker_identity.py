from __future__ import annotations

import hashlib
import math
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

import numpy as np

from ..authority import EvidenceModality, EvidenceVerdict, IdentityEvidence

CAMPP_MODEL_FILENAME = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"
CAMPP_MODEL_SHA256 = "aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2"
CAMPP_MODEL_SIZE_BYTES = 28_281_164
CAMPP_PROVIDER_ID = "jarvis-sherpa-campp-shadow-v1"


class SpeakerShadowState(str, Enum):
    INSUFFICIENT = "insufficient"
    PROFILE_BUILDING = "profile_building"
    SCORED = "scored"


@dataclass(frozen=True, slots=True)
class SpeakerQualityPolicy:
    """Conservative quality gate derived from the first real JARVIS bake-off."""

    min_duration_seconds: float = 1.5
    min_rms_dbfs: float = -45.0
    max_clipping_ratio: float = 0.005

    def __post_init__(self) -> None:
        if self.min_duration_seconds <= 0:
            raise ValueError("speaker min duration must be positive")
        if not math.isfinite(self.min_rms_dbfs) or self.min_rms_dbfs >= 0:
            raise ValueError("speaker RMS floor must be a finite negative dBFS value")
        if not 0.0 <= self.max_clipping_ratio <= 1.0:
            raise ValueError("speaker clipping ratio must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class SpeakerSegmentQuality:
    duration_seconds: float
    rms_dbfs: float
    peak_dbfs: float
    clipping_ratio: float
    accepted: bool
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SpeakerShadowAssessment:
    session_id: str
    audio_turn_id: str
    provider_id: str
    observed_at_monotonic: float
    state: SpeakerShadowState
    quality: SpeakerSegmentQuality
    prototype_count: int
    max_reference_cosine: float | None
    reason_codes: tuple[str, ...]

    def to_identity_evidence(
        self,
        *,
        evidence_ttl_seconds: float = 2.0,
    ) -> IdentityEvidence:
        """Emit typed speaker evidence without granting an identity verdict yet."""
        if evidence_ttl_seconds <= 0:
            raise ValueError("speaker evidence TTL must be positive")
        reasons = tuple(
            dict.fromkeys((*self.reason_codes, "speaker_shadow_only_no_threshold"))
        )
        return IdentityEvidence(
            evidence_id=str(uuid.uuid4()),
            session_id=self.session_id,
            modality=EvidenceModality.SPEAKER_MATCH,
            observed_at_monotonic=self.observed_at_monotonic,
            expires_at_monotonic=self.observed_at_monotonic + evidence_ttl_seconds,
            source_id=f"audio-turn:{self.audio_turn_id}",
            provider_id=self.provider_id,
            verdict=EvidenceVerdict.INSUFFICIENT,
            audio_turn_id=self.audio_turn_id,
            reason_codes=reasons,
        )


class SpeakerEmbeddingProvider(Protocol):
    provider_id: str
    dimension: int

    def embed(
        self,
        samples: np.ndarray,
        *,
        sample_rate: int,
    ) -> np.ndarray | None: ...


class SherpaCamPlusEmbeddingProvider:
    """Exact-frontend CAM++ provider using sherpa-onnx rather than custom fbank code."""

    provider_id = CAMPP_PROVIDER_ID

    def __init__(
        self,
        model_path: str | Path,
        *,
        num_threads: int = 1,
        provider: str = "cpu",
        debug: bool = False,
        verify_asset: bool = True,
    ) -> None:
        if num_threads <= 0:
            raise ValueError("speaker model num_threads must be positive")
        path = Path(model_path).expanduser()
        if not path.is_file():
            raise FileNotFoundError(path)
        if verify_asset:
            _verify_campp_asset(path)
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError(
                "sherpa-onnx is required for speaker shadow mode; "
                'install with: python -m pip install -e ".[speaker]"'
            ) from exc

        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(path),
            num_threads=num_threads,
            debug=debug,
            provider=provider,
        )
        if not config.validate():
            raise RuntimeError(f"invalid sherpa CAM++ speaker model config: {config}")
        self.model_path = path
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        self.dimension = int(self._extractor.dim)

    def embed(
        self,
        samples: np.ndarray,
        *,
        sample_rate: int,
    ) -> np.ndarray | None:
        pcm = _validate_pcm(samples, sample_rate)
        stream = self._extractor.create_stream()
        stream.accept_waveform(
            sample_rate=sample_rate,
            waveform=pcm.astype(np.float32) / 32768.0,
        )
        stream.input_finished()
        if not self._extractor.is_ready(stream):
            return None
        embedding = np.asarray(self._extractor.compute(stream), dtype=np.float32)
        return normalize_embedding(embedding)


class SessionSpeakerPrototypeBank:
    """Bounded, memory-only prototype set for one trusted session."""

    def __init__(self, *, dimension: int, max_prototypes: int = 8) -> None:
        if dimension <= 0:
            raise ValueError("speaker prototype dimension must be positive")
        if max_prototypes < 1:
            raise ValueError("speaker max_prototypes must be positive")
        self.dimension = dimension
        self.max_prototypes = max_prototypes
        self._prototypes: list[np.ndarray] = []

    @property
    def count(self) -> int:
        return len(self._prototypes)

    def clear(self) -> None:
        self._prototypes.clear()

    def add(self, embedding: np.ndarray) -> bool:
        vector = normalize_embedding(embedding)
        if vector.size != self.dimension:
            raise ValueError("speaker prototype dimension mismatch")
        if self.count >= self.max_prototypes:
            return False
        self._prototypes.append(vector.copy())
        return True

    def score(self, embedding: np.ndarray) -> float | None:
        if not self._prototypes:
            return None
        vector = normalize_embedding(embedding)
        if vector.size != self.dimension:
            raise ValueError("speaker embedding dimension mismatch")
        matrix = np.stack(self._prototypes)
        return float(np.max(matrix @ vector))


class SpeakerShadowSession:
    """Passive, non-persistent speaker corroboration for one JARVIS session.

    `trusted_owner_context` must come from a separate accepted owner context
    (for example face+liveness bound to the same live session). The speaker
    model never bootstraps itself from its own similarity score.
    """

    def __init__(
        self,
        *,
        session_id: str,
        embedding_provider: SpeakerEmbeddingProvider,
        quality_policy: SpeakerQualityPolicy | None = None,
        max_prototypes: int = 8,
    ) -> None:
        if not session_id.strip():
            raise ValueError("speaker session_id must not be empty")
        self.session_id = session_id
        self.embedding_provider = embedding_provider
        self.quality_policy = quality_policy or SpeakerQualityPolicy()
        self._prototypes = SessionSpeakerPrototypeBank(
            dimension=embedding_provider.dimension,
            max_prototypes=max_prototypes,
        )

    @property
    def prototype_count(self) -> int:
        return self._prototypes.count

    def clear(self) -> None:
        self._prototypes.clear()

    def observe_segment(
        self,
        samples: np.ndarray,
        *,
        sample_rate: int,
        audio_turn_id: str,
        trusted_owner_context: bool,
        observed_at_monotonic: float | None = None,
    ) -> SpeakerShadowAssessment:
        if not audio_turn_id.strip():
            raise ValueError("audio_turn_id must not be empty")
        observed_at = (
            time.monotonic() if observed_at_monotonic is None else observed_at_monotonic
        )
        if observed_at < 0:
            raise ValueError("speaker observation time must be non-negative")

        quality = assess_speaker_segment(
            samples,
            sample_rate=sample_rate,
            policy=self.quality_policy,
        )
        if not quality.accepted:
            return SpeakerShadowAssessment(
                session_id=self.session_id,
                audio_turn_id=audio_turn_id,
                provider_id=self.embedding_provider.provider_id,
                observed_at_monotonic=observed_at,
                state=SpeakerShadowState.INSUFFICIENT,
                quality=quality,
                prototype_count=self.prototype_count,
                max_reference_cosine=None,
                reason_codes=quality.reason_codes,
            )

        embedding = self.embedding_provider.embed(samples, sample_rate=sample_rate)
        if embedding is None:
            return SpeakerShadowAssessment(
                session_id=self.session_id,
                audio_turn_id=audio_turn_id,
                provider_id=self.embedding_provider.provider_id,
                observed_at_monotonic=observed_at,
                state=SpeakerShadowState.INSUFFICIENT,
                quality=quality,
                prototype_count=self.prototype_count,
                max_reference_cosine=None,
                reason_codes=("speaker_embedding_not_ready",),
            )

        score = self._prototypes.score(embedding)
        admitted = False
        if trusted_owner_context:
            admitted = self._prototypes.add(embedding)

        if score is None:
            state = (
                SpeakerShadowState.PROFILE_BUILDING
                if admitted
                else SpeakerShadowState.INSUFFICIENT
            )
            reasons = (
                ("trusted_owner_shadow_prototype_admitted",)
                if admitted
                else ("speaker_shadow_has_no_trusted_prototypes",)
            )
        else:
            state = SpeakerShadowState.SCORED
            reasons_list = ["speaker_shadow_score_observed_no_threshold"]
            if admitted:
                reasons_list.append("trusted_owner_shadow_prototype_admitted")
            reasons = tuple(reasons_list)

        return SpeakerShadowAssessment(
            session_id=self.session_id,
            audio_turn_id=audio_turn_id,
            provider_id=self.embedding_provider.provider_id,
            observed_at_monotonic=observed_at,
            state=state,
            quality=quality,
            prototype_count=self.prototype_count,
            max_reference_cosine=score,
            reason_codes=reasons,
        )


def assess_speaker_segment(
    samples: np.ndarray,
    *,
    sample_rate: int,
    policy: SpeakerQualityPolicy | None = None,
) -> SpeakerSegmentQuality:
    policy = policy or SpeakerQualityPolicy()
    pcm = _validate_pcm(samples, sample_rate)
    normalized = pcm.astype(np.float32) / 32768.0
    rms = float(np.sqrt(np.mean(np.square(normalized, dtype=np.float64))))
    peak = float(np.max(np.abs(normalized)))
    clipping_ratio = float(np.mean(np.abs(pcm.astype(np.int32)) >= 32760))
    duration = pcm.size / sample_rate
    rms_dbfs = _amplitude_dbfs(rms)
    peak_dbfs = _amplitude_dbfs(peak)

    reasons: list[str] = []
    if duration < policy.min_duration_seconds:
        reasons.append("speaker_segment_too_short")
    if rms_dbfs < policy.min_rms_dbfs:
        reasons.append("speaker_segment_below_rms_floor")
    if clipping_ratio > policy.max_clipping_ratio:
        reasons.append("speaker_segment_excessive_clipping")

    return SpeakerSegmentQuality(
        duration_seconds=duration,
        rms_dbfs=rms_dbfs,
        peak_dbfs=peak_dbfs,
        clipping_ratio=clipping_ratio,
        accepted=not reasons,
        reason_codes=tuple(reasons),
    )


def normalize_embedding(embedding: np.ndarray) -> np.ndarray:
    vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
    if vector.size == 0 or not np.isfinite(vector).all():
        raise ValueError("speaker embedding must be finite and non-empty")
    norm = float(np.linalg.norm(vector))
    if norm <= 0:
        raise ValueError("speaker embedding norm must be positive")
    return vector / norm


def _validate_pcm(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    pcm = np.asarray(samples)
    if pcm.ndim != 1 or pcm.dtype != np.int16 or pcm.size == 0:
        raise ValueError("speaker PCM must be non-empty one-dimensional int16")
    if sample_rate <= 0:
        raise ValueError("speaker sample_rate must be positive")
    return pcm


def _amplitude_dbfs(amplitude: float) -> float:
    if amplitude <= 0:
        return -120.0
    return max(-120.0, 20.0 * math.log10(amplitude))


def _verify_campp_asset(path: Path) -> None:
    size = path.stat().st_size
    if size != CAMPP_MODEL_SIZE_BYTES:
        raise RuntimeError(
            f"CAM++ model size mismatch: expected {CAMPP_MODEL_SIZE_BYTES}, got {size}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != CAMPP_MODEL_SHA256:
        raise RuntimeError(
            f"CAM++ model sha256 mismatch: expected {CAMPP_MODEL_SHA256}, got {actual}"
        )