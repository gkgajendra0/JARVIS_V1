from __future__ import annotations

import math

import numpy as np
import pytest

from jarvis.identity.calibration import (
    CalibrationStatus,
    derive_face_calibration,
)


def _unit_feature(angle_radians: float) -> np.ndarray:
    return np.asarray(
        [[math.cos(angle_radians), math.sin(angle_radians), 0.0]],
        dtype=np.float32,
    )


def test_calibration_derives_separated_candidate_band() -> None:
    owner = [
        _unit_feature(-0.12 + (0.24 * index / 129))
        for index in range(130)
    ]
    non_owner = [
        _unit_feature(1.25 + (0.20 * index / 129))
        for index in range(130)
    ]

    result = derive_face_calibration(owner, non_owner, minimum_samples=120)

    assert result.status is CalibrationStatus.CANDIDATE_READY
    assert result.accept_threshold > result.reject_threshold
    assert result.ambiguity_width > 0
    assert result.owner_reference_count == 65
    assert result.owner_probe_count == 65
    assert result.non_owner_count == 130
    assert result.owner_point_accept_rate >= 0.90
    assert result.non_owner_point_false_accept_rate == pytest.approx(0.0)
    assert result.owner_window_accept_rate >= 0.90
    assert result.non_owner_window_false_accept_rate == pytest.approx(0.0)


def test_calibration_fails_closed_when_positive_and_negative_overlap() -> None:
    owner = [
        _unit_feature(-0.08 + (0.16 * index / 129))
        for index in range(130)
    ]
    non_owner = [
        _unit_feature(-0.06 + (0.12 * index / 129))
        for index in range(130)
    ]

    result = derive_face_calibration(owner, non_owner, minimum_samples=120)

    assert result.status is CalibrationStatus.INSUFFICIENT_SEPARATION
    assert result.accept_threshold <= result.reject_threshold
    assert result.ambiguity_width <= 0


def test_calibration_rejects_insufficient_subject_samples() -> None:
    owner = [_unit_feature(0.0) for _ in range(119)]
    non_owner = [_unit_feature(1.2) for _ in range(130)]

    with pytest.raises(ValueError, match="OWNER calibration needs at least 120"):
        derive_face_calibration(owner, non_owner, minimum_samples=120)

    with pytest.raises(ValueError, match="non-owner calibration needs at least 120"):
        derive_face_calibration(non_owner, owner, minimum_samples=120)


def test_calibration_rejects_invalid_feature_vectors() -> None:
    owner = [_unit_feature(0.0) for _ in range(130)]
    non_owner = [_unit_feature(1.2) for _ in range(130)]
    owner[10] = np.zeros((1, 3), dtype=np.float32)

    with pytest.raises(ValueError, match="feature norm must be positive"):
        derive_face_calibration(owner, non_owner, minimum_samples=120)
