import time

import cv2
import numpy as np
import pytest

from jarvis.vision.camera import (
    CapturedFrame,
    OpenCVCameraConfig,
    OpenCVCameraSource,
    SwitchableCameraSource,
)


class FakeCapture:
    def __init__(self, opened: bool = True, *, fail_first_read: bool = False) -> None:
        self.opened = opened
        self.fail_first_read = fail_first_read
        self.released = False
        self.read_count = 0
        self.settings: dict[int, float] = {}

    def isOpened(self) -> bool:
        return self.opened

    def set(self, key: int, value: float) -> bool:
        self.settings[key] = value
        return True

    def read(self):
        self.read_count += 1
        if self.fail_first_read and self.read_count == 1:
            return False, None
        time.sleep(0.005)
        value = self.read_count % 255
        return True, np.full((4, 6, 3), value, dtype=np.uint8)

    def release(self) -> None:
        self.released = True


def test_config_defaults_to_benchmarked_dshow_720p() -> None:
    config = OpenCVCameraConfig()

    assert config.backend == "dshow"
    assert config.width == 1280
    assert config.height == 720


def test_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        OpenCVCameraConfig(device_index=-1)
    with pytest.raises(ValueError):
        OpenCVCameraConfig(width=0)
    with pytest.raises(ValueError):
        OpenCVCameraConfig(backend="unknown")
    with pytest.raises(ValueError):
        OpenCVCameraConfig(fps=0)
    with pytest.raises(ValueError):
        OpenCVCameraConfig(codec="MJ")


def test_camera_uses_requested_backend_and_latest_frame() -> None:
    created: list[tuple[int, int]] = []
    fake = FakeCapture()

    def factory(index: int, backend: int):
        created.append((index, backend))
        return fake

    source = OpenCVCameraSource(capture_factory=factory)
    source.start()
    first = source.latest()
    assert first is not None

    newer = source.latest(after_frame_id=first.frame_id, timeout_seconds=0.2)
    source.close()

    assert created == [(0, cv2.CAP_DSHOW)]
    assert newer is not None
    assert newer.frame_id > first.frame_id
    assert newer.width == 6
    assert newer.height == 4
    assert fake.released


def test_camera_open_failure_releases_handle() -> None:
    fake = FakeCapture(opened=False)
    source = OpenCVCameraSource(capture_factory=lambda index, backend: fake)

    with pytest.raises(RuntimeError, match="failed to open"):
        source.start()

    assert fake.released


def test_camera_initial_read_failure_releases_handle() -> None:
    fake = FakeCapture(fail_first_read=True)
    source = OpenCVCameraSource(capture_factory=lambda index, backend: fake)

    with pytest.raises(RuntimeError, match="did not provide a frame"):
        source.start()

    assert fake.released


def test_camera_negotiates_mjpg_1080p_30_when_opening() -> None:
    fake = FakeCapture()
    created: list[tuple[int, int, list[int | float]]] = []

    def factory(index: int, backend: int, params: list[int | float]):
        created.append((index, backend, list(params)))
        return fake

    source = OpenCVCameraSource(
        OpenCVCameraConfig(
            device_index=0,
            width=1920,
            height=1080,
            backend="dshow",
            fps=30.0,
            codec="MJPG",
        ),
        capture_factory=factory,
    )

    source.start()
    source.close()

    assert len(created) == 1
    index, backend, params = created[0]
    assert index == 0
    assert backend == cv2.CAP_DSHOW
    configured = dict(zip(params[::2], params[1::2], strict=True))
    assert configured[cv2.CAP_PROP_FRAME_WIDTH] == 1920
    assert configured[cv2.CAP_PROP_FRAME_HEIGHT] == 1080
    assert configured[cv2.CAP_PROP_FPS] == 30.0
    assert configured[cv2.CAP_PROP_FOURCC] == cv2.VideoWriter_fourcc(*"MJPG")


class _FakeCameraSource:
    def __init__(self, value: int) -> None:
        self.value = value
        self.started = False
        self.frame_id = 0

    def start(self) -> None:
        if self.started:
            raise RuntimeError("already started")
        self.started = True

    def latest(
        self,
        *,
        after_frame_id: int | None = None,
        timeout_seconds: float | None = None,
    ) -> CapturedFrame | None:
        del timeout_seconds
        if not self.started:
            return None
        time.sleep(0.002)
        self.frame_id += 1
        if after_frame_id is not None and self.frame_id <= after_frame_id:
            self.frame_id = after_frame_id + 1
        return CapturedFrame(
            frame_id=self.frame_id,
            captured_at=time.monotonic(),
            image=np.full((4, 6, 3), self.value, dtype=np.uint8),
        )

    def close(self) -> None:
        self.started = False


def test_switchable_camera_keeps_global_frame_ids_monotonic() -> None:
    lenovo = _FakeCameraSource(10)
    pocket = _FakeCameraSource(20)
    source = SwitchableCameraSource(
        {"lenovo": lenovo, "pocket3": pocket},
        default_source="lenovo",
    )

    source.start()
    first = source.latest(timeout_seconds=0.2)
    assert first is not None
    assert source.active_source_name == "lenovo"
    assert int(first.image[0, 0, 0]) == 10

    source.switch("pocket3")
    second = source.latest(after_frame_id=first.frame_id, timeout_seconds=0.2)
    source.close()

    assert second is not None
    assert second.frame_id > first.frame_id
    assert int(second.image[0, 0, 0]) == 20
    assert not lenovo.started
    assert not pocket.started


def test_switchable_camera_rolls_back_when_next_source_fails() -> None:
    lenovo = _FakeCameraSource(10)

    class _FailingCameraSource(_FakeCameraSource):
        def start(self) -> None:
            raise RuntimeError("device unavailable")

    pocket = _FailingCameraSource(20)
    source = SwitchableCameraSource(
        {"lenovo": lenovo, "pocket3": pocket},
        default_source="lenovo",
    )

    source.start()
    with pytest.raises(RuntimeError, match="restored 'lenovo'"):
        source.switch("pocket3")

    assert source.active_source_name == "lenovo"
    assert lenovo.started
    source.close()
