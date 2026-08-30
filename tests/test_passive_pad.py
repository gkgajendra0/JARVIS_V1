from __future__ import annotations

import numpy as np
import pytest

from jarvis.identity.passive_pad import _probabilities, _scaled_face_crop
from jarvis.identity.passive_pad_benchmark import (
    _associate_face,
    _FaceBox,
    rolling_medians,
)


def test_probability_helper_preserves_probability_vector() -> None:
    values = _probabilities(np.asarray([[0.8, 0.2]], dtype=np.float32))

    assert values.tolist() == pytest.approx([0.8, 0.2])


def test_probability_helper_softmaxes_logits() -> None:
    values = _probabilities(np.asarray([[2.0, 0.0]], dtype=np.float32))

    assert float(values.sum()) == pytest.approx(1.0)
    assert values[0] > values[1]


def test_scaled_face_crop_stays_inside_source_image() -> None:
    image = np.zeros((100, 120, 3), dtype=np.uint8)

    crop = _scaled_face_crop(
        image,
        (0, 0, 30, 40),
        scale=4.0,
        output_size=(80, 80),
    )

    assert crop.shape == (80, 80, 3)


def test_face_association_prefers_overlap() -> None:
    previous = _FaceBox(100, 100, 200, 200, 0.95)
    candidates = [
        _FaceBox(110, 105, 210, 205, 0.92),
        _FaceBox(500, 300, 600, 400, 0.99),
    ]

    selected = _associate_face(
        previous,
        candidates,
        frame_width=1280,
        frame_height=720,
    )

    assert selected == candidates[0]


def test_face_association_rejects_distant_replacement() -> None:
    previous = _FaceBox(100, 100, 200, 200, 0.95)
    candidates = [_FaceBox(1000, 500, 1100, 600, 0.99)]

    selected = _associate_face(
        previous,
        candidates,
        frame_width=1280,
        frame_height=720,
    )

    assert selected is None


def test_rolling_medians_require_complete_window() -> None:
    assert rolling_medians([0.1, 0.2, 0.9, 0.8], 5) == []
    assert rolling_medians([0.1, 0.2, 0.9, 0.8, 0.7], 5) == [0.7]


def test_rolling_median_window_must_be_positive() -> None:
    with pytest.raises(ValueError):
        rolling_medians([0.5], 0)
