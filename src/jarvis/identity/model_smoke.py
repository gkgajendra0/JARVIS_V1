from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .model_assets import ModelAssetCache, load_default_face_model_manifest


@dataclass(frozen=True, slots=True)
class TimingSummary:
    median_ms: float
    p95_ms: float
    minimum_ms: float
    maximum_ms: float


def _summarize(samples_ms: list[float]) -> TimingSummary:
    if not samples_ms:
        raise ValueError("timing samples must not be empty")
    ordered = sorted(samples_ms)
    p95_index = min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)
    return TimingSummary(
        median_ms=statistics.median(ordered),
        p95_ms=ordered[p95_index],
        minimum_ms=ordered[0],
        maximum_ms=ordered[-1],
    )


def _timed(callable_, *, iterations: int, warmup: int = 3) -> TimingSummary:
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    if warmup < 0:
        raise ValueError("warmup must not be negative")
    for _ in range(warmup):
        callable_()
    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        callable_()
        samples.append((time.perf_counter() - started) * 1000.0)
    return _summarize(samples)


def _fetch(cache: ModelAssetCache, asset) -> tuple[Path, float]:
    started = time.perf_counter()
    path = cache.fetch(asset)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return path, elapsed_ms


def run_smoke(*, iterations: int = 30) -> None:
    manifest = load_default_face_model_manifest()
    detector_asset = manifest.by_role("face_detector")
    recognizer_asset = manifest.by_role("face_recognizer")
    cache = ModelAssetCache()

    print("JARVIS Step 3B.3 face-model non-enrollment smoke")
    print("------------------------------------------------")
    print(f"OpenCV: {cv2.__version__}")
    print(f"Model cache: {cache.root}")
    print(f"OpenCV Zoo revision: {manifest.source_revision}")
    print()

    detector_path, detector_fetch_ms = _fetch(cache, detector_asset)
    recognizer_path, recognizer_fetch_ms = _fetch(cache, recognizer_asset)

    print("PINNED ASSETS")
    print(
        f"YuNet: {detector_path} | sha256={detector_asset.sha256} "
        f"| fetch/verify={detector_fetch_ms:.1f} ms"
    )
    print(
        f"SFace: {recognizer_path} | sha256={recognizer_asset.sha256} "
        f"| fetch/verify={recognizer_fetch_ms:.1f} ms"
    )
    print()

    started = time.perf_counter()
    detector = cv2.FaceDetectorYN.create(
        str(detector_path),
        "",
        (320, 320),
        0.9,
        0.3,
        5000,
        cv2.dnn.DNN_BACKEND_OPENCV,
        cv2.dnn.DNN_TARGET_CPU,
    )
    detector_load_ms = (time.perf_counter() - started) * 1000.0

    started = time.perf_counter()
    recognizer = cv2.FaceRecognizerSF.create(
        str(recognizer_path),
        "",
        cv2.dnn.DNN_BACKEND_OPENCV,
        cv2.dnn.DNN_TARGET_CPU,
    )
    recognizer_load_ms = (time.perf_counter() - started) * 1000.0

    blank_detector_input = np.zeros((320, 320, 3), dtype=np.uint8)
    blank_recognizer_input = np.zeros((112, 112, 3), dtype=np.uint8)

    detector.setInputSize((320, 320))

    def detect_blank() -> None:
        detector.detect(blank_detector_input)

    def embed_blank() -> None:
        feature = recognizer.feature(blank_recognizer_input)
        if feature is None or feature.size == 0 or not np.isfinite(feature).all():
            raise RuntimeError("SFace produced an invalid synthetic feature")

    detector_timing = _timed(detect_blank, iterations=iterations)
    recognizer_timing = _timed(embed_blank, iterations=iterations)
    feature = recognizer.feature(blank_recognizer_input)

    print("CPU MODEL SMOKE")
    print(f"YuNet load: {detector_load_ms:.1f} ms")
    print(
        "YuNet synthetic inference: "
        f"median={detector_timing.median_ms:.2f} ms, "
        f"p95={detector_timing.p95_ms:.2f} ms, "
        f"min={detector_timing.minimum_ms:.2f} ms, "
        f"max={detector_timing.maximum_ms:.2f} ms"
    )
    print(f"SFace load: {recognizer_load_ms:.1f} ms")
    print(
        "SFace synthetic feature: "
        f"median={recognizer_timing.median_ms:.2f} ms, "
        f"p95={recognizer_timing.p95_ms:.2f} ms, "
        f"min={recognizer_timing.minimum_ms:.2f} ms, "
        f"max={recognizer_timing.maximum_ms:.2f} ms"
    )
    print(f"SFace feature shape: {tuple(int(v) for v in feature.shape)}")
    print()
    print("NO CAMERA OPENED")
    print("NO OWNER PROFILE CREATED")
    print("NO BIOMETRIC TEMPLATE PERSISTED")
    print("STEP_3B3_MODEL_SMOKE = PASS")


def main() -> None:
    run_smoke()


if __name__ == "__main__":
    main()
