"""Background ownership boundary for integrated JARVIS vision."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from threading import Event, RLock, Thread

from jarvis.vision.diagnostics import VisionDiagnostics
from jarvis.vision.runtime import VisionRuntime

LOGGER = logging.getLogger(__name__)

_HEAD_MODEL_NAME = "blaze_face_full_range.tflite"


class VisionService:
    """Run one VisionRuntime continuously and expose thread-safe test controls."""

    def __init__(
        self,
        runtime: VisionRuntime,
        *,
        diagnostics: VisionDiagnostics | None = None,
        process_timeout_seconds: float = 0.20,
    ) -> None:
        if process_timeout_seconds <= 0:
            raise ValueError("process_timeout_seconds must be positive")
        self.runtime = runtime
        self.diagnostics = diagnostics or VisionDiagnostics()
        self._process_timeout_seconds = process_timeout_seconds
        self._runtime_lock = RLock()
        self._lifecycle_lock = RLock()
        self._stop_requested = Event()
        self._thread: Thread | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    def start(self) -> None:
        with self._lifecycle_lock:
            if self.running:
                return
            self._stop_requested.clear()
            with self._runtime_lock:
                self.runtime.start()
            self.diagnostics.set_running(True)
            self._thread = Thread(
                target=self._run_loop,
                name="jarvis-vision",
                daemon=True,
            )
            self._thread.start()

    def stop(self, *, join_timeout_seconds: float = 3.0) -> None:
        if join_timeout_seconds <= 0:
            raise ValueError("join_timeout_seconds must be positive")
        with self._lifecycle_lock:
            thread = self._thread
            if thread is None:
                return
            self._stop_requested.set()
        thread.join(timeout=join_timeout_seconds)
        if thread.is_alive():
            raise RuntimeError("vision service did not stop within the shutdown timeout")
        with self._lifecycle_lock:
            self._thread = None

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
                if snapshot is not None:
                    self.diagnostics.observe(snapshot)
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
) -> VisionService:
    """Compose the benchmark-selected Step 2.5 hardware/runtime stack lazily."""
    from jarvis.vision.camera import OpenCVCameraSource
    from jarvis.vision.detector import RFDetrNanoDetector
    from jarvis.vision.follow import FollowConfig, FollowController
    from jarvis.vision.head_mediapipe import (
        MediaPipeBlazeFaceConfig,
        MediaPipeBlazeFaceDetector,
    )
    from jarvis.vision.ptz import DuvcPtzConfig, DuvcPtzController
    from jarvis.vision.runtime import VisionRuntimeConfig
    from jarvis.vision.targeting import TargetManager
    from jarvis.vision.tracker import ByteTrackAdapter

    model_path = resolve_blazeface_model_path(head_model_path)
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
        ptz=DuvcPtzController(
            DuvcPtzConfig(
                pan_step_fraction=0.02,
                tilt_step_fraction=0.02,
            )
        ),
        head_detector=MediaPipeBlazeFaceDetector(
            MediaPipeBlazeFaceConfig(model_path=model_path)
        ),
        config=VisionRuntimeConfig(
            minimum_ptz_interval_seconds=0.20,
            require_head_for_lock=True,
            required_head_confirmation_frames=3,
        ),
    )
    return VisionService(runtime)
