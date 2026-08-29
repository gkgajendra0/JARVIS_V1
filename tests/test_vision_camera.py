import time

import cv2
import numpy as np
import pytest

from jarvis.vision.camera import OpenCVCameraConfig, OpenCVCameraSource


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
