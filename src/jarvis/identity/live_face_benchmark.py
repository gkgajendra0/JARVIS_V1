"""Non-persistent live YuNet/SFace benchmark on the selected JARVIS track."""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass

import cv2
import numpy as np

from jarvis.identity.model_assets import (
    ModelAssetCache,
    load_default_face_model_manifest,
)

_WINDOW_NAME = "JARVIS Face Identity Benchmark"


@dataclass(frozen=True, slots=True)
class LiveFaceSample:
    yunet_confidence: float
    head_width_px: int
    head_height_px: int
    detection_ms: float
    align_ms: float
    embedding_ms: float
    brightness: float
    sharpness: float
    anchor_cosine: float


@dataclass(frozen=True, slots=True)
class _Crop:
    image: np.ndarray
    left: int
    top: int


class _SelectionState:
    def __init__(self) -> None:
        self.clicked_track_id: int | None = None
        self.tracks = ()
        self.frame_width = 0
        self.frame_height = 0

    def update(self, tracks, *, width: int, height: int) -> None:
        self.tracks = tracks
        self.frame_width = width
        self.frame_height = height

    def on_mouse(self, event, x, y, flags, param) -> None:
        del flags, param
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        if self.frame_width <= 0 or self.frame_height <= 0:
            return

        normalized_x = x / self.frame_width
        normalized_y = y / self.frame_height
        containing = [
            track
            for track in self.tracks
            if track.bounds.left <= normalized_x <= track.bounds.right
            and track.bounds.top <= normalized_y <= track.bounds.bottom
        ]
        if not containing:
            return

        self.clicked_track_id = min(
            containing,
            key=lambda track: track.bounds.width * track.bounds.height,
        ).track_id


class _NoOpPtz:
    def move(self, command) -> None:
        del command

    def close(self) -> None:
        return None


def _crop_head(image: np.ndarray, bounds, *, margin_fraction: float = 0.25) -> _Crop:
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("head crop expects a BGR image")
    if margin_fraction < 0:
        raise ValueError("margin_fraction must be non-negative")

    height, width = image.shape[:2]
    head_width = bounds.width * width
    head_height = bounds.height * height
    margin_x = head_width * margin_fraction
    margin_y = head_height * margin_fraction

    left = max(0, math.floor(bounds.left * width - margin_x))
    top = max(0, math.floor(bounds.top * height - margin_y))
    right = min(width, math.ceil(bounds.right * width + margin_x))
    bottom = min(height, math.ceil(bounds.bottom * height + margin_y))
    if left >= right or top >= bottom:
        raise ValueError("head crop is empty")

    return _Crop(
        image=np.ascontiguousarray(image[top:bottom, left:right]),
        left=left,
        top=top,
    )


def _face_rows(result) -> np.ndarray:
    faces = result
    if isinstance(result, tuple):
        faces = result[1] if len(result) >= 2 else None
    if faces is None:
        return np.empty((0, 15), dtype=np.float32)

    rows = np.asarray(faces, dtype=np.float32)
    if rows.size == 0:
        return np.empty((0, 15), dtype=np.float32)
    if rows.ndim == 1:
        rows = rows.reshape(1, -1)
    if rows.ndim != 2 or rows.shape[1] < 15:
        raise RuntimeError(f"unexpected YuNet output shape: {rows.shape}")
    return rows


def _select_center_face(faces: np.ndarray, *, width: int, height: int) -> np.ndarray:
    if faces.size == 0:
        raise ValueError("cannot select from an empty face set")
    center_x = width / 2.0
    center_y = height / 2.0

    def score(face: np.ndarray) -> tuple[float, float]:
        x, y, face_width, face_height = (float(value) for value in face[:4])
        face_center_x = x + face_width / 2.0
        face_center_y = y + face_height / 2.0
        distance_squared = (face_center_x - center_x) ** 2 + (
            face_center_y - center_y
        ) ** 2
        return distance_squared, -float(face[-1])

    return min(faces, key=score)


def _cosine_similarity(first: np.ndarray, second: np.ndarray) -> float:
    first_flat = np.asarray(first, dtype=np.float32).reshape(-1)
    second_flat = np.asarray(second, dtype=np.float32).reshape(-1)
    if first_flat.shape != second_flat.shape:
        raise ValueError("feature shapes must match")
    denominator = float(np.linalg.norm(first_flat) * np.linalg.norm(second_flat))
    if denominator <= 0:
        raise ValueError("feature norm must be positive")
    return float(np.dot(first_flat, second_flat) / denominator)


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def _summary_line(name: str, values: list[float], *, suffix: str = "") -> str:
    if not values:
        return f"{name}: n/a"
    return (
        f"{name}: median={statistics.median(values):.2f}{suffix}, "
        f"p95={_p95(values):.2f}{suffix}, "
        f"min={min(values):.2f}{suffix}, max={max(values):.2f}{suffix}"
    )


def _draw_benchmark_overlay(preview: np.ndarray, sample: LiveFaceSample | None) -> None:
    lines = [
        "3B.4 NON-PERSISTENT | click a green person to lock | C clear | Q quit",
        "Move naturally: frontal, left/right, near/far, normal room lighting.",
    ]
    if sample is not None:
        lines.extend(
            [
                (
                    f"YuNet {sample.yunet_confidence:.3f} | "
                    f"head {sample.head_width_px}x{sample.head_height_px}px | "
                    f"cos {sample.anchor_cosine:.3f}"
                ),
                (
                    f"detect {sample.detection_ms:.2f}ms | "
                    f"align {sample.align_ms:.2f}ms | "
                    f"embed {sample.embedding_ms:.2f}ms | "
                    f"brightness {sample.brightness:.1f} | "
                    f"sharp {sample.sharpness:.1f}"
                ),
            ]
        )

    for index, line in enumerate(lines):
        cv2.putText(
            preview,
            line,
            (14, preview.shape[0] - 82 + index * 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (0, 255, 255),
            1,
            cv2.LINE_AA,
        )


def run_live_benchmark(*, analysis_interval_seconds: float = 0.12) -> int:
    if analysis_interval_seconds <= 0:
        raise ValueError("analysis_interval_seconds must be positive")

    from jarvis.vision.camera import OpenCVCameraSource
    from jarvis.vision.detector import RFDetrNanoDetector
    from jarvis.vision.follow import FollowConfig, FollowController
    from jarvis.vision.framing import HeadFirstFramingPolicy
    from jarvis.vision.head_mediapipe import (
        MediaPipeBlazeFaceConfig,
        MediaPipeBlazeFaceDetector,
        default_blazeface_model_path,
    )
    from jarvis.vision.observer import render_snapshot
    from jarvis.vision.runtime import VisionRuntime, VisionRuntimeConfig
    from jarvis.vision.targeting import TargetManager
    from jarvis.vision.tracker import ByteTrackAdapter

    manifest = load_default_face_model_manifest()
    cache = ModelAssetCache()
    detector_asset = manifest.by_role("face_detector")
    recognizer_asset = manifest.by_role("face_recognizer")
    detector_path = cache.fetch(detector_asset)
    recognizer_path = cache.fetch(recognizer_asset)

    yunet = cv2.FaceDetectorYN.create(
        str(detector_path),
        "",
        (320, 320),
        0.9,
        0.3,
        5000,
    )
    sface = cv2.FaceRecognizerSF.create(str(recognizer_path), "")

    blazeface_path = default_blazeface_model_path()
    if not blazeface_path.is_file():
        raise RuntimeError(
            "BlazeFace model is missing. Expected it at "
            f"{blazeface_path}. Set JARVIS_BLAZEFACE_MODEL_PATH to override."
        )

    framing_policy = HeadFirstFramingPolicy()
    runtime = VisionRuntime(
        camera=OpenCVCameraSource(),
        detector=RFDetrNanoDetector(),
        tracker=ByteTrackAdapter(),
        target_manager=TargetManager(lost_timeout_seconds=0.5),
        follow_controller=FollowController(
            FollowConfig(
                horizontal_dead_zone=0.14,
                vertical_dead_zone=0.14,
                gain=1.0,
                max_command=0.20,
                minimum_confidence=0.5,
                desired_x=0.50,
                desired_y=0.40,
            )
        ),
        ptz=_NoOpPtz(),
        head_detector=MediaPipeBlazeFaceDetector(
            MediaPipeBlazeFaceConfig(model_path=blazeface_path)
        ),
        framing_policy=framing_policy,
        config=VisionRuntimeConfig(
            minimum_ptz_interval_seconds=0.20,
            require_head_for_lock=True,
            required_head_confirmation_frames=3,
        ),
    )

    print("JARVIS Step 3B.4 selected-track live face benchmark")
    print("----------------------------------------------------")
    print("Camera is READ-ONLY for this diagnostic; PTZ is never armed or moved.")
    print("Click a green/head-confirmed person to lock the benchmark target.")
    print("Then move naturally for ~30-60 seconds and press Q to finish.")
    print("No frame, aligned face, feature vector, or OWNER template is saved.")

    selection = _SelectionState()
    samples: list[LiveFaceSample] = []
    associated_attempts = 0
    successful_embeddings = 0
    anchor_feature: np.ndarray | None = None
    last_analysis_at: float | None = None
    last_sample: LiveFaceSample | None = None
    last_face_rect: tuple[int, int, int, int] | None = None

    cv2.namedWindow(_WINDOW_NAME)
    cv2.setMouseCallback(_WINDOW_NAME, selection.on_mouse)

    try:
        runtime.start()
        while True:
            snapshot = runtime.process_once(timeout_seconds=1.0)
            if snapshot is None:
                continue
            frame = runtime.latest_frame
            if frame is None:
                continue

            selection.update(
                snapshot.tracks,
                width=frame.width,
                height=frame.height,
            )
            if selection.clicked_track_id is not None:
                try:
                    runtime.lock(selection.clicked_track_id)
                    samples.clear()
                    associated_attempts = 0
                    successful_embeddings = 0
                    anchor_feature = None
                    last_sample = None
                    last_face_rect = None
                    print(
                        f"Locked track {selection.clicked_track_id}; benchmark statistics reset."
                    )
                except ValueError as exc:
                    print(exc)
                finally:
                    selection.clicked_track_id = None

            target = runtime.target
            head = framing_policy.associated_head(target, list(snapshot.heads))
            should_analyze = (
                head is not None
                and target is not None
                and target.visible
                and (
                    last_analysis_at is None
                    or frame.captured_at - last_analysis_at >= analysis_interval_seconds
                )
            )

            if should_analyze:
                last_analysis_at = frame.captured_at
                associated_attempts += 1
                crop = _crop_head(frame.image, head.bounds)
                crop_height, crop_width = crop.image.shape[:2]
                yunet.setInputSize((crop_width, crop_height))

                started = time.perf_counter()
                faces = _face_rows(yunet.detect(crop.image))
                detection_ms = (time.perf_counter() - started) * 1000.0

                if faces.size:
                    face = _select_center_face(
                        faces,
                        width=crop_width,
                        height=crop_height,
                    )
                    started = time.perf_counter()
                    aligned = sface.alignCrop(crop.image, face)
                    align_ms = (time.perf_counter() - started) * 1000.0

                    started = time.perf_counter()
                    feature = sface.feature(aligned)
                    embedding_ms = (time.perf_counter() - started) * 1000.0
                    if (
                        feature is not None
                        and feature.size > 0
                        and np.isfinite(feature).all()
                    ):
                        feature = np.asarray(feature, dtype=np.float32).copy()
                        if anchor_feature is None:
                            anchor_feature = feature
                        anchor_cosine = _cosine_similarity(anchor_feature, feature)

                        gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
                        brightness = float(np.mean(gray))
                        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                        head_width_px = max(
                            1,
                            round(head.bounds.width * frame.width),
                        )
                        head_height_px = max(
                            1,
                            round(head.bounds.height * frame.height),
                        )
                        last_sample = LiveFaceSample(
                            yunet_confidence=float(face[-1]),
                            head_width_px=head_width_px,
                            head_height_px=head_height_px,
                            detection_ms=detection_ms,
                            align_ms=align_ms,
                            embedding_ms=embedding_ms,
                            brightness=brightness,
                            sharpness=sharpness,
                            anchor_cosine=anchor_cosine,
                        )
                        samples.append(last_sample)
                        successful_embeddings += 1

                        x, y, face_width, face_height = (
                            int(round(float(value))) for value in face[:4]
                        )
                        last_face_rect = (
                            crop.left + x,
                            crop.top + y,
                            crop.left + x + face_width,
                            crop.top + y + face_height,
                        )

            preview = render_snapshot(frame.image, snapshot)
            if last_face_rect is not None:
                left, top, right, bottom = last_face_rect
                cv2.rectangle(
                    preview,
                    (left, top),
                    (right, bottom),
                    (0, 255, 255),
                    2,
                )
                cv2.putText(
                    preview,
                    "YUNET -> SFACE",
                    (left, max(22, top - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 255),
                    2,
                    cv2.LINE_AA,
                )
            _draw_benchmark_overlay(preview, last_sample)
            cv2.imshow(_WINDOW_NAME, preview)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                break
            if key in (ord("c"), ord("C")):
                runtime.clear_target()
                samples.clear()
                associated_attempts = 0
                successful_embeddings = 0
                anchor_feature = None
                last_sample = None
                last_face_rect = None
                print("Target and in-memory benchmark statistics cleared.")
    finally:
        runtime.close()
        cv2.destroyAllWindows()
        anchor_feature = None

    print()
    print("LIVE BENCHMARK SUMMARY")
    print(f"Associated-head analysis attempts: {associated_attempts}")
    print(f"Successful SFace embeddings: {successful_embeddings}")
    success_rate = (
        successful_embeddings / associated_attempts if associated_attempts else 0.0
    )
    print(f"Embedding success rate: {success_rate * 100.0:.1f}%")

    if samples:
        print(_summary_line("YuNet confidence", [s.yunet_confidence for s in samples]))
        print(
            _summary_line(
                "YuNet detection", [s.detection_ms for s in samples], suffix=" ms"
            )
        )
        print(_summary_line("SFace align", [s.align_ms for s in samples], suffix=" ms"))
        print(
            _summary_line(
                "SFace embedding",
                [s.embedding_ms for s in samples],
                suffix=" ms",
            )
        )
        print(_summary_line("Brightness", [s.brightness for s in samples]))
        print(_summary_line("Sharpness", [s.sharpness for s in samples]))
        print(_summary_line("Anchor cosine", [s.anchor_cosine for s in samples]))
        print(
            _summary_line(
                "Head width",
                [float(s.head_width_px) for s in samples],
                suffix=" px",
            )
        )
        print(
            _summary_line(
                "Head height",
                [float(s.head_height_px) for s in samples],
                suffix=" px",
            )
        )

    print()
    print("NO OWNER PROFILE CREATED")
    print("NO BIOMETRIC TEMPLATE PERSISTED")
    print("NO FRAME OR FEATURE VECTOR SAVED")
    outcome = "COMPLETE" if successful_embeddings >= 20 else "INSUFFICIENT_SAMPLES"
    print(f"STEP_3B4_LIVE_BENCHMARK = {outcome}")
    return 0 if successful_embeddings >= 20 else 2


def main() -> None:
    raise SystemExit(run_live_benchmark())


if __name__ == "__main__":
    main()
