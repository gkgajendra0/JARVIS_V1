from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class PassivePadScore:
    provider_id: str
    real_probability: float
    spoof_probability: float
    latency_ms: float

    def __post_init__(self) -> None:
        for value in (self.real_probability, self.spoof_probability):
            if not np.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError("PAD probabilities must be finite values in [0, 1]")
        if not np.isfinite(self.latency_ms) or self.latency_ms < 0:
            raise ValueError("PAD latency must be a non-negative finite value")


class PassivePadProvider(Protocol):
    provider_id: str

    def score(
        self, frame_bgr: np.ndarray, face_xyxy: tuple[int, int, int, int]
    ) -> PassivePadScore: ...


def _load_ort_session(model_path: str | Path) -> Any:
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError(
            "Passive PAD requires onnxruntime. Install JARVIS with the vision extra."
        ) from exc
    return ort.InferenceSession(
        str(model_path),
        providers=["CPUExecutionProvider"],
    )


def _probabilities(values: np.ndarray) -> np.ndarray:
    vector = np.asarray(values, dtype=np.float64).reshape(-1)
    if vector.size < 2 or not np.isfinite(vector).all():
        raise RuntimeError("PAD model returned an invalid output vector")
    total = float(vector.sum())
    if np.all(vector >= 0.0) and np.all(vector <= 1.0) and abs(total - 1.0) <= 1e-4:
        return vector
    shifted = vector - float(np.max(vector))
    exponentials = np.exp(shifted)
    denominator = float(exponentials.sum())
    if denominator <= 0 or not np.isfinite(denominator):
        raise RuntimeError("PAD model softmax normalization failed")
    return exponentials / denominator


def _bounded_xyxy(
    image: np.ndarray,
    face_xyxy: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("PAD inference expects a BGR image")
    left, top, right, bottom = face_xyxy
    height, width = image.shape[:2]
    left = max(0, min(width - 1, int(left)))
    top = max(0, min(height - 1, int(top)))
    right = max(left + 1, min(width, int(right)))
    bottom = max(top + 1, min(height, int(bottom)))
    return left, top, right, bottom


def _scaled_face_crop(
    image: np.ndarray,
    face_xyxy: tuple[int, int, int, int],
    *,
    scale: float,
    output_size: tuple[int, int],
) -> np.ndarray:
    if scale <= 0:
        raise ValueError("crop scale must be positive")
    left, top, right, bottom = _bounded_xyxy(image, face_xyxy)
    height, width = image.shape[:2]
    box_width = right - left
    box_height = bottom - top
    center_x = left + box_width / 2.0
    center_y = top + box_height / 2.0
    applied_scale = min(
        scale,
        (width - 1) / max(1, box_width),
        (height - 1) / max(1, box_height),
    )
    new_width = box_width * applied_scale
    new_height = box_height * applied_scale
    crop_left = max(0, int(center_x - new_width / 2.0))
    crop_top = max(0, int(center_y - new_height / 2.0))
    crop_right = min(width, int(center_x + new_width / 2.0))
    crop_bottom = min(height, int(center_y + new_height / 2.0))
    if crop_left >= crop_right or crop_top >= crop_bottom:
        raise ValueError("scaled PAD face crop is empty")
    crop = image[crop_top:crop_bottom, crop_left:crop_right]
    return cv2.resize(crop, output_size, interpolation=cv2.INTER_LINEAR)


class AntiSpoofMn3Provider:
    provider_id = "openvino-anti-spoof-mn3-v1"
    _MEAN = np.asarray([151.2405, 119.5950, 107.8395], dtype=np.float32)
    _SCALE = np.asarray([63.0105, 56.4570, 55.0035], dtype=np.float32)

    def __init__(self, model_path: str | Path) -> None:
        self._session = _load_ort_session(model_path)
        self._input_name = self._session.get_inputs()[0].name
        self._output_name = self._session.get_outputs()[0].name

    def score(
        self,
        frame_bgr: np.ndarray,
        face_xyxy: tuple[int, int, int, int],
    ) -> PassivePadScore:
        face = _scaled_face_crop(
            frame_bgr,
            face_xyxy,
            scale=1.0,
            output_size=(128, 128),
        )
        rgb = cv2.cvtColor(face, cv2.COLOR_BGR2RGB).astype(np.float32)
        normalized = (rgb - self._MEAN) / self._SCALE
        tensor = np.ascontiguousarray(normalized.transpose(2, 0, 1)[None, ...])
        started = time.perf_counter()
        output = self._session.run([self._output_name], {self._input_name: tensor})[0]
        latency_ms = (time.perf_counter() - started) * 1000.0
        probs = _probabilities(output)
        real = float(probs[0])
        spoof = float(probs[1])
        return PassivePadScore(
            provider_id=self.provider_id,
            real_probability=real,
            spoof_probability=spoof,
            latency_ms=latency_ms,
        )


@dataclass(slots=True)
class _MiniFasMember:
    session: Any
    input_name: str
    output_name: str
    crop_scale: float


class MiniFasEnsembleProvider:
    provider_id = "minifasnet-v1se-v2-ensemble-v1"

    def __init__(
        self,
        v1se_path: str | Path,
        v2_path: str | Path,
    ) -> None:
        self._members = (
            self._member(v1se_path, crop_scale=4.0),
            self._member(v2_path, crop_scale=2.7),
        )

    @staticmethod
    def _member(model_path: str | Path, *, crop_scale: float) -> _MiniFasMember:
        session = _load_ort_session(model_path)
        return _MiniFasMember(
            session=session,
            input_name=session.get_inputs()[0].name,
            output_name=session.get_outputs()[0].name,
            crop_scale=crop_scale,
        )

    def score(
        self,
        frame_bgr: np.ndarray,
        face_xyxy: tuple[int, int, int, int],
    ) -> PassivePadScore:
        real_scores: list[float] = []
        total_latency_ms = 0.0
        for member in self._members:
            face = _scaled_face_crop(
                frame_bgr,
                face_xyxy,
                scale=member.crop_scale,
                output_size=(80, 80),
            )
            tensor = np.ascontiguousarray(
                face.astype(np.float32).transpose(2, 0, 1)[None, ...]
            )
            started = time.perf_counter()
            output = member.session.run(
                [member.output_name],
                {member.input_name: tensor},
            )[0]
            total_latency_ms += (time.perf_counter() - started) * 1000.0
            probs = _probabilities(output)
            if probs.size < 3:
                raise RuntimeError("MiniFASNet output must contain at least 3 classes")
            real_scores.append(float(probs[1]))

        real = float(np.mean(real_scores))
        return PassivePadScore(
            provider_id=self.provider_id,
            real_probability=real,
            spoof_probability=1.0 - real,
            latency_ms=total_latency_ms,
        )
