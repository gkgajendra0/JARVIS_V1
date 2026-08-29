"""Camera capture boundary for JARVIS vision."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    frame_id: int
    captured_at: float
    image: np.ndarray

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
    device_index: int = 0
    width: int = 1280
    height: int = 720
    backend: str = "dshow"

    def __post_init__(self) -> None:
        backend = self.backend.strip().lower()
        if self.device_index < 0:
            raise ValueError("device_index must be non-negative")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("camera dimensions must be positive")
        if backend not in {"dshow", "msmf"}:
            raise ValueError(f"unsupported camera backend: {self.backend!r}")
        object.__setattr__(self, "backend", backend)


class OpenCVCameraSource:
    """Capture continuously into a single overwrite slot."""

    def __init__(self, config: OpenCVCameraConfig | None = None) -> None:
        self.config = config or OpenCVCameraConfig()
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._capture: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._latest: CapturedFrame | None = None
        self._next_frame_id = 0
        self._read_error: RuntimeError | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        if self._capture is not None:
            raise RuntimeError("camera source is already started")

        backend = cv2.CAP_DSHOW if self.config.backend == "dshow" else cv2.CAP_MSMF
        capture = cv2.VideoCapture(self.config.device_index, backend)
        if not capture.isOpened():
            capture.release()
            raise RuntimeError("camera failed to open")

        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        ok, image = capture.read()
        if not ok or image is None:
            capture.release()
            raise RuntimeError("camera opened but did not provide a frame")

        self._stop.clear()
        self._read_error = None
        self._capture = capture
        self._publish(image)
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="jarvis-vision-camera",
            daemon=True,
        )
        self._thread.start()

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
        self._stop.set()
        with self._condition:
            self._condition.notify_all()

        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)

        capture = self._capture
        if capture is not None:
            capture.release()

        self._thread = None
        self._capture = None

    def _capture_loop(self) -> None:
        capture = self._capture
        if capture is None:
            return

        while not self._stop.is_set():
            ok, image = capture.read()
            if not ok or image is None:
                with self._condition:
                    self._read_error = RuntimeError("camera frame capture failed")
                    self._condition.notify_all()
                return
            self._publish(image)

    def _publish(self, image: np.ndarray) -> None:
        frame = CapturedFrame(
            frame_id=self._next_frame_id,
            captured_at=time.monotonic(),
            image=image,
        )
        self._next_frame_id += 1
        with self._condition:
            self._latest = frame
            self._condition.notify_all()
