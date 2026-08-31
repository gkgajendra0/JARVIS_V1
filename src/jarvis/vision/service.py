"""Background ownership boundary for integrated JARVIS vision."""

from __future__ import annotations

import logging
import os
import queue
from collections.abc import Callable
from pathlib import Path
from threading import Event, RLock, Thread

from jarvis.vision.camera import CapturedFrame
from jarvis.vision.diagnostics import VisionDiagnostics
from jarvis.vision.observer import VisionObserver
from jarvis.vision.runtime import VisionRuntime, VisionSnapshot

LOGGER = logging.getLogger(__name__)

_HEAD_MODEL_NAME = "blaze_face_full_range.tflite"
FramePairTap = Callable[[CapturedFrame, VisionSnapshot], None]


class VisionService:
    """Run one VisionRuntime continuously and expose thread-safe test controls."""

    def __init__(
        self,
        runtime: VisionRuntime,
        *,
        diagnostics: VisionDiagnostics | None = None,
        observer: VisionObserver | None = None,
        evidence_observer: VisionObserver | None = None,
        frame_pair_tap: FramePairTap | None = None,
        frame_pair_tap_max_snapshot_age_seconds: float = 0.15,
        process_timeout_seconds: float = 0.20,
    ) -> None:
        if process_timeout_seconds <= 0:
            raise ValueError("process_timeout_seconds must be positive")
        if frame_pair_tap_max_snapshot_age_seconds <= 0:
            raise ValueError("frame-pair tap snapshot age must be positive")
        self.runtime = runtime
        self.diagnostics = diagnostics or VisionDiagnostics()
        self._observer = observer
        self._evidence_observer = evidence_observer
        self._frame_pair_tap = frame_pair_tap
        self._frame_pair_tap_max_snapshot_age_seconds = (
            frame_pair_tap_max_snapshot_age_seconds
        )
        self._process_timeout_seconds = process_timeout_seconds
        self._runtime_lock = RLock()
        self._snapshot_lock = RLock()
        self._lifecycle_lock = RLock()
        self._stop_requested = Event()
        self._thread: Thread | None = None
        self._observer_thread: Thread | None = None
        self._evidence_thread: Thread | None = None
        self._frame_pair_thread: Thread | None = None
        self._latest_snapshot: VisionSnapshot | None = None
        self._evidence_queue: queue.Queue[tuple[CapturedFrame, VisionSnapshot]] = (
            queue.Queue(maxsize=1)
        )

    @property
    def running(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    def start(self) -> None:
        with self._lifecycle_lock:
            if self.running:
                return
            self._stop_requested.clear()
            self._clear_evidence_queue()
            with self._snapshot_lock:
                self._latest_snapshot = None
            with self._runtime_lock:
                self.runtime.start()
            self.diagnostics.set_running(True)
            self._thread = Thread(
                target=self._run_loop,
                name="jarvis-vision",
                daemon=True,
            )
            self._thread.start()
            if self._frame_pair_tap is not None:
                self._frame_pair_thread = Thread(
                    target=self._frame_pair_loop,
                    name="jarvis-vision-frame-tap",
                    daemon=True,
                )
                self._frame_pair_thread.start()
            if self._observer is not None:
                self._observer_thread = Thread(
                    target=self._observer_loop,
                    name="jarvis-vision-observer",
                    daemon=True,
                )
                self._observer_thread.start()
            if self._evidence_observer is not None:
                self._evidence_thread = Thread(
                    target=self._evidence_observer_loop,
                    name="jarvis-vision-evidence",
                    daemon=True,
                )
                self._evidence_thread.start()

    def stop(self, *, join_timeout_seconds: float = 3.0) -> None:
        if join_timeout_seconds <= 0:
            raise ValueError("join_timeout_seconds must be positive")
        with self._lifecycle_lock:
            thread = self._thread
            frame_pair_thread = self._frame_pair_thread
            observer_thread = self._observer_thread
            evidence_thread = self._evidence_thread
            if thread is None:
                return
            self._stop_requested.set()
        thread.join(timeout=join_timeout_seconds)
        if thread.is_alive():
            raise RuntimeError(
                "vision service did not stop within the shutdown timeout"
            )
        if frame_pair_thread is not None:
            frame_pair_thread.join(timeout=join_timeout_seconds)
            if frame_pair_thread.is_alive():
                raise RuntimeError(
                    "vision frame-pair tap did not stop within the shutdown timeout"
                )
        if observer_thread is not None:
            observer_thread.join(timeout=join_timeout_seconds)
            if observer_thread.is_alive():
                raise RuntimeError(
                    "vision observer did not stop within the shutdown timeout"
                )
        if evidence_thread is not None:
            evidence_thread.join(timeout=join_timeout_seconds)
            if evidence_thread.is_alive():
                raise RuntimeError(
                    "vision evidence observer did not stop within the shutdown timeout"
                )
        with self._lifecycle_lock:
            self._thread = None
            self._frame_pair_thread = None
            self._observer_thread = None
            self._evidence_thread = None
            self._clear_evidence_queue()

    def report(self, *, event_limit: int = 12) -> dict[str, object]:
        return self.diagnostics.report(event_limit=event_limit)

    def lock_only_confirmed_person(self) -> dict[str, object]:
        """Lock only when exactly one currently visible track has confirmed head evidence."""
        with self._runtime_lock:
            candidates = [
                track
                for track in self.runtime.latest_tracks
                if self.runtime.head_lock_eligible(track.track_id)
            ]
            if len(candidates) != 1:
                return {
                    "ok": False,
                    "reason": (
                        "lock requires exactly one head-confirmed visible person; "
                        f"found {len(candidates)}"
                    ),
                }
            track = candidates[0]
            self.runtime.lock(track.track_id)
        self.diagnostics.record_action(
            code="operator_lock_requested",
            message=f"Explicitly locked the only head-confirmed visible track {track.track_id}.",
        )
        return {"ok": True, "track_id": track.track_id, "armed": False}

    def arm_follow(self) -> dict[str, object]:
        with self._runtime_lock:
            self.runtime.arm_follow()
            target = self.runtime.target
            target_id = target.track_id if target is not None else None
        self.diagnostics.record_action(
            code="operator_arm_requested",
            message=f"Explicitly armed follow for target {target_id}.",
        )
        return {"ok": True, "target_id": target_id}

    def disarm_follow(self) -> dict[str, object]:
        with self._runtime_lock:
            self.runtime.disarm_follow()
            target = self.runtime.target
            target_id = target.track_id if target is not None else None
        self.diagnostics.record_action(
            code="operator_disarm_requested",
            message=f"Explicitly disarmed follow for target {target_id}.",
        )
        return {"ok": True, "target_id": target_id}

    def clear_target(self) -> dict[str, object]:
        with self._runtime_lock:
            target = self.runtime.target
            target_id = target.track_id if target is not None else None
            self.runtime.clear_target()
        self.diagnostics.record_action(
            code="operator_clear_requested",
            message=f"Explicitly cleared target {target_id} and disarmed follow.",
        )
        return {"ok": True, "cleared_target_id": target_id}

    def _run_loop(self) -> None:
        try:
            while not self._stop_requested.is_set():
                with self._runtime_lock:
                    snapshot = self.runtime.process_once(
                        timeout_seconds=self._process_timeout_seconds
                    )
                    frame = self.runtime.latest_frame if snapshot is not None else None
                if snapshot is not None:
                    with self._snapshot_lock:
                        self._latest_snapshot = snapshot
                    self.diagnostics.observe(snapshot)
                    exact_pair = (
                        frame is not None and frame.frame_id == snapshot.frame_id
                    )
                    if exact_pair and self._evidence_observer is not None:
                        self._publish_evidence_pair(frame, snapshot)
        except Exception as exc:
            self.diagnostics.record_error(exc)
            LOGGER.exception("Integrated vision service failed")
        finally:
            try:
                with self._runtime_lock:
                    self.runtime.close()
            except Exception as exc:
                self.diagnostics.record_error(exc)
                LOGGER.exception("Integrated vision shutdown failed")
            finally:
                self.diagnostics.set_running(False)
                self._stop_requested.set()

    def _publish_evidence_pair(
        self,
        frame: CapturedFrame,
        snapshot: VisionSnapshot,
    ) -> None:
        if self._evidence_queue.full():
            try:
                self._evidence_queue.get_nowait()
            except queue.Empty:
                pass
        try:
            self._evidence_queue.put_nowait((frame, snapshot))
        except queue.Full:
            pass

    def _clear_evidence_queue(self) -> None:
        while True:
            try:
                self._evidence_queue.get_nowait()
            except queue.Empty:
                return

    def _frame_pair_loop(self) -> None:
        assert self._frame_pair_tap is not None
        last_frame_id: int | None = None
        try:
            while not self._stop_requested.is_set():
                frame = self.runtime.latest_camera_frame(
                    after_frame_id=last_frame_id,
                    timeout_seconds=0.05,
                )
                if frame is None:
                    continue
                last_frame_id = frame.frame_id
                snapshot = self._fresh_snapshot_for_frame(frame)
                if snapshot is None:
                    continue
                try:
                    self._frame_pair_tap(frame, snapshot)
                except Exception:
                    LOGGER.exception(
                        "Integrated vision frame-pair tap failed; evidence dropped"
                    )
        except Exception as exc:
            if not self._stop_requested.is_set():
                self.diagnostics.record_error(exc)
                LOGGER.exception("Integrated vision frame-pair tap failed closed")

    def _fresh_snapshot_for_frame(
        self,
        frame: CapturedFrame,
    ) -> VisionSnapshot | None:
        with self._snapshot_lock:
            snapshot = self._latest_snapshot
        if snapshot is None:
            return None
        age = frame.captured_at - snapshot.captured_at
        if age < 0 or age > self._frame_pair_tap_max_snapshot_age_seconds:
            return None
        return snapshot

    def _observer_loop(self) -> None:
        assert self._observer is not None
        last_frame_id: int | None = None
        try:
            while not self._stop_requested.is_set():
                frame = self.runtime.latest_camera_frame(
                    after_frame_id=last_frame_id,
                    timeout_seconds=0.05,
                )
                if frame is None:
                    continue
                last_frame_id = frame.frame_id
                with self._snapshot_lock:
                    snapshot = self._latest_snapshot
                if snapshot is not None:
                    self._observer.observe(frame, snapshot)
        except Exception as exc:
            if not self._stop_requested.is_set():
                self.diagnostics.record_error(exc)
                LOGGER.exception("Integrated vision observer failed")
        finally:
            try:
                self._observer.close()
            except Exception as exc:
                self.diagnostics.record_error(exc)
                LOGGER.exception("Integrated vision observer shutdown failed")

    def _evidence_observer_loop(self) -> None:
        assert self._evidence_observer is not None
        try:
            while not self._stop_requested.is_set():
                try:
                    frame, snapshot = self._evidence_queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                self._evidence_observer.observe(frame, snapshot)
        except Exception as exc:
            if not self._stop_requested.is_set():
                self.diagnostics.record_error(exc)
                LOGGER.exception("Integrated vision evidence observer failed closed")
        finally:
            try:
                self._evidence_observer.close()
            except Exception as exc:
                self.diagnostics.record_error(exc)
                LOGGER.exception("Integrated vision evidence observer shutdown failed")


def resolve_blazeface_model_path(configured: str | Path | None = None) -> Path:
    if configured is not None:
        path = Path(configured)
    elif value := os.environ.get("JARVIS_BLAZEFACE_MODEL_PATH"):
        path = Path(value)
    elif local_app_data := os.environ.get("LOCALAPPDATA"):
        path = Path(local_app_data) / "JARVIS" / "models" / _HEAD_MODEL_NAME
    else:
        path = Path.home() / ".jarvis" / "models" / _HEAD_MODEL_NAME

    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def build_default_vision_service(
    *,
    head_model_path: str | Path | None = None,
    evidence_observer: VisionObserver | None = None,
    frame_pair_tap: FramePairTap | None = None,
) -> VisionService:
    """Compose the benchmark-selected Step 2.5 hardware/runtime stack lazily."""
    from jarvis.vision.camera import OpenCVCameraSource
    from jarvis.vision.detector import RFDetrNanoDetector
    from jarvis.vision.follow import (
        FollowConfig,
        FollowController,
        ZoomConfig,
        ZoomController,
    )
    from jarvis.vision.head_mediapipe import (
        MediaPipeBlazeFaceConfig,
        MediaPipeBlazeFaceDetector,
    )
    from jarvis.vision.observer import OpenCVVisionObserver
    from jarvis.vision.ptz import DuvcPtzConfig, DuvcPtzController
    from jarvis.vision.runtime import VisionRuntimeConfig
    from jarvis.vision.targeting import TargetManager
    from jarvis.vision.tracker import OCSORTAdapter, OCSORTConfig

    model_path = resolve_blazeface_model_path(head_model_path)
    runtime = VisionRuntime(
        camera=OpenCVCameraSource(),
        detector=RFDetrNanoDetector(),
        tracker=OCSORTAdapter(
            OCSORTConfig(
                lost_track_buffer=60,
                minimum_consecutive_frames=2,
                minimum_iou_threshold=-0.30,
                direction_consistency_weight=0.20,
                high_conf_det_threshold=0.40,
                delta_t=2,
            )
        ),
        target_manager=TargetManager(lost_timeout_seconds=1.25),
        follow_controller=FollowController(
            FollowConfig(
                horizontal_dead_zone=0.08,
                vertical_dead_zone=0.08,
                gain=2.2,
                max_command=0.65,
                minimum_confidence=0.5,
                desired_x=0.50,
                desired_y=0.40,
            )
        ),
        zoom_controller=ZoomController(
            ZoomConfig(
                desired_body_height=0.56,
                dead_zone=0.08,
                gain=1.4,
                max_command=0.30,
                minimum_confidence=0.5,
            )
        ),
        ptz=DuvcPtzController(
            DuvcPtzConfig(
                pan_step_fraction=0.025,
                tilt_step_fraction=0.025,
                zoom_step_fraction=0.025,
                zoom_max_fraction=0.50,
                pan_negative_scale=1.25,
                pan_positive_scale=1.75,
            )
        ),
        head_detector=MediaPipeBlazeFaceDetector(
            MediaPipeBlazeFaceConfig(model_path=model_path)
        ),
        config=VisionRuntimeConfig(
            minimum_ptz_interval_seconds=0.05,
            minimum_zoom_interval_seconds=0.15,
            require_head_for_lock=True,
            required_head_confirmation_frames=3,
            body_fallback_tilt_scale=0.45,
        ),
    )
    observer = (
        OpenCVVisionObserver()
        if os.environ.get("JARVIS_VISION_PREVIEW", "").strip().lower()
        in {"1", "true", "yes", "on"}
        else None
    )
    return VisionService(
        runtime,
        observer=observer,
        evidence_observer=evidence_observer,
        frame_pair_tap=frame_pair_tap,
    )
