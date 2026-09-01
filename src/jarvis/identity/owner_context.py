from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

from jarvis.authority import (
    WindowsSessionProvider,
    WindowsSessionUnavailable,
    WindowsWtsSessionProvider,
)
from jarvis.identity.crypto import WindowsDpapiKeyProtector
from jarvis.identity.live_face_benchmark import (
    _crop_head,
    _face_rows,
    _select_center_face,
)
from jarvis.identity.model_assets import (
    ModelAssetCache,
    load_default_face_model_manifest,
)
from jarvis.identity.owner_enrollment import default_identity_data_dir
from jarvis.identity.owner_evidence import (
    OwnerIdentityObservation,
    OwnerLivenessBindingAssessment,
    OwnerLivenessBindingState,
    TemporalOwnerIdentity,
    bind_owner_liveness,
    max_prototype_cosine,
)
from jarvis.identity.owner_template_runtime import (
    RuntimeOwnerFaceTemplate,
    load_compatible_owner_face_template,
)
from jarvis.identity.passive_liveness import (
    PassiveLivenessObservation,
    TemporalPassiveLiveness,
)
from jarvis.identity.passive_pad import MiniFasEnsembleProvider, PassivePadProvider
from jarvis.identity.passive_pad_assets import (
    MINIFASNET_V1SE,
    MINIFASNET_V2,
    PassivePadAssetCache,
)
from jarvis.identity.store import SqliteOwnerProfileStore
from jarvis.vision.camera import CapturedFrame
from jarvis.vision.framing import HeadFirstFramingPolicy
from jarvis.vision.models import TargetState
from jarvis.vision.runtime import VisionSnapshot

LOGGER = logging.getLogger(__name__)

_DEFAULT_ANALYSIS_INTERVAL_SECONDS = 0.10
_DEFAULT_SESSION_POLL_INTERVAL_SECONDS = 0.25
_DEFAULT_EVIDENCE_TTL_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class OwnerContextSnapshot:
    assessment: OwnerLivenessBindingAssessment | None
    invalidation_reason: str | None


class OwnerContextState:
    """Thread-safe publication boundary from vision evidence to voice runtime."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._assessment: OwnerLivenessBindingAssessment | None = None
        self._invalidation_reason: str | None = "owner_context_not_observed"

    def publish(self, assessment: OwnerLivenessBindingAssessment) -> None:
        with self._lock:
            self._assessment = assessment
            self._invalidation_reason = None

    def invalidate(self, reason: str) -> None:
        if not reason.strip():
            raise ValueError("owner context invalidation reason must not be empty")
        with self._lock:
            self._assessment = None
            self._invalidation_reason = reason

    def snapshot(self) -> OwnerContextSnapshot:
        with self._lock:
            return OwnerContextSnapshot(
                assessment=self._assessment,
                invalidation_reason=self._invalidation_reason,
            )

    def has_fresh_live_owner_candidate(
        self,
        *,
        now_monotonic: float | None = None,
        max_age_seconds: float = _DEFAULT_EVIDENCE_TTL_SECONDS,
    ) -> bool:
        if max_age_seconds <= 0:
            raise ValueError("owner context max age must be positive")
        now = time.monotonic() if now_monotonic is None else now_monotonic
        with self._lock:
            assessment = self._assessment
        if assessment is None:
            return False
        age = now - assessment.observed_at_monotonic
        return (
            0.0 <= age <= max_age_seconds
            and assessment.state is OwnerLivenessBindingState.LIVE_OWNER_CANDIDATE
        )


class OwnerContextObserver:
    """Production observer for the accepted Step-3B.8 face+liveness evidence path.

    It consumes the exact camera frame paired with the canonical VisionSnapshot,
    never opens another camera, never persists biometric material, and publishes
    only the short-lived fused assessment needed by other runtime components.
    """

    def __init__(
        self,
        *,
        owner_template: RuntimeOwnerFaceTemplate,
        face_detector: object,
        face_recognizer: object,
        pad_provider: PassivePadProvider,
        session_provider: WindowsSessionProvider,
        state: OwnerContextState | None = None,
        framing_policy: HeadFirstFramingPolicy | None = None,
        analysis_interval_seconds: float = _DEFAULT_ANALYSIS_INTERVAL_SECONDS,
        session_poll_interval_seconds: float = _DEFAULT_SESSION_POLL_INTERVAL_SECONDS,
    ) -> None:
        if analysis_interval_seconds <= 0:
            raise ValueError("owner context analysis interval must be positive")
        if session_poll_interval_seconds <= 0:
            raise ValueError("owner context session poll interval must be positive")
        self.owner_template = owner_template
        self.face_detector = face_detector
        self.face_recognizer = face_recognizer
        self.pad_provider = pad_provider
        self.session_provider = session_provider
        self.state = state or OwnerContextState()
        self.framing_policy = framing_policy or HeadFirstFramingPolicy()
        self.analysis_interval_seconds = analysis_interval_seconds
        self.session_poll_interval_seconds = session_poll_interval_seconds
        self._session_id: str | None = None
        self._track_id: int | None = None
        self._identity_window: TemporalOwnerIdentity | None = None
        self._liveness_window: TemporalPassiveLiveness | None = None
        self._last_analysis_at: float | None = None
        self._last_session_poll_at: float | None = None

    def observe(self, frame: CapturedFrame, snapshot: VisionSnapshot) -> None:
        if snapshot.frame_id != frame.frame_id:
            self._invalidate("owner_context_frame_snapshot_mismatch")
            return

        if not self._refresh_windows_session(frame.captured_at):
            return

        selected = self._select_evidence_target(snapshot)
        if selected is None:
            self._invalidate("owner_context_requires_one_head_associated_subject")
            return
        target, head = selected

        if self._track_id != target.track_id:
            self._reset_binding(target.track_id)

        if (
            self._last_analysis_at is not None
            and frame.captured_at - self._last_analysis_at
            < self.analysis_interval_seconds
        ):
            return
        self._last_analysis_at = frame.captured_at

        identity_window = self._identity_window
        liveness_window = self._liveness_window
        session_id = self._session_id
        if identity_window is None or liveness_window is None or session_id is None:
            self._invalidate("owner_context_binding_unavailable")
            return

        try:
            crop = _crop_head(frame.image, head.bounds)
            crop_height, crop_width = crop.image.shape[:2]
            self.face_detector.setInputSize((crop_width, crop_height))
            faces = _face_rows(self.face_detector.detect(crop.image))
            if not faces.size:
                return
            face = _select_center_face(faces, width=crop_width, height=crop_height)
            aligned = self.face_recognizer.alignCrop(crop.image, face)
            feature = self.face_recognizer.feature(aligned)
            if feature is None or feature.size == 0 or not np.isfinite(feature).all():
                return

            similarity = max_prototype_cosine(self.owner_template.prototypes, feature)
            face_xyxy = _full_frame_face_xyxy(
                face,
                crop_left=crop.left,
                crop_top=crop.top,
                frame_width=frame.width,
                frame_height=frame.height,
            )
            pad_score = self.pad_provider.score(frame.image, face_xyxy)
            observed_at = frame.captured_at
            identity = identity_window.observe(
                OwnerIdentityObservation(
                    session_id=session_id,
                    visual_track_id=target.track_id,
                    provider_id=self.owner_template.provider_id,
                    observed_at_monotonic=observed_at,
                    max_prototype_cosine=similarity,
                )
            )
            liveness = liveness_window.observe(
                PassiveLivenessObservation(
                    session_id=session_id,
                    visual_track_id=target.track_id,
                    provider_id=self.pad_provider.provider_id,
                    observed_at_monotonic=observed_at,
                    real_probability=pad_score.real_probability,
                )
            )
            self.state.publish(bind_owner_liveness(identity, liveness))
        except Exception:
            self._invalidate("owner_context_inference_failed")
            LOGGER.exception("Live OWNER context inference failed closed")

    def close(self) -> None:
        self._invalidate("owner_context_observer_closed")

    def _refresh_windows_session(self, now: float) -> bool:
        if (
            self._last_session_poll_at is not None
            and now - self._last_session_poll_at < self.session_poll_interval_seconds
            and self._session_id is not None
        ):
            return True
        self._last_session_poll_at = now
        try:
            current = self.session_provider.current_session()
        except WindowsSessionUnavailable:
            self._invalidate("owner_context_windows_session_unavailable")
            return False
        if not current.active_unlocked:
            self._invalidate("owner_context_windows_session_locked")
            return False
        if current.session_id != self._session_id:
            self._session_id = current.session_id
            self._track_id = None
            self._identity_window = None
            self._liveness_window = None
            self._last_analysis_at = None
            self.state.invalidate("owner_context_windows_session_changed")
        return True

    def _select_evidence_target(
        self,
        snapshot: VisionSnapshot,
    ) -> tuple[TargetState, object] | None:
        heads = list(snapshot.heads)
        target = snapshot.target
        if target is not None and target.visible:
            head = self.framing_policy.associated_head(target, heads)
            if head is not None:
                return target, head
            return None

        candidates: list[tuple[TargetState, object]] = []
        for track in snapshot.tracks:
            candidate = TargetState(track_id=track.track_id, track=track)
            head = self.framing_policy.associated_head(candidate, heads)
            if head is not None:
                candidates.append((candidate, head))
        if len(candidates) != 1:
            return None
        return candidates[0]

    def _reset_binding(self, track_id: int) -> None:
        session_id = self._session_id
        if session_id is None:
            self._invalidate("owner_context_windows_session_unavailable")
            return
        self._track_id = track_id
        self._identity_window = TemporalOwnerIdentity(
            session_id=session_id,
            visual_track_id=track_id,
            face_provider_id=self.owner_template.provider_id,
        )
        self._liveness_window = TemporalPassiveLiveness(
            session_id=session_id,
            visual_track_id=track_id,
            pad_provider_id=self.pad_provider.provider_id,
        )
        self._last_analysis_at = None
        self.state.invalidate("owner_context_temporal_window_reset")

    def _invalidate(self, reason: str) -> None:
        if self._identity_window is not None:
            self._identity_window.clear()
        if self._liveness_window is not None:
            self._liveness_window.clear()
        self._track_id = None
        self._identity_window = None
        self._liveness_window = None
        self._last_analysis_at = None
        self.state.invalidate(reason)


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


def build_default_owner_context_observer() -> OwnerContextObserver:
    """Load the exact accepted 3B.8 OWNER template, SFace, and MiniFAS stack."""
    manifest = load_default_face_model_manifest()
    model_cache = ModelAssetCache()
    detector_asset = manifest.by_role("face_detector")
    recognizer_asset = manifest.by_role("face_recognizer")
    detector_path = model_cache.fetch(detector_asset)
    recognizer_path = model_cache.fetch(recognizer_asset)

    face_detector = cv2.FaceDetectorYN.create(
        str(detector_path),
        "",
        (320, 320),
        0.9,
        0.3,
        5000,
    )
    face_recognizer = cv2.FaceRecognizerSF.create(str(recognizer_path), "")

    identity_db = default_identity_data_dir() / "owner_identity.db"
    store = SqliteOwnerProfileStore(
        identity_db,
        key_protector=WindowsDpapiKeyProtector(),
    )
    try:
        owner_template = load_compatible_owner_face_template(store, recognizer_asset)
    finally:
        store.close()

    pad_cache = PassivePadAssetCache()
    v1se_path = pad_cache.fetch(MINIFASNET_V1SE)
    v2_path = pad_cache.fetch(MINIFASNET_V2)
    pad_provider = MiniFasEnsembleProvider(v1se_path, v2_path)

    return OwnerContextObserver(
        owner_template=owner_template,
        face_detector=face_detector,
        face_recognizer=face_recognizer,
        pad_provider=pad_provider,
        session_provider=WindowsWtsSessionProvider(),
    )
