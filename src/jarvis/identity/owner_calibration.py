"""OWNER-only positive calibration for enrollment readiness.

This module deliberately does not estimate impostor rejection or a non-owner false
accept rate. It answers one narrower question: is the enrolled OWNER's live SFace
signal stable enough, under representative conditions, to proceed to secure
OWNER-template enrollment?
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import cv2

from jarvis.identity.calibration import (
    _DEFAULT_ANALYSIS_INTERVAL_SECONDS,
    _DEFAULT_MAXIMUM_SAMPLES,
    _DEFAULT_MINIMUM_SAMPLES,
    _DEFAULT_WINDOW_REQUIRED_ACCEPTS,
    _DEFAULT_WINDOW_SIZE,
    _capture_stage,
    _distribution,
    _format_distribution,
    _prototype,
    _rolling_accept_rate,
    _sample_quality_summary,
    _scores_against,
    CalibrationDistribution,
)
from jarvis.identity.model_assets import (
    ModelAssetCache,
    load_default_face_model_manifest,
)

_MINIMUM_OWNER_P05_FOR_ENROLLMENT = 0.70
_MINIMUM_OWNER_WINDOW_ACCEPT_RATE = 0.90


class OwnerCalibrationStatus(str, Enum):
    READY_FOR_ENROLLMENT = "ready_for_enrollment"
    UNSTABLE_OWNER_BASELINE = "unstable_owner_baseline"


@dataclass(frozen=True, slots=True)
class OwnerCalibrationResult:
    status: OwnerCalibrationStatus
    owner_reference_count: int
    owner_probe_count: int
    owner_scores: CalibrationDistribution
    provisional_accept_floor: float
    owner_point_accept_rate: float
    owner_window_accept_rate: float
    window_size: int
    window_required_accepts: int


def derive_owner_only_calibration(
    owner_features: list,
    *,
    minimum_samples: int = _DEFAULT_MINIMUM_SAMPLES,
    window_size: int = _DEFAULT_WINDOW_SIZE,
    window_required_accepts: int = _DEFAULT_WINDOW_REQUIRED_ACCEPTS,
) -> OwnerCalibrationResult:
    """Derive positive-only OWNER stability statistics.

    OWNER samples are split deterministically into alternating reference/probe sets.
    The reference half builds a normalized mean prototype. The held-out probe half
    measures positive similarity against that prototype. The OWNER p05 is reported
    as a provisional positive floor for later engineering, but it is *not* an
    impostor-rejection threshold and must not be used alone to grant authority.
    """
    if minimum_samples < 10:
        raise ValueError("minimum_samples must be at least 10")
    if len(owner_features) < minimum_samples:
        raise ValueError(
            f"OWNER calibration needs at least {minimum_samples} samples; "
            f"received {len(owner_features)}"
        )

    owner_reference = owner_features[::2]
    owner_probe = owner_features[1::2]
    if not owner_reference or not owner_probe:
        raise ValueError("OWNER calibration split produced an empty partition")

    reference = _prototype(owner_reference)
    owner_scores = _scores_against(reference, owner_probe)
    distribution = _distribution(owner_scores)
    provisional_accept_floor = distribution.p05

    point_accept_rate = sum(
        score >= provisional_accept_floor for score in owner_scores
    ) / len(owner_scores)
    window_accept_rate = _rolling_accept_rate(
        owner_scores,
        accept_threshold=provisional_accept_floor,
        window_size=window_size,
        required_accepts=window_required_accepts,
    )

    ready = (
        provisional_accept_floor >= _MINIMUM_OWNER_P05_FOR_ENROLLMENT
        and window_accept_rate >= _MINIMUM_OWNER_WINDOW_ACCEPT_RATE
    )
    status = (
        OwnerCalibrationStatus.READY_FOR_ENROLLMENT
        if ready
        else OwnerCalibrationStatus.UNSTABLE_OWNER_BASELINE
    )

    return OwnerCalibrationResult(
        status=status,
        owner_reference_count=len(owner_reference),
        owner_probe_count=len(owner_probe),
        owner_scores=distribution,
        provisional_accept_floor=provisional_accept_floor,
        owner_point_accept_rate=point_accept_rate,
        owner_window_accept_rate=window_accept_rate,
        window_size=window_size,
        window_required_accepts=window_required_accepts,
    )


def run_owner_calibration(
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

    print("JARVIS Step 3B.5A OWNER-only positive calibration")
    print("----------------------------------------------------")
    print("This command performs ONE camera/tracker session for the OWNER only.")
    print("All 128-D SFace features remain in RAM and are discarded before exit.")
    print("NO raw frame, aligned face, OWNER profile, or biometric template is saved.")
    print("This run measures OWNER stability only; it does NOT measure impostor FAR.")

    owner_stage = _capture_stage(
        stage_name="OWNER POSITIVE",
        yunet=yunet,
        sface=sface,
        minimum_samples=minimum_samples,
        maximum_samples=maximum_samples,
        analysis_interval_seconds=analysis_interval_seconds,
    )
    if owner_stage.aborted:
        print("STEP_3B5A_OWNER_CALIBRATION = ABORTED")
        return 2

    owner_features = [sample.feature for sample in owner_stage.samples]
    result = derive_owner_only_calibration(
        owner_features,
        minimum_samples=minimum_samples,
    )

    print()
    print("OWNER-ONLY CALIBRATION SUMMARY")
    print(f"OWNER valid samples: {len(owner_stage.samples)}")
    print(f"OWNER associated-head attempts: {owner_stage.associated_attempts}")
    _sample_quality_summary("OWNER", owner_stage.samples)
    print()
    print(_format_distribution("OWNER held-out scores", result.owner_scores))
    print()
    print(
        "Provisional OWNER positive floor (held-out p05): "
        f"{result.provisional_accept_floor:.4f}"
    )
    print(
        "Enrollment-quality p05 requirement: "
        f">= {_MINIMUM_OWNER_P05_FOR_ENROLLMENT:.2f}"
    )
    print(f"OWNER point accept rate: {result.owner_point_accept_rate * 100.0:.2f}%")
    print(
        f"Temporal stability rule: {result.window_required_accepts}/"
        f"{result.window_size} fresh valid scores >= positive floor and "
        "window median >= positive floor"
    )
    print(
        "OWNER rolling-window accept rate: "
        f"{result.owner_window_accept_rate * 100.0:.2f}%"
    )
    print(
        "Enrollment readiness requires p05 >= "
        f"{_MINIMUM_OWNER_P05_FOR_ENROLLMENT:.2f} and at least "
        f"{_MINIMUM_OWNER_WINDOW_ACCEPT_RATE * 100:.0f}% rolling-window stability."
    )
    print()
    print("IMPORTANT: no non-owner false-accept rate was measured in this run.")
    print("Anything not strongly matching OWNER remains UNKNOWN/AMBIGUOUS.")
    print("This positive floor is not sufficient by itself to grant T2 or authority.")
    print()
    print("NO OWNER PROFILE CREATED")
    print("NO BIOMETRIC TEMPLATE PERSISTED")
    print("NO FRAME, ALIGNED FACE, OR FEATURE VECTOR SAVED")
    print(f"STEP_3B5A_OWNER_CALIBRATION = {result.status.value.upper()}")

    owner_features.clear()
    return 0 if result.status is OwnerCalibrationStatus.READY_FOR_ENROLLMENT else 3


def main() -> None:
    raise SystemExit(run_owner_calibration())


if __name__ == "__main__":
    main()
