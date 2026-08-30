from __future__ import annotations

import cv2
import numpy as np
import pytest

from jarvis.identity.live_face_benchmark import (
    _SelectionState,
    _cosine_similarity,
    _crop_head,
    _face_rows,
    _select_center_face,
)
from jarvis.vision.framing import HeadFirstFramingPolicy
from jarvis.vision.head import HeadObservation
from jarvis.vision.models import BoundingBox, TargetState, Track


def test_crop_head_expands_and_clamps_normalized_bounds() -> None:
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    crop = _crop_head(
        image,
        BoundingBox(left=0.25, top=0.20, right=0.50, bottom=0.60),
        margin_fraction=0.20,
    )

    assert crop.left == 40
    assert crop.top == 12
    assert crop.image.shape == (56, 70, 3)


def test_face_rows_accepts_opencv_tuple_and_empty_result() -> None:
    face = np.arange(15, dtype=np.float32).reshape(1, 15)

    assert np.array_equal(_face_rows((1, face)), face)
    assert _face_rows((0, None)).shape == (0, 15)


def test_select_center_face_prefers_associated_crop_center() -> None:
    faces = np.array(
        [
            [2, 2, 20, 20, *([0] * 10), 0.99],
            [40, 40, 20, 20, *([0] * 10), 0.92],
        ],
        dtype=np.float32,
    )

    selected = _select_center_face(faces, width=100, height=100)

    assert float(selected[0]) == 40.0
    assert float(selected[-1]) == pytest.approx(0.92)


def test_cosine_similarity_requires_matching_nonzero_features() -> None:
    first = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
    second = np.array([[0.5, 0.0, 0.0]], dtype=np.float32)

    assert _cosine_similarity(first, second) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="feature shapes"):
        _cosine_similarity(first, np.ones((1, 2), dtype=np.float32))
    with pytest.raises(ValueError, match="norm"):
        _cosine_similarity(first, np.zeros_like(first))


def test_selection_state_allows_clicking_associated_head_region() -> None:
    track = Track(
        track_id=7,
        category="person",
        confidence=0.9,
        bounds=BoundingBox(0.10, 0.10, 0.90, 0.95),
        first_seen_at=1.0,
        last_seen_at=1.0,
    )
    head_bounds = BoundingBox(0.40, 0.15, 0.60, 0.40)
    state = _SelectionState()
    state.update(
        (track,),
        head_regions=((7, head_bounds),),
        width=100,
        height=100,
    )

    state.on_mouse(cv2.EVENT_LBUTTONDOWN, 50, 25, 0, None)

    assert state.clicked_track_id == 7


def test_canonical_framing_policy_exposes_same_associated_head() -> None:
    track = Track(
        track_id=7,
        category="person",
        confidence=0.9,
        bounds=BoundingBox(0.20, 0.10, 0.80, 0.90),
        first_seen_at=1.0,
        last_seen_at=1.0,
    )
    target = TargetState(track_id=7, track=track)
    expected = HeadObservation(
        confidence=0.95,
        bounds=BoundingBox(0.42, 0.14, 0.58, 0.34),
        frame_id=1,
        observed_at=1.0,
    )
    distractor = HeadObservation(
        confidence=0.99,
        bounds=BoundingBox(0.65, 0.50, 0.78, 0.68),
        frame_id=1,
        observed_at=1.0,
    )
    policy = HeadFirstFramingPolicy()

    associated = policy.associated_head(target, [distractor, expected])
    framing = policy.resolve(target, [distractor, expected])

    assert associated == expected
    assert framing is not None
    assert framing.source == "head"
    assert framing.track_id == 7
    assert framing.x == pytest.approx(expected.bounds.center_x)
    assert framing.y == pytest.approx(expected.bounds.center_y)
