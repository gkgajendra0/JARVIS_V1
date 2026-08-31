from __future__ import annotations

import hashlib
import logging
import math
import threading
from collections import deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import cv2
import numpy as np

from jarvis.identity.speaker_turn import SpeakerTurnAudio
from jarvis.vision.camera import CapturedFrame
from jarvis.vision.framing import HeadFirstFramingPolicy
from jarvis.vision.models import BoundingBox, TargetState
from jarvis.vision.runtime import VisionSnapshot

LOGGER = logging.getLogger(__name__)

LR_ASD_SOURCE_COMMIT = "1b6dcd2d8fc2895683de6508ec6294ec47d388ca"
LR_ASD_AVA_FILENAME = "pretrain_AVA.model"
LR_ASD_AVA_SIZE_BYTES = 3_426_337
LR_ASD_AVA_GIT_BLOB_SHA1 = "d724be582f6d34f1b099657235dedafa0668fd82"
LR_ASD_PROVIDER_ID = "jarvis-lr-asd-ava-shadow-v1"
LR_ASD_AUDIO_RATE = 16_000
LR_ASD_VISUAL_FPS = 25
LR_ASD_VISUAL_SIZE = 112


class ActiveSpeakerState(str, Enum):
    SCORED = "scored"
    INSUFFICIENT = "insufficient"
    AMBIGUOUS = "ambiguous"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ActiveSpeakerVisualSample:
    frame_id: int
    observed_at_monotonic: float
    visual_track_id: int
    image: np.ndarray

    def __post_init__(self) -> None:
        if self.frame_id < 0:
            raise ValueError("active-speaker frame_id must be non-negative")
        if self.observed_at_monotonic < 0:
            raise ValueError("active-speaker visual timestamp must be non-negative")
        if self.visual_track_id < 0:
            raise ValueError("active-speaker visual track id must be non-negative")
        if self.image.shape != (LR_ASD_VISUAL_SIZE, LR_ASD_VISUAL_SIZE):
            raise ValueError("LR-ASD visual sample must be 112x112 grayscale")
        if self.image.dtype != np.uint8:
            raise ValueError("LR-ASD visual sample must use uint8 pixels")


@dataclass(frozen=True, slots=True)
class ActiveSpeakerVisualWindow:
    visual_track_id: int
    start_monotonic: float
    end_monotonic: float
    frames: np.ndarray
    source_sample_count: int
    unique_source_frames: int
    source_fps: float
    maximum_source_gap_seconds: float

    def __post_init__(self) -> None:
        if self.end_monotonic <= self.start_monotonic:
            raise ValueError("active-speaker visual window must have positive duration")
        if self.frames.ndim != 3 or self.frames.shape[1:] != (
            LR_ASD_VISUAL_SIZE,
            LR_ASD_VISUAL_SIZE,
        ):
            raise ValueError(
                "active-speaker window must contain 112x112 grayscale frames"
            )
        if self.frames.dtype != np.uint8:
            raise ValueError("active-speaker visual window must use uint8 frames")
        if not math.isfinite(self.source_fps) or self.source_fps <= 0:
            raise ValueError("active-speaker source fps must be positive and finite")

    @property
    def duration_seconds(self) -> float:
        return self.end_monotonic - self.start_monotonic


@dataclass(frozen=True, slots=True)
class ActiveSpeakerAssessment:
    provider_id: str
    state: ActiveSpeakerState
    audio_turn_id: str
    windows_session_id: str
    visual_track_id: int
    start_monotonic: float
    end_monotonic: float
    visual_frames: int
    unique_visual_frames: int
    audio_feature_frames: int
    mean_score: float | None
    median_score: float | None
    minimum_score: float | None
    maximum_score: float | None
    reason_codes: tuple[str, ...]

    @property
    def active_speaker_confirmed(self) -> bool:
        """Threshold promotion is deliberately disabled until real-machine acceptance."""
        return False


class ActiveSpeakerVisualBuffer:
    """Cheap memory-only LR-ASD visual ring fed by exact canonical frame/snapshot pairs."""

    def __init__(
        self,
        *,
        max_seconds: float = 16.0,
        framing_policy: HeadFirstFramingPolicy | None = None,
        crop_scale: float = 1.35,
    ) -> None:
        if max_seconds <= 0:
            raise ValueError("active-speaker visual buffer duration must be positive")
        if not 1.0 <= crop_scale <= 2.0:
            raise ValueError("active-speaker crop scale must be in [1, 2]")
        self.max_seconds = max_seconds
        self.framing_policy = framing_policy or HeadFirstFramingPolicy()
        self.crop_scale = crop_scale
        self._lock = threading.RLock()
        self._samples: deque[ActiveSpeakerVisualSample] = deque()

    def observe(self, frame: CapturedFrame, snapshot: VisionSnapshot) -> None:
        if frame.frame_id != snapshot.frame_id:
            return
        selected = self._select_target(snapshot)
        if selected is None:
            return
        target, head = selected
        image = _normalized_head_crop(
            frame.image,
            head.bounds,
            crop_scale=self.crop_scale,
        )
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(
            gray,
            (LR_ASD_VISUAL_SIZE, LR_ASD_VISUAL_SIZE),
            interpolation=cv2.INTER_AREA,
        )
        sample = ActiveSpeakerVisualSample(
            frame_id=frame.frame_id,
            observed_at_monotonic=frame.captured_at,
            visual_track_id=target.track_id,
            image=np.ascontiguousarray(gray, dtype=np.uint8),
        )
        with self._lock:
            self._samples.append(sample)
            cutoff = frame.captured_at - self.max_seconds
            while self._samples and self._samples[0].observed_at_monotonic < cutoff:
                self._samples.popleft()

    def close(self) -> None:
        self.clear()

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()

    def build_window(
        self,
        *,
        visual_track_id: int,
        start_monotonic: float,
        end_monotonic: float,
        max_duration_seconds: float = 2.0,
        minimum_source_frames: int = 5,
        maximum_source_gap_seconds: float = 0.35,
        maximum_edge_gap_seconds: float = 0.15,
    ) -> ActiveSpeakerVisualWindow | None:
        if end_monotonic <= start_monotonic:
            return None
        if max_duration_seconds <= 0:
            raise ValueError("active-speaker max window duration must be positive")
        if maximum_edge_gap_seconds <= 0:
            raise ValueError("active-speaker edge gap must be positive")
        window_start = max(start_monotonic, end_monotonic - max_duration_seconds)
        with self._lock:
            candidates = tuple(
                sample
                for sample in self._samples
                if sample.visual_track_id == visual_track_id
                and window_start <= sample.observed_at_monotonic <= end_monotonic
            )
        if len(candidates) < minimum_source_frames:
            return None

        times = np.asarray(
            [sample.observed_at_monotonic for sample in candidates], dtype=np.float64
        )
        start_gap = float(times[0] - window_start)
        end_gap = float(end_monotonic - times[-1])
        if start_gap > maximum_edge_gap_seconds or end_gap > maximum_edge_gap_seconds:
            return None
        gaps = np.diff(times)
        maximum_gap = float(np.max(gaps)) if gaps.size else 0.0
        if maximum_gap > maximum_source_gap_seconds:
            return None
        span = float(times[-1] - times[0])
        if span <= 0:
            return None
        source_fps = (len(candidates) - 1) / span
        if not 5.0 <= source_fps <= 60.0:
            return None

        frame_ids = {sample.frame_id for sample in candidates}
        return ActiveSpeakerVisualWindow(
            visual_track_id=visual_track_id,
            start_monotonic=window_start,
            end_monotonic=end_monotonic,
            frames=np.stack([sample.image for sample in candidates]),
            source_sample_count=len(candidates),
            unique_source_frames=len(frame_ids),
            source_fps=source_fps,
            maximum_source_gap_seconds=maximum_gap,
        )

    def _select_target(
        self, snapshot: VisionSnapshot
    ) -> tuple[TargetState, object] | None:
        heads = list(snapshot.heads)
        target = snapshot.target
        if target is not None and target.visible:
            head = self.framing_policy.associated_head(target, heads)
            return (target, head) if head is not None else None

        candidates: list[tuple[TargetState, object]] = []
        for track in snapshot.tracks:
            candidate = TargetState(track_id=track.track_id, track=track)
            head = self.framing_policy.associated_head(candidate, heads)
            if head is not None:
                candidates.append((candidate, head))
        return candidates[0] if len(candidates) == 1 else None


class LrAsdActiveSpeakerProvider:
    """Inference-only LR-ASD provider using the official model frontend contract."""

    provider_id = LR_ASD_PROVIDER_ID

    def __init__(self, model_path: str | Path, *, device: str | None = None) -> None:
        self.model_path = Path(model_path)
        _verify_lr_asd_asset(self.model_path)

        import torch

        from jarvis.identity.lr_asd_model import LrAsdInferenceModel

        selected_device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.device = torch.device(selected_device)
        model = LrAsdInferenceModel()
        loaded = torch.load(self.model_path, map_location="cpu", weights_only=True)
        if not isinstance(loaded, dict):
            raise TypeError("LR-ASD checkpoint did not contain a state dictionary")
        normalized = {
            str(name).removeprefix("module."): value for name, value in loaded.items()
        }
        model.load_state_dict(normalized, strict=True)
        model.eval()
        self.model = model.to(self.device)
        self._inference_lock = threading.Lock()
        LOGGER.info("LR-ASD active-speaker provider loaded on %s", self.device)

    def assess(
        self,
        turn: SpeakerTurnAudio,
        visual: ActiveSpeakerVisualWindow,
        *,
        audio_turn_id: str,
        windows_session_id: str,
    ) -> ActiveSpeakerAssessment:
        if not audio_turn_id.strip() or not windows_session_id.strip():
            raise ValueError(
                "active-speaker turn/session identifiers must not be empty"
            )
        if turn.start_monotonic is None or turn.end_monotonic is None:
            return _insufficient_assessment(
                self.provider_id,
                audio_turn_id,
                windows_session_id,
                visual,
                "active_speaker_audio_timestamps_missing",
            )

        overlap_start = max(turn.start_monotonic, visual.start_monotonic)
        overlap_end = min(turn.end_monotonic, visual.end_monotonic)
        if overlap_end <= overlap_start:
            return _insufficient_assessment(
                self.provider_id,
                audio_turn_id,
                windows_session_id,
                visual,
                "active_speaker_audio_visual_no_overlap",
            )

        audio = _slice_turn_audio(turn, overlap_start, overlap_end)
        if audio.size == 0:
            return _insufficient_assessment(
                self.provider_id,
                audio_turn_id,
                windows_session_id,
                visual,
                "active_speaker_audio_overlap_empty",
            )
        if visual.duration_seconds < 1.0 or len(visual.frames) < 5:
            return _insufficient_assessment(
                self.provider_id,
                audio_turn_id,
                windows_session_id,
                visual,
                "active_speaker_window_below_one_second",
            )

        audio_16k = _resample_audio(audio, turn.sample_rate, LR_ASD_AUDIO_RATE)
        features = _mfcc_features(audio_16k, visual.source_fps)
        if features.size == 0:
            return _insufficient_assessment(
                self.provider_id,
                audio_turn_id,
                windows_session_id,
                visual,
                "active_speaker_audio_features_empty",
            )
        visual_frames = visual.frames
        target_audio_frames = len(visual_frames) * 4
        if len(features) < target_audio_frames:
            shortage = target_audio_frames - len(features)
            features = np.pad(features, ((0, shortage), (0, 0)), mode="wrap")
        else:
            features = features[:target_audio_frames]

        import torch

        audio_tensor = torch.from_numpy(
            features.astype(np.float32, copy=False)
        ).unsqueeze(0)
        visual_tensor = torch.from_numpy(
            visual_frames.astype(np.float32, copy=False)
        ).unsqueeze(0)
        audio_tensor = audio_tensor.to(self.device)
        visual_tensor = visual_tensor.to(self.device)
        with self._inference_lock, torch.inference_mode():
            scores = self.model.active_speaker_probabilities(
                audio_tensor,
                visual_tensor,
            )
        values = scores.detach().float().cpu().numpy().reshape(-1)
        if values.size == 0 or not np.isfinite(values).all():
            return _insufficient_assessment(
                self.provider_id,
                audio_turn_id,
                windows_session_id,
                visual,
                "active_speaker_model_output_invalid",
                audio_feature_frames=len(features),
            )
        return ActiveSpeakerAssessment(
            provider_id=self.provider_id,
            state=ActiveSpeakerState.SCORED,
            audio_turn_id=audio_turn_id,
            windows_session_id=windows_session_id,
            visual_track_id=visual.visual_track_id,
            start_monotonic=overlap_start,
            end_monotonic=overlap_end,
            visual_frames=len(visual_frames),
            unique_visual_frames=visual.unique_source_frames,
            audio_feature_frames=len(features),
            mean_score=float(np.mean(values)),
            median_score=float(np.median(values)),
            minimum_score=float(np.min(values)),
            maximum_score=float(np.max(values)),
            reason_codes=("active_speaker_shadow_score_no_threshold",),
        )


def _normalized_head_crop(
    image: np.ndarray,
    bounds: BoundingBox,
    *,
    crop_scale: float,
) -> np.ndarray:
    height, width = image.shape[:2]
    center_x = bounds.center_x * width
    center_y = bounds.center_y * height
    side = max(bounds.width * width, bounds.height * height) * crop_scale
    half = side / 2.0
    left = max(0, math.floor(center_x - half))
    top = max(0, math.floor(center_y - half))
    right = min(width, math.ceil(center_x + half))
    bottom = min(height, math.ceil(center_y + half))
    if right <= left or bottom <= top:
        raise ValueError("active-speaker head crop is empty")
    return image[top:bottom, left:right]


def _slice_turn_audio(
    turn: SpeakerTurnAudio,
    start_monotonic: float,
    end_monotonic: float,
) -> np.ndarray:
    assert turn.start_monotonic is not None
    start = max(0, round((start_monotonic - turn.start_monotonic) * turn.sample_rate))
    end = min(
        turn.samples.size,
        round((end_monotonic - turn.start_monotonic) * turn.sample_rate),
    )
    return turn.samples[start:end]


def _resample_audio(
    samples: np.ndarray, source_rate: int, target_rate: int
) -> np.ndarray:
    if source_rate == target_rate:
        return samples.astype(np.float32, copy=False)
    from scipy.signal import resample_poly

    divisor = math.gcd(source_rate, target_rate)
    return np.asarray(
        resample_poly(
            samples.astype(np.float32), target_rate // divisor, source_rate // divisor
        ),
        dtype=np.float32,
    )


def _mfcc_features(samples: np.ndarray, source_fps: float) -> np.ndarray:
    from python_speech_features import mfcc

    cadence_scale = LR_ASD_VISUAL_FPS / source_fps
    return np.asarray(
        mfcc(
            samples,
            samplerate=LR_ASD_AUDIO_RATE,
            numcep=13,
            winlen=0.025 * cadence_scale,
            winstep=0.010 * cadence_scale,
        ),
        dtype=np.float32,
    )


def _verify_lr_asd_asset(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = path.read_bytes()
    if len(payload) != LR_ASD_AVA_SIZE_BYTES:
        raise RuntimeError(
            f"LR-ASD asset size mismatch: expected {LR_ASD_AVA_SIZE_BYTES}, "
            f"got {len(payload)}"
        )
    header = f"blob {len(payload)}\0".encode()
    git_blob_sha1 = hashlib.sha1(header + payload, usedforsecurity=False).hexdigest()
    if git_blob_sha1 != LR_ASD_AVA_GIT_BLOB_SHA1:
        raise RuntimeError("LR-ASD asset does not match the pinned official Git blob")


def _insufficient_assessment(
    provider_id: str,
    audio_turn_id: str,
    windows_session_id: str,
    visual: ActiveSpeakerVisualWindow,
    reason: str,
    *,
    audio_feature_frames: int = 0,
) -> ActiveSpeakerAssessment:
    return ActiveSpeakerAssessment(
        provider_id=provider_id,
        state=ActiveSpeakerState.INSUFFICIENT,
        audio_turn_id=audio_turn_id,
        windows_session_id=windows_session_id,
        visual_track_id=visual.visual_track_id,
        start_monotonic=visual.start_monotonic,
        end_monotonic=visual.end_monotonic,
        visual_frames=len(visual.frames),
        unique_visual_frames=visual.unique_source_frames,
        audio_feature_frames=audio_feature_frames,
        mean_score=None,
        median_score=None,
        minimum_score=None,
        maximum_score=None,
        reason_codes=(reason,),
    )
