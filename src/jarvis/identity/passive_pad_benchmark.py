from __future__ import annotations

import argparse
import math
import statistics
import time
from dataclasses import dataclass

import cv2
import numpy as np

from jarvis.identity.model_assets import ModelAssetCache, load_default_face_model_manifest
from jarvis.identity.passive_pad import (
    AntiSpoofMn3Provider,
    MiniFasEnsembleProvider,
    PassivePadProvider,
    PassivePadScore,
)
from jarvis.identity.passive_pad_assets import (
    ANTI_SPOOF_MN3,
    MINIFASNET_V1SE,
    MINIFASNET_V2,
    PassivePadAssetCache,
)
from jarvis.vision.camera import OpenCVCameraSource

_WINDOW_NAME = "JARVIS Passive RGB PAD Benchmark"
_MIN_SAMPLES = 120
_MAX_SAMPLES = 300
_ANALYSIS_INTERVAL_SECONDS = 0.10


@dataclass(frozen=True, slots=True)
class _FaceBox:
    left: int
    top: int
    right: int
    bottom: int
    confidence: float

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center(self) -> tuple[float, float]:
        return ((self.left + self.right) / 2.0, (self.top + self.bottom) / 2.0)

    def as_xyxy(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.right, self.bottom


class _FaceSelection:
    def __init__(self) -> None:
        self.faces: tuple[_FaceBox, ...] = ()
        self.clicked_face: _FaceBox | None = None

    def update(self, faces: list[_FaceBox]) -> None:
        self.faces = tuple(faces)

    def on_mouse(self, event, x, y, flags, param) -> None:
        del flags, param
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        containing = [
            face
            for face in self.faces
            if face.left <= x <= face.right and face.top <= y <= face.bottom
        ]
        if containing:
            self.clicked_face = min(containing, key=lambda face: face.width * face.height)


def _parse_faces(result) -> list[_FaceBox]:
    rows = result[1] if isinstance(result, tuple) and len(result) >= 2 else result
    if rows is None:
        return []
    array = np.asarray(rows, dtype=np.float32)
    if array.size == 0:
        return []
    if array.ndim == 1:
        array = array.reshape(1, -1)
    if array.ndim != 2 or array.shape[1] < 15:
        raise RuntimeError(f"unexpected YuNet output shape: {array.shape}")
    faces: list[_FaceBox] = []
    for row in array:
        x, y, width, height = (float(value) for value in row[:4])
        faces.append(
            _FaceBox(
                left=max(0, round(x)),
                top=max(0, round(y)),
                right=max(1, round(x + width)),
                bottom=max(1, round(y + height)),
                confidence=float(row[-1]),
            )
        )
    return faces


def _intersection_over_union(first: _FaceBox, second: _FaceBox) -> float:
    left = max(first.left, second.left)
    top = max(first.top, second.top)
    right = min(first.right, second.right)
    bottom = min(first.bottom, second.bottom)
    intersection = max(0, right - left) * max(0, bottom - top)
    if intersection <= 0:
        return 0.0
    union = first.width * first.height + second.width * second.height - intersection
    return intersection / union if union > 0 else 0.0


def _associate_face(
    previous: _FaceBox,
    candidates: list[_FaceBox],
    *,
    frame_width: int,
    frame_height: int,
) -> _FaceBox | None:
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda candidate: _intersection_over_union(previous, candidate),
        reverse=True,
    )
    best = ranked[0]
    if _intersection_over_union(previous, best) >= 0.10:
        return best

    previous_x, previous_y = previous.center
    diagonal = math.hypot(frame_width, frame_height)
    nearest = min(
        candidates,
        key=lambda candidate: math.hypot(
            candidate.center[0] - previous_x,
            candidate.center[1] - previous_y,
        ),
    )
    distance = math.hypot(
        nearest.center[0] - previous_x,
        nearest.center[1] - previous_y,
    )
    return nearest if diagonal > 0 and distance / diagonal <= 0.18 else None


def rolling_medians(values: list[float], window: int) -> list[float]:
    if window <= 0:
        raise ValueError("rolling-median window must be positive")
    if len(values) < window:
        return []
    return [
        float(statistics.median(values[index - window + 1 : index + 1]))
        for index in range(window - 1, len(values))
    ]


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot compute percentile of empty values")
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be in [0, 1]")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _distribution(name: str, values: list[float]) -> str:
    if not values:
        return f"{name}: n/a"
    return (
        f"{name}: n={len(values)}, min={min(values):.4f}, "
        f"p05={_percentile(values, 0.05):.4f}, "
        f"median={statistics.median(values):.4f}, "
        f"p95={_percentile(values, 0.95):.4f}, max={max(values):.4f}"
    )


def _latency_distribution(values: list[float]) -> str:
    if not values:
        return "latency: n/a"
    return (
        f"latency: median={statistics.median(values):.2f} ms, "
        f"p95={_percentile(values, 0.95):.2f} ms, max={max(values):.2f} ms"
    )


def _draw(
    preview: np.ndarray,
    faces: list[_FaceBox],
    selected: _FaceBox | None,
    *,
    collecting: bool,
    sample_count: int,
    latest_scores: dict[str, PassivePadScore],
) -> None:
    for face in faces:
        cv2.rectangle(
            preview,
            (face.left, face.top),
            (face.right, face.bottom),
            (0, 255, 0),
            2,
        )
    if selected is not None:
        cv2.rectangle(
            preview,
            (selected.left, selected.top),
            (selected.right, selected.bottom),
            (0, 255, 255),
            3,
        )

    state = "COLLECTING" if collecting else "READY"
    lines = [
        f"3B.7B PASSIVE PAD | {state} | samples {sample_count}/{_MAX_SAMPLES}",
        "Click one face | S start | D finish >=120 | C clear | Q abort",
        "Scores are diagnostic only; no PAD threshold or T2 decision is active.",
    ]
    for score in latest_scores.values():
        lines.append(
            f"{score.provider_id}: real={score.real_probability:.3f} "
            f"({score.latency_ms:.1f} ms)"
        )
    for index, line in enumerate(lines):
        cv2.putText(
            preview,
            line,
            (14, 26 + index * 23),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.50,
            (0, 255, 255),
            1,
            cv2.LINE_AA,
        )


def run_benchmark(scenario: str) -> int:
    manifest = load_default_face_model_manifest()
    yunet_path = ModelAssetCache().fetch(manifest.by_role("face_detector"))
    yunet = cv2.FaceDetectorYN.create(
        str(yunet_path),
        "",
        (1280, 720),
        0.75,
        0.3,
        5000,
    )

    pad_cache = PassivePadAssetCache()
    mn3_path = pad_cache.fetch(ANTI_SPOOF_MN3)
    v1se_path = pad_cache.fetch(MINIFASNET_V1SE)
    v2_path = pad_cache.fetch(MINIFASNET_V2)
    providers: tuple[PassivePadProvider, ...] = (
        AntiSpoofMn3Provider(mn3_path),
        MiniFasEnsembleProvider(v1se_path, v2_path),
    )

    print("JARVIS Step 3B.7B passive RGB PAD benchmark")
    print("---------------------------------------------")
    print(f"scenario = {scenario}")
    print("Camera is read-only. No PTZ is created or moved.")
    print("Click the face to test, press S, then collect at least 120 samples.")
    print("Press D to finish after 120 samples; collection stops at 300 automatically.")
    print("No frame, face crop, PAD tensor, or output vector is saved.")
    print("No score threshold, liveness verdict, or trust upgrade is active.")

    camera = OpenCVCameraSource()
    selection = _FaceSelection()
    selected: _FaceBox | None = None
    collecting = False
    samples: dict[str, list[PassivePadScore]] = {
        provider.provider_id: [] for provider in providers
    }
    latest_scores: dict[str, PassivePadScore] = {}
    last_frame_id: int | None = None
    last_analysis_at: float | None = None
    detection_attempts = 0
    associated_faces = 0

    cv2.namedWindow(_WINDOW_NAME)
    cv2.setMouseCallback(_WINDOW_NAME, selection.on_mouse)
    try:
        camera.start()
        while True:
            frame = camera.latest(
                after_frame_id=last_frame_id,
                timeout_seconds=1.0,
            )
            if frame is None:
                continue
            last_frame_id = frame.frame_id
            yunet.setInputSize((frame.width, frame.height))
            faces = _parse_faces(yunet.detect(frame.image))
            detection_attempts += 1
            selection.update(faces)

            if selection.clicked_face is not None:
                selected = selection.clicked_face
                selection.clicked_face = None
                collecting = False
                samples = {provider.provider_id: [] for provider in providers}
                latest_scores.clear()
                print("Face selected; statistics reset. Press S when ready.")
            elif selected is not None:
                selected = _associate_face(
                    selected,
                    faces,
                    frame_width=frame.width,
                    frame_height=frame.height,
                )

            if selected is not None:
                associated_faces += 1

            should_score = (
                collecting
                and selected is not None
                and (
                    last_analysis_at is None
                    or frame.captured_at - last_analysis_at >= _ANALYSIS_INTERVAL_SECONDS
                )
            )
            if should_score:
                last_analysis_at = frame.captured_at
                for provider in providers:
                    score = provider.score(frame.image, selected.as_xyxy())
                    samples[provider.provider_id].append(score)
                    latest_scores[provider.provider_id] = score
                if min(len(values) for values in samples.values()) >= _MAX_SAMPLES:
                    break

            preview = frame.image.copy()
            _draw(
                preview,
                faces,
                selected,
                collecting=collecting,
                sample_count=min((len(values) for values in samples.values()), default=0),
                latest_scores=latest_scores,
            )
            cv2.imshow(_WINDOW_NAME, preview)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                print("STEP_3B7B_PASSIVE_PAD_BENCHMARK = ABORTED")
                return 2
            if key in (ord("c"), ord("C")):
                selected = None
                collecting = False
                samples = {provider.provider_id: [] for provider in providers}
                latest_scores.clear()
                print("Face selection and in-memory statistics cleared.")
            if key in (ord("s"), ord("S")):
                if selected is None:
                    print("Select one detected face before starting.")
                else:
                    collecting = True
                    last_analysis_at = None
                    print("Passive PAD collection started.")
            if key in (ord("d"), ord("D")):
                count = min((len(values) for values in samples.values()), default=0)
                if count < _MIN_SAMPLES:
                    print(f"Need at least {_MIN_SAMPLES} samples before finishing; have {count}.")
                else:
                    break
    finally:
        camera.close()
        cv2.destroyAllWindows()

    print()
    print("PASSIVE RGB PAD BENCHMARK SUMMARY")
    print(f"scenario = {scenario}")
    print(f"face_detection_attempts = {detection_attempts}")
    print(f"frames_with_associated_selected_face = {associated_faces}")
    for provider in providers:
        provider_samples = samples[provider.provider_id]
        real_values = [sample.real_probability for sample in provider_samples]
        latency_values = [sample.latency_ms for sample in provider_samples]
        print()
        print(f"provider = {provider.provider_id}")
        print(_distribution("real_probability", real_values))
        print(_distribution("rolling_median_5", rolling_medians(real_values, 5)))
        print(_distribution("rolling_median_15", rolling_medians(real_values, 15)))
        print(_latency_distribution(latency_values))
    print()
    print("frames_saved = False")
    print("face_crops_saved = False")
    print("pad_tensors_saved = False")
    print("pad_output_vectors_saved = False")
    print("passive_pad_grants_T2 = False")
    print("passive_pad_threshold_approved = False")
    print("STEP_3B7B_PASSIVE_PAD_BENCHMARK = COMPLETE")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JARVIS passive RGB PAD benchmark")
    parser.add_argument(
        "--scenario",
        choices=("live", "phone-photo", "phone-video", "printed-photo", "other"),
        default="live",
        help="Human-declared benchmark scenario; used only in the printed summary.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    raise SystemExit(run_benchmark(args.scenario))


if __name__ == "__main__":
    main()
