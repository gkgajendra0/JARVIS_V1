"""Interactive armed-follow diagnostic for the Step 2.5 vision stack."""

from __future__ import annotations

import cv2

from jarvis.vision.camera import OpenCVCameraSource
from jarvis.vision.detector import RFDetrNanoDetector
from jarvis.vision.follow import FollowConfig, FollowController
from jarvis.vision.models import Track
from jarvis.vision.ptz import DuvcPtzConfig, DuvcPtzController
from jarvis.vision.runtime import VisionRuntime, VisionRuntimeConfig
from jarvis.vision.targeting import TargetManager
from jarvis.vision.tracker import ByteTrackAdapter

_WINDOW_NAME = "JARVIS Vision Follow"


class _SelectionState:
    def __init__(self) -> None:
        self.clicked_track_id: int | None = None
        self.tracks: tuple[Track, ...] = ()
        self.frame_width = 0
        self.frame_height = 0

    def update(self, tracks: tuple[Track, ...], *, width: int, height: int) -> None:
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
            key=lambda track: (
                (track.bounds.right - track.bounds.left)
                * (track.bounds.bottom - track.bounds.top)
            ),
        ).track_id


def _draw(image, snapshot, runtime: VisionRuntime):
    height, width = image.shape[:2]
    preview = image.copy()
    target_id = runtime.target.track_id if runtime.target is not None else None

    for track in snapshot.tracks:
        left = int(track.bounds.left * width)
        top = int(track.bounds.top * height)
        right = int(track.bounds.right * width)
        bottom = int(track.bounds.bottom * height)
        selected = track.track_id == target_id
        color = (0, 165, 255) if selected else (0, 255, 0)
        thickness = 3 if selected else 2
        cv2.rectangle(preview, (left, top), (right, bottom), color, thickness)
        suffix = " LOCKED" if selected else ""
        label = f"ID {track.track_id} person {track.confidence:.2f}{suffix}"
        cv2.putText(
            preview,
            label,
            (left, max(20, top - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            color,
            2,
            cv2.LINE_AA,
        )

    state = "ARMED" if runtime.armed else "SAFE"
    target_text = "none" if target_id is None else str(target_id)
    status = (
        f"{state} | target: {target_text} | click: lock | A: arm | "
        "SPACE: disarm | C: clear | Q: quit"
    )
    cv2.putText(
        preview,
        status,
        (14, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (0, 0, 255) if runtime.armed else (0, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return preview


def main() -> int:
    camera = OpenCVCameraSource()
    detector = RFDetrNanoDetector()
    tracker = ByteTrackAdapter()
    ptz = DuvcPtzController(
        DuvcPtzConfig(
            pan_step_fraction=0.02,
            tilt_step_fraction=0.02,
        )
    )
    runtime = VisionRuntime(
        camera=camera,
        detector=detector,
        tracker=tracker,
        target_manager=TargetManager(lost_timeout_seconds=0.5),
        follow_controller=FollowController(
            FollowConfig(
                horizontal_dead_zone=0.14,
                vertical_dead_zone=0.14,
                gain=1.0,
                max_command=0.20,
                minimum_confidence=0.5,
            )
        ),
        ptz=ptz,
        config=VisionRuntimeConfig(minimum_ptz_interval_seconds=0.20),
    )
    selection = _SelectionState()

    print("JARVIS armed vision follow")
    print(
        "Starts SAFE: the camera will not move until a target is locked and follow is armed."
    )
    print("Click a visible person to lock them, press A to arm follow.")
    print("Press SPACE to disarm immediately, C to clear target, Q/Esc to quit.")

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
                    print(
                        f"Locked track {selection.clicked_track_id}; follow remains SAFE."
                    )
                except ValueError as exc:
                    print(exc)
                finally:
                    selection.clicked_track_id = None

            cv2.imshow(_WINDOW_NAME, _draw(frame.image, snapshot, runtime))
            key = cv2.waitKey(1) & 0xFF

            if key in (ord("q"), ord("Q"), 27):
                break
            if key == ord(" "):
                runtime.disarm_follow()
                print("Follow DISARMED.")
            elif key in (ord("c"), ord("C")):
                runtime.clear_target()
                print("Target cleared; follow DISARMED.")
            elif key in (ord("a"), ord("A")):
                try:
                    runtime.arm_follow()
                    print("Follow ARMED for the locked track.")
                except RuntimeError as exc:
                    print(exc)
    finally:
        runtime.close()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
