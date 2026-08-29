"""Live no-PTZ diagnostic preview for the Step 2.5 vision stack."""

from __future__ import annotations

import cv2

from jarvis.vision.camera import OpenCVCameraSource
from jarvis.vision.detector import RFDetrNanoDetector
from jarvis.vision.models import Track
from jarvis.vision.tracker import ByteTrackAdapter

_WINDOW_NAME = "JARVIS Vision Preview - Q to quit"


def _draw_tracks(image, tracks: list[Track]):
    height, width = image.shape[:2]
    preview = image.copy()

    for track in tracks:
        left = int(track.bounds.left * width)
        top = int(track.bounds.top * height)
        right = int(track.bounds.right * width)
        bottom = int(track.bounds.bottom * height)

        cv2.rectangle(preview, (left, top), (right, bottom), (0, 255, 0), 2)
        label = f"ID {track.track_id}  person {track.confidence:.2f}"
        text_y = max(20, top - 8)
        cv2.putText(
            preview,
            label,
            (left, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )

    status = f"tracks: {len(tracks)} | PTZ: DISABLED | Q: quit"
    cv2.putText(
        preview,
        status,
        (16, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )
    return preview


def main() -> int:
    camera = OpenCVCameraSource()
    detector = RFDetrNanoDetector()
    tracker = ByteTrackAdapter()
    last_frame_id: int | None = None

    print("JARVIS live vision preview")
    print("PTZ movement is disabled in this command.")
    print("Press Q in the preview window to quit.")

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
            detections = detector.detect(frame)
            tracks = tracker.update(detections, now=frame.captured_at)

            preview = _draw_tracks(frame.image, tracks)
            cv2.imshow(_WINDOW_NAME, preview)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q"), 27):
                break
    finally:
        camera.close()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
