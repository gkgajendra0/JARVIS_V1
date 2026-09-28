"""Camera capture boundaries for JARVIS vision."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

import cv2
import numpy as np

CaptureFactory = Callable[..., object]


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
    device_index: int = 0
    width: int = 1280
    height: int = 720
    backend: str = "dshow"
    fps: float | None = None
    codec: str | None = None

    def __post_init__(self) -> None:
        backend = self.backend.strip().lower()
        if self.device_index < 0:
            raise ValueError("device_index must be non-negative")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("camera dimensions must be positive")
        if backend not in {"dshow", "msmf"}:
            raise ValueError(f"unsupported camera backend: {self.backend!r}")
        object.__setattr__(self, "backend", backend)

        if self.fps is not None and self.fps <= 0:
            raise ValueError("camera fps must be positive when configured")

        if self.codec is not None:
            codec = self.codec.strip().upper()
            if len(codec) != 4:
                raise ValueError("camera codec must be a four-character code")
            object.__setattr__(self, "codec", codec)


class OpenCVCameraSource:
    """Capture continuously into a single overwrite slot.

    Camera formats that specify FPS and/or codec are negotiated when VideoCapture
    opens. This matters on Windows DirectShow: setting MJPG after opening can leave
    the device in an uncompressed YUY2 mode with dramatically lower throughput.
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
        if self._capture is not None:
            raise RuntimeError("camera source is already started")

        backend = cv2.CAP_DSHOW if self.config.backend == "dshow" else cv2.CAP_MSMF
        capture = self._open_capture(backend)
        if not capture.isOpened():
            capture.release()
            raise RuntimeError("camera failed to open")

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
        with self._condition:
            self._latest = None
            self._condition.notify_all()

    def _open_capture(self, backend: int):
        codec = self.config.codec
        fps = self.config.fps

        if codec is not None or fps is not None:
            params: list[int | float] = [
                cv2.CAP_PROP_FRAME_WIDTH,
                self.config.width,
                cv2.CAP_PROP_FRAME_HEIGHT,
                self.config.height,
            ]
            if codec is not None:
                params.extend(
                    [
                        cv2.CAP_PROP_FOURCC,
                        cv2.VideoWriter_fourcc(*codec),
                    ]
                )
            if fps is not None:
                params.extend([cv2.CAP_PROP_FPS, fps])

            try:
                return self._capture_factory(
                    self.config.device_index,
                    backend,
                    params,
                )
            except TypeError:
                # Test doubles and older wrappers may expose only the classic
                # two-argument constructor. Preserve testability while keeping
                # production OpenCV on the open-time negotiation path.
                capture = self._capture_factory(self.config.device_index, backend)
                for key, value in zip(params[::2], params[1::2], strict=True):
                    capture.set(key, value)
                return capture

        capture = self._capture_factory(self.config.device_index, backend)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        return capture

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
            captured_at=self._clock(),
            image=image,
        )
        self._next_frame_id += 1
        with self._condition:
            self._latest = frame
            self._condition.notify_all()


class SwitchableCameraSource:
    """Expose named cameras through one monotonic latest-frame stream.

    Only the active physical source is kept open. Frames are re-numbered at this
    boundary so consumers can switch between cameras without seeing frame IDs move
    backwards when the newly activated camera starts from its own local frame zero.
    """

    def __init__(
        self,
        sources: Mapping[str, CameraSource],
        *,
        default_source: str,
    ) -> None:
        normalized_sources = {
            self._normalize_name(name): source for name, source in sources.items()
        }
        if not normalized_sources:
            raise ValueError("at least one camera source is required")

        normalized_default = self._normalize_name(default_source)
        if normalized_default not in normalized_sources:
            raise ValueError(
                f"unknown default camera source: {default_source!r}; "
                f"available={sorted(normalized_sources)}"
            )

        self._sources = normalized_sources
        self._active_source_name = normalized_default
        self._switch_lock = threading.RLock()
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest: CapturedFrame | None = None
        self._next_frame_id = 0
        self._generation = 0
        self._started = False
        self._read_error: RuntimeError | None = None

    @property
    def active_source_name(self) -> str:
        with self._switch_lock:
            return self._active_source_name

    @property
    def available_sources(self) -> tuple[str, ...]:
        return tuple(self._sources)

    @property
    def running(self) -> bool:
        thread = self._thread
        return self._started and thread is not None and thread.is_alive()

    def start(self) -> None:
        with self._switch_lock:
            if self._started:
                raise RuntimeError("switchable camera source is already started")
            active = self._sources[self._active_source_name]
            active.start()
            self._started = True
            self._generation += 1
            self._stop.clear()
            self._read_error = None
            with self._condition:
                self._latest = None
                self._condition.notify_all()
            self._thread = threading.Thread(
                target=self._capture_loop,
                name="jarvis-vision-camera-router",
                daemon=True,
            )
            self._thread.start()

    def switch(self, source_name: str) -> str:
        normalized = self._normalize_name(source_name)
        if normalized not in self._sources:
            raise ValueError(
                f"unknown camera source: {source_name!r}; "
                f"available={list(self.available_sources)}"
            )

        with self._switch_lock:
            previous = self._active_source_name
            if normalized == previous:
                return previous

            if not self._started:
                self._active_source_name = normalized
                self._generation += 1
                with self._condition:
                    self._latest = None
                    self._condition.notify_all()
                return normalized

            previous_source = self._sources[previous]
            next_source = self._sources[normalized]
            self._generation += 1
            with self._condition:
                self._latest = None
                self._condition.notify_all()

            previous_source.close()
            try:
                next_source.start()
            except Exception as exc:
                try:
                    previous_source.start()
                except Exception as rollback_exc:
                    self._read_error = RuntimeError(
                        "camera switch failed and previous camera could not be restored"
                    )
                    with self._condition:
                        self._condition.notify_all()
                    raise self._read_error from rollback_exc

                self._generation += 1
                raise RuntimeError(
                    f"camera switch to {normalized!r} failed; restored {previous!r}"
                ) from exc

            self._active_source_name = normalized
            self._generation += 1
            self._read_error = None
            return normalized

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

        with self._switch_lock:
            if self._started:
                self._sources[self._active_source_name].close()
            self._started = False
            self._thread = None
            self._generation += 1

        with self._condition:
            self._latest = None
            self._condition.notify_all()

    def _capture_loop(self) -> None:
        source_frame_id: int | None = None
        observed_generation = -1

        while not self._stop.is_set():
            with self._switch_lock:
                source_name = self._active_source_name
                source = self._sources[source_name]
                generation = self._generation

            if generation != observed_generation:
                source_frame_id = None
                observed_generation = generation

            try:
                frame = source.latest(
                    after_frame_id=source_frame_id,
                    timeout_seconds=0.05,
                )
            except RuntimeError as exc:
                with self._switch_lock:
                    still_current = (
                        generation == self._generation
                        and source_name == self._active_source_name
                    )
                if still_current and not self._stop.is_set():
                    with self._condition:
                        self._read_error = RuntimeError(
                            f"active camera {source_name!r} failed: {exc}"
                        )
                        self._condition.notify_all()
                    return
                continue

            if frame is None:
                continue

            with self._switch_lock:
                if (
                    generation != self._generation
                    or source_name != self._active_source_name
                ):
                    continue

            source_frame_id = frame.frame_id
            routed = CapturedFrame(
                frame_id=self._next_frame_id,
                captured_at=frame.captured_at,
                image=frame.image,
            )
            self._next_frame_id += 1
            with self._condition:
                self._latest = routed
                self._read_error = None
                self._condition.notify_all()

    @staticmethod
    def _normalize_name(value: str) -> str:
        normalized = str(value).strip().lower()
        if not normalized:
            raise ValueError("camera source name must not be empty")
        return normalized
