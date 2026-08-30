"""Non-persistent Pocket-3 SFace positive/negative calibration harness."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from enum import Enum

import cv2
import numpy as np

from jarvis.identity.live_face_benchmark import (
    _NoOpPtz,
    _SelectionState,
    _crop_head,
    _face_rows,
    _select_center_face,
)
from jarvis.identity.model_assets import (
    ModelAssetCache,
    load_default_face_model_manifest,
)

_WINDOW_NAME = "JARVIS Face Calibration"
_DEFAULT_MINIMUM_SAMPLES = 120
_DEFAULT_MAXIMUM_SAMPLES = 240
_DEFAULT_ANALYSIS_INTERVAL_SECONDS = 0.20
_DEFAULT_WINDOW_SIZE = 5
_DEFAULT_WINDOW_REQUIRED_ACCEPTS = 4
_MINIMUM_OWNER_WINDOW_ACCEPT_RATE = 0.90


class CalibrationStatus(str, Enum):
    CANDIDATE_READY = "candidate_ready"
    INSUFFICIENT_SEPARATION = "insufficient_separation"


@dataclass(frozen=True, slots=True)
class CalibrationSample:
    feature: np.ndarray
    yunet_confidence: float
    brightness: float
    sharpness: float
    head_width_px: int
    head_height_px: int


@dataclass(frozen=True, slots=True)
class CalibrationDistribution:
    count: int
    minimum: float
    p01: float
    p05: float
    median: float
    p95: float
    p99: float
    maximum: float


@dataclass(frozen=True, slots=True)
class FaceCalibrationResult:
    status: CalibrationStatus
    owner_reference_count: int
    owner_probe_count: int
    non_owner_count: int
    owner_scores: CalibrationDistribution
    non_owner_scores: CalibrationDistribution
    reject_threshold: float
    accept_threshold: float
    ambiguity_width: float
    owner_point_accept_rate: float
    non_owner_point_false_accept_rate: float
    owner_window_accept_rate: float
    non_owner_window_false_accept_rate: float
    window_size: int
    window_required_accepts: int


@dataclass(frozen=True, slots=True)
class _StageResult:
    samples: tuple[CalibrationSample, ...]
    associated_attempts: int
    aborted: bool


def _normalize_feature(feature: np.ndarray) -> np.ndarray:
    vector = np.asarray(feature, dtype=np.float32).reshape(-1)
    if vector.size == 0 or not np.isfinite(vector).all():
        raise ValueError("face feature must be finite and non-empty")
    norm = float(np.linalg.norm(vector))
    if norm <= 0:
        raise ValueError("face feature norm must be positive")
    return vector / norm


def _prototype(features: list[np.ndarray]) -> np.ndarray:
    if not features:
        raise ValueError("prototype requires at least one feature")
    normalized = np.stack([_normalize_feature(feature) for feature in features])
    return _normalize_feature(np.mean(normalized, axis=0))


def _scores_against(prototype: np.ndarray, features: list[np.ndarray]) -> list[float]:
    reference = _normalize_feature(prototype)
    return [
        float(np.dot(reference, _normalize_feature(feature))) for feature in features
    ]


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0 <= percentile <= 100:
        raise ValueError("percentile must be in [0, 100]")
    return float(np.percentile(np.asarray(values, dtype=np.float64), percentile))


def _distribution(values: list[float]) -> CalibrationDistribution:
    if not values:
        raise ValueError("distribution requires at least one value")
    return CalibrationDistribution(
        count=len(values),
        minimum=min(values),
        p01=_percentile(values, 1),
        p05=_percentile(values, 5),
        median=statistics.median(values),
        p95=_percentile(values, 95),
        p99=_percentile(values, 99),
        maximum=max(values),
    )


def _rolling_accept_rate(
    scores: list[float],
    *,
    accept_threshold: float,
    window_size: int,
    required_accepts: int,
) -> float:
    if window_size < 1:
        raise ValueError("window_size must be positive")
    if not 1 <= required_accepts <= window_size:
        raise ValueError("required_accepts must be within the window")
    if len(scores) < window_size:
        return 0.0

    outcomes: list[bool] = []
    for start in range(0, len(scores) - window_size + 1):
        window = scores[start : start + window_size]
        accepts = sum(score >= accept_threshold for score in window)
        outcomes.append(
            accepts >= required_accepts
            and statistics.median(window) >= accept_threshold
        )
    return sum(outcomes) / len(outcomes)


def derive_face_calibration(
    owner_features: list[np.ndarray],
    non_owner_features: list[np.ndarray],
    *,
    minimum_samples: int = _DEFAULT_MINIMUM_SAMPLES,
    window_size: int = _DEFAULT_WINDOW_SIZE,
    window_required_accepts: int = _DEFAULT_WINDOW_REQUIRED_ACCEPTS,
) -> FaceCalibrationResult:
    """Derive a conservative candidate band from live positive/negative features.

    OWNER samples are split deterministically into alternating reference/probe sets.
    A normalized mean reference prototype is built only from the reference half. The
    positive distribution is the held-out OWNER probe similarity to that prototype;
    the negative distribution is the consenting non-owner similarity to the same
    prototype. The 5th percentile positive score becomes the candidate ACCEPT floor
    and the 99th percentile negative score becomes the candidate REJECT ceiling.
    Values between those bounds are deliberately AMBIGUOUS.

    A candidate is only considered ready when the percentile bands separate, at
    least 90% of rolling OWNER windows satisfy the proposed temporal rule, and no
    rolling non-owner window is observed to satisfy it.
    """
    if minimum_samples < 10:
        raise ValueError("minimum_samples must be at least 10")
    if len(owner_features) < minimum_samples:
        raise ValueError(
            f"OWNER calibration needs at least {minimum_samples} samples; "
            f"received {len(owner_features)}"
        )
    if len(non_owner_features) < minimum_samples:
        raise ValueError(
            f"non-owner calibration needs at least {minimum_samples} samples; "
            f"received {len(non_owner_features)}"
        )

    owner_reference = owner_features[::2]
    owner_probe = owner_features[1::2]
    if not owner_reference or not owner_probe:
        raise ValueError("OWNER calibration split produced an empty partition")

    reference = _prototype(owner_reference)
    owner_scores = _scores_against(reference, owner_probe)
    non_owner_scores = _scores_against(reference, non_owner_features)
    owner_distribution = _distribution(owner_scores)
    non_owner_distribution = _distribution(non_owner_scores)

    accept_threshold = owner_distribution.p05
    reject_threshold = non_owner_distribution.p99
    ambiguity_width = accept_threshold - reject_threshold

    owner_point_accept_rate = sum(
        score >= accept_threshold for score in owner_scores
    ) / len(owner_scores)
    non_owner_point_false_accept_rate = sum(
        score >= accept_threshold for score in non_owner_scores
    ) / len(non_owner_scores)

    owner_window_accept_rate = _rolling_accept_rate(
        owner_scores,
        accept_threshold=accept_threshold,
        window_size=window_size,
        required_accepts=window_required_accepts,
    )
    non_owner_window_false_accept_rate = _rolling_accept_rate(
        non_owner_scores,
        accept_threshold=accept_threshold,
        window_size=window_size,
        required_accepts=window_required_accepts,
    )

    candidate_ready = (
        ambiguity_width > 0
        and owner_window_accept_rate >= _MINIMUM_OWNER_WINDOW_ACCEPT_RATE
        and non_owner_window_false_accept_rate == 0.0
    )
    status = (
        CalibrationStatus.CANDIDATE_READY
        if candidate_ready
        else CalibrationStatus.INSUFFICIENT_SEPARATION
    )

    return FaceCalibrationResult(
        status=status,
        owner_reference_count=len(owner_reference),
        owner_probe_count=len(owner_probe),
        non_owner_count=len(non_owner_features),
        owner_scores=owner_distribution,
        non_owner_scores=non_owner_distribution,
        reject_threshold=reject_threshold,
        accept_threshold=accept_threshold,
        ambiguity_width=ambiguity_width,
        owner_point_accept_rate=owner_point_accept_rate,
        non_owner_point_false_accept_rate=non_owner_point_false_accept_rate,
        owner_window_accept_rate=owner_window_accept_rate,
        non_owner_window_false_accept_rate=non_owner_window_false_accept_rate,
        window_size=window_size,
        window_required_accepts=window_required_accepts,
    )


def _build_runtime():
    from jarvis.vision.camera import OpenCVCameraSource
    from jarvis.vision.detector import RFDetrNanoDetector
    from jarvis.vision.follow import FollowConfig, FollowController
    from jarvis.vision.framing import HeadFirstFramingPolicy
    from jarvis.vision.head_mediapipe import (
        MediaPipeBlazeFaceConfig,
        MediaPipeBlazeFaceDetector,
        default_blazeface_model_path,
    )
    from jarvis.vision.runtime import VisionRuntime, VisionRuntimeConfig
    from jarvis.vision.targeting import TargetManager
    from jarvis.vision.tracker import ByteTrackAdapter

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
    return runtime, framing_policy


def _draw_stage_overlay(
    preview: np.ndarray,
    *,
    stage_name: str,
    sample_count: int,
    minimum_samples: int,
    maximum_samples: int,
) -> None:
    ready = sample_count >= minimum_samples
    lines = [
        (
            f"3B.5 {stage_name} | samples {sample_count}/{minimum_samples} minimum "
            f"({maximum_samples} max)"
        ),
        "click GREEN HEAD to lock | C clear target | R reset stage | Q abort",
        (
            "D finish this stage"
            if ready
            else "Move naturally: frontal, left/right, near/far, slight up/down."
        ),
        "NO frames or face embeddings are written to disk.",
    ]
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


def _draw_clickable_heads(preview: np.ndarray, head_regions) -> None:
    height, width = preview.shape[:2]
    for track_id, bounds in head_regions:
        left = round(bounds.left * width)
        top = round(bounds.top * height)
        right = round(bounds.right * width)
        bottom = round(bounds.bottom * height)
        cv2.rectangle(preview, (left, top), (right, bottom), (0, 255, 0), 3)
        cv2.putText(
            preview,
            f"CLICK -> TRACK {track_id}",
            (left, min(height - 8, bottom + 22)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )


def _capture_stage(
    *,
    stage_name: str,
    yunet,
    sface,
    minimum_samples: int,
    maximum_samples: int,
    analysis_interval_seconds: float,
) -> _StageResult:
    from jarvis.vision.models import TargetState
    from jarvis.vision.observer import render_snapshot

    runtime, framing_policy = _build_runtime()
    selection = _SelectionState()
    samples: list[CalibrationSample] = []
    associated_attempts = 0
    last_analysis_at: float | None = None
    last_face_rect: tuple[int, int, int, int] | None = None
    aborted = False

    cv2.namedWindow(_WINDOW_NAME)
    cv2.setMouseCallback(_WINDOW_NAME, selection.on_mouse)

    print()
    print(f"{stage_name} CAPTURE")
    print("-" * (len(stage_name) + 8))
    print("Wait for a GREEN associated head, click it once, then move naturally.")
    print(f"Collect at least {minimum_samples} valid SFace samples, then press D.")
    print("C clears only the selected track. R deliberately resets this stage.")

    try:
        runtime.start()
        while True:
            snapshot = runtime.process_once(timeout_seconds=1.0)
            if snapshot is None:
                continue
            frame = runtime.latest_frame
            if frame is None:
                continue

            heads = list(snapshot.heads)
            clickable_head_regions = []
            for track in snapshot.tracks:
                if not runtime.head_lock_eligible(track.track_id):
                    continue
                candidate_target = TargetState(track_id=track.track_id, track=track)
                associated = framing_policy.associated_head(candidate_target, heads)
                if associated is not None:
                    clickable_head_regions.append((track.track_id, associated.bounds))

            selection.update(
                snapshot.tracks,
                head_regions=clickable_head_regions,
                width=frame.width,
                height=frame.height,
            )
            if selection.clicked_track_id is not None:
                requested_track = selection.clicked_track_id
                selection.clicked_track_id = None
                target = runtime.target
                if target is not None and target.track_id == requested_track:
                    print(
                        f"Track {requested_track} is already selected; capture continues."
                    )
                else:
                    try:
                        runtime.lock(requested_track)
                        print(
                            f"Locked track {requested_track}; {stage_name} capture active."
                        )
                    except ValueError as exc:
                        print(exc)

            target = runtime.target
            head = framing_policy.associated_head(target, heads)
            should_analyze = (
                len(samples) < maximum_samples
                and head is not None
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
                faces = _face_rows(yunet.detect(crop.image))

                if faces.size:
                    face = _select_center_face(
                        faces,
                        width=crop_width,
                        height=crop_height,
                    )
                    aligned = sface.alignCrop(crop.image, face)
                    feature = sface.feature(aligned)
                    if (
                        feature is not None
                        and feature.size > 0
                        and np.isfinite(feature).all()
                    ):
                        feature_copy = np.asarray(feature, dtype=np.float32).copy()
                        gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
                        sample = CalibrationSample(
                            feature=feature_copy,
                            yunet_confidence=float(face[-1]),
                            brightness=float(np.mean(gray)),
                            sharpness=float(cv2.Laplacian(gray, cv2.CV_64F).var()),
                            head_width_px=max(
                                1, round(head.bounds.width * frame.width)
                            ),
                            head_height_px=max(
                                1, round(head.bounds.height * frame.height)
                            ),
                        )
                        samples.append(sample)

                        x, y, face_width, face_height = (
                            round(float(value)) for value in face[:4]
                        )
                        last_face_rect = (
                            crop.left + x,
                            crop.top + y,
                            crop.left + x + face_width,
                            crop.top + y + face_height,
                        )

            preview = render_snapshot(frame.image, snapshot)
            _draw_clickable_heads(preview, clickable_head_regions)
            if last_face_rect is not None:
                left, top, right, bottom = last_face_rect
                cv2.rectangle(preview, (left, top), (right, bottom), (0, 255, 255), 2)
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
            _draw_stage_overlay(
                preview,
                stage_name=stage_name,
                sample_count=len(samples),
                minimum_samples=minimum_samples,
                maximum_samples=maximum_samples,
            )
            cv2.imshow(_WINDOW_NAME, preview)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                aborted = True
                break
            if key in (ord("c"), ord("C")):
                runtime.clear_target()
                last_face_rect = None
                print("Selected target cleared; collected samples were retained.")
            if key in (ord("r"), ord("R")):
                runtime.clear_target()
                samples.clear()
                associated_attempts = 0
                last_face_rect = None
                last_analysis_at = None
                print(f"{stage_name} samples deliberately reset to zero.")
            if key in (ord("d"), ord("D")):
                if len(samples) < minimum_samples:
                    print(
                        f"Need {minimum_samples - len(samples)} more valid samples "
                        f"before finishing {stage_name}."
                    )
                else:
                    break
    finally:
        runtime.close()
        cv2.destroyAllWindows()

    return _StageResult(
        samples=tuple(samples),
        associated_attempts=associated_attempts,
        aborted=aborted,
    )


def _format_distribution(name: str, distribution: CalibrationDistribution) -> str:
    return (
        f"{name}: n={distribution.count}, min={distribution.minimum:.4f}, "
        f"p01={distribution.p01:.4f}, p05={distribution.p05:.4f}, "
        f"median={distribution.median:.4f}, p95={distribution.p95:.4f}, "
        f"p99={distribution.p99:.4f}, max={distribution.maximum:.4f}"
    )


def _sample_quality_summary(name: str, samples: tuple[CalibrationSample, ...]) -> None:
    if not samples:
        return
    print(
        f"{name} quality: YuNet median="
        f"{statistics.median(sample.yunet_confidence for sample in samples):.3f}, "
        f"brightness median="
        f"{statistics.median(sample.brightness for sample in samples):.1f}, "
        f"sharpness median="
        f"{statistics.median(sample.sharpness for sample in samples):.1f}, "
        f"head median="
        f"{statistics.median(sample.head_width_px for sample in samples):.0f}x"
        f"{statistics.median(sample.head_height_px for sample in samples):.0f}px"
    )


def run_calibration(
    *,
    minimum_samples: int = _DEFAULT_MINIMUM_SAMPLES,
    maximum_samples: int = _DEFAULT_MAXIMUM_SAMPLES,
    analysis_interval_seconds: float = _DEFAULT_ANALYSIS_INTERVAL_SECONDS,
) -> int:
    if minimum_samples < 10:
        raise ValueError("minimum_samples must be at least 10")
    if maximum_samples < minimum_samples:
        raise ValueError("maximum_samples must be at least minimum_samples")
    if analysis_interval_seconds <= 0:
        raise ValueError("analysis_interval_seconds must be positive")

    manifest = load_default_face_model_manifest()
    cache = ModelAssetCache()
    detector_path = cache.fetch(manifest.by_role("face_detector"))
    recognizer_path = cache.fetch(manifest.by_role("face_recognizer"))

    yunet = cv2.FaceDetectorYN.create(
        str(detector_path),
        "",
        (320, 320),
        0.9,
        0.3,
        5000,
    )
    sface = cv2.FaceRecognizerSF.create(str(recognizer_path), "")

    print("JARVIS Step 3B.5 non-persistent face calibration")
    print("-------------------------------------------------")
    print("This command performs two fresh camera/tracker sessions.")
    print("Stage 1 captures OWNER-positive samples in RAM only.")
    print(
        "Stage 2 captures a consenting adult's non-owner-negative samples in RAM only."
    )
    print(
        "NO raw frame, aligned face, 128-D feature, OWNER profile, or template is saved."
    )
    print("The final output is numeric candidate calibration statistics only.")

    owner_stage = _capture_stage(
        stage_name="OWNER POSITIVE",
        yunet=yunet,
        sface=sface,
        minimum_samples=minimum_samples,
        maximum_samples=maximum_samples,
        analysis_interval_seconds=analysis_interval_seconds,
    )
    if owner_stage.aborted:
        print("STEP_3B5_CALIBRATION = ABORTED")
        return 2

    print()
    print("OWNER capture is complete and its camera/tracker session is closed.")
    print("Have the OWNER leave the camera view before the next session starts.")
    print("Use a different adult only if they have explicitly agreed to this test.")
    consent = input(
        "Type CONSENT after the other adult has agreed, or anything else to abort: "
    )
    if consent.strip().upper() != "CONSENT":
        print(
            "Consent acknowledgement was not provided; negative capture was not started."
        )
        print("STEP_3B5_CALIBRATION = ABORTED")
        return 2

    non_owner_stage = _capture_stage(
        stage_name="NON-OWNER NEGATIVE",
        yunet=yunet,
        sface=sface,
        minimum_samples=minimum_samples,
        maximum_samples=maximum_samples,
        analysis_interval_seconds=analysis_interval_seconds,
    )
    if non_owner_stage.aborted:
        print("STEP_3B5_CALIBRATION = ABORTED")
        return 2

    owner_features = [sample.feature for sample in owner_stage.samples]
    non_owner_features = [sample.feature for sample in non_owner_stage.samples]
    result = derive_face_calibration(
        owner_features,
        non_owner_features,
        minimum_samples=minimum_samples,
    )

    print()
    print("FACE CALIBRATION SUMMARY")
    print(f"OWNER valid samples: {len(owner_stage.samples)}")
    print(f"OWNER associated-head attempts: {owner_stage.associated_attempts}")
    print(f"NON-OWNER valid samples: {len(non_owner_stage.samples)}")
    print(f"NON-OWNER associated-head attempts: {non_owner_stage.associated_attempts}")
    _sample_quality_summary("OWNER", owner_stage.samples)
    _sample_quality_summary("NON-OWNER", non_owner_stage.samples)
    print()
    print(_format_distribution("OWNER held-out scores", result.owner_scores))
    print(_format_distribution("NON-OWNER scores", result.non_owner_scores))
    print()
    print(f"Candidate REJECT ceiling (non-owner p99): {result.reject_threshold:.4f}")
    print(f"Candidate ACCEPT floor (OWNER p05): {result.accept_threshold:.4f}")
    print(f"Candidate ambiguity width: {result.ambiguity_width:.4f}")
    print(f"OWNER point accept rate: {result.owner_point_accept_rate * 100.0:.2f}%")
    print(
        "NON-OWNER point false-accept rate at ACCEPT floor: "
        f"{result.non_owner_point_false_accept_rate * 100.0:.4f}%"
    )
    print(
        f"Candidate temporal rule: {result.window_required_accepts}/"
        f"{result.window_size} consecutive valid scores >= ACCEPT and "
        "window median >= ACCEPT"
    )
    print(
        "OWNER rolling-window accept rate: "
        f"{result.owner_window_accept_rate * 100.0:.2f}%"
    )
    print(
        "NON-OWNER rolling-window false-accept rate: "
        f"{result.non_owner_window_false_accept_rate * 100.0:.4f}%"
    )
    print(
        "Candidate readiness requires separated percentile bands, at least "
        f"{_MINIMUM_OWNER_WINDOW_ACCEPT_RATE * 100:.0f}% OWNER rolling-window "
        "acceptance, and zero observed non-owner rolling-window false accepts."
    )
    print()
    print("NO OWNER PROFILE CREATED")
    print("NO BIOMETRIC TEMPLATE PERSISTED")
    print("NO FRAME, ALIGNED FACE, OR FEATURE VECTOR SAVED")
    print("Thresholds are CANDIDATES only; human review is required before enrollment.")
    print(f"STEP_3B5_CALIBRATION = {result.status.value.upper()}")

    owner_features.clear()
    non_owner_features.clear()
    return 0 if result.status is CalibrationStatus.CANDIDATE_READY else 3


def main() -> None:
    raise SystemExit(run_calibration())


if __name__ == "__main__":
    main()
