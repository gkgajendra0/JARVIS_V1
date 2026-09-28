"""Camera capture boundary for JARVIS vision."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np

CaptureFactory = Callable[[int, int, list[int]], object]


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    frame_id: int
    captured_at: float
    image: np.ndarray

    def __post_init__(self) -> None:
        if self.frame_id < 0:
            raise ValueError("frame_id must be non-negative")
        if self.captured_at < 0:
            raise ValueError("captured_at must be non-negative")
        if self.image.ndim < 2:
            raise ValueError("captured frame image must have at least two dimensions")

    @property
    def width(self) -> int:
        return int(self.image.shape[1])

    @property
    def height(self) -> int:
        return int(self.image.shape[0])


class CameraSource(Protocol):
    def start(self) -> None: ...

    def latest(
        self,
        *,
        after_frame_id: int | None = None,
        timeout_seconds: float | None = None,
    ) -> CapturedFrame | None: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class OpenCVCameraConfig:
    """OpenCV capture profile.

    The production defaults match the owner-machine accepted Lenovo 510 RGB path:
    DirectShow + MJPEG + 1920x1080 @ 30 FPS. Passing these values at open time is
    intentional; the Lenovo driver can otherwise negotiate YUY2 and collapse to
    single-digit FPS at 1080p.
    """

    device_index: int = 0
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    fourcc: str = "MJPG"
    backend: str = "dshow"

    def __post_init__(self) -> None:
        backend = self.backend.strip().lower()
        fourcc = self.fourcc.strip().upper()
        if self.device_index < 0:
            raise ValueError("device_index must be non-negative")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("camera dimensions must be positive")
        if self.fps <= 0:
            raise ValueError("camera fps must be positive")
        if len(fourcc) != 4:
            raise ValueError("camera fourcc must contain exactly four characters")
        if backend not in {"dshow", "msmf"}:
            raise ValueError(f"unsupported camera backend: {self.backend!r}")
        object.__setattr__(self, "backend", backend)
        object.__setattr__(self, "fourcc", fourcc)


def _decode_fourcc(value: float) -> str:
    encoded = int(value)
    return "".join(chr((encoded >> (8 * offset)) & 0xFF) for offset in range(4))


class OpenCVCameraSource:
    """Capture continuously into a single overwrite slot.

    Frame IDs remain monotonic across an explicit camera switch so downstream
    consumers never confuse a new device's first frame with an old frame.
    """

    def __init__(
        self,
        config: OpenCVCameraConfig | None = None,
        *,
        capture_factory: CaptureFactory = cv2.VideoCapture,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or OpenCVCameraConfig()
        self._capture_factory = capture_factory
        self._clock = clock
        self._condition = threading.Condition()
        self._lifecycle_lock = threading.RLock()
        self._stop = threading.Event()
        self._capture: object | None = None
        self._thread: threading.Thread | None = None
        self._latest: CapturedFrame | None = None
        self._next_frame_id = 0
        self._read_error: RuntimeError | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._capture is not None:
                raise RuntimeError("camera source is already started")
            self._activate(self.config)

    def switch(self, config: OpenCVCameraConfig) -> None:
        """Switch to another OpenCV camera profile with rollback on open failure."""
        with self._lifecycle_lock:
            if config == self.config:
                return
            if self._capture is None:
                self.config = config
                return

            previous = self.config
            self._deactivate()

            try:
                self._activate(config)
            except Exception as switch_error:
                try:
                    self._activate(previous)
                except Exception as rollback_error:
                    raise RuntimeError(
                        "camera switch failed and previous camera could not be restored"
                    ) from rollback_error
                raise RuntimeError(
                    f"camera switch to device index {config.device_index} failed; "
                    "previous camera restored"
                ) from switch_error

    def latest(
        self,
        *,
        after_frame_id: int | None = None,
        timeout_seconds: float | None = None,
    ) -> CapturedFrame | None:
        if timeout_seconds is not None and timeout_seconds < 0:
            raise ValueError("timeout_seconds must be non-negative")

        def ready() -> bool:
            frame = self._latest
            return (
                self._read_error is not None
                or self._stop.is_set()
                or (
                    frame is not None
                    and (after_frame_id is None or frame.frame_id > after_frame_id)
                )
            )

        with self._condition:
            if not ready():
                self._condition.wait_for(ready, timeout=timeout_seconds)
            if self._read_error is not None:
                raise self._read_error
            frame = self._latest
            if frame is None:
                return None
            if after_frame_id is not None and frame.frame_id <= after_frame_id:
                return None
            return frame

    def close(self) -> None:
        with self._lifecycle_lock:
            self._deactivate()

    def _activate(self, config: OpenCVCameraConfig) -> None:
        backend = cv2.CAP_DSHOW if config.backend == "dshow" else cv2.CAP_MSMF
        params = [
            cv2.CAP_PROP_FOURCC,
            cv2.VideoWriter_fourcc(*config.fourcc),
            cv2.CAP_PROP_FRAME_WIDTH,
            int(config.width),
            cv2.CAP_PROP_FRAME_HEIGHT,
            int(config.height),
            cv2.CAP_PROP_FPS,
            int(config.fps),
        ]
        capture = self._capture_factory(config.device_index, backend, params)
        if not capture.isOpened():
            capture.release()
            raise RuntimeError("camera failed to open")

        get_property = getattr(capture, "get", None)
        if callable(get_property):
            negotiated_width = int(get_property(cv2.CAP_PROP_FRAME_WIDTH))
            negotiated_height = int(get_property(cv2.CAP_PROP_FRAME_HEIGHT))
            negotiated_fourcc = _decode_fourcc(get_property(cv2.CAP_PROP_FOURCC))
            if (
                negotiated_width != config.width
                or negotiated_height != config.height
                or negotiated_fourcc != config.fourcc
            ):
                capture.release()
                raise RuntimeError(
                    "camera capture negotiation mismatch: "
                    f"requested={config.width}x{config.height}/{config.fourcc}, "
                    f"negotiated={negotiated_width}x{negotiated_height}/"
                    f"{negotiated_fourcc!r}"
                )

        ok, image = capture.read()
        if not ok or image is None:
            capture.release()
            raise RuntimeError("camera opened but did not provide a frame")

        self._stop.clear()
        self._read_error = None
        self.config = config
        self._capture = capture
        self._publish(image)
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="jarvis-vision-camera",
            daemon=True,
        )
        self._thread.start()

    def _deactivate(self) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()

        capture = self._capture
        if capture is not None:
            capture.release()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
            if thread.is_alive():
                raise RuntimeError("camera capture thread did not stop")

        self._thread = None
        self._capture = None

    def _capture_loop(self) -> None:
        capture = self._capture
        if capture is None:
            return

        while not self._stop.is_set():
            ok, image = capture.read()
            if not ok or image is None:
                if self._stop.is_set():
                    return
                with self._condition:
                    self._read_error = RuntimeError("camera frame capture failed")
                    self._condition.notify_all()
                return
            self._publish(image)

    def _publish(self, image: np.ndarray) -> None:
        frame = CapturedFrame(
            frame_id=self._next_frame_id,
            captured_at=self._clock(),
            image=image,
        )
        self._next_frame_id += 1
        with self._condition:
            self._latest = frame
            self._condition.notify_all()
