from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections import Counter

import cv2
import numpy as np

from jarvis.authority import WindowsSessionUnavailable, WindowsWtsSessionProvider
from jarvis.identity.calibration import _build_runtime, _draw_clickable_heads
from jarvis.identity.crypto import WindowsDpapiKeyProtector
from jarvis.identity.face_template import FACE_TEMPLATE_FORMAT
from jarvis.identity.live_face_benchmark import (
    _crop_head,
    _face_rows,
    _select_center_face,
    _SelectionState,
)
from jarvis.identity.model_assets import ModelAssetCache, load_default_face_model_manifest
from jarvis.identity.owner_enrollment import default_identity_data_dir
from jarvis.identity.owner_evidence import (
    OwnerIdentityObservation,
    OwnerIdentityState,
    OwnerLivenessBindingAssessment,
    OwnerLivenessBindingState,
    TemporalOwnerIdentity,
    bind_owner_liveness,
    max_prototype_cosine,
)
from jarvis.identity.owner_template_runtime import (
    OwnerTemplateCompatibilityError,
    load_compatible_owner_face_template,
)
from jarvis.identity.passive_liveness import (
    PassiveLivenessObservation,
    PassiveLivenessState,
    TemporalPassiveLiveness,
)
from jarvis.identity.passive_pad import MiniFasEnsembleProvider
from jarvis.identity.passive_pad_assets import (
    MINIFASNET_V1SE,
    MINIFASNET_V2,
    PassivePadAssetCache,
    PassivePadAssetError,
)
from jarvis.identity.store import OwnerProfileStoreError, SqliteOwnerProfileStore
from jarvis.vision.models import TargetState
from jarvis.vision.observer import render_snapshot

_WINDOW_NAME = "JARVIS 3B.8 OWNER + Liveness Evidence"
_MIN_SAMPLES = 120
_MAX_SAMPLES = 300
_ANALYSIS_INTERVAL_SECONDS = 0.10
_SESSION_POLL_INTERVAL_SECONDS = 0.25


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot compute percentile of empty values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(np.floor(position))
    upper = int(np.ceil(position))
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


def _full_frame_face_xyxy(
    face: np.ndarray,
    *,
    crop_left: int,
    crop_top: int,
    frame_width: int,
    frame_height: int,
) -> tuple[int, int, int, int]:
    x, y, width, height = (float(value) for value in face[:4])
    left = max(0, min(frame_width - 1, round(crop_left + x)))
    top = max(0, min(frame_height - 1, round(crop_top + y)))
    right = max(left + 1, min(frame_width, round(crop_left + x + width)))
    bottom = max(top + 1, min(frame_height, round(crop_top + y + height)))
    return left, top, right, bottom


def _draw_overlay(
    preview: np.ndarray,
    *,
    sample_count: int,
    collecting: bool,
    identity_state: OwnerIdentityState,
    identity_similarity: float | None,
    liveness_state: PassiveLivenessState,
    liveness_probability: float | None,
    combined: OwnerLivenessBindingAssessment | None,
) -> None:
    run_state = "COLLECTING" if collecting else "READY"
    identity_value = "n/a" if identity_similarity is None else f"{identity_similarity:.3f}"
    liveness_value = (
        "n/a" if liveness_probability is None else f"{liveness_probability:.3f}"
    )
    combined_state = "n/a" if combined is None else combined.state.value
    lines = [
        f"3B.8 EVIDENCE ONLY | {run_state} | samples {sample_count}/{_MAX_SAMPLES}",
        f"identity={identity_state.value} temporal_cos={identity_value}",
        f"liveness={liveness_state.value} temporal_real={liveness_value}",
        f"combined={combined_state}",
        "T2 DISABLED | Click GREEN HEAD | S start | D finish >=120 | C clear | Q abort",
    ]
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


def run_owner_evidence_live(scenario: str) -> int:
    if sys.platform != "win32":
        print("Step 3B.8 OWNER evidence harness currently requires Windows.")
        return 2

    session_provider = WindowsWtsSessionProvider()
    try:
        initial_session = session_provider.current_session()
    except WindowsSessionUnavailable as exc:
        print(f"Windows session unavailable: {exc}")
        return 2
    if not initial_session.active_unlocked:
        print("Windows session is not active/unlocked; refusing to start evidence capture.")
        return 2

    manifest = load_default_face_model_manifest()
    model_cache = ModelAssetCache()
    detector_asset = manifest.by_role("face_detector")
    recognizer_asset = manifest.by_role("face_recognizer")
    detector_path = model_cache.fetch(detector_asset)
    recognizer_path = model_cache.fetch(recognizer_asset)

    yunet = cv2.FaceDetectorYN.create(
        str(detector_path),
        "",
        (320, 320),
        0.9,
        0.3,
        5000,
    )
    sface = cv2.FaceRecognizerSF.create(str(recognizer_path), "")

    identity_db = default_identity_data_dir() / "owner_identity.db"
    store = SqliteOwnerProfileStore(
        identity_db,
        key_protector=WindowsDpapiKeyProtector(),
    )
    try:
        owner_template = load_compatible_owner_face_template(store, recognizer_asset)
    except (OwnerProfileStoreError, OwnerTemplateCompatibilityError) as exc:
        store.close()
        print(f"OWNER template unavailable/incompatible: {exc}")
        print("STEP_3B8_OWNER_LIVENESS_EVIDENCE = FAIL_CLOSED")
        return 2
    finally:
        if "owner_template" in locals():
            store.close()

    if owner_template.embedding_dimension != 128:
        print(
            "OWNER template embedding dimension is not the expected SFace 128-D runtime."
        )
        print("STEP_3B8_OWNER_LIVENESS_EVIDENCE = FAIL_CLOSED")
        return 2

    pad_cache = PassivePadAssetCache()
    try:
        v1se_path = pad_cache.fetch(MINIFASNET_V1SE)
        v2_path = pad_cache.fetch(MINIFASNET_V2)
    except PassivePadAssetError as exc:
        print(f"Passive PAD assets unavailable: {exc}")
        return 2
    pad_provider = MiniFasEnsembleProvider(v1se_path, v2_path)

    runtime, framing_policy = _build_runtime()
    selection = _SelectionState()
    current_track_id: int | None = None
    identity_window: TemporalOwnerIdentity | None = None
    liveness_window: TemporalPassiveLiveness | None = None
    collecting = False
    last_analysis_at: float | None = None
    last_session_poll_at = 0.0
    identity_scores: list[float] = []
    liveness_scores: list[float] = []
    combined_counts: Counter[str] = Counter()
    identity_counts: Counter[str] = Counter()
    liveness_counts: Counter[str] = Counter()
    latest_combined: OwnerLivenessBindingAssessment | None = None
    last_face_rect: tuple[int, int, int, int] | None = None
    valid_observations = 0
    associated_attempts = 0
    session_invalidated = False

    def reset_windows(track_id: int | None) -> None:
        nonlocal identity_window, liveness_window, latest_combined
        if track_id is None:
            identity_window = None
            liveness_window = None
            latest_combined = None
            return
        identity_window = TemporalOwnerIdentity(
            session_id=initial_session.session_id,
            visual_track_id=track_id,
            face_provider_id=owner_template.provider_id,
        )
        liveness_window = TemporalPassiveLiveness(
            session_id=initial_session.session_id,
            visual_track_id=track_id,
            pad_provider_id=pad_provider.provider_id,
        )
        latest_combined = None

    print("JARVIS Step 3B.8 integrated OWNER + liveness evidence")
    print("------------------------------------------------------")
    print(f"scenario = {scenario}")
    print(f"Windows session = {initial_session.session_id}")
    print(f"OWNER profile version = {owner_template.profile_version}")
    print(f"OWNER template format = {FACE_TEMPLATE_FORMAT}")
    print(f"OWNER prototype count = {owner_template.prototype_count}")
    print(f"SFace model = {recognizer_asset.asset_id}")
    print(f"passive PAD provider = {pad_provider.provider_id}")
    print("Identity threshold is provisional/evidence-only because live non-owner calibration is still missing.")
    print("T2 is disabled. No action authority is exercised by this harness.")
    print("No frame, aligned face, SFace embedding, or PAD tensor/output is saved.")
    print("Wait for a GREEN associated head, click it once, press S, then behave naturally.")

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

            now = time.monotonic()
            if now - last_session_poll_at >= _SESSION_POLL_INTERVAL_SECONDS:
                last_session_poll_at = now
                try:
                    current_session = session_provider.current_session()
                except WindowsSessionUnavailable as exc:
                    print(f"Windows session became unavailable: {exc}")
                    session_invalidated = True
                    break
                if (
                    current_session.session_id != initial_session.session_id
                    or not current_session.active_unlocked
                ):
                    print(
                        "Windows session changed or locked; clearing identity/liveness "
                        "evidence and failing closed."
                    )
                    if identity_window is not None:
                        identity_window.clear()
                    if liveness_window is not None:
                        liveness_window.clear()
                    session_invalidated = True
                    break

            heads = list(snapshot.heads)
            clickable_head_regions = []
            for track in snapshot.tracks:
                if not runtime.head_lock_eligible(track.track_id):
                    continue
                candidate = TargetState(track_id=track.track_id, track=track)
                associated = framing_policy.associated_head(candidate, heads)
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
                    print(f"Track {requested_track} is already selected; no reset performed.")
                else:
                    try:
                        runtime.lock(requested_track)
                    except ValueError as exc:
                        print(exc)
                    else:
                        current_track_id = requested_track
                        reset_windows(current_track_id)
                        collecting = False
                        last_analysis_at = None
                        last_face_rect = None
                        print(
                            f"Locked track {requested_track}; temporal windows reset. "
                            "Press S when ready."
                        )

            target = runtime.target
            if target is None:
                current_track_id = None
            elif current_track_id is not None and target.track_id != current_track_id:
                current_track_id = target.track_id
                reset_windows(current_track_id)
                collecting = False
                last_analysis_at = None
                last_face_rect = None
                print(f"Target changed to track {current_track_id}; windows reset.")

            head = framing_policy.associated_head(target, heads)
            should_analyze = (
                collecting
                and target is not None
                and target.visible
                and head is not None
                and identity_window is not None
                and liveness_window is not None
                and valid_observations < _MAX_SAMPLES
                and (
                    last_analysis_at is None
                    or frame.captured_at - last_analysis_at
                    >= _ANALYSIS_INTERVAL_SECONDS
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
                        similarity = max_prototype_cosine(
                            owner_template.prototypes,
                            feature,
                        )
                        face_xyxy = _full_frame_face_xyxy(
                            face,
                            crop_left=crop.left,
                            crop_top=crop.top,
                            frame_width=frame.width,
                            frame_height=frame.height,
                        )
                        pad_score = pad_provider.score(frame.image, face_xyxy)
                        observed_at = frame.captured_at
                        identity = identity_window.observe(
                            OwnerIdentityObservation(
                                session_id=initial_session.session_id,
                                visual_track_id=target.track_id,
                                provider_id=owner_template.provider_id,
                                observed_at_monotonic=observed_at,
                                max_prototype_cosine=similarity,
                            )
                        )
                        liveness = liveness_window.observe(
                            PassiveLivenessObservation(
                                session_id=initial_session.session_id,
                                visual_track_id=target.track_id,
                                provider_id=pad_provider.provider_id,
                                observed_at_monotonic=observed_at,
                                real_probability=pad_score.real_probability,
                            )
                        )
                        latest_combined = bind_owner_liveness(identity, liveness)
                        identity_scores.append(similarity)
                        liveness_scores.append(pad_score.real_probability)
                        identity_counts[identity.state.value] += 1
                        liveness_counts[liveness.state.value] += 1
                        combined_counts[latest_combined.state.value] += 1
                        valid_observations += 1
                        last_face_rect = face_xyxy
                        if valid_observations >= _MAX_SAMPLES:
                            break

            preview = render_snapshot(frame.image, snapshot)
            _draw_clickable_heads(preview, clickable_head_regions)
            if last_face_rect is not None:
                left, top, right, bottom = last_face_rect
                cv2.rectangle(preview, (left, top), (right, bottom), (0, 255, 255), 2)
            identity_assessment = (
                identity_window.assessment if identity_window is not None else None
            )
            liveness_assessment = (
                liveness_window.assessment if liveness_window is not None else None
            )
            _draw_overlay(
                preview,
                sample_count=valid_observations,
                collecting=collecting,
                identity_state=(
                    OwnerIdentityState.INSUFFICIENT
                    if identity_assessment is None
                    else identity_assessment.state
                ),
                identity_similarity=(
                    None
                    if identity_assessment is None
                    else identity_assessment.temporal_similarity
                ),
                liveness_state=(
                    PassiveLivenessState.INSUFFICIENT
                    if liveness_assessment is None
                    else liveness_assessment.state
                ),
                liveness_probability=(
                    None
                    if liveness_assessment is None
                    else liveness_assessment.temporal_real_probability
                ),
                combined=latest_combined,
            )
            cv2.imshow(_WINDOW_NAME, preview)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                print("STEP_3B8_OWNER_LIVENESS_EVIDENCE = ABORTED")
                return 2
            if key in (ord("c"), ord("C")):
                runtime.clear_target()
                current_track_id = None
                reset_windows(None)
                collecting = False
                last_analysis_at = None
                last_face_rect = None
                print("Selected target cleared; temporal evidence windows discarded.")
            if key in (ord("s"), ord("S")):
                if runtime.target is None or identity_window is None or liveness_window is None:
                    print("Select one GREEN associated head before starting.")
                else:
                    collecting = True
                    last_analysis_at = None
                    print("Integrated OWNER+liveness evidence collection started.")
            if key in (ord("d"), ord("D")):
                if valid_observations < _MIN_SAMPLES:
                    print(
                        f"Need at least {_MIN_SAMPLES} observations before finishing; "
                        f"have {valid_observations}."
                    )
                else:
                    break
    finally:
        runtime.close()
        cv2.destroyAllWindows()

    print()
    print("OWNER + LIVENESS EVIDENCE SUMMARY")
    print(f"scenario = {scenario}")
    print(f"windows_session = {initial_session.session_id}")
    print(f"valid_integrated_observations = {valid_observations}")
    print(f"associated_head_attempts = {associated_attempts}")
    print(_distribution("max_prototype_cosine", identity_scores))
    print(_distribution("minifas_real_probability", liveness_scores))
    print(f"identity_state_counts = {dict(sorted(identity_counts.items()))}")
    print(f"liveness_state_counts = {dict(sorted(liveness_counts.items()))}")
    print(f"combined_state_counts = {dict(sorted(combined_counts.items()))}")
    print(f"session_invalidated = {session_invalidated}")
    print("frames_saved = False")
    print("aligned_faces_saved = False")
    print("sface_embeddings_saved = False")
    print("pad_tensors_saved = False")
    print("pad_output_vectors_saved = False")
    print("identity_threshold_authoritative = False")
    print("live_non_owner_calibration_available = False")
    print("face_evidence_grants_T2 = False")
    print("STEP_3B8_OWNER_LIVENESS_EVIDENCE = COMPLETE")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="JARVIS Step 3B.8 OWNER identity + liveness evidence harness"
    )
    parser.add_argument(
        "--scenario",
        choices=("live", "phone-photo", "phone-video", "session-lock", "other"),
        default="live",
        help="Human-declared acceptance scenario; used only in the printed summary.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    raise SystemExit(run_owner_evidence_live(args.scenario))


if __name__ == "__main__":
    main()
