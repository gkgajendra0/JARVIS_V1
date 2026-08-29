"""Live observer window for the exact integrated JARVIS vision state."""

from __future__ import annotations

from typing import Protocol

import cv2
import numpy as np

from jarvis.vision.camera import CapturedFrame
from jarvis.vision.runtime import VisionSnapshot


class VisionObserver(Protocol):
    def observe(self, frame: CapturedFrame, snapshot: VisionSnapshot) -> None: ...

    def close(self) -> None: ...


class OpenCVVisionObserver:
    """Render smooth camera frames with the latest canonical JARVIS interpretation."""

    def __init__(
        self,
        *,
        window_name: str = "JARVIS Vision - live interpretation",
        window_width: int = 640,
        window_height: int = 360,
    ) -> None:
        if window_width <= 0 or window_height <= 0:
            raise ValueError("observer window dimensions must be positive")
        self._window_name = window_name
        self._window_width = window_width
        self._window_height = window_height
        self._window_created = False

    def observe(self, frame: CapturedFrame, snapshot: VisionSnapshot) -> None:
        if not self._window_created:
            cv2.namedWindow(self._window_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(
                self._window_name,
                self._window_width,
                self._window_height,
            )
            self._window_created = True

        preview = render_snapshot(
            frame.image,
            snapshot,
            display_captured_at=frame.captured_at,
        )
        cv2.imshow(self._window_name, preview)
        cv2.waitKey(1)

    def close(self) -> None:
        if not self._window_created:
            return
        try:
            cv2.destroyWindow(self._window_name)
        except cv2.error:
            pass
        finally:
            self._window_created = False


def render_snapshot(
    image: np.ndarray,
    snapshot: VisionSnapshot,
    *,
    display_captured_at: float | None = None,
) -> np.ndarray:
    """Draw the latest canonical interpretation onto a camera frame."""
    preview = image.copy()
    height, width = preview.shape[:2]
    target_id = snapshot.target.track_id if snapshot.target is not None else None

    for track in snapshot.tracks:
        left = int(track.bounds.left * width)
        top = int(track.bounds.top * height)
        right = int(track.bounds.right * width)
        bottom = int(track.bounds.bottom * height)
        is_target = track.track_id == target_id
        color = (0, 255, 255) if is_target else (0, 255, 0)
        thickness = 3 if is_target else 2
        cv2.rectangle(preview, (left, top), (right, bottom), color, thickness)
        label = f"TRACK {track.track_id}  {track.confidence:.2f}"
        if is_target:
            label += "  LOCKED"
        cv2.putText(
            preview,
            label,
            (left, max(22, top - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
            cv2.LINE_AA,
        )

    for index, head in enumerate(snapshot.heads):
        left = int(head.bounds.left * width)
        top = int(head.bounds.top * height)
        right = int(head.bounds.right * width)
        bottom = int(head.bounds.bottom * height)
        cv2.rectangle(preview, (left, top), (right, bottom), (255, 180, 0), 2)
        cv2.putText(
            preview,
            f"HEAD {index + 1}  {head.confidence:.2f}",
            (left, max(22, top - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 180, 0),
            2,
            cv2.LINE_AA,
        )

    framing = snapshot.framing_target
    if framing is not None:
        x = int(framing.x * width)
        y = int(framing.y * height)
        cv2.drawMarker(
            preview,
            (x, y),
            (255, 0, 255),
            markerType=cv2.MARKER_CROSS,
            markerSize=24,
            thickness=2,
        )
        cv2.putText(
            preview,
            framing.source.upper(),
            (min(width - 120, x + 8), max(22, y - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 0, 255),
            2,
            cv2.LINE_AA,
        )

    target_text = "none"
    if snapshot.target is not None:
        visibility = "visible" if snapshot.target.visible else "missing"
        target_text = f"{snapshot.target.track_id} ({visibility})"

    analysis_age_ms = 0
    if display_captured_at is not None:
        analysis_age_ms = max(
            0,
            int((display_captured_at - snapshot.captured_at) * 1000),
        )

    lines = [
        (
            f"BoT-SORT tracks: {len(snapshot.tracks)} | heads: {len(snapshot.heads)} "
            f"| analysis age: {analysis_age_ms} ms"
        ),
        f"target: {target_text} | follow: {'ARMED' if snapshot.armed else 'SAFE'}",
        (
            "framing: "
            f"{framing.source if framing is not None else 'none'} | "
            f"pan {snapshot.command.pan:+.2f}  tilt {snapshot.command.tilt:+.2f}  "
            f"zoom {snapshot.command.zoom:+.2f}"
        ),
    ]
    for index, line in enumerate(lines):
        y = 28 + index * 26
        cv2.putText(
            preview,
            line,
            (14, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )

    return preview
