from __future__ import annotations

import math

import numpy as np
import pytest

from jarvis.identity.owner_calibration import (
    OwnerCalibrationStatus,
    derive_owner_only_calibration,
)


def _unit_feature(angle_radians: float) -> np.ndarray:
    return np.asarray(
        [[math.cos(angle_radians), math.sin(angle_radians), 0.0]],
        dtype=np.float32,
    )


def test_owner_only_calibration_accepts_stable_positive_baseline() -> None:
    owner = [_unit_feature(-0.12 + (0.24 * index / 129)) for index in range(130)]

    result = derive_owner_only_calibration(owner, minimum_samples=120)

    assert result.status is OwnerCalibrationStatus.READY_FOR_ENROLLMENT
    assert result.owner_reference_count == 65
    assert result.owner_probe_count == 65
    assert result.owner_scores.p05 >= 0.70
    assert result.provisional_accept_floor == pytest.approx(result.owner_scores.p05)
    assert result.owner_point_accept_rate >= 0.90
    assert result.owner_window_accept_rate >= 0.90


def test_owner_only_calibration_fails_closed_for_unstable_positive_baseline() -> None:
    owner = []
    for index in range(130):
        owner.append(_unit_feature(0.0 if index % 2 == 0 else 1.2))

    result = derive_owner_only_calibration(owner, minimum_samples=120)

    assert result.status is OwnerCalibrationStatus.UNSTABLE_OWNER_BASELINE
    assert result.provisional_accept_floor < 0.70


def test_owner_only_calibration_rejects_insufficient_samples() -> None:
    owner = [_unit_feature(0.0) for _ in range(119)]

    with pytest.raises(ValueError, match="OWNER calibration needs at least 120"):
        derive_owner_only_calibration(owner, minimum_samples=120)
