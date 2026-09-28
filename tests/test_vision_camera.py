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

    def isOpened(self) -> bool:
        return self.opened

    def read(self):
        self.read_count += 1
        if self.fail_first_read and self.read_count == 1:
            return False, None
        time.sleep(0.005)
        value = self.read_count % 255
        return True, np.full((4, 6, 3), value, dtype=np.uint8)

    def release(self) -> None:
        self.released = True


def test_config_defaults_to_owner_accepted_lenovo_profile() -> None:
    config = OpenCVCameraConfig()

    assert config.backend == "dshow"
    assert config.width == 1920
    assert config.height == 1080
    assert config.fps == pytest.approx(30.0)
    assert config.fourcc == "MJPG"


def test_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        OpenCVCameraConfig(device_index=-1)
    with pytest.raises(ValueError):
        OpenCVCameraConfig(width=0)
    with pytest.raises(ValueError):
        OpenCVCameraConfig(fps=0)
    with pytest.raises(ValueError):
        OpenCVCameraConfig(fourcc="MJPEG")
    with pytest.raises(ValueError):
        OpenCVCameraConfig(backend="unknown")


def test_camera_opens_with_mjpeg_parameters_and_latest_frame() -> None:
    created: list[tuple[int, int, list[int]]] = []
    fake = FakeCapture()

    def factory(index: int, backend: int, params: list[int]):
        created.append((index, backend, params))
        return fake

    source = OpenCVCameraSource(capture_factory=factory)
    source.start()
    first = source.latest()
    assert first is not None

    newer = source.latest(after_frame_id=first.frame_id, timeout_seconds=0.2)
    source.close()

    assert len(created) == 1
    index, backend, params = created[0]
    assert index == 0
    assert backend == cv2.CAP_DSHOW
    assert params == [
        cv2.CAP_PROP_FOURCC,
        cv2.VideoWriter_fourcc(*"MJPG"),
        cv2.CAP_PROP_FRAME_WIDTH,
        1920,
        cv2.CAP_PROP_FRAME_HEIGHT,
        1080,
        cv2.CAP_PROP_FPS,
        30,
    ]
    assert newer is not None
    assert newer.frame_id > first.frame_id
    assert newer.width == 6
    assert newer.height == 4
    assert fake.released


def test_camera_switch_keeps_frame_ids_monotonic() -> None:
    created: list[int] = []
    captures: list[FakeCapture] = []

    def factory(index: int, backend: int, params: list[int]):
        del backend, params
        created.append(index)
        capture = FakeCapture()
        captures.append(capture)
        return capture

    source = OpenCVCameraSource(capture_factory=factory)
    source.start()
    before = source.latest()
    assert before is not None

    source.switch(OpenCVCameraConfig(device_index=1, width=1280, height=720))
    after = source.latest(after_frame_id=before.frame_id, timeout_seconds=0.2)
    source.close()

    assert created == [0, 1]
    assert after is not None
    assert after.frame_id > before.frame_id
    assert all(capture.released for capture in captures)


def test_camera_switch_rolls_back_when_new_camera_cannot_open() -> None:
    created: list[int] = []
    captures: list[FakeCapture] = []

    def factory(index: int, backend: int, params: list[int]):
        del backend, params
        created.append(index)
        capture = FakeCapture(opened=index != 1)
        captures.append(capture)
        return capture

    source = OpenCVCameraSource(capture_factory=factory)
    source.start()

    with pytest.raises(RuntimeError, match="previous camera restored"):
        source.switch(OpenCVCameraConfig(device_index=1))

    assert source.running
    assert source.config.device_index == 0
    source.close()

    assert created == [0, 1, 0]
    assert all(capture.released for capture in captures)


def test_camera_open_failure_releases_handle() -> None:
    fake = FakeCapture(opened=False)
    source = OpenCVCameraSource(capture_factory=lambda index, backend, params: fake)

    with pytest.raises(RuntimeError, match="failed to open"):
        source.start()

    assert fake.released


def test_camera_initial_read_failure_releases_handle() -> None:
    fake = FakeCapture(fail_first_read=True)
    source = OpenCVCameraSource(capture_factory=lambda index, backend, params: fake)

    with pytest.raises(RuntimeError, match="did not provide a frame"):
        source.start()

    assert fake.released
